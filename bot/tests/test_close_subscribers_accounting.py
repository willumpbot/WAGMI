"""Tests for the ACCOUNTING-TIER close_bus subscribers (Phase 0.4-B, part 2).

CORRECTNESS-CRITICAL scope: equity, circuit-breaker, log_trade (T0) and
ledger, trades_csv, trade_logger (T1). All collaborators are mocked --
these tests MUST NOT touch any real data file under bot/data/.
"""
from __future__ import annotations

import ast
import os
from dataclasses import replace
from unittest.mock import Mock, call

import pytest

from core.close_pipeline.close_bus import CloseBus, InMemoryAppliedStore, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_accounting import (
    on_close_circuit_breaker,
    on_close_equity,
    on_close_ledger,
    on_close_log_trade,
    on_close_trade_logger,
    on_close_trades_csv,
    register_accounting,
)
from execution.risk import CircuitBreaker

SUBSCRIBERS_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "close_pipeline", "close_subscribers_accounting.py",
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _make_terminal_event(**overrides) -> TradeClosed:
    """A single-leg TERMINAL TradeClosed (no prior TP1 leg) -- for this
    shape, ev.total_pnl (pos.realized_pnl, nothing realized before this
    event) and ev.pnl - ev.fee (no funding) are numerically equal by
    construction, which is what lets the equity test assert against
    ev.total_pnl directly (see test_equity_booked_by_total_pnl_once).
    """
    defaults = dict(
        position_id="pos-abc123",
        leg_kind=LegKind.TERMINAL,
        close_type="SL",
        symbol="BTC",
        side="LONG",
        price=50100.0,
        qty=0.1,
        pnl=52.0,        # gross leg pnl
        fee=2.0,          # this leg's fee
        leverage=5.0,
        strategy="ensemble",
        total_pnl=50.0,   # == pnl - fee (no prior TP1, no funding)
        fees_total=2.0,
        funding_costs=0.0,
        equity_after=5050.0,
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
            "snapshot_entry": "50000.0",
        },
        trade_profile={"volatility_band": "normal"},
        state_path="IDLE->OPEN->TRAILING->CLOSED",
        outcome="WIN",
        hold_time_s=1800.0,
        entry_type="TREND",
        primary_driver="regime_trend",
        regime="trend",
        mfe_pct=1.2,
        mae_pct=-0.3,
    )
    defaults.update(overrides)
    return TradeClosed(**defaults)


