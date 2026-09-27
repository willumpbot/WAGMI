#!/usr/bin/env python
"""
WAGMI Co-Pilot - MARKET WEATHER context layer - weather.py
=============================================================================
A daily, market-wide "weather" read for ALT LONGS - a CONTEXT/CAUTION-WEIGHT
signal, NEVER a trigger and NEVER a block. It does not change the ADD/HOLD/
WAIT call in copilot.py; it only adds one line at the TOP of the brief (once
per run, not per coin) so the owner's own discretion is informed by the
broader regime before reading the per-coin calls below it.

READ-ONLY / STANDALONE, same constraints as every other tools/copilot/*.py
module: only imports copilot.py's public fetch/indicator helpers (no
duplicated fetch/EMA math), reads data/longtail/universe.json + the longtail
OHLC CSVs (already-collected, not a new feed), and never imports live-bot
packages (llm/, execution/, core/, strategies/) or touches live/.env/
data/replay.

WHAT IT MEASURES
-----------------
Two instruments, both computed entry-time-safe from the LATEST CLOSED daily
candle (the in-progress "today" candle, if the fetch/CSV happens to include
one, is dropped - see `_closed_daily_df`):

  1. breadth20 = % of the alt universe (the ~25 non-major coins tracked in
     data/longtail/universe.json / ohlc/ - BTC, SOL, and thin/majors are
     already excluded upstream by that universe's own screen) whose latest
     closed daily close is above their own 20-day SMA.
  2. BTC vs its own 50-day EMA (above/below).

WHAT IT IS - CONTEXT ONLY: a read on how wide/violent the alt tape is right
now, independent of the per-coin ADD signal. It is NOT a sizing/permission
gate, NOT a trigger, NOT a block, and it does NOT sharpen the ADD/dip call.

  ** OOS STATUS (weather_value_test.py, 2026-07-31) - the old "size by regime"
  framing was REFUTED. A weather-conditioned sizing gate (size down in
  STORMY/HEADWIND, full size in WASHED_OUT) was BEATEN on every OOS tail
  metric by a flat baseline at the same average exposure - i.e. the regime
  TIMING was counterproductive, only the average de-risking helped. The
  per-regime return tilts are era-unstable (they invert in the most recent
  eras). breadth20 carries essentially all the signal; BTC-vs-50dEMA is
  near-redundant for this use. AND the direction was backwards: WASHED_OUT,
  the regime the old code green-lit for a "full tranche", is empirically the
  WIDEST-drawdown regime (CVaR ~-24%, 10-17x more likely to see a 20%+ 5d
  adverse move). So weather is kept ONLY as volatility/attention context. **

  ** It also does NOT stack with ADD/dip: inside washed-out, ADD (dip) days
  UNDERPERFORM non-ADD days by ~-2.6%/3d OOS. The ADD signal stays a mild
  standalone hint, uncoupled from weather. **

THE REGIMES (treat as VOLATILITY CONTEXT, not a directional or sizing call -
the %/3d tilts below are historical, era-unstable, and were refuted as a
tradeable/sizing gate; they are shown only as rough color):

  STORMY      BTC>50dEMA AND breadth>50%        (~21% of days)
              broad alt rally priced in + BTC leading. Historical alt-long
              drag (~-2.3%/3d) is era-unstable - context only, not a call.
  HEADWIND    exactly one of {BTC>50dEMA, breadth>50%} true
              mixed tape; any historical long tilt is small + era-unstable.
  WASHED OUT  BTC<50dEMA AND breadth<20%        (~30% of days)
              CAUTION, NOT a green light: OOS the WIDEST-drawdown regime
              (CVaR ~-24%; 10-17x more likely to see a 20%+ 5d adverse move),
              returns sign-flip across eras. Do NOT upsize into it.
  NEUTRAL     otherwise (BTC<50dEMA, breadth in [20%, 50%])
              no strong read either way.

HONESTY - CONTEXT, not a call, and specifically NOT a validated sizing gate
(that use was refuted OOS). The regime still separates forward VOLATILITY
somewhat (breadth<20% especially - ~2.5x more than trailing-vol terciles), so
it earns its place as an attention/volatility line, but it is era-unstable and
must be re-scored if the tape flips to a sustained alt-BULL regime.

TODO: a funding-regime leg (crowding/positioning across the same universe)
is a natural third instrument here, but there isn't yet enough live funding
history (~6 more months wanted) to validate it the same way breadth/BTC-EMA
were validated - do not add it before that data exists and is backtested.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import _ema, fetch_ohlc, DAYS_1D  # noqa: E402 - reuse, no duplicated fetch/indicator math

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNIVERSE_JSON_PATH = os.path.join(BOT_DIR, "data", "longtail", "universe.json")
LONGTAIL_OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")

BREADTH_SMA_PERIOD = 20
BTC_EMA_PERIOD = 50
MIN_BTC_ROWS = BTC_EMA_PERIOD + 10   # warm-up buffer for a stable EMA50 read

BREADTH_HIGH_PCT = 50.0   # breadth20 strictly above this = "high"
BREADTH_LOW_PCT = 20.0    # breadth20 strictly below this = "low"

WEATHER_TAG = (
    "[VOLATILITY CONTEXT only - refuted OOS as a sizing/direction gate: the "
    "per-regime return tilts sign-flip across eras and a regime sizing rule lost "
    "to a flat baseline. What survives = it separates forward VOLATILITY (breadth "
    "carries it; BTC-EMA near-redundant). NEVER a trigger, block, or size rule; "
    "re-score if the tape flips to a sustained alt-BULL regime.]"
)

# The printed CONTEXT body per regime. HONEST STATUS (weather_value_test.py,
# OOS 2026-07-31): this is CONTEXT ONLY, not a validated sizing/permission
# gate. The old "size up/down by regime" + "WASHED_OUT = safe green-light"
# framing was REFUTED - a weather-conditioned sizing gate was BEATEN by a flat
# same-average-exposure baseline OOS, and the per-regime return tilts are
# era-unstable (they invert in the most recent eras). Worst of all, WASHED_OUT
# - which the old code green-lit for a "full tranche" - is empirically the
# WIDEST-drawdown regime (CVaR ~-24%, 10-17x more likely to see a 20%+ 5d
# adverse move than any other regime). So the bodies below describe regime as
# attention/volatility context and explicitly do NOT tell you to upsize.
_REGIME_BODY = {
    "STORMY": (
        "STORMY (BTC>50dEMA + breadth>50%) - broad alt rally priced in + BTC leading. "
        "CONTEXT ONLY: a historical alt-long drag here (~-2.3%/3d) is era-unstable and "
        "not a reliable directional call. Expect chop; your entry read stands on its own."
    ),
    "HEADWIND": (
        "HEADWIND (one of BTC>50dEMA / breadth>50%) - mixed tape. CONTEXT ONLY: any "
        "historical long tilt here is small and era-unstable; nothing actionable on its own."
    ),
    "WASHED_OUT": (
        "WASHED OUT (BTC<50dEMA + breadth<20%) - CAUTION, NOT a green light: OOS this is "
        "the WIDEST-drawdown regime (CVaR ~-24%, 10-17x more likely to see a 20%+ 5d adverse "
        "move than other regimes), and its returns sign-flip across eras. Do NOT upsize into "
        "it - expect violent two-way moves; if anything, smaller size + wider tolerance."
    ),
    "NEUTRAL": "NEUTRAL - no strong regime read.",
}

# ONE explicit honest line so no one over-combines weather with the dip call.
# An OOS test REFUTED "washed-out makes dips better": inside washed-out, ADD
# (dip) days UNDERPERFORM non-ADD days by ~-2.6%/3d OOS. And the broader
# weather_value_test.py refuted weather as a sizing gate entirely. So weather
# is CONTEXT ONLY - it neither sizes your call nor sharpens the dip signal.
WEATHER_DESTACK_NOTE = (
    "Note: weather is CONTEXT ONLY - not a validated sizing/permission gate (a regime "
    "sizing rule lost to a flat baseline OOS) and it does NOT sharpen the dip call (in "
    "washed-out tapes ADD days ran ~-2.6%/3d OOS vs non-ADD). Read it as 'how wide/violent "
    "is the tape right now', not 'how much to buy'."
)


def session_vol_context(hour_utc: Optional[int] = None) -> str:
    """Time-of-day VOLATILITY context (NOT a directional edge). OOS-validated
    (session_vol_test.py, 2026-07-31): sharp 1h moves are ~25-45% more likely
    in the US session (13-21 UTC), peaking ~14-15 UTC; calmest early-EU/Asia
    (~07 UTC). Magnitude is MODEST (1.2-1.6x mean-move, up to ~2.5x tail-move
    frequency) - but era-stable (top session unchanged across both halves) and
    near-unanimous (26/27 coins incl. memes rank US most-violent). So it earns
    a calibrated risk-context note, NOT a "trade this" claim. Pass the current
    UTC hour to also flag whether you're in the higher-vol window right now."""
    base = (
        "SESSION (volatility context, not direction): sharp 1h moves ~25-45% more likely in the "
        "US session (13-21 UTC, peak ~14-15 UTC); calmest early-EU/Asia (~07 UTC). Modest but era-stable."
    )
    if hour_utc is None:
        return base
    if 14 <= hour_utc <= 15:
        return base + f" >> right now ({hour_utc:02d} UTC) is the PEAK-vol hour - expect sharper moves."
    if 13 <= hour_utc <= 21:
        return base + f" >> right now ({hour_utc:02d} UTC) you're in the higher-vol US window."
    return base + f" >> right now ({hour_utc:02d} UTC) is a calmer window."


