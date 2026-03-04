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
        max_cb_overrides: int = 2,
    ):
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_cb_overrides = max_cb_overrides
        self.max_drawdown_pct = max_drawdown_pct
        self.cooldown_minutes = cooldown_minutes

        # State
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.peak_equity = 0.0
        self.start_of_day_equity = 0.0  # Reset at start of each trading day
        self.tripped = False
        self.trip_time: Optional[float] = None
        self.trip_reason: str = ""
        self.last_reset_date: Optional[str] = None
        self._override_count = 0  # Track CB overrides per trip

    def _maybe_reset_daily(self, equity: float = 0.0, sim_time: Optional[datetime] = None):
        ref_time = sim_time or datetime.now(timezone.utc)
        today = ref_time.strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.start_of_day_equity = equity if equity > 0 else self.peak_equity
            self.last_reset_date = today

    def record_trade(self, pnl: float, equity: float, sim_time: Optional[datetime] = None):
        """Record a completed trade's PnL for circuit breaker evaluation.

        Args:
            pnl: Trade PnL (positive = profit, negative = loss)
            equity: Current equity after this trade
            sim_time: Optional simulation timestamp (for backtest mode).
                      When provided, daily resets and cooldown use sim_time
                      instead of wall-clock time.
        """
        self._maybe_reset_daily(equity, sim_time=sim_time)
        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if equity > self.peak_equity:
            self.peak_equity = equity

        self._check_breakers(equity, sim_time=sim_time)

    def _check_breakers(self, equity: float, sim_time: Optional[datetime] = None):
        """Check if any circuit breaker should trigger."""
        if self.tripped:
            return

        # 1. Daily loss limit — use CURRENT equity, not peak.
        # During drawdowns, losses are a bigger % of actual capital.
        # Using peak equity makes the breaker too lenient when it matters most.
        base_equity = equity if equity > 0 else self.start_of_day_equity or self.peak_equity
        if base_equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / base_equity
            if self.daily_pnl < 0 and daily_loss_pct >= self.daily_loss_limit_pct:
                self._trip(f"Daily loss {daily_loss_pct:.1%} >= {self.daily_loss_limit_pct:.1%} limit", sim_time=sim_time)
                return

        # 2. Consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._trip(f"{self.consecutive_losses} consecutive losses >= {self.max_consecutive_losses} limit", sim_time=sim_time)
            return

        # 3. Drawdown from peak
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._trip(f"Drawdown {drawdown:.1%} >= {self.max_drawdown_pct:.1%} limit", sim_time=sim_time)
                return

    def _trip(self, reason: str, sim_time: Optional[datetime] = None):
        self.tripped = True
        self.trip_time = time.time()
        self._trip_sim_time = sim_time  # For backtest cooldown tracking
        self.trip_reason = reason
        logger.warning(f"CIRCUIT BREAKER TRIPPED: {reason}")
        _log_safety_event("circuit_breaker", reason, {
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
        })

    def is_trading_allowed(self, confidence: float = 0.0,
                            cb_conf_override_pct: float = 0.92,
                            max_overrides: Optional[int] = None,
                            sim_time: Optional[datetime] = None) -> bool:
        """Check if trading is currently allowed.

        When tripped, allows up to max_overrides trades with
        confidence >= cb_conf_override_pct. After that, hard-locked until cooldown.

        Args:
            max_overrides: Override limit per trip. Defaults to self.max_cb_overrides.
            sim_time: Optional simulation timestamp. When provided, cooldown is
                      checked against sim_time instead of wall-clock time.
        """
        if max_overrides is None:
            max_overrides = self.max_cb_overrides
        if not self.tripped:
            return True

        # Check cooldown — use sim_time elapsed if provided, else wall-clock
        if self.trip_time:
            if sim_time is not None:
                # In backtest: trip_time is stored as wall-clock, but we track
                # sim elapsed via _trip_sim_time set at trip time
                trip_sim = getattr(self, "_trip_sim_time", None)
                if trip_sim and (sim_time - trip_sim).total_seconds() >= self.cooldown_minutes * 60:
                    self.tripped = False
                    self.trip_reason = ""
                    self.trip_time = None
                    self._trip_sim_time = None
                    self.consecutive_losses = 0
                    self._override_count = 0
                    logger.info("Circuit breaker cooldown complete (sim time), trading resumed")
                    return True
            elif (time.time() - self.trip_time) >= self.cooldown_minutes * 60:
                self.tripped = False
                self.trip_reason = ""
                self.trip_time = None
                self.consecutive_losses = 0
                self._override_count = 0
                logger.info("Circuit breaker cooldown complete, trading resumed")
                return True

        # High-confidence override: allow exceptional setups through
        # but limit the number of overrides per trip to prevent CB bypass
        if confidence >= cb_conf_override_pct * 100:
            if self._override_count >= max_overrides:
                logger.warning(
                    f"[SAFETY] CB override limit reached ({max_overrides}), "
                    f"hard-locked until cooldown"
                )
                return False
            self._override_count += 1
            logger.info(
                f"[SAFETY] Circuit breaker override {self._override_count}/{max_overrides}: "
                f"confidence {confidence:.0f}% >= {cb_conf_override_pct:.0%}"
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
        self._trip_sim_time = None
        self.consecutive_losses = 0
        self._override_count = 0  # Reset override counter so new overrides are allowed
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
        max_risk_multiplier: float = 1.5,
    ):
        self.equity = starting_equity
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_portfolio_leverage = max_portfolio_leverage
        self.max_risk_multiplier = max_risk_multiplier
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.circuit_breaker.peak_equity = starting_equity

    def can_open_position(self, current_open: int, confidence: float = 0.0,
                          cb_conf_override_pct: float = 0.92,
                          sim_time: Optional[datetime] = None) -> bool:
        """Check if we can open a new position.

        When circuit breaker is tripped, only high-confidence trades
        (>= cb_conf_override_pct) are allowed through.
        """
        if not self.circuit_breaker.is_trading_allowed(
            confidence=confidence, cb_conf_override_pct=cb_conf_override_pct,
            sim_time=sim_time,
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
                       symbol: str = "", slippage_bps: int = 0,
                       risk_per_trade_override: float = 0.0) -> float:
        """Calculate position quantity based on fixed-risk sizing.

        Formula (keeps dollar risk constant regardless of leverage):
          risk_amount = equity * risk_per_trade_pct
          effective_stop = abs(entry - SL) + slippage_spread
          qty = risk_amount / (effective_stop * leverage)

        Guards:
        - risk_multiplier capped at 1.5
        - Minimum stop width enforced (0.3% of entry)
        - Notional value capped at equity * leverage * 2
        - Slippage/spread added to stop distance for realistic sizing
        """
        stop_width = abs(entry - stop_loss)
        if entry <= 0:
            return 0.0

        # Add estimated slippage to stop distance for spread-aware sizing
        slippage_spread = entry * (slippage_bps / 10000.0)
        effective_stop = stop_width + slippage_spread

        # Enforce minimum stop width to prevent near-zero stops
        min_width = entry * 0.003  # 0.3% of entry
        if effective_stop < min_width:
            logger.warning(
                f"[SIZE] {symbol or '?'} effective stop {effective_stop:.6f} < min "
                f"{min_width:.6f} (0.3% of {entry:.2f}), rejecting"
            )
            return 0.0

        # Cap risk_multiplier to prevent oversizing (was up to 3.5x before)
        capped_rm = min(max(risk_multiplier, 0.1), self.max_risk_multiplier)
        effective_risk_pct = risk_per_trade_override if risk_per_trade_override > 0 else self.risk_per_trade
        risk_usd = self.equity * effective_risk_pct * capped_rm
        effective_leverage = max(leverage, 1.0)
        qty = risk_usd / (effective_stop * effective_leverage)

        # Notional cap: prevent position from exceeding reasonable bounds
        notional = qty * entry
        max_notional = self.equity * effective_leverage * 2
        if notional > max_notional:
            qty = max_notional / entry
            logger.warning(
                f"[SIZE] {symbol or '?'} notional capped: "
                f"${notional:.0f} > max ${max_notional:.0f}"
            )
        logger.info(
            f"[SIZE] {symbol or '?'} risk=${risk_usd:.2f} "
            f"stop={stop_width:.6f}+slip={slippage_spread:.6f} lev={effective_leverage:.1f}x "
            f"rm={capped_rm:.2f} qty={qty:.6f}"
        )
        return qty

    def update_equity(self, pnl: float, sim_time: Optional[datetime] = None):
        """Update equity after a trade closes.

        Args:
            pnl: Net PnL from the trade (after fees)
            sim_time: Optional simulation timestamp for backtest mode
        """
        self.equity += pnl
        self.circuit_breaker.record_trade(pnl, self.equity, sim_time=sim_time)

    def get_status(self) -> Dict[str, Any]:
        return {
            "equity": self.equity,
            "risk_per_trade": self.risk_per_trade,
            "risk_usd": self.equity * self.risk_per_trade,
            "max_open_positions": self.max_open_positions,
            "circuit_breaker": self.circuit_breaker.get_status(),
        }
