"""
Graceful degradation: handle partial system failures without total shutdown.

When external services fail (exchange API, LLM API), the bot should degrade
gracefully rather than freeze or crash:
  - Exchange down: halt new entries, monitor existing positions with last known prices
  - LLM down: fall back to ensemble-only mode (LLM_MODE=0)
  - Both down: halt new entries, protect existing positions only

Usage:
    degradation = DegradationManager()
    degradation.record_exchange_error()
    if degradation.should_halt_entries():
        skip_new_trades()
    if degradation.should_skip_llm():
        use_ensemble_only()
"""

import logging
import time
from typing import Dict, Any

logger = logging.getLogger("bot.execution.degradation")

# Thresholds
_EXCHANGE_ERROR_THRESHOLD = 3   # Consecutive errors before degrading
_LLM_ERROR_THRESHOLD = 2        # Consecutive errors before falling back
_RECOVERY_WINDOW_S = 300        # 5 minutes of success to recover
_LLM_PROBE_INTERVAL_S = 600     # Try one probe call every 10 min while degraded


class DegradationManager:
    """Manages graceful degradation when external services fail."""

    def __init__(self):
        self._exchange_errors = 0
        self._exchange_degraded = False
        self._exchange_last_success = time.time()
        self._exchange_last_error = 0.0

        self._llm_errors = 0
        self._llm_degraded = False
        self._llm_last_success = time.time()
        self._llm_last_error = 0.0
        self._llm_last_probe_attempt = 0.0  # last probe attempt while degraded

    def record_exchange_success(self):
        """Record a successful exchange API call."""
        self._exchange_errors = 0
        self._exchange_last_success = time.time()
        if self._exchange_degraded:
            # Check if we've had enough success time to recover
            if time.time() - self._exchange_last_error > _RECOVERY_WINDOW_S:
                self._exchange_degraded = False
                logger.info("[DEGRADATION] Exchange API recovered — resuming normal operations")

    def record_exchange_error(self):
        """Record a failed exchange API call."""
        self._exchange_errors += 1
        self._exchange_last_error = time.time()
        if self._exchange_errors >= _EXCHANGE_ERROR_THRESHOLD and not self._exchange_degraded:
            self._exchange_degraded = True
            logger.warning(
                f"[DEGRADATION] Exchange API degraded after {self._exchange_errors} "
                f"consecutive errors — halting new entries"
            )

    def record_llm_success(self):
        """Record a successful LLM API call."""
        self._llm_errors = 0
        self._llm_last_success = time.time()
        if self._llm_degraded:
            if time.time() - self._llm_last_error > _RECOVERY_WINDOW_S:
                self._llm_degraded = False
                logger.info("[DEGRADATION] LLM API recovered — resuming LLM-enhanced mode")

    def record_llm_error(self):
        """Record a failed LLM API call."""
        self._llm_errors += 1
        self._llm_last_error = time.time()
        if self._llm_errors >= _LLM_ERROR_THRESHOLD and not self._llm_degraded:
            self._llm_degraded = True
            # Start the probe cooldown timer from the moment we degrade so
            # the first probe fires ~10 minutes later, not immediately.
            self._llm_last_probe_attempt = time.time()
            logger.warning(
                f"[DEGRADATION] LLM API degraded after {self._llm_errors} "
                f"consecutive errors — falling back to ensemble-only"
            )

    def should_halt_entries(self) -> bool:
        """Should we halt new trade entries?"""
        return self._exchange_degraded

    def should_skip_llm(self) -> bool:
        """Should we skip LLM calls and use ensemble-only?

        While degraded, allow ONE probe call every _LLM_PROBE_INTERVAL_S so
        the system can self-heal after a transient outage. Without this, the
        degraded flag is permanent until restart (record_llm_success never
        fires because all calls are blocked — silent lockout).
        """
        if not self._llm_degraded:
            return False
        # Allow a probe if enough time has passed since last attempt
        now = time.time()
        if now - self._llm_last_probe_attempt >= _LLM_PROBE_INTERVAL_S:
            self._llm_last_probe_attempt = now
            logger.info(
                "[DEGRADATION] LLM probe attempt — testing recovery after outage"
            )
            return False  # Let this one call through
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get degradation status for monitoring."""
        return {
            "exchange_degraded": self._exchange_degraded,
            "exchange_errors": self._exchange_errors,
            "exchange_last_success_s_ago": round(time.time() - self._exchange_last_success, 1),
            "llm_degraded": self._llm_degraded,
            "llm_errors": self._llm_errors,
            "llm_last_success_s_ago": round(time.time() - self._llm_last_success, 1),
            "mode": self._current_mode(),
        }

    def _current_mode(self) -> str:
        """Describe the current operating mode."""
        if self._exchange_degraded and self._llm_degraded:
            return "CRITICAL: exchange+LLM down, protect-only"
        elif self._exchange_degraded:
            return "DEGRADED: exchange down, no new entries"
        elif self._llm_degraded:
            return "DEGRADED: LLM down, ensemble-only"
        return "NORMAL"
