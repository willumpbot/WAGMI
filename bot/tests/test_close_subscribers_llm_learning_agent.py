"""Tests for the FINAL close_bus subscriber -- the LLM Learning Agent close
hook (Phase 0.4-B, subscriber extraction COMPLETE).

Scope: on_close_llm_learning_agent / register_llm_learning_agent. All
collaborators are mocked -- these tests MUST NOT make a real LLM call and
MUST NOT touch any real data file under bot/data/.
"""
from __future__ import annotations

import ast
import os

import pytest
from unittest.mock import Mock

from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_llm_learning_agent import (
    on_close_llm_learning_agent,
    register_llm_learning_agent,
)
from core.close_types import CloseKind

SUBSCRIBERS_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "close_pipeline",
    "close_subscribers_llm_learning_agent.py",
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _make_terminal_event(**overrides) -> TradeClosed:
    defaults = dict(
        position_id="pos-abc123",
        leg_kind=LegKind.TERMINAL,
        close_type="SL",
        symbol="BTC",
        side="LONG",
        price=50100.0,
        qty=0.1,
        pnl=52.0,
        fee=2.0,
        leverage=5.0,
        strategy="regime_trend",
        total_pnl=50.0,
        equity_after=5050.0,
        pnl_pct_of_equity=1.0,
        entry=50000.0,
        confidence=72.0,
        entry_reasons={
            "llm_notes": "thesis_id=th-1 some notes",
            "agent_confidences": {"trade": 80.0, "risk": 65.0},
        },
        trade_profile={"entry_type": "TREND", "regime": "trending"},
        hold_time_s=1800.0,
    )
    defaults.update(overrides)
    return TradeClosed(**defaults)


