"""Tests for Phase 0.4-B3 execution/close_with_execution.py -- the ONE
sanctioned close entry point.

Everything here is mocked: no real exchange, no real data files, no real
PositionManager/OrderExecutor instances are constructed. Every test builds
lightweight fakes/mocks so these tests are fast, deterministic, and never
touch anything under bot/data/.

Focus: the invariants spec04.md section (2) mandates for the helper --
order-first, abort-and-leave-OPEN on a failed fill (the MFE / L1-continue
bug-class regression test), pre-close qty capture (the MFE qty=0 bug), the
no_exchange/GHOST-CLOSE HOLD_LIMIT path, partial-close routing, and a
best-effort thread-safety smoke test.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from execution.close_with_execution import close_with_execution, validate_close_type
from execution.order_executor import OrderResult
from execution.position_manager import Position, TradeEvent


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
def _make_position(**overrides) -> Position:
    defaults = dict(
        symbol="BTC",
        side="LONG",
        entry=100.0,
        qty=5.0,
        sl=95.0,
        tp1=105.0,
        tp2=110.0,
        strategy="regime_trend",
        confidence=72.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


class FakePosMgr:
    """Stand-in for PositionManager. force_close/partial_close mirror the
    REAL PositionManager behavior that matters for these tests: they read
    pos.qty as the "close qty" and then zero (or reduce) pos.qty on the
    SAME Position object -- exactly the in-place mutation that made the old
    MFE call site's post-force_close qty read return 0."""

    def __init__(self, position: Optional[Position]):
        self.positions: Dict[str, Position] = {}
        if position is not None:
            self.positions[position.symbol] = position
        self.force_close_calls: List[tuple] = []
        self.partial_close_calls: List[tuple] = []
        # Toggle: if True, force_close/partial_close return None (simulates
        # a booking race -- position already closed by something else).
        self.booking_returns_none = False

    def force_close(self, symbol: str, price: float, reason: str) -> Optional[TradeEvent]:
        self.force_close_calls.append((symbol, price, reason))
        if self.booking_returns_none:
            return None
        pos = self.positions[symbol]
        captured_qty = pos.qty
        fee = 0.5
        pnl = 10.0
        pos.realized_pnl += pnl - fee
        pos.qty = 0.0  # mirror position_manager.py:1905 (_close_position)
        event = TradeEvent(
            symbol=symbol,
            action=reason,
            side=pos.side,
            price=price,
            qty=captured_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            position_id=pos.position_id,
            is_position_close=True,
            metadata={
                "total_pnl": pos.realized_pnl,
                "total_fees": pos.fees_paid,
                "funding_costs": pos.funding_costs,
            },
        )
        return event

    def partial_close(
        self, symbol: str, pct: float, price: float, action: str, qty: Optional[float] = None,
    ) -> Optional[TradeEvent]:
        self.partial_close_calls.append((symbol, pct, price, action, qty))
        if self.booking_returns_none:
            return None
        pos = self.positions[symbol]
        close_qty = qty if qty is not None else pos.qty * pct
        fee = 0.1
        pnl = 3.0
        pos.realized_pnl += pnl - fee
        pos.qty = pos.qty - close_qty
        event = TradeEvent(
            symbol=symbol,
            action=action,
            side=pos.side,
            price=price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            position_id=pos.position_id,
            is_position_close=False,
            metadata={
                "total_pnl": pos.realized_pnl,
                "remaining_qty": pos.qty,
            },
        )
        return event


def _make_order_executor(filled: bool, error: str = "") -> MagicMock:
    oe = MagicMock()
    if filled:
        oe.close_position.return_value = OrderResult(
            success=True, status="filled", fill_price=99.0, fill_qty=5.0,
        )
    else:
        oe.close_position.return_value = OrderResult(
            success=False, status="rejected", error=error or "insufficient margin",
        )
    return oe


