"""
Tests for the Manual Trade Journal & Equity Tracker.

Covers:
- Entry/exit logging
- P&L calculation with leverage
- Equity curve tracking
- Stats computation
- Compounding report math
- Edge cases
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Ensure bot/ is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from manual.trade_journal import TradeJournal, JournalEntry


@pytest.fixture
def tmp_journal(tmp_path):
    """Create a TradeJournal with temp files."""
    journal_path = str(tmp_path / "trade_journal.jsonl")
    equity_path = str(tmp_path / "equity_state.json")
    return TradeJournal(
        journal_path=journal_path,
        equity_path=equity_path,
        starting_equity=100.0,
    )


class TestEntryLogging:
    """Test trade entry logging."""

    def test_log_basic_entry(self, tmp_journal):
        entry = tmp_journal.log_entry(
            symbol="HYPE", side="BUY", entry_price=40.0,
            leverage=25, qty=10,
        )
        assert entry.trade_id.startswith("MJ-")
        assert entry.symbol == "HYPE"
        assert entry.side == "BUY"
        assert entry.entry_price == 40.0
        assert entry.leverage == 25
        assert entry.qty == 10
        assert entry.status == "OPEN"
        assert entry.margin_used == 16.0  # 40 * 10 / 25

    def test_log_sell_entry(self, tmp_journal):
        entry = tmp_journal.log_entry(
            symbol="SOL", side="SELL", entry_price=145.0,
            leverage=20, qty=5,
        )
        assert entry.side == "SELL"
        assert entry.margin_used == 36.25  # 145 * 5 / 20

    def test_normalize_long_to_buy(self, tmp_journal):
        entry = tmp_journal.log_entry(
            symbol="BTC", side="LONG", entry_price=85000,
            leverage=10, qty=0.01,
        )
        assert entry.side == "BUY"

    def test_normalize_short_to_sell(self, tmp_journal):
        entry = tmp_journal.log_entry(
            symbol="BTC", side="SHORT", entry_price=85000,
            leverage=10, qty=0.01,
        )
        assert entry.side == "SELL"

    def test_invalid_side_raises(self, tmp_journal):
        with pytest.raises(ValueError, match="Invalid side"):
            tmp_journal.log_entry(
                symbol="BTC", side="HOLD", entry_price=85000,
                leverage=10, qty=0.01,
            )

    def test_entry_persists_to_file(self, tmp_journal):
        tmp_journal.log_entry(
            symbol="HYPE", side="BUY", entry_price=40.0,
            leverage=25, qty=10,
        )
        with open(tmp_journal.journal_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["symbol"] == "HYPE"
        assert data["status"] == "OPEN"

    def test_multiple_entries(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40, 25, 10)
        tmp_journal.log_entry("SOL", "SELL", 145, 20, 5)
        tmp_journal.log_entry("BTC", "BUY", 85000, 10, 0.01)
        assert len(tmp_journal.get_open_trades()) == 3

    def test_signal_id_link(self, tmp_journal):
        entry = tmp_journal.log_entry(
            symbol="HYPE", side="BUY", entry_price=40.0,
            leverage=25, qty=10, signal_id="SNIPER-ABC123",
        )
        assert entry.signal_id == "SNIPER-ABC123"


class TestExitLogging:
    """Test trade exit logging and P&L calculation."""

    def test_profitable_long_exit(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit("HYPE", 42.0, "TP")

        assert trade is not None
        assert trade.status == "CLOSED"
        assert trade.exit_price == 42.0
        assert trade.exit_reason == "TP"
        # PnL: (42-40)/40 * 400 (position value) = 20
        assert trade.pnl == 20.0
        # PnL%: 5% price move * 25x leverage = 125% on margin
        assert trade.pnl_pct == 125.0

    def test_losing_long_exit(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit("HYPE", 39.0, "SL")

        assert trade is not None
        assert trade.pnl == -10.0  # (39-40)/40 * 400 = -10
        assert trade.pnl_pct == -62.5  # -2.5% * 25x = -62.5%

    def test_profitable_short_exit(self, tmp_journal):
        tmp_journal.log_entry("SOL", "SELL", 150.0, 20, 5)
        trade = tmp_journal.log_exit("SOL", 140.0, "TP")

        assert trade is not None
        # PnL: (150-140)/150 * 750 = 50
        assert trade.pnl == 50.0

    def test_losing_short_exit(self, tmp_journal):
        tmp_journal.log_entry("SOL", "SELL", 150.0, 20, 5)
        trade = tmp_journal.log_exit("SOL", 155.0, "SL")

        assert trade is not None
        # PnL: (150-155)/150 * 750 = -25
        assert trade.pnl == -25.0

    def test_exit_updates_equity(self, tmp_journal):
        assert tmp_journal.current_equity == 100.0
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")
        assert tmp_journal.current_equity == 120.0  # 100 + 20

    def test_exit_loss_reduces_equity(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 39.0, "SL")
        assert tmp_journal.current_equity == 90.0  # 100 - 10

    def test_exit_by_trade_id(self, tmp_journal):
        entry = tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit(entry.trade_id, 42.0, "TP")
        assert trade is not None
        assert trade.trade_id == entry.trade_id

    def test_exit_nonexistent_returns_none(self, tmp_journal):
        result = tmp_journal.log_exit("NONEXISTENT", 42.0, "TP")
        assert result is None

    def test_exit_already_closed_returns_none(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")
        # Try to exit again
        result = tmp_journal.log_exit("HYPE", 43.0, "TP")
        assert result is None

    def test_hold_time_tracked(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit("HYPE", 42.0, "TP")
        assert trade.hold_time_hours is not None
        assert trade.hold_time_hours >= 0

    def test_multiple_trades_sequential(self, tmp_journal):
        """Trade 1 wins, trade 2 loses. Equity should reflect both."""
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")  # +$20
        assert tmp_journal.current_equity == 120.0

        tmp_journal.log_entry("SOL", "BUY", 150.0, 20, 5)
        tmp_journal.log_exit("SOL", 145.0, "SL")  # PnL: -5/150 * 750 = -25
        assert tmp_journal.current_equity == 95.0


class TestPnLCalculation:
    """Detailed P&L math verification."""

    def test_leveraged_long_pnl(self, tmp_journal):
        """$100 equity, 25x leverage, 2% move up = $20 profit."""
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        # Position value = 400, price up 5% to 42
        trade = tmp_journal.log_exit("HYPE", 42.0, "TP")
        assert trade.pnl == 20.0  # 5% of $400

    def test_leveraged_short_pnl(self, tmp_journal):
        """Short at 150, close at 140 = 6.67% gain on position."""
        tmp_journal.log_entry("SOL", "SELL", 150.0, 20, 5)
        # Position value = 750, price down 6.67%
        trade = tmp_journal.log_exit("SOL", 140.0, "TP")
        assert trade.pnl == 50.0  # (150-140)/150 * 750

    def test_breakeven_trade(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit("HYPE", 40.0, "BREAKEVEN")
        assert trade.pnl == 0.0
        assert trade.pnl_pct == 0.0
        assert tmp_journal.current_equity == 100.0

    def test_small_account_real_scenario(self, tmp_journal):
        """Simulate $100 account, HYPE 25x, typical sniper trade."""
        # $100 account, risk $10 (10%), 25x lev
        # HYPE at $40, stop at $39.20 (2% risk)
        # Position: $10 margin * 25x = $250 position = 6.25 HYPE
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 6.25)
        # Hit scalp TP at $41.20 (3% move)
        trade = tmp_journal.log_exit("HYPE", 41.20, "TP")
        # PnL: 3% of $250 = $7.50
        assert trade.pnl == 7.5
        # PnL%: 3% * 25x = 75% on margin
        assert trade.pnl_pct == 75.0
        assert tmp_journal.current_equity == 107.5


class TestEquityCurve:
    """Test equity curve generation."""

    def test_empty_curve(self, tmp_journal):
        curve = tmp_journal.get_equity_curve()
        assert len(curve) == 1  # Just starting point
        assert curve[0]["equity"] == 100.0

    def test_curve_after_trades(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")  # +20
        tmp_journal.log_entry("SOL", "BUY", 150.0, 20, 5)
        tmp_journal.log_exit("SOL", 145.0, "SL")  # -25

        curve = tmp_journal.get_equity_curve()
        assert len(curve) == 3  # Start + 2 trades
        assert curve[0]["equity"] == 100.0
        assert curve[1]["equity"] == 120.0
        assert curve[2]["equity"] == 95.0

    def test_curve_only_includes_closed(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")
        tmp_journal.log_entry("SOL", "BUY", 150.0, 20, 5)  # Still open

        curve = tmp_journal.get_equity_curve()
        assert len(curve) == 2  # Start + 1 closed trade


class TestStats:
    """Test statistics computation."""

    def test_empty_stats(self, tmp_journal):
        stats = tmp_journal.get_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0
        assert stats["current_equity"] == 100.0

    def test_stats_with_trades(self, tmp_journal):
        # 3 wins, 1 loss
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")  # +20

        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 41.0, "TP")  # +10

        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 41.5, "TP")  # +15

        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 39.0, "SL")  # -10

        stats = tmp_journal.get_stats()
        assert stats["total_trades"] == 4
        assert stats["wins"] == 3
        assert stats["losses"] == 1
        assert stats["win_rate"] == 0.75
        assert stats["total_pnl"] == 35.0  # 20 + 10 + 15 - 10
        assert stats["best_trade"] == 20.0
        assert stats["worst_trade"] == -10.0
        # PF: (20+10+15) / 10 = 4.5
        assert stats["profit_factor"] == 4.5

    def test_all_wins_pf_inf(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")
        stats = tmp_journal.get_stats()
        assert stats["profit_factor"] == float("inf")

    def test_win_loss_streaks(self, tmp_journal):
        # W W W L L W
        for exit_price in [42, 41, 41.5, 39, 38.5, 43]:
            tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
            tmp_journal.log_exit("HYPE", exit_price, "TP" if exit_price > 40 else "SL")

        stats = tmp_journal.get_stats()
        assert stats["longest_win_streak"] == 3
        assert stats["longest_loss_streak"] == 2

    def test_total_return_pct(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")  # +$20
        stats = tmp_journal.get_stats()
        assert stats["total_return_pct"] == 20.0  # $20 on $100


class TestCompoundingReport:
    """Test compounding math and projections."""

    def test_report_at_start(self, tmp_journal):
        report = tmp_journal.get_compounding_report()
        assert report["starting_equity"] == 100.0
        assert report["current_equity"] == 100.0
        assert report["total_return"] == 0.0
        assert report["target"] == 1000.0

    def test_report_after_growth(self, tmp_journal):
        # Simulate 20% growth, with start_date set to yesterday
        tmp_journal._start_date = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")  # +$20

        report = tmp_journal.get_compounding_report()
        assert report["current_equity"] == 120.0
        assert report["total_return"] == 20.0
        assert report["total_return_pct"] == 20.0
        assert report["progress_pct"] > 0

    def test_projections_exist(self, tmp_journal):
        tmp_journal._start_date = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        tmp_journal.log_exit("HYPE", 42.0, "TP")

        report = tmp_journal.get_compounding_report()
        assert "1w" in report["projections"]
        assert "4w" in report["projections"]
        assert "12w" in report["projections"]

    def test_target_reached(self, tmp_journal):
        """Set equity above target, days_to_target should be 0."""
        tmp_journal._start_date = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        tmp_journal.set_equity(1500.0)
        report = tmp_journal.get_compounding_report()
        assert report["days_to_target"] == 0

    def test_progress_pct(self, tmp_journal):
        """$100 -> $550 should be ~50% progress to $1000."""
        tmp_journal.set_equity(550.0)
        report = tmp_journal.get_compounding_report()
        assert abs(report["progress_pct"] - 50.0) < 0.1


class TestPersistence:
    """Test that journal survives reload."""

    def test_reload_trades(self, tmp_path):
        journal_path = str(tmp_path / "journal.jsonl")
        equity_path = str(tmp_path / "equity.json")

        # First session: create trades
        j1 = TradeJournal(journal_path, equity_path, 100.0)
        j1.log_entry("HYPE", "BUY", 40.0, 25, 10)
        j1.log_exit("HYPE", 42.0, "TP")
        j1.log_entry("SOL", "BUY", 150.0, 20, 5)

        # Second session: reload
        j2 = TradeJournal(journal_path, equity_path, 100.0)
        assert len(j2.get_closed_trades()) == 1
        assert len(j2.get_open_trades()) == 1
        assert j2.current_equity == 120.0

    def test_reload_equity_state(self, tmp_path):
        journal_path = str(tmp_path / "journal.jsonl")
        equity_path = str(tmp_path / "equity.json")

        j1 = TradeJournal(journal_path, equity_path, 100.0)
        j1.log_entry("HYPE", "BUY", 40.0, 25, 10)
        j1.log_exit("HYPE", 42.0, "TP")

        j2 = TradeJournal(journal_path, equity_path, 100.0)
        assert j2.current_equity == 120.0
        assert j2.starting_equity == 100.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_symbol_case_normalization(self, tmp_journal):
        entry = tmp_journal.log_entry("hype", "buy", 40.0, 25, 10)
        assert entry.symbol == "HYPE"
        assert entry.side == "BUY"

    def test_exit_by_symbol_gets_most_recent(self, tmp_journal):
        """When multiple trades open for same symbol, exit most recent."""
        e1 = tmp_journal.log_entry("HYPE", "BUY", 38.0, 25, 10)
        e2 = tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        trade = tmp_journal.log_exit("HYPE", 42.0, "TP")
        assert trade.trade_id == e2.trade_id  # Most recent

    def test_set_equity_manual(self, tmp_journal):
        tmp_journal.set_equity(250.0)
        assert tmp_journal.current_equity == 250.0

    def test_get_open_after_close(self, tmp_journal):
        tmp_journal.log_entry("HYPE", "BUY", 40.0, 25, 10)
        assert len(tmp_journal.get_open_trades()) == 1
        tmp_journal.log_exit("HYPE", 42.0, "TP")
        assert len(tmp_journal.get_open_trades()) == 0
        assert len(tmp_journal.get_closed_trades()) == 1


class TestJournalEntry:
    """Test JournalEntry dataclass."""

    def test_to_dict_round_trip(self):
        entry = JournalEntry(
            trade_id="MJ-TEST1234",
            symbol="HYPE",
            side="BUY",
            entry_price=40.0,
            leverage=25,
            qty=10,
            margin_used=16.0,
            entry_time="2026-03-24T12:00:00+00:00",
        )
        d = entry.to_dict()
        restored = JournalEntry.from_dict(d)
        assert restored.trade_id == entry.trade_id
        assert restored.symbol == entry.symbol
        assert restored.entry_price == entry.entry_price
