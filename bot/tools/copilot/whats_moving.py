#!/usr/bin/env python
"""
WAGMI Co-Pilot - What's-Moving Scanner - whats_moving.py  (Theme E)
=============================================================================
Coin-SELECTION help over the FULL Hyperliquid perp universe (~230 markets).
Being in the right meme EARLY is where meme profit is actually made - this
tool's whole job is narrowing ~230 perps down to the handful worth a human
looking at right now.

CRITICAL FRAMING - READ THIS BEFORE TOUCHING THE SCORING
-----------------------------------------------------------------------------
This is a RADAR, not a SIGNAL. It finds ATTENTION / MOVEMENT (volume
surging, price breaking out, OI building), never EDGE or DIRECTION. This
codebase already ran the experiment: TAILWIND-style momentum-as-a-gate was
built and REFUTED on an entry-time-safe re-audit (see
project_edge_instruments_2026-07-27 - 70.6%->50% win rate, p=0.17, n=2 OOS).
Autonomous prediction from exactly these kinds of features does not hold up.
So this tool makes NO "buy this" claim, ever, and never will. Every line
reads as a due-diligence PROMPT ("worth a look, here's the risk"), not a
trade call. A parabolic, low-OI meme topping the raw momentum list is
EXACTLY the thing to flag as DANGER (late / thin / rug-risk), not
opportunity - that flag IS the product, not a caveat bolted onto it.

STANDALONE, READ-ONLY w.r.t. the live bot, same constraints as copilot.py /
copilot_alerts.py:
  - Only imports data/fetchers/hl_native.py (HLNative) and, in --alert mode,
    tools/discord_notify.py's send_discord(). No llm/execution/core/
    strategies imports. Never touches live/.env/data/replay.
  - Its own persistent state lives at data/copilot/moving_state.json - a
    new, isolated file this tool owns; it never reads/writes
    alert_state.json or any other copilot/live-bot state file.
  - Does NOT import copilot.py or copilot_alerts.py, and neither of those
    files imports this one - fully independent script. This is a universe
    SCREEN (breadth), not a per-symbol deep-dive (depth); deliberately kept
    decoupled from the existing per-symbol dip/liquidation tool.

WHY metaAndAssetCtxs INSTEAD OF HLNative.meta()
-----------------------------------------------------------------------------
HLNative.meta() (POST {"type":"meta"}) only returns the static per-asset
universe row (maxLeverage, szDecimals, marginTableId) - no price, volume,
OI, or funding. The per-asset market data this scanner needs (dayNtlVlm,
openInterest, funding, markPx, prevDayPx) only comes back from
POST {"type":"metaAndAssetCtxs"}, which HLNative doesn't expose a public
method for. Rather than duplicate HLNative's rate-limiter/retry/backoff HTTP
plumbing in a second copy (the way research/longtail/universe_screener.py's
standalone hl_post does), this module reuses an HLNative instance's own
`_post()` - same rate limit, same retry/backoff, same fail-soft behavior,
one fewer HTTP client in the codebase. `_post` is "private" by convention
only; this is same-repo, read-only, single-process use, not a stability
contract violation.

TWO-STAGE PIPELINE (mirrors research/longtail/universe_screener.py's
cheap-prefilter-then-per-coin-calls shape, adapted for full-universe speed)
-----------------------------------------------------------------------------
Stage 1 (one HTTP call, all ~230 coins): metaAndAssetCtxs gives markPx,
prevDayPx, dayNtlVlm, openInterest, funding, maxLeverage for the ENTIRE
universe at once. The LIQUIDITY / QUALITY FLOOR (see MIN_* constants) is
applied here - this is the actual product: per the owner's framing, most of
a raw momentum list is noise or rugs, and the floor is what keeps that noise
off the list, before any ranking happens.

Stage 2 (per-coin candle calls, rate-limited ~5 req/s): fetching 1h/4h ROC
and a volume/range baseline needs per-coin candle history, which does not
scale to all ~230 survivors in reasonable time. So Stage 1 survivors are
CHEAP-RANKED by |24h%| alone and only the top CANDLE_STAGE_POOL (default 40)
go through Stage 2 candle enrichment. KNOWN LIMITATION: a coin with a huge
4h move but a flat/net-zero 24h number (e.g. pumped then round-tripped) can
be cheap-ranked out of the Stage-2 pool and missed. Documented in the TODO
at the bottom of this file - not solved here to keep runtime bounded.

CLI:
    python tools/copilot/whats_moving.py                    # print top-N table (default N=10)
    python tools/copilot/whats_moving.py --top 15
    python tools/copilot/whats_moving.py --watch POPCAT,SOL,BTC,MOG
    python tools/copilot/whats_moving.py --alert             # Discord ping on NEW top-decile entrants only (cooldown, dedup)
    python tools/copilot/whats_moving.py --alert --dry-run   # show what --alert WOULD push; no Discord call, no state write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
FETCHERS_DIR = os.path.join(BOT_DIR, "data", "fetchers")

STATE_DIR = os.path.join(BOT_DIR, "data", "copilot")
STATE_PATH = os.path.join(STATE_DIR, "moving_state.json")

# ---------------------------------------------------------------------------
# LIQUIDITY / QUALITY FLOOR - the actual product. Module-level constants so
# they're the obvious place to tune. Survivors of this floor are the ONLY
# candidates ranking ever sees - noise/rugs are excluded before scoring, not
# down-weighted after.
# ---------------------------------------------------------------------------
MIN_24H_VOLUME_USD = 2_000_000     # dayNtlVlm floor - below this, too thin to trade meaningfully
MIN_OI_USD = 1_000_000             # openInterest * markPx floor - below this, no real skin in the game
LOW_OI_MULTIPLE = 2.0              # OI < this x the floor -> "thin" annotation even though it passed

# Stage-2 candle enrichment pool size (per-coin HTTP calls; rate-limited)
CANDLE_STAGE_POOL = 40

# Baseline / range lookback for volume-surge + distance-from-range
BASELINE_LOOKBACK_DAYS = 20
MIN_BASELINE_DAYS = 5               # below this many daily candles, baseline is "n/a" not fabricated

# Composite score bounds (keep one outlier from dominating the whole table)
VOL_SURGE_CAP = 15.0
OI_CONFIRM_MIN_MULT = 0.7
OI_CONFIRM_MAX_MULT = 1.5

# Honest-annotation thresholds (due-diligence prompts, NOT signals)
PARABOLIC_24H_PCT = 40.0            # abs 24h% at/above this...
PARABOLIC_RANGE_POS_PCT = 90.0      # ...AND sitting in the top/bottom of its own range -> "likely late"
HIGH_FUNDING_DAILY_PCT = 0.5        # abs funding, annualized-to-daily, at/above this -> "crowded"

TOP_N_DEFAULT = 10
ALERT_DECILE_FRACTION = 0.10
DEFAULT_COOLDOWN_HOURS = 6.0
DEFAULT_WATCH = ["POPCAT", "SOL", "BTC"]  # owner's coins (copilot.py's DEFAULT_SYMBOLS)

FUNDING_PAYMENTS_PER_DAY = 24  # HL pays funding hourly (confirmed in copilot.py) - rate*24 = daily %


# ---------------------------------------------------------------------------
# HL client (standalone, read-only - see module docstring for why _post)
# ---------------------------------------------------------------------------
def _get_hl_client():
    if FETCHERS_DIR not in sys.path:
        sys.path.insert(0, FETCHERS_DIR)
    from hl_native import HLNative  # standalone, read-only, no live-bot deps
    return HLNative()


def _f(x, default=None):
    try:
        v = float(x)
        return v if v == v else default  # filter NaN
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Stage 1: one call, full universe
# ---------------------------------------------------------------------------
def fetch_universe(client) -> List[Dict[str, Any]]:
    """metaAndAssetCtxs -> one merged row per coin. Fail-soft: returns []
    (never raises) if the call fails, so callers can print a clear error
    instead of a traceback."""
    data = client._post({"type": "metaAndAssetCtxs"})
    if not isinstance(data, list) or len(data) != 2:
        print(f"[whats_moving] metaAndAssetCtxs came back malformed: {type(data)}", file=sys.stderr)
        return []
    meta, ctxs = data[0], data[1]
    universe = (meta or {}).get("universe", [])
    n = min(len(universe), len(ctxs))
    if len(universe) != len(ctxs):
        print(f"[whats_moving] universe len ({len(universe)}) != ctx len ({len(ctxs)}) - joining by index up to {n}", file=sys.stderr)
    rows = []
    for i in range(n):
        a, c = universe[i], ctxs[i]
        if not isinstance(a, dict) or not isinstance(c, dict) or "name" not in a:
            continue
        rows.append({
            "symbol": a["name"],
            "max_leverage": _f(a.get("maxLeverage")),
            "mark_px": _f(c.get("markPx")),
            "prev_day_px": _f(c.get("prevDayPx")),
            "day_ntl_vlm": _f(c.get("dayNtlVlm")),
            "open_interest_base": _f(c.get("openInterest")),
            "funding_hourly": _f(c.get("funding")),
        })
    return rows


def apply_liquidity_floor(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """The actual product. Excludes anything below the tradeable floor
    BEFORE ranking ever sees it. Returns (survivors, rejection_reason_counts)."""
    survivors = []
    rejects: Dict[str, int] = {"no_price": 0, "below_volume_floor": 0, "below_oi_floor": 0}
    for r in rows:
        if not r["mark_px"] or r["mark_px"] <= 0 or not r["prev_day_px"] or r["prev_day_px"] <= 0:
            rejects["no_price"] += 1
            continue
        if not r["day_ntl_vlm"] or r["day_ntl_vlm"] < MIN_24H_VOLUME_USD:
            rejects["below_volume_floor"] += 1
            continue
        oi_usd = (r["open_interest_base"] or 0.0) * r["mark_px"]
        r["oi_usd"] = oi_usd
        if oi_usd < MIN_OI_USD:
            rejects["below_oi_floor"] += 1
            continue
        r["pct_24h"] = (r["mark_px"] - r["prev_day_px"]) / r["prev_day_px"] * 100.0
        survivors.append(r)
    return survivors, rejects


# ---------------------------------------------------------------------------
# Stage 2: per-coin candle enrichment (ROC, volume baseline, range position)
# ---------------------------------------------------------------------------
def _fetch_daily_and_hourly(client, symbol: str) -> Tuple[list, list]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day_start = now_ms - (BASELINE_LOOKBACK_DAYS + 2) * 24 * 3600 * 1000
    hour_start = now_ms - 8 * 3600 * 1000
    try:
        daily = client.candles(symbol, "1d", day_start, now_ms)
    except Exception as e:
        print(f"[whats_moving] {symbol} 1d candle fetch failed: {e}", file=sys.stderr)
        daily = []
    try:
        hourly = client.candles(symbol, "1h", hour_start, now_ms)
    except Exception as e:
        print(f"[whats_moving] {symbol} 1h candle fetch failed: {e}", file=sys.stderr)
        hourly = []
    return daily, hourly


def _roc(candles: list, periods_back: int) -> Optional[float]:
    if len(candles) <= periods_back:
        return None
    last_c = _f(candles[-1].get("c"))
    ref_c = _f(candles[-1 - periods_back].get("c"))
    if not last_c or not ref_c or ref_c == 0:
        return None
    return (last_c - ref_c) / ref_c * 100.0


def enrich_with_candles(client, row: Dict[str, Any]) -> None:
    """Mutates row in place: roc_1h, roc_4h, vol_ratio, range_pos_pct.
    Fail-soft - missing/thin data leaves fields None, never raises."""
    daily, hourly = _fetch_daily_and_hourly(client, row["symbol"])

    row["roc_1h"] = _roc(hourly, 1)
    row["roc_4h"] = _roc(hourly, 4)

    # Volume-vs-baseline: dayNtlVlm (live rolling 24h) vs the MEDIAN of
    # completed daily candles' notional volume (v * c). NOTE: dayNtlVlm is a
    # rolling window, not "today's calendar day" - comparing it to a
    # calendar-day median is an approximation, not exact like-for-like, but
    # it's the only baseline available without a dedicated volume-history
    # endpoint. Good enough for "surging vs typical", not precise multiples.
    completed = daily[:-1] if len(daily) >= 2 else []  # drop today's still-forming candle
    if len(completed) >= MIN_BASELINE_DAYS:
        daily_notionals = sorted(
            (_f(c.get("v")) or 0.0) * (_f(c.get("c")) or 0.0) for c in completed
        )
        median_vol = daily_notionals[len(daily_notionals) // 2]
        if median_vol > 0 and row.get("day_ntl_vlm"):
            row["vol_ratio"] = min(row["day_ntl_vlm"] / median_vol, VOL_SURGE_CAP)
        else:
            row["vol_ratio"] = None
    else:
        row["vol_ratio"] = None

    # Distance from recent range (0=at lookback low, 100=at lookback high)
    if len(daily) >= MIN_BASELINE_DAYS:
        highs = [_f(c.get("h")) for c in daily if _f(c.get("h")) is not None]
        lows = [_f(c.get("l")) for c in daily if _f(c.get("l")) is not None]
        if highs and lows:
            rng_hi, rng_lo = max(highs), min(lows)
            if rng_hi > rng_lo and row.get("mark_px") is not None:
                row["range_pos_pct"] = max(0.0, min(100.0, (row["mark_px"] - rng_lo) / (rng_hi - rng_lo) * 100.0))
            else:
                row["range_pos_pct"] = None
        else:
            row["range_pos_pct"] = None
    else:
        row["range_pos_pct"] = None


# ---------------------------------------------------------------------------
# Composite "attention" score: momentum x volume-surge x OI-confirmation
# ---------------------------------------------------------------------------
def compute_score(row: Dict[str, Any], oi_delta_pct: Optional[float]) -> float:
    momentum = abs(row.get("pct_24h") or 0.0)

    roc_1h, roc_4h, pct_24h = row.get("roc_1h"), row.get("roc_4h"), row.get("pct_24h")
    same_direction = (
        roc_1h is not None and roc_4h is not None and pct_24h is not None
        and (roc_1h >= 0) == (roc_4h >= 0) == (pct_24h >= 0)
    )
    momentum *= 1.25 if same_direction else 1.0

    vol_surge = row.get("vol_ratio")
    vol_factor = vol_surge if vol_surge else 1.0  # unknown baseline -> neutral, not zero (don't punish thin history)

    if oi_delta_pct is None:
        oi_factor = 1.0  # first observation - no history yet, neutral
    else:
        oi_factor = 1.0 + max(-0.3, min(0.5, oi_delta_pct / 100.0))
        oi_factor = max(OI_CONFIRM_MIN_MULT, min(OI_CONFIRM_MAX_MULT, oi_factor))

    return momentum * vol_factor * oi_factor


# ---------------------------------------------------------------------------
# Honest annotations - due-diligence prompts, never signals
# ---------------------------------------------------------------------------
def annotate(row: Dict[str, Any]) -> List[str]:
    flags = []
    pct_24h = row.get("pct_24h")
    range_pos = row.get("range_pos_pct")
    if pct_24h is not None and abs(pct_24h) >= PARABOLIC_24H_PCT and range_pos is not None and (
        range_pos >= PARABOLIC_RANGE_POS_PCT or range_pos <= (100 - PARABOLIC_RANGE_POS_PCT)
    ):
        flags.append("PARABOLIC - likely late")
    if row.get("oi_usd") is not None and row["oi_usd"] < LOW_OI_MULTIPLE * MIN_OI_USD:
        flags.append("low OI - thin/rug-risk")
    funding_hourly = row.get("funding_hourly")
    if funding_hourly is not None:
        daily_pct = funding_hourly * FUNDING_PAYMENTS_PER_DAY * 100.0
        if abs(daily_pct) >= HIGH_FUNDING_DAILY_PCT:
            flags.append("high funding - crowded")
    return flags


# ---------------------------------------------------------------------------
# State file (own, isolated - OI-delta history + alert dedup)
# ---------------------------------------------------------------------------
def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"history": {}, "alerted": {}}
        data.setdefault("history", {})
        data.setdefault("alerted", {})
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"history": {}, "alerted": {}}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_ts: Optional[str]) -> float:
    if not iso_ts:
        return float("inf")
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def oi_delta_pct(history: Dict[str, Any], symbol: str, oi_usd: float) -> Optional[float]:
    prior = history.get(symbol)
    if not prior or not prior.get("last_oi_usd"):
        return None
    prev = prior["last_oi_usd"]
    if prev <= 0:
        return None
    return (oi_usd - prev) / prev * 100.0


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _fmt_pct(x: Optional[float]) -> str:
    return f"{x:+.1f}%" if x is not None else "n/a"


def _fmt_line(rank: int, row: Dict[str, Any], oi_delta: Optional[float], watch: List[str]) -> str:
    sym = row["symbol"]
    vol_ratio = row.get("vol_ratio")
    vol_str = f"{vol_ratio:.1f}x avg" if vol_ratio is not None else "n/a avg"
    oi_str = f"{oi_delta:+.1f}% vs last run" if oi_delta is not None else "n/a (first observation)"
    funding_hourly = row.get("funding_hourly")
    if funding_hourly is not None:
        funding_str = f"{funding_hourly*100:+.4f}%/hr (~{funding_hourly*FUNDING_PAYMENTS_PER_DAY*100:+.2f}%/day)"
    else:
        funding_str = "n/a"
    range_pos = row.get("range_pos_pct")
    range_str = f"{range_pos:.0f}% of {BASELINE_LOOKBACK_DAYS}d range" if range_pos is not None else "range n/a"
    lev = row.get("max_leverage")
    lev_str = f"{lev:.0f}x" if lev else "n/a"
    marker = "  [OWNER COIN]" if sym in watch else ""

    line = (
        f"{rank:2d}. {sym:<10s} {_fmt_pct(row.get('pct_24h')):>7s} 24h | "
        f"1h {_fmt_pct(row.get('roc_1h')):>7s} / 4h {_fmt_pct(row.get('roc_4h')):>7s} | "
        f"vol {vol_str:<10s} | OI {oi_str:<24s} | funding {funding_str:<24s} | "
        f"maxLev {lev_str:<4s} | {range_str} | score {row['score']:.1f}{marker}"
    )
    flags = row.get("flags") or []
    if flags:
        line += "\n     [!] " + "  [!] ".join(flags)
    return line


# ---------------------------------------------------------------------------
# Main pipeline (shared by print mode and --alert mode)
# ---------------------------------------------------------------------------
def run_scan(client, top_n: int, pool_size: int, history: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, int], int]:
    """Returns (ranked_rows_desc, reject_counts, total_universe_count)."""
    raw = fetch_universe(client)
    survivors, rejects = apply_liquidity_floor(raw)

    # Stage-1 cheap rank (no candles yet) to pick the Stage-2 candle pool.
    survivors.sort(key=lambda r: abs(r["pct_24h"]), reverse=True)
    pool = survivors[:pool_size]

    for row in pool:
        enrich_with_candles(client, row)
        delta = oi_delta_pct(history, row["symbol"], row["oi_usd"])
        row["oi_delta_pct"] = delta
        row["score"] = compute_score(row, delta)
        row["flags"] = annotate(row)

    pool.sort(key=lambda r: r["score"], reverse=True)
    return pool, rejects, len(raw)


def update_history(history: Dict[str, Any], ranked: List[Dict[str, Any]]) -> None:
    now = _now_iso()
    for row in ranked:
        history[row["symbol"]] = {
            "last_oi_usd": row["oi_usd"],
            "last_vol_usd": row.get("day_ntl_vlm"),
            "last_ts": now,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Co-Pilot What's-Moving Scanner - a 'look here, do your own diligence' "
                    "attention radar over the full HL perp universe. NOT a signal, NOT a buy call."
    )
    ap.add_argument("--top", type=int, default=TOP_N_DEFAULT, help="Top-N movers to show (default 10)")
    ap.add_argument("--pool", type=int, default=CANDLE_STAGE_POOL, help="Stage-2 candle-enrichment pool size (default 40)")
    ap.add_argument("--watch", type=str, default=",".join(DEFAULT_WATCH), help="Comma-separated owner coins to mark/report (default POPCAT,SOL,BTC)")
    ap.add_argument("--alert", action="store_true", help="Also check for NEW top-decile entrants and push a Discord ping (anti-spam, cooldown)")
    ap.add_argument("--cooldown-hours", type=float, default=DEFAULT_COOLDOWN_HOURS, help="Per-symbol alert cooldown hours (default 6)")
    ap.add_argument("--dry-run", action="store_true", help="With --alert: compute + print what WOULD fire; no Discord push, no state write")
    args = ap.parse_args()

    watch = [s.strip().upper() for s in args.watch.split(",") if s.strip()]

    client = _get_hl_client()
    state = load_state()
    history = state["history"]

    print(f"=== WAGMI What's-Moving Scanner - {_now_iso()} ===")
    print("RADAR, not a signal: this finds ATTENTION/MOVEMENT, not edge. Do your own diligence.")
    print("  OOS-measured: flagged movers had a ~50% next-day direction hit-rate (NO directional edge - do")
    print("  not read the ranking as bullish/bearish). What IS real: flagged names carry elevated forward")
    print("  volatility vs their own baseline - i.e. worth a LOOK, not a trade. Direction is yours.\n")

    ranked, rejects, total = run_scan(client, args.top, args.pool, history)
    n_survivors = total - sum(rejects.values())

    print(f"Universe: {total} perps | survived liquidity floor: {n_survivors} | rejected: {rejects}")
    print(f"  floor = 24h volume >= ${MIN_24H_VOLUME_USD:,.0f} AND OI >= ${MIN_OI_USD:,.0f}")
    print(f"Stage-2 candle enrichment ran on top {min(args.pool, n_survivors)} by |24h%| (cheap pre-rank)\n")

    top = ranked[: args.top]
    if not top:
        print("No survivors cleared the liquidity floor this run.")
    else:
        print(f"--- TOP {len(top)} WHAT'S MOVING ---")
        for i, row in enumerate(top, 1):
            print(_fmt_line(i, row, row.get("oi_delta_pct"), watch))

    # Owner-coins section - always shown, marked if present in the ranked pool
    print("\n--- OWNER COINS ---")
    ranked_by_symbol = {r["symbol"]: r for r in ranked}
    for sym in watch:
        row = ranked_by_symbol.get(sym)
        if row:
            rank = next(i for i, r in enumerate(ranked, 1) if r["symbol"] == sym)
            in_top = " (IN TOP LIST)" if row in top else ""
            print(_fmt_line(rank, row, row.get("oi_delta_pct"), watch) + in_top)
        else:
            print(f"    {sym:<10s} not in this run's Stage-2 pool (didn't rank in top {args.pool} by 24h move, or failed the liquidity floor)")

    # --alert mode: top-decile-entrant Discord ping, cooldown + dedup
    if args.alert:
        decile_n = max(1, round(len(ranked) * ALERT_DECILE_FRACTION))
        top_decile = ranked[:decile_n]
        top_decile_symbols = {r["symbol"] for r in top_decile}
        alerted = state["alerted"]
        print(f"\n--- ALERT CHECK (top decile = top {decile_n} of {len(ranked)} ranked) ---")

        any_fired = False
        for row in top_decile:
            sym = row["symbol"]
            prior = alerted.get(sym) or {}
            was_in_decile = bool(prior.get("in_top_decile"))
            if was_in_decile:
                print(f"  {sym}: already in top decile last run - no re-alert (anti-spam)")
                continue
            cooldown_ok = _hours_since(prior.get("last_alert_ts")) >= args.cooldown_hours
            if not cooldown_ok:
                print(f"  {sym}: NEW top-decile entrant but within cooldown ({args.cooldown_hours}h) - suppressed")
                if not args.dry_run:
                    alerted[sym] = {**prior, "in_top_decile": True}
                continue
            msg = _fmt_line(ranked.index(row) + 1, row, row.get("oi_delta_pct"), watch)
            title = f"WAGMI Radar - NEW mover: {sym}"
            body = (
                f"{msg}\n\nLOOK HERE, do your own diligence - this is attention/movement, "
                f"NOT a buy signal or predicted edge. (OOS: flagged movers ~50% next-day direction "
                f"hit-rate = no directional edge; the real signal is elevated forward volatility, not which way.)"
            )
            if args.dry_run:
                print(f"  [DRY RUN] would push to Discord (title={title!r}):")
                print("  " + body.replace("\n", "\n  "))
            else:
                tools_dir = os.path.dirname(_THIS_DIR)
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from discord_notify import send_discord  # local import: only needed on a real fire
                ok = send_discord(body, title=title)
                print(f"  {sym}: Discord push {'sent' if ok else 'FAILED'}")
                alerted[sym] = {"in_top_decile": True, "last_alert_ts": _now_iso()}
            any_fired = True

        # Anything that fell OUT of the top decile: clear the flag silently (no spam on exit)
        if not args.dry_run:
            for sym, prior in list(alerted.items()):
                if prior.get("in_top_decile") and sym not in top_decile_symbols:
                    alerted[sym] = {**prior, "in_top_decile": False}

        if not any_fired:
            print("  (no new top-decile entrants this run)")

    # State persistence: history (OI-delta baseline) always updates on a real
    # run - even without --alert - so OI delta has something to compare
    # against next time. --dry-run writes nothing at all (zero side effects).
    if not args.dry_run:
        update_history(history, ranked)
        save_state(state)
        print(f"\nState written to {STATE_PATH}")
    else:
        print("\n[DRY RUN] no state file written.")


if __name__ == "__main__":
    main()


# =============================================================================
# TODO
# =============================================================================
# - Stage-2 pool is cheap-ranked by |24h%| only (see module docstring): a coin
#   with a sharp 4h spike inside a flat/round-tripped 24h number can miss the
#   candle-enrichment pool entirely. A second, cheaper "hot in the last hour"
#   funnel (e.g. from a lighter per-coin call, or a rolling cache built across
#   repeated runs) would close this gap without scanning all ~230 on every run.
# - Volume-vs-baseline compares a rolling 24h figure (dayNtlVlm) against a
#   calendar-day median from daily candles - an approximation, not an exact
#   like-for-like (see comment in enrich_with_candles). A dedicated intraday
#   volume-history series would make "Nx avg" precise instead of directional.
# - OI-confirmation needs one prior run before it means anything (no HL
#   endpoint returns OI history directly) - first run always shows "n/a
#   (first observation)". Fine for a scheduled/repeated tool, less useful for
#   a single ad-hoc invocation.
# - Funding "crowded" threshold (HIGH_FUNDING_DAILY_PCT) is a fixed heuristic,
#   not data-derived from this bot's own funding history the way copilot.py's
#   per-symbol z-score is - fine for a fast full-universe scan, but a future
#   version could z-score funding per-coin from HLNative.funding_history() for
#   the Stage-2 pool only (same cost budget as the candle calls already made).
# - No unit tests yet (parallel projects have tests/test_copilot*.py-style
#   coverage; this file has none). Worth adding fixture-based tests for
#   apply_liquidity_floor, compute_score, and annotate before this is relied
#   on daily - the arithmetic is simple but easy to silently break on a
#   refactor.
