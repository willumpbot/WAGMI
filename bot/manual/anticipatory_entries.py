"""
Anticipatory Entry Engine -- Precision limit-order style entries.

PROBLEM: We enter trades reactively at market price when a strategy fires.
  Example: SOL SELL entered at $82.29 (RSI 37, recovering) instead of
  waiting for bounce to $83.50 (RSI 70+, overbought reversal).
  Better entry = tighter stop = higher leverage = better R:R.

SOLUTION: Analyze market structure, set PENDING entries at optimal levels,
  and execute only when price AND confirmation conditions are met.

  For SELL entries (shorting overbought):
    - Target: BB upper band or recent resistance
    - Trigger: RSI > 70 AND price reaches target
    - SL: tight (0.8-1.2% above entry)
    - TP: EMA20 or BB lower (mean reversion)
    - Leverage: 8-15x

  For BUY entries (buying oversold bounces):
    - Target: BB lower band or recent support
    - Trigger: RSI crosses back above 35 (confirmation)
    - SL: tight below the low
    - TP: EMA20 or BB upper
    - Leverage: 8-15x

The math: SOL SELL at $83.50 (RSI 72) with SL $84.30 (0.95%)
  and TP $80.50 (3.6%) gives R:R=3.8:1.
  At 10x leverage, 1% equity risk: win=$3.38, loss=$0.89.
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger("bot.manual.anticipatory")

# -- Paths ------------------------------------------------------------------
_DATA_DIR = os.path.join("data", "manual")
_PENDING_PATH = os.path.join(_DATA_DIR, "pending_entries.json")
_HISTORY_PATH = os.path.join(_DATA_DIR, "anticipatory_history.jsonl")

# -- Constants --------------------------------------------------------------
DEFAULT_EXPIRY_HOURS = 12.0
MIN_RR_RATIO = 2.0          # Minimum reward:risk for anticipatory entries
MIN_RR_RATIO_CANDLE = 1.2  # Lower R:R for high-WR candle patterns (65-77% accuracy)
MAX_PENDING_PER_SYMBOL = 3   # Max pending entries per symbol (raised for more setup types)
MAX_PENDING_TOTAL = 12       # Max total pending entries (raised for more setup types)
MIN_STOP_PCT = 0.005         # 0.5% minimum stop width (tightened for precision entries)
MAX_STOP_PCT = 0.010         # 1.0% maximum stop width (was 1.5% -- precision entry justifies tighter)
# Asymmetric stops: LONGs need wide stops (ATR x 2.0), SHORTs tight (ATR x 1.2)
# 24% of candles wick past previous low -- add 0.2% buffer beyond swing levels
MAX_STOP_PCT_BUY = 0.020     # 2.0% max for BUY (LONGs need room to breathe)
MAX_STOP_PCT_SELL = 0.012    # 1.2% max for SELL (SHORTs work better with tight stops)
SWING_SL_BUFFER_PCT = 0.002  # 0.2% buffer beyond swing high/low used as SL
SWING_SL_LOOKBACK = 5        # 5-candle swing high/low for structure-based SL
DEFAULT_LEVERAGE_LOW = 10.0  # Raised from 8x -- anticipatory entries have better R:R
DEFAULT_LEVERAGE_HIGH = 15.0
PRICE_INVALIDATION_PCT = 0.03  # Remove if price moves 3% away from target

# -- Volume Confirmation Constants ------------------------------------------
VOL_AVG_PERIOD = 20            # Lookback for average volume
VOL_MIN_RATIO = 0.8            # Minimum volume ratio vs average (dead market filter)
VOL_REVERSAL_MIN_RATIO = 1.2   # Reversal setups need higher volume (conviction)
VOL_TREND_MIN_RATIO = 0.9      # Trend continuation OK on normal volume
VOL_SPIKE_RATIO = 2.0          # Volume spike threshold (institutional interest)
VOL_SPIKE_CONFIDENCE_BOOST = 15 # Confidence boost on volume spike

# Setup type classifications for volume requirements
REVERSAL_SETUPS = {
    "bb_upper_rejection", "bb_lower_bounce",
    "resistance_rejection", "support_bounce",
    "session_high_rejection", "session_low_bounce",
    "round_number_rejection", "round_number_bounce",
    "vwap_reversion_sell", "vwap_reversion_buy",
    "exhaustion_reversal", "shooting_star_short",
    "adx_exhaustion_sell", "adx_exhaustion_buy",
}
TREND_SETUPS = {
    "ema20_bear_touch", "ema20_bull_touch",
    "institutional_continuation",
    "btc_lead_bearish", "btc_lead_bullish",
}

# -- Candle Pattern Constants -----------------------------------------------
# Setup 10: Exhaustion Reversal (SOL, BTC only)
EXHAUSTION_VOL_RATIO = 1.5       # Volume must exceed 1.5x average
EXHAUSTION_BODY_RATIO = 0.7      # Body must be < 0.7x average body
EXHAUSTION_WICK_MIN_PCT = 0.003  # Wick must be > 0.3% of price
EXHAUSTION_SYMBOLS = {"SOL", "BTC"}  # 77% SOL, 71% BTC
EXHAUSTION_CONFIDENCE = 75

# Setup 11: Institutional Continuation (SOL, HYPE only)
INSTITUTIONAL_VOL_RATIO = 2.0    # Volume must exceed 2.0x average
INSTITUTIONAL_BODY_RATIO = 1.5   # Body must be > 1.5x average body
INSTITUTIONAL_SYMBOLS = {"SOL", "HYPE"}  # 70% SOL, 61% HYPE
INSTITUTIONAL_CONFIDENCE = 70

# Setup 12: Shooting Star Short (HYPE only)
SHOOTING_STAR_WICK_RATIO = 0.6   # Upper wick > 60% of range
SHOOTING_STAR_BODY_RATIO = 0.3   # Body < 30% of range
SHOOTING_STAR_SYMBOLS = {"HYPE"}  # 68% accuracy on HYPE
SHOOTING_STAR_CONFIDENCE = 65
SHOOTING_STAR_SL_BUFFER_PCT = 0.002  # 0.2% buffer above high

RSI_OVERBOUGHT = 65.0        # Start watching for sell entries
RSI_OVERBOUGHT_TRIGGER = 70.0  # Confirm overbought for execution
RSI_OVERSOLD = 35.0           # Start watching for buy entries
RSI_OVERSOLD_TRIGGER = 35.0   # RSI crossing back ABOVE this from below

# -- Multi-Timeframe Alignment ---------------------------------------------
# 6h sets DIRECTION, 1h finds SETUP, 5m times ENTRY.
# Insight journal: "1h+6h aligned = 33% WR, misaligned = 10%."
TF_FLAT_THRESHOLD = 0.003     # EMAs within 0.3% = flat/neutral
LEVERAGE_ALIGNED = (12.0, 15.0)    # Max conviction -- 6h confirms direction
LEVERAGE_NEUTRAL = (8.0, 10.0)     # 6h is flat -- moderate sizing
LEVERAGE_COUNTER = (3.0, 5.0)      # Against 6h trend -- minimal or skip


@dataclass
class PendingEntry:
    """A pending anticipatory entry waiting for conditions to be met."""
    entry_id: str
    symbol: str
    side: str                   # BUY or SELL
    target_price: float         # Price level we want to enter at
    sl: float                   # Stop loss
    tp: float                   # Primary take profit
    tp2: float                  # Extended take profit
    trigger_conditions: Dict[str, Any]  # Conditions that must all be true
    confidence: float           # 0-100
    leverage: float             # Suggested leverage
    risk_pct: float             # % of equity to risk
    expiry: float               # Unix timestamp when this expires
    reasoning: str              # Human-readable thesis
    setup_type: str             # e.g. "overbought_reversal", "oversold_bounce"
    source: str                 # What generated this (e.g. "bb_upper", "resistance")
    created_at: float           # Unix timestamp
    created_at_iso: str
    rr_ratio: float             # Expected reward:risk ratio
    stop_width_pct: float       # Stop as % of entry

    # Tracking
    best_approach_price: float = 0.0   # Closest price got to target
    checks: int = 0                     # How many times we checked this
    status: str = "pending"             # pending / triggered / expired / invalidated

    # Optional confluence/multi-TF fields
    confluence_count: int = 0
    confluence_sources: List[str] = field(default_factory=list)
    timeframe_alignment: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PendingEntry":
        return PendingEntry(**{k: v for k, v in d.items()
                               if k in PendingEntry.__dataclass_fields__})


@dataclass
class TriggerResult:
    """Result of checking a pending entry against current conditions."""
    triggered: bool
    conditions_met: Dict[str, bool]
    reason: str


def _compute_indicators(df: pd.DataFrame) -> Dict[str, float]:
    """Compute all indicators needed for anticipatory entry analysis.

    Returns dict with: close, ema20, ema50, rsi, atr, bb_upper, bb_lower,
    bb_mid, vwap (approx), swing_high, swing_low, atr_pct, and volume metrics.
    """
    if df is None or len(df) < 20:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    c = float(close.iloc[-1])

    # EMAs
    ema20 = float(close.ewm(span=20).mean().iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_s.replace(0, 1e-12)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1])
    # Previous RSI for crossover detection
    rsi_prev = float(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else rsi

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
    atr_pct = atr / c if c > 0 else 0

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = float((sma20 + 2 * std20).iloc[-1])
    bb_lower = float((sma20 - 2 * std20).iloc[-1])
    bb_mid = float(sma20.iloc[-1])

    # Swing high/low (last 20 bars)
    lookback = min(20, len(df))
    swing_high = float(high.iloc[-lookback:].max())
    swing_low = float(low.iloc[-lookback:].min())

    # 5-candle swing high/low for structure-based SL placement
    lookback_5 = min(SWING_SL_LOOKBACK, len(df))
    swing_high_5 = float(high.iloc[-lookback_5:].max())
    swing_low_5 = float(low.iloc[-lookback_5:].min())

    # Recent resistance/support (local peaks/troughs in last 50 bars)
    lookback_long = min(50, len(df))
    resistance = _find_resistance(high.iloc[-lookback_long:], c)
    support = _find_support(low.iloc[-lookback_long:], c)

    # VWAP approximation (typical price * volume weighted)
    if "volume" in df.columns:
        typical = (high + low + close) / 3
        cum_vol = df["volume"].rolling(20, min_periods=1).sum()
        cum_tp_vol = (typical * df["volume"]).rolling(20, min_periods=1).sum()
        vwap = float((cum_tp_vol / cum_vol.replace(0, 1e-12)).iloc[-1])
    else:
        vwap = bb_mid  # Fallback: use SMA20 as proxy

    # -- Candle Body & Wick Analysis ----------------------------------------
    last_open = float(df["open"].iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])
    last_close = float(close.iloc[-1])

    candle_body = abs(last_close - last_open)
    candle_range = last_high - last_low if last_high > last_low else 1e-12
    upper_wick = last_high - max(last_open, last_close)
    lower_wick = min(last_open, last_close) - last_low
    candle_is_green = last_close > last_open

    # Average body over lookback period for comparison
    body_series = (close - df["open"]).abs()
    avg_body = float(body_series.iloc[-VOL_AVG_PERIOD:].mean()) if len(df) >= VOL_AVG_PERIOD else candle_body

    # Body as fraction of range
    body_pct_of_range = candle_body / candle_range if candle_range > 1e-12 else 0.0
    upper_wick_pct = upper_wick / candle_range if candle_range > 1e-12 else 0.0
    lower_wick_pct = lower_wick / candle_range if candle_range > 1e-12 else 0.0

    # Prominent wick: max wick as % of price
    prominent_wick_pct = max(upper_wick, lower_wick) / c if c > 0 else 0.0

    # -- Volume Analysis ----------------------------------------------------
    vol_avg = 0.0
    vol_current = 0.0
    vol_ratio = 0.0
    vol_is_buying = candle_is_green  # True if close > open (buying pressure candle)
    if "volume" in df.columns and len(df) >= VOL_AVG_PERIOD:
        vol_series = df["volume"]
        vol_avg = float(vol_series.iloc[-VOL_AVG_PERIOD:].mean())
        vol_current = float(vol_series.iloc[-1])
        vol_ratio = vol_current / vol_avg if vol_avg > 0 else 0.0

    return {
        "close": c,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "rsi_prev": rsi_prev,
        "atr": atr,
        "atr_pct": atr_pct,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_mid": bb_mid,
        "vwap": vwap,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "swing_high_5": swing_high_5,
        "swing_low_5": swing_low_5,
        "resistance": resistance,
        "support": support,
        "vol_avg": vol_avg,
        "vol_current": vol_current,
        "vol_ratio": vol_ratio,
        "vol_is_buying": vol_is_buying,
        # Candle body/wick metrics (for pattern setups 10-12)
        "candle_body": candle_body,
        "avg_body": avg_body,
        "candle_range": candle_range,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "body_pct_of_range": body_pct_of_range,
        "prominent_wick_pct": prominent_wick_pct,
        "candle_is_green": candle_is_green,
        "last_open": last_open,
        "last_high": last_high,
        "last_low": last_low,
    }


def _find_resistance(highs: pd.Series, current_price: float) -> float:
    """Find nearest resistance level above current price."""
    levels = []
    arr = highs.values
    for i in range(1, len(arr) - 1):
        if arr[i] > arr[i - 1] and arr[i] > arr[i + 1]:
            if arr[i] > current_price:
                levels.append(float(arr[i]))

    if not levels:
        return float(highs.max())

    return min(levels)


def _find_support(lows: pd.Series, current_price: float) -> float:
    """Find nearest support level below current price."""
    levels = []
    arr = lows.values
    for i in range(1, len(arr) - 1):
        if arr[i] < arr[i - 1] and arr[i] < arr[i + 1]:
            if arr[i] < current_price:
                levels.append(float(arr[i]))

    if not levels:
        return float(lows.min())

    return max(levels)


def _compute_6h_trend(df_6h):
    """Determine higher-timeframe trend direction from 6h candles.

    Returns "bullish", "bearish", "neutral", or "unknown".
    """
    if df_6h is None or len(df_6h) < 50:
        return "unknown"

    close = df_6h["close"].astype(float)
    ema20 = close.ewm(span=20, min_periods=20, adjust=False).mean()
    ema50 = close.ewm(span=50, min_periods=50, adjust=False).mean()

    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])

    if e50 == 0:
        return "unknown"

    pct_diff = (e20 - e50) / e50

    if abs(pct_diff) < TF_FLAT_THRESHOLD:
        return "neutral"
    elif pct_diff > 0:
        return "bullish"
    else:
        return "bearish"


def _get_timeframe_alignment(side, trend_6h):
    """Determine alignment between trade side and 6h trend.

    Returns "aligned", "neutral", "counter", or "unknown".
    """
    if trend_6h == "unknown":
        return "unknown"
    if trend_6h == "neutral":
        return "neutral"

    if (side == "BUY" and trend_6h == "bullish") or (side == "SELL" and trend_6h == "bearish"):
        return "aligned"
    else:
        return "counter"


def _detect_5m_reversal(df_5m, side):
    """Detect 5m reversal candle patterns for precision entry timing.

    Returns dict with: found, pattern, entry_price, stop_price.
    """
    result = {"found": False, "pattern": "none", "entry_price": 0.0, "stop_price": 0.0}

    if df_5m is None or len(df_5m) < 5:
        return result

    last = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]

    o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
    body = abs(c - o)
    candle_range = h - l
    if candle_range <= 0:
        return result

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if side == "BUY":
        is_hammer = (lower_wick > 0.6 * candle_range and body < 0.3 * candle_range)
        prev_o, prev_c = float(prev["open"]), float(prev["close"])
        is_engulfing = (prev_c < prev_o and c > o and c > prev_o and o < prev_c)

        if is_hammer:
            result = {"found": True, "pattern": "hammer", "entry_price": c,
                      "stop_price": l - (h - l) * 0.1}
        elif is_engulfing:
            result = {"found": True, "pattern": "bullish_engulfing", "entry_price": c,
                      "stop_price": min(l, float(prev["low"])) - (h - l) * 0.1}

    elif side == "SELL":
        is_shooting_star = (upper_wick > 0.6 * candle_range and body < 0.3 * candle_range)
        prev_o, prev_c = float(prev["open"]), float(prev["close"])
        is_engulfing = (prev_c > prev_o and c < o and o > prev_c and c < prev_o)

        if is_shooting_star:
            result = {"found": True, "pattern": "shooting_star", "entry_price": c,
                      "stop_price": h + (h - l) * 0.1}
        elif is_engulfing:
            result = {"found": True, "pattern": "bearish_engulfing", "entry_price": c,
                      "stop_price": max(h, float(prev["high"])) + (h - l) * 0.1}

    return result


class AnticipationEngine:
    """
    Generates and manages anticipatory entries based on technical analysis.

    Instead of entering at market price when a strategy fires, this engine:
    1. Analyzes market structure (BB, RSI, S/R, EMA, VWAP)
    2. Sets pending entries at optimal levels
    3. Checks each cycle if conditions are met
    4. Executes precision entries with tight stops and high R:R
    """

    def __init__(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        self._pending: List[PendingEntry] = []
        self._entry_counter = 0
        self._triggered_count = 0
        self._expired_count = 0
        self._invalidated_count = 0
        self._load_pending()
        logger.info(
            f"[ANTICIPATE] Initialized -- {len(self._pending)} pending entries loaded"
        )

    # -- Public API ---------------------------------------------------------

    def scan_for_setups(
        self,
        symbol: str,
        df_1h: Optional[pd.DataFrame] = None,
        df_5m: Optional[pd.DataFrame] = None,
        df_6h: Optional[pd.DataFrame] = None,
        regime_predictions: Optional[Dict[str, Any]] = None,
    ) -> List[PendingEntry]:
        """
        Analyze market data and generate pending anticipatory entries.

        Called each scan cycle. Looks for setups where waiting for a better
        price gives significantly better R:R than entering now.

        regime_predictions: optional dict from RegimePredictions.to_dict() with keys:
            - adx_exhaustions: list of ADX exhaustion signals
            - btc_lead_signals: list of BTC-leads-HYPE signals
            - squeeze_signals: list of BB squeeze signals

        Returns list of newly created PendingEntry objects.
        """
        new_entries: List[PendingEntry] = []

        # Use 1h data primarily; 5m for precision timing
        ind = _compute_indicators(df_1h)
        if not ind:
            return new_entries

        ind_5m = _compute_indicators(df_5m) if df_5m is not None else {}

        # -- Higher Timeframe Trend Filter ----------------------------------
        # 6h EMA20 vs EMA50 determines allowed trade direction.
        # Insight journal validated: aligned = 33% WR, misaligned = 10%.
        trend_6h = _compute_6h_trend(df_6h)
        logger.info(f"[ANTICIPATE] {symbol} 6h trend: {trend_6h}")

        c = ind["close"]
        rsi = ind["rsi"]
        ema20 = ind["ema20"]
        bb_upper = ind["bb_upper"]
        bb_lower = ind["bb_lower"]
        bb_mid = ind["bb_mid"]
        atr = ind["atr"]
        resistance = ind["resistance"]
        support = ind["support"]
        vwap = ind["vwap"]

        # Count existing pending for this symbol
        sym_pending = sum(1 for p in self._pending if p.symbol == symbol and p.status == "pending")
        if sym_pending >= MAX_PENDING_PER_SYMBOL:
            return new_entries
        if len(self._pending) >= MAX_PENDING_TOTAL:
            return new_entries

        # -- 5m Reversal Detection (precision entry timing) -----------------
        reversal_buy = _detect_5m_reversal(df_5m, "BUY")
        reversal_sell = _detect_5m_reversal(df_5m, "SELL")

        # -- SELL SETUPS: Shorting overbought bounces --------------------

        # Setup 1: BB Upper Band Rejection (SELL)
        dist_to_bb_upper_pct = (bb_upper - c) / c if c > 0 else 999
        if 0.002 < dist_to_bb_upper_pct < 0.025 and rsi > RSI_OVERBOUGHT - 10:
            entry = self._build_sell_entry(
                symbol=symbol,
                target_price=bb_upper,
                sl_price=bb_upper * 1.010,
                tp_price=ema20,
                tp2_price=bb_lower,
                trigger_conditions={
                    "rsi_above": RSI_OVERBOUGHT_TRIGGER,
                    "price_above": bb_upper * 0.998,
                },
                confidence=80,
                setup_type="bb_upper_rejection",
                source="bb_upper",
                reasoning=(
                    f"Price approaching BB upper ${bb_upper:.2f} "
                    f"(currently ${c:.2f}, {dist_to_bb_upper_pct*100:.1f}% away). "
                    f"RSI {rsi:.0f} building overbought. "
                    f"Expect mean reversion to EMA20 ${ema20:.2f}."
                ),
                atr=atr,
                ind=ind,
            )
            if entry and not self._has_duplicate(entry):
                new_entries.append(entry)

        # Setup 2: Resistance Rejection (SELL)
        if resistance > c:
            dist_to_resistance_pct = (resistance - c) / c
            if 0.002 < dist_to_resistance_pct < 0.02 and rsi > 55:
                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=resistance,
                    sl_price=resistance * 1.012,
                    tp_price=ema20 if ema20 < resistance * 0.98 else bb_mid,
                    tp2_price=support,
                    trigger_conditions={
                        "rsi_above": 65,
                        "price_above": resistance * 0.998,
                    },
                    confidence=78,
                    setup_type="resistance_rejection",
                    source="swing_high",
                    reasoning=(
                        f"Price approaching resistance ${resistance:.2f} "
                        f"({dist_to_resistance_pct*100:.1f}% away). "
                        f"RSI {rsi:.0f}. Expect rejection to EMA20 ${ema20:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # Setup 3: EMA20 Touch from Below in Downtrend (SELL)
        ema50 = ind["ema50"]
        if c < ema20 and ema20 < ema50 and rsi < 55:
            dist_to_ema20_pct = (ema20 - c) / c
            if 0.003 < dist_to_ema20_pct < 0.02:
                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=ema20,
                    sl_price=ema20 * 1.010,
                    tp_price=support if support < c else bb_lower,
                    tp2_price=bb_lower,
                    trigger_conditions={
                        "rsi_above": 50,
                        "price_above": ema20 * 0.997,
                    },
                    confidence=76,
                    setup_type="ema20_bear_touch",
                    source="ema20_downtrend",
                    reasoning=(
                        f"Bear trend ({symbol}: EMA20 < EMA50). "
                        f"Price ${c:.2f} approaching EMA20 ${ema20:.2f} "
                        f"({dist_to_ema20_pct*100:.1f}% away). "
                        f"Mean reversion short opportunity."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- BUY SETUPS: Buying oversold dips with confirmation ----------

        # Setup 4: BB Lower Band Bounce (BUY)
        dist_to_bb_lower_pct = (c - bb_lower) / c if c > 0 else 999
        if 0.002 < dist_to_bb_lower_pct < 0.025 and rsi < RSI_OVERSOLD + 10:
            entry = self._build_buy_entry(
                symbol=symbol,
                target_price=bb_lower,
                sl_price=bb_lower * 0.990,
                tp_price=ema20,
                tp2_price=bb_upper,
                trigger_conditions={
                    "rsi_below_then_above": RSI_OVERSOLD_TRIGGER,
                    "price_below": bb_lower * 1.002,
                },
                confidence=80,
                setup_type="bb_lower_bounce",
                source="bb_lower",
                reasoning=(
                    f"Price approaching BB lower ${bb_lower:.2f} "
                    f"(currently ${c:.2f}, {dist_to_bb_lower_pct*100:.1f}% away). "
                    f"RSI {rsi:.0f} approaching oversold. "
                    f"Expect bounce to EMA20 ${ema20:.2f}."
                ),
                atr=atr,
                ind=ind,
            )
            if entry and not self._has_duplicate(entry):
                new_entries.append(entry)

        # Setup 5: Support Bounce (BUY)
        if support < c:
            dist_to_support_pct = (c - support) / c
            if 0.002 < dist_to_support_pct < 0.02 and rsi < 45:
                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=support,
                    sl_price=support * 0.988,
                    tp_price=ema20 if ema20 > support * 1.02 else bb_mid,
                    tp2_price=resistance,
                    trigger_conditions={
                        "rsi_below_then_above": 32,
                        "price_below": support * 1.002,
                    },
                    confidence=78,
                    setup_type="support_bounce",
                    source="swing_low",
                    reasoning=(
                        f"Price approaching support ${support:.2f} "
                        f"({dist_to_support_pct*100:.1f}% away). "
                        f"RSI {rsi:.0f}. Expect bounce to EMA20 ${ema20:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # Setup 6: EMA20 Touch from Above in Uptrend (BUY)
        if c > ema20 and ema20 > ema50 and rsi > 45:
            dist_below_ema20_pct = (c - ema20) / c
            if 0.001 < dist_below_ema20_pct < 0.015:
                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=ema20,
                    sl_price=ema20 * 0.990,
                    tp_price=resistance if resistance > c else bb_upper,
                    tp2_price=bb_upper,
                    trigger_conditions={
                        "rsi_below_then_above": 45,
                        "price_below": ema20 * 1.003,
                    },
                    confidence=76,
                    setup_type="ema20_bull_touch",
                    source="ema20_uptrend",
                    reasoning=(
                        f"Bull trend ({symbol}: EMA20 > EMA50). "
                        f"Price ${c:.2f} near EMA20 ${ema20:.2f} "
                        f"({dist_below_ema20_pct*100:.1f}% away). "
                        f"Trend continuation buy opportunity."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- Setup 7: VWAP Reversion --
        if vwap > 0 and c > 0:
            vwap_dist_pct = (c - vwap) / c
            if 0.008 < vwap_dist_pct < 0.03 and rsi > 55:
                vwap_target = c + atr * 0.3
                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=round(vwap_target, 4),
                    sl_price=round(vwap_target * 1.008, 4),
                    tp_price=vwap,
                    tp2_price=vwap - atr,
                    trigger_conditions={
                        "rsi_above": 60,
                        "price_above": vwap_target * 0.998,
                    },
                    confidence=77,
                    setup_type="vwap_reversion_sell",
                    source="vwap",
                    reasoning=(
                        f"Price ${c:.2f} stretched {vwap_dist_pct*100:.1f}% above "
                        f"VWAP ${vwap:.2f}. Expect mean reversion to VWAP."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

            vwap_below_pct = (vwap - c) / c if c > 0 else 0
            if 0.008 < vwap_below_pct < 0.03 and rsi < 45:
                vwap_buy_target = c - atr * 0.3
                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=round(vwap_buy_target, 4),
                    sl_price=round(vwap_buy_target * 0.992, 4),
                    tp_price=vwap,
                    tp2_price=vwap + atr,
                    trigger_conditions={
                        "rsi_below_then_above": 35,
                        "price_below": vwap_buy_target * 1.002,
                    },
                    confidence=77,
                    setup_type="vwap_reversion_buy",
                    source="vwap",
                    reasoning=(
                        f"Price ${c:.2f} stretched {vwap_below_pct*100:.1f}% below "
                        f"VWAP ${vwap:.2f}. Expect mean reversion to VWAP."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- Setup 8: Previous Session High/Low --
        swing_high = ind["swing_high"]
        swing_low = ind["swing_low"]

        if swing_high > c:
            dist_sh = (swing_high - c) / c
            if 0.003 < dist_sh < 0.015:
                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=swing_high,
                    sl_price=round(swing_high * 1.008, 4),
                    tp_price=ema20 if ema20 < swing_high * 0.98 else bb_mid,
                    tp2_price=swing_low,
                    trigger_conditions={
                        "rsi_above": 60,
                        "price_above": swing_high * 0.998,
                    },
                    confidence=76,
                    setup_type="session_high_rejection",
                    source="session_high",
                    reasoning=(
                        f"Price approaching previous session high ${swing_high:.2f} "
                        f"({dist_sh*100:.1f}% away). Expect rejection."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        if swing_low < c:
            dist_sl = (c - swing_low) / c
            if 0.003 < dist_sl < 0.015:
                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=swing_low,
                    sl_price=round(swing_low * 0.992, 4),
                    tp_price=ema20 if ema20 > swing_low * 1.02 else bb_mid,
                    tp2_price=swing_high,
                    trigger_conditions={
                        "rsi_below_then_above": 33,
                        "price_below": swing_low * 1.002,
                    },
                    confidence=76,
                    setup_type="session_low_bounce",
                    source="session_low",
                    reasoning=(
                        f"Price approaching previous session low ${swing_low:.2f} "
                        f"({dist_sl*100:.1f}% away). Expect bounce."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- Setup 9: Round Number Magnet --
        if c > 0:
            _round_levels = self._find_round_number_levels(c, symbol)
            for _rnd_level, _rnd_side in _round_levels:
                _rnd_dist = abs(c - _rnd_level) / c
                if 0.003 < _rnd_dist < 0.02:
                    if _rnd_side == "SELL" and _rnd_level > c:
                        entry = self._build_sell_entry(
                            symbol=symbol,
                            target_price=_rnd_level,
                            sl_price=round(_rnd_level * 1.008, 4),
                            tp_price=ema20 if ema20 < _rnd_level * 0.98 else bb_mid,
                            tp2_price=bb_lower,
                            trigger_conditions={
                                "rsi_above": 58,
                                "price_above": _rnd_level * 0.998,
                            },
                            confidence=75,
                            setup_type="round_number_rejection",
                            source=f"round_{_rnd_level:.0f}",
                            reasoning=(
                                f"Price approaching round number ${_rnd_level:.2f} "
                                f"from below ({_rnd_dist*100:.1f}% away). "
                                f"Psychological resistance -- expect rejection."
                            ),
                            atr=atr,
                            ind=ind,
                        )
                        if entry and not self._has_duplicate(entry):
                            new_entries.append(entry)
                    elif _rnd_side == "BUY" and _rnd_level < c:
                        entry = self._build_buy_entry(
                            symbol=symbol,
                            target_price=_rnd_level,
                            sl_price=round(_rnd_level * 0.992, 4),
                            tp_price=ema20 if ema20 > _rnd_level * 1.02 else bb_mid,
                            tp2_price=bb_upper,
                            trigger_conditions={
                                "rsi_below_then_above": 35,
                                "price_below": _rnd_level * 1.002,
                            },
                            confidence=75,
                            setup_type="round_number_bounce",
                            source=f"round_{_rnd_level:.0f}",
                            reasoning=(
                                f"Price approaching round number ${_rnd_level:.2f} "
                                f"from above ({_rnd_dist*100:.1f}% away). "
                                f"Psychological support -- expect bounce."
                            ),
                            atr=atr,
                            ind=ind,
                        )
                        if entry and not self._has_duplicate(entry):
                            new_entries.append(entry)

        # -- Setup 10: Exhaustion Reversal (candle pattern) --
        # High volume + small body + prominent wick = exhaustion.
        # Direction: OPPOSITE of the exhaustion candle.
        # SOL/BTC only (77%/71% 3h reversal rate).
        _sym_base = symbol.split("/")[0].split("-")[0].upper()
        vol_ratio = ind.get("vol_ratio", 0.0)
        candle_body = ind.get("candle_body", 0.0)
        avg_body = ind.get("avg_body", 0.0)
        prominent_wick_pct = ind.get("prominent_wick_pct", 0.0)
        candle_is_green = ind.get("candle_is_green", True)
        last_high = ind.get("last_high", 0.0)
        last_low = ind.get("last_low", 0.0)

        if (
            _sym_base in EXHAUSTION_SYMBOLS
            and vol_ratio >= EXHAUSTION_VOL_RATIO
            and avg_body > 0
            and candle_body < EXHAUSTION_BODY_RATIO * avg_body
            and prominent_wick_pct >= EXHAUSTION_WICK_MIN_PCT
        ):
            # Bearish exhaustion candle (red, big wick down) -> BUY reversal
            # Bullish exhaustion candle (green, big wick up) -> SELL reversal
            if not candle_is_green:
                # Bearish exhaustion -> BUY
                # SL: ATR-based (1.0x ATR below entry) for tight risk
                exhaust_entry = c
                exhaust_sl = c - atr * 1.0
                exhaust_tp = ema20  # Mean reversion to EMA20
                exhaust_tp2 = bb_mid if bb_mid > ema20 else ema20 + atr
                if exhaust_tp > exhaust_entry:
                    entry = self._build_buy_entry(
                        symbol=symbol,
                        target_price=exhaust_entry,
                        sl_price=exhaust_sl,
                        tp_price=exhaust_tp,
                        tp2_price=exhaust_tp2,
                        trigger_conditions={
                            "price_below": exhaust_entry * 1.002,
                        },
                        confidence=EXHAUSTION_CONFIDENCE,
                        setup_type="exhaustion_reversal",
                        source="candle_exhaustion",
                        reasoning=(
                            f"EXHAUSTION REVERSAL: {symbol} bearish candle with "
                            f"vol {vol_ratio:.1f}x avg, body {candle_body:.2f} "
                            f"< {EXHAUSTION_BODY_RATIO}x avg ({avg_body:.2f}), "
                            f"wick {prominent_wick_pct*100:.2f}%. "
                            f"Expect reversal to EMA20 ${ema20:.2f}."
                        ),
                        atr=atr,
                        ind=ind,
                        min_rr=MIN_RR_RATIO_CANDLE,
                    )
                    if entry and not self._has_duplicate(entry):
                        new_entries.append(entry)
            else:
                # Bullish exhaustion -> SELL
                # SL: ATR-based (1.0x ATR above entry) for tight risk
                exhaust_entry = c
                exhaust_sl = c + atr * 1.0
                exhaust_tp = ema20  # Mean reversion to EMA20
                exhaust_tp2 = bb_mid if bb_mid < ema20 else ema20 - atr
                if exhaust_tp < exhaust_entry:
                    entry = self._build_sell_entry(
                        symbol=symbol,
                        target_price=exhaust_entry,
                        sl_price=exhaust_sl,
                        tp_price=exhaust_tp,
                        tp2_price=exhaust_tp2,
                        trigger_conditions={
                            "price_above": exhaust_entry * 0.998,
                        },
                        confidence=EXHAUSTION_CONFIDENCE,
                        setup_type="exhaustion_reversal",
                        source="candle_exhaustion",
                        reasoning=(
                            f"EXHAUSTION REVERSAL: {symbol} bullish candle with "
                            f"vol {vol_ratio:.1f}x avg, body {candle_body:.2f} "
                            f"< {EXHAUSTION_BODY_RATIO}x avg ({avg_body:.2f}), "
                            f"wick {prominent_wick_pct*100:.2f}%. "
                            f"Expect reversal to EMA20 ${ema20:.2f}."
                        ),
                        atr=atr,
                        ind=ind,
                        min_rr=MIN_RR_RATIO_CANDLE,
                    )
                    if entry and not self._has_duplicate(entry):
                        new_entries.append(entry)

        # -- Setup 11: Institutional Continuation (candle pattern) --
        # Giant green candle with huge volume = institutional buying.
        # Direction: SAME as candle (BUY continuation).
        # SOL/HYPE only (70%/61% continuation rate).
        if (
            _sym_base in INSTITUTIONAL_SYMBOLS
            and vol_ratio >= INSTITUTIONAL_VOL_RATIO
            and avg_body > 0
            and candle_body > INSTITUTIONAL_BODY_RATIO * avg_body
            and candle_is_green
        ):
            inst_entry = c
            # Use ATR-based SL if candle low is too far; take tighter of the two
            inst_sl_candle = last_low
            inst_sl_atr = inst_entry - atr * 1.5
            inst_sl = max(inst_sl_candle, inst_sl_atr)
            inst_tp = inst_entry + 1.5 * candle_body  # 1.5x the candle body
            inst_tp2 = inst_entry + 2.0 * candle_body  # Extended target

            if inst_tp > inst_entry and inst_sl < inst_entry:
                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=inst_entry,
                    sl_price=inst_sl,
                    tp_price=inst_tp,
                    tp2_price=inst_tp2,
                    trigger_conditions={
                        "price_below": inst_entry * 1.002,
                    },
                    confidence=INSTITUTIONAL_CONFIDENCE,
                    setup_type="institutional_continuation",
                    source="candle_institutional",
                    reasoning=(
                        f"INSTITUTIONAL CONTINUATION: {symbol} green candle with "
                        f"vol {vol_ratio:.1f}x avg, body {candle_body:.2f} "
                        f"> {INSTITUTIONAL_BODY_RATIO}x avg ({avg_body:.2f}). "
                        f"Institutional buying detected. "
                        f"TP at entry + 1.5x body = ${inst_tp:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                    min_rr=MIN_RR_RATIO_CANDLE,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- Setup 12: Shooting Star Short (candle pattern) --
        # Upper wick > 60% of range, body < 30% of range = selling pressure.
        # Direction: SELL.
        # HYPE only (68% next-hour downside accuracy).
        upper_wick_pct_val = ind.get("upper_wick_pct", 0.0)
        body_pct_of_range = ind.get("body_pct_of_range", 1.0)

        if (
            _sym_base in SHOOTING_STAR_SYMBOLS
            and upper_wick_pct_val > SHOOTING_STAR_WICK_RATIO
            and body_pct_of_range < SHOOTING_STAR_BODY_RATIO
        ):
            star_entry = c
            # ATR-based SL (tighter than candle high for better R:R)
            star_sl_candle = last_high * (1 + SHOOTING_STAR_SL_BUFFER_PCT)
            star_sl_atr = star_entry + atr * 1.0
            star_sl = min(star_sl_candle, star_sl_atr)  # Tighter of the two
            # TP: candle low or EMA20, whichever is closer to entry
            star_tp_low = last_low
            star_tp_ema = ema20
            # TP: EMA20 (mean reversion target) or candle low, whichever gives better R:R.
            # Use the target that's further away for viable R:R on high-WR pattern.
            tp_candidates = [t for t in [star_tp_low, star_tp_ema] if t < star_entry]
            if tp_candidates:
                star_tp = min(tp_candidates)  # Further target = better R:R
                star_tp2 = min(tp_candidates) - atr if len(tp_candidates) == 1 else max(tp_candidates)

                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=star_entry,
                    sl_price=star_sl,
                    tp_price=star_tp,
                    tp2_price=star_tp2,
                    trigger_conditions={
                        "price_above": star_entry * 0.998,
                    },
                    confidence=SHOOTING_STAR_CONFIDENCE,
                    setup_type="shooting_star_short",
                    source="candle_shooting_star",
                    reasoning=(
                        f"SHOOTING STAR SHORT: {symbol} upper wick "
                        f"{upper_wick_pct_val*100:.0f}% of range, "
                        f"body {body_pct_of_range*100:.0f}% of range. "
                        f"Strong rejection at ${last_high:.2f}. "
                        f"SL ${star_sl:.2f}, TP ${star_tp:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                    min_rr=MIN_RR_RATIO_CANDLE,
                )
                if entry and not self._has_duplicate(entry):
                    new_entries.append(entry)

        # -- Regime Prediction Setups ------------------------------------------
        # Generate entries based on BTC lead signals and ADX exhaustion warnings.
        if regime_predictions:
            new_entries.extend(self._generate_prediction_entries(
                symbol=symbol,
                regime_predictions=regime_predictions,
                ind=ind,
                atr=atr,
            ))

        # -- Multi-Timeframe Filter & Alignment Tagging ---------------------
        filtered_entries = []
        for entry in new_entries:
            alignment = _get_timeframe_alignment(entry.side, trend_6h)
            entry.timeframe_alignment = alignment

            # Block counter-trend setups entirely (10% WR = net losers).
            if alignment == "counter":
                logger.info(
                    f"[ANTICIPATE] BLOCKED {entry.symbol} {entry.side} "
                    f"{entry.setup_type} -- COUNTER to 6h {trend_6h} trend"
                )
                continue

            # Adjust leverage based on alignment
            if alignment == "aligned":
                lev_low, lev_high = LEVERAGE_ALIGNED
            elif alignment == "neutral":
                lev_low, lev_high = LEVERAGE_NEUTRAL
                entry.confidence = max(60, entry.confidence - 5)
            else:
                lev_low, lev_high = DEFAULT_LEVERAGE_LOW, DEFAULT_LEVERAGE_HIGH

            base_lev = min(0.08 / max(entry.stop_width_pct, 0.001), 20.0)
            conf_bonus = max(0, (entry.confidence - 75) / 5)
            raw_lev = base_lev + conf_bonus
            entry.leverage = round(max(lev_low, min(lev_high, raw_lev)), 1)

            # 5m precision: tighten stop if reversal candle detected
            reversal = reversal_buy if entry.side == "BUY" else reversal_sell
            if reversal.get("found") and reversal.get("stop_price", 0) > 0:
                five_m_stop = reversal["stop_price"]
                if entry.side == "BUY" and 0 < five_m_stop < entry.target_price:
                    old_sw = entry.stop_width_pct
                    new_sw = (entry.target_price - five_m_stop) / entry.target_price
                    if MIN_STOP_PCT <= new_sw <= MAX_STOP_PCT:
                        entry.sl = round(five_m_stop, 4)
                        entry.stop_width_pct = round(new_sw, 4)
                        entry.reasoning += (
                            f" | 5m {reversal['pattern']} -- "
                            f"stop tightened {old_sw*100:.2f}% to {new_sw*100:.2f}%"
                        )
                elif entry.side == "SELL" and five_m_stop > entry.target_price:
                    old_sw = entry.stop_width_pct
                    new_sw = (five_m_stop - entry.target_price) / entry.target_price
                    if MIN_STOP_PCT <= new_sw <= MAX_STOP_PCT:
                        entry.sl = round(five_m_stop, 4)
                        entry.stop_width_pct = round(new_sw, 4)
                        entry.reasoning += (
                            f" | 5m {reversal['pattern']} -- "
                            f"stop tightened {old_sw*100:.2f}% to {new_sw*100:.2f}%"
                        )

            filtered_entries.append(entry)

        for entry in filtered_entries:
            self._pending.append(entry)
            logger.info(
                f"[ANTICIPATE] NEW {entry.entry_id} | {entry.symbol} {entry.side} "
                f"@ ${entry.target_price:.2f} | {entry.setup_type} | "
                f"align={entry.timeframe_alignment} 6h={trend_6h} | "
                f"SL=${entry.sl:.2f} TP=${entry.tp:.2f} | "
                f"R:R={entry.rr_ratio:.1f} lev={entry.leverage:.0f}x | "
                f"expires in {(entry.expiry - time.time()) / 3600:.1f}h"
            )

        if filtered_entries:
            self._save_pending()

        return filtered_entries

    def check_pending_entries(
        self,
        prices: Dict[str, float],
        indicators: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[PendingEntry]:
        """
        Check all pending entries against current prices and indicators.

        Called every scan cycle. Returns list of entries that triggered
        (ready to be converted to Signals and executed).

        Args:
            prices: {symbol: current_price}
            indicators: {symbol: {rsi, ema20, bb_upper, vol_ratio, ...}}
                        If None, only price conditions are checked.
        """
        triggered: List[PendingEntry] = []
        remaining: List[PendingEntry] = []
        now = time.time()

        for entry in self._pending:
            if entry.status != "pending":
                continue

            entry.checks += 1
            price = prices.get(entry.symbol)
            if price is None:
                remaining.append(entry)
                continue

            ind = indicators.get(entry.symbol, {}) if indicators else {}

            # 1. Check expiry
            if now >= entry.expiry:
                entry.status = "expired"
                self._expired_count += 1
                self._log_outcome(entry, "expired", price)
                logger.info(
                    f"[ANTICIPATE] EXPIRED {entry.entry_id} | {entry.symbol} {entry.side} "
                    f"@ ${entry.target_price:.2f} (current ${price:.2f}) | "
                    f"checked {entry.checks}x"
                )
                continue

            # 2. Check invalidation (price moved too far from target)
            if entry.side == "SELL":
                dist = (entry.target_price - price) / price if price > 0 else 0
            else:
                dist = (price - entry.target_price) / price if price > 0 else 0

            if dist > PRICE_INVALIDATION_PCT:
                entry.status = "invalidated"
                self._invalidated_count += 1
                self._log_outcome(entry, "invalidated", price)
                logger.info(
                    f"[ANTICIPATE] INVALIDATED {entry.entry_id} | {entry.symbol} {entry.side} "
                    f"@ ${entry.target_price:.2f} -- price ${price:.2f} moved "
                    f"{dist*100:.1f}% away"
                )
                continue

            # 3. Track best approach
            if entry.side == "SELL":
                if price > entry.best_approach_price:
                    entry.best_approach_price = price
            else:
                if entry.best_approach_price == 0 or price < entry.best_approach_price:
                    entry.best_approach_price = price

            # 4. Check trigger conditions (including volume confirmation)
            result = self._check_triggers(entry, price, ind)
            if result.triggered:
                entry.status = "triggered"
                self._triggered_count += 1
                self._log_outcome(entry, "triggered", price)
                triggered.append(entry)
                logger.info(
                    f"[ANTICIPATE] TRIGGERED {entry.entry_id} | {entry.symbol} {entry.side} "
                    f"@ ${price:.2f} (target ${entry.target_price:.2f}) | "
                    f"{entry.setup_type} | R:R={entry.rr_ratio:.1f} | "
                    f"{result.reason}"
                )
            else:
                remaining.append(entry)

        self._pending = remaining + [e for e in self._pending if e.status != "pending"]
        # Keep only active + recently completed (last 50)
        active = [e for e in self._pending if e.status == "pending"]
        completed = [e for e in self._pending if e.status != "pending"]
        self._pending = active + completed[-50:]

        if triggered:
            self._save_pending()

        return triggered

    def get_status(
        self, indicators: Optional[Dict[str, Dict[str, float]]] = None
    ) -> Dict[str, Any]:
        """Return engine status for monitoring.

        Args:
            indicators: Optional {symbol: {vol_ratio, vol_is_buying, ...}}
                        for volume status display on pending entries.
        """
        active = [e for e in self._pending if e.status == "pending"]
        entries_with_vol = []
        for e in active:
            d = e.to_dict()
            # Annotate with volume status if indicators available
            if indicators and e.symbol in indicators:
                ind = indicators[e.symbol]
                vol_ratio = ind.get("vol_ratio", 0.0)
                if vol_ratio > 0:
                    if vol_ratio >= 1.2:
                        d["vol_status"] = f"Vol: {vol_ratio:.1f}x avg (CONFIRMED)"
                    elif vol_ratio >= 0.8:
                        d["vol_status"] = f"Vol: {vol_ratio:.1f}x avg (OK)"
                    else:
                        d["vol_status"] = f"Vol: {vol_ratio:.1f}x avg (LOW - wait)"
                else:
                    d["vol_status"] = "Vol: no data"
            entries_with_vol.append(d)

        return {
            "active_pending": len(active),
            "total_triggered": self._triggered_count,
            "total_expired": self._expired_count,
            "total_invalidated": self._invalidated_count,
            "pending_entries": entries_with_vol,
            "trigger_rate": (
                round(self._triggered_count /
                      max(1, self._triggered_count + self._expired_count + self._invalidated_count) * 100, 1)
            ),
        }

    def remove_entry(self, entry_id: str) -> bool:
        """Manually remove a pending entry."""
        for i, e in enumerate(self._pending):
            if e.entry_id == entry_id and e.status == "pending":
                e.status = "invalidated"
                self._invalidated_count += 1
                self._save_pending()
                return True
        return False

    # -- Entry Builders -----------------------------------------------------

    def _build_sell_entry(
        self,
        symbol: str,
        target_price: float,
        sl_price: float,
        tp_price: float,
        tp2_price: float,
        trigger_conditions: Dict[str, Any],
        confidence: float,
        setup_type: str,
        source: str,
        reasoning: str,
        atr: float,
        ind: Dict[str, float],
        min_rr: Optional[float] = None,
    ) -> Optional[PendingEntry]:
        """Build a SELL pending entry with validation.

        Uses tight stops for SHORTs (ATR x 1.2 philosophy) and
        swing-structure SL when tighter than the proposed level.
        """
        if target_price <= 0 or sl_price <= target_price or tp_price >= target_price:
            return None

        # Swing-structure SL: use 5-candle swing high + buffer if tighter
        swing_high_5 = ind.get("swing_high_5", 0)
        if swing_high_5 > target_price:
            swing_sl = swing_high_5 * (1 + SWING_SL_BUFFER_PCT)
            if swing_sl < sl_price and swing_sl > target_price:
                reasoning += (
                    f" | Swing-structure SL: 5-bar high ${swing_high_5:.2f} "
                    f"+ 0.2% buffer = ${swing_sl:.2f}"
                )
                sl_price = swing_sl

        # Calculate stop width — SELL uses tight max (SHORTs work better tight)
        stop_width_pct = (sl_price - target_price) / target_price
        if stop_width_pct < MIN_STOP_PCT:
            sl_price = target_price * (1 + MIN_STOP_PCT)
            stop_width_pct = MIN_STOP_PCT
        if stop_width_pct > MAX_STOP_PCT_SELL:
            sl_price = target_price * (1 + MAX_STOP_PCT_SELL)
            stop_width_pct = MAX_STOP_PCT_SELL

        # Calculate R:R
        reward_pct = (target_price - tp_price) / target_price
        rr_ratio = reward_pct / stop_width_pct if stop_width_pct > 0 else 0
        rr_threshold = min_rr if min_rr is not None else MIN_RR_RATIO
        if rr_ratio < rr_threshold:
            return None

        # Calculate leverage: tighter stop = higher leverage, capped
        leverage = self._calc_leverage(stop_width_pct, confidence)

        # Risk per trade
        risk_pct = self._calc_risk_pct(confidence, rr_ratio)

        now = time.time()
        self._entry_counter += 1

        return PendingEntry(
            entry_id=f"ANT-{self._entry_counter:04d}",
            symbol=symbol,
            side="SELL",
            target_price=round(target_price, 4),
            sl=round(sl_price, 4),
            tp=round(tp_price, 4),
            tp2=round(tp2_price, 4),
            trigger_conditions=trigger_conditions,
            confidence=confidence,
            leverage=leverage,
            risk_pct=risk_pct,
            expiry=now + DEFAULT_EXPIRY_HOURS * 3600,
            reasoning=reasoning,
            setup_type=setup_type,
            source=source,
            created_at=now,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            rr_ratio=round(rr_ratio, 2),
            stop_width_pct=round(stop_width_pct, 4),
        )

    def _build_buy_entry(
        self,
        symbol: str,
        target_price: float,
        sl_price: float,
        tp_price: float,
        tp2_price: float,
        trigger_conditions: Dict[str, Any],
        confidence: float,
        setup_type: str,
        source: str,
        reasoning: str,
        atr: float,
        ind: Dict[str, float],
        min_rr: Optional[float] = None,
    ) -> Optional[PendingEntry]:
        """Build a BUY pending entry with validation.

        Uses wide stops for LONGs (ATR x 2.0 philosophy) and
        swing-structure SL when tighter than the proposed level.
        """
        if target_price <= 0 or sl_price >= target_price or tp_price <= target_price:
            return None

        # Swing-structure SL: use 5-candle swing low - buffer if tighter
        swing_low_5 = ind.get("swing_low_5", 0)
        if swing_low_5 > 0 and swing_low_5 < target_price:
            swing_sl = swing_low_5 * (1 - SWING_SL_BUFFER_PCT)
            if swing_sl > sl_price and swing_sl < target_price:
                reasoning += (
                    f" | Swing-structure SL: 5-bar low ${swing_low_5:.2f} "
                    f"- 0.2% buffer = ${swing_sl:.2f}"
                )
                sl_price = swing_sl

        # Calculate stop width — BUY uses wide max (LONGs need room to breathe)
        stop_width_pct = (target_price - sl_price) / target_price
        if stop_width_pct < MIN_STOP_PCT:
            sl_price = target_price * (1 - MIN_STOP_PCT)
            stop_width_pct = MIN_STOP_PCT
        if stop_width_pct > MAX_STOP_PCT_BUY:
            sl_price = target_price * (1 - MAX_STOP_PCT_BUY)
            stop_width_pct = MAX_STOP_PCT_BUY

        # Calculate R:R
        reward_pct = (tp_price - target_price) / target_price
        rr_ratio = reward_pct / stop_width_pct if stop_width_pct > 0 else 0
        rr_threshold = min_rr if min_rr is not None else MIN_RR_RATIO
        if rr_ratio < rr_threshold:
            return None

        leverage = self._calc_leverage(stop_width_pct, confidence)
        risk_pct = self._calc_risk_pct(confidence, rr_ratio)

        now = time.time()
        self._entry_counter += 1

        return PendingEntry(
            entry_id=f"ANT-{self._entry_counter:04d}",
            symbol=symbol,
            side="BUY",
            target_price=round(target_price, 4),
            sl=round(sl_price, 4),
            tp=round(tp_price, 4),
            tp2=round(tp2_price, 4),
            trigger_conditions=trigger_conditions,
            confidence=confidence,
            leverage=leverage,
            risk_pct=risk_pct,
            expiry=now + DEFAULT_EXPIRY_HOURS * 3600,
            reasoning=reasoning,
            setup_type=setup_type,
            source=source,
            created_at=now,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            rr_ratio=round(rr_ratio, 2),
            stop_width_pct=round(stop_width_pct, 4),
        )

    # -- Trigger Checking ---------------------------------------------------

    def _check_triggers(
        self, entry: PendingEntry, price: float, ind: Dict[str, float]
    ) -> TriggerResult:
        """Check if all trigger conditions for a pending entry are met.

        Includes volume confirmation:
        - Dead market filter (vol < 0.8x avg blocks all entries)
        - Reversal setups require vol >= 1.2x avg
        - Trend setups require vol >= 0.9x avg
        - Candle pressure must match trade direction
        - Volume spike (>2x avg) boosts confidence +15%
        """
        conditions = entry.trigger_conditions
        met: Dict[str, bool] = {}
        reasons: List[str] = []

        # Price condition: is price at/past the target?
        if entry.side == "SELL":
            price_ok = price >= entry.target_price * 0.998  # Within 0.2%
            met["price_at_target"] = price_ok
            if price_ok:
                reasons.append(f"price ${price:.2f} >= target ${entry.target_price:.2f}")
        else:
            price_ok = price <= entry.target_price * 1.002
            met["price_at_target"] = price_ok
            if price_ok:
                reasons.append(f"price ${price:.2f} <= target ${entry.target_price:.2f}")

        # RSI conditions
        rsi = ind.get("rsi")
        rsi_prev = ind.get("rsi_prev")

        if "rsi_above" in conditions:
            if rsi is None:
                met["rsi_above"] = False  # Can't evaluate without data
            else:
                threshold = conditions["rsi_above"]
                ok = rsi >= threshold
                met["rsi_above"] = ok
                if ok:
                    reasons.append(f"RSI {rsi:.0f} >= {threshold}")

        if "rsi_below_then_above" in conditions:
            if rsi is None:
                met["rsi_confirmation"] = False  # Can't evaluate without data
            else:
                threshold = conditions["rsi_below_then_above"]
                # RSI was below threshold and has now crossed above it
                if rsi_prev is not None:
                    ok = rsi >= threshold and rsi_prev < threshold
                    # Also accept: RSI was recently below and now above (within 5 pts)
                    if not ok and rsi >= threshold and rsi < threshold + 5:
                        # Accept if price is at target (close enough to confirmation)
                        ok = price_ok
                else:
                    ok = rsi >= threshold
                met["rsi_confirmation"] = ok
                if ok:
                    reasons.append(f"RSI {rsi:.0f} crossed above {threshold}")

        if "price_above" in conditions:
            threshold = conditions["price_above"]
            ok = price >= threshold
            met["price_above_level"] = ok
            if ok:
                reasons.append(f"price ${price:.2f} >= ${threshold:.2f}")

        if "price_below" in conditions:
            threshold = conditions["price_below"]
            ok = price <= threshold
            met["price_below_level"] = ok
            if ok:
                reasons.append(f"price ${price:.2f} <= ${threshold:.2f}")

        # -- Volume Confirmation --------------------------------------------
        vol_ratio = ind.get("vol_ratio", 0.0)
        vol_is_buying = ind.get("vol_is_buying", None)

        if vol_ratio > 0:
            # 1. Minimum volume gate (dead market filter)
            if entry.setup_type in REVERSAL_SETUPS:
                vol_min = VOL_REVERSAL_MIN_RATIO
            elif entry.setup_type in TREND_SETUPS:
                vol_min = VOL_TREND_MIN_RATIO
            else:
                vol_min = VOL_MIN_RATIO

            vol_ok = vol_ratio >= vol_min
            met["volume_confirmed"] = vol_ok
            if vol_ok:
                reasons.append(f"vol {vol_ratio:.1f}x avg (>={vol_min}x)")
            else:
                reasons.append(f"vol LOW {vol_ratio:.1f}x avg (<{vol_min}x)")

            # 2. Candle pressure must match trade direction
            if vol_is_buying is not None:
                if entry.side == "BUY":
                    pressure_ok = vol_is_buying  # Need buying pressure for BUY
                else:
                    pressure_ok = not vol_is_buying  # Need selling pressure for SELL
                met["candle_pressure"] = pressure_ok
                if pressure_ok:
                    pressure_type = "buying" if vol_is_buying else "selling"
                    reasons.append(f"{pressure_type} pressure candle")
                else:
                    pressure_type = "buying" if vol_is_buying else "selling"
                    reasons.append(f"wrong pressure ({pressure_type} for {entry.side})")

        # All conditions must be met
        all_met = all(met.values()) if met else False

        # -- Volume Spike: boost confidence if vol > 2x average -------------
        # (applied post-trigger, doesn't block entry)
        vol_spike = vol_ratio >= VOL_SPIKE_RATIO if vol_ratio > 0 else False
        if all_met and vol_spike:
            entry.confidence = min(100, entry.confidence + VOL_SPIKE_CONFIDENCE_BOOST)
            reasons.append(f"VOL SPIKE {vol_ratio:.1f}x -> conf+{VOL_SPIKE_CONFIDENCE_BOOST}")

        return TriggerResult(
            triggered=all_met,
            conditions_met=met,
            reason=" | ".join(reasons) if reasons else "conditions not met",
        )

    # -- Regime Prediction Entries ------------------------------------------

    def _generate_prediction_entries(
        self,
        symbol: str,
        regime_predictions: Dict[str, Any],
        ind: Dict[str, float],
        atr: float,
    ) -> List[PendingEntry]:
        """Generate anticipatory entries from regime prediction signals.

        1. BTC Lead -> HYPE: When BTC regime shifts, pre-position HYPE in same direction.
        2. ADX Exhaustion: When trend is dying, prepare reversal entries at key levels.
        """
        entries: List[PendingEntry] = []
        c = ind.get("close", 0)
        if c <= 0:
            return entries

        ema20 = ind.get("ema20", c)
        bb_upper = ind.get("bb_upper", c * 1.02)
        bb_lower = ind.get("bb_lower", c * 0.98)
        resistance = ind.get("resistance", bb_upper)
        support = ind.get("support", bb_lower)

        # -- BTC Lead -> HYPE entries --
        # When BTC turns bearish, set HYPE SELL entries at resistance.
        # When BTC turns bullish, set HYPE BUY entries at support.
        btc_leads = regime_predictions.get("btc_lead_signals", [])
        for sig in btc_leads:
            if symbol != "HYPE":
                continue  # BTC lead only predicts HYPE

            direction = sig.get("predicted_hype_direction", "")
            hours_left = sig.get("hours_remaining", 0)
            if hours_left <= 0:
                continue

            # Confidence decays as countdown progresses (fresher = higher edge)
            base_conf = 80
            time_decay = max(0, (4.0 - hours_left) / 4.0) * 5  # lose up to 5 pts
            conf = base_conf - time_decay

            if direction == "bearish":
                # Set SELL entry at resistance / BB upper
                target = max(resistance, bb_upper) if resistance > c else bb_upper
                if target <= c:
                    target = c * 1.005  # Slight premium if no clear resistance above

                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=target,
                    sl_price=target * 1.012,
                    tp_price=ema20 if ema20 < target * 0.98 else target * 0.97,
                    tp2_price=bb_lower,
                    trigger_conditions={
                        "rsi_above": 55,
                        "price_above": target * 0.998,
                    },
                    confidence=conf,
                    setup_type="btc_lead_bearish",
                    source="btc_lead_signal",
                    reasoning=(
                        f"BTC regime shift predicts HYPE bearish within {hours_left:.1f}h "
                        f"(83% accuracy). Target SELL at ${target:.2f}. "
                        f"BTC: {sig.get('btc_from_regime', '?')} -> {sig.get('btc_to_regime', '?')}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    entries.append(entry)
                    logger.info(
                        f"[ANTICIPATE] BTC_LEAD: {symbol} SELL @ ${target:.2f} "
                        f"({hours_left:.1f}h window)"
                    )

            elif direction == "bullish":
                # Set BUY entry at support / BB lower
                target = min(support, bb_lower) if support < c else bb_lower
                if target >= c:
                    target = c * 0.995

                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=target,
                    sl_price=target * 0.988,
                    tp_price=ema20 if ema20 > target * 1.02 else target * 1.03,
                    tp2_price=bb_upper,
                    trigger_conditions={
                        "rsi_below_then_above": 40,
                        "price_below": target * 1.002,
                    },
                    confidence=conf,
                    setup_type="btc_lead_bullish",
                    source="btc_lead_signal",
                    reasoning=(
                        f"BTC regime shift predicts HYPE bullish within {hours_left:.1f}h "
                        f"(83% accuracy). Target BUY at ${target:.2f}. "
                        f"BTC: {sig.get('btc_from_regime', '?')} -> {sig.get('btc_to_regime', '?')}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    entries.append(entry)
                    logger.info(
                        f"[ANTICIPATE] BTC_LEAD: {symbol} BUY @ ${target:.2f} "
                        f"({hours_left:.1f}h window)"
                    )

        # -- ADX Exhaustion -> reversal entries --
        # When ADX is falling from a peak, the current trend is dying.
        # Prepare entries in the OPPOSITE direction at key levels.
        adx_exhaustions = regime_predictions.get("adx_exhaustions", [])
        for exh in adx_exhaustions:
            if exh.get("symbol") != symbol:
                continue

            current_regime = exh.get("current_regime", "")
            window = exh.get("reversal_window_hours", [0, 0])
            min_h, max_h = (window[0], window[1]) if len(window) >= 2 else (0, 0)

            if max_h <= 0:
                continue  # Window already expired

            adx_peak = exh.get("adx_peak", 0)
            adx_now = exh.get("adx_current", 0)

            # Determine reversal direction based on current regime
            if current_regime in ("trend_bull",):
                # Bull trend exhausting -> prepare SELL
                target = resistance if resistance > c else bb_upper
                if target <= c:
                    target = c * 1.003

                entry = self._build_sell_entry(
                    symbol=symbol,
                    target_price=target,
                    sl_price=target * 1.012,
                    tp_price=ema20 if ema20 < target * 0.98 else target * 0.97,
                    tp2_price=bb_lower,
                    trigger_conditions={
                        "rsi_above": 55,
                        "price_above": target * 0.998,
                    },
                    confidence=75,
                    setup_type="adx_exhaustion_sell",
                    source="adx_trajectory",
                    reasoning=(
                        f"TREND_EXHAUSTION: {symbol} ADX peaked {adx_peak:.0f} "
                        f"-> now {adx_now:.0f}. Bull trend dying. "
                        f"Reversal in {min_h:.1f}-{max_h:.1f}h. "
                        f"SELL at resistance ${target:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    entries.append(entry)
                    logger.info(
                        f"[ANTICIPATE] ADX_EXHAUSTION: {symbol} SELL @ ${target:.2f} "
                        f"(reversal in {min_h:.0f}-{max_h:.0f}h)"
                    )

            elif current_regime in ("trend_bear",):
                # Bear trend exhausting -> prepare BUY
                target = support if support < c else bb_lower
                if target >= c:
                    target = c * 0.997

                entry = self._build_buy_entry(
                    symbol=symbol,
                    target_price=target,
                    sl_price=target * 0.988,
                    tp_price=ema20 if ema20 > target * 1.02 else target * 1.03,
                    tp2_price=bb_upper,
                    trigger_conditions={
                        "rsi_below_then_above": 35,
                        "price_below": target * 1.002,
                    },
                    confidence=75,
                    setup_type="adx_exhaustion_buy",
                    source="adx_trajectory",
                    reasoning=(
                        f"TREND_EXHAUSTION: {symbol} ADX peaked {adx_peak:.0f} "
                        f"-> now {adx_now:.0f}. Bear trend dying. "
                        f"Reversal in {min_h:.1f}-{max_h:.1f}h. "
                        f"BUY at support ${target:.2f}."
                    ),
                    atr=atr,
                    ind=ind,
                )
                if entry and not self._has_duplicate(entry):
                    entries.append(entry)
                    logger.info(
                        f"[ANTICIPATE] ADX_EXHAUSTION: {symbol} BUY @ ${target:.2f} "
                        f"(reversal in {min_h:.0f}-{max_h:.0f}h)"
                    )

        return entries

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _calc_leverage(stop_width_pct: float, confidence: float) -> float:
        """Calculate leverage based on stop width and confidence.

        Tighter stop = higher leverage (same dollar risk, bigger position).
        Capped between DEFAULT_LEVERAGE_LOW and DEFAULT_LEVERAGE_HIGH.
        """
        if stop_width_pct <= 0:
            return DEFAULT_LEVERAGE_LOW

        # Base: inverse of stop width, scaled
        # 0.5% stop -> ~12x, 1.0% stop -> ~8x, 1.5% stop -> ~6x
        base_lev = min(0.08 / stop_width_pct, 20.0)

        # Confidence bonus: +1x per 5% above 75
        conf_bonus = max(0, (confidence - 75) / 5)

        leverage = base_lev + conf_bonus
        return round(
            max(DEFAULT_LEVERAGE_LOW, min(DEFAULT_LEVERAGE_HIGH, leverage)),
            1,
        )

    @staticmethod
    def _calc_risk_pct(confidence: float, rr_ratio: float) -> float:
        """Calculate risk % based on confidence and R:R.

        Higher confidence + higher R:R = larger position.
        Range: 0.02 (2%) to 0.08 (8%).
        """
        base = 0.03  # 3% base
        conf_bonus = max(0, (confidence - 75) / 100)  # +0.5% per 10% above 75
        rr_bonus = max(0, (rr_ratio - 2.0) * 0.01)    # +1% per R:R above 2.0
        risk = base + conf_bonus + rr_bonus
        return round(max(0.02, min(0.08, risk)), 3)

    def _has_duplicate(self, new_entry: PendingEntry) -> bool:
        """Check if a similar pending entry already exists."""
        for existing in self._pending:
            if existing.status != "pending":
                continue
            if (
                existing.symbol == new_entry.symbol
                and existing.side == new_entry.side
                and existing.setup_type == new_entry.setup_type
            ):
                # Same symbol+side+setup = duplicate
                return True
            if (
                existing.symbol == new_entry.symbol
                and existing.side == new_entry.side
                and abs(existing.target_price - new_entry.target_price) / new_entry.target_price < 0.005
            ):
                # Same symbol+side and target within 0.5% = duplicate
                return True
        return False

    @staticmethod
    def _find_round_number_levels(
        current_price: float, symbol: str
    ) -> List[Tuple[float, str]]:
        """Find nearby round-number levels that act as psychological S/R.

        Returns list of (level, side) tuples where side is "BUY" (support)
        or "SELL" (resistance).
        """
        levels: List[Tuple[float, str]] = []
        if current_price <= 0:
            return levels

        # Determine step size based on price magnitude
        if current_price > 1000:
            steps = [50, 100, 250]
        elif current_price > 100:
            steps = [5, 10, 25]
        elif current_price > 10:
            steps = [1, 2.5, 5]
        elif current_price > 1:
            steps = [0.25, 0.5, 1.0]
        else:
            steps = [0.05, 0.1, 0.25]

        for step in steps:
            # Nearest round above (resistance / sell)
            above = math.ceil(current_price / step) * step
            if above > current_price:
                levels.append((above, "SELL"))
            # Nearest round below (support / buy)
            below = math.floor(current_price / step) * step
            if below < current_price and below > 0:
                levels.append((below, "BUY"))

        # Deduplicate by level (keep first occurrence)
        seen = set()
        unique: List[Tuple[float, str]] = []
        for lvl, side in levels:
            key = (round(lvl, 4), side)
            if key not in seen:
                seen.add(key)
                unique.append((lvl, side))

        return unique

    # -- Signal Conversion --------------------------------------------------

    @staticmethod
    def pending_to_signal(
        entry: PendingEntry,
        current_price: float,
        vol_ratio: float = 0.0,
    ):
        """
        Convert a triggered PendingEntry into a strategies.base.Signal
        that can be fed to the sniper filter / simulator.

        Args:
            entry: The triggered PendingEntry
            current_price: Price at trigger time
            vol_ratio: Volume ratio (current / 20-period avg) at trigger time

        Returns a Signal object compatible with the existing pipeline.
        """
        from strategies.base import Signal

        # Use current price as entry (we triggered at this price)
        actual_entry = current_price

        # Recalculate SL/TP relative to actual entry if needed
        if entry.side == "SELL":
            sl = actual_entry * (1 + entry.stop_width_pct)
            tp_dist = entry.rr_ratio * entry.stop_width_pct
            tp1 = actual_entry * (1 - tp_dist)
            tp2 = entry.tp2 if entry.tp2 < actual_entry else actual_entry * (1 - tp_dist * 1.5)
        else:
            sl = actual_entry * (1 - entry.stop_width_pct)
            tp_dist = entry.rr_ratio * entry.stop_width_pct
            tp1 = actual_entry * (1 + tp_dist)
            tp2 = entry.tp2 if entry.tp2 > actual_entry else actual_entry * (1 + tp_dist * 1.5)

        return Signal(
            strategy=f"anticipatory_{entry.setup_type}",
            symbol=entry.symbol,
            side=entry.side,
            confidence=entry.confidence,
            entry=actual_entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=0,  # Not needed for sniper path
            metadata={
                "num_agree": 2,  # Anticipatory = quant + timing agreement
                "strategies_agree": [f"anticipatory_{entry.setup_type}", "precision_timing"],
                "regime": "anticipatory",
                "anticipatory_entry": True,
                "entry_id": entry.entry_id,
                "setup_type": entry.setup_type,
                "rr_ratio": entry.rr_ratio,
                "leverage_suggestion": entry.leverage,
                "target_price": entry.target_price,
                "reasoning": entry.reasoning,
                # Conviction sizing data
                "confluence_count": entry.confluence_count,
                "confluence_sources": list(entry.confluence_sources),
                "multi_tf_aligned": entry.timeframe_alignment == "aligned",
                "timeframe_alignment": entry.timeframe_alignment,
                # Volume confirmation data (for scorecard)
                "vol_ratio": vol_ratio,
            },
            signal_context=(
                f"ANTICIPATORY {entry.setup_type}: waited for price "
                f"${entry.target_price:.2f}, triggered at ${current_price:.2f}. "
                f"R:R={entry.rr_ratio:.1f} | vol={vol_ratio:.1f}x avg | "
                f"{entry.reasoning}"
            ),
        )

    # -- Persistence --------------------------------------------------------

    def _save_pending(self) -> None:
        """Save pending entries to disk."""
        try:
            data = {
                "pending": [e.to_dict() for e in self._pending],
                "counter": self._entry_counter,
                "stats": {
                    "triggered": self._triggered_count,
                    "expired": self._expired_count,
                    "invalidated": self._invalidated_count,
                },
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp = _PENDING_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, _PENDING_PATH)
        except Exception as e:
            logger.warning(f"[ANTICIPATE] Failed to save pending entries: {e}")

    def _load_pending(self) -> None:
        """Load pending entries from disk."""
        if not os.path.exists(_PENDING_PATH):
            return
        try:
            with open(_PENDING_PATH, "r") as f:
                content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
            self._entry_counter = data.get("counter", 0)
            stats = data.get("stats", {})
            self._triggered_count = stats.get("triggered", 0)
            self._expired_count = stats.get("expired", 0)
            self._invalidated_count = stats.get("invalidated", 0)

            now = time.time()
            for pd_dict in data.get("pending", []):
                try:
                    entry = PendingEntry.from_dict(pd_dict)
                    # Only load entries that are still pending and not expired
                    if entry.status == "pending" and entry.expiry > now:
                        self._pending.append(entry)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[ANTICIPATE] Failed to load pending entries: {e}")

    def _log_outcome(self, entry: PendingEntry, outcome: str, price: float) -> None:
        """Append entry outcome to history log."""
        try:
            record = {
                "entry_id": entry.entry_id,
                "symbol": entry.symbol,
                "side": entry.side,
                "setup_type": entry.setup_type,
                "target_price": entry.target_price,
                "outcome": outcome,
                "price_at_outcome": price,
                "rr_ratio": entry.rr_ratio,
                "leverage": entry.leverage,
                "timeframe_alignment": entry.timeframe_alignment,
                "checks": entry.checks,
                "best_approach_price": entry.best_approach_price,
                "created_at": entry.created_at_iso,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "lifetime_hours": round((time.time() - entry.created_at) / 3600, 2),
                "reasoning": entry.reasoning,
            }
            with open(_HISTORY_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.warning(f"[ANTICIPATE] Failed to log outcome: {e}")


# -- Module-level singleton -------------------------------------------------

_engine: Optional[AnticipationEngine] = None


def get_anticipation_engine() -> AnticipationEngine:
    """Get or create the singleton AnticipationEngine."""
    global _engine
    if _engine is None:
        _engine = AnticipationEngine()
    return _engine
