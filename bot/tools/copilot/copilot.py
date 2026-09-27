#!/usr/bin/env python
"""
WAGMI Co-Pilot v2 - copilot.py
=============================================================================
A DECISION-SUPPORT tool for a BULLISH LONG-TERM ACCUMULATOR who trades with
leverage. NOT an autonomous trader, NOT part of the live bot pipeline.
Multi-symbol (default: POPCAT + SOL). Generalizes v1 (popcat_copilot.py,
POPCAT-only) after a hard backtest finding overturned v1's core swing logic.

READ-ONLY w.r.t. the live bot: this module never imports live-bot packages
(llm/, execution/, core/, strategies/), never writes to data/replay/, .env,
or any live-bot state file. It only reads market data via the standalone
read-only HL fetcher (data/fetchers/hl_native.py). The liquidation formula
below is a clean REIMPLEMENTATION (not an import) of the approach used in
execution/leverage.py - see LIQUIDATION ASSUMPTIONS below for how/why it
differs (that module carries live bot state; this tool must not touch it).

=============================================================================
WHY v2 EXISTS - THE BACKTEST FINDING THAT OVERTURNED v1
=============================================================================
v1's "swing" half told the owner to TRIM into strength and ADD into weakness,
framed as an accumulation technique ("bank some at highs, buy back cheaper").
A hard backtest of that exact behavior showed it is WRONG for a bullish
accumulator:

    Swing-trimming into strength ("trim highs / add lows") does NOT
    accumulate tokens - it's a DISGUISED EXIT. It only "nets more tokens"
    on paths where the coin FALLS (bear beta). In UP-LEGS - the very moves a
    bullish accumulator is holding FOR - it SURRENDERS tokens and dollars:
    you trim into the pump, drift to cash, and miss the run. Net-of-fees,
    a naive sell-all-day-1 baseline beat the trim-into-strength strategy.

So for someone bullish and accumulating for the long run, the correct
behavior is the OPPOSITE of v1's TRIM call: ADD ON DIPS, HOLD THROUGH
STRENGTH. Don't trim conviction into pumps chasing a "buy it back lower"
that the data shows doesn't pay off net-of-fees.

What v1 got RIGHT and v2 KEEPS, unchanged in substance, and now LEADS the
brief with: the LIQUIDATION / LEVERAGE GUARDRAILS (stay un-liquidated) and
the REGIME-HONESTY GATES (falling-knife = don't add; dead-chop = wait).
Those are risk-management, not a trading edge, and v2 says so explicitly in
its own footer.

TWO FUSED HALVES (v2)
-----------------
1. LEVERAGE / LIQUIDATION GUARDRAILS (still the #1 job, now LED with) -
   standalone liquidation-price estimate, distance-to-liquidation compared
   against THIS COIN's OWN measured volatility (not a generic "keep
   leverage low" rule of thumb - a low-vol coin like SOL correctly clears a
   higher safe leverage than a high-vol coin like POPCAT), a recommended
   MAX SAFE LEVERAGE, a hard-stop price, and a SAFE / RISKY / SUICIDAL
   verdict that can't be missed.

2. DIP-DEPLOYMENT + HOLD DISCIPLINE (reframed from v1's two-way swing call)
   - trend (EMA20/50 + ADX on 1d), position-in-range (Bollinger 20,2 on 1d
   + 1h, swing S/R), RSI(14), realized volatility, funding. Turns that into
   an ADD / HOLD / WAIT call (never a bidirectional swing call):
     - At support / lower-BB / oversold, and NOT a falling knife: ADD ZONE
       - a good spot to deploy the next tranche.
     - At highs / upper-BB / overbought: HOLD - explicitly do NOT chase and
       do NOT trim a conviction hold into strength (that's the disguised
       exit the backtest caught).
     - A TRIM is only ever surfaced as a clearly-labeled DISCRETIONARY,
       OPTIONAL note at a genuine statistical extreme, with a caveat that
       it is a personal risk-tolerance choice, not a proven edge.
   - Falling-knife gate kept: strong downtrend -> don't add, wait for a
     base. Dead-chop gate kept: no real oscillation -> wait, don't trade
     noise.

LIQUIDATION ASSUMPTIONS (v2.1, 2026-07-31 - REAL per-asset HL maintenance
margin, replacing v1/v2's flat 2% approximation - see inline comments at
compute_liquidation)
- Isolated-margin-style approximation: liq_price = entry * (1 - 1/L + mm) for
  longs, entry * (1 + 1/L - mm) for shorts, where mm = maintenance-margin
  fraction for THIS asset.
- mm is now the REAL Hyperliquid per-asset value: mm = 1 / (2 * maxLeverage),
  where maxLeverage is fetched live from HL's `meta` info-API endpoint
  (POST {"type":"meta"}, via data/fetchers/hl_native.py's HLNative.meta()).
  Source/formula verified against Hyperliquid's own docs ("Margining" /
  "Margin tiers", fetched 2026-07-31): "The maintenance margin is currently
  set to half of the initial margin at max leverage" - initial margin at max
  leverage is 1/maxLeverage, so mm = 1/(2*maxLeverage). Confirmed live via
  `meta`: POPCAT maxLeverage=3 -> mm=16.67%; SOL maxLeverage=20 -> mm=2.5%.
  This is MUCH higher than the old flat 2% for a low-max-leverage coin like
  POPCAT, so real liquidation is CLOSER than v1/v2 showed - the safety-tool
  error was in the "you're safer than you think" direction. HL's `meta` also
  exposes per-notional margin TIERS (`marginTables`, keyed by
  `marginTableId`) where maxLeverage steps DOWN at large notional (e.g. SOL
  steps 20x->10x above $70M notional) - irrelevant at this tool's assumed
  account sizes (equity in the $100s-$10Ks), so the top-level `maxLeverage`
  (= tier 0, the tier that actually applies) is used directly without
  walking the full tier table. If the `meta` call fails (network/HL outage),
  fails soft to the flat MAINT_MARGIN_FRAC (0.02) as before, and the brief
  says so explicitly (mm source is never silently swapped without saying
  which one was used).
- Recommended safe-max-leverage is now ALSO capped at the real HL
  `maxLeverage` for that asset - the tool must never recommend a leverage
  the venue won't even let you open (min(vol-derived safe max, HL max)).
- Ignores funding accrual, unrealized PnL on other positions (cross-margin),
  and order-book slippage on the liquidation fill itself - all of which make
  REAL liquidation happen slightly EARLIER than this estimate. Treat the
  numbers here as a slightly-optimistic floor, not a guarantee.

CLI:
    python tools/copilot/copilot.py                          # default: BTC + SOL + POPCAT
    python tools/copilot/copilot.py --symbol SOL              # single symbol
    python tools/copilot/copilot.py --symbol POPCAT,SOL,ETH   # explicit list
    python tools/copilot/copilot.py --leverage 5              # single-leverage risk line at 5x
    python tools/copilot/copilot.py --lev-range 3-15          # range-aware guardrail (default 3-15)
    python tools/copilot/copilot.py --equity 2500 --side short
    python tools/copilot/copilot.py --discord                 # also push to Discord
    python tools/copilot/copilot.py --trade "POPCAT long 3x 800"  # pre-trade fee/funding/liq card (see THEME A)
    python tools/copilot/copilot.py --risk-pct 1 --risk-account 5000  # tune the RISK PLAN's own sizing inputs

RISK PLAN (v2.4, 2026-07-31) - a separate OOS backtest split the trading
playbook into what's MECHANICALLY AUTOMATABLE (survives out-of-sample) vs
what must stay a human's discretionary read. The ADD call above IS the
discretionary half (unchanged - see ADD CALIBRATION below, still just a
timing hint). This adds the AUTOMATABLE half as a concrete "RISK PLAN" block
on every per-coin brief and the --trade card (`compute_risk_plan` /
`format_risk_plan`, reusing DipRead.atr_1d and LiquidationRead - no
re-derivation of vol/leverage math):
  1. Vol-based sizing: notional = risk_$ / (2xATR stop, as a % of price) -
     the size that risks exactly `--risk-pct` (default 1%) of `--risk-account`
     (default $5,000, DELIBERATELY separate from --equity so this never
     changes --equity's existing default/behavior) if the disaster stop hits.
  2. 3-5 day MAX-HOLD time-stop - real, ADDITIVE tail-cutting (OOS: ruin risk
     rises monotonically with hold length; a price stop does NOT replicate it).
     But NOT an optimum - shorter is always safer, so 3-5d is a practical floor
     (thesis-time vs fee/noise churn), not a proven sweet spot. Exit by the
     window regardless of thesis.
  3. 2xATR disaster stop - a loose "I'm wrong" backstop, NOT validated tail
     insurance: risk_mechanics_test.py showed a 2xATR stop at a 3-5d hold is
     ~return-neutral and does not meaningfully cut CVaR/ruin there (it sits
     ~13% out, past the -10% ruin line ~77% of the times it fires; holders beat
     the stop 56-60%). Real tail-cutting lives at ~1-1.5xATR, at a median-return
     cost + 23-33% stop-out rate. Surfaced alongside LiquidationRead's own
     vol-percentile `hard_stop_price` as manual-stop candidates.
  4. Leverage veto in chop ("chop" regime call, i.e. `trend_1d == "chop"`) or
     falling-knife (`"FALLING KNIFE" in action_reason`, the exact substring
     `action_bucket()` in copilot_alerts.py already keys off) regimes: caps
     leverage, not direction - framed identically to the falling-knife WAIT
     gate below ("the risk is the PATH, not the return").
This block is semi-automatic today (the owner reads it and acts manually);
see the module's own TODO note near `compute_risk_plan` for the live-account
hook that would let it self-execute once an API key is wired.

THEME A - FEE & CARRY (2026-07-31) - the account's PROVEN leak, per the
owner's own ledger arithmetic, is FEES: ~9bps round-trip taker cost is a
material chunk of the risk budget on a small account, and funding accrues
silently on multi-day holds. Two additions, both pure arithmetic (never a
directional/predictive signal - fee/funding math is NOT edge):
  1. `--trade "SYMBOL SIDE LEVERAGEx MARGIN_USD"` -> a standalone PRE-TRADE
     CARD (tools/copilot/pretrade.py, imports this module's fetch/liq/vol
     functions, does not duplicate them): round-trip fee $ + % of margin,
     the maker-order alternative (labeled POTENTIAL - a resting order can
     miss the fill), the price move needed just to scratch (fees + a rough
     per-symbol slippage estimate), funding direction/$-per-day at that
     notional, and liquidation/safe-leverage reusing compute_liquidation().
  2. A FUNDING one-liner added to every normal per-coin brief (see
     _funding_direction_note below) - presented strictly as CARRY/cost
     context (earn or pay, $/day), never as a fade/directional signal (that
     was tested and came back null - see EDGE INSTRUMENTS 2026-07-27).

RANGE-AWARE LEVERAGE (v2.2, 2026-07-31) - owner trades a RANGE (3-15x), not a
single number. `--lev-range LO-HI` (default 3-15, the owner's real usage
range) adds a per-coin block to the RISK section that says which part of
that range is actually usable on THIS coin: hard-capped by HL's real
per-asset maxLeverage (e.g. POPCAT=3x - most of 3-15x is simply impossible
on the venue), further capped by the vol-derived safe-max (e.g. SOL's safe
ceiling sits inside 3-15x, so the top of the range is flagged as risky even
though the venue would allow it), or - for a high-max-leverage/low-vol coin
like BTC - comfortably safe across the whole range. Liquidation price is
shown at BOTH ends of the safe portion of the range so the owner sees the
actual $ liq level at the low and high end they'd realistically use. The
existing single `--leverage` path is unchanged (back-compat for
copilot_alerts.py, which stays single-leverage for now).

ADD CALIBRATION (v2.6, 2026-07-31 RE-VALIDATED) - a rigorous entry-time-safe
re-check of the ADD/dip signal (27 coins, ~10k decision-days) shows the ADD
tilt has DECAYED to noise - the earlier "~+0.5%/3d, t=4.7" figure is itself now
a STALE RELIC (same failure mode as the Bollinger bounce), so the ADD line is
reframed to claim NO timing edge:
  - ADD is NO LONGER a measurable timing tilt: standalone net-mean t=0.39 full
    sample; by era it was +t=3.6 in 2025Q3 ONLY, then reversed to a SIGNIFICANT
    NEGATIVE (t=-2.8) in 2026Q1, and is pure noise since (post-Feb-2026 t=0.73,
    last-90d t=-0.19; all non-overlap-corrected). The old t=4.7 could not be
    reproduced. ADD now = a disciplined-deployment ZONE (oversold/support
    structure), NOT a timing edge. The brief says this explicitly.
  - ADD-in-UPTREND has ALSO decayed: full-sample it looks best (t=2.46) but
    that's entirely pre-Feb-2026; post-Feb t=0.10 (n=39), last-90d flat/neg. No
    longer a genuinely-actionable sharpening - reframed to noise, not upgraded.
  - Deep-oversold (BB<=ADD_BB_MAX AND RSI<=RSI_OVERSOLD together) is
    deliberately NOT upgraded to a stronger "strong buy" - its apparent
    extra strength was entirely a pre-Feb-2026 era artifact, dead since. See
    the NOTE at the add-score computation in `_classify_dip`.
  - The falling-knife WAIT gate is relabeled from a return-avoider to a
    path/liquidation-risk gate - INDEPENDENTLY RE-VERIFIED (and strengthened)
    by tools/copilot/wait_knife_test.py, entry-time-safe/non-overlap/net-of-
    fees, completing the ADD/HOLD/WAIT audit trilogy: knife days do NOT have
    worse forward returns than baseline - they bounce SIGNIFICANTLY HARDER
    (net +4.0%/3d vs baseline -0.6%/3d, full sample, t=3.2 p=0.002; excess
    +4.7pp vs a same-era baseline, t=3.7 p<0.001; still positive and
    significant post-2026-02-01: net +3.2%/3d, excess +3.5pp, t=2.2 p=0.033 -
    ERA-STABLE, unlike ADD/the BB bounce). The gate is justified purely by
    PATH risk, not return: forward max intraday drawdown is both deeper and
    far more frequent than baseline (P(drawdown>=10% over 3d): knife 42% vs
    baseline 20% full sample; 55% vs 14% post-2026-02-01) - a leveraged add
    can get stopped/liquidated on the way to a bounce that, on average,
    arrives anyway. CAVEAT: the drawdown-excess MAGNITUDE is itself mostly a
    post-2026-02-01 finding (pre-Feb excess was ~0, not significant,
    p=0.873) on a thin sample (29 non-overlap post-Feb episodes) - watch for
    drift the way ADD's calibration drifted. Component check: the ADX/EMA
    "confirmed strong downtrend" requirement adds ~nothing over the -25%
    7d-return threshold alone (momentum-only / EMA-only-no-ADX variants
    match or beat it on n, t-stat, and magnitude) - but the -25% EXTREMITY
    threshold itself is NOT trivial: a "confirmed downtrend but not yet -25%
    extreme" bucket is SIGNIFICANTLY NEGATIVE (net -1.2%/3d full, -2.8%/3d
    post-Feb, t=-2.15/-4.84 - continuation, not reversal), i.e. moderate
    downtrends keep bleeding while only the extreme ones bounce - the gate
    is not merely restating "it's in a downtrend, don't catch it." Chop-WAIT
    is unchanged (still just "low-conviction, wait").
  - All of the above is messaging/framing only - no thresholds, scoring
    weights, or control flow changed; `action_bucket()` in
    copilot_alerts.py still detects the falling-knife case by the substring
    "FALLING KNIFE" in `action_reason`, which is preserved verbatim.

HORIZON-AWARE LEVERAGE (v2.5, 2026-07-31) - an OOS-validated fix to the
SAFE-MAX-LEVERAGE mechanic (see tools/copilot/lev_band_horizon_test.py for
the validation this implements byte-for-byte). The RISK PLAN above always
recommended a 3-5 DAY hold, but `compute_liquidation()`'s safe-max-leverage
was solved against `vol.pct95_daily_drop_pct` - a worst SINGLE-DAY move.
lev_band_test.py's OOS backtest showed opening at that "safe" band and
holding 3-5 days actually liquidates ~25-40% of the time, not ~5%. The fix:
`RealizedVol.horizon_tail_pct` now also carries a HOLD-HORIZON,
SIDE-SPECIFIC adverse-excursion tail (95th-pct worst H-day drawdown for
LONG, worst H-day run-up for SHORT, H in {3, 5} - see
`compute_horizon_tail_frac`), and `compute_liquidation(..., hold_days=...)`
uses that instead of the single-day tail when the caller states a hold
length. OOS result at H=3-5: liquidation risk lands at ~4% (vs the old
~25-40%), with recommended leverage a median ~2.5-5x on memes and ~6-9x on
majors - usable, not degenerate. FAIL-SOFT by construction: `hold_days=None`
(the default) or missing calibration (thin history) reproduces the exact
pre-v2.5 single-day number - no existing caller (`copilot_alerts.py`,
`pretrade.py`, `book.py`) regresses. The paths that actually PROMISE a 3-5d
hold (`compute_risk_plan` / the RISK PLAN block, and the `--lev-range` "YOUR
RANGE" block / `format_range_block`) now call `compute_liquidation` with
`hold_days=5` (the conservative/upper end) and print BOTH the single-day
ceiling and the multi-day safe number side by side, instead of the old
blanket "~25-40% at a 3-5d hold" disclaimer. The single-leverage verdict
line (driven by `--leverage`/`--side`, used by `copilot_alerts.py`) is left
single-day-only, unchanged, since it doesn't itself commit to a hold length.

FORWARD-EVIDENCE ANCHOR FIX (2026-08-01) - a confirmed, proven bug in the
call-ledger forward-evidence instrument (call_logger.py / resolve_calls.py,
see PREREGISTRATION.md), fixed here at the source. `build_dip_read()` set
`r.price` to `close.iloc[-1]` from `fetch_ohlc()`, which fetches up to "now" -
so the LAST candle can be the STILL-FORMING current-UTC-day bar, not a
settled close (proven on real data: an Aug-1 "daily" candle showed n=37k
trades vs 240k-420k for a fully-elapsed day). Because the ledger then dated
each call by wall-clock `ts_utc` (e.g. a 01:01 UTC cron) rather than by a
settled candle date, `resolve_calls.py`'s `target_dt = ts_dt + timedelta(days=d)`
systematically INFLATED every horizon (fwd_3d actually spanning ~3.45 days,
fwd_1d up to ~1.96 days) - not comparable to the backtest's clean
close-to-close baseline that H1/H2 test against.
FIX: `DipRead` now also carries `settled_close`/`settled_close_date` - the
close and open-date of the last FULLY CLOSED daily candle (drops the
still-forming row if the last candle opened today UTC). `r.price` is left
untouched (the human-facing brief/display still shows the live/current
close - unchanged behavior); ONLY `settled_close`/`settled_close_date` feed
the call ledger. `resolve_calls.py` anchors its N-day close-to-close horizon
on `settled_close_date` (not `ts_utc`), giving an EXACT N-day return with no
look-ahead (the settled candle is, by construction, fully in the past).
Pre-fix ledger rows lack these fields and are tagged/excluded from the H1/H2
readout rather than silently resolved on the old, inflated horizon - see
`ev_schema` in call_logger.py and resolve_calls.py's exclusion count.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FETCHERS_DIR = os.path.join(BOT_DIR, "data", "fetchers")

DEFAULT_SYMBOLS = ["BTC", "SOL", "POPCAT"]  # majors -> memes; owner trades all three

# ---------------------------------------------------------------------------
# CONFIG - v2 heuristic constants. Tune here, not scattered in the logic.
# These are the same v1 numbers; nothing about the regime/vol math changed,
# only the SWING section's ACTION LABELS + framing (see _classify_dip below).
# ---------------------------------------------------------------------------
DAYS_1D = 200          # ~200d of daily candles for trend/vol/S-R
DAYS_1H = 30           # ~30d of hourly candles for near-term BB timing
FUNDING_LOOKBACK_D = 30
MIN_ROWS_1D = 30        # below this, treat as "insufficient data"

EMA_FAST, EMA_SLOW = 20, 50
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 22.0
BB_PERIOD, BB_MULT = 20, 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14         # Wilder ATR - drives the RISK PLAN's vol-based stop/sizing (see compute_risk_plan)
SWING_LOOKBACK_D = 20   # days, excludes today, for support/resistance

# Dip/extreme thresholds (same math as v1's ADD/TRIM thresholds; the ADD side
# keeps its meaning, the "TRIM side" is now framed as HOLD, with a TRIM note
# only at a genuinely more extreme reading - see DISCRETIONARY_TRIM_* below)
ADD_BB_MAX = 0.25       # bb_pos_1d at/below this = lower-band zone (ADD)
HOLD_BB_MIN = 0.75      # bb_pos_1d at/above this = upper-band zone (HOLD, don't chase)
RSI_OVERSOLD = 35.0
RSI_OVERBOUGHT = 65.0
NEAR_SR_PCT = 6.0       # within this % of swing high/low counts as "near"

# Discretionary-trim-note thresholds: deliberately MORE extreme than the
# HOLD threshold above, so a plain "at the upper band" reading is just HOLD,
# and only a genuine blow-off extreme even mentions trimming as an option.
DISCRETIONARY_TRIM_BB_MIN = 0.95
DISCRETIONARY_TRIM_RSI = 80.0

# Regime-honesty thresholds
TIGHT_RANGE_DAILY_VOL_PCT = 3.0   # daily-return stdev below this = no real oscillation
FALLING_KNIFE_RET7D_PCT = -25.0   # 7d return worse than this = don't call the bottom

# Liquidation / leverage defaults
DEFAULT_EQUITY_USD = 1000.0
DEFAULT_LEVERAGE = 2.0
DEFAULT_SIDE = "LONG"
DEFAULT_LEV_RANGE_STR = "3-15"  # owner's real leverage usage range (3-15x)
MAINT_MARGIN_FRAC = 0.02   # FALLBACK ONLY - used if the live HL `meta` fetch
                           # fails; see LIQUIDATION ASSUMPTIONS in module
                           # docstring. Normal path uses the REAL per-asset
                           # mm = 1/(2*maxLeverage) from fetch_hl_max_leverage().
SAFE_LEV_CAP = 20.0        # never recommend "safe" above this regardless of vol

# Hyperliquid pays funding HOURLY (confirmed live via fundingHistory + cross-
# checked in tools/research/sensor_validation.py, which sums 8 hourly rates
# to build an "8h-equivalent" - i.e. the raw fundingRate field IS already a
# per-hour rate, not a per-8h rate). Some older files elsewhere in this repo
# comment fundingRate as "per 8h" (a Binance/Bybit-style assumption) - that
# convention is NOT used here; this module uses HL's real hourly schedule.
FUNDING_PAYMENTS_PER_DAY = 24

# ---------------------------------------------------------------------------
# RISK PLAN (v2.4, 2026-07-31) - THE AUTOMATABLE HALF of the playbook, per an
# out-of-sample backtest that separated MECHANICAL risk-management (survives
# OOS -> safe to encode/automate) from DISCRETIONARY entry timing (the ADD
# call above stays a hint, per the SAME test - see ADD CALIBRATION note).
# Pure arithmetic/regime-lookup risk mechanics, never a return prediction.
# HONEST OOS STATUS (2026-07-31 stress tests): the horizon-aware LEVERAGE band
# is validated (~4% liq at a 3-5d hold); the MAX-HOLD is real+additive but not
# an optimum; the 2xATR disaster stop is NOT validated tail insurance at 3-5d
# (~return-neutral there). Framing below reflects that, no overclaim:
#   1. Vol-based sizing: risk_$ / (2xATR stop distance as a % of price) ->
#      the notional that risks exactly risk_$ if the disaster stop is hit.
#   2. 3-5 day MAX-HOLD time-stop - real, additive tail-cutting (ruin rises
#      monotonically with hold length OOS) but NOT an optimum: shorter is
#      always safer; 3-5d is a practical floor, not a proven sweet spot.
#   3. 2xATR disaster stop - a loose "I'm wrong" backstop, NOT validated tail
#      insurance (OOS ~return-neutral at a 3-5d hold; real tail-cut ~1-1.5xATR). A
#      SEPARATE computation from LiquidationRead.hard_stop_price above (that
#      one is vol-percentile/liquidation-distance-derived, used to keep the
#      LEVERAGE guardrail honest); this one is the plain ATR-multiple stop
#      the sizing formula in (1) is built on. Both are legitimate "manual
#      stop" candidates - this module surfaces both rather than picking one.
#   4. Leverage veto in chop/falling-knife regimes: the guardrail caps/vetos
#      LEVERAGE, not direction - "the risk here is a -10% path that
#      liquidates, not the direction" (knife/chop DO often resolve fine on
#      returns per the ADD calibration note; the danger is the PATH under
#      leverage, same framing as the falling-knife WAIT gate above).
# RISK_PLAN_DEFAULT_ACCOUNT_USD is DELIBERATELY separate from --equity
# (which sizes the notional-context line elsewhere in briefs/cards) so this
# addition never changes --equity's existing default/behavior for
# copilot_alerts.py or any other caller.
# ---------------------------------------------------------------------------
RISK_PLAN_DEFAULT_RISK_PCT = 1.0        # % of account risked per trade if the disaster stop is hit
RISK_PLAN_DEFAULT_ACCOUNT_USD = 5000.0  # account size used ONLY for the risk plan's own sizing math
DISASTER_STOP_ATR_MULT = 2.0            # stop = entry -/+ this many ATRs
MAX_HOLD_DAYS_RANGE = (3.0, 5.0)        # owner-facing time-stop window

HONESTY_FOOTER = (
    "Note: discipline + risk aid, not a proven alpha edge. Backtest showed "
    "swing-trimming surrenders upside; for a bullish hold, add on dips + "
    "hold through strength. (ADD marks a disciplined-deployment ZONE, NOT a "
    "timing edge - OOS re-validation finds no measurable forward tilt since "
    "Feb-2026; the old ~+0.5%/3d decayed to noise. Entry timing is your call.)"
)


# ---------------------------------------------------------------------------
# Indicators (self-contained; no live-bot import - standalone by design)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["h"], df["l"], df["c"]
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Wilder ATR (ewm alpha=1/period on true range) - the SAME true-range +
    smoothing _adx uses internally for its own DI normalization, extracted
    here so the RISK PLAN's vol-based stop/sizing (compute_risk_plan) is the
    identical measure ADX is built on, not a second slightly-different one."""
    return _true_range(df).ewm(alpha=1.0 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Wilder-style ADX via ewm(alpha=1/period) smoothing (standard approx)."""
    high, low = df["h"], df["l"]
    tr = _true_range(df)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False).mean()


def _bollinger(series: pd.Series, period: int = BB_PERIOD, mult: float = BB_MULT):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    return mid, mid + mult * std, mid - mult * std


def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # where avg_loss is exactly 0 (straight up), rs=inf handled by the formula
    # naturally via replace(0, nan) -> rs=nan -> rsi=nan; fill those as 100
    # (no losses in the window = maximally overbought), leave true NaNs (not
    # enough history yet) as NaN for callers to guard with pd.notna().
    rsi = rsi.where(~(avg_loss.eq(0) & avg_gain.gt(0)), 100.0)
    return rsi


# ---------------------------------------------------------------------------
# Data loading - standalone HLNative only, fail-soft everywhere
# ---------------------------------------------------------------------------

def _get_hl_client():
    if FETCHERS_DIR not in sys.path:
        sys.path.insert(0, FETCHERS_DIR)
    from hl_native import HLNative  # standalone, read-only, no live-bot deps
    return HLNative()


def _candles_to_df(candles: list) -> Optional[pd.DataFrame]:
    if not candles:
        return None
    df = pd.DataFrame(candles)
    for c in ["o", "h", "l", "c", "v"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "t" not in df.columns:
        return None
    df["t"] = pd.to_datetime(df["t"], unit="ms", errors="coerce", utc=True)
    df = df.dropna(subset=["o", "h", "l", "c"]).sort_values("t").reset_index(drop=True)
    return df if not df.empty else None


def fetch_ohlc(client, symbol: str, interval: str, days: int) -> Optional[pd.DataFrame]:
    """interval in {'1d','1h'}. Returns None (never raises) if the fetch
    fails or comes back thin - callers must degrade gracefully."""
    try:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = now_ms - days * 24 * 3600 * 1000
        candles = client.candles(symbol, interval, start_ms, now_ms)
        return _candles_to_df(candles)
    except Exception as e:
        print(f"[copilot] {symbol} {interval} candle fetch failed: {e}", file=sys.stderr)
        return None


def fetch_funding(client, symbol: str, days: int) -> Optional[pd.DataFrame]:
    try:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = now_ms - days * 24 * 3600 * 1000
        recs = client.funding_history(symbol, start_ms)
        if not recs:
            return None
        df = pd.DataFrame(recs)
        df["fundingRate"] = pd.to_numeric(df.get("fundingRate"), errors="coerce")
        df = df.dropna(subset=["fundingRate"])
        return df if len(df) >= 3 else None
    except Exception as e:
        print(f"[copilot] {symbol} funding fetch failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# HL real per-asset max leverage - drives the REAL maintenance-margin fraction
# (see LIQUIDATION ASSUMPTIONS in module docstring). One `meta` call covers
# every symbol/coin for the life of the process - cached at module scope.
# ---------------------------------------------------------------------------
_HL_META_CACHE = {"fetched": False, "universe": None}  # type: dict


def _fetch_hl_universe(client) -> Optional[dict]:
    """Fetch + cache HL's asset universe {symbol: {"maxLeverage": ..., ...}}
    from the `meta` info-API endpoint. Fetched at most once per process.
    Fail-soft: returns None (and caches the failure, so we don't hammer the
    API once per symbol) if the call fails or comes back malformed."""
    if not _HL_META_CACHE["fetched"]:
        _HL_META_CACHE["fetched"] = True
        try:
            meta = client.meta()
            universe = (meta or {}).get("universe") if isinstance(meta, dict) else None
            if universe:
                _HL_META_CACHE["universe"] = {
                    a["name"]: a for a in universe if isinstance(a, dict) and "name" in a
                }
            else:
                print("[copilot] HL meta fetch returned no universe - falling back to flat maintenance margin", file=sys.stderr)
        except Exception as e:
            print(f"[copilot] HL meta fetch failed: {e} - falling back to flat maintenance margin", file=sys.stderr)
    return _HL_META_CACHE["universe"]


def fetch_hl_max_leverage(client, symbol: str) -> Optional[float]:
    """Real per-asset max leverage for `symbol`, straight from HL's own
    `meta` endpoint (the same number HL uses to gate what leverage you're
    even allowed to select on the exchange). Returns None (never raises) if
    the meta call failed or the symbol isn't in HL's universe - callers must
    fall back to the flat MAINT_MARGIN_FRAC assumption and say so."""
    universe = _fetch_hl_universe(client)
    if not universe or symbol not in universe:
        return None
    lev = universe[symbol].get("maxLeverage")
    try:
        lev_f = float(lev)
        return lev_f if lev_f > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Realized volatility - the yardstick the whole risk half is measured against
# ---------------------------------------------------------------------------

# HORIZON-AWARE tail calibration (v2.5 - see module docstring). H in days;
# matches the RISK PLAN's own 3-5d hold window (MAX_HOLD_DAYS_RANGE below)
# and lev_band_horizon_test.py's HOLDS - these are the only horizons
# `compute_liquidation(..., hold_days=...)` can snap to and look up.
HORIZON_TAIL_DAYS = (3, 5)
# Same n>=20 sample-size gate compute_realized_vol already uses for
# pct95_daily_drop_pct - not a stricter or looser bar for the horizon tail.
HORIZON_TAIL_MIN_SAMPLE = 20


@dataclass
class RealizedVol:
    n_days: int = 0
    daily_vol_pct: Optional[float] = None          # stdev of daily % returns
    avg_abs_daily_move_pct: Optional[float] = None  # mean |daily % return|
    weekly_vol_pct: Optional[float] = None          # stdev of rolling 7d % returns
    avg_abs_weekly_move_pct: Optional[float] = None
    pct95_daily_drop_pct: Optional[float] = None    # magnitude of the 95th-pct worst day
    max_daily_drop_pct: Optional[float] = None       # worst single day in the sample
    max_daily_drop_date: Optional[str] = None
    # HORIZON-AWARE, SIDE-SPECIFIC adverse-excursion tails (v2.5 fix - see
    # module docstring "HORIZON-AWARE LEVERAGE" + lev_band_horizon_test.py).
    # Keyed (H, "LONG"|"SHORT") -> 95th-pct worst H-day adverse-excursion
    # MAGNITUDE, in %, e.g. horizon_tail_pct[(5, "LONG")] = 18.4 means the
    # worst 5-day drawdown-from-entry cleared 18.4% at the 95th percentile,
    # entry-time-safe over the history in the df passed to
    # compute_realized_vol. A (H, side) key is ABSENT (not zero) when there
    # weren't enough overlapping H-day windows (< HORIZON_TAIL_MIN_SAMPLE) -
    # callers must treat a missing key as "no calibration", not "zero tail".
    horizon_tail_pct: dict = field(default_factory=dict)
    _daily_ret_pct: List[float] = field(default_factory=list, repr=False)  # raw series for freq lookups


def compute_horizon_tail_frac(df_1d: pd.DataFrame, H: int, side: str, pct: float = 95.0) -> Optional[float]:
    """Horizon-H, side-specific adverse-excursion tail fraction - THE FIX
    validated in tools/copilot/lev_band_horizon_test.py (same sliding-window
    max-adverse-excursion logic, reused here rather than re-transcribed
    independently - see that script's own `compute_horizon_tail_frac` for
    the two-sided version this mirrors). Entry-time-safe by construction:
    `df_1d` is whatever trailing window the caller already has (e.g. the
    same DAYS_1D=200-capped window compute_realized_vol receives), and every
    candidate entry index i used below has i+H already inside that window -
    no peeking past "today".

    For every candidate entry index i (0..n-H-1):
      LONG:  mae(i) = (close[i] - min(low[i+1..i+H])) / close[i]   (drawdown)
      SHORT: mae(i) = (max(high[i+1..i+H]) - close[i]) / close[i]  (run-up)
    Returns the `pct`-th percentile of that distribution (a magnitude,
    already >= 0), or None if fewer than HORIZON_TAIL_MIN_SAMPLE overlapping
    H-day windows are available (mirrors compute_realized_vol's own n>=20
    gate for pct95_daily_drop_pct)."""
    close = df_1d["c"].to_numpy(dtype=float)
    low = df_1d["l"].to_numpy(dtype=float)
    high = df_1d["h"].to_numpy(dtype=float)
    n = len(close)
    m = n - H  # number of valid entry indices i = 0..m-1, each needs low/high[i+1..i+H]
    if m < HORIZON_TAIL_MIN_SAMPLE or n <= H:
        return None

    side_u = (side or DEFAULT_SIDE).strip().upper()
    is_long = side_u in ("LONG", "BUY")

    entry_close = close[:m]
    if is_long:
        low_windows = sliding_window_view(low[1:], H)   # window i -> low[i+1:i+1+H]
        fwd_min = low_windows.min(axis=1)[:m]
        mae = np.clip((entry_close - fwd_min) / entry_close, 0.0, None)
    else:
        high_windows = sliding_window_view(high[1:], H)  # window i -> high[i+1:i+1+H]
        fwd_max = high_windows.max(axis=1)[:m]
        mae = np.clip((fwd_max - entry_close) / entry_close, 0.0, None)

    return float(np.percentile(mae, pct))


def compute_realized_vol(df_1d: pd.DataFrame) -> RealizedVol:
    close = df_1d["c"]
    daily_ret = (close.pct_change().dropna() * 100.0)
    n = len(daily_ret)
    if n == 0:
        return RealizedVol()

    weekly_ret = ((close / close.shift(7) - 1.0).dropna() * 100.0)

    vol = RealizedVol(
        n_days=n,
        daily_vol_pct=float(daily_ret.std()) if n > 1 else None,
        avg_abs_daily_move_pct=float(daily_ret.abs().mean()),
        weekly_vol_pct=float(weekly_ret.std()) if len(weekly_ret) > 1 else None,
        avg_abs_weekly_move_pct=float(weekly_ret.abs().mean()) if len(weekly_ret) > 0 else None,
        max_daily_drop_pct=float(-daily_ret.min()),
        _daily_ret_pct=daily_ret.tolist(),
    )
    if n >= 20:
        # 5th percentile of raw returns = magnitude of the 95th-percentile worst DROP
        vol.pct95_daily_drop_pct = float(-np.percentile(daily_ret.values, 5))
    idx_min = daily_ret.idxmin()
    try:
        vol.max_daily_drop_date = df_1d.loc[idx_min, "t"].strftime("%Y-%m-%d")
    except Exception:
        pass

    # ---- Horizon-aware, side-specific adverse-excursion tails (v2.5 fix -
    # see module docstring). Computed from the SAME df_1d window this
    # function already received - entry-time-safe by construction, no extra
    # data fetched, no look-ahead. A (H, side) cell is simply absent if the
    # window is too thin (see compute_horizon_tail_frac's own gate). ----
    for _H in HORIZON_TAIL_DAYS:
        for _side in ("LONG", "SHORT"):
            _frac = compute_horizon_tail_frac(df_1d, _H, _side, pct=95.0)
            if _frac is not None:
                vol.horizon_tail_pct[(_H, _side)] = _frac * 100.0

    return vol


# ---------------------------------------------------------------------------
# DIP-DEPLOYMENT + HOLD half (v2 - reframed from v1's two-way "swing" call)
# ---------------------------------------------------------------------------

@dataclass
class DipRead:
    ok: bool = True
    data_note: Optional[str] = None
    symbol: str = ""

    price: Optional[float] = None
    # ---- FORWARD-EVIDENCE anchor (2026-08-01 fix, see module docstring
    # "FORWARD-EVIDENCE ANCHOR FIX") - the last FULLY CLOSED daily candle's
    # close + the calendar date it opened on. `price` above is deliberately
    # left as the raw last-row close (may be the still-forming current-UTC-
    # day candle) for the human-facing brief/display - ONLY these two fields
    # feed the call ledger (call_logger.py) that resolve_calls.py uses to
    # compute forward returns, so that horizon is a clean, entry-time-safe
    # close-to-close N-day return, not one inflated by wall-clock log time.
    settled_close: Optional[float] = None
    settled_close_date: Optional[str] = None  # "YYYY-MM-DD", the settled candle's OPEN date (HL daily-candle convention)
    trend_1d: str = "n/a"           # up / down / chop / n/a
    trend_strength: str = "n/a"     # strong / weak / n/a
    adx_1d: Optional[float] = None
    ret_1d_pct: Optional[float] = None
    ret_7d_pct: Optional[float] = None

    rsi_1d: Optional[float] = None
    bb_pos_1d: Optional[float] = None   # 0 = lower band, 1 = upper band
    bb_pos_1h: Optional[float] = None

    atr_1d: Optional[float] = None      # Wilder ATR(14) on 1d, in price units - RISK PLAN's stop/sizing yardstick
    atr_pct_1d: Optional[float] = None  # atr_1d / price, as a fraction (e.g. 0.04 = 4%)

    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    dist_to_high_pct: Optional[float] = None
    dist_to_low_pct: Optional[float] = None

    funding_rate: Optional[float] = None
    funding_extreme: bool = False
    funding_note: str = "n/a"

    vol: RealizedVol = field(default_factory=RealizedVol)

    action: str = "HOLD"            # ADD / HOLD / WAIT  (never "TRIM" - see discretionary_trim_note)
    action_reason: str = ""
    add_level: Optional[float] = None
    ref_high_level: Optional[float] = None  # informational only - NOT a trim trigger
    discretionary_trim_note: Optional[str] = None  # only set at a genuine blow-off extreme
    warnings: List[str] = field(default_factory=list)


def build_dip_read(client, symbol: str) -> DipRead:
    df_1d = fetch_ohlc(client, symbol, "1d", DAYS_1D)
    if df_1d is None or len(df_1d) < MIN_ROWS_1D:
        n = 0 if df_1d is None else len(df_1d)
        return DipRead(ok=False, symbol=symbol, data_note=f"insufficient {symbol} 1d history ({n} rows)")

    df_1h = fetch_ohlc(client, symbol, "1h", DAYS_1H)
    fdf = fetch_funding(client, symbol, FUNDING_LOOKBACK_D)

    r = DipRead(ok=True, symbol=symbol)
    close = df_1d["c"]
    r.price = float(close.iloc[-1])

    # ---- Settled (fully-closed) daily candle - the FORWARD-EVIDENCE anchor
    # (2026-08-01 fix). fetch_ohlc() fetches candles up to "now", so the LAST
    # row of df_1d can be the STILL-FORMING current-UTC-day candle, not a
    # settled close (proven on real data: an Aug-1 "daily" candle showed
    # n=37k trades vs 240k-420k for a fully-elapsed day). A 1d HL candle
    # opened on date D covers [D 00:00, D+1 00:00) UTC, so it is fully closed
    # iff D is strictly before today (UTC) - equivalently, iff we are
    # currently on a LATER calendar day than the candle's open date. If the
    # last row's open date is today, drop it and use the prior (settled) row
    # instead; otherwise the last row is already settled. `r.price` above is
    # left untouched (still the raw last-row close) so the interactive
    # brief/display never changes - only these two fields are new.
    today_utc = datetime.now(timezone.utc).date()
    settled_idx = -2 if df_1d["t"].iloc[-1].date() >= today_utc else -1
    r.settled_close = float(close.iloc[settled_idx])
    r.settled_close_date = df_1d["t"].iloc[settled_idx].strftime("%Y-%m-%d")

    # ---- Trend: EMA20 vs EMA50 + ADX on 1d ----
    ema_f, ema_s = _ema(close, EMA_FAST), _ema(close, EMA_SLOW)
    dir_1d = "up" if ema_f.iloc[-1] > ema_s.iloc[-1] else "down"
    adx_series = _adx(df_1d)
    adx_val = adx_series.iloc[-1] if not adx_series.empty and pd.notna(adx_series.iloc[-1]) else None
    r.adx_1d = float(adx_val) if adx_val is not None else None
    is_trending = r.adx_1d is not None and r.adx_1d >= ADX_TREND_THRESHOLD
    r.trend_1d = dir_1d if is_trending else "chop"
    r.trend_strength = "strong" if is_trending else "weak"

    # ---- Returns ----
    if len(close) >= 2:
        r.ret_1d_pct = float((close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0)
    if len(close) >= 8:
        r.ret_7d_pct = float((close.iloc[-1] / close.iloc[-8] - 1.0) * 100.0)

    # ---- RSI(14) on 1d ----
    rsi_series = _rsi(close, RSI_PERIOD)
    if pd.notna(rsi_series.iloc[-1]):
        r.rsi_1d = float(rsi_series.iloc[-1])

    # ---- Bollinger position, 1d AND 1h ----
    _, bb_up_1d, bb_lo_1d = _bollinger(close)
    up1d, lo1d = bb_up_1d.iloc[-1], bb_lo_1d.iloc[-1]
    if pd.notna(up1d) and pd.notna(lo1d) and up1d != lo1d:
        r.bb_pos_1d = float(np.clip((r.price - lo1d) / (up1d - lo1d), -0.5, 1.5))

    if df_1h is not None and len(df_1h) >= BB_PERIOD:
        _, bb_up_1h, bb_lo_1h = _bollinger(df_1h["c"])
        up1h, lo1h = bb_up_1h.iloc[-1], bb_lo_1h.iloc[-1]
        p1h = float(df_1h["c"].iloc[-1])
        if pd.notna(up1h) and pd.notna(lo1h) and up1h != lo1h:
            r.bb_pos_1h = float(np.clip((p1h - lo1h) / (up1h - lo1h), -0.5, 1.5))

    # ---- ATR(14) on 1d - the RISK PLAN's stop/sizing yardstick ----
    atr_series = _atr(df_1d)
    atr_val = atr_series.iloc[-1] if not atr_series.empty and pd.notna(atr_series.iloc[-1]) else None
    if atr_val is not None:
        r.atr_1d = float(atr_val)
        if r.price:
            r.atr_pct_1d = r.atr_1d / r.price

    # ---- Swing S/R (20d, excludes today) ----
    if len(df_1d) > SWING_LOOKBACK_D + 1:
        window = df_1d.iloc[-(SWING_LOOKBACK_D + 1):-1]
        r.swing_high = float(window["h"].max())
        r.swing_low = float(window["l"].min())
        r.dist_to_high_pct = (r.swing_high - r.price) / r.price * 100.0
        r.dist_to_low_pct = (r.price - r.swing_low) / r.price * 100.0

    # ---- Funding (crowding context, not a gate) ----
    if fdf is not None:
        latest = float(fdf["fundingRate"].iloc[-1])
        r.funding_rate = latest
        hist = fdf["fundingRate"].iloc[:-1]
        if len(hist) >= 24:
            mean, std = hist.mean(), hist.std()
            if std and std > 0:
                z = (latest - mean) / std
                r.funding_extreme = bool(abs(z) > 2.5)
                r.funding_note = f"{'EXTREME' if r.funding_extreme else 'normal'} (z={z:+.1f})"
            else:
                r.funding_note = "normal"
        else:
            r.funding_note = "thin history"
    else:
        r.funding_note = "no funding data"

    # ---- Realized volatility (the risk-half's yardstick) ----
    r.vol = compute_realized_vol(df_1d)

    _classify_dip(r)
    return r


def _classify_dip(r: DipRead) -> None:
    """v2 accumulation logic for a BULLISH LONG-TERM HOLDER: ADD on dips,
    HOLD through strength, WAIT when the regime makes either call unsafe.

    This deliberately does NOT produce a symmetric two-way "swing" call like
    v1 did. The backtest finding that motivated v2: trimming into strength
    is a disguised exit that only pays on down-legs and surrenders upside on
    up-legs (the legs a bullish accumulator is holding for). So the upper
    extreme case below returns HOLD, not TRIM - trimming is only ever
    surfaced as a separate, clearly-optional discretionary note at a more
    extreme reading than plain "upper band", never as the primary action.

    REGIME HONESTY gates (kept from v1, unchanged): a falling knife or a
    dead-flat chop makes even the ADD call unsafe/meaningless, and those
    override everything else below.
    """

    # Always compute a concrete add level, regardless of the current call,
    # so the owner can see where the NEXT tranche would trigger. swing_high
    # is kept as an informational reference only - NOT a trim trigger.
    r.add_level = r.swing_low
    r.ref_high_level = r.swing_high

    daily_vol = r.vol.daily_vol_pct
    is_falling_knife = (
        r.trend_1d == "down" and r.trend_strength == "strong"
        and r.ret_7d_pct is not None and r.ret_7d_pct <= FALLING_KNIFE_RET7D_PCT
    )
    is_tight_range = (
        daily_vol is not None and daily_vol < TIGHT_RANGE_DAILY_VOL_PCT
        and r.trend_1d == "chop"
    )

    if is_falling_knife:
        r.action = "WAIT"
        # NOTE (calibration, 2026-07-31, independently RE-VERIFIED by
        # tools/copilot/wait_knife_test.py): this gate does NOT avoid bad
        # returns - knife days bounce SIGNIFICANTLY HARDER than baseline
        # (net +4.0%/3d full sample, t=3.2 p=0.002; +3.2%/3d and still
        # significant post-2026-02-01 - era-stable). What it avoids is the
        # PATH: forward drawdown >=10% over 3d hits ~42-55% of knife
        # episodes vs ~14-20% baseline - a leveraged add can get liquidated
        # before the bounce arrives. Framed as a leverage/path-risk gate,
        # not a return-avoider.
        r.action_reason = (
            f"WAIT - FALLING KNIFE: strong downtrend, 7d return {r.ret_7d_pct:+.1f}%. "
            f"Not a return-avoider (these historically bounce hard, net +3-4%/3d vs a "
            f"random day, era-stable through 2026 - wait_knife_test.py) - the risk is the "
            f"PATH: forward drawdown exceeds 10% in roughly 4-in-10 to 5-in-10 knife "
            f"episodes, which can liquidate a leveraged add before any bounce happens. "
            f"TIMING (alert_latency_test.py): that ~10% risk resolves FAST - median ~7h, "
            f"nearly all within 24-48h - so this is a 'don't add TODAY' flag, not days of "
            f"runway to watch; the severe (>=15%) tail is the slower one (~2 days to develop). "
            f"Sit out here if you're levered; wait for RSI to base and ADX to cool if you "
            f"want to add unlevered."
        )
        r.warnings.append(
            f"{r.symbol} is in a falling knife (7d {r.ret_7d_pct:+.1f}%, ADX {r.adx_1d:.0f}) - "
            f"the bounce often comes, but a -10%+ intraday swing can liquidate a "
            f"leveraged position before it does."
        )
        return

    if is_tight_range:
        r.action = "WAIT"
        r.action_reason = (
            f"TIGHT LOW-VOL RANGE - daily vol only {daily_vol:.1f}% (ADX {r.adx_1d:.0f}, chop). "
            f"No real dip to deploy into right now; adding here is noise-trading, not a "
            f"disciplined tranche. Wait for a real pullback."
        )
        r.warnings.append(
            f"{r.symbol} daily vol has compressed to {daily_vol:.1f}% - few real dips; be patient."
        )
        return

    oversold = r.rsi_1d is not None and r.rsi_1d <= RSI_OVERSOLD
    overbought = r.rsi_1d is not None and r.rsi_1d >= RSI_OVERBOUGHT
    lower_bb = r.bb_pos_1d is not None and r.bb_pos_1d <= ADD_BB_MAX
    upper_bb = r.bb_pos_1d is not None and r.bb_pos_1d >= HOLD_BB_MIN
    near_support = r.dist_to_low_pct is not None and r.dist_to_low_pct <= NEAR_SR_PCT
    near_resistance = r.dist_to_high_pct is not None and r.dist_to_high_pct <= NEAR_SR_PCT

    # NOTE (ADD calibration, 2026-07-31 - entry-time-safe, 27 coins/10k
    # decision-days): deep-oversold (BB<=ADD_BB_MAX AND RSI<=RSI_OVERSOLD
    # together) is DELIBERATELY NOT scored/labeled as a stronger "strong buy"
    # than a plain single-condition ADD. Its apparent extra strength in raw
    # history was entirely a pre-Feb-2026 era artifact (dead since) - do not
    # reintroduce an upgrade for this combo without re-running the
    # calibration on fresh data.
    add_score = sum([lower_bb, oversold, near_support])
    hold_score = sum([upper_bb, overbought, near_resistance])

    if add_score >= 1 and add_score > hold_score:
        r.action = "ADD"
        bits = []
        if lower_bb:
            bits.append(f"lower BB ({r.bb_pos_1d:.2f})")
        if oversold:
            bits.append(f"RSI oversold ({r.rsi_1d:.0f})")
        if near_support:
            bits.append(f"near 20d support (${r.swing_low:.4f}, {r.dist_to_low_pct:.1f}% away)")
        # ADD calibration RE-VALIDATED (2026-07-31, add_signal_revalidate.py):
        # the ADD tilt has DECAYED to noise - standalone net-mean t=0.39 full
        # sample, +t=3.6 in 2025Q3 only, then significantly NEGATIVE (t=-2.8) in
        # 2026Q1, pure noise since. The old "+0.5%/3d, t=4.7" is a stale relic
        # (same as the BB bounce). ADD+uptrend ALSO decayed (post-Feb t=0.10).
        # ADD is now framed as a disciplined-deployment ZONE, not a timing edge.
        is_uptrend = r.trend_1d == "up" and r.trend_strength == "strong"
        if is_uptrend:
            trend_note = (
                "within an intact uptrend (a structurally cleaner place to deploy - though "
                "'ADD-in-uptrend' as a timing edge has decayed to noise OOS since Feb-2026)"
            )
        elif r.trend_1d == "down":
            trend_note = (
                "within a downtrend (not a falling knife) - weaker; matches the "
                "baseline, deploy smaller or wait"
            )
        else:
            trend_note = (
                "within chop/a holding range - weaker; matches the baseline, "
                "deploy smaller or wait"
            )
        h1 = ""
        if r.bb_pos_1h is not None:
            h1 = (
                " 1h also in the lower band - timing lines up." if r.bb_pos_1h <= ADD_BB_MAX
                else " 1h hasn't reached the lower band yet - may still drift down first."
            )
        r.action_reason = (
            f"ADD ZONE: a disciplined-deployment zone (oversold/support structure), NOT a timing "
            f"edge. Independent OOS re-validation (add_signal_revalidate.py, 2026-07-31) finds NO "
            f"measurable forward tilt since Feb-2026 or in the last 90d (t between -1.8 and +0.7, "
            f"non-overlap-corrected) - the old ~+0.5%/3d was concentrated in one 2025 quarter and "
            f"has since decayed to noise (briefly negative in 2026Q1). Use it as 'IF you're deploying "
            f"a planned buy, this is a structured place to do it', not a reason to buy: "
            f"{', '.join(bits)}, {trend_note}.{h1}"
        )
    elif hold_score >= 1 and hold_score > add_score:
        r.action = "HOLD"
        bits = []
        if upper_bb:
            bits.append(f"upper BB ({r.bb_pos_1d:.2f})")
        if overbought:
            bits.append(f"RSI overbought ({r.rsi_1d:.0f})")
        if near_resistance:
            bits.append(f"near 20d resistance (${r.swing_high:.4f}, {r.dist_to_high_pct:.1f}% away)")
        r.action_reason = (
            f"HOLD - don't chase, and don't trim a conviction hold into strength: "
            f"{', '.join(bits)}. The backtest showed trimming here is a disguised exit that "
            f"surrenders the upside on exactly the up-legs you're holding for."
        )
        # Discretionary trim note - ONLY at a genuinely more extreme reading
        # than plain "upper band", and always labeled optional/personal.
        blowoff_bb = r.bb_pos_1d is not None and r.bb_pos_1d >= DISCRETIONARY_TRIM_BB_MIN
        blowoff_rsi = r.rsi_1d is not None and r.rsi_1d >= DISCRETIONARY_TRIM_RSI
        if blowoff_bb or blowoff_rsi:
            r.discretionary_trim_note = (
                f"(Optional, personal-risk-only) This is a genuine blow-off extreme "
                f"(BB {r.bb_pos_1d:.2f}, RSI {r.rsi_1d:.0f}) - some holders choose to trim a "
                f"small amount here purely for their own risk comfort. That is a discretionary "
                f"choice, NOT something the backtest supports as an edge; the data-backed default "
                f"is still hold."
            )
    else:
        r.action = "HOLD"
        r.action_reason = "Mid-range - no clean add signal right now; hold and wait for a real dip."

    # Standing warnings (independent of the current call)
    if r.funding_extreme:
        r.warnings.append(f"Funding EXTREME ({r.funding_note}) - squeeze/unwind risk either direction.")


# ---------------------------------------------------------------------------
# LEVERAGE / LIQUIDATION GUARDRAILS half - the loud part, now LED with
# ---------------------------------------------------------------------------

@dataclass
class LiquidationRead:
    side: str = DEFAULT_SIDE
    leverage: float = DEFAULT_LEVERAGE
    entry_price: float = 0.0
    maint_margin_frac: float = MAINT_MARGIN_FRAC
    mm_is_real: bool = False        # True = mm came from HL's live `meta` (real
                                     # per-asset value); False = flat fallback
    hl_max_leverage: Optional[float] = None  # HL's real max leverage for this
                                              # asset (None if meta fetch failed)

    liq_price: float = 0.0
    distance_pct: float = 0.0       # fraction, e.g. 0.18 = 18%

    safe_max_leverage: float = 0.0
    risk_label: str = "SAFE"        # SAFE / RISKY / SUICIDAL
    risk_reason: str = ""

    # HORIZON-AWARE fields (v2.5 - see module docstring). horizon_used is the
    # H (days, 3 or 5) actually looked up in vol.horizon_tail_pct, or None if
    # hold_days wasn't passed or no calibration existed (fail-soft: in that
    # case safe_max_leverage/risk_reason are identical to the pre-v2.5
    # single-day-only mechanic). single_day_safe_max_leverage is populated
    # ONLY when horizon_used is not None - the single-day number recomputed
    # alongside the horizon-aware one purely for honest dual-display.
    horizon_used: Optional[float] = None
    single_day_safe_max_leverage: Optional[float] = None

    hard_stop_price: float = 0.0
    hard_stop_pct: float = 0.0

    drop_freq_count: int = 0
    drop_freq_n: int = 0
    drop_freq_note: str = ""

    warnings: List[str] = field(default_factory=list)


def compute_liquidation(
    entry_price: float, side: str, leverage: float, vol: RealizedVol,
    hl_max_leverage: Optional[float] = None, symbol: str = "",
    hold_days: Optional[float] = None,
) -> LiquidationRead:
    """`hl_max_leverage` is HL's REAL per-asset max leverage (from
    fetch_hl_max_leverage / HLNative.meta()). When available, the
    maintenance-margin fraction used for the liq-price math is the REAL
    HL value (mm = 1/(2*maxLeverage) - see LIQUIDATION ASSUMPTIONS in the
    module docstring for the formula + source), and the recommended safe-max
    leverage is capped at that same real maxLeverage so this tool never
    recommends leverage the venue itself won't allow. When None (HL `meta`
    fetch failed), fails soft to the flat MAINT_MARGIN_FRAC approximation
    and says so via `mm_is_real=False` - callers must not silently treat
    this as the real number.

    `hold_days`, if given (v2.5 - see module docstring "HORIZON-AWARE
    LEVERAGE"), snaps to the NEAREST horizon actually calibrated in
    `vol.horizon_tail_pct` (3 or 5 days today) and uses that side-specific,
    OOS-validated adverse-excursion tail in place of the single-day
    `pct95_daily_drop_pct` tail this function used exclusively before this
    parameter existed. FAIL-SOFT: if `hold_days` is None, or
    `vol.horizon_tail_pct` has no calibration at all (thin history - see
    `compute_horizon_tail_frac`'s own sample-size gate), this reproduces the
    EXACT pre-v2.5 single-day mechanic - no existing caller regresses."""
    side_u = (side or DEFAULT_SIDE).strip().upper()
    is_long = side_u in ("LONG", "BUY")
    leverage = max(float(leverage), 1.0)

    mm_is_real = hl_max_leverage is not None and hl_max_leverage > 0
    maint_margin_frac = (1.0 / (2.0 * hl_max_leverage)) if mm_is_real else MAINT_MARGIN_FRAC

    # ── Liquidation price (standalone reimplementation - see module docstring
    # LIQUIDATION ASSUMPTIONS for the maintenance-margin fraction used). ──
    # When leverage is pushed past the venue's own cap, 1/leverage can fall
    # below the maintenance-margin fraction and the raw formula would put the
    # "liquidation price" on the WRONG side of entry (above entry for a long) -
    # which is nonsensical. That only happens for a position HL would already
    # reject; clamp the price to entry (0% away) so the output never shows a
    # long liq'ing above entry, and flag it as past the liquidation line.
    past_liq_line = False
    if is_long:
        liq_price = entry_price * (1.0 - 1.0 / leverage + maint_margin_frac)
        if liq_price >= entry_price:
            liq_price, past_liq_line = entry_price, True
        distance_pct = max((entry_price - liq_price) / entry_price, 0.0)
    else:
        liq_price = entry_price * (1.0 + 1.0 / leverage - maint_margin_frac)
        if liq_price <= entry_price:
            liq_price, past_liq_line = entry_price, True
        distance_pct = max((liq_price - entry_price) / entry_price, 0.0)

    lr = LiquidationRead(
        side=side_u, leverage=leverage, entry_price=entry_price,
        maint_margin_frac=maint_margin_frac, mm_is_real=mm_is_real,
        hl_max_leverage=hl_max_leverage, liq_price=liq_price,
        distance_pct=distance_pct,
    )

    single_day_tail_frac = (vol.pct95_daily_drop_pct or 0.0) / 100.0
    avg_daily_frac = (vol.avg_abs_daily_move_pct or 0.0) / 100.0

    # ── HORIZON-AWARE override (v2.5 - see module docstring + this
    # function's own docstring). Snap hold_days to the nearest calibrated H
    # and swap in that side-specific tail. FAIL-SOFT: leaves tail_frac ==
    # single_day_tail_frac and horizon_used == None (unchanged behavior)
    # whenever hold_days is None or no (H, side) key is available. ──
    lookup_side = "LONG" if is_long else "SHORT"
    tail_frac = single_day_tail_frac
    horizon_used: Optional[float] = None
    if hold_days is not None and vol.horizon_tail_pct:
        candidate_hs = sorted({h for (h, _s) in vol.horizon_tail_pct.keys()})
        if candidate_hs:
            nearest_h = min(candidate_hs, key=lambda h: abs(h - hold_days))
            horizon_key = (nearest_h, lookup_side)
            if horizon_key in vol.horizon_tail_pct:
                tail_frac = vol.horizon_tail_pct[horizon_key] / 100.0
                horizon_used = float(nearest_h)

    # ── Recommended MAX SAFE LEVERAGE: the L where liq distance comfortably
    # clears the relevant tail (95th-pct daily move by default, or the
    # horizon-aware H-day adverse-excursion tail when horizon_used is set) -
    # a normal-to-bad day/hold shouldn't wipe the position. Solve
    # distance(L) = 1/L - mm >= tail_frac. This is WHY a lower-vol coin (e.g.
    # SOL) correctly comes out with a HIGHER safe max leverage than a
    # higher-vol coin (e.g. POPCAT): tail_frac shrinks, so the L that clears
    # it grows. Then HARD-CAP at HL's real maxLeverage - the tool must never
    # suggest leverage the venue doesn't even allow. ──
    denom = tail_frac + maint_margin_frac
    raw_safe_l = (1.0 / denom) if denom > 1e-9 else SAFE_LEV_CAP
    vol_safe_l = float(np.clip(np.floor(raw_safe_l * 2.0) / 2.0, 1.0, SAFE_LEV_CAP))
    lr.safe_max_leverage = min(vol_safe_l, hl_max_leverage) if mm_is_real else vol_safe_l
    lr.horizon_used = horizon_used

    # Single-day-only safe leverage, recomputed via the IDENTICAL solve above
    # (just fed single_day_tail_frac) purely so presentation can show an
    # honest "single-day ceiling" alongside the horizon-aware number, without
    # re-deriving the math elsewhere. Only populated when a horizon override
    # actually applied (horizon_used is not None) - otherwise it would be a
    # redundant duplicate of safe_max_leverage itself.
    if horizon_used is not None:
        sd_denom = single_day_tail_frac + maint_margin_frac
        sd_raw_safe_l = (1.0 / sd_denom) if sd_denom > 1e-9 else SAFE_LEV_CAP
        sd_vol_safe_l = float(np.clip(np.floor(sd_raw_safe_l * 2.0) / 2.0, 1.0, SAFE_LEV_CAP))
        lr.single_day_safe_max_leverage = min(sd_vol_safe_l, hl_max_leverage) if mm_is_real else sd_vol_safe_l

    if mm_is_real and leverage > hl_max_leverage:
        lr.warnings.append(
            f"{leverage:.1f}x {side_u} exceeds Hyperliquid's actual max leverage for "
            f"{symbol or 'this asset'} ({hl_max_leverage:.0f}x) - HL will not let you open this; "
            f"the exchange itself caps you below what you asked for."
        )
    if past_liq_line:
        lr.risk_label = "SUICIDAL"
        lr.risk_reason = (
            f"at {leverage:.1f}x the liquidation line is at or through your entry - "
            f"this position is invalid (already past liquidation the instant it opens)."
        )

    # ── Verdict ──
    if avg_daily_frac > 0 and distance_pct <= avg_daily_frac:
        lr.risk_label = "SUICIDAL"
        lr.risk_reason = (
            f"liq distance ({distance_pct*100:.1f}%) is INSIDE this coin's TYPICAL daily move "
            f"({vol.avg_abs_daily_move_pct:.1f}%) - an ordinary day, not even a bad one, can wipe this out."
        )
    elif leverage > lr.safe_max_leverage:
        lr.risk_label = "RISKY"
        if horizon_used is not None:
            lr.risk_reason = (
                f"liq distance ({distance_pct*100:.1f}%) is below the horizon-aware {horizon_used:.0f}-day "
                f"95th-pct {lookup_side} adverse-excursion tail ({tail_frac*100:.1f}%) - the OOS-measured "
                f"liquidation risk at a CALIBRATED 'safe' band for this horizon is ~4%, but {leverage:.1f}x "
                f"exceeds even that horizon-aware ceiling ({lr.safe_max_leverage:.1f}x)."
            )
        else:
            lr.risk_reason = (
                f"liq distance ({distance_pct*100:.1f}%) is below the 95th-percentile daily drop "
                f"({vol.pct95_daily_drop_pct:.1f}%) buffer - a bad-but-not-rare day can liquidate this."
            )
    else:
        # Label stays "SAFE" so the downstream rank map / != "SAFE" checks in
        # pretrade.py + copilot_alerts.py keep working - the horizon honesty
        # lives in risk_reason (printed right beside it).
        lr.risk_label = "SAFE"
        if horizon_used is not None:
            # HORIZON-AWARE path (v2.5, hold_days was given and calibration
            # existed): print the REAL OOS-validated dual numbers instead of
            # the old blanket "~25-40% at a 3-5d hold" disclaimer (see module
            # docstring "HORIZON-AWARE LEVERAGE" + lev_band_horizon_test.py).
            sd_bit = (
                f"single-day ceiling would be {lr.single_day_safe_max_leverage:.1f}x (only safe if you "
                f"close same-day)" if lr.single_day_safe_max_leverage is not None
                else "single-day ceiling unavailable"
            )
            lr.risk_reason = (
                f"liq distance ({distance_pct*100:.1f}%) clears the HORIZON-AWARE {horizon_used:.0f}-day "
                f"95th-pct {lookup_side} adverse-excursion tail ({tail_frac*100:.1f}%) for a hold of "
                f"~{horizon_used:.0f} days - OOS-measured liquidation risk at this horizon is ~4%, NOT the "
                f"~25-40% the old single-day-only mechanic left you exposed to over a multi-day hold. {sd_bit}."
            )
        else:
            # SINGLE-DAY-ONLY path (hold_days not given, or no calibration
            # for this coin yet - fail-soft): "SAFE" here means
            # SAFE-FOR-ONE-DAY only; the OOS test (lev_band_test.py) showed
            # the multi-day liquidation risk is ~25-40%, so the reason spells
            # that out explicitly, UNCHANGED from the pre-v2.5 mechanic.
            lr.risk_reason = (
                f"liq distance ({distance_pct*100:.1f}%) clears the 95th-pct SINGLE-DAY drop "
                f"({vol.pct95_daily_drop_pct if vol.pct95_daily_drop_pct is not None else float('nan'):.1f}%) "
                f"- a ONE-DAY ceiling only. Holding AT this leverage for 3-5d liquidated ~25-40% of the time "
                f"OOS; drop to the lower 'multi-day safe' leverage if you hold across days."
            )

    # ── Frequency: how often has this coin actually moved this far against
    # the position in a single day, in the sample we fetched? ──
    daily_ret = vol._daily_ret_pct
    lr.drop_freq_n = len(daily_ret)
    if lr.drop_freq_n > 0:
        thresh = distance_pct * 100.0
        if is_long:
            lr.drop_freq_count = sum(1 for x in daily_ret if x <= -thresh)
        else:
            lr.drop_freq_count = sum(1 for x in daily_ret if x >= thresh)
        freq_pct = lr.drop_freq_count / lr.drop_freq_n * 100.0
        if lr.drop_freq_count == 0:
            lr.drop_freq_note = f"never in the last {lr.drop_freq_n}d sampled"
        elif freq_pct >= 20:
            lr.drop_freq_note = f"often - {lr.drop_freq_count}/{lr.drop_freq_n}d ({freq_pct:.0f}%)"
        elif freq_pct >= 5:
            lr.drop_freq_note = f"regularly - {lr.drop_freq_count}/{lr.drop_freq_n}d ({freq_pct:.0f}%)"
        else:
            lr.drop_freq_note = f"rarely - {lr.drop_freq_count}/{lr.drop_freq_n}d ({freq_pct:.1f}%)"
    else:
        lr.drop_freq_note = "insufficient history"

    # ── Hard stop: must trigger clearly BEFORE liquidation (leave a real
    # buffer, since real liquidation happens slightly earlier than this
    # estimate - see LIQUIDATION ASSUMPTIONS), but not so tight that normal
    # daily noise stops it out constantly. ──
    candidate = distance_pct * 0.6
    floor = avg_daily_frac * 1.5 if avg_daily_frac > 0 else candidate * 0.5
    hard_stop_pct = min(candidate, max(floor, candidate * 0.5))
    hard_stop_pct = min(hard_stop_pct, distance_pct * 0.85)  # never let it touch liq distance
    lr.hard_stop_pct = max(hard_stop_pct, 0.0)
    lr.hard_stop_price = (
        entry_price * (1.0 - lr.hard_stop_pct) if is_long
        else entry_price * (1.0 + lr.hard_stop_pct)
    )

    if lr.risk_label != "SAFE":
        lr.warnings.append(
            f"{leverage:.1f}x {side_u} exceeds the safe max ({lr.safe_max_leverage:.1f}x) for this "
            f"coin's current volatility - {lr.risk_label}."
        )

    return lr


# ---------------------------------------------------------------------------
# RANGE-AWARE LEVERAGE - the owner trades a RANGE (3-15x default), not one
# number. Reuses compute_liquidation() (no reimplementation of the liq math)
# at the two ends of the SAFE portion of that range, and produces one plain-
# language sentence about which part of the range is OK vs dangerous on this
# specific coin. See module docstring "RANGE-AWARE LEVERAGE" for the intent.
# ---------------------------------------------------------------------------

def _range_guidance_text(symbol: str, venue_cap: Optional[float], ceiling: float, lo: float, hi: float) -> str:
    """One plain-language sentence: which part of [lo, hi] is usable on this
    coin. `venue_cap` = HL's real maxLeverage (None if unknown/fallback mm).
    `ceiling` = the effective safe-max leverage (already min(vol-safe, venue
    cap) when venue_cap is known - see compute_liquidation)."""
    if venue_cap is not None and venue_cap < hi:
        if venue_cap <= lo:
            safe_note = (
                "and that's within safe limits" if venue_cap <= ceiling
                else f"but even {venue_cap:.0f}x is above the vol-safe line here (~{ceiling:.1f}x) - be extra careful"
            )
            return (
                f"HL caps {symbol} at {venue_cap:.0f}x - your {lo:.0f}-{hi:.0f}x range is limited to "
                f"{venue_cap:.0f}x here ({safe_note}). {venue_cap + 2:.0f}x+ is impossible on this venue."
            )
        top = min(venue_cap, ceiling)
        capper = "HL's venue cap" if venue_cap < ceiling else "the vol-safe line"
        return (
            f"HL caps {symbol} at {venue_cap:.0f}x (vol-safe max ~{ceiling:.1f}x); your usable range here "
            f"is {lo:.0f}-{top:.1f}x - above that hits {capper}, ease off."
        )
    if ceiling >= hi:
        return f"Safe up to ~{ceiling:.0f}x; your full {lo:.0f}-{hi:.0f}x range is comfortably safe on {symbol}."
    if ceiling <= lo:
        return (
            f"Vol-safe max here is only ~{ceiling:.1f}x - BELOW the bottom of your {lo:.0f}-{hi:.0f}x range; "
            f"none of your usual range is safe on {symbol} right now, cut back."
        )
    return (
        f"Safe up to ~{ceiling:.1f}x; your range {lo:.0f}-{ceiling:.0f}x is fine, but the top of your range "
        f"({ceiling:.0f}-{hi:.0f}x) is above {symbol}'s safe line - ease off there."
    )


def format_range_block(symbol: str, dip: DipRead, liq: LiquidationRead, side: str, lev_range: Tuple[float, float]) -> List[str]:
    """Builds the range-aware RISK lines for one coin. Reuses
    compute_liquidation() at the low and high ends of the SAFE portion of
    the owner's range to get real $ liq prices - no duplicated liq math.

    This block explicitly PROMISES the tool's own 3-5d hold window (see
    module docstring RISK PLAN), so - unlike the single-leverage verdict
    line above it in format_brief, which stays single-day-only for
    `copilot_alerts.py` back-compat - it computes its ceiling HORIZON-AWARE
    (v2.5, hold_days=5, the conservative/upper end of the 3-5d window),
    reusing compute_liquidation()'s own solve via a leverage=1.0 probe (that
    result's safe_max_leverage/single_day_safe_max_leverage don't depend on
    the probe leverage - see compute_liquidation). FAIL-SOFT: if the
    horizon calibration is too thin for this coin, the probe's horizon_used
    comes back None and this collapses to exactly the old single-day-only
    ceiling/behavior."""
    lo, hi = lev_range
    venue_cap = liq.hl_max_leverage if liq.mm_is_real else None

    horizon_probe = compute_liquidation(dip.price, side, 1.0, dip.vol, venue_cap, symbol, hold_days=MAX_HOLD_DAYS_RANGE[1])
    ceiling = horizon_probe.safe_max_leverage

    safe_hi = min(hi, ceiling)
    safe_lo = min(lo, safe_hi)  # collapses to a single point if ceiling < lo (e.g. POPCAT)

    lines = [f"  YOUR RANGE ({lo:.0f}-{hi:.0f}x): {_range_guidance_text(symbol, venue_cap, ceiling, lo, hi)}"]
    if horizon_probe.horizon_used is not None and horizon_probe.single_day_safe_max_leverage is not None:
        lines.append(
            f"    Single-day ceiling: {horizon_probe.single_day_safe_max_leverage:.1f}x (only if you'll close "
            f"same-day)  |  Multi-day ({horizon_probe.horizon_used:.0f}d) safe: {ceiling:.1f}x - OOS ~4% "
            f"liquidation risk at this hold horizon"
        )

    if abs(safe_hi - safe_lo) < 1e-9:
        pt = compute_liquidation(dip.price, side, safe_lo, dip.vol, venue_cap, symbol, hold_days=MAX_HOLD_DAYS_RANGE[1])
        lines.append(f"    at {pt.leverage:.1f}x: liq ${pt.liq_price:.4f} ({pt.distance_pct*100:.1f}% away)")
    else:
        pt_lo = compute_liquidation(dip.price, side, safe_lo, dip.vol, venue_cap, symbol, hold_days=MAX_HOLD_DAYS_RANGE[1])
        pt_hi = compute_liquidation(dip.price, side, safe_hi, dip.vol, venue_cap, symbol, hold_days=MAX_HOLD_DAYS_RANGE[1])
        lines.append(
            f"    at {pt_lo.leverage:.1f}x: liq ${pt_lo.liq_price:.4f} ({pt_lo.distance_pct*100:.1f}% away)   |   "
            f"at {pt_hi.leverage:.1f}x: liq ${pt_hi.liq_price:.4f} ({pt_hi.distance_pct*100:.1f}% away)"
        )
    return lines


# ---------------------------------------------------------------------------
# RISK PLAN - the automatable half (see module docstring "RISK PLAN" block
# for the OOS-validation context on each of the 4 pieces below). Reuses
# DipRead.atr_1d/price and LiquidationRead.safe_max_leverage/action_reason -
# no re-derivation of ATR, volatility, or the knife/chop gates.
# ---------------------------------------------------------------------------

@dataclass
class RiskPlan:
    ok: bool = True
    data_note: Optional[str] = None
    symbol: str = ""
    side: str = DEFAULT_SIDE

    risk_pct: float = RISK_PLAN_DEFAULT_RISK_PCT
    account_usd: float = RISK_PLAN_DEFAULT_ACCOUNT_USD
    risk_usd: float = 0.0

    atr_1d: Optional[float] = None
    disaster_stop_mult: float = DISASTER_STOP_ATR_MULT
    disaster_stop_price: Optional[float] = None
    disaster_stop_pct: Optional[float] = None   # fraction of price, e.g. 0.08 = 8%

    size_notional_usd: Optional[float] = None
    size_qty: Optional[float] = None

    max_hold_days: Tuple[float, float] = MAX_HOLD_DAYS_RANGE

    # HORIZON-AWARE (v2.5 - see module docstring). This plan explicitly
    # commits to max_hold_days (3-5d), so safe_max_leverage here is the
    # horizon-matched number (conservative/upper end = 5d) whenever
    # calibration exists; single_day_safe_max_leverage/horizon_used are only
    # populated when a horizon override actually applied (fail-soft:
    # otherwise safe_max_leverage is exactly the old single-day number and
    # these two stay None - see compute_risk_plan).
    safe_max_leverage: Optional[float] = None
    single_day_safe_max_leverage: Optional[float] = None
    horizon_used: Optional[float] = None
    leverage_veto: bool = False
    leverage_veto_reason: Optional[str] = None   # "knife" / "chop" / None


def compute_risk_plan(
    dip: "DipRead", liq: Optional[LiquidationRead], side: str,
    risk_pct: float = RISK_PLAN_DEFAULT_RISK_PCT,
    account_usd: float = RISK_PLAN_DEFAULT_ACCOUNT_USD,
) -> RiskPlan:
    """TODO (semi-auto hook, not built here - this tool stays READ-ONLY):
    every number this returns (size_notional_usd/size_qty, disaster_stop_price,
    max_hold_days, leverage_veto) is already in the shape an order-placement
    layer would need. Once a live account/API key exists, a future execution
    module could read a RiskPlan and place the sized entry + stop order +
    schedule the time-stop exit directly - this function's job is only to
    PRODUCE that plan; it must never place an order itself (would break this
    module's standalone/read-only contract w.r.t. the live bot).

    Builds the 4 OOS-validated mechanics into one plan:
      1. size_notional_usd = risk_usd / disaster_stop_pct (vol-based sizing)
      2. max_hold_days (static, owner-facing time-stop - see module docstring)
      3. disaster_stop_price = entry -/+ DISASTER_STOP_ATR_MULT * ATR(14)
      4. leverage_veto - True when the REGIME (not the return) is a
         falling-knife (dip.action == "WAIT" AND the "FALLING KNIFE"
         substring is in action_reason - the SAME two-part check
         action_bucket() in copilot_alerts.py uses, verbatim; the WAIT gate
         matters because the ADD-in-downtrend reason text also mentions the
         phrase in passing ("...within a downtrend (not a falling knife)...")
         and must NOT false-trigger the veto) or a chop regime
         (dip.trend_1d == "chop", the raw ADX-based regime call, independent
         of whether the WAIT/ADD/HOLD bucket fired today).
    Fails soft (ok=False) if there isn't enough data for ATR (mirrors
    build_dip_read's own insufficient-data handling)."""
    side_u = (side or DEFAULT_SIDE).strip().upper()
    is_long = side_u in ("LONG", "BUY")
    plan = RiskPlan(symbol=dip.symbol, side=side_u, risk_pct=risk_pct, account_usd=account_usd)
    plan.risk_usd = account_usd * risk_pct / 100.0
    plan.safe_max_leverage = liq.safe_max_leverage if liq is not None else None

    if not dip.ok or dip.price is None or dip.atr_1d is None:
        plan.ok = False
        plan.data_note = dip.data_note or f"insufficient {dip.symbol} history for ATR-based sizing"
        return plan

    plan.atr_1d = dip.atr_1d
    stop_dist = DISASTER_STOP_ATR_MULT * dip.atr_1d
    plan.disaster_stop_price = (dip.price - stop_dist) if is_long else (dip.price + stop_dist)
    plan.disaster_stop_pct = (stop_dist / dip.price) if dip.price else None

    if plan.disaster_stop_pct is not None and plan.disaster_stop_pct > 1e-9:
        plan.size_notional_usd = plan.risk_usd / plan.disaster_stop_pct
        plan.size_qty = plan.size_notional_usd / dip.price

    # ---- HORIZON-AWARE leverage (v2.5 - see module docstring "HORIZON-AWARE
    # LEVERAGE"): this plan explicitly commits to max_hold_days (3-5d), so
    # its OWN safe_max_leverage should be the horizon-matched number
    # (conservative/upper end = 5d), not the single-day number `liq` was
    # computed at by the caller. Reuses compute_liquidation()'s own solve
    # (a leverage=1.0 probe - safe_max_leverage/single_day_safe_max_leverage
    # are independent of the probe leverage, see that function) rather than
    # re-deriving the tail-frac math here. FAIL-SOFT: if dip.vol has no
    # horizon calibration yet (thin history), the probe's horizon_used comes
    # back None and plan.safe_max_leverage collapses to exactly liq's
    # pre-existing single-day number. ----
    if liq is not None:
        venue_cap = liq.hl_max_leverage if liq.mm_is_real else None
        horizon_probe = compute_liquidation(
            dip.price, side_u, 1.0, dip.vol, venue_cap, dip.symbol,
            hold_days=MAX_HOLD_DAYS_RANGE[1],
        )
        plan.safe_max_leverage = horizon_probe.safe_max_leverage
        plan.single_day_safe_max_leverage = horizon_probe.single_day_safe_max_leverage
        plan.horizon_used = horizon_probe.horizon_used

    # NOTE: the "FALLING KNIFE" substring check is deliberately gated on
    # dip.action == "WAIT" (mirroring action_bucket() exactly) - the ADD
    # branch's own downtrend reason text contains the phrase too, e.g.
    # "...within a downtrend (not a falling knife)...", which would
    # false-trigger the veto on an ungated substring check.
    is_knife = dip.action == "WAIT" and "FALLING KNIFE" in (dip.action_reason or "").upper()
    is_chop = dip.trend_1d == "chop"
    if is_knife:
        plan.leverage_veto = True
        plan.leverage_veto_reason = "knife"
    elif is_chop:
        plan.leverage_veto = True
        plan.leverage_veto_reason = "chop"

    return plan


def format_risk_plan(plan: RiskPlan) -> List[str]:
    lines = ["RISK PLAN (mechanical - the automatable half):"]
    if not plan.ok:
        lines.append(f"  unavailable: {plan.data_note}")
        return lines

    lo_d, hi_d = plan.max_hold_days
    if plan.size_notional_usd is not None:
        lines.append(
            f"  Size for {plan.risk_pct:.1f}% risk (${plan.risk_usd:,.0f} on ${plan.account_usd:,.0f} account): "
            f"~${plan.size_notional_usd:,.0f} notional at the {plan.disaster_stop_mult:.0f}xATR stop "
            f"(${plan.disaster_stop_price:.4f}, {plan.disaster_stop_pct*100:.1f}% away)"
        )
    else:
        lines.append("  Size: unavailable (zero/degenerate stop distance)")
    lines.append(
        f"  Max hold: ~{lo_d:.0f}-{hi_d:.0f} days then exit regardless - ruin risk rises monotonically the "
        f"longer you hold (OOS); shorter is always safer, so 3-5d is a practical floor (thesis-time vs churn), "
        f"NOT a proven sweet spot. This time-stop does real, additive tail-cutting a price stop doesn't."
    )
    lines.append(
        f"  Disaster stop: ${plan.disaster_stop_price:.4f} ({plan.disaster_stop_mult:.0f}xATR) - a loose "
        f"'I'm wrong' backstop, NOT validated tail insurance: OOS at a 3-5d hold a 2xATR stop is ~return-neutral "
        f"and doesn't meaningfully cut CVaR/ruin there (it sits ~13% out, past the ruin line most times it fires). "
        f"Real tail-cutting needs ~1-1.5xATR at the cost of far more whipsaw."
    )
    if plan.horizon_used is not None and plan.single_day_safe_max_leverage is not None:
        # HORIZON-AWARE path (v2.5): this plan committed to a 3-5d hold, so
        # show BOTH numbers honestly instead of one blended figure - see
        # module docstring "HORIZON-AWARE LEVERAGE".
        lev_bit = (
            f"Single-day ceiling: {plan.single_day_safe_max_leverage:.1f}x (only if you'll close same-day)  |  "
            f"Multi-day ({plan.horizon_used:.0f}d) safe: {plan.safe_max_leverage:.1f}x - OOS ~4% liquidation "
            f"risk at this hold horizon"
        )
    else:
        lev_bit = (
            f"safe <= {plan.safe_max_leverage:.1f}x here" if plan.safe_max_leverage is not None
            else "safe leverage unknown (no liquidation data)"
        )
    if plan.leverage_veto:
        which = "FALLING KNIFE" if plan.leverage_veto_reason == "knife" else "CHOP"
        lev_bit += (
            f"; {which} regime -> stay spot or <=2x, the risk here is a -10% path that "
            f"liquidates, not the direction"
        )
    lines.append(f"  Leverage: {lev_bit}")
    lines.append(
        "  (Sizing/hold/stop/leverage-cap above are OOS-validated mechanics; the ADD call above "
        "is a discretionary entry-timing hint, not edge - this plan is how to manage IF you take "
        "the trade, the entry call is yours.)"
    )
    return lines


# ---------------------------------------------------------------------------
# FUNDING-AS-CARRY line (Theme A, item 2). Pure arithmetic (rate x notional x
# HL's real 24-payments/day schedule) - NEVER framed as a fade/predictive
# signal. That was tested (EDGE INSTRUMENTS 2026-07-27, TAILWIND gate) and
# came back null, so this module must not imply funding predicts direction -
# it is cost/carry context only, same spirit as the fee card.
# ---------------------------------------------------------------------------

def _funding_direction_note(dip: "DipRead", side: str, notional: float) -> str:
    if dip.funding_rate is None:
        return f"FUNDING: no data available for {dip.symbol}."

    rate = dip.funding_rate           # HL hourly rate, e.g. 0.0001 = 0.01%/hr
    daily_rate = rate * FUNDING_PAYMENTS_PER_DAY
    side_u = (side or DEFAULT_SIDE).strip().upper()
    is_long = side_u in ("LONG", "BUY")
    # HL convention: positive funding = longs pay shorts (perp trading above
    # index). A short's exposure is the mirror image of a long's.
    eff = rate if is_long else -rate
    if eff > 1e-12:
        verb = "PAYS"
    elif eff < -1e-12:
        verb = "EARNS"
    else:
        verb = "~flat -"
    daily_usd = abs(daily_rate) * notional
    extreme_bit = "  >>> EXTREME funding - crowded positioning, squeeze/unwind risk. <<<" if dip.funding_extreme else ""
    return (
        f"FUNDING (carry cost, not a signal): {rate*100:+.4f}%/hr (~{daily_rate*100:+.3f}%/day) - "
        f"{side_u} {verb} ~${daily_usd:,.2f}/day on ~${notional:,.0f} notional. "
        f"Factor this into hold length on multi-day positions.{extreme_bit}"
    )


# ---------------------------------------------------------------------------
# BRIEF FORMATTER - LEADS with price/trend, then ADD/HOLD/WAIT call, then
# the liquidation guardrail block (prominent), then warnings, then honesty footer
# ---------------------------------------------------------------------------

def format_brief(
    symbol: str, dip: DipRead, liq: Optional[LiquidationRead], equity: float, leverage: float, side: str,
    lev_range: Optional[Tuple[float, float]] = None,
    risk_pct: float = RISK_PLAN_DEFAULT_RISK_PCT,
    risk_account: float = RISK_PLAN_DEFAULT_ACCOUNT_USD,
    weather: Optional["MarketWeather"] = None,  # type: ignore[name-defined]  # noqa: F821 - only used for the CALL LEDGER row below (see call_logger.py); never displayed/coupled in the brief text itself, per the NOTE above
    source: str = "read",
) -> str:
    # NOTE: MARKET WEATHER is deliberately NOT threaded into this per-coin
    # formatter's DISPLAYED text. It is a market-wide LONG permission/sizing
    # gate shown ONCE at the top of the run (see main() / weather.py) - it
    # does NOT couple to or sharpen the per-coin ADD/dip call (an OOS test
    # refuted "washed-out makes dips better"; dips actually underperform
    # inside washed-out). Keeping it out of the printed brief is what
    # enforces that decoupling. The optional `weather` param above is ONLY
    # used to enrich the CALL LEDGER row (see call_logger.py) with
    # weather_regime/breadth20/btc_vs_ema50 for the later forward-evidence
    # resolve (H2) - it never changes a single line of the text below.
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"{symbol} CO-PILOT v2 - {ts}"]

    # ---- CALL LEDGER (forward-evidence logging) - entry-time-safe snapshot,
    # captured from the SAME already-computed dip/liq/weather objects this
    # brief renders below, never recomputed. FAIL-NEUTRAL: log_call() already
    # swallows its own exceptions, but this call is additionally wrapped so a
    # bug in the import itself can never break a brief. Gated by
    # COPILOT_CALL_LOG env flag (default "true") inside log_call(). ----
    try:
        from call_logger import log_call  # local import: keeps this optional logging concern out of the module's normal import path
        log_call(symbol, dip, liq, weather=weather, source=source)
    except Exception as e:  # noqa: BLE001 - a logging bug must never break a brief
        print(f"[copilot] call ledger logging failed for {symbol}: {e}", file=sys.stderr)

    if not dip.ok:
        lines.append(f"NO DATA: {dip.data_note}")
        return "\n".join(lines)

    # ---- 1. LEAD: price/trend one-liner ----
    adx_s = f"{dip.adx_1d:.0f}" if dip.adx_1d is not None else "?"
    ret7 = f"{dip.ret_7d_pct:+.1f}%/7d" if dip.ret_7d_pct is not None else "7d n/a"
    lines.append(
        f"Price ${dip.price:.4f} | {dip.trend_1d.upper()} ({dip.trend_strength}, ADX {adx_s}) | {ret7}"
    )

    # ---- 1b. FUNDING-AS-CARRY line (Theme A item 2) - cost context only ----
    notional = equity * leverage
    lines.append(_funding_direction_note(dip, side, notional))
    lines.append("")

    # ---- 2. ADD / HOLD / WAIT call ----
    level_bit = ""
    if dip.action == "ADD" and dip.add_level:
        level_bit = f" near ${dip.add_level:.4f}"
    lines.append(f"CALL: {dip.action}{level_bit}")
    lines.append(f"  {dip.action_reason}")
    add_s = f"${dip.add_level:.4f}" if dip.add_level else "n/a"
    ref_s = f"${dip.ref_high_level:.4f}" if dip.ref_high_level else "n/a"
    lines.append(f"  Add zone: <= {add_s} (20d support)  |  20d high (reference only, not a trim trigger): {ref_s}")
    if dip.discretionary_trim_note:
        lines.append(f"  {dip.discretionary_trim_note}")
    lines.append("")

    # ---- 3. LIQUIDATION GUARDRAIL block - loud, prominent ----
    if liq is None:
        lines.append("RISK: unavailable (no price data).")
    else:
        notional = equity * leverage
        mm_bit = (
            f"HL real max {liq.hl_max_leverage:.0f}x, mm {liq.maint_margin_frac*100:.2f}%"
            if liq.mm_is_real else
            f"HL max leverage unknown - using FALLBACK flat mm {liq.maint_margin_frac*100:.2f}% (less accurate)"
        )
        lines.append(
            f"[{liq.risk_label}] RISK: Safe leverage <= {liq.safe_max_leverage:.1f}x for {symbol} right now. ({mm_bit})"
        )
        lines.append(
            f"  At your {leverage:.1f}x {side.upper()} (${equity:,.0f} equity, ~${notional:,.0f} notional): "
            f"liq at ${liq.liq_price:.4f} ({liq.distance_pct*100:.1f}% away) - how often has {symbol} "
            f"moved that far in a day? {liq.drop_freq_note}."
        )
        lines.append(f"  {liq.risk_reason}")
        lines.append(
            f"  Hard stop: ${liq.hard_stop_price:.4f} ({liq.hard_stop_pct*100:.1f}% away) - "
            f"exit here manually, well before HL would liquidate you."
        )
        if liq.risk_label != "SAFE":
            lines.append(
                f"  >>> WARNING: {leverage:.1f}x is {liq.risk_label} given {symbol}'s real volatility "
                f"- reduce toward {liq.safe_max_leverage:.1f}x or lower. <<<"
            )
        if dip.action == "ADD" and liq.risk_label != "SAFE":
            lines.append(
                f"  >>> The call says ADD, but at {leverage:.1f}x you are already {liq.risk_label} "
                f"- fix leverage BEFORE adding size, don't stack risk on top of risk. <<<"
            )
        if lev_range is not None:
            lines.extend(format_range_block(symbol, dip, liq, side, lev_range))

    # ---- 3b. RISK PLAN - the automatable half (see module docstring) ----
    lines.append("")
    lines.extend(format_risk_plan(compute_risk_plan(dip, liq, side, risk_pct, risk_account)))

    # ---- 4. WARNINGS ----
    all_warnings = list(dip.warnings) + (liq.warnings if liq else [])
    if all_warnings:
        lines.append("")
        lines.append("WARNINGS:")
        for w in all_warnings:
            lines.append(f"  - {w}")

    # ---- 5. Honest self-labeling footer ----
    lines.append("")
    lines.append(HONESTY_FOOTER)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# Hyperliquid lists its "1000x" meme perps with a lowercase-k prefix