def _fake_ctx(**overrides) -> CloseCtx:
    risk_mgr = Mock()
    risk_mgr.equity = 5000.0
    ctx = CloseCtx(
        risk_mgr=risk_mgr,
        llm_multi_agent_enabled=True,
        learning_agent_fn=Mock(return_value={"lesson": "avoid chasing", "category": "entry"}),
        process_agent_lesson_fn=Mock(),
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# Grep/AST guard: ZERO occurrences of the live-refetch anti-patterns.
# ---------------------------------------------------------------------------
class TestGrepGuard:
    @pytest.fixture(scope="class")
    def source_text(self) -> str:
        with open(SUBSCRIBERS_MODULE_PATH, "r", encoding="utf-8") as f:
            return f.read()

    @pytest.fixture(scope="class")
    def tree(self, source_text: str) -> ast.Module:
        return ast.parse(source_text)

    def test_no_live_positions_refetch(self, tree: ast.Module):
        violations = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "positions"
            ):
                violations.append(("positions.get(", node.lineno))
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "positions"
            ):
                violations.append((".positions[", node.lineno))
        assert violations == [], f"live positions refetch found: {violations}"

    def test_no_live_equity_read(self, tree: ast.Module):
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "equity":
                inner = node.value
                inner_name = getattr(inner, "attr", None) or getattr(inner, "id", None)
                if inner_name == "risk_mgr":
                    violations.append(("risk_mgr.equity", node.lineno))
        assert violations == [], f"live risk_mgr.equity read found: {violations}"

    def test_no_bare_pnl_as_total(self, tree: ast.Module):
        """This subscriber must use ``.total_pnl`` exclusively -- unlike
        on_close_alert (misc batch 3), there is no per-leg ``pnl=`` field in
        either LLM payload the god-block builds at this call site."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "pnl":
                violations.append(node.lineno)
        assert violations == [], (
            f"bare `.pnl` attribute access found at lines {violations} -- "
            f"must use `.total_pnl` exclusively."
        )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------
class TestLLMLearningAgent:
    def test_noop_when_llm_multi_agent_disabled(self):
        ctx = _fake_ctx(llm_multi_agent_enabled=False)
        on_close_llm_learning_agent(_make_terminal_event(), ctx)
        ctx.learning_agent_fn.assert_not_called()
        ctx.process_agent_lesson_fn.assert_not_called()

    def test_noop_when_disabled_via_env_default(self, monkeypatch):
        monkeypatch.delenv("LLM_MULTI_AGENT", raising=False)
        ctx = _fake_ctx(llm_multi_agent_enabled=None)
        on_close_llm_learning_agent(_make_terminal_event(), ctx)
        ctx.learning_agent_fn.assert_not_called()

    def test_enabled_via_env_default(self, monkeypatch):
        monkeypatch.setenv("LLM_MULTI_AGENT", "true")
        ctx = _fake_ctx(llm_multi_agent_enabled=None)
        on_close_llm_learning_agent(_make_terminal_event(), ctx)
        ctx.learning_agent_fn.assert_called_once()

    def test_builds_lesson_input_from_event(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_llm_learning_agent(ev, ctx)
        payload = ctx.learning_agent_fn.call_args.args[0]
        assert payload["symbol"] == "BTC"
        assert payload["side"] == "LONG"
        assert payload["outcome"] == "WIN"
        assert payload["pnl"] == pytest.approx(50.0)
        assert payload["pnl_pct"] == pytest.approx(1.0)
        assert payload["pnl_pct_signed"] == pytest.approx(1.0)
        assert payload["confidence"] == pytest.approx(72.0)
        assert payload["regime"] == "trending"
        assert payload["strategy"] == "regime_trend"
        assert payload["hold_time_s"] == pytest.approx(1800.0)
        assert payload["hold_hours"] == pytest.approx(0.5)
        assert payload["exit_action"] == "SL"
        assert payload["exit_price"] == pytest.approx(50100.0)
        assert payload["leverage"] == pytest.approx(5.0)
        assert payload["entry_type"] == "TREND"
        assert "thesis_id=th-1" in payload["notes"]

    def test_loss_outcome(self):
        ev = _make_terminal_event(total_pnl=-25.0, pnl_pct_of_equity=-0.5)
        ctx = _fake_ctx()
        on_close_llm_learning_agent(ev, ctx)
        payload = ctx.learning_agent_fn.call_args.args[0]
        assert payload["outcome"] == "LOSS"
        assert payload["pnl"] == pytest.approx(-25.0)

    def test_calls_process_agent_lesson_with_lesson_and_trade_data(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_llm_learning_agent(ev, ctx)
        ctx.process_agent_lesson_fn.assert_called_once()
        lesson_arg, trade_data_arg = ctx.process_agent_lesson_fn.call_args.args
        assert lesson_arg == {"lesson": "avoid chasing", "category": "entry"}
        assert trade_data_arg["symbol"] == "BTC"
        assert trade_data_arg["side"] == "LONG"
        assert trade_data_arg["outcome"] == "WIN"
        assert trade_data_arg["pnl"] == pytest.approx(50.0)
        assert trade_data_arg["entry_price"] == pytest.approx(50000.0)
        assert trade_data_arg["exit_price"] == pytest.approx(50100.0)
        assert trade_data_arg["price_move_pct"] == pytest.approx(0.2, rel=1e-3)
        assert trade_data_arg["confidence"] == pytest.approx(72.0)
        assert trade_data_arg["agent_confidences"] == {"trade": 80.0, "risk": 65.0}
        assert trade_data_arg["regime"] == "trending"
        assert trade_data_arg["strategy"] == "regime_trend"
        assert "thesis_id=th-1" in trade_data_arg["notes"]

    def test_no_process_call_when_lesson_is_none(self):
        ctx = _fake_ctx(learning_agent_fn=Mock(return_value=None))
        on_close_llm_learning_agent(_make_terminal_event(), ctx)
        ctx.process_agent_lesson_fn.assert_not_called()

    def test_no_process_call_when_lesson_not_a_dict(self):
        ctx = _fake_ctx(learning_agent_fn=Mock(return_value="not a dict"))
        on_close_llm_learning_agent(_make_terminal_event(), ctx)
        ctx.process_agent_lesson_fn.assert_not_called()

    def test_llm_call_raising_is_swallowed(self):
        """The core fire-and-forget contract: a raising LLM mock must never
        propagate out of the subscriber."""
        ctx = _fake_ctx(learning_agent_fn=Mock(side_effect=RuntimeError("LLM boom")))
        on_close_llm_learning_agent(_make_terminal_event(), ctx)  # must not raise
        ctx.process_agent_lesson_fn.assert_not_called()

    def test_process_agent_lesson_raising_is_swallowed(self):
        """A failure in the SECOND (non-LLM) wiring call must also never
        propagate -- matches the god-block's own nested try/except."""
        ctx = _fake_ctx(process_agent_lesson_fn=Mock(side_effect=RuntimeError("wiring boom")))
        on_close_llm_learning_agent(_make_terminal_event(), ctx)  # must not raise

    def test_zero_entry_price_avoids_division_by_zero(self):
        ev = _make_terminal_event(entry=0.0)
        ctx = _fake_ctx()
        on_close_llm_learning_agent(ev, ctx)  # must not raise
        trade_data_arg = ctx.process_agent_lesson_fn.call_args.args[1]
        assert trade_data_arg["price_move_pct"] == 0.0
        assert trade_data_arg["entry_price"] == 0.0

    def test_confidence_and_regime_defaults_when_missing(self):
        ev = _make_terminal_event(confidence=None, trade_profile={}, entry_reasons={})
        ctx = _fake_ctx()
        on_close_llm_learning_agent(ev, ctx)
        payload = ctx.learning_agent_fn.call_args.args[0]
        assert payload["confidence"] == 0
        assert payload["regime"] == ""
        assert payload["entry_type"] == ""
        assert payload["notes"] == ""

    def test_lazy_coordinator_resolution_failure_is_swallowed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def _fail_import(name, *a, **kw):
            if name == "llm.agents.coordinator":
                raise ImportError("no coordinator")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _fail_import)
        ctx = _fake_ctx(learning_agent_fn=None)
        on_close_llm_learning_agent(_make_terminal_event(), ctx)  # must not raise