def _fake_ctx(**overrides) -> CloseCtx:
    risk_mgr = Mock()
    risk_mgr.equity = 5000.0
    risk_mgr.circuit_breaker = Mock(consecutive_losses=0, tripped=False)
    ctx = CloseCtx(
        risk_mgr=risk_mgr,
        trade_ledger=Mock(),
        trade_logger=Mock(),
        kelly_engine=None,
        source="paper",
        log_trade_fn=Mock(),
        record_trade_outcome_fn=Mock(),
        log_closed_trade_fn=Mock(),
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# Grep/AST guard: ZERO occurrences of the live-refetch anti-patterns.
# ---------------------------------------------------------------------------
class TestGrepGuard:
    """Mechanically enforces spec04.md's R5/R7/R10 invariant: every value an
    accounting subscriber uses comes off the frozen ``TradeClosed`` event or
    the injected ``CloseCtx`` -- never a live ``pos_mgr.positions`` re-read,
    a ``risk_mgr.equity`` read-for-derivation, or ``event.pnl`` used as if
    it were the position's total.

    Coverage: (1) simple substring checks for the two unambiguous
    live-refetch patterns (positions.get(/.positions[) and the live-equity-
    read pattern (risk_mgr.equity); (2) an AST walk asserting that a bare
    ``.pnl`` attribute access (as opposed to ``.total_pnl``, a different
    attribute name and therefore never confused by this check) appears ONLY
    inside the three subscribers that legitimately use the PER-LEG pnl
    (on_close_equity, on_close_log_trade, on_close_trade_logger -- see the
    module's "WHY PER-LEG ev.pnl" docstring) and nowhere else in the file
    (in particular, never in on_close_ledger or on_close_trades_csv, which
    must use ev.total_pnl exclusively).
    """

    @pytest.fixture(scope="class")
    def source_text(self) -> str:
        with open(SUBSCRIBERS_MODULE_PATH, "r", encoding="utf-8") as f:
            return f.read()

    @pytest.fixture(scope="class")
    def tree(self, source_text: str) -> ast.Module:
        return ast.parse(source_text)

    def test_no_live_positions_refetch(self, tree: ast.Module):
        # AST-based (not a raw substring scan) so this test itself is not
        # tripped by mentioning the forbidden pattern in a docstring/comment
        # while explaining WHY it's forbidden.
        violations = []
        for node in ast.walk(tree):
            # `<something>.positions.get(...)`
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "positions"
            ):
                violations.append(("positions.get(", node.lineno))
            # `<something>.positions[...]`
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "positions"
            ):
                violations.append((".positions[", node.lineno))
        assert violations == [], f"live positions refetch found: {violations}"

    def test_no_live_equity_read(self, tree: ast.Module):
        # Any `<something>.risk_mgr.equity` (or `.equity` off a name literally
        # called risk_mgr) attribute READ would be a live read-for-derivation;
        # the only sanctioned equity interaction is calling
        # ctx.risk_mgr.update_equity(...) to MUTATE it. AST-based so this
        # test isn't tripped by the docstrings that explain the rule.
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "equity":
                inner = node.value
                inner_name = getattr(inner, "attr", None) or getattr(inner, "id", None)
                if inner_name == "risk_mgr":
                    violations.append(("risk_mgr.equity", node.lineno))
        assert violations == [], f"live risk_mgr.equity read found: {violations}"

    def test_pnl_attribute_confined_to_per_leg_subscribers(self, tree: ast.Module):
        allowed_functions = {
            "on_close_equity",       # T0-a: per-leg booking (see module docstring)
            "on_close_log_trade",    # T0-c: mirrors event.pnl in the sqlite log
            "on_close_trade_logger", # T1-c: TradeLog.pnl is per-leg, unconditional tier
        }

        violations = []

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.func_stack = []

            def visit_FunctionDef(self, node):
                self.func_stack.append(node.name)
                self.generic_visit(node)
                self.func_stack.pop()

            def visit_Attribute(self, node):
                if node.attr == "pnl":  # exact match -- "total_pnl" never matches
                    current_fn = self.func_stack[-1] if self.func_stack else "<module>"
                    if current_fn not in allowed_functions:
                        violations.append((current_fn, node.lineno))
                self.generic_visit(node)

        Visitor().visit(tree)
        assert violations == [], (
            f"bare `.pnl` attribute access found outside the allowed per-leg "
            f"subscribers: {violations} -- accounting/ledger-tier code must "
            f"use `.total_pnl` exclusively."
        )

    def test_ledger_and_trades_csv_use_total_pnl(self, source_text: str):
        # Cheap corroborating check: the two T1 CSV/ledger writers must each
        # reference `ev.total_pnl` at least once (they are the subscribers
        # that must NEVER use per-leg `.pnl`).
        import inspect
        from core.close_pipeline import close_subscribers_accounting as mod

        ledger_src = inspect.getsource(mod.on_close_ledger)
        trades_csv_src = inspect.getsource(mod.on_close_trades_csv)
        assert "total_pnl" in ledger_src
        assert "total_pnl" in trades_csv_src


