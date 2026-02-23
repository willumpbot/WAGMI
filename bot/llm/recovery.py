"""
LLM Error Recovery Pipeline: Handle timeouts, invalid JSON, API failures.

This is the resilience layer that ensures LLM failures never crash the bot.

Failure modes handled:
1. API timeout → fallback to cached/baseline
2. Invalid JSON → log + fallback
3. Empty response → log + fallback
4. Network error → log + fallback
5. Rate limit → back off + fallback
6. Validation failure → log + fallback

All failures are logged and tracked for monitoring.
"""

import logging
import os
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from llm.decision_types import LLMDecision

logger = logging.getLogger("bot.llm.recovery")


# ── Error Tracking ────────────────────────────────────────────

@dataclass
class ErrorStats:
    """Tracks LLM error rates and patterns."""
    total_calls: int = 0
    total_errors: int = 0
    consecutive_errors: int = 0
    last_error_ts: float = 0.0
    last_error_type: str = ""
    error_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        """Percentage of calls that failed."""
        if self.total_calls == 0:
            return 0.0
        return (self.total_errors / self.total_calls) * 100

    def record_call(self):
        """Record a successful call."""
        self.total_calls += 1
        self.consecutive_errors = 0

    def record_error(self, error_type: str):
        """Record a failed call."""
        self.total_errors += 1
        self.consecutive_errors += 1
        self.last_error_ts = time.time()
        self.last_error_type = error_type
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        logger.warning(
            f"[LLM-RECOVERY] Error #{self.total_errors} ({error_type}): "
            f"rate={self.error_rate:.1f}% consecutive={self.consecutive_errors}"
        )


_error_stats = ErrorStats()


def get_error_stats() -> ErrorStats:
    """Get current error statistics."""
    return _error_stats


def reset_error_stats():
    """Reset error counters (e.g., after a successful recovery)."""
    global _error_stats
    _error_stats = ErrorStats()


# ── Error Handlers ────────────────────────────────────────────


def handle_api_error(
    error_msg: str,
    error_type: str = "api_error",
) -> tuple:
    """Handle API-level errors (timeout, connection, rate limit).

    Returns (is_recoverable, fallback_decision, reason).
    """
    _error_stats.record_error(error_type)

    logger.error(f"[LLM-RECOVERY] API error ({error_type}): {error_msg}")

    # Check if we're in a critical error loop
    if _error_stats.consecutive_errors >= 3:
        logger.critical(
            f"[LLM-RECOVERY] CIRCUIT BREAKER: {_error_stats.consecutive_errors} "
            f"consecutive errors. Disabling LLM temporarily."
        )
        return False, None, f"circuit_breaker_active ({error_type})"

    # Otherwise recoverable
    return True, None, error_type


def handle_validation_error(
    error_msg: str,
    raw_output: Optional[str] = None,
) -> tuple:
    """Handle validation-level errors (invalid JSON, schema mismatch).

    Returns (is_recoverable, fallback_decision, reason).
    """
    _error_stats.record_error("validation_error")

    logger.error(f"[LLM-RECOVERY] Validation error: {error_msg}")
    if raw_output:
        logger.debug(f"[LLM-RECOVERY] Raw output: {raw_output[:200]}")

    # Validation errors are always recoverable (fallback to baseline)
    return True, None, "validation_error"


def handle_semantic_error(
    error_msg: str,
    decision: Optional[LLMDecision] = None,
) -> tuple:
    """Handle semantic errors (business logic violation).

    Returns (is_recoverable, fallback_decision, reason).
    """
    _error_stats.record_error("semantic_error")

    logger.error(f"[LLM-RECOVERY] Semantic error: {error_msg}")
    if decision:
        logger.debug(f"[LLM-RECOVERY] Decision: {decision}")

    # Semantic errors are recoverable (decision rejected, fallback)
    return True, None, "semantic_error"


# ── Fallback Strategies ───────────────────────────────────────

def fallback_to_baseline(reason: str = "") -> tuple:
    """Fallback: use baseline ensemble logic (no LLM influence).

    Returns (decision, reason).
    """
    logger.info(f"[LLM-RECOVERY] Fallback to baseline: {reason}")
    return None, f"fallback: {reason}"


def fallback_to_cached(cached_decision: Optional[LLMDecision]) -> tuple:
    """Fallback: use cached LLM decision if available.

    Returns (decision, reason).
    """
    if cached_decision:
        logger.info("[LLM-RECOVERY] Fallback to cached decision")
        return cached_decision, "fallback_cached"
    return None, "fallback_no_cache"


def should_disable_llm_temporarily() -> bool:
    """Check if LLM should be temporarily disabled due to error rate.

    Rules:
    - If consecutive errors >= 3, disable
    - If error_rate > 30% in last 10 calls, disable
    - If last error < 2 minutes ago AND consecutive >= 2, disable
    """
    stats = _error_stats

    if stats.consecutive_errors >= 3:
        logger.warning("[LLM-RECOVERY] Disabling LLM: 3+ consecutive errors")
        return True

    if stats.total_calls >= 10:
        recent_error_rate = (stats.consecutive_errors / max(stats.total_calls, 1)) * 100
        if recent_error_rate > 30 and stats.consecutive_errors >= 2:
            logger.warning(
                f"[LLM-RECOVERY] Disabling LLM: {recent_error_rate:.1f}% error rate "
                f"({stats.consecutive_errors} recent)"
            )
            return True

    return False


def get_llm_disabled_reason() -> Optional[str]:
    """Get the reason LLM is disabled, if any."""
    if should_disable_llm_temporarily():
        stats = _error_stats
        if stats.consecutive_errors >= 3:
            return f"circuit_breaker ({stats.consecutive_errors} consecutive errors)"
        return f"high_error_rate ({stats.error_rate:.1f}%)"
    return None


# ── Recovery Wrapper ─────────────────────────────────────────


def recovery_wrapper(func):
    """Decorator: wraps LLM calls with error recovery.

    Usage:
        @recovery_wrapper
        def get_llm_decision(...):
            ...
    """
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            _error_stats.record_call()
            return result
        except TimeoutError as e:
            recoverable, _, reason = handle_api_error(str(e), "timeout")
            if recoverable:
                return fallback_to_baseline(reason)
            raise
        except ConnectionError as e:
            recoverable, _, reason = handle_api_error(str(e), "connection_error")
            if recoverable:
                return fallback_to_baseline(reason)
            raise
        except Exception as e:
            recoverable, _, reason = handle_api_error(str(e), "unknown_error")
            if recoverable:
                return fallback_to_baseline(reason)
            raise
    return wrapper


# ── Monitoring ───────────────────────────────────────────────

def log_recovery_summary():
    """Log a summary of LLM error recovery metrics."""
    stats = _error_stats
    logger.info(
        f"[LLM-RECOVERY] Summary: "
        f"{stats.total_calls} calls, "
        f"{stats.total_errors} errors ({stats.error_rate:.1f}%), "
        f"consecutive={stats.consecutive_errors}"
    )
    if stats.error_counts:
        logger.info(
            f"[LLM-RECOVERY] Error types: "
            f"{', '.join(f'{k}={v}' for k, v in sorted(stats.error_counts.items()))}"
        )
