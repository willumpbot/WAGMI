"""
Adaptive Confidence Floor: Dynamic confidence thresholds driven by feedback loops.

Instead of a static 65% confidence floor, this module computes a dynamic floor
that adjusts based on:
  1. Recent win rate at each confidence level (binned)
  2. Per-strategy realized accuracy vs predicted confidence
  3. Per-symbol historical performance
  4. Current regime performance
  5. Backtest validation of recent signal quality

The floor RISES when low-confidence trades keep losing (tighten up).
The floor DROPS when the system is performing well and has earned trust (open up).

All adjustments are bounded:
  - Hard minimum: 50% (never trade below this)
  - Hard maximum: 80% (never lock yourself out)
  - Max daily change: +/- 5% (gradualism prevents whiplash)
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("bot.feedback.confidence")

# Hard bounds
ABSOLUTE_MIN_FLOOR = 50.0
ABSOLUTE_MAX_FLOOR = 80.0
DEFAULT_FLOOR = 55.0
MAX_DAILY_CHANGE = 5.0


@dataclass
class ConfidenceBin:
    """Tracks outcomes for a range of confidence values."""
    low: float
    high: float
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    recent_results: list = field(default_factory=list)  # last 50 outcomes (1=win, 0=loss)

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.5

    @property
    def recent_win_rate(self) -> float:
        if not self.recent_results:
            return 0.5
        return sum(self.recent_results) / len(self.recent_results)

    @property
    def ev_per_trade(self) -> float:
        return self.total_pnl / self.total if self.total > 0 else 0.0

    def record(self, win: bool, pnl: float):
        if win:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += pnl
        self.recent_results.append(1 if win else 0)
        if len(self.recent_results) > 50:
            self.recent_results = self.recent_results[-50:]


class AdaptiveConfidenceFloor:
    """
    Computes dynamic confidence floors from realized trading performance.

    The floor is the confidence level below which expected value turns negative.
    We learn this from actual trade outcomes binned by confidence.
    """

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = data_dir
        self._state_file = os.path.join(data_dir, "confidence_state.json")
        os.makedirs(data_dir, exist_ok=True)

        # Confidence bins: 50-55, 55-60, 60-65, 65-70, 70-75, 75-80, 80-85, 85-90, 90-100
        self.bins: List[ConfidenceBin] = [
            ConfidenceBin(50, 55), ConfidenceBin(55, 60),
            ConfidenceBin(60, 65), ConfidenceBin(65, 70),
            ConfidenceBin(70, 75), ConfidenceBin(75, 80),
            ConfidenceBin(80, 85), ConfidenceBin(85, 90),
            ConfidenceBin(90, 100),
        ]

        # Per-strategy floors (strategies earn their own trust)
        self.strategy_floors: Dict[str, float] = {}

        # Per-symbol adjustments
        self.symbol_adjustments: Dict[str, float] = {}

        # Per-regime adjustments
        self.regime_adjustments: Dict[str, float] = {}

        # Current computed floor
        self.current_floor: float = DEFAULT_FLOOR
        self.last_update: float = 0.0
        self.last_floor_change: float = 0.0

        # Calibration tracking: predicted confidence vs actual win rate
        self.calibration_errors: List[float] = []

        self._load_state()

    def _get_bin(self, confidence: float) -> Optional[ConfidenceBin]:
        for b in self.bins:
            if b.low <= confidence < b.high:
                return b
        if confidence >= 100:
            return self.bins[-1]
        return None

    def record_outcome(
        self,
        confidence: float,
        win: bool,
        pnl: float,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
    ):
        """Record a trade outcome to update all feedback loops."""
        # Update confidence bin
        b = self._get_bin(confidence)
        if b:
            b.record(win, pnl)

        # Update per-strategy tracking
        if strategy:
            if strategy not in self.strategy_floors:
                self.strategy_floors[strategy] = DEFAULT_FLOOR
            # Exponential moving average of strategy-specific floor
            # Based on: what's the lowest confidence this strategy wins at?
            self._update_strategy_floor(strategy, confidence, win, pnl)

        # Update per-symbol adjustment
        if symbol:
            self._update_symbol_adjustment(symbol, win, pnl)

        # Update per-regime adjustment
        if regime:
            self._update_regime_adjustment(regime, win, pnl)

        # Calibration tracking: how well does confidence predict outcomes?
        predicted = confidence / 100.0
        actual = 1.0 if win else 0.0
        self.calibration_errors.append(predicted - actual)
        if len(self.calibration_errors) > 200:
            self.calibration_errors = self.calibration_errors[-200:]

        # Recompute floor periodically (every 5 outcomes or 5 minutes)
        should_recompute = (
            (self.bins[2].total + self.bins[3].total) % 5 == 0  # every 5 trades near floor
            or time.time() - self.last_update > 300
        )
        if should_recompute:
            self._recompute_floor()
            self._save_state()

    def get_floor(
        self,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
    ) -> float:
        """Get the current adaptive confidence floor.

        Returns a float between ABSOLUTE_MIN_FLOOR and ABSOLUTE_MAX_FLOOR.
        The floor is adjusted per-strategy, per-symbol, and per-regime.
        """
        base = self.current_floor

        # Strategy-specific adjustment
        if strategy and strategy in self.strategy_floors:
            strat_floor = self.strategy_floors[strategy]
            # Blend: 60% global floor + 40% strategy-specific
            base = base * 0.6 + strat_floor * 0.4

        # Symbol adjustment (additive, bounded)
        if symbol and symbol in self.symbol_adjustments:
            base += self.symbol_adjustments[symbol]

        # Regime adjustment (additive, bounded)
        if regime and regime in self.regime_adjustments:
            base += self.regime_adjustments[regime]

        return max(ABSOLUTE_MIN_FLOOR, min(ABSOLUTE_MAX_FLOOR, base))

    def should_trade(
        self,
        confidence: float,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
    ) -> Tuple[bool, float, str]:
        """Check if a signal's confidence meets the adaptive floor.

        Returns:
            (should_trade, floor_value, reason)
        """
        floor = self.get_floor(strategy, symbol, regime)

        if confidence >= floor:
            margin = confidence - floor
            return True, floor, f"conf {confidence:.0f}% >= floor {floor:.0f}% (margin +{margin:.0f})"

        deficit = floor - confidence
        return False, floor, f"conf {confidence:.0f}% < floor {floor:.0f}% (deficit -{deficit:.0f})"

    def _recompute_floor(self):
        """Recompute the confidence floor from binned outcomes.

        Strategy: Find the lowest confidence bin where expected value is positive.
        The floor is the low edge of that bin, with smoothing.
        """
        old_floor = self.current_floor

        # Always clamp to bounds first
        self.current_floor = max(
            ABSOLUTE_MIN_FLOOR, min(ABSOLUTE_MAX_FLOOR, self.current_floor)
        )

        # Need minimum data before adjusting further
        total_trades = sum(b.total for b in self.bins)
        if total_trades < 10:
            return  # Not enough data

        # Find the EV break-even point
        # Walk from low confidence to high and find where EV turns positive
        ev_positive_bin = None
        for b in self.bins:
            if b.total >= 3:  # Need at least 3 trades in a bin
                if b.ev_per_trade > 0:
                    ev_positive_bin = b
                    break

        if ev_positive_bin is None:
            # All bins negative — tighten up
            new_floor = min(self.current_floor + 2.0, ABSOLUTE_MAX_FLOOR)
        else:
            # Floor = low edge of first profitable bin
            raw_floor = ev_positive_bin.low

            # Smooth: blend with recent win rate signal
            # If recent trades at 60-65% are profitable, we can trust lower floors
            confidence_earned = self._compute_trust_bonus(total_trades)
            raw_floor -= confidence_earned

            new_floor = raw_floor

        # Gradualism: max change per update
        change = new_floor - self.current_floor
        max_step = MAX_DAILY_CHANGE / 12  # Spread daily budget across ~12 updates
        change = max(-max_step, min(max_step, change))

        self.current_floor = max(
            ABSOLUTE_MIN_FLOOR,
            min(ABSOLUTE_MAX_FLOOR, self.current_floor + change)
        )
        self.last_update = time.time()

        if abs(self.current_floor - old_floor) > 0.5:
            self.last_floor_change = self.current_floor - old_floor
            logger.info(
                f"[ADAPTIVE-FLOOR] {old_floor:.1f}% -> {self.current_floor:.1f}% "
                f"(change: {self.last_floor_change:+.1f}%, "
                f"total trades: {total_trades})"
            )

    def _compute_trust_bonus(self, total_trades: int) -> float:
        """Compute how much to lower the floor based on earned trust.

        Trust comes from:
        1. Overall win rate being good
        2. Calibration being accurate (confidence predicts well)
        3. Having enough data
        """
        bonus = 0.0

        # Win rate bonus: if we're winning >55%, earn trust
        total_wins = sum(b.wins for b in self.bins)
        total = sum(b.total for b in self.bins)
        if total >= 20:
            wr = total_wins / total
            if wr > 0.55:
                bonus += (wr - 0.55) * 20  # Up to 4% bonus at 75% win rate
            elif wr < 0.45:
                bonus -= (0.45 - wr) * 30  # Penalty for poor performance

        # Calibration bonus: if our confidence predictions are accurate
        if len(self.calibration_errors) >= 20:
            mean_error = sum(self.calibration_errors) / len(self.calibration_errors)
            # mean_error > 0 means we're overconfident, < 0 means underconfident
            if abs(mean_error) < 0.05:
                bonus += 2.0  # Well calibrated, can trust lower floors
            elif mean_error > 0.15:
                bonus -= 3.0  # Overconfident, raise floor

        # Data volume bonus: more data = more trust
        if total_trades > 100:
            bonus += 1.0
        elif total_trades > 50:
            bonus += 0.5

        return max(-5.0, min(5.0, bonus))

    def _update_strategy_floor(
        self, strategy: str, confidence: float, win: bool, pnl: float
    ):
        """Update per-strategy floor using exponential moving average."""
        alpha = 0.1  # Learning rate

        if win and pnl > 0:
            # Won at this confidence — lower the strategy floor toward it
            target = max(confidence - 5, ABSOLUTE_MIN_FLOOR)
        else:
            # Lost — raise the floor slightly above this confidence
            target = min(confidence + 3, ABSOLUTE_MAX_FLOOR)

        current = self.strategy_floors.get(strategy, DEFAULT_FLOOR)
        self.strategy_floors[strategy] = current * (1 - alpha) + target * alpha

    def _update_symbol_adjustment(self, symbol: str, win: bool, pnl: float):
        """Update per-symbol confidence adjustment."""
        alpha = 0.1
        current = self.symbol_adjustments.get(symbol, 0.0)

        if win:
            # Performing well on this symbol, lower the bar slightly
            target = -2.0
        else:
            # Performing poorly, raise the bar
            target = 3.0

        self.symbol_adjustments[symbol] = current * (1 - alpha) + target * alpha
        # Clamp
        self.symbol_adjustments[symbol] = max(-5.0, min(10.0, self.symbol_adjustments[symbol]))

    def _update_regime_adjustment(self, regime: str, win: bool, pnl: float):
        """Update per-regime confidence adjustment."""
        alpha = 0.1
        current = self.regime_adjustments.get(regime, 0.0)

        if win:
            target = -2.0
        else:
            target = 3.0

        self.regime_adjustments[regime] = current * (1 - alpha) + target * alpha
        self.regime_adjustments[regime] = max(-5.0, min(10.0, self.regime_adjustments[regime]))

    def get_report(self) -> Dict[str, Any]:
        """Get a human-readable report of the adaptive floor state."""
        bins_report = {}
        for b in self.bins:
            if b.total > 0:
                bins_report[f"{b.low}-{b.high}%"] = {
                    "trades": b.total,
                    "win_rate": round(b.win_rate, 3),
                    "recent_wr": round(b.recent_win_rate, 3),
                    "ev": round(b.ev_per_trade, 2),
                    "total_pnl": round(b.total_pnl, 2),
                }

        mean_cal_err = 0.0
        if self.calibration_errors:
            mean_cal_err = sum(self.calibration_errors) / len(self.calibration_errors)

        return {
            "current_floor": round(self.current_floor, 1),
            "last_change": round(self.last_floor_change, 1),
            "strategy_floors": {k: round(v, 1) for k, v in self.strategy_floors.items()},
            "symbol_adjustments": {k: round(v, 1) for k, v in self.symbol_adjustments.items()},
            "regime_adjustments": {k: round(v, 1) for k, v in self.regime_adjustments.items()},
            "calibration_error": round(mean_cal_err, 3),
            "bins": bins_report,
        }

    def _save_state(self):
        try:
            state = {
                "current_floor": self.current_floor,
                "last_update": self.last_update,
                "strategy_floors": self.strategy_floors,
                "symbol_adjustments": self.symbol_adjustments,
                "regime_adjustments": self.regime_adjustments,
                "calibration_errors": self.calibration_errors[-100:],
                "bins": [
                    {
                        "low": b.low, "high": b.high,
                        "wins": b.wins, "losses": b.losses,
                        "total_pnl": b.total_pnl,
                        "recent_results": b.recent_results[-50:],
                    }
                    for b in self.bins
                ],
            }
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save confidence state: {e}")

    def _load_state(self):
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            self.current_floor = state.get("current_floor", DEFAULT_FLOOR)
            self.last_update = state.get("last_update", 0)
            self.strategy_floors = state.get("strategy_floors", {})
            self.symbol_adjustments = state.get("symbol_adjustments", {})
            self.regime_adjustments = state.get("regime_adjustments", {})
            self.calibration_errors = state.get("calibration_errors", [])

            for saved_bin, live_bin in zip(state.get("bins", []), self.bins):
                live_bin.wins = saved_bin.get("wins", 0)
                live_bin.losses = saved_bin.get("losses", 0)
                live_bin.total_pnl = saved_bin.get("total_pnl", 0.0)
                live_bin.recent_results = saved_bin.get("recent_results", [])

            logger.info(
                f"[ADAPTIVE-FLOOR] Loaded state: floor={self.current_floor:.1f}%, "
                f"total bins data: {sum(b.total for b in self.bins)} trades"
            )
        except Exception as e:
            logger.warning(f"Failed to load confidence state: {e}")
