"""
Regression tests for the LLM_EXIT_HIGH/CRITICAL silent-drop fix.

BUG (confirmed on the live bot, 2026-07-21): a BTC LONG position closed via
LLM_EXIT_HIGH (PnL -$2.90) but was never booked -- the log showed
"State: OPEN -> CLOSED (LLM_EXIT_HIGH @ ...)" and a [TRADE_CLOSED] event, the
position went to 0 qty -- but there was no ledger row, no equity change, no
CLOSED_BOOKED. Root cause: core/llm_integration.py's _run_exit_agent_checks
called `_pm.force_close(symbol, price, f"LLM_EXIT_{urgency.upper()}")` and
DISCARDED the returned TradeEvent -- it was never injected into
self._pending_exit_events (the queue multi_strategy_main's per-symbol event
loop drains to book equity/ledger/learning), and no exchange order was ever
submitted either.

FIX: route the close through the SAME booked path LLM_EXIT_AGENT already
uses (core/position_wiring.py::_check_llm_exit_suggestions): submit the
exchange close order first, force_close the position-manager state only on
a confirmed fill, stamp metadata["_exchange_submitted"] = True, and append
the TradeEvent onto self._pending_exit_events (under self._pending_exit_lock
when present -- T0-A-race, 2026-07-14) so the per-symbol event loop books it.

INVARIANT under test: LLM_EXIT_HIGH/CRITICAL must NEVER close a position
(force_close) without that close being routed onto _pending_exit_events.
Either it books, or the position stays open -- no unrouted close path.

Everything here is mocked (pos_mgr, order_executor, coordinator, prices) --
no real exchange/data access.
"""

import ast
import os
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_integration import LLMIntegrationMixin

_LLM_INTEGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "llm_integration.py"
)


class _FakeBot(LLMIntegrationMixin):
    """Minimal stand-in for MultiStrategyBot exposing only what
    _run_exit_agent_checks touches via `self.*`."""


def _make_position(side="LONG", qty=1.0, entry=100.0):
    pos = MagicMock()
    pos.state = "OPEN"
    pos.side = side
    pos.entry = entry
    pos.sl = 95.0
    pos.tp1 = 110.0
    pos.tp2 = 120.0
    pos.qty = qty
    pos.leverage = 1.0
    pos.confidence = 80
    pos.open_time = datetime.now(timezone.utc)
    return pos


def _build_bot(with_order_executor=True, with_pending_lock=True, last_price=101.0,
               side="LONG", qty=1.0):
    obj = _FakeBot()
    fake_pos = _make_position(side=side, qty=qty)

    obj.pos_mgr = MagicMock()
    obj.pos_mgr.positions = {"BTC": fake_pos}

    def _force_close(symbol, price, reason):
        ev = MagicMock()
        ev.symbol = symbol
        ev.pnl = -2.90
        ev.metadata = {}
        return ev
    obj.pos_mgr.force_close = MagicMock(side_effect=_force_close)

    if with_order_executor:
        obj.order_executor = MagicMock()
        obj.order_executor.close_position = MagicMock(return_value=MagicMock(filled=True))

    obj._last_prices = {"BTC": last_price}
    obj._tick_regime_cache = {}
    obj._pending_exit_events = []
    if with_pending_lock:
        obj._pending_exit_lock = threading.Lock()
    return obj


def _run_with_verdict(obj, action, urgency, reason="thesis broken"):
    mock_coordinator = MagicMock()
    mock_coordinator.get_exit_intelligence.return_value = {
        "action": action, "urgency": urgency, "reason": reason,
    }
    with patch("llm.autonomy.get_llm_mode", return_value=object()), \
         patch("llm.autonomy.should_call_llm", return_value=True), \
         patch("llm.agents.coordinator.get_coordinator", return_value=mock_coordinator), \
         patch("llm.agents.coordinator.is_multi_agent_enabled", return_value=True):
        obj._run_exit_agent_checks(trace_id="test-trace")


class TestLLMExitHighRoutesToBookedPath(unittest.TestCase):
    """Primary fix assertion: full_close/critical and close/high inject the
    TradeEvent into _pending_exit_events -- the SAME queue LLM_EXIT_AGENT
    uses -- instead of discarding it after an unrouted force_close()."""

    def test_critical_full_close_submits_exchange_order_then_books(self):
        obj = _build_bot(last_price=101.0)
        _run_with_verdict(obj, action="full_close", urgency="critical")

        obj.order_executor.close_position.assert_called_once_with(
            "BTC", "SELL", 1.0, 101.0, reason="LLM_EXIT_CRITICAL"
        )
        obj.pos_mgr.force_close.assert_called_once_with("BTC", 101.0, "LLM_EXIT_CRITICAL")

        self.assertEqual(len(obj._pending_exit_events), 1)
        booked = obj._pending_exit_events[0]
        self.assertEqual(booked.symbol, "BTC")
        self.assertTrue(booked.metadata.get("_exchange_submitted"))

    def test_high_close_submits_exchange_order_then_books(self):
        obj = _build_bot(last_price=250.5)
        _run_with_verdict(obj, action="close", urgency="high")

        obj.order_executor.close_position.assert_called_once_with(
            "BTC", "SELL", 1.0, 250.5, reason="LLM_EXIT_HIGH"
        )
        obj.pos_mgr.force_close.assert_called_once_with("BTC", 250.5, "LLM_EXIT_HIGH")

        self.assertEqual(len(obj._pending_exit_events), 1)
        self.assertTrue(obj._pending_exit_events[0].metadata.get("_exchange_submitted"))

    def test_short_position_closes_with_buy_side(self):
        obj = _build_bot(last_price=95.0, side="SHORT")
        _run_with_verdict(obj, action="full_close", urgency="critical")

        obj.order_executor.close_position.assert_called_once_with(
            "BTC", "BUY", 1.0, 95.0, reason="LLM_EXIT_CRITICAL"
        )
        self.assertEqual(len(obj._pending_exit_events), 1)

    def test_hold_action_does_not_close_or_queue(self):
        obj = _build_bot()
        _run_with_verdict(obj, action="hold", urgency="low")

        obj.order_executor.close_position.assert_not_called()
        obj.pos_mgr.force_close.assert_not_called()
        self.assertEqual(obj._pending_exit_events, [])


