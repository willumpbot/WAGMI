#!/usr/bin/env python
"""
WAGMI Co-Pilot - EYE DEEP structural layer - eye_deep.py
=============================================================================
The `--deep` structural layer behind `eye --deep SYMBOL`. It adds a MEASURED
PRICE-ACTION MAP on top of the shallow `eye` brief:

  HL-listed perps: multi-timeframe trend (24h/72h/7d/30d), swing S/R with TOUCH
  COUNTS (touch count = how many times price respected a level = conviction of
  the level), volume trend (recent vs prior), liquidation MAGNETS (price
  clusters where leverage got flushed = where stops sit = PATH context), and the
  funding/OI trajectory (OI building = leverage accumulating/fragile vs flushed
  = cleaner; carry cost + positioning, NOT a timing signal).

  DEX-spot memes: recent-window swing S/R with touch counts (mint-keyed OHLCV),
  the mint-keyed ACCUMULATION trajectory (holders + organic health across our
  forward snapshots), and the mint-keyed liquidity trajectory (LPs adding vs
  pulling).

THE HARD RULE (identical to eye.py / SIGNAL_SCORECARD.md, non-negotiable):
this is MEASURED STRUCTURAL CONTEXT (levels, stops, positioning, trend), NEVER
a direction prediction. The project has PROVEN no mechanical signal predicts
direction on this data. Levels tell you WHERE the map has walls, not which way
price walks. Every level is labelled with its touch count; every section is
honest about its data age/coverage; liq magnets are "where stops sit = path
context, NOT direction"; funding is "carry cost + positioning, not a timing
signal". A structural map, not a forecast.

TWO GAPS THIS MODULE FIXES vs the prototype:
  1. MINT-CONTAMINATED HISTORY. Solana symbols are NOT unique (KITTY = 3 mints,
     one genuinely-traded + wash clones). The accumulation/holder/liquidity
     trajectory MUST describe the SAME mint the structure + current snapshot
     describe, so we resolve the coin to ONE mint first (owner_call.resolve_mint,
     which already prefers the genuinely-traded mint over wash clones) and filter
     ALL history (flow_signal / liquidity_snapshots) by that MINT, never by the
     symbol. (organic_score lives in flow_signal.jsonl, NOT wash_signal.jsonl.)
  2. THIN-COIN GRACEFUL DEGRADE. A young coin (e.g. CASHCAT, ~27 daily candles)
     cannot support reliable multi-week levels. We SKIP the swing-level section
     with an honest "too few candles for reliable levels - young coin" note but
     STILL show current price + whatever multi-TF trend IS available + the
     mint-keyed accumulation/flow. Never crash, never fabricate levels.

READ-ONLY / WRITES NOTHING. Same contract as every tools/copilot/*.py module:
never imports live-bot packages (llm/ execution/ core/ strategies/), never
touches live/.env/data/replay. Standalone HL candle fetch is LIVE (end =
now) so the price matches the shallow brief.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
import sys
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# Reuse (do NOT duplicate) the mint-resolution + jsonl/ohlcv machinery.
from owner_call import (  # noqa: E402
    FLOW_PATH,
    LIQ_SNAP_PATH,
    OHLCV_DIR,
    SNAPSHOT_STALE_WARN_HOURS,
    MintMatch,
    _fmt_age,
    _iter_jsonl,
    _parse_snapshot_ts,
    _read_ohlcv_daily,
    resolve_mint,
)

BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
LIQ_EVENTS_PATH = os.path.join(BOT_DIR, "data", "copilot", "liquidations", "liq_events.jsonl")
FUNDING_OI_PATH = os.path.join(BOT_DIR, "data", "funding_oi_history.jsonl")

# --- structural knobs (documented, not magic) ---
MIN_DAILY_FOR_LEVELS = 30      # below this a coin is too young for reliable multi-week levels
SWING_WIN = 4                  # local pivot half-window (a swing high/low dominates +/- this many bars)
MIN_HOURLY_FOR_LEVELS = 48     # gate swing S/R on HOURLY sufficiency (levels come from hourly, not daily):
                               # ~2d of hourly bars minimum before we trust a swing map
LEVEL_TOL = 0.015              # cluster prices within 1.5% into one level
MEME_LEVEL_WINDOW_H = 500      # recent ~20d hourly window for meme levels (avoid ancient sub-cent lows)
LIQ_MAGNET_DAYS = 7            # look-back for the "where stops sit" liquidation price clusters
FUNDING_MIN_OBS = 10           # need this many funding/OI observations for a trajectory read


# ---------------------------------------------------------------------------
# SYMBOL SANITIZER (integrity floor - shared, used by every display path that
# echoes a symbol from an UNTRUSTED discovery feed).
#
# Coin symbols from micro-cap collectors / the HL universe are attacker-shaped
# text. Some carry Unicode BIDI/control characters (e.g. U+202E RIGHT-TO-LEFT
# OVERRIDE) that VISUALLY SPOOF which coin a trading tool is showing - the
# terminal renders a different string than the bytes say, so the owner can be
# fooled about which coin he is eyeing. `safe_symbol` replaces every such char
# with a visible ASCII marker ('?') so a raw bidi/control char NEVER reaches
# the terminal. Applied to EVERY symbol printed to the owner.
# ---------------------------------------------------------------------------

# Explicit high-risk ranges (belt-and-braces on top of the Unicode-category
# check below - these are the chars that actually reorder/hide text):
#   U+202A..U+202E  LRE RLE PDF LRO RLO  (bidi embeddings + overrides)
#   U+2066..U+2069  LRI RLI FSI PDI       (bidi isolates)
#   U+200E/U+200F   LRM/RLM               (bidi marks)
#   U+200B..U+200D  ZWSP/ZWNJ/ZWJ         (zero-width)
#   U+FEFF          ZWNBSP / BOM
#   U+061C          ARABIC LETTER MARK    (bidi)
_SPOOF_CODEPOINTS = (
    set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
    | {0x200E, 0x200F, 0x200B, 0x200C, 0x200D, 0xFEFF, 0x061C}
)
# Unicode general categories that must never reach a trading terminal:
#   Cc control, Cf format (covers bidi/zero-width), Cs surrogate, Co private-use
_SPOOF_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})


def safe_symbol(s, marker: str = "?", maxlen: int = 24) -> str:
    """Neutralize a discovery-fed symbol for safe display. Replaces BIDI/control/
    zero-width/format chars with `marker` ('?') so the terminal can never render
    a spoofed coin name. ASCII tickers pass through unchanged. Length-capped so a
    pathological feed value cannot blow up a line. NEVER use the return value to
    place an API call - it is display-only; keep the raw symbol for network I/O."""
    if s is None:
        return marker
    if not isinstance(s, str):
        s = str(s)
    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7F:                       # C0 controls + DEL
            out.append(marker)
        elif cp in _SPOOF_CODEPOINTS:                     # explicit bidi/zero-width
            out.append(marker)
        elif unicodedata.category(ch) in _SPOOF_CATEGORIES:  # any control/format/surrogate/private
            out.append(marker)
        else:
            out.append(ch)
    res = "".join(out)
    if maxlen and len(res) > maxlen:
        res = res[:maxlen]
    return res or marker


def _safe_symbol_selftest() -> None:
    """Tiny assertion battery proving the bidi/control neutralizer holds. Run via
    `python eye_deep.py --selftest`."""
    # U+202E RIGHT-TO-LEFT OVERRIDE must be neutralized, not passed through.
    spoof = "‮DABKCAT"
    got = safe_symbol(spoof)
    assert "‮" not in got, "bidi override leaked through safe_symbol!"
    assert got == "?DABKCAT", f"expected '?DABKCAT', got {got!r}"
    # A clean ASCII ticker is untouched.
    assert safe_symbol("POPCAT") == "POPCAT"
    assert safe_symbol("KITTY") == "KITTY"
    # Zero-width + isolates + C0 controls all neutralized.
    assert "​" not in safe_symbol("SO​L")
    assert safe_symbol("A⁦B⁩C") == "A?B?C"
    assert safe_symbol("X\x00Y\x1bZ") == "X?Y?Z"
    # None / non-str degrade to a visible marker, never crash.
    assert safe_symbol(None) == "?"
    assert safe_symbol("") == "?"
    # No raw spoof char ever survives, for a broad sweep of the danger set.
    for cp in list(_SPOOF_CODEPOINTS) + [0x00, 0x1b, 0x7f, 0x9f]:
        assert chr(cp) not in safe_symbol("A" + chr(cp) + "B")
    print("safe_symbol selftest: PASS (bidi/control/zero-width neutralized)")


# ---------------------------------------------------------------------------
# LIVE HL candle fetch (standalone - end = now, never a stale hardcoded ts)
# ---------------------------------------------------------------------------

def hl_candles(coin: str, interval: str, lookback_ms: int) -> List[dict]:
    end = int(time.time() * 1000)
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": end - lookback_ms, "endTime": end}}
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return [{"t": c["t"], "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]),
                 "c": float(c["c"]), "v": float(c["v"])} for c in d]
    except Exception as e:  # noqa: BLE001 - a candle-fetch failure degrades, never crashes
        print(f"[eye_deep] candle fetch failed {coin} {interval}: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# structural math (from the verified prototype - reused, not reinvented)
# ---------------------------------------------------------------------------

def swings(candles: List[dict], win: int = SWING_WIN) -> Tuple[list, list]:
    """Local pivot highs/lows: bar i is a swing high if its high is the max over
    [i-win, i+win] (and symmetrically for lows). Returns ([(i, high)], [(i, low)])."""
    hi, lo = [], []
    for i in range(win, len(candles) - win):
        window = candles[i - win:i + win + 1]
        if candles[i]["h"] == max(c["h"] for c in window):
            hi.append((i, candles[i]["h"]))
        if candles[i]["l"] == min(c["l"] for c in window):
            lo.append((i, candles[i]["l"]))
    return hi, lo


def cluster_levels(points: List[Tuple[int, float]], tol: float = LEVEL_TOL) -> List[Tuple[float, int]]:
    """Cluster nearby pivot prices into levels. Returns [(level_price, touch_count)]
    sorted by touch_count desc. Touch count = how many pivots landed on the level
    = the level's conviction."""
    vals = sorted(p for _, p in points)
    clusters: List[list] = []
    for v in vals:
        placed = False
        for cl in clusters:
            if abs(v - cl[0]) / cl[0] <= tol:
                cl[1].append(v)
                cl[0] = sum(cl[1]) / len(cl[1])
                placed = True
                break
        if not placed:
            clusters.append([v, [v]])
    return sorted(((round(c[0], 8), len(c[1])) for c in clusters), key=lambda x: -x[1])


