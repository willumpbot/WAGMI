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
        max_drawdown_pct: float = None,
        cooldown_minutes: int = 60,
        max_cb_overrides: int = 0,
    ):
        if max_drawdown_pct is None:
            max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "0.10"))
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
        self._trip_count = 0  # Total trips for log deduplication
        self.post_cooldown_caution = 0  # Trades remaining at reduced size after CB cooldown

        # Session-level drawdown protection (fixes peak_equity reset bug).
        # The existing cooldown code resets peak_equity to current equity after
        # each CB cooldown, allowing cumulative DD to exceed the limit:
        # $10K → -15% CB → peak resets to $8,500 → -15% CB → cumulative -27.75%.
        # session_peak_equity is set once at session start and NEVER resets.
        self.session_peak_equity: float = 0.0
        self.max_session_drawdown_pct: float = float(
            os.getenv("MAX_SESSION_DRAWDOWN_PCT", "0.20")
        )  # 20% cumulative hard stop — cannot be bypassed by cooldown resets
        self._session_halted: bool = False

    def start_session(self, equity: float):
        """Set session peak equity once at trading session start.

        This value NEVER resets during the session, preventing the cumulative
        drawdown bug where peak_equity resets after cooldown.
        """
        if self.session_peak_equity <= 0:
            self.session_peak_equity = equity
            self._session_halted = False
            logger.info(f"Session started: peak_equity=${equity:.2f}, "
                        f"max_session_dd={self.max_session_drawdown_pct:.0%}")

    def reset(self):
        """Full reset of circuit breaker state. Used between backtest symbols."""
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.tripped = False
        self.trip_time = None
        self._trip_sim_time = None
        self.trip_reason = ""
        self._override_count = 0
        # Note: peak_equity is NOT reset here — caller should set it explicitly

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

        # Auto-initialize session peak if start_session() wasn't called
        if self.session_peak_equity <= 0 and equity > 0:
            self.session_peak_equity = equity

        # Decrement post-cooldown caution counter
        if self.post_cooldown_caution > 0:
            self.post_cooldown_caution -= 1
            logger.info(f"Post-cooldown caution: {self.post_cooldown_caution} trades remaining at reduced size")

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if equity > self.peak_equity:
            self.peak_equity = equity

        self._check_breakers(equity, sim_time=sim_time)

    def check_mtm_breakers(self, mtm_equity: float, sim_time: Optional[datetime] = None):
        """Check circuit breakers using mark-to-market equity (realized + unrealized).

        Unlike _check_breakers (which runs on trade close), this runs on price
        updates to catch drawdowns from open losing positions. Only checks the
        drawdown-from-peak breaker — daily PnL and consecutive losses are
        trade-close concepts.

        Also updates peak_equity continuously (not just on trade closes).
        """
        if self.tripped:
            return

        # Update peak equity continuously — captures unrealized highs
        if mtm_equity > self.peak_equity:
            self.peak_equity = mtm_equity

        # Drawdown from peak (includes open position losses)
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - mtm_equity) / self.peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._trip(
                    f"MTM drawdown {drawdown:.1%} >= {self.max_drawdown_pct:.1%} limit "
                    f"(includes unrealized PnL)",
                    sim_time=sim_time,
                )

    def _check_breakers(self, equity: float, sim_time: Optional[datetime] = None):
        """Check if any circuit breaker should trigger.

        FAIL-SAFE: If any exception occurs during checks, assume breakers
        are tripped (deny trading) rather than silently allowing it.
        """
        try:
            self._check_breakers_inner(equity, sim_time=sim_time)
        except Exception as e:
            # FAIL-SAFE: On any error, trip the breaker to prevent trading
            logger.error(
                f"CIRCUIT BREAKER EXCEPTION — tripping as fail-safe: {e}"
            )
            self._trip(f"Exception in breaker check (fail-safe): {e}", sim_time=sim_time)
            _log_safety_event("cb_exception_failsafe", str(e), {
                "equity": equity,
                "tripped_reason": "exception_failsafe",
            })

    def _check_breakers_inner(self, equity: float, sim_time: Optional[datetime] = None):
        """Inner breaker checks. Exceptions caught by _check_breakers."""
        if self._session_halted:
            return  # Session permanently halted — no recovery via cooldown

        if self.tripped:
            return

        # 0. Cumulative session drawdown — NEVER resets, even after cooldown.
        # This prevents: $10K → -15% CB → peak resets to $8.5K → -15% again = -27.75% total.
        if self.session_peak_equity > 0:
            session_dd = (self.session_peak_equity - equity) / self.session_peak_equity
            if session_dd >= self.max_session_drawdown_pct:
                self._trip(
                    f"Session DD {session_dd:.1%} >= {self.max_session_drawdown_pct:.1%} — HALTED",
                    sim_time=sim_time,
                )
                self._session_halted = True  # Cooldown cannot resume session
                _log_safety_event("session_halt", f"Cumulative DD {session_dd:.1%}", {
                    "session_peak": self.session_peak_equity,
                    "current_equity": equity,
                    "session_dd_pct": round(session_dd * 100, 2),
                })
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
        self._trip_count += 1
        # Log first few trips at WARNING, then throttle to reduce noise
        if self._trip_count <= 3 or self._trip_count % 10 == 0:
            logger.warning(f"CIRCUIT BREAKER TRIPPED (#{self._trip_count}): {reason}")
        else:
            logger.debug(f"CIRCUIT BREAKER TRIPPED (#{self._trip_count}): {reason}")
        _log_safety_event("circuit_breaker", reason, {
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
        })

    def is_trading_allowed(self, confidence: float = 0.0,
                            cb_conf_override_pct: float = 0.92,
                            max_overrides: Optional[int] = None,
                            sim_time: Optional[datetime] = None,
                            equity: float = 0.0) -> bool:
        """Check if trading is currently allowed.

        When tripped, allows up to max_overrides trades with
        confidence >= cb_conf_override_pct. After that, hard-locked until cooldown.

        Args:
            max_overrides: Override limit per trip. Defaults to self.max_cb_overrides.
            sim_time: Optional simulation timestamp. When provided, cooldown is
                      checked against sim_time instead of wall-clock time.
        """
        # Reset daily PnL on day boundary even if no trade closed today.
        # Without this, daily_pnl accumulates across sim-days in backtests.
        if sim_time is not None:
            self._maybe_reset_daily(sim_time=sim_time)

        if max_overrides is None:
            max_overrides = self.max_cb_overrides

        # Session halted = permanent stop. No overrides, no cooldown recovery.
        if self._session_halted:
            return False

        if not self.tripped:
            return True

        # Check cooldown — use sim_time elapsed if provided, else wall-clock
        if self.trip_time:
            cooldown_elapsed = False
            if sim_time is not None:
                trip_sim = getattr(self, "_trip_sim_time", None)
                if trip_sim and (sim_time - trip_sim).total_seconds() >= self.cooldown_minutes * 60:
                    cooldown_elapsed = True
            elif (time.time() - self.trip_time) >= self.cooldown_minutes * 60:
                cooldown_elapsed = True

            if cooldown_elapsed:
                # Reset trip state and allow trading again.
                # Instead of re-tripping (which causes permanent lockout),
                # enter "caution mode" with reduced position sizes for
                # the next 2 trades. This lets the bot recover with
                # smaller bets rather than sitting out entirely.
                self.consecutive_losses = 0
                self._override_count = 0
                self.tripped = False
                self.trip_time = None
                self._trip_sim_time = None
                self.trip_reason = ""
                self.post_cooldown_caution = 4  # Next 4 trades at half size
                # UNCONDITIONALLY reset peak_equity to current equity to prevent immediate re-trip.
                # Without this, the drawdown from the old peak is still >10% and
                # check_mtm_breakers() re-trips on the very next candle.
                # Note: session_peak_equity (cumulative max) is NOT reset, only the
                # daily peak_equity (used for per-breaker drawdown checks).
                old_peak = self.peak_equity
                self.peak_equity = equity if equity > 0 else self.peak_equity
                logger.info(
                    f"Circuit breaker cooldown complete, peak_equity reset "
                    f"${old_peak:.2f} → ${self.peak_equity:.2f} (caution mode: 4 trades at reduced size)"
                )
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
            # Post-cooldown caution: reduce size for first N trades after CB reset
            if self.post_cooldown_caution > 0:
                return {
                    "max_leverage": 2.0,
                    "size_multiplier": 0.5,
                    "constrained": True,
                    "reason": f"post_cooldown_caution: {self.post_cooldown_caution} trades remaining at reduced size",
                }
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
        risk_per_trade: float = 0.02,
        max_open_positions: int = 3,
        max_portfolio_leverage: float = 5.0,
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
        # Last sizing breakdown for attribution/debugging
        self.last_sizing_breakdown: Dict[str, Any] = {}

    def can_open_position(self, current_open: int, confidence: float = 0.0,
                          cb_conf_override_pct: float = 0.92,
                          sim_time: Optional[datetime] = None) -> bool:
        """Check if we can open a new position.

        When circuit breaker is tripped, only high-confidence trades
        (>= cb_conf_override_pct) are allowed through.
        """
        if not self.circuit_breaker.is_trading_allowed(
            confidence=confidence, cb_conf_override_pct=cb_conf_override_pct,
            sim_time=sim_time, equity=self.equity,
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
                       risk_per_trade_override: float = 0.0,
                       skip_notional_cap: bool = False) -> float:
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

        # Add estimated slippage AND round-trip fees to stop distance
        # This prevents sizing as if 100% of stop distance is available for risk,
        # when in reality fees consume a portion of every stop-out
        slippage_spread = entry * (slippage_bps / 10000.0)
        from trading_config import TradingConfig as _TC2
        _fee_bps = _TC2().taker_fee_bps
        round_trip_fee_width = entry * (_fee_bps * 2 / 10000.0)  # Entry + exit fee
        effective_stop = stop_width + slippage_spread + round_trip_fee_width

        # Enforce minimum stop width to prevent near-zero stops
        # Single source of truth: trading_config.py MIN_STOP_WIDTH_PCT
        from trading_config import TradingConfig as _TC
        min_width = entry * _TC().min_stop_width_pct
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
        notional_cap_applied = False
        if not skip_notional_cap:
            notional = qty * entry
            max_notional = self.equity * effective_leverage * 2
            if notional > max_notional:
                qty = max_notional / entry
                notional_cap_applied = True
                logger.warning(
                    f"[SIZE] {symbol or '?'} notional capped: "
                    f"${notional:.0f} > max ${max_notional:.0f}"
                )

        # Store sizing breakdown for attribution/debugging
        fee_pct_of_stop = round_trip_fee_width / effective_stop * 100 if effective_stop > 0 else 0
        self.last_sizing_breakdown = {
            "symbol": symbol or "?",
            "equity": self.equity,
            "base_risk_pct": effective_risk_pct,
            "risk_multiplier_raw": risk_multiplier,
            "risk_multiplier_capped": capped_rm,
            "risk_usd": risk_usd,
            "stop_width": stop_width,
            "slippage_spread": slippage_spread,
            "round_trip_fee_width": round_trip_fee_width,
            "fee_pct_of_stop": round(fee_pct_of_stop, 1),
            "effective_stop": effective_stop,
            "leverage": effective_leverage,
            "qty_before_cap": risk_usd / (effective_stop * effective_leverage),
            "notional_cap_applied": notional_cap_applied,
            "final_qty": qty,
        }

        logger.info(
            f"[SIZE] {symbol or '?'} risk=${risk_usd:.2f} "
            f"stop={stop_width:.6f}+slip={slippage_spread:.6f} lev={effective_leverage:.1f}x "
            f"rm={capped_rm:.2f} qty={qty:.6f}"
            + (" [NOTIONAL-CAPPED]" if notional_cap_applied else "")
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

    def is_trading_allowed(self, confidence: float = 0.0,
                            cb_conf_override_pct: float = 0.92,
                            sim_time: Optional[datetime] = None) -> bool:
        """Delegate to circuit breaker's is_trading_allowed."""
        return self.circuit_breaker.is_trading_allowed(
            confidence=confidence,
            cb_conf_override_pct=cb_conf_override_pct,
            sim_time=sim_time,
            equity=self.equity,
        )

    def get_override_constraints(self, confidence: float = 0.0) -> Dict[str, Any]:
        """Delegate to circuit breaker's get_override_constraints."""
        return self.circuit_breaker.get_override_constraints(confidence=confidence)

    def check_unrealized_risk(self, unrealized_pnl: float,
                               sim_time: Optional[datetime] = None):
        """Check circuit breakers using mark-to-market equity (realized + unrealized).

        Call this on each price update to catch drawdowns from open positions,
        not just after trades close.
        """
        mtm_equity = self.equity + unrealized_pnl
        self.circuit_breaker.check_mtm_breakers(mtm_equity, sim_time=sim_time)

    def calculate_compound_size(
        self,
        base_risk: float = 0.01,
        kelly_weight: float = 1.0,
        regime_scalar: float = 1.0,
        vol_regime: float = 1.0,
        correlation_adj: float = 1.0,
        drawdown_dial: float = 1.0,
        signal_decay: float = 1.0,
        btc_momentum: float = 1.0,
    ) -> float:
        """Compound sizing formula with 8 multipliers.

        Every trade passes through 8 multipliers before position size is issued.
        Marginal trades compute to near-zero automatically — no human judgment required.

        Args:
            base_risk: Base risk as fraction of equity (e.g., 0.01 = 1%)
            kelly_weight: Rolling Kelly fraction per factor (0.05-1.0)
            regime_scalar: Per-regime multiplier (consolidation=1.0, bull=0.85, bear=0.5, high_vol=0.3, unknown=0.0)
            vol_regime: Realized vol / baseline vol, inverted (high vol = smaller size)
            correlation_adj: 1.0 if uncorrelated, 0.5 if cluster
            drawdown_dial: 1.0 normal, 0.5 at -10%, 0.25 at -15%
            signal_decay: 1.0 fresh signal, decays over max_age
            btc_momentum: BTC direction alignment (1.0 aligned, 0.5 counter)

        Returns:
            Risk amount as fraction of equity (capped at 2× base_risk).
        """
        raw = (
            base_risk
            * kelly_weight
            * regime_scalar
            * vol_regime
            * correlation_adj
            * drawdown_dial
            * signal_decay
            * btc_momentum
        )
        capped = max(0.0, min(raw, base_risk * 2))

        self._last_compound_breakdown = {
            "base_risk": base_risk,
            "kelly_weight": round(kelly_weight, 4),
            "regime_scalar": round(regime_scalar, 2),
            "vol_regime": round(vol_regime, 3),
            "correlation_adj": round(correlation_adj, 2),
            "drawdown_dial": round(drawdown_dial, 3),
            "signal_decay": round(signal_decay, 3),
            "btc_momentum": round(btc_momentum, 2),
            "raw": round(raw, 6),
            "capped": round(capped, 6),
        }

        return capped

    # Regime scalar lookup: data-driven from 75-day backtest results
    REGIME_SIZE_SCALARS = {
        "consolidation": 1.0,      # 80-89% WR — full size
        "trending_bull": 0.85,     # 58% WR — near full
        "trend": 0.85,             # Legacy name
        "range": 0.7,              # Unclear direction — reduced
        "trending_bear": 0.5,      # 48-52% WR — half size
        "high_volatility": 0.3,    # Unpredictable — minimal
        "panic": 0.2,              # Extreme — minimal
        "low_liquidity": 0.3,      # Thin books — minimal
        "news_dislocation": 0.3,   # Event-driven — minimal
        "unknown": 0.0,            # No regime = no trade
    }

    def get_regime_scalar(self, regime: str) -> float:
        """Get position size scalar for current regime."""
        return self.REGIME_SIZE_SCALARS.get(regime, 0.5)

    def get_drawdown_dial(self) -> float:
        """Get position size reduction based on current drawdown depth.

        Graduated reduction:
          0-5% DD: 1.0× (normal)
          5-10% DD: 0.75× (caution)
          10-15% DD: 0.5× (defensive)
          15-20% DD: 0.25× (survival)
          >20%: 0.0× (halted)
        """
        if self.equity <= 0 or self.circuit_breaker.session_peak_equity <= 0:
            return 1.0

        dd_pct = (self.circuit_breaker.session_peak_equity - self.equity) / self.circuit_breaker.session_peak_equity

        if dd_pct <= 0.05:
            return 1.0
        elif dd_pct <= 0.10:
            return 0.75
        elif dd_pct <= 0.15:
            return 0.5
        elif dd_pct <= 0.20:
            return 0.25
        else:
            return 0.0

    @staticmethod
    def compute_vol_regime_multiplier(atr_current: float, atr_baseline: float) -> float:
        """Inverse vol scaling: high vol = smaller size, low vol = larger.

        Returns multiplier between 0.3 and 1.5.
        """
        if atr_baseline <= 0:
            return 1.0
        ratio = atr_current / atr_baseline
        multiplier = 1.0 / max(ratio, 0.5)
        return max(0.3, min(1.5, multiplier))

    @staticmethod
    def compute_signal_decay(signal_age_seconds: float, max_age_seconds: float = 300.0) -> float:
        """Signal freshness: 1.0 when fresh, decays to 0.5 at max age."""
        if signal_age_seconds <= 0:
            return 1.0
        if signal_age_seconds >= max_age_seconds:
            return 0.5
        return 1.0 - 0.5 * (signal_age_seconds / max_age_seconds)

    @staticmethod
    def compute_btc_momentum_multiplier(btc_return_1h: float, alt_side: str) -> float:
        """BTC direction alignment: boost when alt aligns with BTC momentum.

        Returns multiplier between 0.5 and 1.2.
        """
        if abs(btc_return_1h) < 0.001:
            return 1.0
        btc_bullish = btc_return_1h > 0
        trade_long = alt_side.upper() in ("LONG", "BUY")
        if btc_bullish == trade_long:
            return min(1.2, 1.0 + abs(btc_return_1h) * 5)
        else:
            return max(0.5, 1.0 - abs(btc_return_1h) * 5)

    def get_status(self) -> Dict[str, Any]:
        return {
            "equity": self.equity,
            "risk_per_trade": self.risk_per_trade,
            "risk_usd": self.equity * self.risk_per_trade,
            "max_open_positions": self.max_open_positions,
            "circuit_breaker": self.circuit_breaker.get_status(),
        }
