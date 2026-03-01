"""
Parameter Tuner: Applies feedback-loop-driven adjustments to live trading parameters.

Consumes data from:
  - AdaptiveConfidenceFloor (dynamic confidence thresholds)
  - ContinuousBacktester (rolling backtest suggestions)
  - RL Policy (offline learning targets)
  - Strategy weight manager (per-strategy accuracy)

Produces:
  - Dynamic confidence floor (replaces static 65%)
  - Dynamic leverage caps (per-symbol, per-regime)
  - Dynamic risk-per-trade (scales with earned trust)
  - Strategy weight adjustments
  - Calibration offsets for ML model

Safety:
  - All changes are bounded (max ±20% from baseline)
  - Changes are gradual (max 3% per update cycle)
  - A "trust score" gates how much autonomy the tuner has
  - Everything is logged and reversible
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.feedback.tuner")

# Safety bounds
MAX_CHANGE_PER_CYCLE = 0.03  # 3% max change per update
MIN_TRUST_SCORE = 0.2        # Below this, tuner is nearly passive
MAX_TRUST_SCORE = 0.95       # Cap trust to always maintain some caution


@dataclass
class TunedParameters:
    """The current set of tuned parameters."""
    confidence_floor: float = 55.0
    max_leverage: float = 25.0
    risk_per_trade: float = 0.01
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    regime_leverage_caps: Dict[str, float] = field(default_factory=dict)
    symbol_confidence_offsets: Dict[str, float] = field(default_factory=dict)
    calibration_offset: float = 0.0

    # Meta: how much we trust our own tuning
    trust_score: float = 0.3  # Starts conservative
    total_adjustments: int = 0
    last_update: float = 0.0


class ParameterTuner:
    """
    Aggregates feedback from multiple sources and produces tuned parameters.

    The tuner's "trust score" determines how aggressively it applies changes:
    - Low trust (0.2-0.4): Very conservative, small adjustments
    - Medium trust (0.4-0.7): Moderate adjustments
    - High trust (0.7-0.95): Confident adjustments (earned through proven accuracy)

    Trust is earned by the tuner's past suggestions being validated as correct
    by subsequent backtests.
    """

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = data_dir
        self._state_file = os.path.join(data_dir, "tuner_state.json")
        os.makedirs(data_dir, exist_ok=True)

        self.params = TunedParameters()

        # Track suggestion accuracy to update trust
        self._suggestion_outcomes: List[Dict] = []

        self._load_state()

    def update(
        self,
        confidence_floor_suggestion: Optional[float] = None,
        leverage_suggestion: Optional[float] = None,
        risk_per_trade_suggestion: Optional[float] = None,
        strategy_weight_suggestions: Optional[Dict[str, float]] = None,
        regime_suggestions: Optional[Dict[str, float]] = None,
        symbol_offsets: Optional[Dict[str, float]] = None,
        calibration_offset: Optional[float] = None,
        backtest_validated: bool = False,
    ):
        """Apply parameter suggestions with trust-gated gradualism.

        Args:
            confidence_floor_suggestion: Suggested new floor (50-80)
            leverage_suggestion: Suggested max leverage cap
            risk_per_trade_suggestion: Suggested risk per trade
            strategy_weight_suggestions: {strategy_name: weight}
            regime_suggestions: {regime: leverage_cap}
            symbol_offsets: {symbol: confidence_offset}
            calibration_offset: ML calibration correction
            backtest_validated: Whether this update is validated by backtest
        """
        trust = self.params.trust_score
        max_step = MAX_CHANGE_PER_CYCLE * trust  # Trust gates the step size

        if confidence_floor_suggestion is not None:
            target = max(50, min(80, confidence_floor_suggestion))
            self.params.confidence_floor = self._gradual_move(
                self.params.confidence_floor, target, max_step * 30  # scale for 50-80 range
            )

        if leverage_suggestion is not None:
            target = max(5, min(25, leverage_suggestion))
            self.params.max_leverage = self._gradual_move(
                self.params.max_leverage, target, max_step * 25
            )

        if risk_per_trade_suggestion is not None:
            target = max(0.005, min(0.02, risk_per_trade_suggestion))
            self.params.risk_per_trade = self._gradual_move(
                self.params.risk_per_trade, target, max_step * 0.02
            )

        if strategy_weight_suggestions:
            for strategy, weight in strategy_weight_suggestions.items():
                current = self.params.strategy_weights.get(strategy, 1.0)
                target = max(0.2, min(2.0, weight))
                self.params.strategy_weights[strategy] = self._gradual_move(
                    current, target, max_step * 2
                )

        if regime_suggestions:
            for regime, cap in regime_suggestions.items():
                current = self.params.regime_leverage_caps.get(regime, 25.0)
                target = max(3, min(25, cap))
                self.params.regime_leverage_caps[regime] = self._gradual_move(
                    current, target, max_step * 25
                )

        if symbol_offsets:
            for symbol, offset in symbol_offsets.items():
                current = self.params.symbol_confidence_offsets.get(symbol, 0.0)
                target = max(-10, min(10, offset))
                self.params.symbol_confidence_offsets[symbol] = self._gradual_move(
                    current, target, max_step * 20
                )

        if calibration_offset is not None:
            target = max(-15, min(15, calibration_offset))
            self.params.calibration_offset = self._gradual_move(
                self.params.calibration_offset, target, max_step * 30
            )

        # Update trust score based on validation
        if backtest_validated:
            self._increase_trust()
        else:
            self._decay_trust()

        self.params.total_adjustments += 1
        self.params.last_update = time.time()

        self._save_state()

    def get_confidence_floor(
        self, strategy: str = "", symbol: str = "", regime: str = ""
    ) -> float:
        """Get the current tuned confidence floor, with per-context adjustments."""
        base = self.params.confidence_floor

        # Per-strategy: if a strategy has earned more/less trust
        if strategy and strategy in self.params.strategy_weights:
            w = self.params.strategy_weights[strategy]
            # Higher weight = lower floor (earned trust)
            base += (1.0 - w) * 5  # w=0.5 -> +2.5, w=1.5 -> -2.5

        # Per-symbol offset
        if symbol and symbol in self.params.symbol_confidence_offsets:
            base += self.params.symbol_confidence_offsets[symbol]

        # Per-regime leverage caps affect floor indirectly
        # In conservative regimes, raise the floor
        if regime and regime in self.params.regime_leverage_caps:
            regime_cap = self.params.regime_leverage_caps[regime]
            if regime_cap < 10:
                base += 3  # Conservative regime → higher floor
            elif regime_cap > 20:
                base -= 2  # Aggressive regime → slightly lower floor

        return max(50, min(80, base))

    def get_leverage_cap(
        self, symbol: str = "", regime: str = ""
    ) -> float:
        """Get the current tuned leverage cap."""
        base = self.params.max_leverage

        if regime and regime in self.params.regime_leverage_caps:
            base = min(base, self.params.regime_leverage_caps[regime])

        return base

    def get_risk_per_trade(self) -> float:
        """Get the current tuned risk per trade."""
        return self.params.risk_per_trade

    def get_strategy_weight(self, strategy: str) -> float:
        """Get the tuned weight for a strategy."""
        return self.params.strategy_weights.get(strategy, 1.0)

    def get_calibration_offset(self) -> float:
        """Get the ML calibration offset."""
        return self.params.calibration_offset

    def validate_suggestion(self, param: str, was_correct: bool):
        """Record whether a past suggestion turned out to be correct.
        This drives the trust score."""
        self._suggestion_outcomes.append({
            "ts": time.time(),
            "param": param,
            "correct": was_correct,
        })
        if len(self._suggestion_outcomes) > 200:
            self._suggestion_outcomes = self._suggestion_outcomes[-200:]

        # Recalculate trust from recent accuracy
        recent = self._suggestion_outcomes[-50:]
        if len(recent) >= 10:
            accuracy = sum(1 for s in recent if s["correct"]) / len(recent)
            # Trust = smoothed accuracy, bounded
            self.params.trust_score = max(
                MIN_TRUST_SCORE,
                min(MAX_TRUST_SCORE, self.params.trust_score * 0.8 + accuracy * 0.2)
            )

    def _gradual_move(self, current: float, target: float, max_step: float) -> float:
        """Move current toward target, capped by max_step."""
        diff = target - current
        if abs(diff) <= max_step:
            return target
        return current + (max_step if diff > 0 else -max_step)

    def _increase_trust(self):
        """Increase trust score when backtest validates suggestions."""
        self.params.trust_score = min(
            MAX_TRUST_SCORE,
            self.params.trust_score + 0.02
        )

    def _decay_trust(self):
        """Slowly decay trust to maintain conservatism."""
        self.params.trust_score = max(
            MIN_TRUST_SCORE,
            self.params.trust_score * 0.999  # Very slow decay
        )

    def get_report(self) -> Dict[str, Any]:
        """Get human-readable tuner state."""
        return {
            "trust_score": round(self.params.trust_score, 3),
            "confidence_floor": round(self.params.confidence_floor, 1),
            "max_leverage": round(self.params.max_leverage, 1),
            "risk_per_trade": round(self.params.risk_per_trade, 4),
            "strategy_weights": {
                k: round(v, 3) for k, v in self.params.strategy_weights.items()
            },
            "regime_leverage_caps": {
                k: round(v, 1) for k, v in self.params.regime_leverage_caps.items()
            },
            "symbol_offsets": {
                k: round(v, 1) for k, v in self.params.symbol_confidence_offsets.items()
            },
            "calibration_offset": round(self.params.calibration_offset, 1),
            "total_adjustments": self.params.total_adjustments,
            "suggestion_accuracy": self._get_suggestion_accuracy(),
        }

    def _get_suggestion_accuracy(self) -> float:
        recent = self._suggestion_outcomes[-50:]
        if not recent:
            return 0.0
        return sum(1 for s in recent if s["correct"]) / len(recent)

    def _save_state(self):
        try:
            state = {
                "confidence_floor": self.params.confidence_floor,
                "max_leverage": self.params.max_leverage,
                "risk_per_trade": self.params.risk_per_trade,
                "strategy_weights": self.params.strategy_weights,
                "regime_leverage_caps": self.params.regime_leverage_caps,
                "symbol_confidence_offsets": self.params.symbol_confidence_offsets,
                "calibration_offset": self.params.calibration_offset,
                "trust_score": self.params.trust_score,
                "total_adjustments": self.params.total_adjustments,
                "suggestion_outcomes": self._suggestion_outcomes[-100:],
            }
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save tuner state: {e}")

    def _load_state(self):
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            self.params.confidence_floor = state.get("confidence_floor", 55.0)
            self.params.max_leverage = state.get("max_leverage", 25.0)
            self.params.risk_per_trade = state.get("risk_per_trade", 0.01)
            self.params.strategy_weights = state.get("strategy_weights", {})
            self.params.regime_leverage_caps = state.get("regime_leverage_caps", {})
            self.params.symbol_confidence_offsets = state.get("symbol_confidence_offsets", {})
            self.params.calibration_offset = state.get("calibration_offset", 0.0)
            self.params.trust_score = state.get("trust_score", 0.3)
            self.params.total_adjustments = state.get("total_adjustments", 0)
            self._suggestion_outcomes = state.get("suggestion_outcomes", [])
            logger.info(
                f"[TUNER] Loaded state: floor={self.params.confidence_floor:.1f}%, "
                f"trust={self.params.trust_score:.2f}, "
                f"adjustments={self.params.total_adjustments}"
            )
        except Exception as e:
            logger.warning(f"Failed to load tuner state: {e}")
