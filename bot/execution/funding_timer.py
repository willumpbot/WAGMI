"""
Funding payment timing utilities.

Hyperliquid funding payments occur every 8 hours at 0:00, 8:00, 16:00 UTC.
This module helps decide whether to close marginal positions before a
funding payment to avoid unnecessary costs.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("bot.execution.funding_timer")

# Funding payment hours (UTC)
_FUNDING_HOURS = (0, 8, 16)


def minutes_until_next_funding(now: datetime = None) -> int:
    """Return minutes until the next 8-hourly funding payment.

    Args:
        now: Override for testing. Defaults to current UTC time.
    Returns:
        Minutes until next funding payment (0-480).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    current_minutes = now.hour * 60 + now.minute

    for fh in _FUNDING_HOURS:
        target = fh * 60
        if target > current_minutes:
            return target - current_minutes

    # Next is midnight tomorrow
    return (24 * 60) - current_minutes


def should_close_before_funding(
    pnl_pct: float,
    funding_rate: float,
    leverage: float,
    side: str,
    minutes_to_funding: int = None,
    now: datetime = None,
) -> bool:
    """Decide whether to close a marginal position before funding.

    Close if ALL of these are true:
      1. Less than 30 minutes until next funding payment
      2. Position is paying funding (not earning)
      3. Position PnL is marginal (< 0.5% profit)
      4. Estimated funding cost > 0.03% of position

    Args:
        pnl_pct: Current unrealized PnL as percentage of entry.
        funding_rate: Current 8-hour funding rate (e.g., 0.0005 = 0.05%).
        leverage: Position leverage.
        side: "LONG" or "SHORT".
        minutes_to_funding: Override minutes until next funding (for testing).
        now: Override current time (for testing).

    Returns:
        True if position should be closed to avoid funding cost.
    """
    if minutes_to_funding is None:
        minutes_to_funding = minutes_until_next_funding(now)

    # Only act within 30 minutes of funding payment
    if minutes_to_funding > 30:
        return False

    # Check if position is paying funding
    side_lower = side.lower()
    is_paying = (
        (side_lower in ("long", "buy") and funding_rate > 0) or
        (side_lower in ("short", "sell") and funding_rate < 0)
    )
    if not is_paying:
        return False

    # Only close marginal positions (less than 0.5% profit)
    if pnl_pct > 0.5:
        return False

    # Check if funding cost is significant
    funding_cost_pct = abs(funding_rate) * leverage * 100  # As % of position
    if funding_cost_pct < 0.03:
        return False

    logger.info(
        f"[FUNDING-TIMER] Recommend close: {side} position "
        f"PnL={pnl_pct:.2f}%, funding_cost={funding_cost_pct:.3f}%, "
        f"{minutes_to_funding}min to payment"
    )
    return True