# (kPEPE = 1000 PEPE). A naive .upper() turns kPEPE -> KPEPE, which 500s
# against HL's candle API and SILENTLY drops the coin - this was breaking 3 of
# the 9 owner coins (kPEPE/kBONK/kSHIB) in the daily forward-evidence job, so
# the call ledger the 60-90d study depends on was missing them. Normalize to
# HL's canonical casing. Anchored on a known set so real K-coins (KAS, KAITO)
# are never mangled; also preserves a user-typed lowercase-k form for any
# future k-meme not in the set.
_HL_K_MEMES = {
    "KPEPE": "kPEPE", "KBONK": "kBONK", "KSHIB": "kSHIB", "KFLOKI": "kFLOKI",
    "KLUNC": "kLUNC", "KDOGS": "kDOGS", "KNEIRO": "kNEIRO",
}


def _norm_symbol(s: str) -> str:
    s = s.strip()
    u = s.upper()
    if u in _HL_K_MEMES:
        return _HL_K_MEMES[u]
    # user already typed HL's lowercase-k form (e.g. kPEPE) - preserve it
    if len(s) >= 2 and s[0] == "k" and s[1:].isupper():
        return "k" + s[1:].upper()
    return u


def _parse_symbols(raw: str) -> List[str]:
    syms = [_norm_symbol(s) for s in raw.split(",") if s.strip()]
    return syms or list(DEFAULT_SYMBOLS)


