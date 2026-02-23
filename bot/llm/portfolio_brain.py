"""
Portfolio Meta-Brain: Cross-symbol reasoning for the LLM.

Adds portfolio-level context to LLM snapshots:
- Exposure per symbol and direction
- Concentration risk (are we overweight one direction?)
- Simple correlation tracking (how many same-direction positions?)
- Total leverage across portfolio

Also implements portfolio-level decisions:
- Reduce risk (cut sizes or close weakest positions)
- Rebalance (even out exposure)
- Symbol priority ranking

This is the bridge between per-symbol trading decisions and
portfolio-level risk management.
"""

import logging
from typing import Dict, List, Any, Optional

from execution.position_manager import PositionManager, Position

logger = logging.getLogger("bot.llm.portfolio_brain")


def build_portfolio_snapshot(
    pos_mgr: PositionManager,
    last_prices: Dict[str, float],
    equity: float,
) -> Dict[str, Any]:
    """Build a compact portfolio snapshot for the LLM.

    Returns a dict suitable for inclusion in the LLM input.
    """
    open_positions = pos_mgr.get_open_positions()
    if not open_positions:
        return {
            "total_positions": 0,
            "total_leverage": 0.0,
            "long_count": 0,
            "short_count": 0,
            "net_exposure_pct": 0.0,
            "positions": [],
        }

    positions_summary = []
    total_notional = 0.0
    total_long_notional = 0.0
    total_short_notional = 0.0
    long_count = 0
    short_count = 0

    for symbol, pos in open_positions.items():
        price = last_prices.get(symbol, pos.entry)
        notional = pos.qty * price * pos.leverage
        total_notional += notional

        # Unrealized PnL
        if pos.side == "LONG":
            unrealized = (price - pos.entry) * pos.qty * pos.leverage
            total_long_notional += notional
            long_count += 1
        else:
            unrealized = (pos.entry - price) * pos.qty * pos.leverage
            total_short_notional += notional
            short_count += 1

        # Distance to SL as percentage
        sl_dist_pct = abs(price - pos.sl) / price * 100 if price > 0 else 0

        positions_summary.append({
            "s": symbol,
            "side": pos.side[0],  # "L" or "S"
            "lev": pos.leverage,
            "entry": pos.entry,
            "pnl": round(unrealized, 2),
            "sl_dist": round(sl_dist_pct, 1),
            "state": pos.state,
        })

    # Net exposure: positive = net long, negative = net short
    net_exposure = total_long_notional - total_short_notional
    net_exposure_pct = (net_exposure / equity * 100) if equity > 0 else 0

    # Concentration: max single-position as % of total
    max_single = max(
        (pos.qty * last_prices.get(s, pos.entry) * pos.leverage)
        for s, pos in open_positions.items()
    ) if open_positions else 0
    concentration_pct = (max_single / total_notional * 100) if total_notional > 0 else 0

    return {
        "total_positions": len(open_positions),
        "total_leverage": round(total_notional / equity, 2) if equity > 0 else 0,
        "long_count": long_count,
        "short_count": short_count,
        "net_exposure_pct": round(net_exposure_pct, 1),
        "concentration_pct": round(concentration_pct, 1),
        "total_notional": round(total_notional, 2),
        "positions": positions_summary,
    }


# ── Portfolio-Level Decisions ─────────────────────────────────


VALID_PORTFOLIO_ACTIONS = {"rebalance", "reduce_risk", "increase_risk", None}


def apply_portfolio_adjustment(
    action: Optional[str],
    portfolio: Dict[str, Any],
    max_positions: int = 6,
    max_concentration_pct: float = 40.0,
) -> Dict[str, Any]:
    """Apply portfolio-level adjustments based on LLM recommendation.

    Returns adjustment instructions for the main loop.
    """
    if action is None:
        return {"adjustment": None}

    if action == "reduce_risk":
        # Scale down all open position sizes for new entries
        current_leverage = portfolio.get("total_leverage", 0)
        if current_leverage > 2.0:
            scale = 0.5
        elif current_leverage > 1.0:
            scale = 0.7
        else:
            scale = 1.0

        logger.info(
            f"[PORTFOLIO] reduce_risk: new trade sizes scaled to {scale:.0%} "
            f"(total_leverage={current_leverage:.2f}x)"
        )
        return {
            "adjustment": "reduce_risk",
            "new_trade_scale": scale,
            "reason": f"portfolio leverage {current_leverage:.2f}x",
        }

    elif action == "rebalance":
        # Suggest which positions to trim
        positions = portfolio.get("positions", [])
        concentration = portfolio.get("concentration_pct", 0)

        if concentration > max_concentration_pct:
            # Find most concentrated position
            largest = max(positions, key=lambda p: abs(p.get("pnl", 0)), default=None)
            if largest:
                logger.info(
                    f"[PORTFOLIO] rebalance: consider trimming {largest['s']} "
                    f"(concentration={concentration:.1f}%)"
                )
                return {
                    "adjustment": "rebalance",
                    "trim_symbol": largest["s"],
                    "concentration_pct": concentration,
                }

        return {"adjustment": "rebalance", "reason": "no action needed"}

    elif action == "increase_risk":
        # Allow slightly larger positions
        logger.info("[PORTFOLIO] increase_risk: allowing 1.2x position sizes")
        return {
            "adjustment": "increase_risk",
            "new_trade_scale": 1.2,
        }

    return {"adjustment": None}


def get_correlation_guard(
    open_positions: Dict[str, Position],
    new_side: str,
    max_same_direction: int = 4,
) -> tuple:
    """Check if adding a new position in the given direction would violate
    the correlation guard (too many same-direction positions).

    Returns (allowed, reason).
    """
    same_count = sum(
        1 for pos in open_positions.values()
        if pos.side == new_side and pos.state != "CLOSED"
    )

    if same_count >= max_same_direction:
        return False, f"Too many {new_side} positions ({same_count}/{max_same_direction})"
    return True, ""
