"""Tests for the LEARNING-TIER (T2) close_bus subscribers (Phase 0.4-B,
batch 2 -- MEMORY/ML/LEARNING).

Scope: deep_memory_dna, post_trade_learner, reflection, autopsy,
learning_integrator, thesis_grading, rl_buffer, counterfactual,
signal_outcome, ml. All collaborators are mocked -- these tests MUST NOT
touch any real data file under bot/data/.
"""
from __future__ import annotations

import ast
import os

import pytest
from unittest.mock import Mock, call

from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_learning2 import (
    on_close_autopsy,
    on_close_counterfactual,
    on_close_deep_memory_dna,
    on_close_learning_integrator,
    on_close_ml,
    on_close_post_trade_learner,
    on_close_reflection,
    on_close_rl_buffer,
    on_close_signal_outcome,
    on_close_thesis_grading,
    register_learning2,
)

SUBSCRIBERS_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "close_pipeline", "close_subscribers_learning2.py",
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
        fees_total=2.0,
        funding_costs=0.0,
        equity_after=5050.0,
        pnl_pct_of_equity=1.0,
        session_dd_pct=1.5,
        entry=50000.0,
        original_sl=49500.0,
        original_qty=0.1,
        tp1=50300.0,
        tp2=50600.0,
        confidence=72.0,
        entry_reasons={
            "num_agree": 2,
            "strategies_agree": ["regime_trend", "confidence_scorer"],
            "strategies_agreed": ["regime_trend", "confidence_scorer"],
            "ev_per_dollar": 0.12,
            "regime": "trend",
            "llm_action": "BUY",
            "llm_confidence": 0.81,
            "llm_agreed": True,
            "thesis_id": "th-999",
            "win_prob": 0.6,
            "rr_tp1": 1.8,
            "llm_size_mult": 1.2,
            "trigger": "breakout",
            "setup_key": "trend_pullback",
            "llm_reasoning": "clean breakout with volume",
        },
        trade_profile={"entry_type": "TREND", "primary_driver": "regime_trend", "regime": "trending"},
        state_path="IDLE->OPEN->TRAILING->CLOSED",
        outcome="WIN",
        open_time="2026-07-15T14:30:00+00:00",
        close_time="2026-07-15T15:00:00+00:00",
        hold_time_s=1800.0,
        entry_type="TREND",
        primary_driver="regime_trend",
        regime="trend",
        llm_action="BUY",
        llm_conf=0.81,
        llm_agreed=True,
        mfe_pct=1.2,
        mae_pct=-0.3,
        highest_price=50500.0,
        lowest_price=49900.0,
    )
    defaults.update(overrides)
    return TradeClosed(**defaults)


