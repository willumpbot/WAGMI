"""
Dip-Buy Detector for HYPE.

Monitors 5m candle data for dip patterns and boosts sniper signal priority.
Tracks pattern occurrence rate and success rate.

Usage:
    from manual.dip_detector import DipDetector
    detector = DipDetector()
    result = detector.check(candles_5m)  # DataFrame with OHLCV
    if result["dip_detected"]:
        # Boost signal priority
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import pandas as pd

logger = logging.getLogger("bot.manual.dip_detector")


class DipDetector:
    """
    Detects dip-buy patterns on HYPE using 5m candle data.

    Pattern:
    1. Price drops > MIN_DIP_PCT from recent high (lookback window)
    2. Recovery begins: current close > previous low
    3. Optional: Volume spike on dip candle (confirms real selling)

    From data analysis:
    - Moderate dips (2-5%): 88.5% WR
    - Deep dips (5-10%): 81.1% WR
    - Very deep dips (>10%): 100% WR (small N)
    - Fast resolution (1-3 bars): 91.2% WR
    """

    # Pattern parameters
    MIN_DIP_PCT = 0.5      # Minimum dip from recent high (0.5%)
    LOOKBACK_CANDLES = 12  # Look back 12 candles (1 hour on 5m)
    RECOVERY_MIN_PCT = 0.1 # Minimum recovery to confirm bounce starting
    VOLUME_SPIKE_MULT = 1.3  # Volume > 1.3x avg = spike

    # Tracking
    _history: List[Dict] = []

    def __init__(self, min_dip_pct: float = 0.5, lookback: int = 12):
        self.MIN_DIP_PCT = min_dip_pct
        self.LOOKBACK_CANDLES = lookback
        self._history = []

    def check(self, df: pd.DataFrame, symbol: str = "HYPE") -> Dict[str, Any]:
        """
        Check for dip-buy pattern in 5m candle data.

        Args:
            df: DataFrame with columns: open, high, low, close, volume
            symbol: Symbol being checked

        Returns:
            Dict with dip_detected, dip_depth_pct, recovery_pct, etc.
        """
        if df is None or len(df) < self.LOOKBACK_CANDLES + 2:
            return {"dip_detected": False, "reason": "insufficient_data"}

        recent = df.tail(self.LOOKBACK_CANDLES + 2)
        current = recent.iloc[-1]
        prev = recent.iloc[-2]

        current_close = float(current["close"])
        current_low = float(current["low"])
        prev_low = float(prev["low"])

        # Find recent high in lookback window
        recent_high = float(recent["high"].max())

        # Calculate dip depth
        dip_depth_pct = (recent_high - current_low) / recent_high * 100 if recent_high > 0 else 0

        # Check if we've dipped enough
        if dip_depth_pct < self.MIN_DIP_PCT:
            return {
                "dip_detected": False,
                "reason": f"dip too shallow ({dip_depth_pct:.2f}% < {self.MIN_DIP_PCT}%)",
                "dip_depth_pct": round(dip_depth_pct, 3),
                "recent_high": recent_high,
                "current_price": current_close,
            }

        # Check for recovery (current close > previous candle's low)
        recovery_pct = (current_close - prev_low) / prev_low * 100 if prev_low > 0 else 0

        # Volume analysis
        avg_volume = float(recent["volume"].mean()) if "volume" in recent.columns else 0
        current_volume = float(current.get("volume", 0))
        volume_spike = current_volume > avg_volume * self.VOLUME_SPIKE_MULT if avg_volume > 0 else False

        # Classify dip depth
        if dip_depth_pct >= 10:
            depth_class = "very_deep"
            expected_wr = 100.0  # From data (small N)
        elif dip_depth_pct >= 5:
            depth_class = "deep"
            expected_wr = 81.1
        elif dip_depth_pct >= 2:
            depth_class = "moderate"
            expected_wr = 88.5
        else:
            depth_class = "shallow"
            expected_wr = 85.0  # General HYPE BUY WR

        # Determine if dip is detected
        dip_detected = dip_depth_pct >= self.MIN_DIP_PCT
        recovering = recovery_pct > self.RECOVERY_MIN_PCT

        # Priority boost: deeper dip + recovery + volume = stronger signal
        priority_boost = 0
        if dip_detected and recovering:
            priority_boost += 1
        if depth_class in ("moderate", "deep", "very_deep"):
            priority_boost += 1
        if volume_spike:
            priority_boost += 1

        result = {
            "dip_detected": dip_detected,
            "recovering": recovering,
            "symbol": symbol,
            "dip_depth_pct": round(dip_depth_pct, 3),
            "depth_class": depth_class,
            "expected_wr": expected_wr,
            "recovery_pct": round(recovery_pct, 3),
            "recent_high": round(recent_high, 4),
            "current_low": round(current_low, 4),
            "current_close": round(current_close, 4),
            "volume_spike": volume_spike,
            "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume > 0 else 0,
            "priority_boost": priority_boost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recommendation": self._get_recommendation(dip_detected, recovering, depth_class, priority_boost),
        }

        # Track history
        if dip_detected:
            self._history.append(result)
            if len(self._history) > 100:
                self._history = self._history[-100:]

        return result

    def _get_recommendation(self, dip_detected: bool, recovering: bool,
                            depth_class: str, priority: int) -> str:
        if not dip_detected:
            return "NO_DIP"
        if not recovering:
            return "DIP_IN_PROGRESS - wait for recovery candle"
        if priority >= 3:
            return "STRONG_DIP_BUY - enter now with full size"
        if priority >= 2:
            return "DIP_BUY - enter on next HYPE BUY signal burst"
        return "WEAK_DIP - monitor, enter only if 3+ signal burst confirms"

    def get_stats(self) -> Dict:
        """Get pattern occurrence statistics"""
        if not self._history:
            return {"patterns_detected": 0}

        depths = [h["dip_depth_pct"] for h in self._history]
        return {
            "patterns_detected": len(self._history),
            "avg_dip_depth": round(sum(depths) / len(depths), 2),
            "max_dip_depth": round(max(depths), 2),
            "depth_distribution": {
                "shallow": sum(1 for h in self._history if h["depth_class"] == "shallow"),
                "moderate": sum(1 for h in self._history if h["depth_class"] == "moderate"),
                "deep": sum(1 for h in self._history if h["depth_class"] == "deep"),
                "very_deep": sum(1 for h in self._history if h["depth_class"] == "very_deep"),
            },
        }