# ---------------------------------------------------------------------------
# validate_close_type
# ---------------------------------------------------------------------------
class TestValidateCloseType:
    def test_unknown_close_type_raises(self):
        with pytest.raises(ValueError, match="unknown close_type"):
            validate_close_type("NOT_A_REAL_CLOSE_TYPE")

    def test_known_close_type_does_not_raise(self):
        validate_close_type("MFE_TAKE_PROFIT")
        validate_close_type("LIQUIDATION_AVOID")
        validate_close_type("TELEGRAM_CLOSE")

    def test_unknown_close_type_blocks_before_any_side_effect(self):
        """validate_close_type runs FIRST inside close_with_execution --
        an unknown close_type must raise before touching pos_mgr/order_executor
        at all."""
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)
        with pytest.raises(ValueError):
            close_with_execution(
                "BTC", 99.0, "TOTALLY_BOGUS_TYPE",
                pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
            )
        order_executor.close_position.assert_not_called()
        assert pos_mgr.force_close_calls == []


# ---------------------------------------------------------------------------
# Order-first happy path
# ---------------------------------------------------------------------------
class TestOrderFirstHappyPath:
    def test_filled_order_books_and_publishes(self):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)
        bus = CloseBus()
        received: List[TradeClosed] = []
        bus.subscribe("spy", received.append, tier=Tier.T3_FIRE_AND_FORGET)

        result = close_with_execution(
            "BTC", 99.0, "MFE_TAKE_PROFIT",
            pos_mgr=pos_mgr, order_executor=order_executor, bus=bus,
        )

        # Order submitted BEFORE booking, order-first pattern.
        order_executor.close_position.assert_called_once()
        call_kwargs = order_executor.close_position.call_args.kwargs
        assert call_kwargs["symbol"] == "BTC"
        assert call_kwargs["side"] == "SELL"  # closing a LONG
        assert call_kwargs["qty"] == 5.0
        assert call_kwargs["reason"] == "MFE_TAKE_PROFIT"

        assert len(pos_mgr.force_close_calls) == 1
        assert result is not None
        assert isinstance(result, TradeClosed)
        assert result.exchange_submitted is True
        assert result.leg_kind == LegKind.TERMINAL
        assert result.close_type == "MFE_TAKE_PROFIT"

        # Published exactly once.
        assert len(received) == 1
        assert received[0].event_id == result.event_id

    def test_returns_none_when_no_open_position(self):
        pos_mgr = FakePosMgr(None)
        order_executor = _make_order_executor(filled=True)
        result = close_with_execution(
            "BTC", 99.0, "MFE_TAKE_PROFIT",
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
        )
        assert result is None
        order_executor.close_position.assert_not_called()
        assert pos_mgr.force_close_calls == []


# ---------------------------------------------------------------------------
# ORDER-FAIL abort -- the key regression test (MFE / L1-continue bug class)
# ---------------------------------------------------------------------------
class TestOrderFailAbort:
    def test_unfilled_order_aborts_leaves_position_open(self, caplog):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=False, error="insufficient margin")
        bus = CloseBus()
        received: List[TradeClosed] = []
        bus.subscribe("spy", received.append, tier=Tier.T3_FIRE_AND_FORGET)

        with caplog.at_level(logging.CRITICAL):
            result = close_with_execution(
                "BTC", 99.0, "MFE_TAKE_PROFIT",
                pos_mgr=pos_mgr, order_executor=order_executor, bus=bus,
            )

        assert result is None
        # force_close must NEVER be called -- the core fix.
        assert pos_mgr.force_close_calls == []
        # Nothing published.
        assert received == []
        # Position left exactly as it was: qty untouched, not CLOSED.
        assert pos.qty == 5.0
        assert pos.state != "CLOSED"
        # CRITICAL logged.
        assert any(
            rec.levelno == logging.CRITICAL and "CLOSE ORDER FAILED" in rec.message
            for rec in caplog.records
        )

    def test_unfilled_partial_order_also_aborts(self, caplog):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=False)
        with caplog.at_level(logging.CRITICAL):
            result = close_with_execution(
                "BTC", 99.0, "LLM_EXIT_PARTIAL",
                qty=2.0, partial=True, partial_pct=0.4,
                pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
            )
        assert result is None
        assert pos_mgr.partial_close_calls == []
        assert pos.qty == 5.0

    def test_pm_booking_race_returns_none_and_does_not_publish(self, caplog):
        """Exchange order fills, but PM booking comes back None (a race --
        position already closed by something else). Must not publish."""
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        pos_mgr.booking_returns_none = True
        order_executor = _make_order_executor(filled=True)
        bus = CloseBus()
        received: List[TradeClosed] = []
        bus.subscribe("spy", received.append, tier=Tier.T3_FIRE_AND_FORGET)

        with caplog.at_level(logging.CRITICAL):
            result = close_with_execution(
                "BTC", 99.0, "MFE_TAKE_PROFIT",
                pos_mgr=pos_mgr, order_executor=order_executor, bus=bus,
            )
        assert result is None
        assert received == []
        assert any(rec.levelno == logging.CRITICAL for rec in caplog.records)


