"""
Portfolio-Level Risk Budgeting.

Instead of sizing each trade independently, allocate from a daily risk budget.
This prevents over-concentration and ensures correlated positions don't
stack up to blow the account.

Architecture:
  PortfolioRiskBudget
    ├── allocate()        — Request risk budget for a new trade
    ├── release()         — Return budget when trade closes
    ├── available()       — How much risk budget remains
    ├── heat_map()        — Current exposure by direction/asset
    └── drawdown_adjust() — Reduce budget after losses

Key rules:
  - Daily risk budget = % of equity (default 30%)
  - Each trade consumes budget = risk_amount
  - Correlated trades consume extra (correlation penalty)
  - After losses, budget shrinks (drawdown scaling)
  - After wins, budget slowly recovers
  - Maximum per-direction exposure (no all-in long)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger("bot.execution.portfolio_risk")


# Known correlations between assets (approximate, from historical data)
_ASSET_CORRELATIONS: Dict[Tuple[str, str], float] = {
    ("BTC", "SOL"): 0.80,
    ("BTC", "HYPE"): 0.70,
    ("SOL", "HYPE"): 0.65,
    ("BTC", "ETH"): 0.90,
    ("SOL", "ETH"): 0.75,
}


def get_correlation(asset1: str, asset2: str) -> float:
    """Get correlation between two assets. Returns 0 if unknown."""
    if asset1 == asset2:
        return 1.0
    key = tuple(sorted([asset1, asset2]))
    return _ASSET_CORRELATIONS.get(key, 0.3)  # Default mild correlation for crypto


@dataclass
class BudgetAllocation:
    """A budget allocation for a single trade."""
    trade_id: str
    symbol: str
    side: str           # "LONG" or "SHORT"
    risk_amount: float  # $ at risk
    allocated_at: float # timestamp
    correlation_penalty: float  # Extra budget consumed due to correlation


@dataclass
class RiskBudgetStatus:
    """Current state of the risk budget."""
    daily_budget: float         # Total daily budget
    used: float                 # Currently allocated
    available: float            # Remaining
    utilization_pct: float      # used / daily_budget
    active_allocations: int     # Number of open trades
    drawdown_mult: float        # Current drawdown multiplier (1.0 = normal)
    long_exposure: float        # Total $ at risk on long side
    short_exposure: float       # Total $ at risk on short side
    net_direction: str          # "LONG", "SHORT", or "NEUTRAL"


class PortfolioRiskBudget:
    """Manages a daily risk budget across all positions."""

    def __init__(
        self,
        daily_budget_pct: float = 0.30,     # 30% of equity per day
        max_direction_pct: float = 0.70,     # Max 70% budget in one direction
        correlation_penalty_mult: float = 0.3,  # 30% extra budget for correlated trades
        drawdown_floor: float = 0.5,         # Min 50% of budget even after losses
        recovery_rate: float = 0.10,         # Recover 10% of lost budget per win
    ):
        self.daily_budget_pct = daily_budget_pct
        self.max_direction_pct = max_direction_pct
        self.correlation_penalty_mult = correlation_penalty_mult
        self.drawdown_floor = drawdown_floor
        self.recovery_rate = recovery_rate

        self._allocations: Dict[str, BudgetAllocation] = {}
        self._drawdown_mult: float = 1.0  # Reduces after losses
        self._daily_reset_date: Optional[str] = None
        self._consecutive_losses: int = 0

    def _reset_if_new_day(self, equity: float) -> None:
        """Reset daily budget at the start of each new day."""
        from datetime import date
        today = str(date.today())
        if self._daily_reset_date != today:
            self._daily_reset_date = today
            # Don't reset allocations (open positions carry over)
            # But do reset the daily budget ceiling
            logger.debug(f"[RISK-BUDGET] New day, budget reset. Equity=${equity:.2f}")

    def get_daily_budget(self, equity: float) -> float:
        """Get the current daily risk budget in dollars."""
        base = equity * self.daily_budget_pct
        adjusted = base * self._drawdown_mult
        return max(adjusted, equity * self.daily_budget_pct * self.drawdown_floor)

    def get_used_budget(self) -> float:
        """Total risk currently allocated to open trades."""
        return sum(
            a.risk_amount + a.correlation_penalty
            for a in self._allocations.values()
        )

    def get_direction_exposure(self) -> Tuple[float, float]:
        """Get (long_exposure, short_exposure) in risk dollars."""
        long_exp = sum(a.risk_amount for a in self._allocations.values() if a.side == "LONG")
        short_exp = sum(a.risk_amount for a in self._allocations.values() if a.side == "SHORT")
        return long_exp, short_exp

    def _compute_correlation_penalty(self, symbol: str, side: str, risk_amount: float) -> float:
        """Compute extra budget consumed due to correlation with existing positions."""
        penalty = 0.0
        for alloc in self._allocations.values():
            if alloc.side == side:  # Same direction = correlation matters
                corr = get_correlation(symbol, alloc.symbol)
                # Penalty = correlation × penalty_mult × smaller of the two risks
                penalty += corr * self.correlation_penalty_mult * min(risk_amount, alloc.risk_amount)
        return penalty

    def can_allocate(
        self, symbol: str, side: str, risk_amount: float, equity: float
    ) -> Tuple[bool, str]:
        """Check if a trade can be allocated from the budget.

        Returns (allowed, reason).
        """
        self._reset_if_new_day(equity)

        budget = self.get_daily_budget(equity)
        used = self.get_used_budget()
        penalty = self._compute_correlation_penalty(symbol, side, risk_amount)
        total_needed = risk_amount + penalty

        if used + total_needed > budget:
            return False, (
                f"Budget exceeded: need ${total_needed:.2f} "
                f"(risk=${risk_amount:.2f} + corr=${penalty:.2f}), "
                f"only ${budget - used:.2f} available of ${budget:.2f}"
            )

        # Check direction limit
        long_exp, short_exp = self.get_direction_exposure()
        direction_budget = budget * self.max_direction_pct

        if side == "LONG" and long_exp + risk_amount > direction_budget:
            return False, (
                f"Long exposure limit: ${long_exp + risk_amount:.2f} "
                f"would exceed ${direction_budget:.2f} ({self.max_direction_pct:.0%} of budget)"
            )
        if side == "SHORT" and short_exp + risk_amount > direction_budget:
            return False, (
                f"Short exposure limit: ${short_exp + risk_amount:.2f} "
                f"would exceed ${direction_budget:.2f}"
            )

        return True, "OK"

    def allocate(
        self, trade_id: str, symbol: str, side: str, risk_amount: float, equity: float
    ) -> Optional[BudgetAllocation]:
        """Allocate risk budget for a trade. Returns allocation or None if denied."""
        allowed, reason = self.can_allocate(symbol, side, risk_amount, equity)
        if not allowed:
            logger.info(f"[RISK-BUDGET] Denied {symbol} {side} ${risk_amount:.2f}: {reason}")
            return None

        penalty = self._compute_correlation_penalty(symbol, side, risk_amount)
        alloc = BudgetAllocation(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            risk_amount=risk_amount,
            allocated_at=time.time(),
            correlation_penalty=penalty,
        )
        self._allocations[trade_id] = alloc

        budget = self.get_daily_budget(equity)
        used = self.get_used_budget()
        logger.info(
            f"[RISK-BUDGET] Allocated {symbol} {side} "
            f"risk=${risk_amount:.2f} penalty=${penalty:.2f} | "
            f"Budget: ${used:.2f}/${budget:.2f} ({used/budget:.0%})"
        )
        return alloc

    def release(self, trade_id: str, won: bool) -> Optional[BudgetAllocation]:
        """Release budget when a trade closes. Adjusts drawdown multiplier."""
        alloc = self._allocations.pop(trade_id, None)
        if alloc is None:
            return None

        if won:
            self._consecutive_losses = 0
            # Recover some drawdown
            if self._drawdown_mult < 1.0:
                self._drawdown_mult = min(1.0, self._drawdown_mult + self.recovery_rate)
        else:
            self._consecutive_losses += 1
            # Reduce budget after losses
            # -5% per loss, floored at drawdown_floor
            reduction = 0.05 * self._consecutive_losses
            self._drawdown_mult = max(
                self.drawdown_floor,
                self._drawdown_mult - reduction
            )

        logger.info(
            f"[RISK-BUDGET] Released {alloc.symbol} {alloc.side} "
            f"{'WIN' if won else 'LOSS'} | "
            f"drawdown_mult={self._drawdown_mult:.2f} streak={-self._consecutive_losses if not won else 0}"
        )
        return alloc

    def get_status(self, equity: float) -> RiskBudgetStatus:
        """Get current budget status."""
        budget = self.get_daily_budget(equity)
        used = self.get_used_budget()
        long_exp, short_exp = self.get_direction_exposure()

        if long_exp > short_exp * 1.5:
            direction = "LONG"
        elif short_exp > long_exp * 1.5:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        return RiskBudgetStatus(
            daily_budget=round(budget, 2),
            used=round(used, 2),
            available=round(max(0, budget - used), 2),
            utilization_pct=round(used / budget * 100, 1) if budget > 0 else 0,
            active_allocations=len(self._allocations),
            drawdown_mult=round(self._drawdown_mult, 2),
            long_exposure=round(long_exp, 2),
            short_exposure=round(short_exp, 2),
            net_direction=direction,
        )