def _fake_ctx(**overrides) -> CloseCtx:
    risk_mgr = Mock()
    risk_mgr.equity = 5000.0
    ctx = CloseCtx(
        risk_mgr=risk_mgr,
        deep_memory=Mock(),
        thesis_grader=Mock(),
        post_trade_learner=Mock(),
        reflection=Mock(),
        autopsy=Mock(),
        learning_integrator=Mock(),
        ml=Mock(),
        counterfactual=Mock(),
        log_signal_outcome_fn=Mock(),
        rl_append_transition_fn=Mock(),
        risk_per_trade=0.02,
        llm_mode_name="DIRECTION",
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

    def test_no_bare_pnl_attribute_anywhere(self, tree: ast.Module):
        """Every batch-2 subscriber is FULL-close-only and terminal-total-
        only -- so a bare ``.pnl`` attribute access (as opposed to
        ``.total_pnl`` / ``.pnl_pct_of_equity``) must never appear anywhere
        in this file."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "pnl":
                violations.append(node.lineno)
        assert violations == [], (
            f"bare `.pnl` attribute access found at lines {violations} -- "
            f"learning-tier subscribers must use `.total_pnl` / "
            f"`.pnl_pct_of_equity` exclusively."
        )


# ---------------------------------------------------------------------------
# T2-j deep_memory_dna
# ---------------------------------------------------------------------------
class TestDeepMemoryDna:
    def test_records_full_trade_from_event_fields(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_deep_memory_dna(ev, ctx)
        kwargs = ctx.deep_memory.record_full_trade.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["side"] == "LONG"
        assert kwargs["entry_price"] == pytest.approx(50000.0)
        assert kwargs["exit_price"] == pytest.approx(50100.0)
        assert kwargs["sl"] == pytest.approx(49500.0)
        assert kwargs["tp1"] == pytest.approx(50300.0)
        assert kwargs["tp2"] == pytest.approx(50600.0)
        assert kwargs["confidence"] == pytest.approx(72.0)
        assert kwargs["leverage"] == pytest.approx(5.0)
        assert kwargs["regime"] == "trending"  # trade_profile-first
        assert kwargs["strategies_agreed"] == ["regime_trend", "confidence_scorer"]
        assert kwargs["outcome"] == "WIN"
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["hold_time_s"] == pytest.approx(1800.0)
        assert kwargs["exit_reason"] == "SL"
        assert kwargs["llm_action"] == "BUY"
        assert kwargs["llm_confidence"] == pytest.approx(0.81)
        assert kwargs["llm_reasoning"] == "clean breakout with volume"
        assert kwargs["entry_type"] == "TREND"
        assert kwargs["setup_type"] == "trend_pullback"
        assert kwargs["trade_id"] == "BTC_LONG_1784125800"
        # FIELD-GAP defaults
        assert kwargs["btc_trend"] == "neutral"
        assert kwargs["volume_ratio"] == pytest.approx(0.0)
        assert kwargs["funding_rate"] == pytest.approx(0.0)
        assert kwargs["atr"] == pytest.approx(0.0)

    def test_outcome_breakeven_and_loss(self):
        ctx = _fake_ctx()
        on_close_deep_memory_dna(_make_terminal_event(total_pnl=0.0), ctx)
        assert ctx.deep_memory.record_full_trade.call_args.kwargs["outcome"] == "BREAKEVEN"

        ctx2 = _fake_ctx()
        on_close_deep_memory_dna(_make_terminal_event(total_pnl=-5.0), ctx2)
        assert ctx2.deep_memory.record_full_trade.call_args.kwargs["outcome"] == "LOSS"

    def test_missing_open_time_falls_back_to_position_id_trade_id(self):
        ev = _make_terminal_event(open_time=None)
        ctx = _fake_ctx()
        on_close_deep_memory_dna(ev, ctx)
        kwargs = ctx.deep_memory.record_full_trade.call_args.kwargs
        assert kwargs["trade_id"] == "BTC_LONG_pos-abc123"

    def test_strategies_agreed_falls_back_to_strategy(self):
        ev = _make_terminal_event(strategy="regime_trend", entry_reasons={})
        ctx = _fake_ctx()
        on_close_deep_memory_dna(ev, ctx)
        kwargs = ctx.deep_memory.record_full_trade.call_args.kwargs
        assert kwargs["strategies_agreed"] == ["regime_trend"]

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(deep_memory=None)
        on_close_deep_memory_dna(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-k post_trade_learner
# ---------------------------------------------------------------------------
class TestPostTradeLearner:
    def test_generates_lesson_and_applies_memory_update(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        ctx.post_trade_learner.generate_immediate_lesson.return_value = "BTC LONG SL — reduce confidence"
        on_close_post_trade_learner(ev, ctx)
        gen_kwargs = ctx.post_trade_learner.generate_immediate_lesson.call_args.args[0]
        assert gen_kwargs["symbol"] == "BTC"
        assert gen_kwargs["outcome"] == "WIN"
        assert gen_kwargs["regime"] == "trending"
        assert gen_kwargs["funding_rate"] == pytest.approx(0.0)
        ctx.post_trade_learner.apply_memory_update.assert_called_once_with(
            "BTC LONG SL — reduce confidence", symbol="BTC", regime="trending",
        )

    def test_no_lesson_skips_memory_update(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        ctx.post_trade_learner.generate_immediate_lesson.return_value = None
        on_close_post_trade_learner(ev, ctx)
        ctx.post_trade_learner.apply_memory_update.assert_not_called()

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(post_trade_learner=None)
        on_close_post_trade_learner(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-l reflection
# ---------------------------------------------------------------------------
class TestReflection:
    def test_records_full_close_context(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_reflection(ev, ctx)
        kwargs = ctx.reflection.on_close.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["entry_price"] == pytest.approx(50000.0)
        assert kwargs["exit_price"] == pytest.approx(50100.0)
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["regime"] == "trending"
        assert kwargs["sl_price"] == pytest.approx(49500.0)
        assert kwargs["tp1_price"] == pytest.approx(50300.0)
        assert kwargs["peak_price"] == pytest.approx(50500.0)
        assert kwargs["lowest_price"] == pytest.approx(49900.0)
        assert kwargs["win_prob"] == pytest.approx(0.6)
        assert kwargs["rr"] == pytest.approx(1.8)
        assert kwargs["atr"] == pytest.approx(0.0)  # FIELD-GAP
        assert kwargs["entry_reasons"]["thesis_id"] == "th-999"

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(reflection=None)
        on_close_reflection(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-m autopsy
# ---------------------------------------------------------------------------
class TestAutopsy:
    def test_increments_counter_and_runs_when_due(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        ctx.autopsy.should_run_autopsy.return_value = True
        on_close_autopsy(ev, ctx)
        assert ctx.closed_trade_count == 1
        ctx.autopsy.should_run_autopsy.assert_called_once_with(1)
        ctx.autopsy.generate_autopsy.assert_called_once()

    def test_skips_generate_when_not_due(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        ctx.autopsy.should_run_autopsy.return_value = False
        on_close_autopsy(ev, ctx)
        ctx.autopsy.generate_autopsy.assert_not_called()

    def test_counter_persists_across_multiple_calls(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        ctx.autopsy.should_run_autopsy.return_value = False
        on_close_autopsy(ev, ctx)
        on_close_autopsy(ev, ctx)
        on_close_autopsy(ev, ctx)
        assert ctx.closed_trade_count == 3
        assert ctx.autopsy.should_run_autopsy.call_args_list == [call(1), call(2), call(3)]


# ---------------------------------------------------------------------------
# T2-n learning_integrator
# ---------------------------------------------------------------------------
class TestLearningIntegrator:
    def test_calls_on_trade_closed_with_event_derived_dict(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_learning_integrator(ev, ctx)
        ctx.learning_integrator.on_trade_closed.assert_called_once_with({
            "symbol": "BTC",
            "side": "LONG",
            "outcome": "WIN",
            "pnl": 50.0,
            "confidence": 72.0,
            "regime": "trending",
            "strategy": "regime_trend",
        })

    def test_loss_outcome(self):
        ev = _make_terminal_event(total_pnl=-10.0)
        ctx = _fake_ctx()
        on_close_learning_integrator(ev, ctx)
        kwargs = ctx.learning_integrator.on_trade_closed.call_args.args[0]
        assert kwargs["outcome"] == "LOSS"


# ---------------------------------------------------------------------------
# T2-o thesis_grading
# ---------------------------------------------------------------------------
class TestThesisGrading:
    def test_grades_thesis_from_dedicated_key(self):
        ev = _make_terminal_event(side="LONG", pnl_pct_of_equity=1.0)
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        ctx.thesis_grader.close_thesis.assert_called_once_with(
            thesis_id="th-999",
            exit_price=50100.0,
            pnl_pct=1.0,
            max_favorable=50500.0,  # highest_price for LONG
            max_adverse=49900.0,    # lowest_price for LONG
            actual_hold_h=pytest.approx(0.5),
        )

    def test_short_side_swaps_favorable_adverse(self):
        ev = _make_terminal_event(side="SHORT")
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        kwargs = ctx.thesis_grader.close_thesis.call_args.kwargs
        assert kwargs["max_favorable"] == 49900.0  # lowest_price for SHORT
        assert kwargs["max_adverse"] == 50500.0    # highest_price for SHORT

    def test_falls_back_to_notes_parsing_when_no_dedicated_key(self):
        ev = _make_terminal_event(entry_reasons={"llm_notes": "some text thesis_id=abc123|more"})
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        assert ctx.thesis_grader.close_thesis.call_args.kwargs["thesis_id"] == "abc123"

    def test_no_thesis_id_anywhere_skips(self):
        ev = _make_terminal_event(entry_reasons={})
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        ctx.thesis_grader.close_thesis.assert_not_called()

    def test_missing_pnl_pct_of_equity_falls_back_to_zero(self):
        ev = _make_terminal_event(pnl_pct_of_equity=None)
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        assert ctx.thesis_grader.close_thesis.call_args.kwargs["pnl_pct"] == pytest.approx(0.0)

    def test_uses_injected_grader_not_default_lazy_import(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_thesis_grading(ev, ctx)
        ctx.thesis_grader.close_thesis.assert_called_once()


# ---------------------------------------------------------------------------
# T2-p rl_buffer
# ---------------------------------------------------------------------------
class TestRlBuffer:
    def test_appends_transition_from_event(self):
        ev = _make_terminal_event(equity_after=5000.0, total_pnl=50.0)
        ctx = _fake_ctx()
        on_close_rl_buffer(ev, ctx)
        kwargs = ctx.rl_append_transition_fn.call_args.kwargs
        assert kwargs["state"]["symbol"] == "BTC"
        assert kwargs["state"]["regime"] == "trending"
        assert kwargs["state"]["confidence"] == pytest.approx(72.0)
        assert kwargs["state"]["volatility"] == pytest.approx(0.0)
        assert kwargs["action"]["llm_mode"] == "DIRECTION"
        assert kwargs["action"]["llm_action"] == "BUY"
        assert kwargs["action"]["size_multiplier"] == pytest.approx(1.2)
        assert kwargs["action"]["entry_type"] == "TREND"
        # reward = total_pnl / (equity_after * 0.01) = 50 / 50 = 1.0
        assert kwargs["reward"] == pytest.approx(1.0)
        assert kwargs["metadata"]["trigger"] == "breakout"
        assert kwargs["metadata"]["outcome"] == "WIN"
        assert kwargs["metadata"]["pnl"] == pytest.approx(50.0)

    def test_zero_equity_after_falls_back_to_zero_reward(self):
        ev = _make_terminal_event(equity_after=0.0)
        ctx = _fake_ctx()
        on_close_rl_buffer(ev, ctx)
        assert ctx.rl_append_transition_fn.call_args.kwargs["reward"] == pytest.approx(0.0)

    def test_missing_llm_mode_name_defaults_empty_string(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(llm_mode_name=None)
        on_close_rl_buffer(ev, ctx)
        assert ctx.rl_append_transition_fn.call_args.kwargs["action"]["llm_mode"] == ""


# ---------------------------------------------------------------------------
# T2-q counterfactual
# ---------------------------------------------------------------------------
class TestCounterfactual:
    def test_records_exit_alternative_from_event(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_counterfactual(ev, ctx)
        ctx.counterfactual.record_exit_alternative.assert_called_once_with(
            symbol="BTC",
            actual_exit_action="SL",
            actual_exit_price=50100.0,
            tp1_price=50300.0,
            tp2_price=50600.0,
            entry_price=50000.0,
            actual_pnl=50.0,
        )

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(counterfactual=None)
        on_close_counterfactual(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-r signal_outcome
# ---------------------------------------------------------------------------
class TestSignalOutcome:
    def test_logs_outcome_with_risk_per_trade_scaled_pnl_pct(self):
        ev = _make_terminal_event(pnl_pct_of_equity=1.0)
        ctx = _fake_ctx(risk_per_trade=0.02)
        on_close_signal_outcome(ev, ctx)
        kwargs = ctx.log_signal_outcome_fn.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["pnl"] == pytest.approx(50.0)
        # pnl_pct = pnl_pct_of_equity / risk_per_trade = 1.0 / 0.02 = 50.0
        assert kwargs["pnl_pct"] == pytest.approx(50.0)
        assert kwargs["regime"] == "trending"
        assert kwargs["win"] is True

    def test_missing_risk_per_trade_falls_back_to_zero_pct(self):
        ev = _make_terminal_event(pnl_pct_of_equity=1.0)
        ctx = _fake_ctx(risk_per_trade=None)
        on_close_signal_outcome(ev, ctx)
        assert ctx.log_signal_outcome_fn.call_args.kwargs["pnl_pct"] == pytest.approx(0.0)

    def test_missing_pnl_pct_of_equity_falls_back_to_zero_pct(self):
        ev = _make_terminal_event(pnl_pct_of_equity=None)
        ctx = _fake_ctx(risk_per_trade=0.02)
        on_close_signal_outcome(ev, ctx)
        assert ctx.log_signal_outcome_fn.call_args.kwargs["pnl_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# T2-s ml
# ---------------------------------------------------------------------------
class TestMl:
    def test_records_trade_outcome_from_event(self):
        ev = _make_terminal_event(close_time="2026-07-15T15:00:00+00:00")
        ctx = _fake_ctx()
        on_close_ml(ev, ctx)
        outcome = ctx.ml.record_outcome.call_args.args[0]
        assert outcome.symbol == "BTC"
        assert outcome.strategy == "regime_trend"
        assert outcome.win is True
        assert outcome.pnl == pytest.approx(50.0)
        assert outcome.hour_of_day == 15
        assert outcome.day_of_week == 2  # 2026-07-15 is a Wednesday
        assert outcome.close_volatility == pytest.approx(0.0)
        assert outcome.close_price_change_1h_pct == pytest.approx(0.0)
        assert outcome.close_regime == "trending"

    def test_missing_close_time_defaults_hour_and_day_zero(self):
        ev = _make_terminal_event(close_time=None)
        ctx = _fake_ctx()
        on_close_ml(ev, ctx)
        outcome = ctx.ml.record_outcome.call_args.args[0]
        assert outcome.hour_of_day == 0
        assert outcome.day_of_week == 0

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(ml=None)
        on_close_ml(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# Exactly-once via the bus / registration order / isolation
# ---------------------------------------------------------------------------
class TestExactlyOnceViaBus:
    def test_duplicate_publish_runs_t2_twice_per_bus_dedup_policy(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning2(bus, ctx)

        ev = _make_terminal_event(position_id="dup-pos", total_pnl=50.0)

        bus.publish(ev)
        bus.publish(ev)

        assert ctx.deep_memory.record_full_trade.call_count == 2
        assert ctx.post_trade_learner.generate_immediate_lesson.call_count == 2
        assert ctx.reflection.on_close.call_count == 2
        assert ctx.autopsy.should_run_autopsy.call_count == 2
        assert ctx.learning_integrator.on_trade_closed.call_count == 2
        assert ctx.thesis_grader.close_thesis.call_count == 2
        assert ctx.rl_append_transition_fn.call_count == 2
        assert ctx.counterfactual.record_exit_alternative.call_count == 2
        assert ctx.log_signal_outcome_fn.call_count == 2
        assert ctx.ml.record_outcome.call_count == 2

    def test_partial_leg_skips_all_full_only_learning_subscribers(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning2(bus, ctx)

        partial_ev = _make_terminal_event(
            position_id="partial-pos", leg_kind=LegKind.PARTIAL, close_type="TP1", total_pnl=19.0,
        )
        report = bus.publish(partial_ev)

        assert ctx.deep_memory.record_full_trade.call_count == 0
        assert ctx.ml.record_outcome.call_count == 0
        for name in (
            "deep_memory_dna", "post_trade_learner", "reflection", "autopsy",
            "learning_integrator", "thesis_grading", "rl_buffer", "counterfactual",
            "signal_outcome", "ml",
        ):
            assert name in report.skipped

    def test_registration_order_matches_god_block_source_order(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning2(bus, ctx)
        names = [s.name for s in bus._ordered_subs()]
        assert names == [
            "deep_memory_dna", "post_trade_learner", "reflection", "autopsy",
            "learning_integrator", "thesis_grading", "rl_buffer", "counterfactual",
            "signal_outcome", "ml",
        ]
        assert all(s.tier == Tier.T2_DERIVED_READERS for s in bus._ordered_subs())

    def test_one_subscriber_failure_does_not_block_the_rest(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        ctx.deep_memory.record_full_trade.side_effect = RuntimeError("boom")
        register_learning2(bus, ctx)

        ev = _make_terminal_event(position_id="fail-pos", total_pnl=50.0)
        report = bus.publish(ev)

        assert ("deep_memory_dna", "RuntimeError('boom')") in report.failed
        assert "reflection" in report.delivered
        assert "ml" in report.delivered
        ctx.ml.record_outcome.assert_called()
