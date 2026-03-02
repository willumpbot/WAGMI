"""
Multi-Factor Chop Detector — identifies choppy/ranging markets where strategies have no edge.

Factors (each scored 0.0-1.0, combined into chop_score):
1. Volume drought: volume < 50% of 20-bar avg
2. ATR compression: ATR14 < 60% of ATR50 (volatility contracting)
3. Range tightness: price range < 1.5% over recent bars
4. Directional weakness: ADX < 20 (no trend)
5. Whipsaw count: 3+ direction flips in last 8 bars

Combined: chop_score = weighted average of all factors
Threshold: CHOP_THRESHOLD env var (default 0.55)
"""

import logging
import os
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger("bot.strategy.chop_detector")

# Factor weights (sum to 1.0)
_WEIGHTS = {
    "volume": 0.20,
    "atr_compression": 0.25,
    "range_tightness": 0.20,
    "adx": 0.20,
    "whipsaw": 0.15,
}


class ChopDetector:
    """Multi-factor choppy market detector."""

    def __init__(self, threshold: float = None):
        self.threshold = threshold or float(os.getenv("CHOP_THRESHOLD", "0.55"))

    def is_choppy(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> Tuple[bool, float, str]:
        """Evaluate whether the market is choppy.

        Returns:
            (is_choppy, chop_score, detail_string)
        """
        df_1h = data.get("1h")
        if df_1h is None or df_1h.empty or len(df_1h) < 20:
            return False, 0.0, "insufficient data"

        factors = {}
        details = []

        # Factor 1: Volume drought
        vol_score = self._volume_factor(df_1h)
        factors["volume"] = vol_score
        details.append(f"vol={vol_score:.2f}")

        # Factor 2: ATR compression
        atr_score = self._atr_compression_factor(df_1h)
        factors["atr_compression"] = atr_score
        details.append(f"atr_comp={atr_score:.2f}")

        # Factor 3: Range tightness
        range_score = self._range_tightness_factor(df_1h)
        factors["range_tightness"] = range_score
        details.append(f"range={range_score:.2f}")

        # Factor 4: ADX (directional weakness)
        adx_score = self._adx_factor(df_1h)
        factors["adx"] = adx_score
        details.append(f"adx={adx_score:.2f}")

        # Factor 5: Whipsaw count
        whipsaw_score = self._whipsaw_factor(df_1h)
        factors["whipsaw"] = whipsaw_score
        details.append(f"whip={whipsaw_score:.2f}")

        # Weighted combination
        chop_score = sum(
            _WEIGHTS[k] * factors[k] for k in _WEIGHTS if k in factors
        )

        is_chop = chop_score >= self.threshold
        detail_str = " ".join(details) + f" => {chop_score:.2f}"

        if is_chop:
            logger.info(
                f"[{symbol}] CHOP DETECTED: score={chop_score:.2f} "
                f"(threshold={self.threshold}) [{detail_str}]"
            )

        return is_chop, chop_score, detail_str

    def _volume_factor(self, df: pd.DataFrame) -> float:
        """Score 0-1: how much volume has dried up vs 20-bar average."""
        vol = df["volume"].astype(float)
        avg_vol = float(vol.tail(20).mean())
        if avg_vol <= 0:
            return 0.0
        current_vol = float(vol.iloc[-1])
        ratio = current_vol / avg_vol

        # ratio < 0.3 = extreme drought (1.0), ratio 0.3-0.7 = partial (scaled), ratio > 0.7 = fine (0.0)
        if ratio >= 0.7:
            return 0.0
        if ratio <= 0.3:
            return 1.0
        return (0.7 - ratio) / 0.4

    def _atr_compression_factor(self, df: pd.DataFrame) -> float:
        """Score 0-1: how compressed current volatility is vs longer-term.
        ATR14 < 60% of ATR50 = high compression."""
        if len(df) < 50:
            return 0.0

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        prev_close = close.shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
        atr50 = float(tr.rolling(50, min_periods=10).mean().iloc[-1])

        if atr50 <= 0:
            return 0.0

        ratio = atr14 / atr50

        # ratio < 0.4 = extreme compression (1.0), ratio 0.4-0.8 = partial, ratio > 0.8 = fine (0.0)
        if ratio >= 0.8:
            return 0.0
        if ratio <= 0.4:
            return 1.0
        return (0.8 - ratio) / 0.4

    def _range_tightness_factor(self, df: pd.DataFrame) -> float:
        """Score 0-1: how tight the recent price range is.
        If (max-min)/mid < 1.5% over last 5 bars, market is ranging."""
        if len(df) < 5:
            return 0.0

        recent = df.tail(5)
        high_max = float(recent["high"].astype(float).max())
        low_min = float(recent["low"].astype(float).min())
        mid = (high_max + low_min) / 2

        if mid <= 0:
            return 0.0

        range_pct = (high_max - low_min) / mid * 100

        # range < 0.5% = extreme tightness (1.0), range 0.5-2.0% = partial, range > 2.0% = fine (0.0)
        if range_pct >= 2.0:
            return 0.0
        if range_pct <= 0.5:
            return 1.0
        return (2.0 - range_pct) / 1.5

    def _adx_factor(self, df: pd.DataFrame) -> float:
        """Score 0-1: directional weakness via simplified ADX.
        ADX < 15 = strong chop (1.0), ADX > 25 = trending (0.0)."""
        if len(df) < 14:
            return 0.0

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        # Simplified ADX: use directional movement ratio
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr14 = tr.rolling(14, min_periods=1).mean()
        plus_di = (plus_dm.rolling(14, min_periods=1).mean() / atr14.replace(0, 1e-9)) * 100
        minus_di = (minus_dm.rolling(14, min_periods=1).mean() / atr14.replace(0, 1e-9)) * 100

        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
        adx = float(dx.rolling(14, min_periods=1).mean().iloc[-1])

        # ADX < 15 = strong chop, ADX > 25 = trending
        if adx >= 25:
            return 0.0
        if adx <= 15:
            return 1.0
        return (25 - adx) / 10

    def _whipsaw_factor(self, df: pd.DataFrame) -> float:
        """Score 0-1: count direction flips in last 8 bars.
        3+ flips = high whipsaw (1.0), 0-1 = low (0.0)."""
        if len(df) < 9:
            return 0.0

        recent = df.tail(9)
        closes = recent["close"].astype(float).values

        # Count direction changes
        flips = 0
        for i in range(2, len(closes)):
            prev_dir = closes[i - 1] - closes[i - 2]
            curr_dir = closes[i] - closes[i - 1]
            if prev_dir * curr_dir < 0:  # Direction changed
                flips += 1

        # 0-1 flips = 0.0, 2 = 0.33, 3 = 0.67, 4+ = 1.0
        if flips <= 1:
            return 0.0
        if flips >= 4:
            return 1.0
        return (flips - 1) / 3.0