# ---------------------------------------------------------------------------
# no_exchange=True (HOLD_LIMIT ghost-close)
# ---------------------------------------------------------------------------
class TestNoExchangeGhostClose:
    def test_no_exchange_books_without_order_and_warns(self, caplog):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)  # should never be consulted

        with caplog.at_level(logging.WARNING):
            result = close_with_execution(
                "BTC", 99.0, "HOLD_LIMIT",
                no_exchange=True,
                pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
            )

        order_executor.close_position.assert_not_called()
        assert len(pos_mgr.force_close_calls) == 1
        assert result is not None
        assert result.exchange_submitted is False
        assert any(
            rec.levelno == logging.WARNING and "GHOST-CLOSE" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# partial=True routing
# ---------------------------------------------------------------------------
class TestPartialClose:
    def test_partial_routes_to_partial_close_never_full(self):
        pos = _make_position(qty=10.0)
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)

        result = close_with_execution(
            "BTC", 99.0, "LLM_EXIT_PARTIAL",
            qty=4.0, partial=True, partial_pct=0.4,
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
        )

        assert pos_mgr.force_close_calls == []
        assert len(pos_mgr.partial_close_calls) == 1
        symbol, pct, price, action, qty = pos_mgr.partial_close_calls[0]
        assert qty == 4.0
        assert action == "LLM_EXIT_PARTIAL"

        assert result is not None
        assert result.leg_kind == LegKind.PARTIAL
        # Position must remain open (qty reduced, not zeroed).
        assert pos.qty == 6.0

    def test_partial_close_qty_captured_pre_close(self):
        """The exchange order for the partial leg must use the caller-
        supplied leg qty, not something read after partial_close() already
        mutated the position's remaining qty."""
        pos = _make_position(qty=10.0)
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)

        close_with_execution(
            "BTC", 99.0, "EXIT_ENGINE_PARTIAL",
            qty=4.0, partial=True, partial_pct=0.4,
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
        )

        call_kwargs = order_executor.close_position.call_args.kwargs
        assert call_kwargs["qty"] == 4.0


# ---------------------------------------------------------------------------
# qty captured pre-close (the MFE qty=0 bug, full-close variant)
# ---------------------------------------------------------------------------
class TestQtyCapturedPreClose:
    def test_qty_not_zero_despite_force_close_zeroing_position(self):
        """FakePosMgr.force_close mirrors the real PositionManager's
        in-place pos.qty = 0 mutation (position_manager.py:1905). The old
        MFE call site read `_mfe_pos.qty` for the exchange order AFTER
        calling force_close(), so it always submitted qty=0. This helper
        must submit the PRE-close qty instead."""
        pos = _make_position(qty=7.5)
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)

        result = close_with_execution(
            "BTC", 99.0, "MFE_TAKE_PROFIT",
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
        )

        call_kwargs = order_executor.close_position.call_args.kwargs
        assert call_kwargs["qty"] == 7.5
        assert call_kwargs["qty"] != 0

        assert result is not None
        assert result.qty == 7.5
        assert result.qty != 0

        # Confirm the position really was zeroed by the (mocked) PM call,
        # proving the bug WOULD have reproduced if qty had been read late.
        assert pos.qty == 0.0


