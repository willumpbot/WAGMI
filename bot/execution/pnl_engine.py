"""
PnL Computation Engine.

All PnL calculations use the effective_entry (live preferred, snapshot fallback).
This ensures reported PnL matches actual execution, not stale snapshot prices.
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("bot.execution.pnl_engine")


def compute_pnl(
    effective_entry: float,
    exit_price: float,
    side: str,
    size_usd: float,
    fee_bps: int = 5,
    funding_costs: float = 0.0,
) -> Dict[str, Any]:
    """Compute realized PnL from effective entry and exit.

    Args:
        effective_entry: Actual entry price used
        exit_price: Price at close
        side: "LONG" or "SHORT"
        size_usd: Position size in USD
        fee_bps: Fee in basis points (both entry + exit)
        funding_costs: Cumulative funding payments during hold (positive = cost)

    Returns:
        dict with pnl, fees, funding_costs, pnl_pct, outcome
    """
    if effective_entry <= 0 or exit_price <= 0 or size_usd <= 0:
        return {
            "pnl": 0.0,
            "fees": 0.0,
            "funding_costs": 0.0,
            "pnl_pct": 0.0,
            "outcome": "INVALID",
        }

    qty = size_usd / effective_entry

    if side.upper() == "LONG":
        raw_pnl = (exit_price - effective_entry) * qty
    elif side.upper() == "SHORT":
        raw_pnl = (effective_entry - exit_price) * qty
    else:
        return {"pnl": 0.0, "fees": 0.0, "funding_costs": 0.0, "pnl_pct": 0.0, "outcome": "INVALID"}

    # Fees: entry + exit (in BPS of notional)
    fee_rate = fee_bps / 10000.0
    fees = size_usd * fee_rate * 2  # Entry + exit

    # Total costs = trading fees + funding payments
    total_costs = fees + abs(funding_costs)
    net_pnl = raw_pnl - total_costs
    pnl_pct = (net_pnl / size_usd) * 100

    if net_pnl > 0.01:
        outcome = "WIN"
    elif net_pnl < -0.01:
        outcome = "LOSS"
    else:
        outcome = "BREAK_EVEN"

    return {
        "pnl": round(net_pnl, 4),
        "fees": round(fees, 4),
        "funding_costs": round(abs(funding_costs), 4),
        "pnl_pct": round(pnl_pct, 4),
        "outcome": outcome,
        "raw_pnl": round(raw_pnl, 4),
    }


def compute_r_multiple(
    effective_entry: float,
    exit_price: float,
    sl_price: float,
    side: str,
) -> float:
    """Compute R-multiple (how many risk units were captured).

    R = 1.0 means we captured exactly our risk amount.
    R = 2.0 means we made 2x our risk.
    R = -1.0 means we lost our full risk amount.
    """
    if effective_entry <= 0 or sl_price <= 0:
        return 0.0

    risk = abs(effective_entry - sl_price)
    if risk <= 0:
        return 0.0

    if side.upper() == "LONG":
        reward = exit_price - effective_entry
    elif side.upper() == "SHORT":
        reward = effective_entry - exit_price
    else:
        return 0.0

    return round(reward / risk, 2)
