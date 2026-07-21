"""Tests for the MISC-TIER (T2 + T3) close_bus subscribers (Phase 0.4-B,
batch 3 -- alerts/telemetry/adaptive/survival/cost/demotion-adjacent/
active-learning-adjacent/etc).

Scope: continuous_backtest, shadow_ledger, adaptive_risk, adaptive_sizer
(T2) + llm_triggers_outcome, quant_brain_chase, regime_strategy_weighter,
growth, discovery_corpus, risk_telemetry, survival, ab_testing,
learning_mode, cooldown_tracking, telemetry, llm_triggers_notify,
agent_perf, cost_optimizer, alert (T3). All collaborators are mocked --
these tests MUST NOT touch any real data file under bot/data/.
"""
from __future__ import annotations

import ast
import os

import pytest
from unittest.mock import Mock

from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_misc import (
    on_close_ab_testing,
    on_close_adaptive_risk,
    on_close_adaptive_sizer,
    on_close_agent_perf,
    on_close_alert,
    on_close_continuous_backtest,
    on_close_cooldown_tracking,
    on_close_cost_optimizer,
    on_close_discovery_corpus,
    on_close_growth,
    on_close_learning_mode,
    on_close_llm_triggers_notify,
    on_close_llm_triggers_outcome,
    on_close_quant_brain_chase,
    on_close_regime_strategy_weighter,
    on_close_risk_telemetry,
    on_close_shadow_ledger,
    on_close_survival,
    on_close_telemetry,
    register_misc,
)

