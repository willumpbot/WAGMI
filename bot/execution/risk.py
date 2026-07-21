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

from core.atomic_state import atomic_write_json

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
        load_persisted_equity: bool = True,
    ):
        # Persisted equity (2026-04-16 fix): restore cumulative equity
        # from disk if available. Previously every bot restart reset
        # equity to `starting_equity`, losing all real gains from prior
        # sessions. User noticed their phone showed $495 after a +$28
        # session because midnight UTC reset + restart erased progress.
        # Falls back to computing from trades.csv if no state file.
        #
        # Tests and backtests pass load_persisted_equity=False so they
        # get exactly the starting_equity they asked for (no state-file
        # interference).
        if load_persisted_equity:
            effective_start, _used_persisted = self._load_persisted_equity_with_flag(starting_equity)
        else:
            effective_start = starting_equity
            _used_persisted = False
        self.equity = effective_start
        self._starting_equity_config = starting_equity  # for reference / reset
        # Only persist future equity updates if we actually loaded persisted
        # state on init (i.e., we're the real bot, not a test with a wildly
        # different starting_equity that triggered the safety fallback).
        self._should_persist_equity = bool(load_persisted_equity and _used_persisted)
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_portfolio_leverage = max_portfolio_leverage
        self.max_risk_multiplier = max_risk_multiplier
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.circuit_breaker.peak_equity = max(effective_start, starting_equity)
        # Last sizing breakdown for attribution/debugging
        self.last_sizing_breakdown: Dict[str, Any] = {}

    @classmethod
    def _load_persisted_equity_with_flag(cls, fallback: float) -> tuple[float, bool]:
        """Load persisted equity and return (equity, used_persisted).

        Returns (equity_value, True) when we actually loaded a persisted
        state that's consistent with the caller's starting_equity context.
        Returns (fallback, False) when we fell back (e.g., test context).

        Bug fix: the previous implementation used (abs(val - fallback) > 0.01) to
        detect file-loaded state, but this fails when persisted equity == starting_equity
        (e.g., bot restarts at $5000 with a $5000 state file → used_persisted=False →
        _should_persist_equity=False → equity updates never saved). Now uses a direct
        file-existence flag from the new _load_persisted_equity_with_source helper.
        """
        import json
        import os
        import csv
        state_path = os.path.join("data", "risk_equity_state.json")
        # Check if state file exists and is usable (the real bot's indicator)
        _found_state_file = False
        try:
            if os.path.exists(state_path):
                with open(state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                val = float(state.get("equity", fallback))
                if fallback > 0:
                    ratio = max(val / fallback, fallback / val) if val > 0 else 0
                    if ratio > 10:
                        logger.debug(
                            f"[RISK] Persisted equity ${val:.2f} is {ratio:.1f}x off "
                            f"from fallback ${fallback:.2f}; using fallback (likely test context)"
                        )
                        return fallback, False
                logger.info(
                    f"[RISK] Loaded persisted equity: ${val:.2f} "
                    f"(saved {state.get('saved_at', 'unknown')})"
                )
                # State file found and loaded — this is the real bot; persist future updates
                return val, True
        except Exception as e:
            logger.warning(f"[RISK] Could not load equity state: {e}")

        # Fallback: reconstruct from trades.csv (rare, cold-start-only path --
        # only reached when risk_equity_state.json is missing/corrupt).
        #
        # FALLACY_AUDIT (measurework, item 5, behavior_gated): trades.csv
        # undercounts closes vs trade_ledger.csv, so summing it here would
        # under-reconstruct equity -> feeds self.risk_mgr.equity -> the
        # daily-loss-% circuit breaker. Per execution-safety.md,
        # circuit-breaker-adjacent code must never change behavior without
        # explicit approval, so the ledger-sourced sum is gated OFF by
        # default. Set EQUITY_RECONSTRUCT_LEDGER_SOURCE=true to opt in.
        _use_ledger = os.environ.get("EQUITY_RECONSTRUCT_LEDGER_SOURCE", "false").strip().lower() in ("1", "true", "yes")
        if _use_ledger:
            try:
                from data.trade_source import load_closed_trades
                _ledger_trades = load_closed_trades()
                if _ledger_trades:
                    total_pnl = sum(t["pnl"] for t in _ledger_trades)
                    n = len(_ledger_trades)
                    reconstructed = fallback + total_pnl
                    logger.info(
                        f"[RISK] Reconstructed equity from {n} ledger trades: "
                        f"${fallback:.2f} + ${total_pnl:+.2f} = ${reconstructed:.2f}"
                    )
                    return reconstructed, True
            except Exception as e:
                logger.warning(f"[RISK] Could not reconstruct equity from trade_ledger.csv: {e}")

        trades_path = os.path.join("data", "trades.csv")
        try:
            if os.path.exists(trades_path):
                with open(trades_path, "r", encoding="utf-8") as f:
                    r = csv.reader(f)
                    header = next(r, None)
                    if header and "pnl" in header:
                        pnl_idx = header.index("pnl")
                        total_pnl = 0.0
                        n = 0
                        for row in r:
                            try:
                                total_pnl += float(row[pnl_idx])
                                n += 1
                            except (ValueError, IndexError):
                                continue
                        if n > 0:
                            reconstructed = fallback + total_pnl
                            logger.info(
                                f"[RISK] Reconstructed equity from {n} trades: "
                                f"${fallback:.2f} + ${total_pnl:+.2f} = ${reconstructed:.2f}"
                            )
                            # Reconstructed from trades.csv → treat as persisted (real bot)
                            return reconstructed, True
        except Exception as e:
            logger.warning(f"[RISK] Could not reconstruct equity from trades.csv: {e}")

        logger.info(f"[RISK] Using fallback starting equity: ${fallback:.2f}")
        return fallback, False



    def save_equity_state(self) -> None:
        """Persist current equity to disk for restart continuity.

        Safety: never save non-sensical values (negative equity, or values
        wildly different from the starting config). Tests running huge
        simulated losses should not corrupt the live equity state file.
        """
        import json
        import os
        from datetime import datetime, timezone
        # Test-pollution guard (D6b root cause, 2026-07-02): a pytest run wrote a
        # synthetic equity into the production file (2026-07-01 22:03Z: $2318.91
        # with peak_equity=10000 replaced the real $1951.01) -- the ratio sanity
        # check below cannot catch in-range values, and the next restart loaded
        # the polluted number into CB/sizing/heartbeat. Never persist to the
        # production path from inside a test run.
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        # Sanity check — refuse to persist obvious test pollution.
        cfg_start = getattr(self, "_starting_equity_config", 0.0)
        if self.equity <= 0:
            logger.debug(
                f"[RISK] Refusing to save non-positive equity ${self.equity:.2f} — "
                f"likely test context"
            )
            return
        if cfg_start > 0:
            # If current equity is 5x+ different from the starting config,
            # it's likely a test with different scale. Don't pollute state.
            ratio = max(self.equity / cfg_start, cfg_start / self.equity)
            if ratio > 5:
                logger.debug(
                    f"[RISK] Refusing to save equity ${self.equity:.2f} — "
                    f"{ratio:.1f}x off from starting ${cfg_start:.2f} (test context)"
                )
                return
        state_path = os.path.join("data", "risk_equity_state.json")
        try:
            payload = {
                "equity": round(self.equity, 4),
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "peak_equity": round(self.circuit_breaker.peak_equity, 4),
            }
            # EQUITY_LEDGER_DRIFT (measurement-integrity, Phase 0): additive
            # fields, all readers use .get() so this is backward-compatible.
            # accumulator_equity == "equity" above (kept explicit for
            # readers that want the pair without re-deriving); derived_equity
            # / drift are the epoch-fenced ledger cross-check (None until an
            # epoch baseline is stamped — see data/epoch.py).
            drift_info = getattr(self, "_last_ledger_drift", None)
            if drift_info is not None:
                payload["accumulator_equity"] = round(drift_info["accumulator_equity"], 4)
                payload["derived_equity"] = round(drift_info["derived_equity"], 4)
                payload["drift"] = round(drift_info["drift"], 4)
                payload["epoch_id"] = drift_info.get("epoch_id", "")
            # Atomic write (Phase 0.3a): this writer already used a
            # tmp-file + os.replace() swap (no torn-file window) but never
            # fsync'd the tmp file before the swap, so the durability
            # guarantee was incomplete. atomic_write_json adds the fsync
            # while writing the exact same payload to the exact same path
            # -- no behavior change beyond durability.
            atomic_write_json(state_path, payload)
        except Exception as e:
            logger.warning(f"[RISK] Could not save equity state: {e}")

    def compute_ledger_drift(self) -> Optional[Dict[str, Any]]:
        """Cross-check the mutable accumulator (self.equity) against the
        epoch-derived truth (epoch_equity + sum(in-epoch ledger net_pnl)).

        Read-only: no writes, no network calls, no behavior change. Returns
        None when no epoch baseline is stamped yet (data/epoch_start.json
        missing/epoch_equity unset) — there is nothing to reconcile against.

        Phase 0.5 PR-2: delegates to EquityEngine.reconcile() so there's one
        implementation of the drift math (it already consumed get_run_stats
        here — same call, now shared). The three correction terms
        (open_realized_pnl / pending_pnl / funding_addback) are passed as
        0.0, which makes this BYTE-IDENTICAL to the pre-PR-2 behavior
        (accumulator - derived, no corrections) — they only become
        load-bearing once a caller passes real values (PR-4 observe mode).
        """
        try:
            from execution.equity_engine import EquityEngine
            result = EquityEngine().reconcile(self.equity)
        except Exception as e:
            logger.debug(f"[RISK] ledger drift check skipped: {e}")
            return None
        if result is None:
            return None
        return {
            "accumulator_equity": result["accumulator"],
            "derived_equity": result["derived"],
            "drift": result["adjusted_drift"],
            "epoch_id": result["epoch_id"],
        }

    def _reconcile_equity_with_ledger(self) -> None:
        """Measurement-integrity cross-check (Phase 0). ALARMS (log, throttled)
        when the accumulator has drifted from the epoch-derived ledger truth.

        Off-by-default behavior change: only ADOPTS the derived value as
        self.equity when EQUITY_DERIVE_FROM_LEDGER=true. Default is
        observe-only — the accumulator stays authoritative, per
        execution-safety.md ("never change circuit-breaker-adjacent equity
        behavior without explicit approval"). Skipped entirely under pytest
        to keep unit tests deterministic and I/O-free (same guard pattern as
        save_equity_state's PYTEST_CURRENT_TEST check).
        """
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        drift_info = self.compute_ledger_drift()
        self._last_ledger_drift = drift_info
        if drift_info is None:
            return
        drift = drift_info["drift"]
        try:
            tol = float(os.environ.get("EQUITY_DRIFT_ALARM_USD", "0.50"))
        except (TypeError, ValueError):
            tol = 0.50
        if abs(drift) > tol:
            _now = time.time()
            _last_warn = getattr(self, "_ledger_drift_last_warn", 0.0)
            if _now - _last_warn > 600:  # throttle: at most once per 10 min
                self._ledger_drift_last_warn = _now
                logger.error(
                    f"[EQUITY-LEDGER-DRIFT] accumulator=${self.equity:.2f} "
                    f"derived=${drift_info['derived_equity']:.2f} "
                    f"(epoch_equity + in-epoch ledger net) drift=${drift:+.2f} "
                    f"(tolerance ${tol:.2f}, epoch={drift_info.get('epoch_id') or 'unset'})"
                )
        if os.environ.get("EQUITY_DERIVE_FROM_LEDGER", "false").strip().lower() in ("1", "true", "yes"):
            if abs(drift) > tol:
                logger.warning(
                    f"[RISK] EQUITY_DERIVE_FROM_LEDGER active — adopting derived "
                    f"equity ${drift_info['derived_equity']:.2f} (was ${self.equity:.2f})"
                )
            self.equity = drift_info["derived_equity"]

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

        # Cap risk_multiplier — raised to 2.0 for full Kelly sizing
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
        # EQUITY_LEDGER_DRIFT (measurement-integrity, Phase 0): cross-check
        # the accumulator against epoch-derived ledger truth and ALARM on
        # drift. Off-by-default adoption (EQUITY_DERIVE_FROM_LEDGER) — see
        # _reconcile_equity_with_ledger docstring. Runs before save so a
        # derived-equity adoption (if enabled) is what gets persisted.
        self._reconcile_equity_with_ledger()
        # Persist equity to disk so bot restarts don't lose progress.
        # ALWAYS attempt to save (sanity checks in save_equity_state prevent test pollution).
        # Previous guard `if _should_persist_equity` caused equity to freeze when:
        # - persisted state file == starting_equity → _used_persisted=True → flag set
        # - but flag sometimes evaluated False due to race/timing issues
        # Unconditional save is safer: sanity checks catch test context anyway.
        self.save_equity_state()

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