# ---------------------------------------------------------------------------
# bus=None (backtest contract) -- never called by backtest in practice, but
# the helper must not crash if a caller passes bus=None.
# ---------------------------------------------------------------------------
class TestBusNone:
    def test_bus_none_does_not_crash(self):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)

        result = close_with_execution(
            "BTC", 99.0, "MFE_EXIT_NOW",
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
        )
        assert result is not None
        assert isinstance(result, TradeClosed)


# ---------------------------------------------------------------------------
# Snapshot kwargs pass-through
# ---------------------------------------------------------------------------
class TestSnapshotKwargs:
    def test_field_gap_kwargs_forwarded(self):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)

        result = close_with_execution(
            "BTC", 99.0, "ROTATE_PROFIT",
            pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
            compound_mult=1.05,
            close_volatility=0.021,
            candidate_ref="cand-123",
            equity_after=5123.45,
            session_dd_pct=1.2,
        )
        assert result.compound_mult == 1.05
        assert result.close_volatility == 0.021
        assert result.candidate_ref == "cand-123"
        assert result.equity_after == 5123.45
        assert result.session_dd_pct == 1.2

    def test_unknown_snapshot_kwarg_raises(self):
        pos = _make_position()
        pos_mgr = FakePosMgr(pos)
        order_executor = _make_order_executor(filled=True)
        with pytest.raises(TypeError):
            close_with_execution(
                "BTC", 99.0, "ROTATE_PROFIT",
                pos_mgr=pos_mgr, order_executor=order_executor, bus=None,
                not_a_real_field="oops",
            )


# ---------------------------------------------------------------------------
# Thread-safety smoke (best-effort, per spec04.md)
# ---------------------------------------------------------------------------
class TestThreadSafetySmoke:
    def test_concurrent_closes_different_symbols_no_corruption(self):
        """Simulate the Telegram poll thread and the main tick loop calling
        close_with_execution concurrently for DIFFERENT symbols against a
        shared bus. No exceptions, no cross-symbol data leakage, exactly
        one TradeClosed per symbol delivered to the bus."""
        symbols = [f"SYM{i}" for i in range(8)]
        positions = {s: _make_position(symbol=s, qty=float(i + 1)) for i, s in enumerate(symbols)}
        pos_mgr = FakePosMgr(None)
        pos_mgr.positions = positions

        # Give each symbol its own OrderExecutor mock (order_executor could
        # be shared in real life, but a single MagicMock isn't guaranteed
        # thread-safe for call recording -- use a lock-guarded dispatcher).
        oe_lock = threading.Lock()
        call_log: List[Dict[str, Any]] = []

        class SharedOrderExecutor:
            def close_position(self, **kwargs):
                with oe_lock:
                    call_log.append(kwargs)
                return OrderResult(success=True, status="filled")

        order_executor = SharedOrderExecutor()
        bus = CloseBus()
        received: List[TradeClosed] = []
        recv_lock = threading.Lock()

        def _spy(event: TradeClosed) -> None:
            with recv_lock:
                received.append(event)

        bus.subscribe("spy", _spy, tier=Tier.T3_FIRE_AND_FORGET)

        results: Dict[str, Optional[TradeClosed]] = {}
        results_lock = threading.Lock()
        errors: List[BaseException] = []

        def _worker(sym: str) -> None:
            try:
                r = close_with_execution(
                    sym, 50.0, "TELEGRAM_CLOSE",
                    pos_mgr=pos_mgr, order_executor=order_executor, bus=bus,
                )
                with results_lock:
                    results[sym] = r
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(s,)) for s in symbols]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        assert set(results.keys()) == set(symbols)
        for sym in symbols:
            assert results[sym] is not None
            assert results[sym].symbol == sym
        assert len(received) == len(symbols)
        assert {e.symbol for e in received} == set(symbols)
        # Each symbol's own pre-close qty (i+1) must have reached its own
        # order call -- no cross-thread qty leakage.
        by_symbol_qty = {c["symbol"]: c["qty"] for c in call_log}
        for i, sym in enumerate(symbols):
            assert by_symbol_qty[sym] == float(i + 1)
