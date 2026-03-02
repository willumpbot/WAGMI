"""
Regime Transition Detector.

Tracks regime history per symbol and detects transitions between regimes.
Transitions are high-alpha moments where the market character is shifting.

Usage:
    detector = RegimeTransitionDetector()
    result = detector.update("BTC/USDC:USDC", "trend")
    if result["transitioning"]:
        print(f"Regime shifting: {result['from']} -> {result['to']}")
"""

import logging
import os
from collections import defaultdict, deque
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.strategies.regime_detector")

# Number of recent regime classifications to track
_HISTORY_SIZE = 10
# Minimum confirmations before declaring a transition (env-overridable)
_MIN_CONFIRMATIONS = int(os.getenv("REGIME_MIN_CONFIRMATIONS", "3"))
# New regime must represent > this fraction of recent labels to confirm
_DOMINANCE_RATIO = 0.60


class RegimeTransitionDetector:
    """Detects regime transitions by tracking classification history."""

    def __init__(self, history_size: int = _HISTORY_SIZE, min_confirmations: int = _MIN_CONFIRMATIONS):
        self.history_size = history_size
        self.min_confirmations = min_confirmations
        # symbol -> deque of recent regime labels
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))
        # symbol -> last confirmed regime
        self._confirmed: Dict[str, str] = {}

    def update(self, symbol: str, current_regime: str) -> Dict[str, Any]:
        """Update regime history and check for transitions.

        Args:
            symbol: Trading pair symbol.
            current_regime: Latest regime classification.

        Returns:
            Dict with keys:
                - regime: current confirmed regime
                - transitioning: bool, True if regime is shifting
                - from_regime: previous confirmed regime (if transitioning)
                - to_regime: new regime being confirmed (if transitioning)
                - confirmations: how many times new regime has been seen
                - confidence: transition confidence (0-1)
                - history: recent regime sequence
        """
        history = self._history[symbol]
        history.append(current_regime)

        confirmed = self._confirmed.get(symbol, "")

        result = {
            "regime": confirmed or current_regime,
            "transitioning": False,
            "from_regime": "",
            "to_regime": "",
            "confirmations": 0,
            "confidence": 0.0,
            "history": list(history),
        }

        if not confirmed:
            # First time seeing this symbol — just set it
            self._confirmed[symbol] = current_regime
            result["regime"] = current_regime
            return result

        if current_regime == confirmed:
            # Same regime — no transition
            return result

        # Check how many recent entries match the new regime
        recent = list(history)[-self.history_size:]
        new_count = sum(1 for r in recent if r == current_regime)
        old_count = sum(1 for r in recent if r == confirmed)

        result["confirmations"] = new_count

        if new_count >= self.min_confirmations:
            # Transition detected
            result["transitioning"] = True
            result["from_regime"] = confirmed
            result["to_regime"] = current_regime
            result["confidence"] = min(1.0, new_count / max(len(recent), 1))

            # Dominance ratio check: new regime must have > 60% of recent labels
            dominance = new_count / max(len(recent), 1)
            if dominance <= _DOMINANCE_RATIO:
                logger.info(
                    f"[REGIME] {symbol}: DOMINANCE CHECK BLOCKED transition "
                    f"{confirmed} -> {current_regime} "
                    f"(dominance {dominance:.0%} <= {_DOMINANCE_RATIO:.0%}, "
                    f"{new_count}/{len(recent)} labels)"
                )
            elif new_count > old_count:
                # If new regime dominates, confirm the transition
                logger.info(
                    f"[REGIME] {symbol}: CONFIRMED transition "
                    f"{confirmed} -> {current_regime} "
                    f"({new_count}/{len(recent)} confirmations, "
                    f"dominance {dominance:.0%})"
                )
                self._confirmed[symbol] = current_regime
                result["regime"] = current_regime
            else:
                logger.info(
                    f"[REGIME] {symbol}: POSSIBLE transition "
                    f"{confirmed} -> {current_regime} "
                    f"({new_count}/{len(recent)} confirmations, "
                    f"not yet dominant over {old_count} old)"
                )

        return result

    def get_regime(self, symbol: str) -> str:
        """Get the current confirmed regime for a symbol."""
        return self._confirmed.get(symbol, "unknown")

    def get_all_regimes(self) -> Dict[str, str]:
        """Get confirmed regimes for all tracked symbols."""
        return dict(self._confirmed)

    def get_transition_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get transition status for all tracked symbols."""
        summary = {}
        for symbol in self._history:
            history = list(self._history[symbol])
            if len(history) < 2:
                continue
            confirmed = self._confirmed.get(symbol, "")
            latest = history[-1] if history else ""
            if latest != confirmed:
                new_count = sum(1 for r in history if r == latest)
                summary[symbol] = {
                    "from": confirmed,
                    "to": latest,
                    "confirmations": new_count,
                    "total": len(history),
                }
        return summary
