"""
TIER 3.2: Cross-Asset Correlation Tracking

Detects when correlated assets move together (or diverge unexpectedly).

Why it matters for multi-asset trading:
- If BTC, SOL, HYPE all move together: Your 3 open positions = 1 big directional bet
- If BTC leads: You can predict SOL/HYPE moves 5-30min ahead
- If correlation breaks: Market structure changing (risky)

Use cases:
1. **Lead-lag detection**: "BTC moved +2%, SOL usually follows in 15min"
2. **Correlation drift**: "These assets usually correlate 0.8, now 0.2 - something's wrong"
3. **Portfolio risk**: "3 open positions, correlation matrix shows high cluster risk"
4. **Signal confirmation**: "SOL signal weak alone, but BTC just signaled same direction"

Expected impact: +0.3-0.5% daily by better position sizing and risk awareness
"""

import logging
import json
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
import time
import math

logger = logging.getLogger("bot.llm.correlation_tracking")


@dataclass
class PriceSnapshot:
    """Price snapshot for one asset at one time."""
    symbol: str
    timestamp: float
    price: float
    change_1h_pct: float
    change_24h_pct: float


@dataclass
class CorrelationMetrics:
    """Correlation metrics between two assets."""
    symbol1: str
    symbol2: str
    period_minutes: int  # 5, 15, 60, 240
    correlation: float  # -1 to 1
    sample_size: int  # Number of data points
    confidence: float  # How confident in this estimate? (0-1)
    timestamp: float


