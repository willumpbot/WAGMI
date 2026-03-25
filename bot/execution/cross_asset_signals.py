"""
Cross-Asset Signal Amplification Module.

Detects lead-lag relationships between correlated assets and generates
amplification signals when a leader asset moves but followers haven't yet.

Known relationships:
  BTC -> HYPE  (15-30 min lag, 0.70 correlation)
  BTC -> SOL   (10-20 min lag, 0.80 correlation)
  SOL -> HYPE  (5-15 min lag, 0.65 correlation)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AmplificationSignal:
    """Signal produced when a leader asset moves and a follower hasn't yet."""

    leader: str  # e.g. "BTC"
    follower: str  # e.g. "HYPE"
    leader_move_pct: float  # signed move in % (positive = up)
    lag_minutes: int  # expected lag in minutes
    confidence_boost: float  # 0-20 extra confidence to add
    rationale: str  # human-readable explanation


@dataclass
class _PriceTick:
    """Internal: a single observed price."""

    price: float
    timestamp: datetime


@dataclass
class LeadLagPair:
    """Defines a known lead-lag relationship between two assets."""

    leader: str
    follower: str
    min_lag_minutes: int
    max_lag_minutes: int
    correlation: float  # historical correlation strength 0-1


# ---------------------------------------------------------------------------
# Default known pairs
# ---------------------------------------------------------------------------

DEFAULT_PAIRS: List[LeadLagPair] = [
    LeadLagPair(leader="BTC", follower="HYPE", min_lag_minutes=15, max_lag_minutes=30, correlation=0.70),
    LeadLagPair(leader="BTC", follower="SOL", min_lag_minutes=10, max_lag_minutes=20, correlation=0.80),
    LeadLagPair(leader="SOL", follower="HYPE", min_lag_minutes=5, max_lag_minutes=15, correlation=0.65),
]

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

# Maximum age of price data before it is considered stale.
_STALE_THRESHOLD = timedelta(minutes=30)

# How much history to keep per symbol (at most).
_MAX_TICKS = 500

# Minimum leader move (%) to trigger amplification.
_MIN_LEADER_MOVE_PCT = 0.5

# Window over which the leader move is measured.
_LEADER_WINDOW = timedelta(minutes=15)

# Maximum follower move that still counts as "hasn't followed yet".
_MAX_FOLLOWER_MOVE_PCT = 0.25


