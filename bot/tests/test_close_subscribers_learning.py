"""Tests for the LEARNING-TIER (T2) close_bus subscribers (Phase 0.4-B,
batch 1).

Scope: weight_mgr, regime_feedback, confidence_floor, hold_time_rules,
parameter_tuner, feedback, graduated_rules, ic_tracker, kelly. All
collaborators are mocked -- these tests MUST NOT touch any real data file
under bot/data/.
"""
from __future__ import annotations

import ast
import os

import pytest
from unittest.mock import Mock

from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_learning import (
    on_close_confidence_floor,
    on_close_feedback,
    on_close_graduated_rules,
    on_close_hold_time_rules,
    on_close_ic_tracker,
    on_close_kelly,
    on_close_parameter_tuner,
    on_close_regime_feedback,
    on_close_weight_mgr,
    register_learning,
)

SUBSCRIBERS_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "close_pipeline", "close_subscribers_learning.py",
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
        pnl_pct_of_equity=1.0,  # == 50 / 5000 * 100 (matches equity_after basis)
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
            "ev_per_dollar": "0.12",
            "regime": "trend",
            "llm_action": "BUY",
            "llm_confidence": 0.81,
            "llm_agreed": True,
        },
        trade_profile={"entry_type": "TREND", "primary_driver": "regime_trend", "regime": "trending"},
        state_path="IDLE->OPEN->TRAILING->CLOSED",
        outcome="WIN",
        open_time="2026-07-15T14:30:00+00:00",
        hold_time_s=1800.0,
        entry_type="TREND",
        primary_driver="regime_trend",
        regime="trend",
        llm_action="BUY",
        llm_conf=0.81,
        llm_agreed=True,
        mfe_pct=1.2,
        mae_pct=-0.3,
    )
    defaults.update(overrides)
    return TradeClosed(**defaults)


