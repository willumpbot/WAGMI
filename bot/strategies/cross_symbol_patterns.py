"""
Cross-symbol pattern memory: detects lead-lag relationships.
E.g., "When BTC drops 3% in 1h, SOL tends to drop 5% in the next 2h"

Tracks price movements across symbols to detect correlated movements
where one symbol consistently leads another. These patterns are fed
into the LLM context so it can make more aggressive, informed decisions
when a confirmed lead-lag signal fires.
"""
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("bot.patterns")


@dataclass
class PriceMove:
    symbol: str
    timestamp: float
    price: float
    pct_change_1h: float  # % change over last hour


@dataclass
class LeadLagPattern:
    leader: str         # Symbol that moved first
    follower: str       # Symbol that followed
    leader_move_pct: float  # Leader's move size
    follower_move_pct: float  # Follower's typical response
    avg_lag_minutes: float   # Average delay
    occurrences: int = 0
    wins: int = 0       # Times the pattern held


class CrossSymbolTracker:
    """Tracks price movements across symbols to detect lead-lag patterns."""

    def __init__(self, lookback_hours: int = 4):
        self.lookback_hours = lookback_hours
        # Recent price snapshots per symbol: deque of (timestamp, price)
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=240))  # 4h at 1min
        # Detected significant moves
        self.recent_moves: deque = deque(maxlen=100)
        # Confirmed lead-lag patterns
        self.patterns: Dict[str, LeadLagPattern] = {}
        # Pending moves waiting for followers
        self._pending_leaders: deque = deque(maxlen=50)

    def record_price(self, symbol: str, price: float, timestamp: float = None):
        """Record a price tick for a symbol."""
        ts = timestamp or time.time()
        self.price_history[symbol].append((ts, price))

        # Check for significant move (> 1.5% in last hour)
        pct_1h = self._compute_pct_change(symbol, 3600)  # 1 hour
        if abs(pct_1h) >= 1.5:
            move = PriceMove(symbol=symbol, timestamp=ts, price=price, pct_change_1h=pct_1h)
            self._check_for_pattern(move)
            self._pending_leaders.append(move)

    def _compute_pct_change(self, symbol: str, seconds: int) -> float:
        """Compute % price change over the given time window."""
        history = self.price_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0
        current_ts, current_price = history[-1]
        target_ts = current_ts - seconds
        # Find the closest price to target_ts
        for ts, price in history:
            if ts >= target_ts:
                if price == 0:
                    return 0.0
                return (current_price - price) / price * 100
        return 0.0

    def _check_for_pattern(self, follower_move: PriceMove):
        """Check if this move follows a leader move (different symbol)."""
        for leader in self._pending_leaders:
            if leader.symbol == follower_move.symbol:
                continue
            # Leader must have moved first (within 2h window)
            lag = follower_move.timestamp - leader.timestamp
            if lag < 60 or lag > 7200:  # Between 1 min and 2 hours
                continue
            # Both must move in same direction
            if (leader.pct_change_1h > 0) != (follower_move.pct_change_1h > 0):
                continue
            # Record pattern
            key = f"{leader.symbol}->{follower_move.symbol}"
            if key not in self.patterns:
                self.patterns[key] = LeadLagPattern(
                    leader=leader.symbol,
                    follower=follower_move.symbol,
                    leader_move_pct=leader.pct_change_1h,
                    follower_move_pct=follower_move.pct_change_1h,
                    avg_lag_minutes=lag / 60,
                )
            pattern = self.patterns[key]
            pattern.occurrences += 1
            # Update running averages
            n = pattern.occurrences
            pattern.leader_move_pct = (pattern.leader_move_pct * (n - 1) + leader.pct_change_1h) / n
            pattern.follower_move_pct = (pattern.follower_move_pct * (n - 1) + follower_move.pct_change_1h) / n
            pattern.avg_lag_minutes = (pattern.avg_lag_minutes * (n - 1) + lag / 60) / n

    def get_active_signals(self) -> List[Dict]:
        """Get current lead-lag signals: a leader just moved, follower hasn't yet."""
        signals = []
        now = time.time()
        for leader in self._pending_leaders:
            age_min = (now - leader.timestamp) / 60
            if age_min > 120:  # Too old
                continue
            # Check each confirmed pattern for this leader
            for key, pattern in self.patterns.items():
                if pattern.leader != leader.symbol:
                    continue
                if pattern.occurrences < 3:  # Need at least 3 observations
                    continue
                # Check if follower has already moved
                follower_change = self._compute_pct_change(pattern.follower, 3600)
                if abs(follower_change) < 0.5:  # Follower hasn't moved yet
                    signals.append({
                        "leader": leader.symbol,
                        "follower": pattern.follower,
                        "leader_move": round(leader.pct_change_1h, 2),
                        "expected_follower_move": round(pattern.follower_move_pct, 2),
                        "avg_lag_min": round(pattern.avg_lag_minutes, 1),
                        "occurrences": pattern.occurrences,
                        "confidence": min(0.9, pattern.occurrences * 0.15),  # 3 obs = 0.45, 6 = 0.9
                    })
        return signals

    def get_pattern_summary(self) -> Dict:
        """Get summary of all detected patterns for LLM injection."""
        confirmed = {}
        for key, p in self.patterns.items():
            if p.occurrences >= 3:
                confirmed[key] = {
                    "leader": p.leader,
                    "follower": p.follower,
                    "leader_avg_move": round(p.leader_move_pct, 2),
                    "follower_avg_move": round(p.follower_move_pct, 2),
                    "avg_lag_min": round(p.avg_lag_minutes, 1),
                    "observations": p.occurrences,
                }
        return confirmed