@dataclass
class MarketWeather:
    ok: bool = True
    data_note: Optional[str] = None

    regime: str = "NEUTRAL"   # STORMY / HEADWIND / WASHED_OUT / NEUTRAL

    breadth_pct: Optional[float] = None
    breadth_n_up: int = 0
    breadth_n_total: int = 0

    btc_price: Optional[float] = None
    btc_ema50: Optional[float] = None
    btc_above_ema50: Optional[bool] = None

    line: str = ""   # the full one-line MARKET WEATHER string, ready to print


def _closed_daily_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Entry-time-safe guard: daily candles are assumed UTC-midnight-aligned,
    24h duration. Drops the last row if EITHER (a) that candle's close time
    (open + 1d) is still in the future by wall clock, OR (b) its open date
    is not strictly before the current UTC date - i.e. it's today's (or a
    still-forming) candle, not a fully-elapsed prior day.

    (b) is a defense-in-depth hardening added 2026-08-01 alongside the
    original (a): a wall-clock-only check can be satisfied by a
    calendar day that has genuinely elapsed even when that SPECIFIC row's
    underlying data was captured mid-day and frozen incomplete by an
    upstream collector bug (confirmed: research/longtail/backfill.py wrote
    a partial last daily row - about half a full day's volume - whenever it
    ran mid-UTC-day, before it had its own forming-candle guard). Once the
    calendar rolls past that row's day, (a) alone no longer flags it as
    "forming" even though the row was never refreshed with the settled
    data. (b) OR'd alongside (a) is strictly more-or-equally conservative
    (it can only cause MORE rows to be dropped, never fewer) and is the
    simpler, date-only check to reason about — but note it does NOT
    retroactively repair an already-stale row sitting in the CSV; only
    re-running backfill (now with its own forming-candle guard) fetches the
    corrected, fully-settled data for that day. This guard's job is to
    never let a still-open bucket masquerade as data at ALL — same-day
    forming candles, from any source, are covered by both (a) and (b).
    Never raises; passes through None/empty unchanged."""
    if df is None or df.empty:
        return df
    now = datetime.now(timezone.utc)
    last_t = df["t"].iloc[-1]
    if hasattr(last_t, "to_pydatetime"):
        last_t = last_t.to_pydatetime()
    if last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    still_forming_by_clock = last_t + timedelta(days=1) > now
    still_forming_by_date = last_t.date() >= now.date()
    if still_forming_by_clock or still_forming_by_date:
        return df.iloc[:-1].reset_index(drop=True)
    return df


def _load_universe_coins() -> List[str]:
    """Reads the alt-universe coin list from data/longtail/universe.json.
    That universe already excludes BTC/SOL/majors/thin names upstream (its
    own `excluded_majors` + liquidity screen) - no re-filtering needed here.
    Fails soft (empty list) if the file is missing/malformed."""
    try:
        with open(UNIVERSE_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = data.get("names") if isinstance(data, dict) else None
        if not names:
            return []
        return [n["coin"] for n in names if isinstance(n, dict) and n.get("coin")]
    except Exception as e:
        print(f"[copilot] weather: failed to load universe.json: {e}", file=sys.stderr)
        return []


def _load_longtail_1d(coin: str) -> Optional[pd.DataFrame]:
    """Loads the already-collected longtail 1d CSV for `coin` (no new fetch -
    same 'intertwine already-collected data' philosophy as the rest of the
    universe pipeline). Fails soft (None) if missing/malformed."""
    path = os.path.join(LONGTAIL_OHLC_DIR, f"{coin}_1d.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "dt_utc_iso" not in df.columns or "c" not in df.columns:
            return None
        df["t"] = pd.to_datetime(df["dt_utc_iso"], utc=True, errors="coerce")
        df["c"] = pd.to_numeric(df["c"], errors="coerce")
        df = df.dropna(subset=["t", "c"]).sort_values("t").reset_index(drop=True)
        return df if not df.empty else None
    except Exception as e:
        print(f"[copilot] weather: failed to load {coin} longtail CSV: {e}", file=sys.stderr)
        return None


def _classify_regime(btc_above_ema50: bool, breadth_pct: float) -> str:
    """The 4-branch regime map - see module docstring for the measured
    reads behind each branch. Order matters: STORMY and WASHED_OUT are the
    two-condition branches and are checked first; HEADWIND is the
    exactly-one-of-two (XOR) branch; everything else is NEUTRAL."""
    breadth_high = breadth_pct > BREADTH_HIGH_PCT
    breadth_low = breadth_pct < BREADTH_LOW_PCT

    if btc_above_ema50 and breadth_high:
        return "STORMY"
    if (not btc_above_ema50) and breadth_low:
        return "WASHED_OUT"
    if btc_above_ema50 != breadth_high:  # XOR - exactly one of the two true
        return "HEADWIND"
    return "NEUTRAL"


def compute_market_weather(client) -> MarketWeather:
    """Computes the MARKET WEATHER read ONCE per run (it is market-wide, not
    per-coin - callers must compute this a single time and reuse it across
    every symbol's brief, never re-derive it per coin). Never raises - fails
    soft to ok=False with a data_note and a NEUTRAL-labeled 'unavailable'
    line if either instrument can't be computed."""
    mw = MarketWeather()
    notes = []

    # ---- Instrument 1: BTC vs its own 50-day EMA ----
    df_btc = _closed_daily_df(fetch_ohlc(client, "BTC", "1d", DAYS_1D))
    if df_btc is None or len(df_btc) < MIN_BTC_ROWS:
        n = 0 if df_btc is None else len(df_btc)
        notes.append(f"insufficient BTC 1d history for 50d EMA ({n} closed rows)")
    else:
        ema50 = _ema(df_btc["c"], BTC_EMA_PERIOD)
        mw.btc_price = float(df_btc["c"].iloc[-1])
        mw.btc_ema50 = float(ema50.iloc[-1])
        mw.btc_above_ema50 = mw.btc_price > mw.btc_ema50

    # ---- Instrument 2: breadth20 across the alt universe ----
    coins = _load_universe_coins()
    if not coins:
        notes.append("alt universe list unavailable (data/longtail/universe.json)")
    n_up, n_total = 0, 0
    for coin in coins:
        df = _closed_daily_df(_load_longtail_1d(coin))
        if df is None or len(df) < BREADTH_SMA_PERIOD:
            continue
        sma20 = df["c"].rolling(BREADTH_SMA_PERIOD).mean().iloc[-1]
        if pd.isna(sma20):
            continue
        n_total += 1
        if float(df["c"].iloc[-1]) > float(sma20):
            n_up += 1

    if n_total == 0:
        notes.append("insufficient longtail OHLC history for breadth20")
    else:
        mw.breadth_n_up, mw.breadth_n_total = n_up, n_total
        mw.breadth_pct = n_up / n_total * 100.0

    if notes:
        mw.data_note = "; ".join(notes)

    if mw.btc_above_ema50 is None or mw.breadth_pct is None:
        mw.ok = False
        mw.regime = "NEUTRAL"
        mw.line = f"MARKET WEATHER: unavailable ({mw.data_note}). {WEATHER_TAG}"
        return mw

    mw.regime = _classify_regime(mw.btc_above_ema50, mw.breadth_pct)
    btc_bit = "BTC>50dEMA" if mw.btc_above_ema50 else "BTC<50dEMA"
    mw.line = (
        f"MARKET WEATHER: {_REGIME_BODY[mw.regime]} "
        f"(breadth20={mw.breadth_pct:.0f}% [{mw.breadth_n_up}/{mw.breadth_n_total} alts>20dSMA], {btc_bit}) "
        f"{WEATHER_TAG}\n{WEATHER_DESTACK_NOTE}"
    )
    return mw
