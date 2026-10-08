#!/usr/bin/env python
"""
WAGMI Co-Pilot - EYE (pre-decision analyst brief) - eye.py
=============================================================================
The PRE-DECISION counterpart to the OWNER-CALL (`call`) command. `call` is
AT-decision: the owner has already picked a direction and wants the
survive-the-trade risk math. `eye SYMBOL` is BEFORE that: it assembles the
full, honest picture on a coin the owner is EYEING so he can form his thesis
faster and without getting fooled.

THE ONE HARD RULE (matches SIGNAL_SCORECARD.md, no overclaim)
-----------------------------------------------------------------------------
This tool presents MEASURED CONTEXT (what IS), it NEVER makes a PREDICTION
(what WILL be). It must NEVER tell the owner which way the coin goes - the
project has PROVEN no mechanical signal predicts direction on this data
(scorecard: every "which way/when to buy" signal is dead or was never real),
and the owner's discretion is the edge. `eye` organizes what is knowable and
flags risks; the directional conviction stays HIS. Every data point is framed
at its scorecard-honest worth: funding = carry cost + crowd positioning (NOT a
timing signal); movers/flow = attention, ~50% next-day (NOT direction);
organic_score = wash/real health; liquidations = path-risk / where stops sit.

The "HONEST BULL vs BEAR" section is a STRUCTURING device - it sorts the SAME
measured facts into "what a long thesis would lean on" vs "what a short/avoid
thesis would lean on" vs "the unknowns", and ends with an explicit line that
direction is HIS read and the tool has no validated directional edge. It is
NOT a recommendation and never resolves to a side.

WHAT IT PRODUCES
-----------------------------------------------------------------------------
HL-LISTED perps (BTC/ETH/SOL/POPCAT/WIF/... detected LIVE via HL's `meta`
universe): 1) WHERE IT IS - price vs swing high/low, trend, RSI/BB/ADX/ATR
framed honestly. 2) THE TRAP - funding crowding, where liquidations are
stacked (path risk, from the live liq_events cascade feed), beta-to-BTC
(proxy check). 3) HONEST BULL vs BEAR. 4) a one-line pointer to `call`.

DEX-SPOT memes NOT on HL ($KITTY etc.): 1) WHERE IT IS - price vs recent
OHLCV range + daily vol. 2) IS IT REAL - holders + holder trend, organic
health score (calibrated reading), liquidity depth + slippage-vs-size note.
3) FLOW RIGHT NOW - buy/sell pressure + vol accel (attention, ~50% at best).
4) HONEST BULL vs BEAR. (No leverage/liq - it's spot.)

`eye` with NO symbol = SCAN mode: a short list of coins currently in a
NOTABLE STATE (attention, not signal) - young micro-caps with accelerating
holder growth + healthy organic + rising liquidity (from flow_signal.jsonl),
and the HL movers (from the what's-moving Stage-1 universe read). Labeled
explicitly "things worth YOUR eyes, ranked by activity - NOT buy signals".

READ-ONLY / STANDALONE / WRITES NOTHING. Same contract as every
tools/copilot/*.py module: never imports live-bot packages (llm/, execution/,
core/, strategies/), never touches live/.env/data/replay. UNLIKE `call`, this
command logs NOTHING to any ledger - it is pre-decision; only `call` records
forward evidence. No Discord push. It reuses (does not duplicate) the routing
+ snapshot machinery from owner_call.py / copilot.py / book.py / whats_moving.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    ADD_BB_MAX,
    DEFAULT_SIDE,
    FALLING_KNIFE_RET7D_PCT,
    HOLD_BB_MIN,
    MAX_HOLD_DAYS_RANGE,
    NEAR_SR_PCT,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    _funding_direction_note,
    _get_hl_client,
    _norm_symbol,
    build_dip_read,
    compute_liquidation,
    fetch_hl_max_leverage,
)
from owner_call import (  # noqa: E402
    FLOW_PATH,
    LIQ_SNAP_PATH,
    SLIPPAGE_NOTABLE_PCT,
    SLIPPAGE_SEVERE_PCT,
    SNAPSHOT_STALE_WARN_HOURS,
    WASH_PATH,
    _daily_vol_pct_from_ohlcv,
    _freshness_line,
    _iter_jsonl,
    _latest_row_for_mint,
    _read_ohlcv_daily,
    _settled_from_ohlcv,
    _snapshot_age_hours,
    estimate_amm_slippage_pct,
    is_hl_listed,
    resolve_mint,
)
# The shared symbol sanitizer lives in eye_deep (the structural-machinery module
# this file reuses); import it here so EVERY symbol echoed to the owner - most of
# all the discovery-fed symbols in SCAN mode - is neutralized against Unicode
# BIDI/control spoofing before it reaches the terminal. eye_deep does NOT import
# eye, so this top-level import is not circular.
from eye_deep import safe_symbol  # noqa: E402

BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
LIQ_EVENTS_PATH = os.path.join(BOT_DIR, "data", "copilot", "liquidations", "liq_events.jsonl")

# Owner's account context, only used for human-scale slippage/notional framing
# (never sizes or recommends anything - this command writes/executes nothing).
DEFAULT_EQUITY_USD = 5000.0
# A "typical size" the owner might deploy into a thin meme, for the honest
# slippage note (constant-product estimate via owner_call.estimate_amm_slippage_pct).
TYPICAL_MEME_SIZE_USD = 500.0

RANGE_LOOKBACK_D = 30            # recent OHLCV window for the meme price-range read
LIQ_CLUSTER_WINDOW_D = 7        # look-back for the "where liquidations stacked" read


# ---------------------------------------------------------------------------
# small format helpers
# ---------------------------------------------------------------------------

def _fmt_price(p: Optional[float]) -> str:
    if not isinstance(p, (int, float)):
        return "n/a"
    if p >= 1:
        return f"${p:,.4f}"
    return f"${p:.8f}".rstrip("0").rstrip(".")


def _fmt_pct(x: Optional[float], places: int = 1) -> str:
    return f"{x:+.{places}f}%" if isinstance(x, (int, float)) else "n/a"


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def _range_label(pos_pct: Optional[float]) -> str:
    """Human label for where price sits in a lo..hi range (0=low, 100=high)."""
    if pos_pct is None:
        return "n/a"
    if pos_pct >= 85:
        return "top of range"
    if pos_pct >= 60:
        return "upper range"
    if pos_pct > 40:
        return "mid range"
    if pos_pct > 15:
        return "lower range"
    return "bottom of range"


# ---------------------------------------------------------------------------
# Liquidation-cascade cluster read (path risk / where stops sit) - reads the
# SAME liq_events.jsonl the liq_collector writes, no new collection. HONEST
# framing: this is a CEX forced-liquidation feed - where leverage recently got
# flushed = where stops/liq sit = PATH risk. NOT a direction signal.
# ---------------------------------------------------------------------------

def liq_cluster_for_symbol(symbol: str, days: int = LIQ_CLUSTER_WINDOW_D) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = {"n": 0, "long": 0, "short": 0, "long_usd": 0.0, "short_usd": 0.0,
           "biggest": None, "days": days, "file_exists": os.path.exists(LIQ_EVENTS_PATH)}
    biggest_usd = -1.0
    for r in _iter_jsonl(LIQ_EVENTS_PATH):
        if r.get("symbol") != symbol:
            continue
        dt = _parse_iso(r.get("ts_utc"))
        if dt is None or dt < cutoff:
            continue
        notional = r.get("notional_usd") or 0.0
        side = r.get("side")
        out["n"] += 1
        if side == "long":
            out["long"] += 1
            out["long_usd"] += notional
        elif side == "short":
            out["short"] += 1
            out["short_usd"] += notional
        if notional > biggest_usd:
            biggest_usd = notional
            out["biggest"] = r
    return out


def _liq_cluster_line(symbol: str, cl: dict) -> str:
    if not cl["file_exists"]:
        return ("Liquidations: no cascade feed on file yet (liq_collector not run) - "
                "path-risk read unavailable.")
    if cl["n"] == 0:
        return (f"Liquidations: none captured for {symbol} in the last {cl['days']}d "
                f"(quiet, or not on the collected venues) - low recent forced-flush activity.")
    # NOTE: a LONG liquidation is a forced SELL (price fell through stacked long
    # stops); a SHORT liquidation is a forced BUY. This is where leverage got
    # flushed = path risk, NOT a direction call.
    return (
        f"Liquidations (last {cl['days']}d, path-risk context - NOT direction): "
        f"{cl['long']} longs flushed (${cl['long_usd']:,.0f}, forced selling) vs "
        f"{cl['short']} shorts flushed (${cl['short_usd']:,.0f}, forced buying). "
        f"Where leverage gets flushed is where stops/liq sit - a levered entry can get "
        f"caught in the same cascade."
    )


# ---------------------------------------------------------------------------
# EyeBrief result object
# ---------------------------------------------------------------------------

@dataclass
class EyeBrief:
    ok: bool = True
    note: Optional[str] = None
    symbol: str = ""
    instrument_type: str = ""     # HL_PERP / DEX_SPOT
    lines: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BULL vs BEAR - a STRUCTURING device. Sorts the SAME measured facts into the
# two theses + the unknowns. Never resolves to a side; always disclaims.
# ---------------------------------------------------------------------------

def _format_bull_bear(bull: List[str], bear: List[str], unknown: List[str]) -> List[str]:
    L = ["HONEST BULL vs BEAR (a way to organize the SAME facts above - NOT a recommendation):"]
    L.append("  A LONG thesis would lean on:")
    if bull:
        L.extend(f"    + {b}" for b in bull)
    else:
        L.append("    + (nothing in the measured data leans long right now)")
    L.append("  A SHORT / AVOID thesis would lean on:")
    if bear:
        L.extend(f"    - {b}" for b in bear)
    else:
        L.append("    - (nothing in the measured data leans short right now)")
    L.append("  The UNKNOWNS (what the data CANNOT tell you):")
    for u in unknown:
        L.append(f"    ? {u}")
    return L


def _hl_bull_bear(dip, funding_note_positive: Optional[bool], beta: Optional[float], cl: dict
                  ) -> Tuple[List[str], List[str], List[str]]:
    bull: List[str] = []
    bear: List[str] = []
    unknown: List[str] = []

    # trend / momentum
    _pullback = "pullback inside" in getattr(dip, "structure_note", "")
    _bounce = "bounce inside" in getattr(dip, "structure_note", "")
    if dip.trend_1d == "up" and dip.trend_strength == "strong":
        if _pullback:
            bull.append("uptrend structure still intact (20d avg above 50d)")
            bear.append(f"but price is below its 20d avg and sellers drove the recent move (ADX {dip.adx_1d:.0f})")
        else:
            bull.append(f"intact uptrend (ADX {dip.adx_1d:.0f} strong up)")
    elif dip.trend_1d == "down" and dip.trend_strength == "strong":
        if _bounce:
            bear.append("downtrend structure still intact (20d avg below 50d)")
            bull.append(f"but price is above its 20d avg and buyers drove the recent move (ADX {dip.adx_1d:.0f})")
        else:
            bear.append(f"intact downtrend (ADX {dip.adx_1d:.0f} strong down)")
    elif dip.trend_1d == "chop":
        unknown.append("no trend - chop regime (ADX below trend threshold); direction is noise here")

    if dip.ret_7d_pct is not None:
        if dip.ret_7d_pct <= FALLING_KNIFE_RET7D_PCT:
            bull.append(f"beaten down {dip.ret_7d_pct:+.1f}%/7d - historically knives bounce "
                        f"(+~4%/3d) BUT 42-55% draw down >=10% first (path risk if levered)")
            bear.append(f"falling knife {dip.ret_7d_pct:+.1f}%/7d - strong downside momentum")
        elif dip.ret_7d_pct >= 20:
            bull.append(f"strong 7d momentum {dip.ret_7d_pct:+.1f}%")
            bear.append(f"already ran {dip.ret_7d_pct:+.1f}%/7d - late/extended if chasing")

    # RSI - framed as "stretched", the lever a mean-reversion thesis points to
    if dip.rsi_1d is not None:
        if dip.rsi_1d <= RSI_OVERSOLD:
            bull.append(f"RSI {dip.rsi_1d:.0f} oversold (stretched down - a mean-reversion long points here; "
                        f"NOTE the ADD/dip timing edge decayed to noise OOS, structure only)")
        elif dip.rsi_1d >= RSI_OVERBOUGHT:
            bear.append(f"RSI {dip.rsi_1d:.0f} overbought (stretched up - a mean-reversion short points here)")

    # position in 20d range
    if dip.dist_to_low_pct is not None and dip.dist_to_low_pct <= NEAR_SR_PCT:
        bull.append(f"near 20d support ${dip.swing_low:.4f} ({dip.dist_to_low_pct:.1f}% above) - "
                    f"a bounce-off-support long points here")
        bear.append(f"only {dip.dist_to_low_pct:.1f}% above 20d support - a break BELOW it is a short trigger")
    if dip.dist_to_high_pct is not None and dip.dist_to_high_pct <= NEAR_SR_PCT:
        bull.append(f"only {dip.dist_to_high_pct:.1f}% below the 20d high ${dip.swing_high:.4f} - "
                    f"a breakout long points here")
        bear.append(f"near 20d resistance ${dip.swing_high:.4f} ({dip.dist_to_high_pct:.1f}% below) - "
                    f"a fade-the-highs short points here")

    # funding = crowd positioning (carry, not timing)
    if funding_note_positive is True:
        bear.append("crowd already positioned LONG (positive funding - longs pay to hold; "
                    "unwind/squeeze risk cuts against a fresh long)")
    elif funding_note_positive is False:
        bull.append("crowd already positioned SHORT (negative funding - shorts pay; "
                    "unwind/squeeze risk cuts against a fresh short)")
    else:
        unknown.append("funding ~flat - no crowd lean to read")

    # beta / proxy
    if beta is not None and abs(beta) >= 1.2:
        unknown.append(f"beta-to-BTC ~{beta:.2f} - this mostly moves WITH BTC; its 'direction' is "
                       f"largely BTC's, not idiosyncratic edge")

    # liquidation path context
    if cl.get("n", 0) >= 20:
        if cl["long"] > cl["short"] * 1.5:
            unknown.append(f"recent forced flush skewed to LONGS ({cl['long']} vs {cl['short']} shorts) - "
                           f"leverage got cleaned out below; path context, not direction")
        elif cl["short"] > cl["long"] * 1.5:
            unknown.append(f"recent forced flush skewed to SHORTS ({cl['short']} vs {cl['long']} longs) - "
                           f"leverage got cleaned out above; path context, not direction")

    unknown.append("DIRECTION ITSELF - no signal here predicts which way it goes (scorecard: entry stays "
                   "discretionary; your read is the edge)")
    return bull, bear, unknown


def _meme_bull_bear(price_pos: Optional[float], organic: Optional[float], holders,
                    holder_growth_1h: Optional[float], liq_change_1h: Optional[float],
                    buy_ratio: Optional[float], vol_accel: Optional[float],
                    daily_vol: Optional[float]) -> Tuple[List[str], List[str], List[str]]:
    bull: List[str] = []
    bear: List[str] = []
    unknown: List[str] = []

    if price_pos is not None:
        if price_pos <= 20:
            bull.append(f"near the bottom of its recent {RANGE_LOOKBACK_D}d range ({price_pos:.0f}%) - "
                        f"a reclaim long points here")
            bear.append(f"bottom of its {RANGE_LOOKBACK_D}d range ({price_pos:.0f}%) - a breakdown short points here")
        elif price_pos >= 80:
            bull.append(f"near the top of its {RANGE_LOOKBACK_D}d range ({price_pos:.0f}%) - strength/breakout long")
            bear.append(f"top of its {RANGE_LOOKBACK_D}d range ({price_pos:.0f}%) - extended, a fade short points here")

    if organic is not None:
        if organic >= 55:
            bull.append(f"organic_score {organic:.0f} (genuinely traded, not wash-dominated) - real flow to build on")
        elif organic < 30:
            bear.append(f"organic_score {organic:.0f} (low - volume looks largely inorganic/wash; "
                        f"'realness' is in doubt)")

    if holder_growth_1h is not None:
        if holder_growth_1h > 0.001:
            bull.append(f"holders growing (+{holder_growth_1h*100:.2f}%/1h) - adoption accelerating")
        elif holder_growth_1h < -0.001:
            bear.append(f"holders shrinking ({holder_growth_1h*100:.2f}%/1h) - distribution")

    if liq_change_1h is not None and liq_change_1h > 0.02:
        bull.append(f"liquidity rising (+{liq_change_1h*100:.1f}%/1h) - LPs adding depth")
    elif liq_change_1h is not None and liq_change_1h < -0.02:
        bear.append(f"liquidity draining ({liq_change_1h*100:.1f}%/1h) - LPs pulling (exit-slippage risk)")

    if buy_ratio is not None:
        if buy_ratio >= 0.55:
            bull.append(f"buy-side pressure ({buy_ratio*100:.0f}% of 24h txns are buys) - "
                        f"CURRENT STATE only, ~50% predictive at best")
        elif buy_ratio <= 0.45:
            bear.append(f"sell-side pressure ({buy_ratio*100:.0f}% of 24h txns are buys) - "
                        f"CURRENT STATE only, ~50% predictive at best")

    unknown.append("24h holder/organic-influx trend is still MATURING (the forward collector is young - "
                   "holder_growth_24h / organic_buyer_influx_24h not yet populated)")
    if daily_vol:
        unknown.append(f"this coin swings ~{daily_vol:.1f}%/day - a spot bag can round-trip fast (no liq, "
                       f"but no floor either)")
    unknown.append("DIRECTION ITSELF - no signal here predicts which way it goes; your read is the edge")
    return bull, bear, unknown


# ---------------------------------------------------------------------------
# The disclaimer footer - the load-bearing honesty line, printed on every brief
# ---------------------------------------------------------------------------

def _disclaimer_lines(symbol: str) -> List[str]:
    symbol = safe_symbol(symbol)
    return [
        "-" * 60,
        "HONESTY: everything above is MEASURED CONTEXT (what IS), never a prediction (what WILL be).",
        f"Nothing here tells you which way {symbol} goes. The project has PROVEN that no mechanical",
        "signal predicts direction on this data (SIGNAL_SCORECARD.md) - your discretion is the edge.",
        "The BULL vs BEAR columns are a STRUCTURING device built from the SAME numbers, NOT a",
        "recommendation. The directional read is YOURS; this tool has no validated directional edge.",
    ]


# ---------------------------------------------------------------------------
# HL brief
# ---------------------------------------------------------------------------

def build_hl_eye(client, symbol: str, equity: float, deep: bool = False) -> EyeBrief:
    eb = EyeBrief(symbol=symbol, instrument_type="HL_PERP")
    dip = build_dip_read(client, symbol)
    if not dip.ok:
        # THIN-COIN GRACEFUL DEGRADE (--deep only): a young HL coin (e.g. CASHCAT,
        # ~27 daily candles) fails the shallow read (build_dip_read needs >=30
        # daily). Rather than bail "NO DATA", the deep view still shows LIVE price
        # + whatever trend IS available + magnets + funding + mint-keyed
        # accumulation, and says honestly it's too young for reliable levels.
        if deep:
            try:
                import eye_deep  # noqa: E402  (local import, reuse not duplicate)
                lines, _px = eye_deep.hl_degraded_lines(symbol)
            except Exception as e:  # noqa: BLE001 - deep is additive, never crash the brief
                print(f"[eye] deep degrade failed for {symbol}: {e}", file=sys.stderr)
                lines = []
            if lines:
                L = eb.lines
                L.append(f"EYE (DEEP): {safe_symbol(symbol)} - HL PERP - YOUNG COIN, shallow read unavailable "
                         f"({dip.data_note or 'insufficient history'}); showing what IS measurable.")
                L.append("")
                L.extend(lines)
                L.append("")
                L.extend(_disclaimer_lines(symbol))
                return eb
        eb.ok = False
        eb.note = dip.data_note or f"no HL data for {symbol}"
        return eb

    hl_max = fetch_hl_max_leverage(client, symbol)
    # a representative liq read (1x) purely for the ATR/vol yardstick context;
    # no leverage is recommended here - `call` owns that.
    liq = compute_liquidation(dip.price, DEFAULT_SIDE, 1.0, dip.vol, hl_max, symbol,
                              hold_days=MAX_HOLD_DAYS_RANGE[1])

    L = eb.lines
    L.append(f"EYE: {safe_symbol(symbol)} - HL PERP (pre-decision analyst brief; direction is NOT called here)")
    L.append("")

    # ---- 1. WHERE IT IS ----
    L.append("1) WHERE IT IS (price vs the levels that matter):")
    adx_s = f"{dip.adx_1d:.0f}" if dip.adx_1d is not None else "?"
    L.append(f"  Price {_fmt_price(dip.price)} | {_fmt_pct(dip.ret_1d_pct)}/1d, {_fmt_pct(dip.ret_7d_pct)}/7d")
    if getattr(dip, "structure_note", ""):
        L.append(f"  Daily: {dip.structure_note}")
    else:
        L.append(f"  Daily: {dip.trend_1d.upper()} ({dip.trend_strength}, ADX {adx_s})")
    if dip.swing_high and dip.swing_low:
        span = dip.swing_high - dip.swing_low
        pos = (dip.price - dip.swing_low) / span * 100.0 if span > 0 else None
        L.append(f"  20d range {_fmt_price(dip.swing_low)} .. {_fmt_price(dip.swing_high)}  ->  "
                 f"you're {_range_label(pos)}"
                 + (f" ({pos:.0f}%)" if pos is not None else ""))
        if dip.dist_to_high_pct is not None and dip.dist_to_low_pct is not None:
            L.append(f"    {dip.dist_to_high_pct:.1f}% below the 20d high, {dip.dist_to_low_pct:.1f}% above the 20d low "
                     f"- so the recent move has {'mostly happened (chasing)' if (pos or 0) >= 70 else 'room / you are early' if (pos or 0) <= 30 else 'partly happened'}.")
    # indicators, framed honestly
    bb = f"{dip.bb_pos_1d:.2f}" if dip.bb_pos_1d is not None else "n/a"
    rsi = f"{dip.rsi_1d:.0f}" if dip.rsi_1d is not None else "n/a"
    atr = f"{dip.atr_pct_1d*100:.1f}%/day" if dip.atr_pct_1d else "n/a"
    L.append(f"  RSI {rsi} (momentum/stretch, NOT a reversal timer - the dip-timing edge decayed to noise OOS) | "
             f"BB pos {bb} (0=lower band, 1=upper) | ATR {atr} (typical daily swing) | ADX {adx_s} (trend strength)")
    L.append("")

    # ---- 2. THE TRAP ----
    L.append("2) THE TRAP (what can catch a levered entry - risk/path context, NOT direction):")
    notional_ctx = equity  # 1x reference notional for the funding $/day framing
    L.append("  " + _funding_direction_note(dip, DEFAULT_SIDE, notional_ctx))
    funding_positive: Optional[bool] = None
    if dip.funding_rate is not None:
        if dip.funding_rate > 1e-9:
            funding_positive = True
        elif dip.funding_rate < -1e-9:
            funding_positive = False
    cl = liq_cluster_for_symbol(symbol)
    L.append("  " + _liq_cluster_line(symbol, cl))
    beta = None
    try:
        from book import build_return_frame, compute_beta_to_btc  # local import (reuse, no dup math)
        frame, _notes = build_return_frame(client, sorted({symbol, "BTC"}), 150)
        beta = compute_beta_to_btc(frame, symbol)
    except Exception as e:  # noqa: BLE001 - beta is a nicety, never break the brief
        print(f"[eye] beta-to-BTC unavailable for {symbol}: {e}", file=sys.stderr)
    if beta is not None:
        proxy = ("this is largely a BTC proxy - its direction is mostly BTC's" if abs(beta) >= 1.2
                 else "moderately BTC-correlated" if abs(beta) >= 0.6
                 else "relatively idiosyncratic vs BTC")
        L.append(f"  Beta-to-BTC ~{beta:.2f} ({proxy}). If you already hold BTC-correlated longs, this is not a fresh, "
                 f"independent bet - run `cli.py book` to see combined risk.")
    else:
        L.append("  Beta-to-BTC: unavailable (thin overlapping history).")
    L.append("")

    # ---- 3. BULL vs BEAR ----
    bull, bear, unknown = _hl_bull_bear(dip, funding_positive, beta, cl)
    L.extend(_format_bull_bear(bull, bear, unknown))
    L.append("")

    # ---- 3b. DEEP STRUCTURE (--deep only): the measured price-action map ----
    if deep:
        L.extend(_append_deep_hl(symbol))
        L.append("")

    # ---- 4. call pointer ----
    L.append("Once you've decided a direction:")
    L.append(f"  `cli.py call {safe_symbol(symbol)} <long|short> \"your reason\"` gives the survive-the-trade risk math "
             f"(safe leverage, liq price, size, disaster stop) and logs YOUR call for forward evidence.")
    L.append("")
    L.extend(_disclaimer_lines(symbol))
    return eb


def _append_deep_hl(symbol: str) -> List[str]:
    """The HL deep structural block (multi-TF trend, swing S/R with touch counts,
    volume, liq magnets, funding/OI). Additive - never crashes the brief."""
    try:
        import eye_deep  # noqa: E402
        lines, _px = eye_deep.hl_deep_lines(symbol)
        return lines or ["DEEP STRUCTURE: live HL candles unavailable this run - deep layer degraded."]
    except Exception as e:  # noqa: BLE001
        print(f"[eye] deep HL layer failed for {symbol}: {e}", file=sys.stderr)
        return ["DEEP STRUCTURE: unavailable this run (deep layer error)."]


# ---------------------------------------------------------------------------
# DEX-spot meme brief
# ---------------------------------------------------------------------------

def build_spot_eye(symbol: str, equity: float, deep: bool = False) -> EyeBrief:
    eb = EyeBrief(symbol=symbol, instrument_type="DEX_SPOT")
    mm = resolve_mint(symbol)
    if mm.mint is None:
        eb.ok = False
        eb.note = mm.note
        return eb

    wash = _latest_row_for_mint(WASH_PATH, mm.mint) or {}
    liqsnap = _latest_row_for_mint(LIQ_SNAP_PATH, mm.mint) or {}
    flow = _latest_row_for_mint(FLOW_PATH, mm.mint) or {}

    _snap_ts, snap_age_h = _snapshot_age_hours([wash, liqsnap, flow])
    snap_stale = snap_age_h is not None and snap_age_h > SNAPSHOT_STALE_WARN_HOURS

    ohlcv_rows = _read_ohlcv_daily(mm.ohlcv_day_path)
    settled_close, settled_date = _settled_from_ohlcv(ohlcv_rows)
    daily_vol = _daily_vol_pct_from_ohlcv(ohlcv_rows)

    organic = wash.get("organic_score", mm.organic_score)
    holders = wash.get("holder_count", flow.get("holder_count"))
    liquidity = liqsnap.get("liquidity_usd", mm.liquidity_usd)
    price = liqsnap.get("price_usd") or flow.get("price_usd")
    if price is None and ohlcv_rows:
        price = ohlcv_rows[-1][1]
    vol_h24 = liqsnap.get("volume_h24")

    # recent close-range position
    price_pos = None
    lo = hi = None
    recent = [c for _d, c in ohlcv_rows[-RANGE_LOOKBACK_D:] if c and c > 0]
    if len(recent) >= 5 and isinstance(price, (int, float)):
        lo, hi = min(recent), max(recent)
        if hi > lo:
            price_pos = max(0.0, min(100.0, (price - lo) / (hi - lo) * 100.0))

    L = eb.lines
    L.append(f"EYE: {safe_symbol(symbol)} - DEX SPOT (pre-decision analyst brief; NO leverage/liq; direction is NOT called here)")
    L.append(f"  Mint: {mm.mint}")
    if mm.ambiguous:
        L.append(f"  >>> AMBIGUOUS SYMBOL: {mm.note} <<<")
    L.append(f"  {_freshness_line(snap_age_h)}")
    L.append("")

    # ---- 1. WHERE IT IS ----
    L.append("1) WHERE IT IS (price vs recent range):")
    L.append(f"  Price {_fmt_price(price)}"
             + (f" | daily vol ~{daily_vol:.1f}%" if daily_vol else " | daily vol n/a")
             + (f" | last settled close {_fmt_price(settled_close)} ({settled_date})" if settled_close else ""))
    if price_pos is not None:
        L.append(f"  {RANGE_LOOKBACK_D}d close range {_fmt_price(lo)} .. {_fmt_price(hi)}  ->  "
                 f"you're {_range_label(price_pos)} ({price_pos:.0f}%) - the recent move has "
                 f"{'mostly happened (chasing)' if price_pos >= 70 else 'room / you are early' if price_pos <= 30 else 'partly happened'}.")
    else:
        L.append(f"  {RANGE_LOOKBACK_D}d range: insufficient OHLCV on disk yet (collector young) - range read degraded.")
    L.append("")

    # ---- 2. IS IT REAL ----
    L.append("2) IS IT REAL (wash/health - the honest 'realness' check):")
    if organic is not None:
        if organic < 30:
            health = f"organic_score {organic:.0f}/100 - LOW: volume looks largely inorganic/wash. Treat with suspicion."
        elif organic < 55:
            health = f"organic_score {organic:.0f}/100 - MEDIUM: some real flow, still thin."
        else:
            health = f"organic_score {organic:.0f}/100 - HEALTHY-ish: genuinely traded (55+ = real flow, not wash/dead)."
        L.append(f"  Health: {health}")
    else:
        L.append("  Health: organic_score unavailable for this mint (degraded) - assume unproven, size small.")
    hg_bits = []
    for k, lbl in (("holder_growth_1h", "1h"), ("holder_growth_6h", "6h"), ("holder_growth_24h", "24h")):
        v = flow.get(k)
        if v is not None:
            hg_bits.append(f"{lbl} {v*100:+.2f}%")
    holders_s = f"{holders:,}" if isinstance(holders, (int, float)) else "n/a"
    L.append(f"  Holders: {holders_s}"
             + (f" | trend " + ", ".join(hg_bits) if hg_bits else " | holder trend still maturing (collector young)"))
    if liquidity:
        size = TYPICAL_MEME_SIZE_USD
        slip_pct = estimate_amm_slippage_pct(size, liquidity)  # constant-product one-way est
        slip = ""
        if slip_pct is not None:
            tag = ("SEVERE, moves the market" if slip_pct >= SLIPPAGE_SEVERE_PCT
                   else "notable, scale in" if slip_pct >= SLIPPAGE_NOTABLE_PCT else "manageable")
            slip = (f" -> a ~${size:,.0f} entry est ~{slip_pct:.1f}% one-way slippage ({tag}); "
                    f"~{SLIPPAGE_NOTABLE_PCT:.0f}%-slippage size ~${liquidity*SLIPPAGE_NOTABLE_PCT/200.0:,.0f} (constant-product)")
        L.append(f"  Liquidity: ${liquidity:,.0f} pool"
                 + (f", 24h vol ${vol_h24:,.0f}" if vol_h24 else "") + slip)
    else:
        L.append("  Liquidity: unavailable (degraded) - keep any entry very small.")
    L.append("")

    # ---- 3. FLOW RIGHT NOW ----
    _flow_when = "AS OF A STALE SNAPSHOT (see freshness warning above)" if snap_stale else "RIGHT NOW"
    L.append(f"3) FLOW {_flow_when} (attention/current-state, ~50% predictive at best - NOT direction):")
    buy_ratio = flow.get("txns_buy_sell_ratio_24h")
    vol_accel = flow.get("vol_accel_1h_vs_24h")
    liq_change_1h = flow.get("liq_change_1h")
    _lean_when = "as of the stale snapshot" if snap_stale else "RIGHT NOW"
    fbits = []
    if buy_ratio is not None:
        fbits.append(f"buy/sell txns 24h: {buy_ratio*100:.0f}% buys "
                     f"({'buy' if buy_ratio >= 0.5 else 'sell'}-leaning {_lean_when})")
    if vol_accel is not None:
        state = "building" if vol_accel > 1.2 else "fading" if vol_accel < 0.8 else "steady"
        fbits.append(f"vol accel 1h-vs-24h: {vol_accel:.2f}x ({state})")
    if liq_change_1h is not None:
        fbits.append(f"liquidity {liq_change_1h*100:+.1f}%/1h")
    if fbits:
        for b in fbits:
            L.append(f"  {b}")
        L.append("  (Flow is CURRENT STATE, not a forecast - attention, not direction. The scorecard puts "
                 "flow/mover reads at ~50% next-day.)")
    else:
        L.append("  Flow deltas not yet populated for this mint (forward collector is young) - degraded.")
    L.append("")

    # ---- 4. BULL vs BEAR ----
    bull, bear, unknown = _meme_bull_bear(price_pos, organic, holders,
                                          flow.get("holder_growth_1h"), liq_change_1h,
                                          buy_ratio, vol_accel, daily_vol)
    L.extend(_format_bull_bear(bull, bear, unknown))
    L.append("")

    # ---- 4b. DEEP STRUCTURE (--deep only): recent-window levels + mint-keyed
    # accumulation trajectory (holders/organic/liquidity over OUR snapshots).
    if deep:
        try:
            import eye_deep  # noqa: E402
            L.extend(eye_deep.meme_deep_lines(mm, symbol, price))
        except Exception as e:  # noqa: BLE001 - additive, never crash the brief
            print(f"[eye] deep meme layer failed for {symbol}: {e}", file=sys.stderr)
            L.append("DEEP STRUCTURE: unavailable this run (deep layer error).")
        L.append("")
    L.extend(_disclaimer_lines(symbol))
    return eb


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def build_eye(symbol: str, equity: float = DEFAULT_EQUITY_USD, client=None, deep: bool = False) -> EyeBrief:
    sym = _norm_symbol(symbol)
    client = client or _get_hl_client()
    if is_hl_listed(client, sym):
        return build_hl_eye(client, sym, equity, deep=deep)
    return build_spot_eye(sym, equity, deep=deep)


def format_eye(eb: EyeBrief) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = [f"=== WAGMI EYE (pre-decision) - {safe_symbol(eb.symbol)} - {ts} ==="]
    if not eb.ok:
        head.append(f"NO DATA: {eb.note}")
        head.append("")
        head.extend(_disclaimer_lines(eb.symbol))
        return "\n".join(head)
    return "\n".join(head + [""] + eb.lines)


# ---------------------------------------------------------------------------
# SCAN mode (no symbol) - the STRUCTURAL-SETUP FINDER: "coins currently in a
# notable state - worth YOUR eyes, ranked by activity - NOT buy signals". Two
# transparently-ranked buckets, each an ATTENTION/CONTEXT list, NEVER a
# direction call (the project has proven ~50% next-day at best):
#   1) HL STRUCTURAL STATE - perps near a well-tested swing level / with volume
#      expanding / at a range edge. Candidate pool = whats_moving Stage-1
#      survivors cheap-ranked by |24h%|, candle-enriched via eye_deep's verified
#      swings()/cluster_levels()/volume machinery. Ranked by volume expansion.
#   2) MICRO-CAP ACCUMULATING - genuinely-traded memes (organic>=40) with an
#      accelerating holder pulse + rising liquidity, from flow_signal.jsonl
#      (local, no network), mint-keyed via resolve_mint so wash clones can't
#      pollute. Ranked by holder-growth rate.
# Every symbol printed is run through safe_symbol() so a Unicode BIDI/control
# char in an untrusted feed value can never spoof which coin is shown.
# ---------------------------------------------------------------------------

def _latest_flow_per_mint() -> List[dict]:
    """Latest flow_signal row per mint (reads the jsonl directly, same posture
    as owner_call - avoids importing the collector's logging side effects)."""
    latest: Dict[str, dict] = {}
    for r in _iter_jsonl(FLOW_PATH):
        m = r.get("mint")
        if not m:
            continue
        ts = r.get("ts_utc") or ""
        if m not in latest or ts >= (latest[m].get("ts_utc") or ""):
            latest[m] = r
    return list(latest.values())


# --- structural-scan knobs (documented, not magic) ---
STRUCT_POOL = 24                # Stage-1 survivors (cheap-ranked by |24h%|) that get candle-enriched
STRUCT_NEAR_LEVEL_PCT = 0.015   # within 1.5% of a tested level = "price is at a decision point"
STRUCT_MIN_TOUCHES = 2          # a swing level needs >=2 pivots on it before we call it "tested"
STRUCT_VOL_EXPAND = 1.3         # last-3d vs prior-7d daily volume ratio to count as "expanding"
STRUCT_RANGE_EDGE_PCT = 15.0    # within 15% of the 90d range low/high = "at a range edge"


# Prefer the 6h delta over the noisier 1h once it's populated (the forward flow
# collector matured ~2026-08-07 so 6h/24h windows now carry data). 1h holder-
# growth is a few-wallet coin-flip; 6h is a real adoption trend. Fall back to 1h
# only when 6h isn't on the row yet.
def _robust_growth(r: dict) -> Optional[float]:
    v = r.get("holder_growth_6h")
    return v if v is not None else r.get("holder_growth_1h")


def _robust_liq_change(r: dict) -> Optional[float]:
    v = r.get("liq_change_6h")
    return v if v is not None else r.get("liq_change_1h")


def scan_memes(top: int = 8) -> List[dict]:
    """MICRO-CAP ACCUMULATING: genuinely-traded coins (organic_score >= 40, wash
    excluded) with an ACCELERATING holder pulse AND RISING liquidity, measured on
    the 6h window where available (falls back to 1h). Mint-keyed via resolve_mint
    so wash clones that share a symbol never pollute the read. ATTENTION only -
    explicitly NOT a buy list, NOT a direction call. Ranked by holder-growth rate."""
    rows = _latest_flow_per_mint()
    cands = []
    for r in rows:
        organic = r.get("organic_score")
        hg = _robust_growth(r)                        # 6h if present, else 1h
        liq = r.get("liquidity_usd")
        liq_ch = _robust_liq_change(r)                # 6h if present, else 1h
        if organic is None or organic < 40:          # wash/dead or unproven -> out (organic shown so it's visible)
            continue
        if hg is None or hg <= 0:                     # holders must be ACCELERATING, not flat/shrinking
            continue
        if not liq:                                   # need a live liquidity number to reason about
            continue
        if liq_ch is None or liq_ch <= 0:             # liquidity must be RISING (LPs adding, not pulling)
            continue
        cands.append(r)

    # Mint-keyed de-dup: a symbol can map to several mints (KITTY = 3, one real +
    # wash clones). Collapse each symbol to the genuinely-traded mint resolve_mint
    # prefers, so a clone can never take a slot from - or be confused with - the
    # real coin. (Filters above already drop 0-organic clones; this is the belt.)
    by_symbol: Dict[str, List[dict]] = {}
    for r in cands:
        by_symbol.setdefault(str(r.get("symbol") or "").upper(), []).append(r)
    deduped: List[dict] = []
    for _sym, group in by_symbol.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        try:
            mm = resolve_mint(group[0].get("symbol") or "")
        except Exception as e:  # noqa: BLE001 - resolution is a nicety; degrade to best-organic
            print(f"[eye] mint resolve failed for {_sym}: {e}", file=sys.stderr)
            mm = None
        chosen = None
        if mm is not None and mm.mint:
            chosen = next((g for g in group if g.get("mint") == mm.mint), None)
        if chosen is None:  # resolver couldn't pin it - keep the highest-organic row (most likely real)
            chosen = max(group, key=lambda g: g.get("organic_score") or 0.0)
        deduped.append(chosen)

    deduped.sort(key=lambda r: _robust_growth(r) or 0.0, reverse=True)
    return deduped[:top]


def _structural_state_for_symbol(symbol: str) -> Optional[dict]:
    """Candle-enrich ONE HL symbol into its structural state using eye_deep's
    verified machinery (hl_candles / swings / cluster_levels). Returns a dict with
    price, volume ratio, nearest TESTED swing level (+touch count), and range
    position - or None if candles are unavailable. Pure MEASUREMENT, no direction."""
    import eye_deep  # local import (reuse, not duplicate) - additive, never crash the scan
    d1 = eye_deep.hl_candles(symbol, "1d", 90 * 86400000)
    h1 = eye_deep.hl_candles(symbol, "1h", 20 * 86400000)
    if not d1 and not h1:
        return None
    px = (h1[-1]["c"] if h1 else d1[-1]["c"])
    if not px or px <= 0:
        return None
    st: dict = {"symbol": symbol, "price": px, "vol_ratio": None, "level": None,
                "level_touch": None, "level_kind": None, "level_dist_pct": None,
                "range_pos": None, "flags": []}

    # volume trend (last-3d vs prior-7d daily) - the transparent ranking metric
    if len(d1) >= 10:
        v_recent = sum(c["v"] for c in d1[-3:]) / 3.0
        v_prior = sum(c["v"] for c in d1[-10:-3]) / 7.0
        if v_prior > 0:
            st["vol_ratio"] = v_recent / v_prior

    # nearest TESTED swing level (support or resistance) within tolerance
    if len(h1) >= eye_deep.MIN_HOURLY_FOR_LEVELS:
        hi, lo = eye_deep.swings(h1)
        levels = ([(lv, t, "resistance") for lv, t in eye_deep.cluster_levels(hi)]
                  + [(lv, t, "support") for lv, t in eye_deep.cluster_levels(lo)])
        best = None  # (touch, -dist, lv, kind, dist_pct)
        for lv, t, kind in levels:
            if t < STRUCT_MIN_TOUCHES or lv <= 0:
                continue
            dist = abs(lv - px) / px
            if dist <= STRUCT_NEAR_LEVEL_PCT:
                key = (t, -dist)  # prefer more touches, then closer
                if best is None or key > (best[0], best[1]):
                    best = (t, -dist, lv, kind, dist * 100.0)
        if best is not None:
            st["level_touch"], _, st["level"], st["level_kind"], st["level_dist_pct"] = best

    # position within the 90d daily range (0 = range low, 100 = range high)
    if len(d1) >= 5:
        rng_hi = max(c["h"] for c in d1)
        rng_lo = min(c["l"] for c in d1)
        if rng_hi > rng_lo:
            st["range_pos"] = max(0.0, min(100.0, (px - rng_lo) / (rng_hi - rng_lo) * 100.0))

    # which notable states this coin is in (a coin qualifies if ANY fire)
    if st["level"] is not None:
        st["flags"].append("near tested level")
    if st["vol_ratio"] is not None and st["vol_ratio"] >= STRUCT_VOL_EXPAND:
        st["flags"].append("volume expanding")
    if st["range_pos"] is not None and (st["range_pos"] >= (100 - STRUCT_RANGE_EDGE_PCT)
                                        or st["range_pos"] <= STRUCT_RANGE_EDGE_PCT):
        st["flags"].append("at range edge")
    return st


def scan_hl_structural(client, top: int = 8, pool: int = STRUCT_POOL
                       ) -> Tuple[List[dict], int, int]:
    """HL perps currently in a NOTABLE STRUCTURAL STATE: near a well-tested swing
    level, and/or volume expanding, and/or at a range edge. Candidate pool =
    whats_moving Stage-1 survivors (volume+OI floor) cheap-ranked by |24h%|, then
    candle-enriched via eye_deep. Ranked by VOLUME EXPANSION (transparent activity
    metric, NOT edge). Returns (states, total_universe, survivors). Path/decision
    CONTEXT only - it never says which way price breaks."""
    try:
        from whats_moving import apply_liquidity_floor, fetch_universe
    except Exception as e:  # noqa: BLE001
        print(f"[eye] HL structural scan unavailable: {e}", file=sys.stderr)
        return [], 0, 0
    raw = fetch_universe(client)
    survivors, _rej = apply_liquidity_floor(raw)
    survivors.sort(key=lambda r: abs(r.get("pct_24h") or 0.0), reverse=True)
    states: List[dict] = []
    for r in survivors[:pool]:
        try:
            st = _structural_state_for_symbol(r["symbol"])
        except Exception as e:  # noqa: BLE001 - one bad coin never sinks the scan
            print(f"[eye] structural enrich failed for {r.get('symbol')}: {e}", file=sys.stderr)
            continue
        if st and st["flags"]:
            st["pct_24h"] = r.get("pct_24h")
            states.append(st)
    # rank by volume expansion (transparent); no-volume coins sink to the bottom
    states.sort(key=lambda s: (s["vol_ratio"] if s["vol_ratio"] is not None else -1.0), reverse=True)
    return states[:top], len(raw), len(survivors)


def run_scan(top: int = 8, client=None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"=== WAGMI EYE - SCAN (structural setup finder) - {ts} ===",
         "Coins currently in a NOTABLE STATE - worth YOUR eyes, ranked by ACTIVITY - NOT buy signals, NOT direction.",
         "The project has PROVEN no mechanical signal predicts direction (~50% next-day at best). Your read is the edge.",
         ""]

    # --- Bucket 1: HL structural state (candle-enriched from the live universe) ---
    L.append("HL STRUCTURAL STATE (price at a decision point: near a tested swing level / volume expanding / range edge):")
    L.append("  ranked by VOLUME EXPANSION (last-3d vs prior-7d daily volume) - a transparent activity metric, NOT edge.")
    client = client or _get_hl_client()
    states, total, surv = scan_hl_structural(client, top=top)
    if not states:
        if total == 0:
            L.append("  (HL universe read unavailable this run - structural bucket could not populate.)")
        else:
            L.append(f"  (universe {total} perps, {surv} cleared the volume+OI floor; none of the top {STRUCT_POOL} "
                     f"by 24h move are near a tested level / expanding volume / at a range edge right now.)")
    else:
        L.append(f"  (candidate pool = top {STRUCT_POOL} of {surv} floor-survivors by |24h move|, then candle-enriched; "
                 f"a quietly-coiling coin with a flat 24h can be missed - honest limitation.)")
        for i, s in enumerate(states, 1):
            vr = s.get("vol_ratio")
            vr_s = (f"vol {vr:.2f}x ({'expanding' if vr >= STRUCT_VOL_EXPAND else 'flat' if vr >= 0.9 else 'fading'})"
                    if vr is not None else "vol n/a")
            if s.get("level") is not None:
                lvl_s = (f"near tested {s['level_kind']} {_fmt_price(s['level'])} "
                         f"({s['level_dist_pct']:.1f}% away, x{s['level_touch']} touches)")
            else:
                lvl_s = "no tested level within 1.5%"
            rp = s.get("range_pos")
            rng_s = f"range {rp:.0f}%" if rp is not None else "range n/a"
            L.append(
                f"  {i}. {safe_symbol(s['symbol']):<11} {_fmt_price(s['price'])} | {vr_s} | {lvl_s} | "
                f"{rng_s} | {_fmt_pct(s.get('pct_24h'))} 24h"
            )
        L.append("  (STRUCTURAL context: price is at a level / activity is elevated = a DECISION POINT, "
                 "NOT a prediction of which way it breaks. Run `eye SYMBOL --deep` for the full structural map.)")
    L.append("")

    # --- Bucket 2: micro-cap accumulating (local flow data, mint-keyed) ---
    L.append("MICRO-CAP ACCUMULATING (accelerating holders + healthy organic + rising liquidity; mint-keyed, wash excluded):")
    L.append("  ranked by HOLDER-GROWTH rate (6h where available, else 1h) - a transparent adoption-velocity metric, NOT edge.")
    memes = scan_memes(top)
    if not memes:
        L.append("  (nothing currently clears organic>=40 + growing-holders + rising-liquidity - "
                 "nothing is accumulating right now.)")
    else:
        for i, r in enumerate(memes, 1):
            org = r.get("organic_score")
            # show the robust (6h-preferred) window so a 1h coin-flip doesn't headline
            hg6 = r.get("holder_growth_6h")
            hg = hg6 if hg6 is not None else r.get("holder_growth_1h")
            hg_win = "6h" if hg6 is not None else "1h"
            lc6 = r.get("liq_change_6h")
            lc = lc6 if lc6 is not None else r.get("liq_change_1h")
            lc_win = "6h" if lc6 is not None else "1h"
            liq = r.get("liquidity_usd")
            br = r.get("txns_buy_sell_ratio_24h")
            va = r.get("vol_accel_1h_vs_24h")
            L.append(
                f"  {i}. {safe_symbol(r.get('symbol')):<12} organic {org:.0f} | "
                f"holders {r.get('holder_count') or 0:>8,} ({hg*100:+.3f}%/{hg_win}) | "
                f"liq ${liq:,.0f} ({lc*100:+.2f}%/{lc_win})"
                + (f" | {br*100:.0f}% buys" if br is not None else "")
                + (f" | vol accel {va:.2f}x" if va is not None else "")
            )
        L.append("  (Every item shows organic_score so wash is visible - <40 is excluded. Genuinely-traded coins "
                 "with an adoption + liquidity pulse. NOT a prediction they go up. Run `eye SYMBOL` for the full picture.)")
    L.append("")

    L.append("-" * 60)
    L.append("HONESTY: this scan surfaces ACTIVITY / STRUCTURAL STATE, never edge or direction. No entry here is a buy signal.")
    L.append("Attention/activity, NOT direction - ~50% next-day at best; your read is the edge.")
    L.append("The project has PROVEN no mechanical signal predicts direction - your discretion is the edge.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="eye.py",
        description="WAGMI Co-Pilot EYE: a PRE-DECISION analyst brief on a coin you're eyeing "
                    "(counterpart to `call`, which is AT-decision). MEASURED CONTEXT, never a "
                    "prediction - it NEVER tells you which way the coin goes. read-only, writes nothing. "
                    "No symbol = SCAN mode (attention list).",
    )
    ap.add_argument("symbol", nargs="?", help="e.g. SOL, POPCAT, KITTY. Omit for SCAN mode.")
    ap.add_argument("--deep", action="store_true",
                    help="add the DEEP STRUCTURAL layer: multi-TF trend, swing S/R with touch counts, "
                         "volume trend, liq magnets, funding/OI trajectory (HL); recent-window levels + "
                         "mint-keyed accumulation trajectory (memes). MEASURED STRUCTURE, never direction.")
    ap.add_argument("--equity", type=float, default=DEFAULT_EQUITY_USD,
                    help=f"account equity USD, for human-scale slippage/notional framing only (default {DEFAULT_EQUITY_USD:.0f})")
    ap.add_argument("--top", type=int, default=8, help="SCAN mode: how many attention names to list (default 8)")
    args = ap.parse_args()

    if not args.symbol:
        print(run_scan(top=args.top))
        return
    eb = build_eye(args.symbol, equity=args.equity, deep=args.deep)
    print(format_eye(eb))


if __name__ == "__main__":
    main()
