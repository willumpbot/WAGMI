"""
Mean-Reversion Strategy — Two detection modes for dip-buying setups.

Mode 1: Bollinger Band bounce (consolidation regimes, ADX < 28)
  Long: Price closes below lower BB AND RSI < 35 AND ADX < 28
  Short: Price closes above upper BB AND RSI > 65 AND ADX < 28
  TP1: Middle BB (the mean), TP2: Opposite BB
  SL: 1.5 ATR beyond entry

Mode 2: Red Candle Streak (proven HYPE alpha)
  Evidence (2026-03-25 analysis):
  - 3+ consecutive red 1h candles on HYPE → 79% bounce probability in next 6h
  - Average gain: +1.17% per bounce
  - RSI 30-35 zone: PF 3.03 (rare big winners)
  Entry conditions:
  - 3+ consecutive red 1h candles (close < open)
  - RSI between 28-40 (recovering from oversold, not still crashing)
  - Price below EMA20 (confirming pullback from mean)
  Targets:
  - TP1: EMA20 (natural reversion target)
  - TP2: 2.5x ATR above entry
  - SL: 2.0x ATR below entry
  Confidence: streak count (3=70, 4=75, 5+=80) + RSI zone bonus

Both modes use the same strategy name "mean_reversion" for ensemble voting.
"""

