"""
Strategy: Cumulative Volume Delta (CVD) Divergence

Core logic:
- Computes Cumulative Volume Delta from OHLCV candle data
- Buy volume approximation: volume * (close - low) / (high - low)
- Sell volume approximation: volume * (high - close) / (high - low)
- CVD = cumulative sum of (buy_volume - sell_volume)

Signal generation:
- Detects divergence between CVD slope and price slope over a rolling window
- Bullish divergence: price falling but CVD rising -> BUY
- Bearish divergence: price rising but CVD falling -> SELL
- Requires minimum slope magnitude to filter noise

Data requirements:
- 1h OHLCV with at least 30 candles
"""

import logging
import os
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.cvd_signal")

# --- Configurable parameters via environment ---
CVD_LOOKBACK = int(os.getenv("CVD_LOOKBACK", "20"))
CVD_MIN_DIVERGENCE = float(os.getenv("CVD_MIN_DIVERGENCE", "0.5"))
CVD_ATR_PERIOD = int(os.getenv("CVD_ATR_PERIOD", "14"))

# Minimum candles required for evaluation
MIN_CANDLES = 30


def _atr(df: pd.DataFrame, period: int = CVD_ATR_PERIOD) -> pd.Series:
    """Average True Range."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _compute_cvd(df: pd.DataFrame) -> pd.Series:
    """Compute Cumulative Volume Delta from OHLCV data.

    Approximation: split each candle's volume into buy/sell
    based on where the close sits within the high-low range.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    candle_range = high - low
    # Avoid division by zero on doji candles (range == 0)
    safe_range = candle_range.replace(0, np.nan)

    buy_volume = volume * (close - low) / safe_range
    sell_volume = volume * (high - close) / safe_range

    # For doji candles, split volume 50/50 (delta = 0)
    buy_volume = buy_volume.fillna(volume * 0.5)
    sell_volume = sell_volume.fillna(volume * 0.5)

    delta = buy_volume - sell_volume
    return delta.cumsum()


def _slope(series: pd.Series, lookback: int) -> float:
    """Simple slope over the lookback window: (last - first) / lookback.

    Returns 0.0 if insufficient data.
    """
    if len(series) < lookback:
        return 0.0
    window = series.iloc[-lookback:]
    first = float(window.iloc[0])
    last = float(window.iloc[-1])
    if first == 0 and last == 0:
        return 0.0
    return (last - first) / lookback


class CVDSignalStrategy(BaseStrategy):
    """Cumulative Volume Delta divergence strategy.

    Detects when CVD trend and price trend diverge, signaling that
    underlying buying/selling pressure disagrees with visible price
    movement. This often precedes reversals.
    """

    def __init__(self, symbols: Dict[str, Any] = None):
        super().__init__("cvd_signal", symbols or {})

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or len(df) < MIN_CANDLES:
            return None

        close = df["close"].astype(float)
        price = float(close.iloc[-1])
        atr_series = _atr(df)
        atr = float(atr_series.iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Compute CVD
        cvd = _compute_cvd(df)

        # Compute slopes over the lookback window
        lookback = min(CVD_LOOKBACK, len(df) - 1)
        if lookback < 5:
            return None

        price_slope = _slope(close, lookback)
        cvd_slope = _slope(cvd, lookback)

        # Normalize slopes for comparison:
        # Price slope normalized by price level, CVD slope by its own magnitude
        price_slope_norm = price_slope / price if price != 0 else 0.0

        # For CVD slope normalization, use the mean absolute CVD over the window
        # to get a unitless ratio
        cvd_window = cvd.iloc[-lookback:]
        cvd_range = float(cvd_window.max() - cvd_window.min())
        cvd_slope_norm = cvd_slope / cvd_range if cvd_range != 0 else 0.0

        # Detect divergence: slopes must go in opposite directions
        # and both must have meaningful magnitude
        min_price_slope = atr * 0.01 / price  # Minimum price movement threshold
        if abs(price_slope_norm) < min_price_slope:
            return None  # Price not moving enough to constitute a divergence

        side = None
        divergence_strength = 0.0

        if price_slope_norm < 0 and cvd_slope_norm > 0:
            # Bullish divergence: price falling, CVD rising
            side = "BUY"
            divergence_strength = abs(cvd_slope_norm) / max(abs(price_slope_norm), 1e-12)
        elif price_slope_norm > 0 and cvd_slope_norm < 0:
            # Bearish divergence: price rising, CVD falling
            side = "SELL"
            divergence_strength = abs(cvd_slope_norm) / max(abs(price_slope_norm), 1e-12)

        if side is None:
            return None

        # Filter: require minimum divergence strength
        if divergence_strength < CVD_MIN_DIVERGENCE:
            return None

        # Confidence: 60-80 based on divergence strength
        # Stronger divergence = higher confidence, capped at 80
        confidence = 60.0 + min(20.0, divergence_strength * 10.0)
        confidence = max(60.0, min(80.0, confidence))

        # SL/TP construction
        atr_mult_sl = 1.5
        atr_mult_tp1 = 2.0
        atr_mult_tp2 = 3.0

        if side == "BUY":
            sl = price - atr * atr_mult_sl
            tp1 = price + atr * atr_mult_tp1
            tp2 = price + atr * atr_mult_tp2
        else:
            sl = price + atr * atr_mult_sl
            tp1 = price - atr * atr_mult_tp1
            tp2 = price - atr * atr_mult_tp2

        context_parts = [
            f"CVD Divergence: {side}",
            f"price_slope={price_slope_norm:.6f}",
            f"cvd_slope={cvd_slope_norm:.4f}",
            f"divergence={divergence_strength:.2f}",
            f"ATR={atr:.2f}",
        ]

        sig = Signal(
            strategy="cvd_signal",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "signal_type": "cvd_divergence",
                "price_slope_norm": round(price_slope_norm, 8),
                "cvd_slope_norm": round(cvd_slope_norm, 6),
                "divergence_strength": round(divergence_strength, 4),
                "lookback": lookback,
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(
            f"[{symbol}] CVD signal: {side} conf={confidence:.0f}% "
            f"div_strength={divergence_strength:.2f} "
            f"price_slope={price_slope_norm:.6f} cvd_slope={cvd_slope_norm:.4f}"
        )
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or len(df) < MIN_CANDLES:
            return {
                "strategy": self.name,
                "symbol": symbol,
                "state": "insufficient_data",
            }

        close = df["close"].astype(float)
        cvd = _compute_cvd(df)

        lookback = min(CVD_LOOKBACK, len(df) - 1)
        price_slope = _slope(close, lookback)
        cvd_slope = _slope(cvd, lookback)

        price = float(close.iloc[-1])
        price_slope_norm = price_slope / price if price != 0 else 0.0

        cvd_window = cvd.iloc[-lookback:]
        cvd_range = float(cvd_window.max() - cvd_window.min())
        cvd_slope_norm = cvd_slope / cvd_range if cvd_range != 0 else 0.0

        diverging = (price_slope_norm > 0 and cvd_slope_norm < 0) or \
                    (price_slope_norm < 0 and cvd_slope_norm > 0)

        return {
            "strategy": self.name,
            "symbol": symbol,
            "cvd_current": round(float(cvd.iloc[-1]), 2),
            "price_slope_norm": round(price_slope_norm, 8),
            "cvd_slope_norm": round(cvd_slope_norm, 6),
            "diverging": diverging,
            "lookback": lookback,
        }