# ---------------------------------------------------------------------------
# T0-a equity
# ---------------------------------------------------------------------------
class TestEquity:
    def test_equity_booked_by_total_pnl_once(self):
        """For a single-leg TERMINAL close (no prior TP1), ev.total_pnl ==
        ev.pnl - ev.fee (no funding) by construction of the fixture -- so
        asserting the booked amount equals ev.total_pnl AND asserting
        update_equity was called exactly once both hold here. See
        module docstring in close_subscribers_accounting.py for why the
        REAL formula is per-leg (ev.pnl - ev.fee [- funding]), not a literal
        `ev.total_pnl` read -- for a multi-leg position these diverge and
        booking total_pnl on every leg would double-count (see
        TestEquity.test_partial_plus_terminal_never_double_counts below).
        """
        ev = _make_terminal_event(pnl=52.0, fee=2.0, total_pnl=50.0)
        ctx = _fake_ctx()

        on_close_equity(ev, ctx)

        ctx.risk_mgr.update_equity.assert_called_once()
        (booked_amount,), _ = ctx.risk_mgr.update_equity.call_args
        assert booked_amount == pytest.approx(50.0)
        assert booked_amount == pytest.approx(ev.total_pnl)

    def test_equity_deduct_funding_env_gate(self, monkeypatch):
        monkeypatch.setenv("EQUITY_DEDUCT_FUNDING", "true")
        ev = _make_terminal_event(pnl=52.0, fee=2.0, funding_costs=3.0, total_pnl=47.0)
        ctx = _fake_ctx()

        on_close_equity(ev, ctx)

        (booked_amount,), _ = ctx.risk_mgr.update_equity.call_args
        assert booked_amount == pytest.approx(47.0)  # 52 - 2 - 3

    def test_equity_funding_off_by_default(self, monkeypatch):
        monkeypatch.delenv("EQUITY_DEDUCT_FUNDING", raising=False)
        ev = _make_terminal_event(pnl=52.0, fee=2.0, funding_costs=3.0, total_pnl=47.0)
        ctx = _fake_ctx()

        on_close_equity(ev, ctx)

        (booked_amount,), _ = ctx.risk_mgr.update_equity.call_args
        assert booked_amount == pytest.approx(50.0)  # funding NOT deducted by default

    def test_partial_plus_terminal_never_double_counts(self):
        """Two-leg position: a TP1 partial (total_pnl == this leg's own
        realized amount, nothing prior) followed by a terminal close whose
        total_pnl is CUMULATIVE (includes TP1's contribution). Booking
        ev.pnl-based per-leg deltas (the real formula) sums to the correct
        grand total; booking ev.total_pnl on both events would double the
        TP1 leg's contribution. This corroborates why on_close_equity must
        NOT use ev.total_pnl.
        """
        ctx = _fake_ctx()
        tp1 = _make_terminal_event(
            position_id="pos-two-leg", leg_kind=LegKind.PARTIAL, close_type="TP1",
            pnl=20.0, fee=1.0, total_pnl=19.0,
        )
        terminal = _make_terminal_event(
            position_id="pos-two-leg", leg_kind=LegKind.TERMINAL, close_type="SL",
            pnl=10.0, fee=1.0, total_pnl=28.0,  # 19 (TP1) + 9 (this leg net)
        )

        on_close_equity(tp1, ctx)
        on_close_equity(terminal, ctx)

        booked = [c.args[0] for c in ctx.risk_mgr.update_equity.call_args_list]
        assert booked == [pytest.approx(19.0), pytest.approx(9.0)]
        assert sum(booked) == pytest.approx(28.0)  # matches terminal.total_pnl exactly
        # The WRONG (double-counting) approach would have summed to 19+28=47.


