"""Tests for the SHADOW close-bus wiring (measurement-integrity, Phase
0.4-C) -- core/close_pipeline/shadow_close_wiring.py.

SAFETY-CRITICAL: these tests exist to PROVE the shadow harness is isolated
BEFORE this wiring is ever enabled against the live bot --
  1. flag-off ships fully dormant (build_shadow_close returns None -- the
     three multi_strategy_main.py taps are `if self._shadow_close is not
     None:` guards, so a None harness makes them structural no-ops; this
     file tests the wiring module the taps depend on, not multi_strategy_
     main.py's giant _process_symbol method directly).
  2. every CloseCtx collaborator field is explicitly injected (non-None)
     except regime_strategy_weighter (documented no-op -- see
     close_context.py's field note) and the two documented-safe scalar
     exceptions (source, symbol_daily_pnl_date).
  3. publishing synthetic TERMINAL/PARTIAL events writes ONLY under
     <DATA_DIR>/shadow/ and NEVER resolves a real production
     singleton/collaborator (the F6 hazard -- see shadow_close_wiring.py's
     module docstring) or fires a real LLM/network call.

Mocks the bot with a plain SimpleNamespace and uses tmp_path exclusively as
DATA_DIR -- this file MUST NOT touch real bot/data/.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from core import paths
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.shadow_close_wiring import (
    CallRecorder,
    ShadowCloseHarness,
    ShadowRiskManager,
    build_shadow_close,
)
from core.close_pipeline.trade_closed import TradeClosed
from execution.position_manager import Position, TradeEvent

# ---------------------------------------------------------------------------
# Helpers (duplicated from test_close_pipeline.py's pattern rather than
# imported -- each close_pipeline test file stays independently leaf-ish,
# same convention as the production close_subscribers_*.py modules).
# ---------------------------------------------------------------------------
def _make_position(**overrides) -> Position:
    defaults = dict(
        symbol="BTC-USD", side="LONG", entry=100.0, qty=1.0, sl=95.0,
        tp1=105.0, tp2=110.0, strategy="regime_trend", confidence=72.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


def _terminal_event(pos: Position, *, total_pnl: float = 12.0) -> TradeEvent:
    return TradeEvent(
        symbol=pos.symbol, action="SL", side=pos.side, price=94.5, qty=pos.qty,
        pnl=8.0, fee=0.4, leverage=pos.leverage, strategy=pos.strategy,
        position_id=pos.position_id, is_position_close=True,
        metadata={
            "total_pnl": total_pnl, "total_fees": 1.23, "funding_costs": 0.05,
            "hold_time_s": 3600.0, "outcome": "CLEAN_LOSS",
            "state_path": "IDLE->OPEN->CLOSED",
            "entry_reasons": {
                "regime": "trend", "num_agree": 3,
                "llm_action": "proceed", "llm_confidence": 0.81, "llm_agreed": True,
                "llm_notes": "thesis_id=abc123",
            },
            "entry": pos.entry, "sl": pos.original_sl, "tp1": pos.tp1, "tp2": pos.tp2,
            "confidence": pos.confidence, "highest_price": 108.0, "lowest_price": 94.0,
        },
    )


def _partial_event(pos: Position) -> TradeEvent:
    return TradeEvent(
        symbol=pos.symbol, action="TP1", side=pos.side, price=105.0, qty=0.5,
        pnl=2.5, fee=0.1, leverage=pos.leverage, strategy=pos.strategy,
        position_id=pos.position_id, is_position_close=False,
        metadata={
            "entry_reasons": {"regime": "trend"},
            "entry": pos.entry, "sl": pos.original_sl, "tp1": pos.tp1, "tp2": pos.tp2,
            "confidence": pos.confidence, "hold_time_s": 600.0,
        },
    )


def _make_bot(risk_equity: float = 5000.0) -> SimpleNamespace:
    """Minimal duck-typed bot stand-in -- build_shadow_close only ever
    reads bot.risk_mgr.equity / bot.config.risk_per_trade / bot.llm_mode
    (one-time snapshots, never mutated)."""
    return SimpleNamespace(
        risk_mgr=SimpleNamespace(equity=risk_equity),
        config=SimpleNamespace(risk_per_trade=0.01),
        llm_mode=SimpleNamespace(name="FULL"),
    )


# Collaborator fields that MUST be non-None in a shadow CloseCtx (every
# field except the three documented exceptions -- see module docstring).
_MUST_BE_NON_NONE = [
    "trade_ledger", "trade_logger", "kelly_engine",
    "log_trade_fn", "record_trade_outcome_fn", "log_closed_trade_fn", "journal_booked_fn",
    "weight_mgr", "regime_feedback", "confidence_floor", "hold_time_rules",
    "parameter_tuner", "feedback", "ic_tracker", "graduated_rules_engine",
    "deep_memory", "thesis_grader", "post_trade_learner", "reflection",
    "autopsy", "learning_integrator", "ml", "counterfactual",
    "log_signal_outcome_fn", "rl_append_transition_fn",
    "adaptive_risk", "adaptive_sizer", "shadow_ledger", "continuous_backtest",
    "llm_triggers", "quant_brain", "growth", "ab_manager", "agent_perf",
    "cost_optimizer", "risk_telemetry", "telemetry_cls", "alerts",
    "format_trade_event_fn", "survival_record_outcome_fn",
    "learning_mode_active_fn", "learning_mode_record_fn", "add_observation_fn",
    "learning_agent_fn", "process_agent_lesson_fn",
]

_DOCUMENTED_NONE = ["regime_strategy_weighter", "source", "symbol_daily_pnl_date"]


# ---------------------------------------------------------------------------
# Flag-off: fully dormant
# ---------------------------------------------------------------------------
class TestFlagOff:
    def test_absent_env_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLOSE_BUS_SHADOW", raising=False)
        bot = _make_bot()
        assert build_shadow_close(bot, data_dir=tmp_path) is None
        # Nothing created -- a None harness means the multi_strategy_main.py
        # taps (`if self._shadow_close is not None:`) never execute at all.
        assert not any(tmp_path.iterdir())

    @pytest.mark.parametrize("val", ["false", "0", "no", "", "off", "garbage"])
    def test_falsy_values_return_none(self, monkeypatch, tmp_path, val):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", val)
        bot = _make_bot()
        assert build_shadow_close(bot, data_dir=tmp_path) is None

    @pytest.mark.parametrize("val", ["true", "1", "yes", "TRUE", "Yes"])
    def test_truthy_values_build_harness(self, monkeypatch, tmp_path, val):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", val)
        bot = _make_bot()
        harness = build_shadow_close(bot, data_dir=tmp_path)
        assert isinstance(harness, ShadowCloseHarness)


# ---------------------------------------------------------------------------
# Every ctx field explicitly injected (F6 hazard test)
# ---------------------------------------------------------------------------
class TestCtxFieldInjection:
    def test_no_lazy_real_singleton_resolution_seams(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        bot = _make_bot()
        harness = build_shadow_close(bot, data_dir=tmp_path)
        assert harness is not None
        ctx = harness.ctx

        none_fields = [
            f.name for f in dataclasses.fields(CloseCtx)
            if getattr(ctx, f.name) is None
        ]
        assert sorted(none_fields) == sorted(_DOCUMENTED_NONE), (
            f"unexpected None ctx field(s) -- F6 hazard: "
            f"{sorted(set(none_fields) - set(_DOCUMENTED_NONE))}"
        )
        for name in _MUST_BE_NON_NONE:
            assert getattr(ctx, name) is not None, f"ctx.{name} must not be None (F6 hazard)"

        # risk_mgr is the required field -- must be the shadow stand-in,
        # never a real execution.risk.RiskManager.
        assert isinstance(ctx.risk_mgr, ShadowRiskManager)

    def test_autopsy_should_run_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        harness = build_shadow_close(_make_bot(), data_dir=tmp_path)
        assert harness.ctx.autopsy.should_run_autopsy(999) is False

    def test_ab_manager_get_active_experiments_returns_list(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        harness = build_shadow_close(_make_bot(), data_dir=tmp_path)
        assert harness.ctx.ab_manager.get_active_experiments() == []


# ---------------------------------------------------------------------------
# ISOLATION -- the critical safety test.
# ---------------------------------------------------------------------------
class TestIsolation:
    def test_zero_writes_outside_shadow_and_zero_real_resolution(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        monkeypatch.setenv("LLM_MULTI_AGENT", "true")  # force the llm_learning_agent path to run

        def _boom(*_a, **_kw):
            raise AssertionError(
                "REAL production singleton/collaborator resolved inside shadow "
                "mode -- F6 hazard regression"
            )

        # Every NAMED lazy "_default_*" resolver across all five
        # close_subscribers_*.py modules -- these are exactly the seams
        # that would resolve REAL ledger/learning writers, REAL process-wide
        # singletons, or (worst case) a REAL live claude -p LLM call if this
        # shadow ctx ever left the corresponding field None.
        import core.close_pipeline.close_subscribers_accounting as acc_mod
        import core.close_pipeline.close_subscribers_learning as l1_mod
        import core.close_pipeline.close_subscribers_learning2 as l2_mod
        import core.close_pipeline.close_subscribers_misc as misc_mod
        import core.close_pipeline.close_subscribers_llm_learning_agent as llm_mod

        for mod, names in [
            (acc_mod, [
                "_default_log_trade", "_default_record_trade_outcome",
                "_default_log_closed_trade", "_default_journal_booked",
            ]),
            (l1_mod, ["_default_graduated_rules_engine"]),
            (l2_mod, [
                "_default_thesis_grader", "_default_autopsy_engine",
                "_default_learning_integrator", "_default_post_trade_learner",
                "_default_log_signal_outcome_fn", "_default_rl_append_transition_fn",
            ]),
            (misc_mod, [
                "_default_adaptive_sizer", "_default_survival_record_outcome_fn",
                "_default_telemetry_cls", "_default_format_trade_event_fn",
            ]),
            (llm_mod, ["_default_learning_agent_fn", "_default_process_agent_lesson_fn"]),
        ]:
            for name in names:
                monkeypatch.setattr(mod, name, _boom)

        # Two inline-import hazards with no named _default_* resolver (see
        # close_subscribers_misc.py's on_close_discovery_corpus /
        # on_close_learning_mode) -- patch the REAL target functions
        # directly so a regression that stops injecting add_observation_fn/
        # learning_mode_*_fn would still be caught here.
        import llm.strategy_discovery.corpus as corpus_mod
        import llm.learning_mode as learning_mode_mod
        monkeypatch.setattr(corpus_mod, "add_observation", _boom)
        monkeypatch.setattr(learning_mode_mod, "is_learning_mode_active", _boom)
        monkeypatch.setattr(learning_mode_mod, "record_trade_observed", _boom)

        bot = _make_bot()
        harness = build_shadow_close(bot, data_dir=tmp_path)
        assert harness is not None

        pos = _make_position(position_id="shadow-iso-pid-1")
        partial_event = _partial_event(pos)
        terminal_event = _terminal_event(pos, total_pnl=12.0)

        tc_partial = TradeClosed.from_trade_event(partial_event, position=pos, equity_after=5002.5)
        tc_terminal = TradeClosed.from_trade_event(terminal_event, position=pos, equity_after=5012.0)

        report_partial = harness.bus.publish(tc_partial)
        report_terminal = harness.bus.publish(tc_terminal)

        # No subscriber raised -- if any _default_* resolver above HAD been
        # invoked, it would have raised AssertionError, been caught by
        # CloseBus's per-subscriber isolation (close_bus.py), and recorded
        # here as a failure. Zero failures is the structural proof that
        # none of the real resolvers ever ran.
        assert report_partial.failed == [], f"unexpected subscriber failures: {report_partial.failed}"
        assert report_terminal.failed == [], f"unexpected subscriber failures: {report_terminal.failed}"
        assert report_terminal.delivered, "expected at least some subscribers to actually run"

        # Also exercise the convenience wrapper the multi_strategy_main.py
        # tap actually calls.
        tc_via_wrapper = harness.publish_shadow(
            terminal_event, position=pos, equity_after=5012.0, session_dd_pct=0.0,
            close_volatility=1.2, compound_mult=1.0, btc_trend="bullish", funding_rate=0.0001,
        )
        assert tc_via_wrapper is not None
        harness.append_god_reference(
            event_id=tc_via_wrapper.event_id, god_total_pnl=12.0, god_equity_after=5012.0,
            god_session_dd=0.0, god_daily_pnl=12.0, god_llm_mode="FULL",
        )

        # ---- ZERO WRITES OUTSIDE <tmp_path>/shadow/ ----
        shadow_dir = tmp_path / "shadow"
        all_files = [p for p in tmp_path.rglob("*") if p.is_file()]
        outside = [p for p in all_files if shadow_dir not in p.parents]
        assert outside == [], f"files written OUTSIDE data/shadow/: {outside}"
        assert all_files, "expected shadow files to actually be written (harness looks inert)"

        # ---- proof the LLM-adjacent recorder was actually exercised
        # THROUGH the stub (not skipped, not routed around it) ----
        learning_agent_sink = shadow_dir / "calls" / "learning_agent_fn.jsonl"
        assert learning_agent_sink.exists(), "learning_agent_fn recorder never invoked"
        lines = [
            json.loads(line) for line in learning_agent_sink.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) >= 1
        assert lines[0]["subscriber"] == "learning_agent_fn"

        # ---- real shadow ledger/logger actually wrote diffable rows ----
        shadow_ledger_csv = shadow_dir / "trade_ledger.csv"
        assert shadow_ledger_csv.exists()
        assert "shadow-iso-pid-1" in shadow_ledger_csv.read_text(encoding="utf-8")

    def test_zero_writes_when_no_events_published(self, monkeypatch, tmp_path):
        """Building the harness alone (before any publish) must not create
        any files beyond the directories it needs -- proves construction
        itself has no side effects beyond directory scaffolding."""
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        harness = build_shadow_close(_make_bot(), data_dir=tmp_path)
        assert harness is not None
        # TradeLedger/TradeLogger construction creates their own header/
        # timestamped files -- that's expected (byte-diffable shadow
        # ledger/logger, see module docstring) -- but everything must still
        # be under data/shadow/.
        shadow_dir = tmp_path / "shadow"
        all_files = [p for p in tmp_path.rglob("*") if p.is_file()]
        outside = [p for p in all_files if shadow_dir not in p.parents]
        assert outside == []


# ---------------------------------------------------------------------------
# REAL FOUNDATION FILES UNTOUCHED -- hardened isolation guard.
#
# WHY THIS CLASS EXISTS: TestIsolation above proves "zero writes outside
# <tmp_path>/shadow/" via ``tmp_path.rglob("*")`` -- but that check is BLIND
# to any write that escapes tmp_path entirely through a ``__file__``-anchored
# path. ``core.position_journal.journal_booked()`` resolves its target via
# ``core.paths.position_journal_path()``, which is anchored to the real
# ``core/paths.py``-relative ``DATA_DIR`` REGARDLESS of any ``data_dir``
# passed to ``build_shadow_close`` -- so a direct-import call to it (the F6
# bug this build fixes: see close_context.py's ``journal_booked_fn`` field
# note) writes to the REAL ``bot/data/position_journal.jsonl``, a location
# entirely outside ``tmp_path`` and therefore invisible to the rglob check.
# This class closes that blind spot by asserting the REAL foundation files'
# on-disk state is byte-for-byte unchanged across a synthetic shadow
# PARTIAL+TERMINAL publish -- it would have FAILED before the
# ``journal_booked_fn`` routing fix (the real ``position_journal.jsonl``'s
# mtime/size would have moved) and PASSES now that ``on_close_ledger`` only
# ever calls the injected ``CallRecorder`` in shadow mode.
#
# SNAPSHOT-ONLY, NEVER CREATES: this test must not itself cause any of these
# real files to spring into existence. It only ``stat()``s them; if a target
# is absent before, it asserts the target is STILL absent after -- it never
# opens/creates/writes any of them.
# ---------------------------------------------------------------------------
class TestRealFoundationFilesUntouched:
    _REAL_TARGETS = {
        "position_journal": staticmethod(paths.position_journal_path),
        "risk_equity_state": staticmethod(paths.risk_equity_state_path),
        "trade_ledger": staticmethod(paths.trade_ledger_path),
        # No dedicated core.paths accessor exists for safety_events.csv
        # (execution/risk.py resolves it via its own CWD-relative
        # ``_SAFETY_LOG_FILE``, not core.paths) -- anchor it off the same
        # real, __file__-anchored ``paths.DATA_DIR`` every other accessor in
        # this module derives from, so this check still targets the one
        # real ``bot/data/logs/safety_events.csv`` regardless of CWD.
        "safety_events": staticmethod(lambda: paths.DATA_DIR / "logs" / "safety_events.csv"),
    }

    @classmethod
    def _snapshot(cls) -> dict:
        snap = {}
        for name, getter in cls._REAL_TARGETS.items():
            p = getter()
            if p.exists():
                st = p.stat()
                snap[name] = (True, st.st_mtime_ns, st.st_size)
            else:
                snap[name] = (False, None, None)
        return snap

    def test_real_data_files_unchanged_by_shadow_partial_and_terminal_publish(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("CLOSE_BUS_SHADOW", "true")
        before = self._snapshot()

        bot = _make_bot()
        harness = build_shadow_close(bot, data_dir=tmp_path)
        assert harness is not None

        pos = _make_position(position_id="shadow-realfile-guard-1")
        partial_event = _partial_event(pos)
        terminal_event = _terminal_event(pos, total_pnl=9.0)

        tc_partial = TradeClosed.from_trade_event(partial_event, position=pos, equity_after=5002.5)
        tc_terminal = TradeClosed.from_trade_event(terminal_event, position=pos, equity_after=5009.0)

        report_partial = harness.bus.publish(tc_partial)
        report_terminal = harness.bus.publish(tc_terminal)
        assert report_partial.failed == [], f"unexpected subscriber failures: {report_partial.failed}"
        assert report_terminal.failed == [], f"unexpected subscriber failures: {report_terminal.failed}"
        assert report_terminal.delivered, "expected at least some subscribers to actually run"

        after = self._snapshot()
        for name in self._REAL_TARGETS:
            assert after[name] == before[name], (
                f"REAL foundation file changed during a SHADOW publish -- "
                f"shadow wiring escaped data/shadow/ via a __file__-anchored "
                f"write path: {name} before={before[name]} after={after[name]}"
            )

        # Positive control: confirm the fixed seam (journal_booked_fn) was
        # actually exercised THROUGH the recorder for this publish, not
        # skipped entirely -- otherwise the mtime-unchanged assertion above
        # would trivially pass for the wrong reason (subscriber never ran).
        journal_sink = (tmp_path / "shadow" / "calls" / "journal_booked_fn.jsonl")
        assert journal_sink.exists(), "journal_booked_fn recorder never invoked"
        recorded = [
            json.loads(line) for line in journal_sink.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(r.get("subscriber") == "journal_booked_fn" for r in recorded)


# ---------------------------------------------------------------------------
# CallRecorder unit behavior
# ---------------------------------------------------------------------------
class TestCallRecorder:
    def test_records_calls_and_returns_default_none(self, tmp_path):
        sink = tmp_path / "calls" / "foo.jsonl"
        rec = CallRecorder("foo", sink)
        result = rec.some_method(1, 2, key="value")
        assert result is None
        assert rec.call_count == 1
        rows = [json.loads(l) for l in sink.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["subscriber"] == "foo"
        assert rows[0]["method"] == "some_method"
        assert rows[0]["kwargs"] == {"key": "value"}

    def test_returns_override_default(self, tmp_path):
        sink = tmp_path / "calls" / "bar.jsonl"
        rec = CallRecorder("bar", sink, returns={"should_run_autopsy": False, "get_active_experiments": []})
        assert rec.should_run_autopsy(5) is False
        assert rec.get_active_experiments() == []
        assert rec.call_count == 2

    def test_callable_shape(self, tmp_path):
        sink = tmp_path / "calls" / "baz.jsonl"
        rec = CallRecorder("baz", sink)
        result = rec(symbol="BTC-USD", pnl=1.0)
        assert result is None
        assert rec.call_count == 1


# ---------------------------------------------------------------------------
# ShadowRiskManager unit behavior
# ---------------------------------------------------------------------------
class TestShadowRiskManager:
    def test_update_equity_purely_in_memory(self):
        rm = ShadowRiskManager(starting_equity=1000.0)
        rm.update_equity(50.0)
        assert rm.equity == 1050.0
        assert rm.circuit_breaker.consecutive_losses == 0
        rm.update_equity(-30.0)
        assert rm.equity == 1020.0
        assert rm.circuit_breaker.consecutive_losses == 1

    def test_equity_trace_written_under_shadow_dir(self, tmp_path):
        trace_path = tmp_path / "shadow" / "equity_trace.jsonl"
        rm = ShadowRiskManager(starting_equity=1000.0, equity_trace_path=trace_path)
        rm.update_equity(10.0)
        rm.update_equity(-5.0)
        assert trace_path.exists()
        rows = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2
        assert rows[0]["pnl_delta"] == 10.0
        assert rows[1]["shadow_equity_after"] == 1005.0
