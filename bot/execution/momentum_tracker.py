"""
Momentum Tracker: tracks win/loss streaks per symbol for sizing adjustments.

From 2,172-signal analysis:
- After 1 win: next signal has 67% WR (vs 50% baseline)
- After 2 wins: 75% WR
- After 1 loss: 34% WR
- After 2 losses: 29% WR

The spread (75% vs 29%) is the strongest single predictor in the system.
This module tracks streaks and provides sizing multipliers.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("bot.execution.momentum_tracker")

# Sizing multipliers derived from 2,172-signal analysis
MOMENTUM_MULTIPLIERS = {
    2: 1.3,    # After 2+ consecutive wins: 75% WR -> size up 30%
    1: 1.15,   # After 1 win: 67% WR -> size up 15%
    0: 1.0,    # No streak: baseline
    -1: 0.6,   # After 1 loss: 34% WR -> reduce 40%
    -2: 0.35,  # After 2+ losses: 29% WR -> reduce 65%
}


class MomentumTracker:
    """Tracks win/loss momentum per symbol for data-driven sizing."""

    def __init__(self, state_path: str = "data/momentum_state.json"):
        self._state_path = state_path
        # streak > 0 = consecutive wins, < 0 = consecutive losses
        self._streaks: Dict[str, int] = {}
        self._last_outcome: Dict[str, bool] = {}
        self._load_state()

    def _load_state(self):
        try:
            # Don't load state if file doesn't exist or in test environments
            import sys
            if "pytest" in sys.modules:
                return
            if os.path.exists(self._state_path):
                with open(self._state_path) as f:
                    state = json.load(f)
                self._streaks = state.get("streaks", {})
                self._last_outcome = {k: v for k, v in state.get("last_outcome", {}).items()}
        except Exception as e:
            logger.debug(f"Momentum state load error: {e}")

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(self._state_path, "w") as f:
                json.dump({
                    "streaks": self._streaks,
                    "last_outcome": self._last_outcome,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }, f)
        except Exception as e:
            logger.debug(f"Momentum state save error: {e}")

    def record_outcome(self, symbol: str, won: bool):
        """Record a trade outcome for streak tracking."""
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        current = self._streaks.get(sym, 0)

        if won:
            self._streaks[sym] = max(1, current + 1) if current >= 0 else 1
        else:
            self._streaks[sym] = min(-1, current - 1) if current <= 0 else -1

        self._last_outcome[sym] = won
        self._save_state()

        logger.info(
            f"[MOMENTUM] {sym}: {'WIN' if won else 'LOSS'} -> "
            f"streak={self._streaks[sym]:+d} "
            f"-> size_mult={self.get_multiplier(symbol):.2f}x"
        )

    def get_multiplier(self, symbol: str) -> float:
        """Get sizing multiplier based on current streak.

        Returns 0.35x to 1.3x based on momentum state.
        """
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        streak = self._streaks.get(sym, 0)

        # Clamp to lookup range
        if streak >= 2:
            return MOMENTUM_MULTIPLIERS[2]
        elif streak == 1:
            return MOMENTUM_MULTIPLIERS[1]
        elif streak == 0:
            return MOMENTUM_MULTIPLIERS[0]
        elif streak == -1:
            return MOMENTUM_MULTIPLIERS[-1]
        else:  # -2 or worse
            return MOMENTUM_MULTIPLIERS[-2]

    def get_streak(self, symbol: str) -> int:
        """Get current streak for a symbol. Positive = wins, negative = losses."""
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        return self._streaks.get(sym, 0)

    def should_skip(self, symbol: str) -> bool:
        """Should we skip this symbol due to extreme losing streak?

        After 3+ consecutive losses: 29% WR is below breakeven for any R:R.
        Disabled by MOMENTUM_SKIP_ENABLED=false env var for testing.
        """
        if os.getenv("MOMENTUM_SKIP_ENABLED", "true").lower() not in ("1", "true", "yes"):
            return False
        return self.get_streak(symbol) <= -3

    def get_all_streaks(self) -> Dict[str, int]:
        """Get all symbol streaks for monitoring."""
        return dict(self._streaks)


# Module-level singleton
_tracker: Optional[MomentumTracker] = None


def get_momentum_tracker() -> MomentumTracker:
    global _tracker
    if _tracker is None:
        _tracker = MomentumTracker()
    return _tracker


def reset_momentum_tracker():
    """Reset singleton (for testing)."""
    global _tracker
    _tracker = None