# ---------------------------------------------------------------------------
# T0-b circuit breaker
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    def test_cb_sees_correct_win_then_loss(self):
        """Uses a REAL CircuitBreaker (not a mock) wired through a minimal
        fake RiskManager whose update_equity mirrors execution/risk.py's
        real fused equity+CB update -- exercises the actual win/loss
        classification logic, not just a call-count assertion.
        """
        cb = CircuitBreaker(max_consecutive_losses=5)

        class FakeRiskManager:
            def __init__(self):
                self.equity = 5000.0
                self.circuit_breaker = cb

            def update_equity(self, pnl, sim_time=None):
                self.equity += pnl
                self.circuit_breaker.record_trade(pnl, self.equity, sim_time=sim_time)

        risk_mgr = FakeRiskManager()
        ctx = _fake_ctx(risk_mgr=risk_mgr)

        win_ev = _make_terminal_event(position_id="p1", pnl=52.0, fee=2.0, total_pnl=50.0)
        on_close_equity(win_ev, ctx)
        assert cb.consecutive_losses == 0

        loss_ev = _make_terminal_event(position_id="p2", pnl=-30.0, fee=1.0, total_pnl=-31.0)
        on_close_equity(loss_ev, ctx)
        assert cb.consecutive_losses == 1

        loss_ev_2 = _make_terminal_event(position_id="p3", pnl=-10.0, fee=1.0, total_pnl=-11.0)
        on_close_equity(loss_ev_2, ctx)
        assert cb.consecutive_losses == 2

        win_ev_2 = _make_terminal_event(position_id="p4", pnl=5.0, fee=0.5, total_pnl=4.5)
        on_close_equity(win_ev_2, ctx)
        assert cb.consecutive_losses == 0

    def test_circuit_breaker_subscriber_does_not_double_count(self):
        """on_close_circuit_breaker must be a pure observer: calling it after
        on_close_equity has already applied the CB update must NOT change
        consecutive_losses again."""
        cb = CircuitBreaker(max_consecutive_losses=5)

        class FakeRiskManager:
            def __init__(self):
                self.equity = 5000.0
                self.circuit_breaker = cb

            def update_equity(self, pnl, sim_time=None):
                self.equity += pnl
                self.circuit_breaker.record_trade(pnl, self.equity, sim_time=sim_time)

        risk_mgr = FakeRiskManager()
        ctx = _fake_ctx(risk_mgr=risk_mgr)

        loss_ev = _make_terminal_event(pnl=-30.0, fee=1.0, total_pnl=-31.0)
        on_close_equity(loss_ev, ctx)
        assert cb.consecutive_losses == 1

        # T0-b runs next per tier order -- must be a no-op mutation-wise.
        # (booked delta was pnl - fee = -30 - 1 = -31, per the per-leg formula)
        on_close_circuit_breaker(loss_ev, ctx)
        assert cb.consecutive_losses == 1
        assert cb.daily_pnl == pytest.approx(-31.0)  # unchanged by the T0-b call


