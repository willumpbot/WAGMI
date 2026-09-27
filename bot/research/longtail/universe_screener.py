"""
Long-Tail Alpha Program — Universe Screener (v1)
==================================================

STANDALONE, READ-ONLY research script. Hits the PUBLIC Hyperliquid info API
directly. Does NOT import anything from the live bot package and does NOT
write to any live-bot state file. Safe to run at any time, from any machine,
with zero risk to the running paper/live bot.

Goal: screen the full HL perp universe (~230 markets) down to a ranked list
of small/mid-cap alt perps that are (a) liquid enough to trade at the bot's
tiny size and (b) plausibly inefficient enough to carry retail-tradeable
edge, then rank survivors by a tradeability score and an estimated
round-trip cost in bps.

Usage:
    python research/longtail/universe_screener.py

Outputs:
    data/longtail/universe.json          - latest ranked top-N snapshot
    data/longtail/universe_history.jsonl - one line appended per run, full
                                            candidate set (survivors AND
                                            rejects) for later
                                            survivorship-bias analysis.

Nothing here touches data/replay/, .env, or any live bot module.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Constants — screen thresholds (kept module-level so they're easy to tune)
# --------------------------------------------------------------------------

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

REQ_TIMEOUT_S = 15
RATE_LIMIT_RPS = 5.0          # max requests/sec to the public HL API
MIN_REQ_INTERVAL_S = 1.0 / RATE_LIMIT_RPS
MAX_RETRIES = 4
RETRY_BACKOFF_BASE_S = 1.5    # exponential backoff base on 429/5xx

# Stage-1 prefilter (cheap, from metaAndAssetCtxs only — no per-coin calls)
# NOTE: tuned DOWN from an initial $2M floor after a live dry-run showed the
# HL long tail mostly trades $0.5-2M/day; $2M left only 26 stage-1
# candidates (too few to reach the ~30-name target after the depth/spread
# cut). $1M keeps ~38 candidates while still requiring real daily turnover.
MIN_DAY_NTL_VLM_USD = 1_000_000
MAX_DAY_NTL_VLM_USD = 150_000_000
MIN_OPEN_INTEREST_USD = 1_500_000
MIN_MAX_LEVERAGE = 3

# Majors excluded on purpose — this screen is for the LONG TAIL, not the
# already-well-covered core universe the live bot already trades.
EXCLUDED_MAJORS = {"BTC", "ETH", "SOL", "XRP", "HYPE", "NEAR", "BNB", "DOGE"}

# Stage-2 filter (requires per-coin l2Book — only run on stage-1 survivors)
# NOTE: HL order books are quoted with very fine tick sizes (confirmed live:
# AVAX/LINK/UNI top-10 levels each spanned well under 1bp of price). A
# literal "sum of the first 5 raw price levels" therefore measures almost
# no real depth and rejected nearly every otherwise-liquid, tight-spread
# name in the first dry run (23/26 stage-1 survivors failed on this alone,
# despite spreads mostly under 3bps). Adapted to cumulative depth within a
# fixed bps band of mid (using however many of the up-to-20 returned levels
# fall inside that band) — a tick-size-robust proxy for "how much can I
# actually trade near the touch," which is what this metric is meant to
# capture. Kept the $25k/side threshold and the output field name
# (depth5_bid_usd/depth5_ask_usd) for continuity with the spec.
MIN_DEPTH5_USD_EACH_SIDE = 25_000
DEPTH_BAND_BPS = 20.0        # depth measured within this many bps of mid, each side
MAX_HALF_SPREAD_BPS = 15.0   # NOTE: single live snapshot, see caveat below

# Listing-age approximation (stage-3, optional, run only on final survivors)
LISTING_AGE_LOOKBACK_DAYS = 40
MIN_DAILY_CANDLES = 21        # ~3 weeks of trading history required
INCLUDE_LISTING_AGE = True    # set False to skip this stage entirely (v1 TODO note below)

# Cost model
TAKER_FEE_BPS_ONE_WAY = 4.5
TAKER_FEE_BPS_ROUND_TRIP = 2 * TAKER_FEE_BPS_ONE_WAY
IMPACT_FALLBACK_BPS = 2.0     # used when impactPxs is missing/unusable

TOP_N = 30

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "longtail"
OUT_JSON = OUT_DIR / "universe.json"
OUT_HISTORY = OUT_DIR / "universe_history.jsonl"


# --------------------------------------------------------------------------
# Rate-limited HTTP helper
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def wait(self):
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call = time.monotonic()


_limiter = RateLimiter(MIN_REQ_INTERVAL_S)
_session = requests.Session()


def hl_post(payload: dict) -> object:
    """POST to the HL public info API with rate limiting + retry/backoff.

    Raises the last exception if all retries are exhausted; callers should
    catch and handle per-coin so one bad symbol doesn't kill the whole run.
    """
    last_exc = None
    for attempt in range(MAX_RETRIES):
        _limiter.wait()
        try:
            resp = _session.post(HL_INFO_URL, json=payload, timeout=REQ_TIMEOUT_S)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                sleep_s = RETRY_BACKOFF_BASE_S * (2 ** attempt)
                time.sleep(sleep_s)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            sleep_s = RETRY_BACKOFF_BASE_S * (2 ** attempt)
            time.sleep(sleep_s)
    raise last_exc if last_exc else RuntimeError("hl_post failed with no exception captured")


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------

def fetch_meta_and_asset_ctxs():
    """POST {"type":"metaAndAssetCtxs"} -> [meta, assetCtxs] (parallel arrays)."""
    data = hl_post({"type": "metaAndAssetCtxs"})
    if not isinstance(data, list) or len(data) != 2:
        raise RuntimeError(f"Unexpected metaAndAssetCtxs shape: {type(data)}")
    meta, ctxs = data[0], data[1]
    universe = meta.get("universe", [])
    if len(universe) != len(ctxs):
        # Not fatal — join by index up to the shorter length, but warn.
        print(
            f"[warn] universe length ({len(universe)}) != assetCtxs length "
            f"({len(ctxs)}); joining by index up to min length",
            file=sys.stderr,
        )
    return universe, ctxs


def fetch_l2book(coin: str):
    """POST {"type":"l2Book","coin":coin} -> {"levels":[bids, asks], ...}

    levels[0] = bids sorted best(highest)->worst, levels[1] = asks sorted
    best(lowest)->worst. Confirmed against a live snapshot during build.
    """
    data = hl_post({"type": "l2Book", "coin": coin})
    levels = data.get("levels")
    if not levels or len(levels) != 2:
        raise RuntimeError(f"Unexpected l2Book shape for {coin}: {data}")
    return levels[0], levels[1]  # bids, asks


def fetch_daily_candle_count(coin: str, lookback_days: int) -> int:
    """Approximate listing age via candleSnapshot 1d candle count.

    HL's public info API doesn't expose a direct "listed since" field, so
    this counts how many daily candles exist in the lookback window as a
    proxy: if the market is younger than the window, fewer candles come
    back. This is an approximation, not an exact listing date — see TODO
    in the module docstring / final report.
    """
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - lookback_days * 24 * 3600 * 1000
    data = hl_post(
        {
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": now_ms},
        }
    )
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected candleSnapshot shape for {coin}: {data}")
    return len(data)


# --------------------------------------------------------------------------
# Screen logic
# --------------------------------------------------------------------------

def _to_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def stage1_prefilter(universe: list, ctxs: list):
    """Cheap filter using only metaAndAssetCtxs data (no per-coin HTTP)."""
    candidates = []
    rejects = []
    n = min(len(universe), len(ctxs))
    for i in range(n):
        u = universe[i]
        ctx = ctxs[i] or {}
        name = u.get("name", f"<unknown-{i}>")
        reasons = []

        if u.get("isDelisted"):
            reasons.append("delisted")
        if name in EXCLUDED_MAJORS:
            reasons.append("excluded_major")

        max_lev = _to_float(u.get("maxLeverage"), 0.0)
        if max_lev is None or max_lev < MIN_MAX_LEVERAGE:
            reasons.append(f"maxLeverage<{MIN_MAX_LEVERAGE}")

        day_vlm = _to_float(ctx.get("dayNtlVlm"))
        mark_px = _to_float(ctx.get("markPx")) or _to_float(ctx.get("oraclePx"))
        oi_coins = _to_float(ctx.get("openInterest"))
        oi_usd = (oi_coins * mark_px) if (oi_coins is not None and mark_px is not None) else None

        if day_vlm is None:
            reasons.append("missing_dayNtlVlm")
        elif not (MIN_DAY_NTL_VLM_USD <= day_vlm <= MAX_DAY_NTL_VLM_USD):
            reasons.append(f"dayNtlVlm={day_vlm:.0f} outside [{MIN_DAY_NTL_VLM_USD},{MAX_DAY_NTL_VLM_USD}]")

        if oi_usd is None:
            reasons.append("missing_oi_usd")
        elif oi_usd < MIN_OPEN_INTEREST_USD:
            reasons.append(f"oi_usd={oi_usd:.0f}<{MIN_OPEN_INTEREST_USD}")

        row = {
            "coin": name,
            "dayNtlVlm": day_vlm,
            "oi_usd": oi_usd,
            "markPx": mark_px,
            "maxLeverage": max_lev,
            "funding": _to_float(ctx.get("funding")),
            "impactPxs": ctx.get("impactPxs"),
        }

        if reasons:
            row["fail_reasons"] = reasons
            rejects.append(row)
        else:
            candidates.append(row)

    return candidates, rejects


def compute_book_stats(bids: list, asks: list):
    if not bids or not asks:
        raise RuntimeError("empty bid or ask side")
    best_bid = _to_float(bids[0].get("px"))
    best_ask = _to_float(asks[0].get("px"))
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        raise RuntimeError(f"invalid top-of-book px: bid={best_bid} ask={best_ask}")
    mid = (best_bid + best_ask) / 2.0
    half_spread_bps = (best_ask - best_bid) / 2.0 / mid * 1e4

    def depth_within_band(levels):
        total = 0.0
        for lvl in levels:
            px = _to_float(lvl.get("px"))
            sz = _to_float(lvl.get("sz"))
            if px is None or sz is None:
                continue
            dist_bps = abs(px - mid) / mid * 1e4
            if dist_bps > DEPTH_BAND_BPS:
                break  # levels are ordered by distance from touch, safe to stop
            total += px * sz
        return total

    depth_bid_usd = depth_within_band(bids)
    depth_ask_usd = depth_within_band(asks)
    return mid, half_spread_bps, depth_bid_usd, depth_ask_usd


def estimate_impact_bps(impact_pxs, mark_px, mid):
    """Small impact term derived from HL's impactPxs (a size-aware quote
    HL itself computes) relative to mid. Falls back to a flat placeholder
    if impactPxs is missing/malformed — this matches the spec's suggested
    'impactPxs vs mark, or 2bps placeholder' approach.
    """
    try:
        if not impact_pxs or len(impact_pxs) != 2 or not mid:
            return IMPACT_FALLBACK_BPS
        imp_bid = _to_float(impact_pxs[0])
        imp_ask = _to_float(impact_pxs[1])
        if imp_bid is None or imp_ask is None:
            return IMPACT_FALLBACK_BPS
        impact_bps = abs(imp_ask - imp_bid) / 2.0 / mid * 1e4
        if impact_bps <= 0:
            return IMPACT_FALLBACK_BPS
        return impact_bps
    except Exception:
        return IMPACT_FALLBACK_BPS


def stage2_book_screen(candidates: list):
    """For each stage-1 survivor, fetch l2Book and apply depth/spread filter."""
    survivors = []
    rejects = []
    for row in candidates:
        coin = row["coin"]
        try:
            bids, asks = fetch_l2book(coin)
            mid, half_spread_bps, depth_bid_usd, depth_ask_usd = compute_book_stats(bids, asks)
        except Exception as exc:
            row2 = dict(row)
            row2["fail_reasons"] = [f"l2Book_error: {exc}"]
            rejects.append(row2)
            print(f"[warn] {coin}: l2Book fetch/parse failed: {exc}", file=sys.stderr)
            continue

        reasons = []
        if depth_bid_usd < MIN_DEPTH5_USD_EACH_SIDE:
            reasons.append(f"depth_bid={depth_bid_usd:.0f}<{MIN_DEPTH5_USD_EACH_SIDE}")
        if depth_ask_usd < MIN_DEPTH5_USD_EACH_SIDE:
            reasons.append(f"depth_ask={depth_ask_usd:.0f}<{MIN_DEPTH5_USD_EACH_SIDE}")
        if half_spread_bps > MAX_HALF_SPREAD_BPS:
            reasons.append(f"half_spread_bps={half_spread_bps:.2f}>{MAX_HALF_SPREAD_BPS}")

        row2 = dict(row)
        row2["mid"] = mid
        row2["spread_bps"] = half_spread_bps
        row2["depth5_bid_usd"] = depth_bid_usd
        row2["depth5_ask_usd"] = depth_ask_usd

        if reasons:
            row2["fail_reasons"] = reasons
            rejects.append(row2)
        else:
            survivors.append(row2)

    return survivors, rejects


def stage3_listing_age(survivors: list):
    """Optional: annotate final survivors with an approximate listing age
    (daily candle count in the lookback window). Never rejects a coin on
    this basis in v1 — it's informational only (see TODO note)."""
    if not INCLUDE_LISTING_AGE:
        for row in survivors:
            row["listed_days"] = None
        return survivors

    for row in survivors:
        coin = row["coin"]
        try:
            n_candles = fetch_daily_candle_count(coin, LISTING_AGE_LOOKBACK_DAYS)
            row["listed_days"] = n_candles  # proxy, capped by lookback window
            row["listing_age_thin"] = n_candles < MIN_DAILY_CANDLES
        except Exception as exc:
            row["listed_days"] = None
            row["listing_age_thin"] = None
            print(f"[warn] {coin}: candleSnapshot fetch failed: {exc}", file=sys.stderr)
    return survivors