import logging
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.mean_reversion")


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, min_periods=n, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = _sma(close, period)
    std = close.rolling(period, min_periods=1).std().fillna(0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = (upper - lower) / mid  # Bandwidth as fraction of mid
    return upper, mid, lower, std, width


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Simplified ADX calculation."""
    high = df["high"]
    low = df["low"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_vals = _atr(df, period)
    atr_safe = atr_vals.replace(0, 1e-12)

    plus_di = 100.0 * plus_dm.rolling(period, min_periods=1).mean() / atr_safe
    minus_di = 100.0 * minus_dm.rolling(period, min_periods=1).mean() / atr_safe

    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = dx.rolling(period, min_periods=1).mean()
    return adx


def _count_red_streak(df: pd.DataFrame) -> int:
    """Count consecutive red candles (close < open) from the most recent bar backwards."""
    if df is None or df.empty:
        return 0
    opens = df["open"].values
    closes = df["close"].values
    streak = 0
    for i in range(len(df) - 1, -1, -1):
        if closes[i] < opens[i]:
            streak += 1
        else:
            break
    return streak


def _count_green_streak(df: pd.DataFrame) -> int:
    """Count consecutive green candles (close > open) from the most recent bar backwards."""
    if df is None or df.empty:
        return 0
    opens = df["open"].values
    closes = df["close"].values
    streak = 0
    for i in range(len(df) - 1, -1, -1):
        if closes[i] > opens[i]:
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class MeanReversionStrategy(BaseStrategy):
    """
    Three-mode mean-reversion strategy:

    Mode 1 (BB Bounce): Bollinger Band extremes in consolidation (ADX < 28).
    Mode 2 (Red Streak BUY): 3+ consecutive red 1h candles with RSI recovery.
    Mode 3 (Green Streak SELL): 3+ consecutive green 1h candles with RSI overbought.

    If multiple modes trigger simultaneously, the higher-confidence one wins.
    """

    # ----- Bollinger Band mode parameters -----
    BB_PERIOD = 20
    BB_STD = 2.0
    RSI_PERIOD = 14
    ADX_PERIOD = 14
    ATR_PERIOD = 14

    MAX_ADX = 28.0
    MIN_BB_WIDTH_PERCENTILE = 0.10
    RSI_OVERSOLD = 32.0          # Tightened from 35: require genuinely oversold for BB bounce
    RSI_OVERBOUGHT = 68.0        # Tightened from 65: require genuinely overbought for BB bounce
    SL_ATR_MULT_BB = 1.5
    TP2_ATR_MULT = 3.0
    BANDWIDTH_EXPANSION_KILL = 1.5

    # ----- Red Candle Streak mode parameters -----
    MIN_RED_STREAK = 3           # Minimum consecutive red 1h candles
    STREAK_RSI_LOW = 25.0        # RSI floor: lowered from 28 to catch deeper dips
    STREAK_RSI_HIGH = 37.0       # RSI ceiling: tightened from 40, must be genuinely oversold
    SL_ATR_MULT_STREAK = 2.0     # Stop loss: 2.0x ATR below entry
    TP2_ATR_MULT_STREAK = 2.5    # TP2: 2.5x ATR above entry

    # ----- Green Candle Streak mode parameters (overbought reversal SHORT) -----
    # DISABLED: Counter-trend shorts into green streaks on crypto are net-negative.
    # Crypto trends heavily; shorting momentum is a losing game without strong confluence.
    # Keep code but raise thresholds to effectively disable until we have 50+ validated trades.
    MIN_GREEN_STREAK = 5         # Raised from 3: require extreme extension before shorting
    GREEN_RSI_LOW = 72.0         # Raised from 60: must be clearly overbought
    GREEN_RSI_HIGH = 80.0        # RSI ceiling (above 80 = extreme, maybe still running)
    SL_ATR_MULT_GREEN = 2.0      # Stop loss: 2.0x ATR above entry
    TP2_ATR_MULT_GREEN = 2.5     # TP2: 2.5x ATR below entry

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("mean_reversion", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    # ------------------------------------------------------------------
    # Mode 1: Bollinger Band bounce (consolidation)
    # ------------------------------------------------------------------
    def _evaluate_bb_bounce(
        self, symbol: str, df: pd.DataFrame,
        close: pd.Series, current_price: float,
        rsi_series: pd.Series, current_rsi: float,
        current_adx: float, current_atr: float,
    ) -> Optional[Signal]:
        """Detect BB bounce setups in consolidation regimes."""

        # Regime gate: only in consolidation
        if current_adx >= self.MAX_ADX:
            return None

        bb_upper, bb_mid, bb_lower, bb_std, bb_width = _bollinger_bands(
            close, self.BB_PERIOD, self.BB_STD
        )
        current_bb_upper = float(bb_upper.iloc[-1])
        current_bb_mid = float(bb_mid.iloc[-1])
        current_bb_lower = float(bb_lower.iloc[-1])
        current_bb_width = float(bb_width.iloc[-1])

        # Breakout kill switch: skip if bandwidth is expanding
        avg_bb_width = float(bb_width.rolling(20, min_periods=5).mean().iloc[-1])
        if avg_bb_width > 0 and current_bb_width > avg_bb_width * self.BANDWIDTH_EXPANSION_KILL:
            return None

        side = None
        confidence_base = 63.0
        z_score = 0.0

        # Long: price at/below lower BB + RSI oversold
        if current_price <= current_bb_lower and current_rsi <= self.RSI_OVERSOLD:
            side = "BUY"
            z_score = (current_price - current_bb_mid) / max(float(bb_std.iloc[-1]), 1e-12)
            confidence_base += min(15, abs(z_score) * 3)

        # Short: price at/above upper BB + RSI overbought
        elif current_price >= current_bb_upper and current_rsi >= self.RSI_OVERBOUGHT:
            side = "SELL"
            z_score = (current_price - current_bb_mid) / max(float(bb_std.iloc[-1]), 1e-12)
            confidence_base += min(15, abs(z_score) * 3)

        if side is None:
            return None

        # Volume confirmation
        vol = df.get("volume")
        if vol is not None and len(vol) >= 20:
            avg_vol = float(vol.rolling(20, min_periods=5).mean().iloc[-1])
            current_vol = float(vol.iloc[-1])
            if avg_vol > 0:
                vol_ratio = current_vol / avg_vol
                if vol_ratio > 1.2:
                    confidence_base += 5
                elif vol_ratio < 0.5:
                    confidence_base -= 5

        # ADX proximity bonus
        if current_adx < 15:
            confidence_base += 5
        elif current_adx < 20:
            confidence_base += 2

        confidence = min(85.0, max(50.0, confidence_base))

        entry = current_price
        if side == "BUY":
            sl = entry - self.SL_ATR_MULT_BB * current_atr
            tp1 = current_bb_mid
            tp2 = current_bb_upper
        else:
            sl = entry + self.SL_ATR_MULT_BB * current_atr
            tp1 = current_bb_mid
            tp2 = current_bb_lower

        stop_width = abs(entry - sl)
        if stop_width < entry * 0.003:
            return None
        tp1_dist = abs(entry - tp1)
        rr = tp1_dist / stop_width if stop_width > 0 else 0
        if rr < 0.5:
            return None

        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=current_atr,
            metadata={
                "setup_type": "mean_reversion_bb",
                "detection_mode": "bb_bounce",
                "adx": round(current_adx, 1),
                "rsi": round(current_rsi, 1),
                "bb_position": "lower" if side == "BUY" else "upper",
                "bb_width": round(current_bb_width, 4),
                "z_score": round(z_score, 2),
                "rr_tp1": round(rr, 2),
                "entry_type": "MEDIUM",
            },
            signal_context=(
                f"BB bounce {side}: price at {'lower' if side == 'BUY' else 'upper'} BB "
                f"(z={z_score:.1f}s), RSI={current_rsi:.0f}, ADX={current_adx:.0f}. "
                f"Target: middle BB at {current_bb_mid:.2f}"
            ),
        )

        if not signal.is_valid:
            return None

        logger.info(
            f"[{symbol}] BB bounce {side}: RSI={current_rsi:.0f} ADX={current_adx:.0f} "
            f"z={z_score:.1f}s conf={confidence:.0f}% R:R={rr:.2f}"
        )
        return signal

    # ------------------------------------------------------------------
    # Mode 2: Red candle streak bounce (proven HYPE alpha)
    # ------------------------------------------------------------------
    def _evaluate_red_streak(
        self, symbol: str, df: pd.DataFrame,
        close: pd.Series, current_price: float,
        rsi_series: pd.Series, current_rsi: float,
        current_atr: float,
    ) -> Optional[Signal]:
        """Detect BUY setups after 3+ consecutive red 1h candles with RSI recovery.

        Evidence: HYPE 3+ red streak -> 79% bounce probability, +1.17% avg gain.
        RSI 30-35 zone has PF 3.03 (rare big winners).
        """

        # Count consecutive red candles from most recent bar
        red_streak = _count_red_streak(df)
        if red_streak < self.MIN_RED_STREAK:
            return None

        # RSI must be in recovery zone: oversold but not crashing
        if current_rsi < self.STREAK_RSI_LOW or current_rsi > self.STREAK_RSI_HIGH:
            return None

        # Price must be below EMA20 (confirming pullback from mean)
        ema20 = _ema(close, 20)
        current_ema20 = float(ema20.iloc[-1])
        if pd.isna(current_ema20):
            return None
        if current_price >= current_ema20:
            return None  # Not a pullback — price still above the mean

        # ----- Signal fires: BUY only (this is a dip-buying setup) -----
        side = "BUY"
        entry = current_price

        # Confidence based on streak length + RSI zone bonus
        if red_streak >= 5:
            confidence_base = 80.0
        elif red_streak == 4:
            confidence_base = 75.0
        else:  # red_streak == 3
            confidence_base = 70.0

        # RSI zone bonus: sweet spot 30-35 has PF 3.03
        if 30.0 <= current_rsi <= 35.0:
            confidence_base += 5.0  # PF 3.03 zone
        elif current_rsi < 30.0:
            confidence_base += 2.0  # Deep oversold, slightly riskier

        # Volume confirmation: high volume on selloff = capitulation (bullish for bounce)
        vol = df.get("volume")
        if vol is not None and len(vol) >= 20:
            avg_vol = float(vol.rolling(20, min_periods=5).mean().iloc[-1])
            current_vol = float(vol.iloc[-1])
            if avg_vol > 0:
                vol_ratio = current_vol / avg_vol
                if vol_ratio > 1.5:
                    confidence_base += 3.0  # Capitulation volume
                elif vol_ratio < 0.5:
                    confidence_base -= 3.0  # Weak selloff, less reliable

        confidence = min(90.0, max(55.0, confidence_base))

        # Stop loss: 2.0x ATR below entry
        sl = entry - self.SL_ATR_MULT_STREAK * current_atr

        # TP1: EMA20 (natural reversion target — the "mean")
        tp1 = current_ema20

        # TP2: 2.5x ATR above entry (extended bounce target)
        tp2 = entry + self.TP2_ATR_MULT_STREAK * current_atr

        # Validate stop width
        stop_width = abs(entry - sl)
        if stop_width < entry * 0.003:
            return None

        # Validate R:R — TP1 is EMA20, which should be above entry
        tp1_dist = abs(entry - tp1)
        rr = tp1_dist / stop_width if stop_width > 0 else 0
        if rr < 0.5:
            # EMA20 is too close — fallback TP1 to 1.5x ATR above entry
            tp1 = entry + 1.5 * current_atr
            tp1_dist = abs(entry - tp1)
            rr = tp1_dist / stop_width if stop_width > 0 else 0

        # Total drop during red streak (for context)
        streak_start_price = float(df["open"].iloc[-red_streak])
        total_drop_pct = ((entry - streak_start_price) / streak_start_price) * 100

        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=current_atr,
            metadata={
                "setup_type": "mean_reversion_streak",
                "detection_mode": "red_streak",
                "red_streak": red_streak,
                "rsi": round(current_rsi, 1),
                "ema20": round(current_ema20, 4),
                "ema20_distance_pct": round(((current_ema20 - entry) / entry) * 100, 3),
                "total_drop_pct": round(total_drop_pct, 2),
                "rr_tp1": round(rr, 2),
                "entry_type": "SCALP",  # Bounce trade — short hold
            },
            signal_context=(
                f"Red streak bounce: {red_streak} consecutive red 1h candles, "
                f"RSI={current_rsi:.0f} (recovery zone), price {((current_ema20 - entry) / entry) * 100:.1f}% "
                f"below EMA20. Drop={total_drop_pct:.1f}%. "
                f"Target: EMA20 at {current_ema20:.2f} (R:R={rr:.1f})"
            ),
        )

        if not signal.is_valid:
            return None

        logger.info(
            f"[{symbol}] Red streak bounce: {red_streak} red candles, "
            f"RSI={current_rsi:.0f}, drop={total_drop_pct:.1f}%, "
            f"conf={confidence:.0f}%, R:R={rr:.2f}"
        )
        return signal

    # ------------------------------------------------------------------
    # Mode 3: Green candle streak reversal SHORT (mirror of Mode 2)
    # ------------------------------------------------------------------
    def _evaluate_green_streak(
        self, symbol: str, df: pd.DataFrame,
        close: pd.Series, current_price: float,
        rsi_series: pd.Series, current_rsi: float,
        current_atr: float,
    ) -> Optional[Signal]:
        """Detect SELL setups after 3+ consecutive green 1h candles with RSI overbought.

        Mirror of the red streak bounce logic: after extended green runs,
        overbought conditions favor mean-reversion shorts back to the EMA20.
        """

        # Count consecutive green candles from most recent bar
        green_streak = _count_green_streak(df)
        if green_streak < self.MIN_GREEN_STREAK:
            return None

        # RSI must be in overbought zone
        if current_rsi < self.GREEN_RSI_LOW or current_rsi > self.GREEN_RSI_HIGH:
            return None

        # Price must be above EMA20 (confirming overextension above mean)
        ema20 = _ema(close, 20)
        current_ema20 = float(ema20.iloc[-1])
        if pd.isna(current_ema20):
            return None
        if current_price <= current_ema20:
            return None  # Not overextended — price still at or below the mean

        # ----- Signal fires: SELL (overbought reversal short) -----
        side = "SELL"
        entry = current_price

        # Confidence based on streak length + RSI zone bonus
        # Reduced vs red streak: counter-trend shorts are inherently riskier
        if green_streak >= 6:
            confidence_base = 72.0
        elif green_streak == 5:
            confidence_base = 65.0
        else:  # green_streak == 4 (can't reach 3 anymore with MIN_GREEN_STREAK=5)
            confidence_base = 60.0

        # RSI zone bonus: 70-75 is the sweet spot for overbought reversals
        if 70.0 <= current_rsi <= 75.0:
            confidence_base += 5.0
        elif current_rsi > 75.0:
            confidence_base += 3.0  # Very overbought, slightly riskier (momentum)

        # Volume confirmation
        vol = df.get("volume")
        if vol is not None and len(vol) >= 20:
            avg_vol = float(vol.rolling(20, min_periods=5).mean().iloc[-1])
            current_vol = float(vol.iloc[-1])
            if avg_vol > 0:
                vol_ratio = current_vol / avg_vol
                if vol_ratio > 1.5:
                    confidence_base += 3.0  # Climax volume (exhaustion)
                elif vol_ratio < 0.5:
                    confidence_base -= 3.0  # Weak rally, less reliable

        confidence = min(88.0, max(55.0, confidence_base))

        # Stop loss: 2.0x ATR above entry
        sl = entry + self.SL_ATR_MULT_GREEN * current_atr

        # TP1: EMA20 (natural reversion target — the "mean")
        tp1 = current_ema20

        # TP2: 2.5x ATR below entry (extended short target)
        tp2 = entry - self.TP2_ATR_MULT_GREEN * current_atr

        # Validate stop width
        stop_width = abs(sl - entry)
        if stop_width < entry * 0.003:
            return None

        # Validate R:R
        tp1_dist = abs(entry - tp1)
        rr = tp1_dist / stop_width if stop_width > 0 else 0
        if rr < 0.5:
            # EMA20 is too close — fallback TP1 to 1.5x ATR below entry
            tp1 = entry - 1.5 * current_atr
            tp1_dist = abs(entry - tp1)
            rr = tp1_dist / stop_width if stop_width > 0 else 0

        # Total rally during green streak (for context)
        streak_start_price = float(df["open"].iloc[-green_streak])
        total_rally_pct = ((entry - streak_start_price) / streak_start_price) * 100

        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=current_atr,
            metadata={
                "setup_type": "mean_reversion_green_streak",
                "detection_mode": "green_streak",
                "green_streak": green_streak,
                "rsi": round(current_rsi, 1),
                "ema20": round(current_ema20, 4),
                "ema20_distance_pct": round(((entry - current_ema20) / entry) * 100, 3),
                "total_rally_pct": round(total_rally_pct, 2),
                "rr_tp1": round(rr, 2),
                "entry_type": "SCALP",
            },
            signal_context=(
                f"Green streak reversal SHORT: {green_streak} consecutive green 1h candles, "
                f"RSI={current_rsi:.0f} (overbought), price {((entry - current_ema20) / entry) * 100:.1f}% "
                f"above EMA20. Rally={total_rally_pct:.1f}%. "
                f"Target: EMA20 at {current_ema20:.2f} (R:R={rr:.1f})"
            ),
        )

        if not signal.is_valid:
            return None

        logger.info(
            f"[{symbol}] Green streak SHORT: {green_streak} green candles, "
            f"RSI={current_rsi:.0f}, rally={total_rally_pct:.1f}%, "
            f"conf={confidence:.0f}%, R:R={rr:.2f}"
        )
        return signal

    # ------------------------------------------------------------------
    # Main evaluate: try all modes, pick the best
    # ------------------------------------------------------------------
    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        """Evaluate for mean-reversion setups using both detection modes."""
        df = data.get("1h")
        if df is None or len(df) < 50:
            return None

        close = df["close"]
        current_price = float(close.iloc[-1])
        if current_price <= 0:
            return None

        # Shared indicators
        rsi_series = _rsi(close, self.RSI_PERIOD)
        current_rsi = float(rsi_series.iloc[-1])
        adx_series = _adx(df, self.ADX_PERIOD)
        current_adx = float(adx_series.iloc[-1])
        atr_series = _atr(df, self.ATR_PERIOD)
        current_atr = float(atr_series.iloc[-1])

        if current_atr <= 0:
            return None

        # Try all detection modes
        bb_signal = self._evaluate_bb_bounce(
            symbol, df, close, current_price,
            rsi_series, current_rsi, current_adx, current_atr,
        )
        streak_signal = self._evaluate_red_streak(
            symbol, df, close, current_price,
            rsi_series, current_rsi, current_atr,
        )
        green_signal = self._evaluate_green_streak(
            symbol, df, close, current_price,
            rsi_series, current_rsi, current_atr,
        )

        # If multiple fire, pick the one with highest confidence
        candidates = [s for s in [bb_signal, streak_signal, green_signal] if s is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.confidence)

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Get current mean-reversion status across both modes."""
        df = data.get("1h")
        if df is None or len(df) < 50:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        close = df["close"]
        current_price = float(close.iloc[-1])
        rsi_series = _rsi(close, self.RSI_PERIOD)
        current_rsi = float(rsi_series.iloc[-1])
        adx_series = _adx(df, self.ADX_PERIOD)
        current_adx = float(adx_series.iloc[-1])

        bb_upper, bb_mid, bb_lower, _, bb_width = _bollinger_bands(
            close, self.BB_PERIOD, self.BB_STD
        )
        bb_pos = "lower" if current_price <= float(bb_lower.iloc[-1]) else (
            "upper" if current_price >= float(bb_upper.iloc[-1]) else "middle"
        )

        red_streak = _count_red_streak(df)
        green_streak = _count_green_streak(df)
        ema20 = _ema(close, 20)
        current_ema20 = float(ema20.iloc[-1]) if not pd.isna(ema20.iloc[-1]) else None

        return {
            "symbol": symbol,
            "strategy": self.name,
            "price": round(current_price, 4),
            "rsi": round(current_rsi, 1),
            "adx": round(current_adx, 1),
            "bb_position": bb_pos,
            "bb_width": round(float(bb_width.iloc[-1]), 4),
            "regime_ok": current_adx < self.MAX_ADX,
            "rsi_extreme": current_rsi <= self.RSI_OVERSOLD or current_rsi >= self.RSI_OVERBOUGHT,
            "red_streak": red_streak,
            "green_streak": green_streak,
            "ema20": round(current_ema20, 4) if current_ema20 else None,
            "below_ema20": current_price < current_ema20 if current_ema20 else False,
            "above_ema20": current_price > current_ema20 if current_ema20 else False,
            "streak_rsi_ok": self.STREAK_RSI_LOW <= current_rsi <= self.STREAK_RSI_HIGH,
            "green_rsi_ok": self.GREEN_RSI_LOW <= current_rsi <= self.GREEN_RSI_HIGH,
        }