def chg(cs: List[dict], n: int) -> float:
    """Percent change over the last n bars (nan if not enough history)."""
    return (cs[-1]["c"] / cs[-1 - n]["c"] - 1) * 100 if len(cs) > n else float("nan")


def _fp(p: Optional[float]) -> str:
    """Compact price format matching eye.py's spirit (majors 4dp, sub-$1 trimmed)."""
    if not isinstance(p, (int, float)):
        return "n/a"
    if p >= 1:
        return f"${p:,.4f}"
    return f"${p:.8f}".rstrip("0").rstrip(".")


def _pct_from(px: float, lv: float) -> str:
    return f"{(lv / px - 1) * 100:+.1f}%"


def _ohlcv_hour_path(day_path: Optional[str], mint: Optional[str]) -> Optional[str]:
    """The hourly CSV twin of a daily OHLCV path (or a mint-prefix glob fallback).
    Meme levels want the finer hourly grid; day_path is what resolve_mint carries."""
    if day_path and day_path.endswith("_day.csv"):
        cand = day_path[: -len("_day.csv")] + "_hour.csv"
        if os.path.isfile(cand):
            return cand
    if mint:
        hits = glob.glob(os.path.join(OHLCV_DIR, f"*_{mint[:8]}_hour.csv"))
        if hits:
            return hits[0]
    return None


