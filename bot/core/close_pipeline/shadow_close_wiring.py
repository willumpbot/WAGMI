"""SHADOW close-bus wiring (measurement-integrity, Phase 0.4-C).

WHAT THIS IS: a LOG-ONLY, PARALLEL wiring of the close_bus (built in Phase
0.4-B) alongside the live god-block in ``multi_strategy_main.py``. It never
replaces, gates, or mutates anything the god-block does -- it observes the
same ``TradeEvent``s the god-block already processed and re-derives a
``TradeClosed`` from them, publishing to a SEPARATE ``CloseBus`` whose every
collaborator writes ONLY under ``data/shadow/``. This exists so the close
pipeline can be scored for accuracy (see ``tools/shadow_close_diff.py``)
before any flip decision is made -- see the flip readiness criteria in the
project's pipeline-accuracy plan. Nothing here is a flip: the god-block
remains the sole authoritative close path.

SHIPS DORMANT: ``build_shadow_close()`` returns ``None`` unless
``CLOSE_BUS_SHADOW`` is explicitly truthy in the environment. When dormant,
importing this module has zero side effects and the three call-site taps in
``multi_strategy_main.py`` are no-ops (``if self._shadow_close is not
None:`` guards).

THE #1 SAFETY HAZARD THIS MODULE EXISTS TO CLOSE (F6): every ``CloseCtx``
collaborator field that is left ``None`` LAZILY RESOLVES TO THE REAL,
PROCESS-WIDE SINGLETON inside its subscriber body the first time it's
needed -- see close_context.py's field notes and each close_subscribers_*.py
module's ``_default_*`` resolvers. Concretely, leaving any of
``graduated_rules_engine`` / ``adaptive_sizer`` / ``autopsy`` /
``learning_integrator`` / ``thesis_grader`` / ``rl_append_transition_fn`` /
``log_signal_outcome_fn`` / ``telemetry_cls`` / ``survival_record_outcome_fn``
/ ``learning_mode_active_fn`` / ``learning_mode_record_fn`` /
``add_observation_fn`` / ``log_trade_fn`` / ``record_trade_outcome_fn`` /
``log_closed_trade_fn`` / ``journal_booked_fn`` / ``process_agent_lesson_fn``
/ ``learning_agent_fn`` as ``None`` in a shadow ``CloseCtx`` would silently
resolve the REAL production collaborator -- writing to REAL ledger/learning
files (or, for ``journal_booked_fn``, the REAL ``__file__``-anchored
``data/position_journal.jsonl`` -- see close_context.py's field note), or
(worst case, ``learning_agent_fn``) firing a SECOND live ``claude -p`` LLM
call per close. This module explicitly injects a recorder/stand-in for
EVERY ``CloseCtx`` field except ``regime_strategy_weighter`` (which is
faithfully left ``None`` -- see close_context.py's field note: the real
god-block collaborator this would shadow is ITSELF permanently ``None`` in
production, since its constructor module does not exist in the current
tree; injecting a stand-in there would NOT be shadowing anything real).

TWO KINDS OF STAND-IN:
  1. ``ShadowRiskManager`` -- the ``risk_mgr`` collaborator. Tracks an
     in-memory equity accumulator + a lightweight circuit-breaker duck-type,
     seeded from (but never writing back to) the bot's real starting
     equity. Deliberately NEVER the real ``execution.risk.RiskManager``:
     that class's ``update_equity()`` unconditionally calls
     ``save_equity_state()`` (writes ``data/risk_equity_state.json``,
     risk.py:858) and its ``CircuitBreaker._trip()`` calls
     ``_log_safety_event()`` (writes ``data/logs/safety_events.csv``,
     risk.py:255) -- both real production files this module must never
     touch.
  2. ``CallRecorder`` -- every other collaborator (weight_mgr, ic_tracker,
     kelly_engine, deep_memory, thesis_grader, ..., and the LLM learning
     agent's ``learning_agent_fn``/``process_agent_lesson_fn``). A single
     generic duck-typed stand-in: ANY attribute access returns a bound
     function that appends one JSON line (method name + args/kwargs) to a
     per-subscriber sink under ``data/shadow/calls/`` and returns a
     configured default (``None`` unless a ``returns=`` override was given
     for that method name -- see ``autopsy``'s ``should_run_autopsy=False``
     and ``ab_manager``'s ``get_active_experiments=[]`` below, both needed
     so the real subscriber body's branching doesn't crash on a ``None``
     it wasn't expecting). ``CallRecorder`` is ALSO directly callable
     (``__call__``) so the exact same class doubles as a stand-in for the
     ``Optional[Callable[..., None]]``-typed fields (``log_trade_fn``,
     ``learning_agent_fn``, etc.) without a second implementation.

SHADOW ``TradeLedger``/``TradeLogger``: unlike every other collaborator,
these two are REAL instances of the production classes -- just pointed at
``data/shadow/`` instead of ``data/``. This is deliberate (see the
BUILD-READY plan): it lets ``tools/shadow_close_diff.py`` diff the shadow
``trade_ledger.csv`` / ``trades_*.csv`` byte-for-byte, column-by-column,
against the real ones, which a generic call-recorder JSONL could not do.
``core.provenance.gate_live_write`` still applies to these paths (they are
still under ``DATA_DIR``), but it only blocks a write when the resolved
SOURCE is simulated (backtest/test/sim) -- a real paper/live bot process
resolves to a REAL source (PAPER/LIVE) regardless of which subdirectory it
writes to, so shadow writes proceed normally in production. Tests
constructing this harness against a ``tmp_path``-based ``data_dir`` are
outside ``DATA_DIR`` entirely, so the gate no-ops for a different reason
(the target isn't a "live target" at all) -- see ``_is_live_target`` in
core/provenance.py.

NEVER CALLS ``replay_unacked``: this harness's ``CloseBus`` never replays a
boot-time backlog -- shadow mode only ever observes events the LIVE
god-block hands it synchronously via ``publish_shadow()`` at tap (c) in
``multi_strategy_main.py``. There is no boot-recovery concept for a
dormant-by-default parallel harness.

NEVER CALLS ``close_with_execution``: that module submits REAL exchange
orders (H1 hazard) -- this harness only ever calls ``CloseBus.publish()``
with an already-decided ``TradeClosed`` snapshot built from a ``TradeEvent``
the god-block already finished processing (including any real exchange
submission, which happened earlier, at the god-block's own call site).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import paths
from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.close_subscribers_accounting import register_accounting
from core.close_pipeline.close_subscribers_learning import register_learning
from core.close_pipeline.close_subscribers_learning2 import register_learning2
from core.close_pipeline.close_subscribers_llm_learning_agent import register_llm_learning_agent
from core.close_pipeline.close_subscribers_misc import register_misc
from core.close_pipeline.trade_closed import TradeClosed
from execution.trade_logger import TradeLogger
from feedback.trade_ledger import TradeLedger

logger = logging.getLogger("bot.core.close_pipeline.shadow_close_wiring")


# ---------------------------------------------------------------------------
# CallRecorder -- the generic, safe stand-in for every non-ledger/logger
# CloseCtx collaborator (both "object with methods" and "bare callable"
# shapes -- see module docstring).
# ---------------------------------------------------------------------------
class CallRecorder:
    """Records every call made against it to a per-subscriber JSONL sink
    under ``data/shadow/calls/`` and NEVER performs the real collaborator's
    side effect. Duck-types as both an object (``recorder.record_outcome(
    ...)`` via ``__getattr__``) and a bare callable (``recorder(**kwargs)``
    via ``__call__``) so one class covers every shape ``CloseCtx`` fields
    take.

    ``returns``: optional ``{method_name: value}`` map for the handful of
    methods whose return value a subscriber body branches on (e.g.
    ``ab_manager.get_active_experiments()`` must return an iterable, not
    ``None``, or the subscriber's ``for exp in ...:`` raises). Every other
    method call returns ``None`` (falsy) by default -- safe, since every
    real subscriber body's use of a collaborator's return value is either
    ignored or used in a truthiness check (``if lesson:``) that treats
    ``None`` as "nothing to do," never as a crash.
    """

    def __init__(
        self,
        name: str,
        sink_path: Path,
        *,
        returns: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.sink_path = Path(sink_path)
        self._returns = dict(returns) if returns else {}
        self.call_count = 0
        self._lock = threading.Lock()

    def _record(self, method: str, args: tuple, kwargs: dict) -> Any:
        with self._lock:
            self.call_count += 1
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "subscriber": self.name,
            "method": method,
            "args": [str(a) for a in args],
            "kwargs": {k: _jsonable(v) for k, v in kwargs.items()},
        }
        try:
            self.sink_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with open(self.sink_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=str) + "\n")
        except Exception:
            logger.debug(
                "[SHADOW-CLOSE] CallRecorder(%s): failed writing sink %s (log-only, non-fatal)",
                self.name, self.sink_path, exc_info=True,
            )
        return self._returns.get(method)

    def __getattr__(self, method: str) -> Callable[..., Any]:
        # __getattr__ only fires for attributes NOT already found via normal
        # lookup (i.e. never shadows self.name/self.sink_path/etc, set in
        # __init__) -- every OTHER attribute access is treated as "the real
        # collaborator's method" and returns a bound recorder function.
        def _bound(*args: Any, **kwargs: Any) -> Any:
            return self._record(method, args, kwargs)
        return _bound

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Bare-callable shape (log_trade_fn(**kwargs), learning_agent_fn(dict), ...).
        return self._record("__call__", args, kwargs)


def _jsonable(value: Any) -> Any:
    """Best-effort JSON-safe coercion for a recorder sink row. Never raises
    -- worst case, falls back to ``str(value)``."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


# ---------------------------------------------------------------------------
# ShadowRiskManager -- the risk_mgr stand-in. See module docstring for why
# this must never be a real execution.risk.RiskManager.
# ---------------------------------------------------------------------------
class _ShadowCircuitBreaker:
    """Lightweight duck-type of ``execution.risk.CircuitBreaker`` exposing
    only the attributes ``on_close_circuit_breaker`` reads
    (``consecutive_losses``/``tripped``/``daily_pnl``, plus
    ``session_peak_equity``/``peak_equity`` for parity with the real
    class's shape). ``record_trade`` mutates ONLY this in-memory object --
    it never calls ``_log_safety_event`` (the real class's
    ``data/logs/safety_events.csv`` writer, risk.py:28-42) and never trips
    in a way that writes anything to disk.
    """

    def __init__(self) -> None:
        self.consecutive_losses = 0
        self.tripped = False
        self.daily_pnl = 0.0
        self.peak_equity = 0.0
        self.session_peak_equity = 0.0
        self.trip_reason = ""
        self.cooldown_minutes = 0

    def record_trade(self, pnl: float, equity: float, sim_time: Any = None) -> None:
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.session_peak_equity <= 0 and equity > 0:
            self.session_peak_equity = equity

    def is_trading_allowed(self, *args: Any, **kwargs: Any) -> bool:
        return not self.tripped


class ShadowRiskManager:
    """Stand-in for ``execution.risk.RiskManager`` used ONLY as
    ``CloseCtx.risk_mgr`` in the shadow bus. Tracks an in-memory equity
    accumulator seeded from (never written back to) the real bot's starting
    equity. Deliberately does NOT implement ``save_equity_state()`` /
    ``_reconcile_equity_with_ledger()`` / any other real-RiskManager method
    beyond the two the accounting-tier subscribers actually call
    (``update_equity``, plus attribute access on ``.circuit_breaker`` /
    ``.equity``) -- see module docstring's F6 hazard note.

    ``equity_trace_path``: optional -- when given, every ``update_equity``
    call appends one JSON line (``pnl_delta``/``equity_after``) to this path
    (always under ``data/shadow/`` -- see ``build_shadow_close``). This is
    the ONLY way the in-memory equity accumulator becomes diffable from an
    external process (``tools/shadow_close_diff.py``): the accumulator
    itself dies with the harness, unlike the real ``RiskManager`` whose
    equity is persisted to ``data/risk_equity_state.json`` on every close.
    """

    def __init__(self, starting_equity: float = 0.0, equity_trace_path: Optional[Path] = None) -> None:
        self.equity = float(starting_equity or 0.0)
        self.circuit_breaker = _ShadowCircuitBreaker()
        self._equity_trace_path = Path(equity_trace_path) if equity_trace_path is not None else None
        self._trace_lock = threading.Lock()

    def update_equity(
        self,
        pnl: float,
        sim_time: Any = None,
        open_realized_pnl: float = 0.0,
    ) -> None:
        """Mirrors ``execution.risk.RiskManager.update_equity``'s equity
        mutation + circuit-breaker record EXACTLY, minus every real-file
        write that function performs (``save_equity_state()``,
        ``_reconcile_equity_with_ledger()`` -- see risk.py:844-858). Purely
        in-memory, except for the optional shadow-dir-only trace append
        below."""
        self.equity += pnl
        self.circuit_breaker.record_trade(pnl, self.equity, sim_time=sim_time)
        if self._equity_trace_path is not None:
            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "pnl_delta": pnl,
                "shadow_equity_after": self.equity,
            }
            try:
                self._equity_trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self._trace_lock:
                    with open(self._equity_trace_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, default=str) + "\n")
            except Exception:
                logger.debug(
                    "[SHADOW-CLOSE] ShadowRiskManager: equity trace append failed (log-only)",
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# ShadowCloseHarness -- bundles the shadow CloseBus + CloseCtx + a
# convenience publish helper the tap in multi_strategy_main.py calls.
# ---------------------------------------------------------------------------
class ShadowCloseHarness:
    """Everything one guarded tap needs: the shadow ``CloseBus``, its
    ``CloseCtx``, and ``publish_shadow``/``append_god_reference`` helpers.
    Constructed once (at bot ``__init__``) by ``build_shadow_close`` and
    stored on ``self._shadow_close``; ``None`` when shadow mode is off."""

    def __init__(self, bus: CloseBus, ctx: CloseCtx, shadow_dir: Path) -> None:
        self.bus = bus
        self.ctx = ctx
        self.shadow_dir = Path(shadow_dir)
        self.publishes_path = self.shadow_dir / "publishes.jsonl"
        self._publishes_lock = threading.Lock()

    def publish_shadow(
        self,
        event: Any,
        *,
        position: Any = None,
        equity_after: Optional[float] = None,
        session_dd_pct: Optional[float] = None,
        close_volatility: Optional[float] = None,
        compound_mult: Optional[float] = None,
        btc_trend: Optional[str] = None,
        funding_rate: Optional[float] = None,
    ) -> Optional[TradeClosed]:
        """Builds a frozen ``TradeClosed`` from the god-block's own
        ``TradeEvent`` (+ position snapshot) and publishes it to the shadow
        bus. Returns the constructed event (so the caller can correlate a
        god-side reference row by ``event_id`` via
        ``append_god_reference``), or ``None`` on any failure -- this
        method NEVER raises; a shadow-side failure must never affect the
        god-block's own close handling.
        """
        try:
            tc = TradeClosed.from_trade_event(
                event,
                position=position,
                equity_after=equity_after,
                session_dd_pct=session_dd_pct,
                close_volatility=close_volatility,
                compound_mult=compound_mult,
                btc_trend=btc_trend,
                funding_rate=funding_rate,
            )
        except Exception:
            logger.exception(
                "[SHADOW-CLOSE] publish_shadow: failed constructing TradeClosed "
                "(log-only -- god-block unaffected)"
            )
            return None
        try:
            self.bus.publish(tc)
        except Exception:
            logger.exception(
                "[SHADOW-CLOSE] publish_shadow: bus.publish failed "
                "(log-only -- god-block unaffected)"
            )
            return None
        return tc

    def append_god_reference(
        self,
        *,
        event_id: str,
        god_total_pnl: Any,
        god_equity_after: Any,
        god_session_dd: Any,
        god_daily_pnl: Any,
        god_llm_mode: Any,
    ) -> None:
        """Appends one row of the god-block's OWN truth for this event to
        ``data/shadow/publishes.jsonl``, keyed by the SAME ``event_id`` the
        shadow ``TradeClosed`` was published with -- so
        ``tools/shadow_close_diff.py`` can compare shadow-derived values
        against what the live god-block actually computed for the same
        close, without needing to re-derive anything itself. Never raises.
        """
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "god_total_pnl": _jsonable(god_total_pnl),
            "god_equity_after": _jsonable(god_equity_after),
            "god_session_dd": _jsonable(god_session_dd),
            "god_daily_pnl": _jsonable(god_daily_pnl),
            "god_llm_mode": _jsonable(god_llm_mode),
        }
        try:
            self.publishes_path.parent.mkdir(parents=True, exist_ok=True)
            with self._publishes_lock:
                with open(self.publishes_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=str) + "\n")
        except Exception:
            logger.debug(
                "[SHADOW-CLOSE] append_god_reference failed (log-only, non-fatal)",
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# build_shadow_close -- the one entry point multi_strategy_main.py calls.
# ---------------------------------------------------------------------------
def build_shadow_close(bot: Any, *, data_dir: Optional[Path] = None) -> Optional[ShadowCloseHarness]:
    """Build the shadow close-bus harness, or return ``None`` if shadow
    mode is off (the default) or if construction fails for any reason.

    GATED: ``CLOSE_BUS_SHADOW`` must be explicitly truthy
    (``"1"``/``"true"``/``"yes"``, case-insensitive) -- absent/anything else
    means off, matching every other boolean env gate in this codebase.

    ``data_dir``: override for tests (a ``tmp_path``-based directory) --
    production callers omit this and get ``core.paths.DATA_DIR`` resolved
    at call time (not import time, so tests may also monkeypatch
    ``core.paths.DATA_DIR`` instead of passing this explicitly).

    NEVER RAISES: every failure inside is caught, logged, and turned into a
    ``None`` return -- a shadow-wiring bug must never be able to crash bot
    startup. Callers (``multi_strategy_main.py``'s ``__init__``) additionally
    wrap the call site in its own try/except as defense in depth.
    """
    if os.getenv("CLOSE_BUS_SHADOW", "false").lower() not in ("1", "true", "yes"):
        return None

    try:
        base_dir = Path(data_dir) if data_dir is not None else paths.DATA_DIR
        shadow_dir = base_dir / "shadow"
        calls_dir = shadow_dir / "calls"
        shadow_dir.mkdir(parents=True, exist_ok=True)
        calls_dir.mkdir(parents=True, exist_ok=True)

        # ---- risk_mgr: ShadowRiskManager, NEVER the real RiskManager ----
        starting_equity = 0.0
        try:
            starting_equity = float(getattr(getattr(bot, "risk_mgr", None), "equity", 0.0) or 0.0)
        except Exception:
            starting_equity = 0.0
        risk_mgr = ShadowRiskManager(
            starting_equity=starting_equity,
            equity_trace_path=shadow_dir / "equity_trace.jsonl",
        )

        # ---- trade_ledger / trade_logger: REAL classes, shadow-dir paths ----
        trade_ledger = TradeLedger(data_dir=str(shadow_dir))
        trade_logger = TradeLogger(log_dir=str(shadow_dir))

        def _rec(name: str, **returns: Any) -> CallRecorder:
            return CallRecorder(name, calls_dir / f"{name}.jsonl", returns=returns or None)

        # ---- static config passthroughs (one-time reads, not live mutable
        # state -- see close_context.py's field notes for risk_per_trade /
        # llm_mode_name / llm_multi_agent_enabled) ----
        risk_per_trade = 0.01
        try:
            risk_per_trade = float(getattr(getattr(bot, "config", None), "risk_per_trade", 0.01) or 0.01)
        except Exception:
            risk_per_trade = 0.01

        llm_mode_name = ""
        try:
            _mode = getattr(bot, "llm_mode", None)
            if _mode is not None:
                llm_mode_name = _mode.name if hasattr(_mode, "name") else str(_mode)
        except Exception:
            llm_mode_name = ""

        llm_multi_agent_enabled = os.getenv("LLM_MULTI_AGENT", "").lower() in ("1", "true", "yes")

        # ---- EVERY CloseCtx field explicitly injected -- see module
        # docstring's F6 hazard note. The ONLY field left None is
        # regime_strategy_weighter (faithful no-op: the real god-block
        # collaborator it would shadow is itself permanently None in
        # production -- close_context.py's field note). ----
        ctx = CloseCtx(
            risk_mgr=risk_mgr,
            trade_ledger=trade_ledger,
            trade_logger=trade_logger,
            kelly_engine=_rec("kelly_engine"),
            source=None,
            log_trade_fn=_rec("log_trade_fn"),
            record_trade_outcome_fn=_rec("record_trade_outcome_fn"),
            log_closed_trade_fn=_rec("log_closed_trade_fn"),
            # CRITICAL (F6): journal_booked_fn MUST be a recorder, never the
            # real core.position_journal.journal_booked -- that function is
            # __file__-anchored to the REAL data/position_journal.jsonl
            # regardless of this shadow_dir, so leaving it None here would
            # both escape data/shadow/ AND (worse) falsely stamp
            # CLOSED_BOOKED into the real journal for a close the real
            # ledger never recorded. See close_context.py's field note.
            journal_booked_fn=_rec("journal_booked_fn"),
            # -- learning batch 1 --
            weight_mgr=_rec("weight_mgr"),
            regime_feedback=_rec("regime_feedback"),
            confidence_floor=_rec("confidence_floor"),
            hold_time_rules=_rec("hold_time_rules"),
            parameter_tuner=_rec("parameter_tuner"),
            feedback=_rec("feedback"),
            ic_tracker=_rec("ic_tracker"),
            graduated_rules_engine=_rec("graduated_rules_engine"),
            # -- learning batch 2 --
            deep_memory=_rec("deep_memory"),
            thesis_grader=_rec("thesis_grader"),
            post_trade_learner=_rec("post_trade_learner"),
            reflection=_rec("reflection"),
            autopsy=_rec("autopsy", should_run_autopsy=False),
            learning_integrator=_rec("learning_integrator"),
            ml=_rec("ml"),
            counterfactual=_rec("counterfactual"),
            log_signal_outcome_fn=_rec("log_signal_outcome_fn"),
            rl_append_transition_fn=_rec("rl_append_transition_fn"),
            risk_per_trade=risk_per_trade,
            llm_mode_name=llm_mode_name,
            closed_trade_count=0,
            # -- misc batch 3 --
            adaptive_risk=_rec("adaptive_risk"),
            adaptive_sizer=_rec("adaptive_sizer"),
            shadow_ledger=_rec("shadow_ledger"),
            continuous_backtest=_rec("continuous_backtest"),
            llm_triggers=_rec("llm_triggers"),
            quant_brain=_rec("quant_brain"),
            regime_strategy_weighter=None,  # faithful no-op -- see docstring above
            growth=_rec("growth"),
            ab_manager=_rec("ab_manager", get_active_experiments=[]),
            agent_perf=_rec("agent_perf"),
            cost_optimizer=_rec("cost_optimizer"),
            risk_telemetry=_rec("risk_telemetry"),
            telemetry_cls=_rec("telemetry_cls"),
            alerts=_rec("alerts"),
            format_trade_event_fn=_rec("format_trade_event_fn"),
            survival_record_outcome_fn=_rec("survival_record_outcome_fn"),
            learning_mode_active_fn=_rec("learning_mode_active_fn"),
            learning_mode_record_fn=_rec("learning_mode_record_fn"),
            add_observation_fn=_rec("add_observation_fn"),
            symbol_cooldown={},
            symbol_daily_pnl={},
            symbol_daily_pnl_date=None,
            symbol_daily_loss_limit=float("-inf"),
            last_close_win={},
            last_close_side={},
            # -- LLM learning agent (T3 final batch) --
            # CRITICAL (F6): learning_agent_fn MUST be a recorder, never the
            # real coordinator -- see module docstring.
            learning_agent_fn=_rec("learning_agent_fn"),
            process_agent_lesson_fn=_rec("process_agent_lesson_fn"),
            llm_multi_agent_enabled=llm_multi_agent_enabled,
        )

        bus = CloseBus(
            applied_store=InMemoryAppliedStore(),
            outbox_path=shadow_dir / "close_outbox.jsonl",
        )
        # Registration order is load-bearing (matches the god-block's own
        # top-to-bottom source order + the T2 ordering pairs documented in
        # close_bus.py's module docstring): accounting -> learning ->
        # learning2 -> misc -> llm_learning_agent. NEVER call
        # bus.replay_unacked() -- see module docstring.
        register_accounting(bus, ctx)
        register_learning(bus, ctx)
        register_learning2(bus, ctx)
        register_misc(bus, ctx)
        register_llm_learning_agent(bus, ctx)

        harness = ShadowCloseHarness(bus=bus, ctx=ctx, shadow_dir=shadow_dir)
        logger.info("[SHADOW-CLOSE] shadow close-bus harness built (dir=%s)", shadow_dir)
        return harness
    except Exception:
        logger.exception(
            "[SHADOW-CLOSE] build_shadow_close failed -- shadow wiring disabled, "
            "live bot unaffected"
        )
        return None