SUBSCRIBERS_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "close_pipeline", "close_subscribers_misc.py",
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
            "ev_per_dollar": 0.12,
            "regime": "trend",
            "cost_pipeline": "fast",
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
    ab_manager = Mock()
    ab_manager.get_active_experiments.return_value = []
    ctx = CloseCtx(
        risk_mgr=risk_mgr,
        continuous_backtest=Mock(),
        shadow_ledger=Mock(),
        adaptive_risk=Mock(),
        adaptive_sizer=Mock(),
        llm_triggers=Mock(),
        quant_brain=Mock(),
        regime_strategy_weighter=Mock(),
        growth=Mock(),
        ab_manager=ab_manager,
        agent_perf=Mock(),
        cost_optimizer=Mock(),
        risk_telemetry=Mock(),
        telemetry_cls=Mock(),
        alerts=Mock(),
        format_trade_event_fn=Mock(return_value="formatted message"),
        survival_record_outcome_fn=Mock(),
        learning_mode_active_fn=Mock(return_value=True),
        learning_mode_record_fn=Mock(),
        add_observation_fn=Mock(),
        symbol_daily_loss_limit=-100.0,
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

    def test_no_bare_pnl_as_total_outside_alert(self, tree: ast.Module):
        """Every subscriber EXCEPT ``on_close_alert`` must use ``.total_pnl``
        exclusively (win/loss classification + all recorded pnl values are
        terminal totals). ``on_close_alert`` legitimately reads BOTH
        ``ev.pnl`` (this leg's fill delta, for the message's ``pnl=`` field)
        AND ``ev.total_pnl`` (for the message's ``total_pnl=`` field) --
        matching the god-block's ``format_trade_event_telegram(pnl=event.pnl,
        ..., total_pnl=_total_pnl_alert, ...)`` call exactly -- so it is the
        one documented exception to the "bare .pnl forbidden" rule (see
        the extraction mandate's guard note: "T3 alert/telemetry subs are
        terminal-total -> use ev.total_pnl", which on_close_alert satisfies
        for its `total_pnl` field while ALSO carrying the per-leg `pnl`
        field forward, same as the live message does today).
        """
        violations = []
        alert_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_close_alert":
                alert_func = node
                break
        alert_lines = set()
        if alert_func is not None:
            for sub in ast.walk(alert_func):
                if hasattr(sub, "lineno"):
                    alert_lines.add(sub.lineno)

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "pnl":
                if node.lineno in alert_lines:
                    continue
                violations.append(node.lineno)
        assert violations == [], (
            f"bare `.pnl` attribute access found outside on_close_alert at "
            f"lines {violations} -- misc-tier subscribers must use "
            f"`.total_pnl` exclusively (except the documented alert case)."
        )


# ---------------------------------------------------------------------------
# T2-t continuous_backtest
# ---------------------------------------------------------------------------
class TestContinuousBacktest:
    def test_records_outcome_from_event_fields(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_continuous_backtest(ev, ctx)
        kwargs = ctx.continuous_backtest.record_outcome.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["win"] is True
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["confidence_at_entry"] == pytest.approx(72.0)
        assert kwargs["strategy"] == "regime_trend"
        assert kwargs["regime"] == "trend"
        assert kwargs["hold_time_s"] == pytest.approx(1800.0)
        assert kwargs["exit_action"] == "SL"
        assert kwargs["leverage"] == pytest.approx(5.0)

    def test_confidence_falls_back_to_50(self):
        ev = _make_terminal_event(confidence=None, entry_reasons={})
        ctx = _fake_ctx()
        on_close_continuous_backtest(ev, ctx)
        assert ctx.continuous_backtest.record_outcome.call_args.kwargs["confidence_at_entry"] == pytest.approx(50.0)

    def test_skipped_when_not_configured(self):
        on_close_continuous_backtest(_make_terminal_event(), _fake_ctx(continuous_backtest=None))


# ---------------------------------------------------------------------------
# T2-u shadow_ledger
# ---------------------------------------------------------------------------
class TestShadowLedger:
    def test_resolves_shadows_with_symbol_and_price(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_shadow_ledger(ev, ctx)
        ctx.shadow_ledger.resolve_shadows.assert_called_once_with("BTC", 50100.0)

    def test_skipped_when_not_configured(self):
        on_close_shadow_ledger(_make_terminal_event(), _fake_ctx(shadow_ledger=None))


# ---------------------------------------------------------------------------
# T2-v adaptive_risk
# ---------------------------------------------------------------------------
class TestAdaptiveRisk:
    def test_records_win_and_trade_profile_regime(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_adaptive_risk(ev, ctx)
        ctx.adaptive_risk.record_outcome.assert_called_once_with(win=True, regime="trending")

    def test_loss(self):
        ev = _make_terminal_event(total_pnl=-10.0)
        ctx = _fake_ctx()
        on_close_adaptive_risk(ev, ctx)
        assert ctx.adaptive_risk.record_outcome.call_args.kwargs["win"] is False

    def test_skipped_when_not_configured(self):
        on_close_adaptive_risk(_make_terminal_event(), _fake_ctx(adaptive_risk=None))


# ---------------------------------------------------------------------------
# T2-w adaptive_sizer
# ---------------------------------------------------------------------------
class TestAdaptiveSizer:
    def test_records_outcome_via_injected_sizer(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_adaptive_sizer(ev, ctx)
        ctx.adaptive_sizer.record_outcome.assert_called_once_with("BTC", won=True)

    def test_lazy_default_resolves_when_none(self, monkeypatch):
        sizer = Mock()
        monkeypatch.setattr(
            "core.close_pipeline.close_subscribers_misc._default_adaptive_sizer",
            lambda: sizer,
        )
        ev = _make_terminal_event()
        ctx = _fake_ctx(adaptive_sizer=None)
        on_close_adaptive_sizer(ev, ctx)
        sizer.record_outcome.assert_called_once_with("BTC", won=True)


# ---------------------------------------------------------------------------
# T3-a llm_triggers_outcome
# ---------------------------------------------------------------------------
class TestLLMTriggersOutcome:
    def test_records_trade_outcome(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_llm_triggers_outcome(ev, ctx)
        ctx.llm_triggers.record_trade_outcome.assert_called_once_with(
            strategy="regime_trend", entry_type="TREND", win=True,
        )

    def test_skipped_when_not_configured(self):
        on_close_llm_triggers_outcome(_make_terminal_event(), _fake_ctx(llm_triggers=None))


# ---------------------------------------------------------------------------
# T3-b quant_brain_chase
# ---------------------------------------------------------------------------
class TestQuantBrainChase:
    def test_records_outcome(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_quant_brain_chase(ev, ctx)
        ctx.quant_brain.record_outcome.assert_called_once_with("BTC", True)

    def test_skipped_when_not_configured(self):
        on_close_quant_brain_chase(_make_terminal_event(), _fake_ctx(quant_brain=None))


# ---------------------------------------------------------------------------
# T3-c regime_strategy_weighter
# ---------------------------------------------------------------------------
class TestRegimeStrategyWeighter:
    def test_records_outcome_when_regime_and_strategy_present(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_regime_strategy_weighter(ev, ctx)
        ctx.regime_strategy_weighter.record_outcome.assert_called_once_with("trending", "regime_trend", True)

    def test_skipped_when_none(self):
        on_close_regime_strategy_weighter(_make_terminal_event(), _fake_ctx(regime_strategy_weighter=None))

    def test_skipped_when_regime_empty(self):
        ev = _make_terminal_event(trade_profile={})
        ctx = _fake_ctx()
        on_close_regime_strategy_weighter(ev, ctx)
        ctx.regime_strategy_weighter.record_outcome.assert_not_called()

    def test_skipped_when_strategy_empty(self):
        ev = _make_terminal_event(strategy="")
        ctx = _fake_ctx()
        on_close_regime_strategy_weighter(ev, ctx)
        ctx.regime_strategy_weighter.record_outcome.assert_not_called()


# ---------------------------------------------------------------------------
# T3-d growth
# ---------------------------------------------------------------------------
class TestGrowth:
    def test_on_trade_closed_payload(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_growth(ev, ctx)
        payload = ctx.growth.on_trade_closed.call_args.args[0]
        assert payload["symbol"] == "BTC"
        assert payload["outcome"] == "WIN"
        assert payload["pnl"] == pytest.approx(50.0)
        assert payload["pnl_pct"] == pytest.approx(1.0)
        assert payload["regime"] == "trending"
        assert payload["entry_type"] == "TREND"
        assert payload["hour"] == 15  # from close_time 15:00:00Z

    def test_skipped_when_not_configured(self):
        on_close_growth(_make_terminal_event(), _fake_ctx(growth=None))


# ---------------------------------------------------------------------------
# T3-e discovery_corpus
# ---------------------------------------------------------------------------
class TestDiscoveryCorpus:
    def test_adds_observation(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_discovery_corpus(ev, ctx)
        kwargs = ctx.add_observation_fn.call_args.kwargs
        assert kwargs["category"] == "trade_outcome"
        assert kwargs["symbol"] == "BTC"
        assert kwargs["regime"] == "trending"
        assert "regime_trend LONG WIN" in kwargs["observation"]

    def test_lazy_import_failure_is_swallowed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def _fail_import(name, *a, **kw):
            if name == "llm.strategy_discovery.corpus":
                raise ImportError("no corpus")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _fail_import)
        on_close_discovery_corpus(_make_terminal_event(), _fake_ctx(add_observation_fn=None))


# ---------------------------------------------------------------------------
# T3-f risk_telemetry
# ---------------------------------------------------------------------------
class TestRiskTelemetry:
    def test_updates_with_frozen_equity_and_zero_daily_pnl_gap(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_risk_telemetry(ev, ctx)
        ctx.risk_telemetry.update.assert_called_once_with(equity=5050.0, daily_pnl=0.0)

    def test_skipped_when_not_configured(self):
        on_close_risk_telemetry(_make_terminal_event(), _fake_ctx(risk_telemetry=None))


# ---------------------------------------------------------------------------
# T3-g survival
# ---------------------------------------------------------------------------
class TestSurvival:
    def test_records_outcome_with_zero_funding_gap(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_survival(ev, ctx)
        ctx.survival_record_outcome_fn.assert_called_once_with(
            outcome="WIN", pnl=50.0, funding_cost=0.0, equity=5050.0,
        )

    def test_loss_outcome_string(self):
        ev = _make_terminal_event(total_pnl=-5.0)
        ctx = _fake_ctx()
        on_close_survival(ev, ctx)
        assert ctx.survival_record_outcome_fn.call_args.kwargs["outcome"] == "LOSS"

    def test_lazy_import_failure_is_swallowed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def _fail_import(name, *a, **kw):
            if name == "llm.survival_pressure":
                raise ImportError("no survival module")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _fail_import)
        on_close_survival(_make_terminal_event(), _fake_ctx(survival_record_outcome_fn=None))


# ---------------------------------------------------------------------------
# T3-h ab_testing
# ---------------------------------------------------------------------------
class TestABTesting:
    def test_records_outcome_per_active_experiment(self):
        exp = Mock(id="exp-1")
        ctx = _fake_ctx()
        ctx.ab_manager.get_active_experiments.return_value = [exp]
        ctx.ab_manager.get_assignment.return_value = "variant"
        ev = _make_terminal_event()
        on_close_ab_testing(ev, ctx)
        ctx.ab_manager.get_assignment.assert_called_once_with("exp-1", "BTC", "regime_trend")
        kwargs = ctx.ab_manager.record_outcome.call_args.kwargs
        assert kwargs["experiment_id"] == "exp-1"
        assert kwargs["group"] == "variant"
        assert kwargs["symbol"] == "BTC"
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["win"] is True
        assert kwargs["metadata"]["regime"] == "trending"

    def test_no_active_experiments_records_nothing(self):
        ctx = _fake_ctx()
        ctx.ab_manager.get_active_experiments.return_value = []
        on_close_ab_testing(_make_terminal_event(), ctx)
        ctx.ab_manager.record_outcome.assert_not_called()

    def test_skipped_when_not_configured(self):
        on_close_ab_testing(_make_terminal_event(), _fake_ctx(ab_manager=None))


# ---------------------------------------------------------------------------
# T3-i learning_mode
# ---------------------------------------------------------------------------
class TestLearningMode:
    def test_records_when_active(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_learning_mode(ev, ctx)
        ctx.learning_mode_record_fn.assert_called_once_with(
            symbol="BTC", side="LONG", outcome="WIN", pnl=50.0, confidence=72.0,
        )

    def test_skipped_when_inactive(self):
        ctx = _fake_ctx(learning_mode_active_fn=Mock(return_value=False))
        on_close_learning_mode(_make_terminal_event(), ctx)
        ctx.learning_mode_record_fn.assert_not_called()


# ---------------------------------------------------------------------------
# T3-j cooldown_tracking
# ---------------------------------------------------------------------------
class TestCooldownTracking:
    def test_sets_cooldown_and_last_close(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        before = ctx.symbol_cooldown.get("BTC")
        on_close_cooldown_tracking(ev, ctx)
        assert ctx.symbol_cooldown["BTC"] != before
        assert ctx.last_close_win["BTC"] is True
        assert ctx.last_close_side["BTC"] == "LONG"

    def test_accumulates_daily_pnl_same_day(self):
        ctx = _fake_ctx()
        on_close_cooldown_tracking(_make_terminal_event(total_pnl=10.0), ctx)
        on_close_cooldown_tracking(_make_terminal_event(total_pnl=-5.0), ctx)
        assert ctx.symbol_daily_pnl["BTC"] == pytest.approx(5.0)

    def test_daily_loss_limit_logs_warning_but_does_not_raise(self):
        ctx = _fake_ctx(symbol_daily_loss_limit=-1.0)
        on_close_cooldown_tracking(_make_terminal_event(total_pnl=-50.0), ctx)  # must not raise


# ---------------------------------------------------------------------------
# T3-k telemetry
# ---------------------------------------------------------------------------
class TestTelemetry:
    def test_increments_won_and_records_pnl(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_telemetry(ev, ctx)
        ctx.telemetry_cls.inc.assert_called_once_with("trades_won")
        ctx.telemetry_cls.record.assert_called_once_with("pnls", 50.0)

    def test_increments_lost_on_loss(self):
        ev = _make_terminal_event(total_pnl=-10.0)
        ctx = _fake_ctx()
        on_close_telemetry(ev, ctx)
        ctx.telemetry_cls.inc.assert_called_once_with("trades_lost")


# ---------------------------------------------------------------------------
# T3-l llm_triggers_notify
# ---------------------------------------------------------------------------
class TestLLMTriggersNotify:
    def test_adds_position_closed_trigger(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_llm_triggers_notify(ev, ctx)
        kwargs = ctx.llm_triggers.add.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert "Closed LONG BTC via SL" in kwargs["context"]
        assert "PnL=$+50.00" in kwargs["context"]

    def test_skipped_when_not_configured(self):
        on_close_llm_triggers_notify(_make_terminal_event(), _fake_ctx(llm_triggers=None))


# ---------------------------------------------------------------------------
# T3-m agent_perf
# ---------------------------------------------------------------------------
class TestAgentPerf:
    def test_records_outcome_from_event_fields(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_agent_perf(ev, ctx)
        kwargs = ctx.agent_perf.record_outcome.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["pnl"] == pytest.approx(50.0)
        assert kwargs["entry_time"] == "2026-07-15T14:30:00+00:00"
        assert kwargs["exit_time"] == "2026-07-15T15:00:00+00:00"
        assert kwargs["mfe_pct"] == 0.0
        assert kwargs["mae_pct"] == 0.0
        assert kwargs["side"] == "LONG"

    def test_skipped_when_not_configured(self):
        on_close_agent_perf(_make_terminal_event(), _fake_ctx(agent_perf=None))


# ---------------------------------------------------------------------------
# T3-n cost_optimizer
# ---------------------------------------------------------------------------
class TestCostOptimizer:
    def test_records_outcome_with_pipeline_from_entry_reasons(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_cost_optimizer(ev, ctx)
        ctx.cost_optimizer.record_outcome.assert_called_once_with(pipeline_type="fast", pnl=50.0)

    def test_defaults_pipeline_to_standard(self):
        ev = _make_terminal_event(entry_reasons={})
        ctx = _fake_ctx()
        on_close_cost_optimizer(ev, ctx)
        assert ctx.cost_optimizer.record_outcome.call_args.kwargs["pipeline_type"] == "standard"

    def test_skipped_when_not_configured(self):
        on_close_cost_optimizer(_make_terminal_event(), _fake_ctx(cost_optimizer=None))


# ---------------------------------------------------------------------------
# T3-o alert
# ---------------------------------------------------------------------------
class TestAlert:
    def test_sends_formatted_trade_event(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_alert(ev, ctx)
        fmt_kwargs = ctx.format_trade_event_fn.call_args.kwargs
        assert fmt_kwargs["pnl"] == pytest.approx(52.0)  # per-leg, NOT total
        assert fmt_kwargs["total_pnl"] == pytest.approx(50.0)
        assert fmt_kwargs["equity"] == pytest.approx(5050.0)
        assert fmt_kwargs["daily_pnl"] == 0.0
        assert fmt_kwargs["tp1_hit"] is False
        ctx.alerts.send_trade_event.assert_called_once_with("SL", "BTC", "formatted message")

    def test_falls_back_to_simple_format_on_formatter_exception(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(format_trade_event_fn=Mock(side_effect=RuntimeError("boom")))
        on_close_alert(ev, ctx)
        args = ctx.alerts.send_trade_event.call_args.args
        assert args[0] == "SL"
        assert args[1] == "BTC"
        assert "Total PnL: $+50.00" in args[2]

    def test_skipped_when_not_configured(self):
        on_close_alert(_make_terminal_event(), _fake_ctx(alerts=None))


# ---------------------------------------------------------------------------
# Registration wiring (register_misc)
# ---------------------------------------------------------------------------
class TestRegisterMisc:
    def test_registers_nineteen_subscribers_with_expected_tiers(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_misc(bus, ctx)
        by_name = {s.name: s for s in bus._subs}
        assert len(by_name) == 19

        t2_names = {"continuous_backtest", "shadow_ledger", "adaptive_risk", "adaptive_sizer"}
        for name in t2_names:
            assert by_name[name].tier == Tier.T2_DERIVED_READERS
            assert by_name[name].replay is True

        t3_names = set(by_name) - t2_names
        for name in t3_names:
            assert by_name[name].tier == Tier.T3_FIRE_AND_FORGET
            assert by_name[name].replay is False
            assert by_name[name].required is False

    def test_publish_delivers_full_close_to_all_and_skips_partial(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_misc(bus, ctx)

        full_ev = _make_terminal_event()
        report = bus.publish(full_ev)
        assert set(report.delivered) == {
            "continuous_backtest", "shadow_ledger", "adaptive_risk", "adaptive_sizer",
            "llm_triggers_outcome", "quant_brain_chase", "regime_strategy_weighter",
            "growth", "discovery_corpus", "risk_telemetry", "survival", "ab_testing",
            "learning_mode", "cooldown_tracking", "telemetry", "llm_triggers_notify",
            "agent_perf", "cost_optimizer", "alert",
        }
        assert report.failed == []

        ctx2 = _fake_ctx()
        bus2 = CloseBus(applied_store=InMemoryAppliedStore())
        register_misc(bus2, ctx2)
        partial_ev = _make_terminal_event(position_id="pos-partial", leg_kind=LegKind.PARTIAL)
        report2 = bus2.publish(partial_ev)
        assert report2.delivered == []
        assert set(report2.skipped) == set(s.name for s in bus2._subs)