class TestAntiSilentDropInvariant(unittest.TestCase):
    """The invariant under test: LLM_EXIT_HIGH/CRITICAL must never close a
    position without routing the close onward. If the exchange order fails
    to fill, or the booked-routing path (order_executor) isn't reachable on
    this object, force_close() must NOT be called and the position must
    remain open -- never a state-only close with the TradeEvent thrown away.
    """

    def test_exchange_order_not_filled_blocks_force_close(self):
        obj = _build_bot()
        obj.order_executor.close_position.return_value = MagicMock(filled=False)
        _run_with_verdict(obj, action="full_close", urgency="critical")

        obj.pos_mgr.force_close.assert_not_called()
        self.assertEqual(obj._pending_exit_events, [])

    def test_missing_order_executor_blocks_close_entirely(self):
        """Safe fallback: if the routing path (order_executor) isn't
        reachable on self, do NOT force_close at all -- leave the position
        open for the mechanical/routed exit path rather than risk a repeat
        of the silent-drop bug."""
        obj = _build_bot(with_order_executor=False)
        _run_with_verdict(obj, action="full_close", urgency="critical")

        obj.pos_mgr.force_close.assert_not_called()
        self.assertEqual(obj._pending_exit_events, [])

    def test_force_close_never_called_without_a_later_queue_append(self):
        """Static guard on the source: the force_close() call inside the
        urgent-exit branch must be immediately followed (same try block) by
        appending the returned event to self._pending_exit_events. This is
        the narrowest possible check for "no unrouted close path" -- it
        would fail if a future edit reintroduced a bare
        `_pm.force_close(...)` call whose return value is discarded.
        """
        with open(_LLM_INTEGRATION_PATH, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=_LLM_INTEGRATION_PATH)

        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_exit_agent_checks":
                method_node = node
                break
        self.assertIsNotNone(method_node, "_run_exit_agent_checks not found")

        # Every `force_close(` call's result must be assigned to a name
        # (not a bare expression statement) -- a bare-statement force_close
        # call is exactly the discarded-return-value shape of the original
        # bug.
        bare_force_close_calls = []
        for node in ast.walk(method_node):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "force_close":
                    bare_force_close_calls.append(call.lineno)

        self.assertEqual(
            bare_force_close_calls, [],
            f"Found force_close() call(s) with discarded return value at "
            f"line(s) {bare_force_close_calls} in _run_exit_agent_checks -- "
            f"this is the exact shape of the silent-drop bug (event never "
            f"routed to _pending_exit_events).",
        )

        # The queue-append call must actually be present in this method.
        found_append = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            for node in ast.walk(method_node)
        )
        self.assertTrue(
            found_append,
            "_run_exit_agent_checks no longer appends to _pending_exit_events "
            "-- the booked-routing path appears to have been removed.",
        )


class TestPendingExitEventsFormatMatchesLLMExitAgent(unittest.TestCase):
    """Confirms the injected event uses the exact format LLM_EXIT_AGENT
    appends in core/position_wiring.py: the TradeEvent's
    metadata['_exchange_submitted'] is stamped True before it is appended
    to self._pending_exit_events (a plain list), and the append happens
    under self._pending_exit_lock when that lock is present on self
    (T0-A-race, 2026-07-14 -- symbol scans can run in a worker pool
    concurrently with the per-symbol drain's filter+reassign)."""

    def test_appended_event_has_exchange_submitted_metadata_stamped(self):
        obj = _build_bot()
        _run_with_verdict(obj, action="full_close", urgency="critical")

        self.assertEqual(len(obj._pending_exit_events), 1)
        event = obj._pending_exit_events[0]
        self.assertEqual(event.metadata["_exchange_submitted"], True)

    def test_append_happens_under_pending_exit_lock_when_available(self):
        # threading.Lock is a read-only C type -- can't monkeypatch .acquire
        # on a real one, so use a MagicMock lock that supports the context
        # manager protocol (`with lock:` -> __enter__/__exit__) and assert
        # those were invoked around the append.
        obj = _build_bot(with_pending_lock=False)
        fake_lock = MagicMock()
        obj._pending_exit_lock = fake_lock

        _run_with_verdict(obj, action="full_close", urgency="critical")

        fake_lock.__enter__.assert_called_once()
        fake_lock.__exit__.assert_called_once()
        self.assertEqual(len(obj._pending_exit_events), 1)

    def test_still_books_when_pending_exit_lock_is_absent(self):
        """Defensive: an older/minimal `self` without _pending_exit_lock
        must still book the close (falls back to an unlocked append) rather
        than crashing or silently skipping the queue."""
        obj = _build_bot(with_pending_lock=False)
        self.assertFalse(hasattr(obj, "_pending_exit_lock"))

        _run_with_verdict(obj, action="full_close", urgency="critical")

        self.assertEqual(len(obj._pending_exit_events), 1)


if __name__ == "__main__":
    unittest.main()