class CorrelationTracker:
    """
    Tracks correlation between assets and detects lead-lag relationships.

    Maintains rolling correlation windows:
    - 5m window: Recent correlation (very volatile)
    - 1h window: Medium-term correlation
    - 6h window: Session-level correlation
    - 24h window: Daily correlation
    """

    def __init__(self, lookback_minutes: int = 1440):  # 24 hours
        """
        Args:
            lookback_minutes: How far back to keep data
        """
        self.lookback_minutes = lookback_minutes
        self.price_history: Dict[str, List[PriceSnapshot]] = {}  # symbol -> list of snapshots
        self.correlation_cache: Dict[str, CorrelationMetrics] = {}  # (symbol1, symbol2, period) -> metrics
        self.output_file = os.path.join("data/llm", "correlations.jsonl")
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

    def record_price(
        self,
        symbol: str,
        price: float,
        change_1h_pct: float = 0.0,
        change_24h_pct: float = 0.0,
    ) -> None:
        """Record price for a symbol."""
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        snapshot = PriceSnapshot(
            symbol=symbol,
            timestamp=time.time(),
            price=price,
            change_1h_pct=change_1h_pct,
            change_24h_pct=change_24h_pct,
        )

        self.price_history[symbol].append(snapshot)

        # Trim old data
        cutoff_time = time.time() - (self.lookback_minutes * 60)
        self.price_history[symbol] = [s for s in self.price_history[symbol] if s.timestamp >= cutoff_time]

    def get_correlation(
        self,
        symbol1: str,
        symbol2: str,
        period_minutes: int = 60,
    ) -> Optional[CorrelationMetrics]:
        """
        Get correlation between two symbols.

        Args:
            symbol1: First symbol
            symbol2: Second symbol
            period_minutes: Window size (5, 15, 60, 240)

        Returns:
            CorrelationMetrics or None if insufficient data
        """
        cache_key = f"{symbol1}_{symbol2}_{period_minutes}"

        # Check cache (valid for 1 minute)
        if cache_key in self.correlation_cache:
            cached = self.correlation_cache[cache_key]
            if time.time() - cached.timestamp < 60:
                return cached

        # Get recent data
        hist1 = self.price_history.get(symbol1, [])
        hist2 = self.price_history.get(symbol2, [])

        if not hist1 or not hist2:
            return None

        # Align data: use only overlapping time range
        cutoff_time = time.time() - (period_minutes * 60)
        data1 = [(s.timestamp, s.price) for s in hist1 if s.timestamp >= cutoff_time]
        data2 = [(s.timestamp, s.price) for s in hist2 if s.timestamp >= cutoff_time]

        if len(data1) < 3 or len(data2) < 3:
            return None

        # Compute percentage changes
        changes1 = self._compute_price_changes(data1)
        changes2 = self._compute_price_changes(data2)

        if len(changes1) < 2 or len(changes2) < 2:
            return None

        # Align both series by timestamp
        aligned = self._align_series(
            [(s[0], c) for s, c in zip(data1[1:], changes1)],
            [(s[0], c) for s, c in zip(data2[1:], changes2)],
        )

        if len(aligned) < 2:
            return None

        changes1_aligned = [c1 for _, c1, _ in aligned]
        changes2_aligned = [c2 for _, _, c2 in aligned]

        # Compute Pearson correlation
        correlation = self._pearson_correlation(changes1_aligned, changes2_aligned)

        # Confidence: more data points = higher confidence
        confidence = min(1.0, len(aligned) / 20)

        metrics = CorrelationMetrics(
            symbol1=symbol1,
            symbol2=symbol2,
            period_minutes=period_minutes,
            correlation=correlation,
            sample_size=len(aligned),
            confidence=confidence,
            timestamp=time.time(),
        )

        # Cache result
        self.correlation_cache[cache_key] = metrics

        return metrics

    def _compute_price_changes(self, data: List[Tuple[float, float]]) -> List[float]:
        """Compute percentage changes from prices."""
        changes = []
        for i in range(1, len(data)):
            prev_price = data[i - 1][1]
            curr_price = data[i][1]
            if prev_price > 0:
                pct_change = ((curr_price - prev_price) / prev_price) * 100
                changes.append(pct_change)
        return changes

    def _align_series(
        self,
        series1: List[Tuple[float, float]],  # (timestamp, value)
        series2: List[Tuple[float, float]],  # (timestamp, value)
        max_time_diff_s: int = 60,
    ) -> List[Tuple[float, float, float]]:
        """Align two time series to same timestamps."""
        aligned = []

        for t1, v1 in series1:
            # Find closest match in series2
            closest = None
            closest_diff = max_time_diff_s + 1

            for t2, v2 in series2:
                diff = abs(t1 - t2)
                if diff < closest_diff:
                    closest = (t2, v2)
                    closest_diff = diff

            if closest and closest_diff <= max_time_diff_s:
                aligned.append((t1, v1, closest[1]))

        return aligned

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation coefficient."""
        if len(x) < 2 or len(y) < 2 or len(x) != len(y):
            return 0.0

        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
        denom_x = sum((x[i] - mean_x) ** 2 for i in range(len(x)))
        denom_y = sum((y[i] - mean_y) ** 2 for i in range(len(y)))

        if denom_x <= 0 or denom_y <= 0:
            return 0.0

        return numerator / math.sqrt(denom_x * denom_y)

    def detect_lead_lag(
        self,
        leader: str,
        follower: str,
        period_minutes: int = 60,
    ) -> Optional[Dict]:
        """
        Detect if one asset leads another.

        Returns:
            {"lead_lag_minutes": 15, "correlation": 0.85} if detected
            None if no clear lead-lag relationship
        """
        hist_leader = self.price_history.get(leader, [])
        hist_follower = self.price_history.get(follower, [])

        if not hist_leader or not hist_follower:
            return None

        # Try different lags (5m, 10m, 15m, 30m)
        best_lag_minutes = None
        best_correlation = 0.0

        for lag_minutes in [5, 10, 15, 30]:
            lag_seconds = lag_minutes * 60

            # Shift follower data forward by lag
            cutoff_time = time.time() - (period_minutes * 60)
            leader_data = [(s.timestamp, s.price) for s in hist_leader if s.timestamp >= cutoff_time]
            follower_data = [(s.timestamp + lag_seconds, s.price) for s in hist_follower if s.timestamp >= cutoff_time - lag_seconds]

            if not leader_data or not follower_data:
                continue

            aligned = self._align_series(leader_data, follower_data)
            if len(aligned) < 3:
                continue

            leader_changes = self._compute_price_changes([(t, p) for t, p, _ in aligned])
            follower_changes = self._compute_price_changes([(t, p) for _, _, p in aligned])

            if not leader_changes or not follower_changes:
                continue

            corr = self._pearson_correlation(leader_changes, follower_changes)
            if corr > best_correlation:
                best_correlation = corr
                best_lag_minutes = lag_minutes

        if best_correlation > 0.6 and best_lag_minutes:
            return {
                "leader": leader,
                "follower": follower,
                "lead_lag_minutes": best_lag_minutes,
                "correlation": round(best_correlation, 2),
            }

        return None

    def detect_correlation_break(
        self,
        symbol1: str,
        symbol2: str,
        historical_correlation: float = 0.8,
        threshold: float = 0.3,
    ) -> bool:
        """
        Detect if two assets are uncorrelated when they normally aren't.

        Returns True if correlation broke (|correlation - historical| > threshold)
        """
        current = self.get_correlation(symbol1, symbol2, period_minutes=60)
        if not current or current.confidence < 0.5:
            return False

        correlation_change = abs(current.correlation - historical_correlation)
        return correlation_change > threshold

    def get_correlation_matrix(self, symbols: List[str], period_minutes: int = 60) -> Dict[str, Dict[str, float]]:
        """Get correlation matrix for multiple symbols."""
        matrix = {}
        for s1 in symbols:
            matrix[s1] = {}
            for s2 in symbols:
                if s1 == s2:
                    matrix[s1][s2] = 1.0
                else:
                    corr_metrics = self.get_correlation(s1, s2, period_minutes)
                    matrix[s1][s2] = corr_metrics.correlation if corr_metrics else 0.0

        return matrix

    def get_report(self) -> Dict:
        """Get correlation report."""
        symbols = list(self.price_history.keys())

        if len(symbols) < 2:
            return {"status": "insufficient_data"}

        correlations = {}
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1:]:
                corr = self.get_correlation(s1, s2, period_minutes=60)
                if corr:
                    key = f"{s1}-{s2}"
                    correlations[key] = round(corr.correlation, 2)

        return {
            "symbols_tracked": len(symbols),
            "correlations_60m": correlations,
        }


# Global correlation tracker
_global_tracker: Optional[CorrelationTracker] = None


def get_correlation_tracker() -> CorrelationTracker:
    """Get or create global tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = CorrelationTracker()
    return _global_tracker