def _load_ohlcv_hlc(path: Optional[str]) -> List[dict]:
    """Load an OHLCV CSV as [{'h','l','c'}] (high/low/close), for swing detection.
    Empty list on any problem - callers degrade."""
    out: List[dict] = []
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out.append({"h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])})
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return out


# ---------------------------------------------------------------------------
# MINT-KEYED history (THE FIX): filter by the resolved mint, never the symbol.
# ---------------------------------------------------------------------------

def _mint_rows(path: str, mint: str) -> List[dict]:
    """All rows in a micro-cap jsonl for exactly this MINT, in time order. This is
    the gap-1 fix: filtering by symbol pollutes the trajectory with wash clones
    (KITTY has 3 mints); the mint pins it to the same coin the structure describes."""
    rows = [r for r in _iter_jsonl(path) if r.get("mint") == mint]
    rows.sort(key=lambda r: r.get("ts_utc") or "")
    return rows


def mint_accumulation_lines(mm: MintMatch, symbol: str) -> List[str]:
    """MINT-KEYED accumulation trajectory: holders + organic health (from
    flow_signal, which carries organic_score - wash_signal does NOT) and the
    liquidity trajectory (from liquidity_snapshots), all pinned to mm.mint so a
    wash clone can never contaminate the read. Degrades honestly on thin history."""
    L: List[str] = []
    if not mm.mint:
        return L
    flow = _mint_rows(FLOW_PATH, mm.mint)
    liqsnap = _mint_rows(LIQ_SNAP_PATH, mm.mint)

    L.append(f"ACCUMULATION TRAJECTORY (mint {mm.mint[:8]}.. - the SAME coin as above, wash clones excluded):")
    if len(flow) >= 2:
        h0, h1 = flow[0].get("holder_count"), flow[-1].get("holder_count")
        o0, o1 = flow[0].get("organic_score"), flow[-1].get("organic_score")
        span_h = _snap_span_hours(flow)
        hbit = (f"holders {h0:,} -> {h1:,} ({(h1 - h0):+,})"
                if isinstance(h0, (int, float)) and isinstance(h1, (int, float)) else "holders n/a")
        obit = (f"organic {o0:.0f} -> {o1:.0f}/100"
                if isinstance(o0, (int, float)) and isinstance(o1, (int, float)) else "organic n/a")
        L.append(f"    {hbit} | {obit}  over {len(flow)} snaps"
                 + (f" (~{_fmt_age(span_h)})" if span_h is not None else ""))
        htrend = ("holders accumulating" if isinstance(h0, (int, float)) and isinstance(h1, (int, float)) and h1 > h0
                  else "holders distributing" if isinstance(h0, (int, float)) and isinstance(h1, (int, float)) and h1 < h0
                  else "holders flat")
        L.append(f"    -> {htrend}; organic {'healthy-ish (55+ = genuinely traded)' if isinstance(o1,(int,float)) and o1>=55 else 'thin/suspect (<55)' if isinstance(o1,(int,float)) else 'unmeasured'}.")
    elif len(flow) == 1:
        o1, h1 = flow[0].get("organic_score"), flow[0].get("holder_count")
        L.append(f"    only 1 flow snapshot so far (trajectory maturing): holders "
                 f"{h1:,} | organic {o1:.0f}/100." if isinstance(h1, (int, float)) and isinstance(o1, (int, float))
                 else "    only 1 flow snapshot so far (trajectory maturing).")
    else:
        L.append("    no mint-keyed flow snapshots yet (forward collector young) - trajectory unavailable.")

    if len(liqsnap) >= 2:
        l0, l1 = liqsnap[0].get("liquidity_usd"), liqsnap[-1].get("liquidity_usd")
        if isinstance(l0, (int, float)) and isinstance(l1, (int, float)) and l0 > 0:
            trend = "LPs adding" if l1 > l0 * 1.05 else "LPs pulling" if l1 < l0 * 0.95 else "stable"
            L.append(f"    liquidity ${l0:,.0f} -> ${l1:,.0f} ({(l1 / l0 - 1) * 100:+.0f}%) over "
                     f"{len(liqsnap)} snaps - {trend}.")
    return L


def _snap_span_hours(rows: List[dict]) -> Optional[float]:
    if len(rows) < 2:
        return None
    t0 = _parse_snapshot_ts(rows[0].get("ts_utc"))
    t1 = _parse_snapshot_ts(rows[-1].get("ts_utc"))
    if t0 is None or t1 is None:
        return None
    return max(0.0, (t1 - t0).total_seconds() / 3600.0)


# ---------------------------------------------------------------------------
# LIQUIDATION MAGNETS (where stops sit = PATH context, NOT direction)
# ---------------------------------------------------------------------------

def liq_magnet_lines(symbol: str, price: float) -> List[str]:
    """Price clusters of recent forced liquidations for `symbol` = where leverage
    got flushed = where stops/liq sit. PATH context only. Reads the same
    liq_events.jsonl the collector writes; no new collection."""
    L: List[str] = []
    if not os.path.exists(LIQ_EVENTS_PATH):
        L.append("LIQ MAGNETS: no cascade feed on file yet (liq_collector not run).")
        return L
    cutoff = datetime.now(timezone.utc) - timedelta(days=LIQ_MAGNET_DAYS)
    prices: List[Tuple[int, float]] = []
    above = below = 0.0
    n = 0
    for r in _iter_jsonl(LIQ_EVENTS_PATH):
        if (r.get("coin") or r.get("symbol")) != symbol:
            continue
        ts = _parse_snapshot_ts(r.get("ts_utc"))
        if ts is not None and ts < cutoff:
            continue
        try:
            p = float(r["price"])
            ntl = float(r.get("notional_usd") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        prices.append((0, p))
        n += 1
        if p > price:
            above += ntl
        else:
            below += ntl
    if n == 0:
        L.append(f"LIQ MAGNETS: none captured for {safe_symbol(symbol)} in {LIQ_MAGNET_DAYS}d "
                 f"(quiet, or not on collected venues).")
        return L
    L.append(f"LIQ MAGNETS ({n} forced liqs, {LIQ_MAGNET_DAYS}d) - where stops sit = PATH context, NOT direction:")
    L.append(f"    ${above:,.0f} flushed ABOVE / ${below:,.0f} flushed BELOW current {_fp(price)}")
    for lv, t in cluster_levels(prices)[:3]:
        L.append(f"    cluster {_fp(lv)} ({_pct_from(price, lv)}) x{t} liqs")
    # CALIBRATED 2026-08-06 (liq_magnet_calibration.py, n=193 BTC+SOL): clusters
    # are NOT magnets - price reached them NO more than distance-matched random
    # levels (38% vs 41%, CI spans 0, sign flips OOS). So this is NOT "where price
    # is headed"; it's only "where a move could ACCELERATE if that level is tagged".
    L.append("    (measured: price does NOT gravitate to these more than a random level - "
             "read as 'where it could accelerate if tagged', not 'where it's headed')")
    return L


# ---------------------------------------------------------------------------
# FUNDING / OI trajectory (carry cost + positioning, NOT a timing signal)
# ---------------------------------------------------------------------------

def funding_oi_lines(symbol: str) -> List[str]:
    L: List[str] = []
    fo = [r for r in _iter_jsonl(FUNDING_OI_PATH) if r.get("symbol") == symbol]
    if len(fo) < FUNDING_MIN_OBS:
        L.append(f"FUNDING/OI: <{FUNDING_MIN_OBS} observations collected for {safe_symbol(symbol)} "
                 f"({len(fo)} on file) - positioning trajectory unavailable.")
        return L
    fo.sort(key=lambda r: r.get("timestamp") or "")
    # Bound the OI delta to a RECENT window so a long-history coin (ETH/SOL have
    # ~2 months on file) doesn't read a 2-month build as CURRENT positioning.
    # Match the 7d liq-magnet window; fall back to full history for young coins.
    last_ts = _parse_snapshot_ts((fo[-1].get("timestamp") or "").replace(" ", "T"))
    first_ts = _parse_snapshot_ts((fo[0].get("timestamp") or "").replace(" ", "T"))
    span_days = (last_ts - first_ts).total_seconds() / 86400.0 if (last_ts and first_ts) else None
    win = fo
    win_note = f"over ~{span_days:.0f}d" if span_days is not None else f"{len(fo)} obs"
    if last_ts is not None and span_days is not None and span_days > 8.0:
        cutoff = last_ts.timestamp() - 7 * 86400
        recent = [r for r in fo if (_parse_snapshot_ts((r.get("timestamp") or "").replace(" ", "T")) or last_ts).timestamp() >= cutoff]
        if len(recent) >= FUNDING_MIN_OBS:
            win = recent
            win_note = "last ~7d"
    oi0, oi1 = win[0].get("open_interest"), win[-1].get("open_interest")
    fr = [r.get("funding_rate") for r in fo if isinstance(r.get("funding_rate"), (int, float))]
    avgf = sum(fr) / len(fr) if fr else 0.0
    age = None
    if last_ts is not None:
        age = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600.0
    L.append("FUNDING/OI (carry cost + positioning, NOT a timing signal):")
    if isinstance(oi0, (int, float)) and isinstance(oi1, (int, float)) and oi0 > 0:
        state = ("OI BUILDING = leverage accumulating (more fragile to a cascade)" if oi1 > oi0 * 1.1
                 else "OI flushed/lower = leverage cleaner" if oi1 < oi0 * 0.9 else "OI ~stable")
        L.append(f"    OI ${oi0:,.0f} -> ${oi1:,.0f} ({(oi1 / oi0 - 1) * 100:+.0f}%, {win_note}, {len(win)} obs) - {state}")
    L.append(f"    avg funding {avgf * 100:+.4f}%/hr ({'longs pay shorts' if avgf > 0 else 'shorts pay longs' if avgf < 0 else 'flat'})"
             + (f" | last obs ~{_fmt_age(age)} old" + (" (STALE)" if age is not None and age > 24 else "") if age is not None else ""))
    return L


# ---------------------------------------------------------------------------
# HL structural section (multi-TF trend + levels + volume + magnets + funding)
# Degrades on a young coin: skips levels, still shows available trend/flow.
# ---------------------------------------------------------------------------

def hl_deep_lines(symbol: str) -> Tuple[List[str], Optional[float]]:
    """Returns (lines, current_price). current_price is the last LIVE hourly close
    (so it matches the shallow brief). Empty lines + None if no candles at all."""
    d1 = hl_candles(symbol, "1d", 90 * 86400000)
    h1 = hl_candles(symbol, "1h", 20 * 86400000)
    if not h1 and not d1:
        return [], None
    px = (h1[-1]["c"] if h1 else d1[-1]["c"])
    L: List[str] = []
    young = len(d1) < MIN_DAILY_FOR_LEVELS
    L.append("DEEP STRUCTURE - HL PERP (measured price map, NOT a forecast):")
    L.append(f"  Price {_fp(px)} [LIVE] | {len(d1)}d daily, {len(h1)}h hourly on file"
             + ("  >>> YOUNG COIN <<<" if young else ""))

    # ---- multi-timeframe trend (whatever the history supports) ----
    def _t(v):
        return "n/a" if v != v else f"{v:+.1f}%"  # v!=v is NaN
    L.append(f"  TREND: 24h {_t(chg(h1, 24))} | 72h {_t(chg(h1, 72))} | 7d {_t(chg(d1, 7))} | 30d {_t(chg(d1, 30))}")

    # ---- swing S/R with touch counts (or honest degrade) ----
    # Gate on HOURLY sufficiency: levels are computed from h1, so a coin that is
    # "young" by daily count (<30d) but has plenty of hourly bars (e.g. 20d = 481h)
    # can still show valid recent S/R. Only skip when hourly itself is too thin.
    if len(h1) >= MIN_HOURLY_FOR_LEVELS:
        hi, lo = swings(h1, SWING_WIN)
        res = [(lv, t) for lv, t in cluster_levels(hi) if lv > px][:4]
        sup = [(lv, t) for lv, t in cluster_levels(lo) if lv < px][:4]
        L.append("  RESISTANCE (swing highs, touch count = level conviction):")
        if res:
            for lv, t in sorted(res):
                L.append(f"      {_fp(lv)}  ({_pct_from(px, lv)})  x{t} touches")
        else:
            L.append("      none above current (at/near local highs)")
        L.append("  SUPPORT (swing lows, touch count = level conviction):")
        if sup:
            for lv, t in sorted(sup, reverse=True):
                L.append(f"      {_fp(lv)}  ({_pct_from(px, lv)})  x{t} touches")
        else:
            L.append("      none below current (at/near local lows)")
    else:
        L.append(f"  LEVELS: too few hourly candles ({len(h1)}h) for reliable swing S/R - "
                 f"skipping rather than fabricate walls from a short history.")

    # ---- volume trend ----
    if len(d1) >= 10:
        v_recent = sum(c["v"] for c in d1[-3:]) / 3
        v_prior = sum(c["v"] for c in d1[-10:-3]) / 7
        ratio = v_recent / v_prior if v_prior else 1.0
        state = "rising" if ratio > 1.1 else "falling" if ratio < 0.9 else "flat"
        L.append(f"  VOLUME last-3d vs prior-7d: {ratio:.2f}x ({state})")
    else:
        L.append("  VOLUME trend: too few daily bars - degraded.")

    # ---- liq magnets + funding/OI ----
    L.extend("  " + ln for ln in liq_magnet_lines(symbol, px))
    L.extend("  " + ln for ln in funding_oi_lines(symbol))
    return L, px


# ---------------------------------------------------------------------------
# Meme structural section (recent-window levels + mint-keyed accumulation)
# ---------------------------------------------------------------------------

def meme_deep_lines(mm: MintMatch, symbol: str, price: Optional[float]) -> List[str]:
    L: List[str] = []
    L.append("DEEP STRUCTURE - DEX SPOT (measured price map, NOT a forecast):")
    hour_path = _ohlcv_hour_path(mm.ohlcv_day_path, mm.mint)
    hc = _load_ohlcv_hlc(hour_path)
    px = price if isinstance(price, (int, float)) else (hc[-1]["c"] if hc else None)

    if hc and isinstance(px, (int, float)) and px > 0:
        window = hc[-MEME_LEVEL_WINDOW_H:]  # recent ~20d structure only
        if len(window) > 2 * SWING_WIN:
            hi, lo = swings(window, SWING_WIN)
            res = [(lv, t) for lv, t in cluster_levels(hi) if lv > px][:3]
            sup = [(lv, t) for lv, t in cluster_levels(lo) if lv < px][:3]
            L.append(f"  RECENT-WINDOW LEVELS (last ~{len(window)}h hourly, touch count = conviction):")
            L.append("    RESISTANCE: " + (", ".join(f"{_fp(lv)}({_pct_from(px, lv)},x{t})"
                                                     for lv, t in sorted(res)) or "none above"))
            L.append("    SUPPORT:    " + (", ".join(f"{_fp(lv)}({_pct_from(px, lv)},x{t})"
                                                     for lv, t in sorted(sup, reverse=True)) or "none below"))
        else:
            L.append(f"  LEVELS: too few candles for reliable levels - young coin ({len(window)}h). Skipping.")
    else:
        L.append("  LEVELS: no mint-keyed hourly OHLCV on disk yet (thin/young coin) - "
                 "too few candles for reliable levels. Skipping rather than fabricate.")

    L.extend("  " + ln for ln in mint_accumulation_lines(mm, symbol))
    return L


# ---------------------------------------------------------------------------
# Degraded-HL builder: an HL coin too young for the shallow read (build_dip_read
# needs >=30 daily). Still surfaces LIVE price + available trend + magnets +
# funding + the mint-keyed accumulation (if the coin has a Solana mint).
# ---------------------------------------------------------------------------

def hl_degraded_lines(symbol: str) -> Tuple[List[str], Optional[float]]:
    lines, px = hl_deep_lines(symbol)
    if not lines:
        return [], None
    # a young HL meme (CASHCAT etc.) often also has a Solana spot mint - fold its
    # mint-keyed accumulation/health/flow in so the degrade still shows "what IS".
    mm = resolve_mint(symbol)
    if mm.mint:
        lines.append("")
        lines.extend(mint_accumulation_lines(mm, symbol))
    return lines, px


# ---------------------------------------------------------------------------
# CLI (selftest only - this module is a library reused by eye.py)
# ---------------------------------------------------------------------------

def main() -> None:
    import sys as _sys
    if "--selftest" in _sys.argv[1:]:
        _safe_symbol_selftest()
        return
    print("eye_deep.py is a library (reused by eye.py). Run `python eye_deep.py --selftest` "
          "to exercise the safe_symbol sanitizer.")


if __name__ == "__main__":
    main()