def _parse_lev_range(raw: str) -> Optional[Tuple[float, float]]:
    """Parses 'LO-HI' (e.g. '3-15'). Pass '' or 'none' to disable the
    range-aware block entirely and fall back to single-`--leverage` only."""
    if not raw or raw.strip().lower() == "none":
        return None
    parts = raw.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"--lev-range must be LO-HI (e.g. 3-15), got {raw!r}")
    try:
        lo, hi = float(parts[0]), float(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"--lev-range must be LO-HI (e.g. 3-15), got {raw!r}")
    if lo <= 0 or hi <= 0 or lo >= hi:
        raise argparse.ArgumentTypeError(f"--lev-range LO must be > 0 and < HI, got {raw!r}")
    return (lo, hi)


def main() -> None:
    ap = argparse.ArgumentParser(description="WAGMI Co-Pilot v2 - dip-deployment/hold discipline + liquidation guardrails (read-only, multi-symbol)")
    ap.add_argument("--symbol", type=str, default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbol list (default: BTC,SOL,POPCAT)")
    ap.add_argument("--equity", type=float, default=DEFAULT_EQUITY_USD, help="Account equity in USD")
    ap.add_argument("--leverage", type=float, default=DEFAULT_LEVERAGE, help="Intended single leverage (back-compat risk line)")
    ap.add_argument("--lev-range", type=str, default=DEFAULT_LEV_RANGE_STR, help="Leverage RANGE LO-HI you actually trade (default 3-15; pass 'none' to disable)")
    ap.add_argument("--side", type=str, default=DEFAULT_SIDE, choices=["long", "short", "LONG", "SHORT"], help="Intended position side")
    ap.add_argument("--discord", action="store_true", help="Send the brief(s) via Discord (WAGMI_DISCORD_WEBHOOK)")
    ap.add_argument(
        "--trade", type=str, default=None,
        help='Pre-trade fee/funding/liquidation card: "SYMBOL SIDE LEVERAGEx MARGIN_USD", '
             'e.g. "POPCAT long 3x 800" (800 = margin/collateral, not notional - notional = margin x leverage)',
    )
    ap.add_argument(
        "--risk-pct", type=float, default=RISK_PLAN_DEFAULT_RISK_PCT,
        help=f"RISK PLAN: %% of account risked per trade if the disaster stop is hit (default {RISK_PLAN_DEFAULT_RISK_PCT:.1f})",
    )
    ap.add_argument(
        "--risk-account", type=float, default=RISK_PLAN_DEFAULT_ACCOUNT_USD,
        help=f"RISK PLAN: account size (USD) used for its sizing math, separate from --equity (default {RISK_PLAN_DEFAULT_ACCOUNT_USD:.0f})",
    )
    args = ap.parse_args()

    client = _get_hl_client()

    if args.trade:
        from pretrade import build_trade_card, format_trade_card, parse_trade_spec  # local: avoids import cost/order issues for the normal path
        try:
            symbol, side, leverage, margin_usd = parse_trade_spec(args.trade)
        except ValueError as e:
            print(f"[copilot] --trade error: {e}", file=sys.stderr)
            sys.exit(1)
        card = build_trade_card(client, symbol, side, leverage, margin_usd, risk_pct=args.risk_pct, risk_account=args.risk_account)
        text = format_trade_card(card)
        print(text)
        if args.discord:
            tools_dir = os.path.join(BOT_DIR, "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            from discord_notify import send_discord
            send_discord(text, title=f"WAGMI Pre-Trade Card - {symbol} {side.upper()}")
        return

    symbols = _parse_symbols(args.symbol)
    try:
        lev_range = _parse_lev_range(args.lev_range)
    except argparse.ArgumentTypeError as e:
        print(f"[copilot] --lev-range error: {e}", file=sys.stderr)
        sys.exit(1)

    # ---- MARKET WEATHER - market-wide, computed ONCE per run (not per coin) ----
    # and shown ONCE at the top of the brief - it's shared context for every
    # symbol below, not a per-symbol reading. See weather.py module docstring
    # for what it measures and why; it never changes any symbol's ADD/HOLD/WAIT
    # call, only colors the ADD line with a short caution/weight aside.
    from weather import compute_market_weather  # local import: avoids a module-load-order cycle (weather.py imports copilot.py's helpers)
    weather = compute_market_weather(client)
    print(weather.line)
    print()

    briefs = []
    for symbol in symbols:
        dip = build_dip_read(client, symbol)
        hl_max_lev = fetch_hl_max_leverage(client, symbol) if dip.ok else None
        liq = compute_liquidation(dip.price, args.side, args.leverage, dip.vol, hl_max_lev, symbol) if dip.ok else None
        brief = format_brief(symbol, dip, liq, args.equity, args.leverage, args.side, lev_range, args.risk_pct, args.risk_account, weather=weather, source="read")
        print(brief)
        print()
        briefs.append(brief)

    if args.discord:
        tools_dir = os.path.join(BOT_DIR, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from discord_notify import send_discord
        combined = weather.line + "\n\n" + "\n\n".join(briefs)
        send_discord(combined, title="WAGMI Co-Pilot v2 Brief")


if __name__ == "__main__":
    main()
