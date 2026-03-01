"""
Risk manager with circuit breakers.
Protects against catastrophic losses by halting trading when thresholds are breached.

Circuit breakers:
1. Daily loss limit (default 5% of equity)
2. Consecutive loss limit (default 5 losses in a row)
3. Drawdown from peak equity (default 10%)
4. Cooldown period after circuit breaker triggers
"""

import csv
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.execution.risk")

_SAFETY_LOG_DIR = os.path.join("data", "logs")
_SAFETY_LOG_FILE = os.path.join(_SAFETY_LOG_DIR, "safety_events.csv")
_SAFETY_HEADERS = ["timestamp", "event_type", "reason", "details"]


def _log_safety_event(event_type: str, reason: str, details: Dict[str, Any] = None):
    """Log a safety event to data/logs/safety_events.csv."""
    os.makedirs(_SAFETY_LOG_DIR, exist_ok=True)
    if not os.path.exists(_SAFETY_LOG_FILE):
        with open(_SAFETY_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_SAFETY_HEADERS)
    try:
        import json
        with open(_SAFETY_LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),
                event_type, reason, json.dumps(details or {}),
            ])
    except Exception as e:
        logger.warning(f"Failed to log safety event: {e}")


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
        _log_safety_event("circuit_breaker", reason, {
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
        })

    def is_trading_allowed(self, confidence: float = 0.0,
                            cb_conf_override_pct: float = 0.92) -> bool:
        """Check if trading is currently allowed.

        When tripped, still allows trades with confidence >= cb_conf_override_pct.
        This prevents total shutdown while maintaining safety.
        """
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

        # High-confidence override: allow exceptional setups through
        if confidence >= cb_conf_override_pct * 100:
            logger.info(
                f"[SAFETY] Circuit breaker active but allowing trade: "
                f"confidence {confidence:.0f}% >= {cb_conf_override_pct:.0%} override"
            )
            return True

        return False

    def get_override_constraints(self, confidence: float = 0.0) -> Dict[str, Any]:
        """When CB is overridden by high confidence, return risk constraints.

        During a CB override, we still allow the trade but with REDUCED risk:
          - Max leverage capped at 2x (not the usual 25x)
          - Position size halved (0.5x multiplier)

        This prevents a single high-confidence override from taking
        full-size risk during a drawdown event.

        Returns:
            Dict with max_leverage, size_multiplier, constrained flag, and reason.
            If CB is not tripped, returns unconstrained defaults.
        """
        if not self.tripped:
            return {
                "max_leverage": 25.0,
                "size_multiplier": 1.0,
                "constrained": False,
                "reason": "",
            }

        return {
            "max_leverage": 2.0,
            "size_multiplier": 0.5,
            "constrained": True,
            "reason": f"circuit_breaker_override: {self.trip_reason}",
        }

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

    def can_open_position(self, current_open: int, confidence: float = 0.0,
                          cb_conf_override_pct: float = 0.92) -> bool:
        """Check if we can open a new position.

        When circuit breaker is tripped, only high-confidence trades
        (>= cb_conf_override_pct) are allowed through.
        """
        if not self.circuit_breaker.is_trading_allowed(
            confidence=confidence, cb_conf_override_pct=cb_conf_override_pct
        ):
            if confidence > 0:
                logger.info(
                    f"[SAFETY] Circuit breaker active: only high-confidence trades allowed "
                    f"(need {cb_conf_override_pct:.0%}, got {confidence:.0f}%)"
                )
            return False
        if current_open >= self.max_open_positions:
            return False
        return True

    def calculate_qty(self, entry: float, stop_loss: float,
                       leverage: float = 1.0, risk_multiplier: float = 1.0,
                       symbol: str = "") -> float:
        """Calculate position quantity based on fixed-risk sizing.

        Formula (keeps dollar risk constant regardless of leverage):
          risk_amount = equity * risk_per_trade_pct
          stop_distance = abs(entry - SL)
          qty = risk_amount / (stop_distance * leverage)

        risk_multiplier is capped at 1.5 to prevent oversizing.
        """
        stop_width = abs(entry - stop_loss)
        if stop_width <= 0:
            return 0.0
        # Cap risk_multiplier to prevent oversizing (was up to 3.5x before)
        capped_rm = min(max(risk_multiplier, 0.1), 1.5)
        risk_usd = self.equity * self.risk_per_trade * capped_rm
        effective_leverage = max(leverage, 1.0)
        qty = risk_usd / (stop_width * effective_leverage)
        logger.info(
            f"[SIZE] {symbol or '?'} risk=${risk_usd:.2f} "
            f"stop={stop_width:.6f} lev={effective_leverage:.1f}x "
            f"rm={capped_rm:.2f} qty={qty:.6f}"
        )
        return qty

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