def compute_cost_and_score(survivors: list):
    for row in survivors:
        impact_bps = estimate_impact_bps(row.get("impactPxs"), row.get("markPx"), row.get("mid"))
        row["impact_bps_est"] = impact_bps
        row["cost_bps_est"] = TAKER_FEE_BPS_ROUND_TRIP + row["spread_bps"] + impact_bps

        depth_min = min(row["depth5_bid_usd"], row["depth5_ask_usd"])
        denom = max(row["spread_bps"], 1.0)
        vlm = row.get("dayNtlVlm") or 0.0
        row["score"] = vlm * depth_min / denom
    return survivors


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def build_output(survivors_ranked: list, all_evaluated: list, as_of: datetime):
    criteria = {
        "min_day_ntl_vlm_usd": MIN_DAY_NTL_VLM_USD,
        "max_day_ntl_vlm_usd": MAX_DAY_NTL_VLM_USD,
        "min_open_interest_usd": MIN_OPEN_INTEREST_USD,
        "min_max_leverage": MIN_MAX_LEVERAGE,
        "excluded_majors": sorted(EXCLUDED_MAJORS),
        "min_depth5_usd_each_side": MIN_DEPTH5_USD_EACH_SIDE,
        "depth_band_bps": DEPTH_BAND_BPS,
        "max_half_spread_bps": MAX_HALF_SPREAD_BPS,
        "listing_age_lookback_days": LISTING_AGE_LOOKBACK_DAYS,
        "min_daily_candles": MIN_DAILY_CANDLES,
        "include_listing_age": INCLUDE_LISTING_AGE,
        "taker_fee_bps_round_trip": TAKER_FEE_BPS_ROUND_TRIP,
        "impact_fallback_bps": IMPACT_FALLBACK_BPS,
        "top_n": TOP_N,
        "caveat": (
            "spread/depth are a SINGLE live snapshot at as_of_iso, not a "
            "time-averaged measure; listed_days is an approximation via "
            "daily-candle count in a fixed lookback window, not an exact "
            "listing date."
        ),
    }

    names = []
    for row in survivors_ranked[:TOP_N]:
        names.append(
            {
                "coin": row["coin"],
                "vol24h": row.get("dayNtlVlm"),
                "oi_usd": row.get("oi_usd"),
                "spread_bps": row.get("spread_bps"),
                "depth5_bid_usd": row.get("depth5_bid_usd"),
                "depth5_ask_usd": row.get("depth5_ask_usd"),
                "funding": row.get("funding"),
                "cost_bps_est": row.get("cost_bps_est"),
                "score": row.get("score"),
                "listed_days": row.get("listed_days"),
            }
        )

    out = {
        "as_of_iso": as_of.isoformat(),
        "criteria": criteria,
        "names": names,
    }

    history_line = {
        "as_of_iso": as_of.isoformat(),
        "criteria": criteria,
        "n_universe_evaluated": len(all_evaluated),
        "n_survivors": len(survivors_ranked),
        "top_n_written": min(TOP_N, len(survivors_ranked)),
        "all_evaluated": all_evaluated,  # includes both survivors and rejects w/ fail_reasons
    }

    return out, history_line