def _fake_ctx(**overrides) -> CloseCtx:
    risk_mgr = Mock()
    risk_mgr.equity = 5000.0
    ctx = CloseCtx(
        risk_mgr=risk_mgr,
        weight_mgr=Mock(),
        regime_feedback=Mock(),
        confidence_floor=Mock(),
        hold_time_rules=Mock(),
        parameter_tuner=Mock(),
        feedback=Mock(),
        ic_tracker=Mock(),
        kelly_engine=Mock(),
        graduated_rules_engine=Mock(),
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# Grep/AST guard: ZERO occurrences of the live-refetch anti-patterns.
# ---------------------------------------------------------------------------
class TestGrepGuard:
    """Mechanically enforces spec04.md's R5/R7/R10 invariant for the
    learning-tier file: every value used comes off the frozen ``TradeClosed``
    event or the injected ``CloseCtx`` -- never a live ``pos_mgr.positions``
    re-read, a ``risk_mgr.equity`` read-for-derivation, or a bare ``.pnl``
    (per-leg) attribute used as if it were the position's authoritative
    total (these are FULL-close-only, terminal-total learning hooks --
    ``ev.total_pnl`` / ``ev.pnl_pct_of_equity`` exclusively).
    """

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
        """Unlike the accounting-tier file (which legitimately uses
        per-leg ``ev.pnl`` in three T0/T1 subscribers), EVERY learning-tier
        subscriber is FULL-close-only and terminal-total-only -- so a bare
        ``.pnl`` attribute access (as opposed to ``.total_pnl`` or
        ``.pnl_pct_of_equity``, different attribute names never confused by
        this exact-match check) must never appear anywhere in this file.
        """
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
# T2-a weight_mgr
# ---------------------------------------------------------------------------
class TestWeightMgr:
    def test_records_win_with_strategy_and_symbol(self):
        ev = _make_terminal_event(strategy="regime_trend", symbol="ETH", total_pnl=50.0)
        ctx = _fake_ctx()
        on_close_weight_mgr(ev, ctx)
        ctx.weight_mgr.record_outcome.assert_called_once_with("regime_trend", True, symbol="ETH")

    def test_empty_strategy_falls_back_to_ensemble(self):
        ev = _make_terminal_event(strategy="", total_pnl=-10.0)
        ctx = _fake_ctx()
        on_close_weight_mgr(ev, ctx)
        ctx.weight_mgr.record_outcome.assert_called_once_with("ensemble", False, symbol="BTC")

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(weight_mgr=None)
        on_close_weight_mgr(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-b regime_feedback
# ---------------------------------------------------------------------------
class TestRegimeFeedback:
    def test_default_uses_raw_total_pnl(self, monkeypatch):
        monkeypatch.delenv("REGIME_FB_FIX", raising=False)
        ev = _make_terminal_event(total_pnl=50.0, regime="trend", confidence=72.0, hold_time_s=3600.0)
        ctx = _fake_ctx()
        on_close_regime_feedback(ev, ctx)
        kwargs = ctx.regime_feedback.record_trade.call_args.kwargs
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["regime"] == "trend"
        assert kwargs["confidence"] == pytest.approx(72.0)
        assert kwargs["hold_hours"] == pytest.approx(1.0)
        assert kwargs["metadata"] == {"symbol": "BTC", "action": "SL"}

    def test_fix_env_uses_pct_of_equity(self, monkeypatch):
        monkeypatch.setenv("REGIME_FB_FIX", "true")
        ev = _make_terminal_event(total_pnl=50.0, pnl_pct_of_equity=1.0)
        ctx = _fake_ctx()
        on_close_regime_feedback(ev, ctx)
        kwargs = ctx.regime_feedback.record_trade.call_args.kwargs
        assert kwargs["pnl"] == pytest.approx(1.0)
        assert kwargs["metadata"]["pnl_usd"] == pytest.approx(50.0)

    def test_missing_regime_defaults_unknown(self):
        ev = _make_terminal_event(regime="")
        ctx = _fake_ctx()
        on_close_regime_feedback(ev, ctx)
        kwargs = ctx.regime_feedback.record_trade.call_args.kwargs
        assert kwargs["regime"] == "unknown"

    def test_zero_confidence_falls_back_to_50(self):
        ev = _make_terminal_event(confidence=0.0)
        ctx = _fake_ctx()
        on_close_regime_feedback(ev, ctx)
        kwargs = ctx.regime_feedback.record_trade.call_args.kwargs
        assert kwargs["confidence"] == pytest.approx(50.0)

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(regime_feedback=None)
        on_close_regime_feedback(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-c confidence_floor
# ---------------------------------------------------------------------------
class TestConfidenceFloor:
    def test_records_full_outcome(self):
        ev = _make_terminal_event(total_pnl=50.0, confidence=72.0, strategy="regime_trend", symbol="BTC", regime="trend")
        ctx = _fake_ctx()
        on_close_confidence_floor(ev, ctx)
        ctx.confidence_floor.record_outcome.assert_called_once_with(
            confidence=72.0, win=True, pnl=50.0, strategy="regime_trend", symbol="BTC", regime="trend",
        )

    def test_loss_marks_win_false(self):
        ev = _make_terminal_event(total_pnl=-30.0)
        ctx = _fake_ctx()
        on_close_confidence_floor(ev, ctx)
        kwargs = ctx.confidence_floor.record_outcome.call_args.kwargs
        assert kwargs["win"] is False

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(confidence_floor=None)
        on_close_confidence_floor(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-d hold_time_rules
# ---------------------------------------------------------------------------
class TestHoldTimeRules:
    def test_records_hold_hours_from_seconds(self):
        ev = _make_terminal_event(hold_time_s=7200.0, regime="trend", total_pnl=50.0)
        ctx = _fake_ctx()
        on_close_hold_time_rules(ev, ctx)
        ctx.hold_time_rules.record_trade.assert_called_once_with(
            regime="trend", hold_hours=2.0, win=True, pnl=50.0,
        )

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(hold_time_rules=None)
        on_close_hold_time_rules(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-e parameter_tuner
# ---------------------------------------------------------------------------
class TestParameterTuner:
    def test_records_total_pnl(self):
        ev = _make_terminal_event(total_pnl=50.0)
        ctx = _fake_ctx()
        on_close_parameter_tuner(ev, ctx)
        ctx.parameter_tuner.record_trade_outcome.assert_called_once_with(50.0)

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(parameter_tuner=None)
        on_close_parameter_tuner(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-f feedback (FeedbackLoop)
# ---------------------------------------------------------------------------
class TestFeedback:
    def test_records_full_outcome_from_trade_profile_and_event(self):
        ev = _make_terminal_event(
            total_pnl=50.0, confidence=72.0, strategy="regime_trend", symbol="BTC",
            side="LONG", trade_profile={"regime": "trending", "entry_type": "TREND"},
            entry_reasons={"num_agree": 2, "llm_action": "BUY", "llm_confidence": 0.81, "llm_agreed": True},
            hold_time_s=1800.0, close_type="SL", leverage=5.0,
        )
        ctx = _fake_ctx()
        on_close_feedback(ev, ctx)
        kwargs = ctx.feedback.record_outcome.call_args.kwargs
        assert kwargs["confidence"] == pytest.approx(72.0)
        assert kwargs["win"] is True
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["strategy"] == "regime_trend"
        assert kwargs["symbol"] == "BTC"
        assert kwargs["regime"] == "trending"        # from trade_profile, not top-level ev.regime
        assert kwargs["side"] == "LONG"
        assert kwargs["entry_type"] == "TREND"        # from trade_profile
        assert kwargs["num_agree"] == 2
        assert kwargs["hold_time_s"] == pytest.approx(1800.0)
        assert kwargs["exit_action"] == "SL"
        assert kwargs["leverage"] == pytest.approx(5.0)
        assert kwargs["llm_action"] == "BUY"
        assert kwargs["llm_confidence"] == pytest.approx(0.81)
        assert kwargs["llm_agreed"] is True

    def test_regime_sourced_from_trade_profile_not_top_level_regime(self):
        """The god-block reads pos.trade_profile.regime here (not
        pos.entry_reasons.regime, which other T2 subscribers use) --
        deliberately different sources, both legitimate."""
        ev = _make_terminal_event(regime="top-level-regime", trade_profile={"regime": "profile-regime"})
        ctx = _fake_ctx()
        on_close_feedback(ev, ctx)
        kwargs = ctx.feedback.record_outcome.call_args.kwargs
        assert kwargs["regime"] == "profile-regime"

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(feedback=None)
        on_close_feedback(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-g graduated_rules
# ---------------------------------------------------------------------------
class TestGraduatedRules:
    def test_records_outcome_with_hour_from_open_time(self):
        ev = _make_terminal_event(
            symbol="BTC", side="LONG", total_pnl=50.0,
            open_time="2026-07-15T14:30:00+00:00",
            entry_reasons={"strategies_agree": ["regime_trend", "confidence_scorer"], "confidence": 72.0, "regime": "trend"},
        )
        ctx = _fake_ctx()
        on_close_graduated_rules(ev, ctx)
        kwargs = ctx.graduated_rules_engine.record_outcome.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["side"] == "LONG"
        assert kwargs["won"] is True
        assert kwargs["hour_utc"] == 14
        assert kwargs["strategies_active"] == ["regime_trend", "confidence_scorer"]
        assert kwargs["num_agree"] == 2
        assert kwargs["confidence"] == pytest.approx(72.0)
        assert kwargs["regime"] == "trend"

    def test_confidence_normalized_from_0_1_scale(self):
        ev = _make_terminal_event(entry_reasons={"llm_confidence": 0.65})
        ctx = _fake_ctx()
        on_close_graduated_rules(ev, ctx)
        kwargs = ctx.graduated_rules_engine.record_outcome.call_args.kwargs
        assert kwargs["confidence"] == pytest.approx(65.0)

    def test_missing_open_time_defaults_hour_minus_1(self):
        ev = _make_terminal_event(open_time=None)
        ctx = _fake_ctx()
        on_close_graduated_rules(ev, ctx)
        kwargs = ctx.graduated_rules_engine.record_outcome.call_args.kwargs
        assert kwargs["hour_utc"] == -1

    def test_uses_injected_engine_not_default_lazy_import(self):
        """Must not attempt the real llm.graduated_rules singleton when a
        mock engine is injected via ctx."""
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_graduated_rules(ev, ctx)
        ctx.graduated_rules_engine.record_outcome.assert_called_once()


# ---------------------------------------------------------------------------
# T2-h ic_tracker
# ---------------------------------------------------------------------------
class TestIcTracker:
    def test_records_signed_market_return_per_factor_long(self):
        ev = _make_terminal_event(
            side="LONG", entry=50000.0, price=50500.0,
            entry_reasons={"strategies_agree": ["regime_trend", "confidence_scorer"]},
        )
        ctx = _fake_ctx()
        on_close_ic_tracker(ev, ctx)
        calls = ctx.ic_tracker.record.call_args_list
        assert len(calls) == 2
        expected_return = (50500.0 - 50000.0) / 50000.0
        for c in calls:
            factor, direction, market_return = c.args
            assert direction == 1
            assert market_return == pytest.approx(expected_return)
        assert {c.args[0] for c in calls} == {"regime_trend", "confidence_scorer"}

    def test_short_direction_is_negative_one(self):
        ev = _make_terminal_event(side="SHORT", entry=50000.0, price=49500.0)
        ctx = _fake_ctx()
        on_close_ic_tracker(ev, ctx)
        _, direction, _ = ctx.ic_tracker.record.call_args.args
        assert direction == -1

    def test_invalid_prices_skip_recording(self):
        ev = _make_terminal_event(entry=0.0, price=50100.0)
        ctx = _fake_ctx()
        on_close_ic_tracker(ev, ctx)
        ctx.ic_tracker.record.assert_not_called()

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(ic_tracker=None)
        on_close_ic_tracker(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# T2-i kelly
# ---------------------------------------------------------------------------
class TestKelly:
    def test_records_pct_of_equity_per_factor(self):
        ev = _make_terminal_event(
            total_pnl=50.0, pnl_pct_of_equity=1.0,
            entry_reasons={"strategies_agree": ["regime_trend"]},
        )
        ctx = _fake_ctx()
        on_close_kelly(ev, ctx)
        ctx.kelly_engine.record_trade.assert_called_once_with("regime_trend", True, 1.0)

    def test_loss_records_won_false(self):
        ev = _make_terminal_event(total_pnl=-30.0, pnl_pct_of_equity=-0.6)
        ctx = _fake_ctx()
        on_close_kelly(ev, ctx)
        factor, won, pnl_pct = ctx.kelly_engine.record_trade.call_args.args
        assert won is False
        assert pnl_pct == pytest.approx(-0.6)

    def test_missing_pct_of_equity_falls_back_to_zero(self):
        ev = _make_terminal_event(pnl_pct_of_equity=None)
        ctx = _fake_ctx()
        on_close_kelly(ev, ctx)
        _, _, pnl_pct = ctx.kelly_engine.record_trade.call_args.args
        assert pnl_pct == pytest.approx(0.0)

    def test_no_factors_falls_back_to_llm_first(self):
        ev = _make_terminal_event(strategy="", entry_reasons={})
        ctx = _fake_ctx()
        on_close_kelly(ev, ctx)
        factor, _, _ = ctx.kelly_engine.record_trade.call_args.args
        assert factor == "llm_first"

    def test_skipped_when_not_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(kelly_engine=None)
        on_close_kelly(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# Exactly-once via the bus
# ---------------------------------------------------------------------------
class TestExactlyOnceViaBus:
    def test_duplicate_publish_runs_t2_twice_per_bus_dedup_policy(self):
        """CloseBus's applied-store dedup (close_bus.py:279) is scoped to
        ``sub.tier == Tier.T0_CORE_ACCOUNTING`` only -- T2 (this file) is
        NOT deduped by the bus, so a duplicate publish() for the same
        position_id runs every learning subscriber again, exactly like T1
        in close_subscribers_accounting.py. This documents the bus's real,
        verified behavior rather than a stronger guarantee it doesn't
        provide at this phase (see module docstring's CLOSE_DEDUP_GUARD
        scope note).
        """
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning(bus, ctx)

        ev = _make_terminal_event(position_id="dup-pos", total_pnl=50.0)

        bus.publish(ev)
        bus.publish(ev)

        assert ctx.weight_mgr.record_outcome.call_count == 2
        assert ctx.regime_feedback.record_trade.call_count == 2
        assert ctx.confidence_floor.record_outcome.call_count == 2
        assert ctx.hold_time_rules.record_trade.call_count == 2
        assert ctx.parameter_tuner.record_trade_outcome.call_count == 2
        assert ctx.feedback.record_outcome.call_count == 2
        assert ctx.graduated_rules_engine.record_outcome.call_count == 2
        assert ctx.ic_tracker.record.call_count >= 2
        assert ctx.kelly_engine.record_trade.call_count >= 2

    def test_partial_leg_skips_all_full_only_learning_subscribers(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning(bus, ctx)

        partial_ev = _make_terminal_event(
            position_id="partial-pos", leg_kind=LegKind.PARTIAL, close_type="TP1", total_pnl=19.0,
        )
        report = bus.publish(partial_ev)

        assert ctx.weight_mgr.record_outcome.call_count == 0
        assert ctx.regime_feedback.record_trade.call_count == 0
        assert ctx.confidence_floor.record_outcome.call_count == 0
        assert ctx.hold_time_rules.record_trade.call_count == 0
        assert ctx.parameter_tuner.record_trade_outcome.call_count == 0
        assert ctx.feedback.record_outcome.call_count == 0
        assert ctx.graduated_rules_engine.record_outcome.call_count == 0
        assert ctx.ic_tracker.record.call_count == 0
        assert ctx.kelly_engine.record_trade.call_count == 0
        for name in (
            "weight_mgr", "regime_feedback", "confidence_floor", "hold_time_rules",
            "parameter_tuner", "feedback", "graduated_rules", "ic_tracker", "kelly",
        ):
            assert name in report.skipped

    def test_registration_order_matches_god_block_source_order(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_learning(bus, ctx)
        names = [s.name for s in bus._ordered_subs()]
        assert names == [
            "weight_mgr", "regime_feedback", "confidence_floor", "hold_time_rules",
            "parameter_tuner", "feedback", "graduated_rules", "ic_tracker", "kelly",
        ]
        assert all(s.tier == Tier.T2_DERIVED_READERS for s in bus._ordered_subs())

    def test_one_subscriber_failure_does_not_block_the_rest(self):
        """Per close_bus.py's PER-SUBSCRIBER ISOLATION invariant: a raising
        collaborator must not prevent the other eight from running."""
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        ctx.weight_mgr.record_outcome.side_effect = RuntimeError("boom")
        register_learning(bus, ctx)

        ev = _make_terminal_event(position_id="fail-pos", total_pnl=50.0)
        report = bus.publish(ev)

        assert ("weight_mgr", "RuntimeError('boom')") in report.failed
        assert "regime_feedback" in report.delivered
        assert "kelly" in report.delivered
        ctx.kelly_engine.record_trade.assert_called()