# ---------------------------------------------------------------------------
# Registration wiring
# ---------------------------------------------------------------------------
class TestRegisterLLMLearningAgent:
    def test_registers_t3_fire_and_forget_not_required_no_replay(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_llm_learning_agent(bus, ctx)
        assert len(bus._subs) == 1
        sub = bus._subs[0]
        assert sub.name == "llm_learning_agent"
        assert sub.tier == Tier.T3_FIRE_AND_FORGET
        assert sub.required is False
        assert sub.replay is False
        assert sub.dedupe is True
        assert sub.kind == (CloseKind.FULL,)

    def test_publish_delivers_full_close_and_skips_partial(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_llm_learning_agent(bus, ctx)

        full_ev = _make_terminal_event()
        report = bus.publish(full_ev)
        assert report.delivered == ["llm_learning_agent"]
        assert report.failed == []
        ctx.learning_agent_fn.assert_called_once()

        ctx2 = _fake_ctx()
        bus2 = CloseBus(applied_store=InMemoryAppliedStore())
        register_llm_learning_agent(bus2, ctx2)
        partial_ev = _make_terminal_event(position_id="pos-partial", leg_kind=LegKind.PARTIAL)
        report2 = bus2.publish(partial_ev)
        assert report2.delivered == []
        assert report2.skipped == ["llm_learning_agent"]
        ctx2.learning_agent_fn.assert_not_called()

    def test_not_replayed_at_boot(self):
        """replay=False -- replay_unacked() must never invoke this
        subscriber, matching spec04.md T-R14 (0 LLM calls on boot replay)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            bus = CloseBus(applied_store=InMemoryAppliedStore(), outbox_path=outbox_path)
            ctx = _fake_ctx()
            register_llm_learning_agent(bus, ctx)

            # A fresh bus (simulating a restart) with the SAME outbox path
            # and a NEW applied store -- this is the "boot replay" scenario.
            bus2 = CloseBus(applied_store=InMemoryAppliedStore(), outbox_path=outbox_path)
            ctx2 = _fake_ctx()
            register_llm_learning_agent(bus2, ctx2)

            ev = _make_terminal_event()
            bus.publish(ev)
            ctx.learning_agent_fn.assert_called_once()

            delivered = bus2.replay_unacked()
            assert delivered == 0
            ctx2.learning_agent_fn.assert_not_called()
