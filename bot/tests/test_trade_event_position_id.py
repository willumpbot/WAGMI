"""
Phase 0.4-A1: TradeEvent.position_id regression tests.

WHY THIS EXISTS: the 0.3b agent added `Position.position_id` (execution/
position_manager.py:98, backfilled :147-152) but TradeEvent — the object
that actually flows into the trade log / close pipeline — never carried it.
That's the single hard dependency the 0.4 close-handler rebuild (trade_closed.py
/ close_outbox.py / close_bus.py) has on this file: every consumer needs a
stable identity key on the event itself, not just on the Position object that
may already be gone/mutated by the time the event is processed downstream.

This file exercises all 4 TradeEvent construction sites in
execution/position_manager.py and asserts each yields a `position_id` that
matches the originating Position's id:
  1. open_position()          -> TradeEvent(action="OPEN")       (:~708)
  2. _partial_close_tp1()      -> TradeEvent(action="TP1")        (:~1641, via update_price)
  3. _close_position()         -> TradeEvent(action=<close type>) (:~1977, via force_close)
  4. partial_close()           -> TradeEvent(action=<partial>)    (:~2182)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager, TradeEvent


class TestTradeEventPositionIdField(unittest.TestCase):
    """Field-level sanity: exists, defaults to "", round-trips."""

    def test_field_exists_and_defaults_empty(self):
        event = TradeEvent(symbol="BTC", action="OPEN", side="LONG", price=1.0, qty=1.0)
        self.assertTrue(hasattr(event, "position_id"))
        self.assertEqual(event.position_id, "")

    def test_field_round_trips(self):
        event = TradeEvent(
            symbol="BTC", action="OPEN", side="LONG", price=1.0, qty=1.0,
            position_id="abc123",
        )
        self.assertEqual(event.position_id, "abc123")


class TestTradeEventPositionIdConstructionSites(unittest.TestCase):
    """Exercise all 4 real construction paths end-to-end via PositionManager."""

    def test_open_event_carries_position_id(self):
        """Site 1 (~:708): open_position() -> TradeEvent(action='OPEN')."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 110.0, 120.0,
                                leverage=1.0, atr=3.0)
        self.assertTrue(pos.position_id, "Position must have a non-empty position_id")

        open_events = [e for e in pm.trade_log if e.action == "OPEN" and e.symbol == "TEST"]
        self.assertEqual(len(open_events), 1)
        self.assertEqual(open_events[0].position_id, pos.position_id)

    def test_tp1_event_carries_position_id(self):
        """Site 2 (~:1641): _partial_close_tp1() -> TradeEvent(action='TP1')."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 105.0, 120.0,
                                leverage=1.0, atr=3.0)
        expected_id = pos.position_id

        events = pm.update_price("TEST", 105.0)  # crosses TP1
        tp1_events = [e for e in events if e.action == "TP1"]
        self.assertEqual(len(tp1_events), 1, f"Expected exactly one TP1 event, got {events}")
        self.assertEqual(tp1_events[0].position_id, expected_id)

        # Also verify it landed in the persistent trade_log (not just the
        # per-tick return value), since that's what downstream consumers read.
        logged_tp1 = [e for e in pm.trade_log if e.action == "TP1" and e.symbol == "TEST"]
        self.assertEqual(len(logged_tp1), 1)
        self.assertEqual(logged_tp1[0].position_id, expected_id)

    def test_close_position_event_carries_position_id(self):
        """Site 3 (~:1977): _close_position() -> TradeEvent, via force_close()."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 110.0, 120.0,
                                leverage=1.0, atr=3.0)
        expected_id = pos.position_id

        event = pm.force_close("TEST", 110.0, "TEST_FINAL")
        self.assertIsNotNone(event)
        self.assertTrue(event.is_position_close)
        self.assertEqual(event.position_id, expected_id)
        # The Position object itself keeps its id after close (not mutated).
        self.assertEqual(pm.positions["TEST"].position_id, expected_id)

    def test_partial_close_event_carries_position_id(self):
        """Site 4 (~:2182): partial_close() -> TradeEvent."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 110.0, 120.0,
                                leverage=1.0, atr=3.0)
        expected_id = pos.position_id

        event = pm.partial_close("TEST", 0.5, 102.0, action="LLM_EXIT_PARTIAL")
        self.assertIsNotNone(event)
        self.assertFalse(event.is_position_close)
        self.assertEqual(event.position_id, expected_id)

    def test_all_four_sites_agree_on_same_position_lifecycle(self):
        """One position through OPEN -> TP1 -> partial -> final close: every
        emitted TradeEvent must carry the SAME position_id throughout."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 103.0, 120.0,
                                leverage=1.0, atr=3.0)
        pid = pos.position_id
        self.assertTrue(pid)

        tp1_events = pm.update_price("TEST", 103.0)  # TP1 leg
        partial_event = pm.partial_close("TEST", 0.3, 104.0, action="LLM_EXIT_PARTIAL")
        final_event = pm.force_close("TEST", 106.0, "TEST_FINAL")

        all_events = [e for e in pm.trade_log if e.symbol == "TEST"]
        self.assertGreaterEqual(len(all_events), 4)  # OPEN, TP1, PARTIAL, close
        for e in all_events:
            self.assertEqual(e.position_id, pid, f"event {e.action!r} had mismatched position_id")


if __name__ == "__main__":
    unittest.main()
