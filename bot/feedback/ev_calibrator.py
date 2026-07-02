"""
EV Calibrator — Adaptive EV threshold adjustment based on measured rejection outcomes.

Phase 2 of the Adaptive Online Learning System.

Problem: The EV gate rejects all signals with EV < 0. Paper trading showed that
marginally negative EV signals (>= -0.01) with 3+ strategy consensus are profitable
50%+ of the time. Strict rejection leaves money on the table.

Solution: Track rejection outcomes by EV bin. When marginal signals are being
missed at a high rate, relax the threshold to allow them through at reduced size.
When the market shifts and correct rejections dominate, tighten back to strict.

Safety rails:
- Threshold never goes below -0.02
- Minimum 10 observations before any adjustment
- Only consensus signals (3+ strategies) get override
- Override signals use 0.5x position size

Reads from: RejectionOutcomeTracker (bot/feedback/rejection_tracker.py)
Persists to: bot/data/ev_calibrator_state.json
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.feedback.ev_calibrator")

# --- Constants ---

# EV bins matching RejectionOutcomeTracker
EV_BIN_STRONG_NEG = "strong_neg"      # EV < -0.05
EV_BIN_MODERATE_NEG = "moderate_neg"  # -0.05 <= EV < -0.01
EV_BIN_MARGINAL_NEG = "marginal_neg"  # -0.01 <= EV < 0.0

# Threshold adjustment triggers
# FALLACY_AUDIT M7 (2026-07-02): was 5 ("faster adaptation") — below
# THE_STANDARD §1/§2b evidence floor. Nothing enforces below n>=13.
MIN_OBSERVATIONS = 13
MISS_RATE_RELAX_THRESHOLD = 0.30   # Relax when miss_rate > 30%
CORRECT_RATE_RELAX_MAX = 0.10      # Only relax when correct_rate < 10%
CORRECT_RATE_TIGHTEN = 0.50        # Tighten when correct_rate > 50%

# Safety rails
ABSOLUTE_MIN_EV_THRESHOLD = -0.02  # Never allow EV below this
MIN_CONSENSUS_FOR_OVERRIDE = 3     # Only override with 3+ strategy agreement
OVERRIDE_SIZE_MULTIPLIER = 0.5     # Half size on overridden signals

# Threshold modes
MODE_STRICT = "strict"        # EV >= 0 required (default)
MODE_RELAXED = "relaxed"      # Allow marginal negatives with consensus
# SHADOW (FALLACY_AUDIT M7): would-have-overridden is logged, nothing is
# admitted. This is the cold-start mode — the old cold-start forced RELAXED
# on every restart, a permanently-relaxed gate no measurement could revoke.
MODE_SHADOW = "shadow"


class EVCalibrator:
    """Adaptively adjusts EV rejection threshold based on measured outcomes.

    Integrates with RejectionOutcomeTracker to read outcome statistics,
    then decides whether marginal EV signals should be allowed through.

    Usage in ensemble.py:
        if ev_per_dollar < 0:
            if self._ev_calibrator and self._ev_calibrator.should_override(ev_per_dollar, n_agree):
                size_mult = self._ev_calibrator.get_override_size_mult()
                # Allow signal through at reduced size
            else:
                return None  # Normal rejection
    """

    def __init__(
        self,
        rejection_tracker=None,
        data_dir: str = "data",
    ):
        self._tracker = rejection_tracker  # RejectionOutcomeTracker instance
        self._data_dir = data_dir
        self._state_file = os.path.join(data_dir, "ev_calibrator_state.json")

        # Current state
        self._mode: str = MODE_STRICT
        self._ev_threshold: float = 0.0  # Current effective EV threshold
        self._override_size_mult: float = OVERRIDE_SIZE_MULTIPLIER
        self._last_update: float = 0.0
        self._total_overrides: int = 0
        self._total_override_wins: int = 0
        self._shadow_would_overrides: int = 0
        self._transition_history: list = []  # [{timestamp, from_mode, to_mode, reason, stats}]

        # Load persisted state
        self._load_state()

        # Cold-start: SHADOW (FALLACY_AUDIT M7 / THE_STANDARD 2b). The old
        # cold-start re-forced RELAXED on every restart based on a claim
        # ("50%+ profitable") whose measurement loop was dead — an enforcing
        # gate with no revocation path. Shadow logs would-have-overridden and
        # admits nothing until n>=13 rejection outcomes justify relaxing.
        if self._total_overrides == 0 and not self._transition_history:
            self._mode = MODE_SHADOW
            self._ev_threshold = -0.01  # what SHADOW *would* allow (logged only)
            logger.info("[EV-CALIBRATOR] Cold-start: beginning in SHADOW mode (log-only)")

        logger.info(
            f"[EV-CALIBRATOR] Initialized: mode={self._mode} "
            f"threshold={self._ev_threshold:.4f} overrides={self._total_overrides}"
        )

    # --- Public API ---

    def should_override(self, ev: float, n_agree: int) -> bool:
        """Decide whether a negative-EV signal should be allowed through.

        Args:
            ev: The calculated EV per dollar (negative)
            n_agree: Number of strategies that agree on direction

        Returns:
            True if the signal should be allowed through at reduced size.
        """
        # Only override negative EV (positive EV doesn't need override)
        if ev >= 0:
            return False

        # Never override if EV is below absolute minimum
        if ev < ABSOLUTE_MIN_EV_THRESHOLD:
            return False

        # SHADOW: log the would-have-overridden decision, admit nothing (M7)
        if self._mode == MODE_SHADOW:
            if n_agree >= MIN_CONSENSUS_FOR_OVERRIDE and ev >= self._ev_threshold:
                self._shadow_would_overrides += 1
                self._save_state()
                logger.info(
                    f"[EV-CALIBRATOR] SHADOW would-have-overridden: EV={ev:.4f} "
                    f"n_agree={n_agree} (total shadow: {self._shadow_would_overrides}) — not admitted"
                )
            return False

        # Only override in relaxed mode
        if self._mode != MODE_RELAXED:
            return False

        # Only override consensus signals
        if n_agree < MIN_CONSENSUS_FOR_OVERRIDE:
            return False

        # Only override if EV is above current threshold
        if ev < self._ev_threshold:
            return False

        self._total_overrides += 1
        self._save_state()

        logger.info(
            f"[EV-CALIBRATOR] Override approved: EV={ev:.4f} n_agree={n_agree} "
            f"threshold={self._ev_threshold:.4f} size_mult={self._override_size_mult}"
        )
        return True

    def get_override_size_mult(self) -> float:
        """Get the position size multiplier for overridden signals.

        Returns:
            Multiplier to apply to position size (0.5 = half size).
        """
        return self._override_size_mult

    def record_override_outcome(self, profitable: bool) -> None:
        """Record whether an overridden signal was profitable.

        Call this when a trade opened via override closes.
        """
        if profitable:
            self._total_override_wins += 1
        self._save_state()

        total = self._total_overrides
        wins = self._total_override_wins
        win_rate = wins / total if total > 0 else 0.0
        logger.info(
            f"[EV-CALIBRATOR] Override outcome: {'WIN' if profitable else 'LOSS'} "
            f"(override win rate: {wins}/{total} = {win_rate:.1%})"
        )

    def ingest_outcome(self, ev: float, n_agree: int, outcome: str) -> None:
        """Per-outcome callback from RejectionOutcomeTracker.

        FALLACY_AUDIT M7: main wired the tracker callback to this method name
        but it never existed — AttributeError at init, the calibrator handle
        was nulled in main while the ensemble kept enforcing the override.
        The tracker's bin stats already include this outcome by callback time;
        re-evaluating the threshold is all that's needed here.
        """
        try:
            self.update()
        except Exception as e:
            logger.debug(f"[EV-CALIBRATOR] ingest_outcome update error: {e}")

    def update(self) -> Dict[str, Any]:
        """Re-evaluate threshold based on current rejection outcome data.

        Should be called periodically (e.g., every scan cycle or hourly).

        Returns:
            Dict with current calibration state.
        """
        if self._tracker is None:
            return self._get_status()

        stats = self._tracker.get_stats_summary()
        bins = stats.get("bins", {})
        marginal = bins.get(EV_BIN_MARGINAL_NEG, {})

        total = marginal.get("total", 0)
        missed = marginal.get("missed", 0)
        correct = marginal.get("correct", 0)

        miss_rate = missed / total if total > 0 else 0.0
        correct_rate = correct / total if total > 0 else 0.0

        old_mode = self._mode
        reason = ""

        if total >= MIN_OBSERVATIONS:
            if self._mode in (MODE_STRICT, MODE_SHADOW):
                # Check if we should relax: high miss rate, low correct rate
                if miss_rate > MISS_RATE_RELAX_THRESHOLD and correct_rate < CORRECT_RATE_RELAX_MAX:
                    self._mode = MODE_RELAXED
                    self._ev_threshold = -0.01  # Allow marginal negatives
                    reason = (
                        f"Relaxing: miss_rate={miss_rate:.1%} > {MISS_RATE_RELAX_THRESHOLD:.0%}, "
                        f"correct_rate={correct_rate:.1%} < {CORRECT_RATE_RELAX_MAX:.0%} "
                        f"over {total} observations"
                    )
                elif self._mode == MODE_SHADOW and correct_rate > CORRECT_RATE_TIGHTEN:
                    # Shadow resolved against relaxing — settle into strict
                    self._mode = MODE_STRICT
                    self._ev_threshold = 0.0
                    reason = (
                        f"Shadow resolved to STRICT: correct_rate={correct_rate:.1%} > "
                        f"{CORRECT_RATE_TIGHTEN:.0%} over {total} observations"
                    )

            elif self._mode == MODE_RELAXED:
                # Check if we should tighten: correct rejections dominate
                if correct_rate > CORRECT_RATE_TIGHTEN:
                    self._mode = MODE_STRICT
                    self._ev_threshold = 0.0
                    reason = (
                        f"Tightening: correct_rate={correct_rate:.1%} > {CORRECT_RATE_TIGHTEN:.0%} "
                        f"over {total} observations"
                    )

        # Enforce absolute minimum threshold
        self._ev_threshold = max(self._ev_threshold, ABSOLUTE_MIN_EV_THRESHOLD)

        # Log transition
        if old_mode != self._mode:
            transition = {
                "timestamp": time.time(),
                "from_mode": old_mode,
                "to_mode": self._mode,
                "reason": reason,
                "stats": {
                    "total": total,
                    "missed": missed,
                    "correct": correct,
                    "miss_rate": round(miss_rate, 4),
                    "correct_rate": round(correct_rate, 4),
                },
            }
            self._transition_history.append(transition)
            # Keep only last 50 transitions
            self._transition_history = self._transition_history[-50:]

            logger.warning(
                f"[EV-CALIBRATOR] THRESHOLD CHANGE: {old_mode} -> {self._mode} | "
                f"{reason}"
            )

        self._last_update = time.time()
        self._save_state()

        return self._get_status()

    def get_status(self) -> Dict[str, Any]:
        """Get current calibrator status for reporting."""
        return self._get_status()

    # --- Internal ---

    def _get_status(self) -> Dict[str, Any]:
        """Build status dict."""
        override_win_rate = (
            self._total_override_wins / self._total_overrides
            if self._total_overrides > 0
            else 0.0
        )
        return {
            "mode": self._mode,
            "ev_threshold": self._ev_threshold,
            "override_size_mult": self._override_size_mult,
            "total_overrides": self._total_overrides,
            "override_win_rate": round(override_win_rate, 4),
            "shadow_would_overrides": self._shadow_would_overrides,
            "last_update": self._last_update,
            "transitions": len(self._transition_history),
        }

    def _save_state(self) -> None:
        """Persist calibrator state to disk."""
        state = {
            "mode": self._mode,
            "ev_threshold": self._ev_threshold,
            "override_size_mult": self._override_size_mult,
            "total_overrides": self._total_overrides,
            "total_override_wins": self._total_override_wins,
            "shadow_would_overrides": self._shadow_would_overrides,
            "last_update": self._last_update,
            "transition_history": self._transition_history,
        }
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            tmp = self._state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2, default=str)
            # Atomic rename
            if os.path.exists(self._state_file):
                os.replace(tmp, self._state_file)
            else:
                os.rename(tmp, self._state_file)
        except Exception as e:
            logger.warning(f"[EV-CALIBRATOR] Save error: {e}")

    def _load_state(self) -> None:
        """Load calibrator state from disk."""
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)

            self._mode = state.get("mode", MODE_STRICT)
            self._ev_threshold = state.get("ev_threshold", 0.0)
            self._override_size_mult = state.get("override_size_mult", OVERRIDE_SIZE_MULTIPLIER)
            self._total_overrides = state.get("total_overrides", 0)
            self._total_override_wins = state.get("total_override_wins", 0)
            self._shadow_would_overrides = state.get("shadow_would_overrides", 0)
            self._last_update = state.get("last_update", 0.0)
            self._transition_history = state.get("transition_history", [])

            # Enforce safety rails on loaded state
            self._ev_threshold = max(self._ev_threshold, ABSOLUTE_MIN_EV_THRESHOLD)
            if self._mode not in (MODE_STRICT, MODE_RELAXED, MODE_SHADOW):
                logger.warning(
                    f"[EV-CALIBRATOR] Invalid mode '{self._mode}' in state file, resetting to strict"
                )
                self._mode = MODE_STRICT
                self._ev_threshold = 0.0

            logger.debug(
                f"[EV-CALIBRATOR] Loaded state: mode={self._mode} "
                f"threshold={self._ev_threshold:.4f} overrides={self._total_overrides}"
            )
        except Exception as e:
            logger.warning(f"[EV-CALIBRATOR] Load error: {e}, starting fresh")