# ---------------------------------------------------------------------------
# T0-c log_trade
# ---------------------------------------------------------------------------
class TestLogTrade:
    def test_log_trade_uses_per_leg_pnl_and_fields(self):
        ev = _make_terminal_event(pnl=52.0, fee=2.0, total_pnl=50.0)
        ctx = _fake_ctx()

        on_close_log_trade(ev, ctx)

        ctx.log_trade_fn.assert_called_once()
        kwargs = ctx.log_trade_fn.call_args.kwargs
        assert kwargs["symbol"] == "BTC"
        assert kwargs["action"] == "SL"
        assert kwargs["side"] == "LONG"
        assert kwargs["price"] == 50100.0
        assert kwargs["qty"] == 0.1
        assert kwargs["pnl"] == pytest.approx(52.0)   # per-leg, NOT total_pnl
        assert kwargs["fee"] == pytest.approx(2.0)
        assert kwargs["leverage"] == 5.0
        assert kwargs["strategy"] == "ensemble"
        assert isinstance(kwargs["metadata"], dict)
        assert kwargs["metadata"]["total_pnl"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# T1-a ledger
# ---------------------------------------------------------------------------
class TestLedger:
    def test_record_trade_row_uses_total_pnl_and_position_id(self):
        ev = _make_terminal_event(
            position_id="pos-ledger-1", pnl=52.0, fee=2.0, total_pnl=50.0,
            equity_after=5050.0,
        )
        ctx = _fake_ctx()

        on_close_ledger(ev, ctx)

        ctx.trade_ledger.record_trade.assert_called_once()
        row, kwargs = ctx.trade_ledger.record_trade.call_args
        row = row[0]
        assert row["net_pnl"] == "50.0" or row["net_pnl"] == str(round(50.0, 2))
        assert row["position_id"] == "pos-ledger-1"
        assert row["win"] == "1"
        assert row["running_equity"] == str(round(5050.0, 2))
        assert kwargs["source"] == "paper"
        assert kwargs["position_id"] == "pos-ledger-1"

    def test_ledger_skipped_when_no_trade_ledger_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(trade_ledger=None)
        on_close_ledger(ev, ctx)  # must not raise

    def test_ledger_loss_marks_win_zero(self):
        ev = _make_terminal_event(pnl=-30.0, fee=1.0, total_pnl=-31.0)
        ctx = _fake_ctx()
        on_close_ledger(ev, ctx)
        row = ctx.trade_ledger.record_trade.call_args[0][0]
        assert row["win"] == "0"
        assert row["net_pnl"] == "-31.0"

    def test_ledger_compound_mult_field_gap_defaults_blank(self):
        ev = _make_terminal_event(compound_mult=None)
        ctx = _fake_ctx()
        on_close_ledger(ev, ctx)
        row = ctx.trade_ledger.record_trade.call_args[0][0]
        assert row["compound_size_multiplier"] == ""

    def test_ledger_kelly_weight_uses_optional_collaborator(self):
        ev = _make_terminal_event(strategy="regime_trend")
        kelly = Mock()
        kelly.compute_kelly_weight.return_value = 0.42
        ctx = _fake_ctx(kelly_engine=kelly)
        on_close_ledger(ev, ctx)
        row = ctx.trade_ledger.record_trade.call_args[0][0]
        assert row["kelly_weight_applied"] == "0.42"
        kelly.compute_kelly_weight.assert_called_once_with("regime_trend")


# ---------------------------------------------------------------------------
# T1-b trades_csv (record_trade_outcome + log_closed_trade)
# ---------------------------------------------------------------------------
class TestTradesCsv:
    def test_both_writers_called_with_total_pnl(self):
        ev = _make_terminal_event(pnl=52.0, fee=2.0, total_pnl=50.0, fees_total=2.0)
        ctx = _fake_ctx()

        on_close_trades_csv(ev, ctx)

        ctx.record_trade_outcome_fn.assert_called_once()
        outcome_kwargs = ctx.record_trade_outcome_fn.call_args.kwargs
        assert outcome_kwargs["pnl"] == pytest.approx(50.0)  # total_pnl, not per-leg

        ctx.log_closed_trade_fn.assert_called_once()
        trades_kwargs = ctx.log_closed_trade_fn.call_args.kwargs
        assert trades_kwargs["pnl"] == pytest.approx(50.0)
        assert trades_kwargs["fees"] == pytest.approx(2.0)

    def test_pollution_source_passed_to_record_trade_outcome(self):
        """0.2 gated record_trade_outcome with core.provenance.gate_live_write
        via its `source=` kwarg -- assert ctx.source flows through so a
        caller can force PAPER/LIVE and avoid the pytest-autodetect-as-TEST
        block once this is wired to the real function."""
        ev = _make_terminal_event()
        ctx = _fake_ctx(source="live")

        on_close_trades_csv(ev, ctx)

        outcome_kwargs = ctx.record_trade_outcome_fn.call_args.kwargs
        assert outcome_kwargs["source"] == "live"

    def test_log_closed_trade_has_no_source_param(self):
        """log_closed_trade (data/trade_log.py) has no pollution gate/source
        param today -- assert we don't invent one that would break the real
        function's signature."""
        ev = _make_terminal_event()
        ctx = _fake_ctx()
        on_close_trades_csv(ev, ctx)
        trades_kwargs = ctx.log_closed_trade_fn.call_args.kwargs
        assert "source" not in trades_kwargs

    def test_tp1_hit_derived_from_state_path(self):
        ev = _make_terminal_event(
            state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED", close_type="SL",
        )
        ctx = _fake_ctx()
        on_close_trades_csv(ev, ctx)
        outcome_kwargs = ctx.record_trade_outcome_fn.call_args.kwargs
        assert outcome_kwargs["tp1_hit"] is True
        assert outcome_kwargs["sl_after_tp1"] is True

    def test_tp1_hit_false_when_absent(self):
        ev = _make_terminal_event(state_path="IDLE->OPEN->CLOSED", close_type="SL")
        ctx = _fake_ctx()
        on_close_trades_csv(ev, ctx)
        outcome_kwargs = ctx.record_trade_outcome_fn.call_args.kwargs
        assert outcome_kwargs["tp1_hit"] is False
        assert outcome_kwargs["sl_after_tp1"] is False


# ---------------------------------------------------------------------------
# T1-c trade_logger
# ---------------------------------------------------------------------------
class TestTradeLogger:
    def test_trade_logger_receives_shim_with_correct_values(self):
        ev = _make_terminal_event(pnl=52.0, fee=2.0, hold_time_s=1800.0)
        ctx = _fake_ctx()

        on_close_trade_logger(ev, ctx)

        ctx.trade_logger.log_trade_event.assert_called_once()
        (shim,), kwargs = ctx.trade_logger.log_trade_event.call_args
        assert shim.symbol == "BTC"
        assert shim.action == "SL"
        assert shim.side == "LONG"
        assert shim.pnl == pytest.approx(52.0)  # per-leg, matches TradeLog.pnl semantics
        assert shim.fee == pytest.approx(2.0)
        assert shim.leverage == 5.0
        assert kwargs["hold_time_s"] == 1800

    def test_trade_logger_skipped_when_none_configured(self):
        ev = _make_terminal_event()
        ctx = _fake_ctx(trade_logger=None)
        on_close_trade_logger(ev, ctx)  # must not raise


# ---------------------------------------------------------------------------
# Exactly-once via the bus
# ---------------------------------------------------------------------------
class TestExactlyOnceViaBus:
    def test_duplicate_publish_applies_t0_and_t1_exactly_once(self):
        """Publishing the SAME TradeClosed (same position_id, same event_id)
        twice through a CloseBus with all six accounting subscribers
        registered: CloseBus.publish's applied-store check is now
        GENERALIZED to every ``dedupe=True`` subscriber (the default --
        see close_bus.py's ``subscribe()``), keyed by
        ``(subscriber_name, position_id)``, not scoped to
        `sub.tier == Tier.T0_CORE_ACCOUNTING` as it used to be.

        T0 (equity/circuit_breaker/log_trade) AND T1
        (ledger/trades_csv/trade_logger) -- none of these subscribers opt
        out with ``dedupe=False`` (see register_accounting) -- must each
        apply EXACTLY ONCE on a duplicate publish. This closes the gap the
        old god-block's ``CLOSE_DEDUP_GUARD`` never fully covered (ledger
        could double-book even though equity/CB were guarded).
        """
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_accounting(bus, ctx)

        ev = _make_terminal_event(position_id="dup-pos", pnl=52.0, fee=2.0, total_pnl=50.0)

        bus.publish(ev)
        bus.publish(ev)

        assert ctx.risk_mgr.update_equity.call_count == 1
        assert ctx.log_trade_fn.call_count == 1

        # T1: now deduped by CloseBus's generalized applied-store -- the
        # second publish's ledger/trades_csv/trade_logger subscribers are
        # skipped, not re-run.
        assert ctx.trade_ledger.record_trade.call_count == 1
        assert ctx.record_trade_outcome_fn.call_count == 1
        assert ctx.log_closed_trade_fn.call_count == 1
        assert ctx.trade_logger.log_trade_event.call_count == 1

    def test_partial_leg_skips_full_only_subscribers(self):
        """A PARTIAL leg (TP1) must reach T0 (unconditional) and
        trade_logger (unconditional), but NOT ledger/trades_csv (FULL-only,
        per the `kind=(CloseKind.FULL,)` subscribe filter mirroring the
        god-block's `_FULL_CLOSE` gate)."""
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_accounting(bus, ctx)

        partial_ev = _make_terminal_event(
            position_id="partial-pos", leg_kind=LegKind.PARTIAL, close_type="TP1",
            pnl=20.0, fee=1.0, total_pnl=19.0,
        )

        report = bus.publish(partial_ev)

        assert ctx.risk_mgr.update_equity.call_count == 1
        assert ctx.log_trade_fn.call_count == 1
        assert ctx.trade_logger.log_trade_event.call_count == 1
        assert ctx.trade_ledger.record_trade.call_count == 0
        assert ctx.record_trade_outcome_fn.call_count == 0
        assert ctx.log_closed_trade_fn.call_count == 0
        assert "ledger" in report.skipped
        assert "trades_csv" in report.skipped

    def test_t0_runs_before_t1_in_registration_order(self):
        bus = CloseBus(applied_store=InMemoryAppliedStore())
        ctx = _fake_ctx()
        register_accounting(bus, ctx)
        names = [s.name for s in bus._ordered_subs()]
        assert names == [
            "equity", "circuit_breaker", "log_trade",
            "ledger", "trades_csv", "trade_logger",
        ]