class CrossAssetAmplifier:
    """Detect cross-asset lead-lag signals and amplify follower trades."""

    def __init__(
        self,
        pairs: Optional[List[LeadLagPair]] = None,
        min_leader_move_pct: float = _MIN_LEADER_MOVE_PCT,
        leader_window: timedelta = _LEADER_WINDOW,
        stale_threshold: timedelta = _STALE_THRESHOLD,
        max_follower_move_pct: float = _MAX_FOLLOWER_MOVE_PCT,
    ) -> None:
        self.pairs = pairs if pairs is not None else list(DEFAULT_PAIRS)
        self.min_leader_move_pct = min_leader_move_pct
        self.leader_window = leader_window
        self.stale_threshold = stale_threshold
        self.max_follower_move_pct = max_follower_move_pct

        # symbol -> deque of _PriceTick (most recent last)
        self._prices: Dict[str, deque] = {}

        # Build indexes for fast lookup
        self._leader_to_pairs: Dict[str, List[LeadLagPair]] = {}
        self._follower_to_pairs: Dict[str, List[LeadLagPair]] = {}
        for pair in self.pairs:
            self._leader_to_pairs.setdefault(pair.leader, []).append(pair)
            self._follower_to_pairs.setdefault(pair.follower, []).append(pair)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_price(self, symbol: str, price: float, timestamp: Optional[datetime] = None) -> None:
        """Feed a new price observation for *symbol*."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=_MAX_TICKS)
        self._prices[symbol].append(_PriceTick(price=price, timestamp=timestamp))

    def check_amplification(
        self,
        symbol: str,
        side: str,
        now: Optional[datetime] = None,
    ) -> Optional[AmplificationSignal]:
        """Check whether a leader asset supports a trade on *symbol* in *side*.

        Returns an ``AmplificationSignal`` if a leader has moved significantly
        in the direction of *side* and *symbol* has not yet followed, or
        ``None`` if no amplification is warranted.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        pairs = self._follower_to_pairs.get(symbol)
        if not pairs:
            return None

        best: Optional[AmplificationSignal] = None

        for pair in pairs:
            sig = self._evaluate_pair(pair, side, now)
            if sig is None:
                continue
            # Keep the strongest signal
            if best is None or sig.confidence_boost > best.confidence_boost:
                best = sig

        return best

    def get_leader_momentum(self, symbol: str, now: Optional[datetime] = None) -> Dict:
        """Return a summary of what each leader of *symbol* is doing.

        Returns a dict keyed by leader symbol with move_pct and freshness.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        pairs = self._follower_to_pairs.get(symbol)
        if not pairs:
            return {}

        result: Dict = {}
        for pair in pairs:
            move = self._recent_move(pair.leader, now)
            if move is None:
                result[pair.leader] = {"move_pct": None, "stale": True, "correlation": pair.correlation}
            else:
                move_pct, _ = move
                result[pair.leader] = {
                    "move_pct": round(move_pct, 4),
                    "stale": False,
                    "correlation": pair.correlation,
                    "expected_lag_min": pair.min_lag_minutes,
                    "expected_lag_max": pair.max_lag_minutes,
                }
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_pair(
        self, pair: LeadLagPair, side: str, now: datetime
    ) -> Optional[AmplificationSignal]:
        """Evaluate a single lead-lag pair for amplification."""
        leader_move = self._recent_move(pair.leader, now)
        if leader_move is None:
            return None

        leader_move_pct, leader_age_min = leader_move

        # Leader move must exceed threshold
        if abs(leader_move_pct) < self.min_leader_move_pct:
            return None

        # Leader direction must agree with requested side
        leader_bullish = leader_move_pct > 0
        side_upper = side.upper()
        if side_upper == "BUY" and not leader_bullish:
            return None
        if side_upper == "SELL" and leader_bullish:
            return None

        # Follower should NOT have moved significantly yet
        follower_move = self._recent_move(pair.follower, now)
        if follower_move is not None:
            follower_move_pct, _ = follower_move
            # If follower already moved in the same direction, opportunity may be gone
            if side_upper == "BUY" and follower_move_pct > self.max_follower_move_pct:
                return None
            if side_upper == "SELL" and follower_move_pct < -self.max_follower_move_pct:
                return None

        # Compute confidence boost: scale by |leader_move|, correlation, capped at 20
        raw_boost = abs(leader_move_pct) * pair.correlation * 10
        confidence_boost = min(round(raw_boost, 2), 20.0)

        direction = "UP" if leader_bullish else "DOWN"
        side_word = "LONG" if side_upper == "BUY" else "SHORT"

        rationale = (
            f"{pair.leader} broke out {leader_move_pct:+.2f}% ({direction}) in the last "
            f"{int(leader_age_min)} min, {pair.follower} hasn't followed yet "
            f"(expected lag {pair.min_lag_minutes}-{pair.max_lag_minutes} min, "
            f"corr {pair.correlation:.2f}) -> preposition {pair.follower} {side_word}"
        )

        return AmplificationSignal(
            leader=pair.leader,
            follower=pair.follower,
            leader_move_pct=round(leader_move_pct, 4),
            lag_minutes=pair.min_lag_minutes,
            confidence_boost=confidence_boost,
            rationale=rationale,
        )

    def _recent_move(
        self, symbol: str, now: datetime
    ) -> Optional[Tuple[float, float]]:
        """Return (move_pct, age_minutes) for *symbol* over the leader window.

        Returns ``None`` when there is insufficient or stale data.
        """
        ticks = self._prices.get(symbol)
        if not ticks or len(ticks) < 2:
            return None

        latest = ticks[-1]
        # Check staleness
        age = now - latest.timestamp
        if age > self.stale_threshold:
            return None

        # Find the oldest tick within the leader window
        window_start = now - self.leader_window
        baseline: Optional[_PriceTick] = None
        for tick in ticks:
            if tick.timestamp >= window_start:
                baseline = tick
                break

        if baseline is None or baseline.price <= 0:
            return None

        move_pct = ((latest.price - baseline.price) / baseline.price) * 100
        age_minutes = (now - baseline.timestamp).total_seconds() / 60.0
        return (move_pct, age_minutes)
