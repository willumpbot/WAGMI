"""
Time-aware position sizing multipliers.

Reduces position sizes during periods of lower liquidity:
1. Weekends (Saturday/Sunday UTC) -> WEEKEND_SIZE_MULTIPLIER
2. Low-liquidity hours (00:00-06:00 UTC, 20:00-24:00 UTC) -> LOW_LIQ_HOURS_MULTIPLIER

These are multiplicative on top of normal sizing, NOT replacements.
Example: a $100 position during a weekend late-night session becomes
         $100 * 0.5 * 0.7 = $35.

All multipliers are env-configurable for tuning.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("bot.execution.time_sizing")

# Env-configurable multipliers
WEEKEND_SIZE_MULTIPLIER = float(os.getenv("WEEKEND_SIZE_MULTIPLIER", "0.5"))
LOW_LIQ_HOURS_MULTIPLIER = float(os.getenv("LOW_LIQ_HOURS_MULTIPLIER", "0.7"))

# Low-liquidity windows (UTC hours)
# Crypto volume drops significantly in Asian late-night / early morning
_LOW_LIQ_HOURS = set(range(0, 7)) | set(range(21, 24))  # 00-06 and 21-23 UTC


def get_time_multiplier(now: datetime = None) -> float:
    """Return the combined time-based sizing multiplier.

    Returns a float in (0.0, 1.0] that should be multiplied into
    the position quantity before opening.

    Args:
        now: Override for testing. Defaults to current UTC time.

    Returns:
        Combined multiplier (weekend * low_liq, whichever apply).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    multiplier = 1.0
    reasons = []

    # Weekend check (Saturday=5, Sunday=6)
    if now.weekday() in (5, 6):
        multiplier *= WEEKEND_SIZE_MULTIPLIER
        reasons.append(f"weekend({WEEKEND_SIZE_MULTIPLIER:.2f}x)")

    # Low-liquidity hours check
    if now.hour in _LOW_LIQ_HOURS:
        multiplier *= LOW_LIQ_HOURS_MULTIPLIER
        reasons.append(f"low_liq_hours({LOW_LIQ_HOURS_MULTIPLIER:.2f}x)")

    if reasons:
        logger.info(
            f"[TIME-SIZE] Applying time multiplier: {multiplier:.2f}x "
            f"({', '.join(reasons)})"
        )

    return multiplier


def is_weekend(now: datetime = None) -> bool:
    """Check if current time is weekend (Saturday or Sunday UTC)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.weekday() in (5, 6)


def is_low_liquidity_hours(now: datetime = None) -> bool:
    """Check if current time is in low-liquidity window."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.hour in _LOW_LIQ_HOURS