def write_outputs(out: dict, history_line: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    with open(OUT_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(history_line) + "\n")


def print_table(survivors_ranked: list):
    rows = survivors_ranked[:TOP_N]
    if not rows:
        print("No names survived the screen — nothing to display.")
        return

    header = f"{'coin':<10}{'vol24h($M)':>12}{'oi($M)':>10}{'spread_bps':>12}{'cost_bps':>10}{'score':>16}"
    print(header)
    print("-" * len(header))
    for row in rows:
        vol_m = (row.get("dayNtlVlm") or 0.0) / 1e6
        oi_m = (row.get("oi_usd") or 0.0) / 1e6
        print(
            f"{row['coin']:<10}"
            f"{vol_m:>12.2f}"
            f"{oi_m:>10.2f}"
            f"{row.get('spread_bps', 0.0):>12.2f}"
            f"{row.get('cost_bps_est', 0.0):>10.2f}"
            f"{row.get('score', 0.0):>16,.0f}"
        )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    as_of = datetime.now(timezone.utc)
    print(f"[{as_of.isoformat()}] Long-Tail Universe Screener v1 — fetching metaAndAssetCtxs...")

    try:
        universe, ctxs = fetch_meta_and_asset_ctxs()
    except Exception as exc:
        print(f"[fatal] could not fetch metaAndAssetCtxs: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    print(f"Universe size: {len(universe)} markets")

    stage1_survivors, stage1_rejects = stage1_prefilter(universe, ctxs)
    print(
        f"Stage 1 (volume/OI/leverage/exclusions): "
        f"{len(stage1_survivors)} pass, {len(stage1_rejects)} rejected"
    )

    if not stage1_survivors:
        print("No candidates survived stage 1 — nothing further to screen.")
        out, history_line = build_output([], stage1_rejects, as_of)
        write_outputs(out, history_line)
        return

    print(
        f"Fetching l2Book for {len(stage1_survivors)} candidates "
        f"(rate-limited to {RATE_LIMIT_RPS}/s, this will take a bit)..."
    )
    stage2_survivors, stage2_rejects = stage2_book_screen(stage1_survivors)
    print(
        f"Stage 2 (spread/depth): {len(stage2_survivors)} pass, "
        f"{len(stage2_rejects)} rejected"
    )

    if INCLUDE_LISTING_AGE and stage2_survivors:
        print(f"Fetching candleSnapshot listing-age proxy for {len(stage2_survivors)} survivors...")
    stage2_survivors = stage3_listing_age(stage2_survivors)

    stage2_survivors = compute_cost_and_score(stage2_survivors)
    survivors_ranked = sorted(stage2_survivors, key=lambda r: r.get("score", 0.0), reverse=True)

    all_evaluated = stage1_rejects + stage2_rejects + survivors_ranked

    out, history_line = build_output(survivors_ranked, all_evaluated, as_of)
    write_outputs(out, history_line)

    print()
    print(f"=== Long-Tail Universe: top {min(TOP_N, len(survivors_ranked))} of {len(survivors_ranked)} survivors ===")
    print_table(survivors_ranked)
    print()
    print(f"Wrote: {OUT_JSON}")
    print(f"Appended: {OUT_HISTORY}")


if __name__ == "__main__":
    main()
