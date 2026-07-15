"""
Hold-Time Rules: Dynamic minimum hold times per regime based on live performance.

Data shows: <2h trades = 29% WR (garbage), >6h = 55-73% WR (gold).
This module learns optimal hold times per regime and blocks early exits below them.

Structure:
  - Track win/loss rates at different hold time buckets
  - Per regime: compute minimum hold time that achieves decent WR
  - On early exit/trailing stop: check hold time against min, veto if below
  - Gradualism: min hold time rises/falls slowly (max 5 min change per trade)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.feedback.hold_time_rules")

# Hold time buckets: classify each trade by its duration
HOLD_TIME_BUCKETS = [
    (0, 0.5),      # < 30 min — noise trades
    (0.5, 1),      # 30m - 1h
    (1, 2),        # 1-2h
    (2, 4),        # 2-4h
    (4, 6),        # 4-6h
    (6, 12),       # 6-12h — proven profitable
    (12, 24),      # 12-24h
    (24, 999),     # > 24h
]


@dataclass
class HoldTimeBucket:
    """Track outcomes for a specific hold time range."""
    low_hours: float
    high_hours: float
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.5

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total if self.total > 0 else 0.0

    def record_trade(self, win: bool, pnl: float):
        """Record a trade in this bucket."""
        self.losses += 1 if not win else 0
        self.wins += 1 if win else 0
        self.total_pnl += pnl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "low_hours": self.low_hours,
            "high_hours": self.high_hours,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "HoldTimeBucket":
        bucket = HoldTimeBucket(data["low_hours"], data["high_hours"])
        bucket.wins = data.get("wins", 0)
        bucket.losses = data.get("losses", 0)
        bucket.total_pnl = data.get("total_pnl", 0.0)
        return bucket


class HoldTimeRuleManager:
    """Learns optimal minimum hold times per regime."""

    # Regimes to track
    KNOWN_REGIMES = [
        "trend", "ranging", "high_volatility", "panic", "unknown"
    ]

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "hold_time_rules_state.json"

        # Per-regime: list of hold-time buckets
        self.regime_buckets: Dict[str, list[HoldTimeBucket]] = {}
        self._init_buckets()

        # Computed minimum hold times per regime (in hours)
        # Defaults: be conservative, require longer holds.
        # MUST be initialized BEFORE _load() — _load() reads/updates
        # min_hold_hours (init-ordering fix 2026-07-15; swarm added the
        # min_hold_hours load path but left this assignment after _load()).
        self.min_hold_hours: Dict[str, float] = {
            "trend": 2.0,          # Trend trades need 2+ hours
            "ranging": 4.0,        # Ranging needs longer to avoid chop
            "high_volatility": 1.0,  # Vol can move fast
            "panic": 0.5,          # Panic can revert quickly
            "unknown": 2.0,        # Safe default
        }
        self._last_update: Dict[str, str] = {}  # Track when each regime was last updated

        self._load()

    def _init_buckets(self):
        """Initialize hold-time buckets for all regimes."""
        for regime in self.KNOWN_REGIMES:
            self.regime_buckets[regime] = [
                HoldTimeBucket(low, high) for low, high in HOLD_TIME_BUCKETS
            ]

    def _load(self):
        """Load persisted hold-time rules."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            for regime_name, regime_data in data.items():
                if regime_name in self.regime_buckets:
                    buckets = [HoldTimeBucket.from_dict(b) for b in regime_data.get("buckets", [])]
                    if buckets:
                        self.regime_buckets[regime_name] = buckets
                if regime_name in self.min_hold_hours:
                    self.min_hold_hours[regime_name] = regime_data.get("min_hold_hours", self.min_hold_hours[regime_name])
        except Exception as e:
            logger.warning(f"Failed to load hold-time rules: {e}")

    def _save(self):
        """Persist hold-time rules to disk."""
        try:
            data = {}
            for regime, buckets in self.regime_buckets.items():
                data[regime] = {
                    "buckets": [b.to_dict() for b in buckets],
                    "min_hold_hours": self.min_hold_hours.get(regime, 2.0),
                }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save hold-time rules: {e}")

    def record_trade(self, regime: str, hold_hours: float, win: bool, pnl: float):
        """Record a trade outcome binned by hold time and regime.

        Args:
            regime: Market regime (e.g., "trend", "ranging")
            hold_hours: How long the trade was held (in hours)
            win: True if profitable
            pnl: Realized P&L
        """
        regime = regime.lower().strip() or "unknown"
        if regime not in self.regime_buckets:
            regime = "unknown"

        # Find bucket and record
        for bucket in self.regime_buckets[regime]:
            if bucket.low_hours <= hold_hours < bucket.high_hours:
                bucket.record_trade(win, pnl)
                self._recompute_min_hold_hours(regime)
                self._save()
                return

        # If no bucket matched (hold_hours >= 999), use last bucket
        if self.regime_buckets[regime]:
            self.regime_buckets[regime][-1].record_trade(win, pnl)
            self._recompute_min_hold_hours(regime)
            self._save()

    def _recompute_min_hold_hours(self, regime: str):
        """Recompute minimum hold hours for a regime based on WR by bucket.

        Logic:
        - Find the FIRST bucket with WR >= 50% (breakeven)
        - Use the low_hours of that bucket as the minimum hold time
        - Hard bounds: 0.5 (min) to 12 (max)
        - Gradualism: change by max 1.0 hour per recompute
        """
        buckets = self.regime_buckets.get(regime, [])
        if not buckets:
            return

        # Find first bucket with WR >= 50%
        profitable_threshold = 0.50
        for bucket in buckets:
            if bucket.total >= 5 and bucket.win_rate >= profitable_threshold:
                # Use this bucket's low_hours as the minimum
                new_min = bucket.low_hours
                break
        else:
            # No bucket with good WR, use conservative default
            new_min = self.min_hold_hours.get(regime, 2.0)

        # Gradualism: cap change at 1.0 hour per update
        old_min = self.min_hold_hours.get(regime, 2.0)
        new_min = old_min + max(-1.0, min(1.0, new_min - old_min))

        # Hard bounds
        new_min = max(0.5, min(12.0, new_min))

        if abs(new_min - old_min) > 0.05:  # Only log if change is significant
            logger.info(
                f"[HOLD-TIME] Regime '{regime}': min hold time adjusted from "
                f"{old_min:.1f}h to {new_min:.1f}h"
            )
            self.min_hold_hours[regime] = new_min
            self._last_update[regime] = datetime.now(timezone.utc).isoformat()

    def get_min_hold_hours(self, regime: str) -> float:
        """Get the minimum hold hours for a regime."""
        regime = (regime or "unknown").lower().strip()
        if regime not in self.min_hold_hours:
            regime = "unknown"
        return self.min_hold_hours.get(regime, 2.0)

    def should_block_early_exit(self, regime: str, hold_hours: float) -> bool:
        """Determine if an early exit should be blocked due to insufficient hold time.

        Returns True if the trade should NOT be exited early (hold time is too short).
        """
        min_hold = self.get_min_hold_hours(regime)
        should_block = hold_hours < min_hold
        if should_block:
            logger.debug(
                f"[HOLD-TIME] Blocking early exit: held {hold_hours:.1f}h < "
                f"min {min_hold:.1f}h (regime={regime})"
            )
        return should_block

    def get_regime_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary of hold-time performance per regime."""
        summary = {}
        for regime, buckets in self.regime_buckets.items():
            summary[regime] = {
                "min_hold_hours": self.min_hold_hours.get(regime, 2.0),
                "buckets": [
                    {
                        "range": f"{b.low_hours:.1f}-{b.high_hours:.1f}h",
                        "total_trades": b.total,
                        "win_rate": f"{b.win_rate*100:.1f}%",
                        "avg_pnl": f"{b.avg_pnl:+.3f}",
                    }
                    for b in buckets
                ],
            }
        return summary
