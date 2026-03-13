"""
Information Coefficient (IC) Tracker: Monitors factor predictive power via Spearman rank correlation.

For every closed trade, records the factor's predicted direction (+1/-1) and the actual return.
Computes rolling Spearman rho to detect:
  - INVERTED factors (negative IC — factor predicts the opposite of reality)
  - DECAYING factors (IC near zero — factor has lost predictive edge)

This exists because confidence_scorer once inverted to rho = -0.50 Spearman
and the system had no mechanism to catch it.

The IC weight feeds back into sizing:
  - Inverted factor (IC < 0): weight = 0.0 (kill it)
  - Unknown factor (< 10 samples): weight = 0.5 (half size until proven)
  - Healthy factor (IC >= 0.10): weight = 1.0
  - In between: linear scale from 0.0 to 1.0
"""

import json
import logging
import os
import threading
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

try:
    from scipy.stats import spearmanr

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

logger = logging.getLogger("bot.feedback.ic_tracker")

# --- Constants ---
IC_WINDOW = 30
DECAY_THRESHOLD = 0.02
INVERSION_THRESHOLD = 0.0
MIN_SAMPLES = 10
MAX_BUFFER = 150  # 30-day window * 5 trades/day max


class ICTracker:
    """
    Tracks Information Coefficient (Spearman rho) per factor to detect
    inverted or decaying signal sources.

    Usage:
        tracker = ICTracker()
        tracker.record("confidence_scorer", +1, 0.023)
        tracker.record("confidence_scorer", -1, -0.011)
        alerts = tracker.check_all_factors()
        weight = tracker.get_ic_weight("confidence_scorer")
    """

    def __init__(self, data_dir: str = "data"):
        self._data_dir = data_dir
        self._state_file = os.path.join(data_dir, "ic_history.json")
        self._lock = threading.Lock()

        # {factor: deque of (predicted_direction, actual_return)}
        self._buffers: Dict[str, deque] = {}

        self._load_state()

    def record(self, factor: str, predicted_direction: int, actual_return: float) -> None:
        """Record a factor prediction and its realized outcome.

        Args:
            factor: Factor/strategy name (e.g. "confidence_scorer", "regime_trend").
            predicted_direction: +1 for long, -1 for short.
            actual_return: Realized return of the trade (signed float).
        """
        if predicted_direction not in (1, -1):
            logger.warning(
                f"[IC] Invalid predicted_direction={predicted_direction} for {factor}, "
                f"expected +1 or -1"
            )
            return

        with self._lock:
            if factor not in self._buffers:
                self._buffers[factor] = deque(maxlen=MAX_BUFFER)

            self._buffers[factor].append((predicted_direction, actual_return))
            self._save_state()

        ic = self.compute_rolling_ic(factor)
        if ic is not None:
            status = self._classify_ic(ic)
            if status == "INVERTED":
                logger.warning(
                    f"[IC] ALERT: {factor} is INVERTED (IC={ic:.3f}) — "
                    f"factor predicts opposite of reality"
                )
            elif status == "DECAYING":
                logger.info(
                    f"[IC] WARNING: {factor} is DECAYING (IC={ic:.3f}) — "
                    f"factor has weak predictive power"
                )

    def compute_rolling_ic(
        self, factor: str, window: int = IC_WINDOW
    ) -> Optional[float]:
        """Compute rolling Spearman rho for a factor.

        Args:
            factor: Factor name.
            window: Number of recent observations to use.

        Returns:
            Spearman rho as float, or None if insufficient data or scipy unavailable.
        """
        if not HAS_SCIPY:
            logger.debug("[IC] scipy not available, cannot compute Spearman rho")
            return None

        with self._lock:
            buf = self._buffers.get(factor)
            if not buf or len(buf) < MIN_SAMPLES:
                return None

            # Take the most recent `window` observations
            recent = list(buf)[-window:]

        predictions = [p for p, _ in recent]
        actuals = [a for _, a in recent]

        try:
            rho, _ = spearmanr(predictions, actuals)
            # spearmanr can return nan for constant arrays
            if rho != rho:  # nan check
                return None
            return float(rho)
        except Exception as e:
            logger.warning(f"[IC] Failed to compute Spearman rho for {factor}: {e}")
            return None

    def check_all_factors(self) -> Dict[str, str]:
        """Check all tracked factors for IC anomalies.

        Returns:
            Dict of {factor: alert_status} where alert_status is one of:
              - "INVERTED": IC < 0 (factor predicts opposite of reality)
              - "DECAYING": IC >= 0 but < 0.02 (factor has lost edge)
              - "HEALTHY": IC >= 0.02
              - "INSUFFICIENT_DATA": fewer than MIN_SAMPLES observations
              - "NO_SCIPY": scipy not available
        """
        alerts: Dict[str, str] = {}

        with self._lock:
            factors = list(self._buffers.keys())

        for factor in factors:
            ic = self.compute_rolling_ic(factor)

            if not HAS_SCIPY:
                alerts[factor] = "NO_SCIPY"
            elif ic is None:
                alerts[factor] = "INSUFFICIENT_DATA"
            else:
                alerts[factor] = self._classify_ic(ic)

        return alerts

    def get_ic_weight(self, factor: str) -> float:
        """Get sizing multiplier based on factor IC health.

        Returns:
            0.0 for inverted factors (IC < 0)
            0.5 for unknown factors (< MIN_SAMPLES observations)
            Linear scale from 0.0 to 1.0 for IC in [0, 0.10]
            1.0 for IC >= 0.10
        """
        ic = self.compute_rolling_ic(factor)

        if ic is None:
            # Not enough data or no scipy — be cautious
            with self._lock:
                buf = self._buffers.get(factor)
                sample_count = len(buf) if buf else 0

            if sample_count < MIN_SAMPLES:
                return 0.5
            # Have enough samples but scipy missing
            return 0.5

        if ic < INVERSION_THRESHOLD:
            return 0.0

        if ic >= 0.10:
            return 1.0

        # Linear scale: IC 0.0 -> 0.0, IC 0.10 -> 1.0
        return round(ic / 0.10, 4)

    def get_report(self) -> Dict[str, Any]:
        """Get summary report of all tracked factors.

        Returns:
            Dict with per-factor breakdown:
              - ic: current rolling IC (or None)
              - samples: number of observations
              - status: INVERTED/DECAYING/HEALTHY/INSUFFICIENT_DATA/NO_SCIPY
              - weight: current sizing multiplier
        """
        report: Dict[str, Any] = {}

        with self._lock:
            factors = list(self._buffers.keys())

        for factor in factors:
            ic = self.compute_rolling_ic(factor)

            with self._lock:
                buf = self._buffers.get(factor)
                sample_count = len(buf) if buf else 0

            if not HAS_SCIPY:
                status = "NO_SCIPY"
            elif ic is None:
                status = "INSUFFICIENT_DATA"
            else:
                status = self._classify_ic(ic)

            report[factor] = {
                "ic": round(ic, 4) if ic is not None else None,
                "samples": sample_count,
                "status": status,
                "weight": self.get_ic_weight(factor),
            }

        return report

    @staticmethod
    def _classify_ic(ic: float) -> str:
        """Classify an IC value into a status label."""
        if ic < INVERSION_THRESHOLD:
            return "INVERTED"
        elif ic < DECAY_THRESHOLD:
            return "DECAYING"
        else:
            return "HEALTHY"

    def _save_state(self) -> None:
        """Persist buffer state to JSON. Must be called with lock held."""
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            state = {}
            for factor, buf in self._buffers.items():
                state[factor] = list(buf)

            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"[IC] Failed to save state: {e}")

    def _load_state(self) -> None:
        """Load buffer state from JSON on init."""
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)

            for factor, entries in state.items():
                buf = deque(maxlen=MAX_BUFFER)
                for entry in entries:
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        buf.append((int(entry[0]), float(entry[1])))
                self._buffers[factor] = buf

            total = sum(len(b) for b in self._buffers.values())
            logger.info(
                f"[IC] Loaded state: {len(self._buffers)} factors, "
                f"{total} total observations"
            )
        except Exception as e:
            logger.warning(f"[IC] Failed to load state: {e}")
