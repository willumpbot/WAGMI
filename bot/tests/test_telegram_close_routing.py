"""
Tests for the Telegram /close and /closeall routed-close (booked path).

BEFORE: TelegramCommandBot._cmd_close/_cmd_closeall called a bare
pos_mgr.force_close and discarded the TradeEvent -- no exchange order, no
equity, no ledger row, no learning fan-out (the same silent-drop shape as the
LLM_EXIT_HIGH bug).

FIX: _routed_manual_close does order-first (mirrors llm_integration): submit the
exchange close -> force_close ONLY on a confirmed fill -> stamp
metadata["_exchange_submitted"] -> inject the event onto bot._pending_exit_events
under _pending_exit_lock, so the per-event loop books equity+ledger+learning+
shadow exactly once (TELEGRAM_CLOSE is in _FULL_CLOSE/_close_actions).

Everything mocked -- no real exchange/data access.
"""
import threading
import unittest
from unittest.mock import MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts.telegram_bot import TelegramCommandBot


def _make_bot(filled=True, has_position=True, side="LONG", qty=2.0,
              force_close_returns_event=True):
    bot = MagicMock()
    if has_position:
        pos = MagicMock()
        pos.side = side
        pos.qty = qty
        bot.pos_mgr.positions = {"SOL": pos}
    else:
        bot.pos_mgr.positions = {}
    bot.order_executor.close_position = MagicMock(
        return_value=MagicMock(filled=filled)
    )
    if force_close_returns_event:
        ev = MagicMock()
        ev.symbol = "SOL"
        ev.pnl = -5.0
        ev.metadata = {}
        bot.pos_mgr.force_close = MagicMock(return_value=ev)
    else:
        bot.pos_mgr.force_close = MagicMock(return_value=None)
    bot._pending_exit_events = []
    bot._pending_exit_lock = threading.Lock()
    return bot


def _tb(bot):
    # Bypass TelegramCommandBot.__init__ (needs a token/config); the routed
    # helper only touches self.bot.*
    tb = TelegramCommandBot.__new__(TelegramCommandBot)
    tb.bot = bot
    return tb


class TestTelegramRoutedClose(unittest.TestCase):
    def test_happy_path_books_via_pending_events(self):
        bot = _make_bot(filled=True, side="LONG", qty=2.0)
        ev = _tb(bot)._routed_manual_close("SOL", 100.0)

        bot.order_executor.close_position.assert_called_once_with(
            "SOL", "SELL", 2.0, 100.0, reason="TELEGRAM_CLOSE"
        )
        bot.pos_mgr.force_close.assert_called_once_with("SOL", 100.0, "TELEGRAM_CLOSE")
        self.assertEqual(len(bot._pending_exit_events), 1)
        self.assertIs(bot._pending_exit_events[0], ev)
        self.assertTrue(ev.metadata.get("_exchange_submitted"))

    def test_short_position_closes_with_buy_side(self):
        bot = _make_bot(side="SHORT", qty=1.5)
        _tb(bot)._routed_manual_close("SOL", 90.0)
        bot.order_executor.close_position.assert_called_once_with(
            "SOL", "BUY", 1.5, 90.0, reason="TELEGRAM_CLOSE"
        )

    def test_order_not_filled_blocks_booking(self):
        bot = _make_bot(filled=False)
        result = _tb(bot)._routed_manual_close("SOL", 100.0)
        self.assertIsNone(result)
        bot.pos_mgr.force_close.assert_not_called()
        self.assertEqual(bot._pending_exit_events, [])

    def test_no_open_position_returns_none(self):
        bot = _make_bot(has_position=False)
        self.assertIsNone(_tb(bot)._routed_manual_close("SOL", 100.0))
        bot.order_executor.close_position.assert_not_called()
        self.assertEqual(bot._pending_exit_events, [])

    def test_force_close_none_does_not_append(self):
        bot = _make_bot(filled=True, force_close_returns_event=False)
        self.assertIsNone(_tb(bot)._routed_manual_close("SOL", 100.0))
        self.assertEqual(bot._pending_exit_events, [])

    def test_append_happens_under_pending_exit_lock(self):
        bot = _make_bot()
        fake_lock = MagicMock()
        bot._pending_exit_lock = fake_lock
        _tb(bot)._routed_manual_close("SOL", 100.0)
        fake_lock.__enter__.assert_called_once()
        fake_lock.__exit__.assert_called_once()
        self.assertEqual(len(bot._pending_exit_events), 1)


if __name__ == "__main__":
    unittest.main()
