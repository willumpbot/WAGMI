"""
Risk manager with circuit breakers.
Protects against catastrophic losses by halting trading when thresholds are breached.

Circuit breakers:
1. Daily loss limit (default 5% of equity)
2. Consecutive loss limit (default 5 losses in a row)
3. Drawdown from peak equity (default 10%)
4. Cooldown period after circuit breaker triggers
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.execution.risk")


class CircuitBreaker:
    """Monitors for dangerous conditions and halts trading."""

    def __init__(
        self,
        daily_loss_limit_pct: float = 0.05,
        max_consecutive_losses: int = 5,
        max_drawdown_pct: float = 0.10,
        cooldown_minutes: int = 60,
    ):
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_drawdown_pct = max_drawdown_pct
        self.cooldown_minutes = cooldown_minutes

        # State
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.peak_equity = 0.0
        self.tripped = False
        self.trip_time: Optional[float] = None
        self.trip_reason: str = ""
        self.last_reset_date: Optional[str] = None

    def _maybe_reset_daily(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.last_reset_date = today

    def record_trade(self, pnl: float, equity: float):
        """Record a completed trade's PnL for circuit breaker evaluation."""
        self._maybe_reset_daily()
        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if equity > self.peak_equity:
            self.peak_equity = equity

        self._check_breakers(equity)

    def _check_breakers(self, equity: float):
        """Check if any circuit breaker should trigger."""
        if self.tripped:
            return

        # 1. Daily loss limit
        if self.peak_equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.peak_equity
            if self.daily_pnl < 0 and daily_loss_pct >= self.daily_loss_limit_pct:
                self._trip(f"Daily loss {daily_loss_pct:.1%} >= {self.daily_loss_limit_pct:.1%} limit")
                return

        # 2. Consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._trip(f"{self.consecutive_losses} consecutive losses >= {self.max_consecutive_losses} limit")
            return

        # 3. Drawdown from peak
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._trip(f"Drawdown {drawdown:.1%} >= {self.max_drawdown_pct:.1%} limit")
                return

    def _trip(self, reason: str):
        self.tripped = True
        self.trip_time = time.time()
        self.trip_reason = reason
        logger.warning(f"CIRCUIT BREAKER TRIPPED: {reason}")

    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed."""
        if not self.tripped:
            return True

        # Check cooldown
        if self.trip_time and (time.time() - self.trip_time) >= self.cooldown_minutes * 60:
            self.tripped = False
            self.trip_reason = ""
            self.trip_time = None
            self.consecutive_losses = 0
            logger.info("Circuit breaker cooldown complete, trading resumed")
            return True

        return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "tripped": self.tripped,
            "reason": self.trip_reason,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "peak_equity": self.peak_equity,
            "cooldown_remaining_s": max(
                0,
                (self.cooldown_minutes * 60) - (time.time() - (self.trip_time or time.time()))
            ) if self.tripped else 0,
        }

    def force_reset(self):
        """Manual override to reset circuit breaker."""
        self.tripped = False
        self.trip_reason = ""
        self.trip_time = None
        self.consecutive_losses = 0
        logger.info("Circuit breaker force reset")


class RiskManager:
    """
    Overall risk management: position sizing, exposure limits, and circuit breakers.
    """

    def __init__(
        self,
        starting_equity: float = 10000.0,
        risk_per_trade: float = 0.015,
        max_open_positions: int = 6,
        max_portfolio_leverage: float = 3.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.equity = starting_equity
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_portfolio_leverage = max_portfolio_leverage
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.circuit_breaker.peak_equity = starting_equity

    def can_open_position(self, current_open: int) -> bool:
        """Check if we can open a new position."""
        if not self.circuit_breaker.is_trading_allowed():
            return False
        if current_open >= self.max_open_positions:
            return False
        return True

    def calculate_qty(self, entry: float, stop_loss: float) -> float:
        """Calculate position quantity based on risk per trade."""
        stop_width = abs(entry - stop_loss)
        if stop_width <= 0:
            return 0.0
        risk_usd = self.equity * self.risk_per_trade
        return risk_usd / stop_width

    def update_equity(self, pnl: float):
        """Update equity after a trade closes."""
        self.equity += pnl
        self.circuit_breaker.record_trade(pnl, self.equity)

    def get_status(self) -> Dict[str, Any]:
        return {
            "equity": self.equity,
            "risk_per_trade": self.risk_per_trade,
            "risk_usd": self.equity * self.risk_per_trade,
            "max_open_positions": self.max_open_positions,
            "circuit_breaker": self.circuit_breaker.get_status(),
        }
