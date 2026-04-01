"""Tests for the daily P&L tracker (manual $100 sniper account)."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

from manual.daily_tracker import (
    DailyTracker,
    DayStats,
    format_daily_dashboard,
    DAILY_LOSS_THRESHOLD,
    MILESTONES,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_sim_trade(
    trade_id: str,
    symbol: str = "HYPE",
    side: str = "BUY",
    pnl_usd: float = 5.0,
    result: str = "WIN",
    closed_at: str = "2026-03-25T12:00:00+00:00",
    equity_at_open: float = 100.0,
    equity_at_close: float = 105.0,
) -> dict:
    """Create a sim_trades.jsonl compatible trade dict."""
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "tier": "SNIPER",
        "entry": 25.0,
        "exit_price": 25.5 if pnl_usd > 0 else 24.5,
        "sl": 24.0,
        "tp_scalp": 26.0,
        "leverage": 25.0,
        "position_size_usd": 250.0,
        "qty": 10.0,
        "risk_amount": 10.0,
        "equity_at_open": equity_at_open,
        "equity_at_close": equity_at_close,
        "pnl_usd": pnl_usd,
        "pnl_pct": round(pnl_usd / equity_at_open * 100, 1),
        "result": result,
        "exit_reason": "tp_scalp" if result == "WIN" else "sl",
        "hold_time_s": 3600,
        "hold_time_hours": 1.0,
        "opened_at": "2026-03-25T11:00:00+00:00",
        "closed_at": closed_at,
        "confidence": 85.0,
        "num_agree": 3,
        "regime": "consolidation",
    }


def _make_journal_trade(
    trade_id: str,
    symbol: str = "HYPE",
    pnl: float = 5.0,
    exit_time: str = "2026-03-25T14:00:00+00:00",
    status: str = "CLOSED",
) -> dict:
    """Create a trade_journal.jsonl compatible trade dict."""
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": "BUY",
        "entry_price": 25.0,
        "leverage": 25.0,
        "qty": 10.0,
        "margin_used": 10.0,
        "exit_price": 25.5 if pnl > 0 else 24.5,
        "exit_reason": "TP" if pnl > 0 else "SL",
        "exit_time": exit_time,
        "pnl": pnl,
        "pnl_pct": round(pnl / 10.0 * 100, 1),
        "hold_time_hours": 2.0,
        "entry_time": "2026-03-25T12:00:00+00:00",
        "status": status,
        "notes": "",
    }


def _write_jsonl(path: str, trades: list):
    """Write trades to a JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide temp directory paths for test files."""
    sim_path = os.path.join(str(tmp_path), "sim_trades.jsonl")
    journal_path = os.path.join(str(tmp_path), "trade_journal.jsonl")
    equity_path = os.path.join(str(tmp_path), "equity_state.json")
    return sim_path, journal_path, equity_path


# ── Tests: DailyTracker basics ────────────────────────────────────────


class TestDailyTrackerEmpty:
    """Tests with no trade data."""

    def test_empty_tracker(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        assert tracker.current_equity == 100.0
        assert tracker.days_traded == 0
        assert tracker.get_daily_stats() == []
        assert tracker.get_best_day() is None
        assert tracker.get_worst_day() is None
        assert tracker.get_avg_daily_return_pct() == 0.0

    def test_empty_streak(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        count, stype = tracker.get_streak()
        assert count == 0
        assert stype == "none"

    def test_empty_projections(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        proj = tracker.project_milestones()
        # With 0 growth rate, all milestones should be None
        for m in MILESTONES:
            assert proj[m] is None


class TestDailyTrackerWithSimTrades:
    """Tests loading from sim_trades.jsonl."""

    def test_single_day_win(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=5.0, result="WIN",
                            closed_at="2026-03-25T14:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        assert tracker.days_traded == 1
        assert tracker.current_equity == 115.0

        day = tracker.get_daily_stats()[0]
        assert day.date == "2026-03-25"
        assert day.pnl == 15.0
        assert day.wins == 2
        assert day.losses == 0
        assert day.win_rate == 100.0

    def test_multi_day(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=12.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=15.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
            _make_sim_trade("SIM-0003", pnl_usd=-5.0, result="LOSS",
                            closed_at="2026-03-25T14:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        assert tracker.days_traded == 2
        assert tracker.current_equity == 122.0  # 100 + 12 + 15 - 5

        days = tracker.get_daily_stats()
        assert days[0].date == "2026-03-24"
        assert days[0].pnl == 12.0
        assert days[1].date == "2026-03-25"
        assert days[1].pnl == 10.0  # 15 - 5
        assert days[1].wins == 1
        assert days[1].losses == 1

    def test_equity_compounds_across_days(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=20.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        days = tracker.get_daily_stats()
        # Day 1: $100 -> $120
        assert days[0].starting_equity == 100.0
        assert days[0].ending_equity == 120.0
        # Day 2: $120 -> $130
        assert days[1].starting_equity == 120.0
        assert days[1].ending_equity == 130.0


class TestDailyTrackerWithJournal:
    """Tests loading from trade_journal.jsonl."""

    def test_journal_closed_only(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_journal_trade("MJ-0001", pnl=8.0, status="CLOSED",
                                exit_time="2026-03-25T14:00:00+00:00"),
            _make_journal_trade("MJ-0002", pnl=0.0, status="OPEN"),  # Should be skipped
        ]
        _write_jsonl(journal_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        assert tracker.days_traded == 1
        assert tracker.current_equity == 108.0


class TestDailyTrackerMerged:
    """Tests combining sim + journal trades."""

    def test_both_sources(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        sim_trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-25T10:00:00+00:00"),
        ]
        journal_trades = [
            _make_journal_trade("MJ-0001", pnl=5.0, status="CLOSED",
                                exit_time="2026-03-25T14:00:00+00:00"),
        ]
        _write_jsonl(sim_path, sim_trades)
        _write_jsonl(journal_path, journal_trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        assert tracker.days_traded == 1
        assert tracker.current_equity == 115.0


# ── Tests: Stats ──────────────────────────────────────────────────────


class TestStats:
    def test_best_worst_day(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=20.0, result="WIN",
                            closed_at="2026-03-23T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=-8.0, result="LOSS",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0003", pnl_usd=5.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        best = tracker.get_best_day()
        worst = tracker.get_worst_day()
        assert best.date == "2026-03-23"
        assert best.pnl == 20.0
        assert worst.date == "2026-03-24"
        assert worst.pnl == -8.0

    def test_avg_daily_return(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=12.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        avg = tracker.get_avg_daily_return_pct()
        # Day 1: 10/100 = 10%, Day 2: 12/110 = 10.91%
        assert avg > 0

    def test_win_streak(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-23T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=5.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0003", pnl_usd=8.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        count, stype = tracker.get_streak()
        assert count == 3
        assert stype == "win"

    def test_loss_streak(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-23T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=-5.0, result="LOSS",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0003", pnl_usd=-3.0, result="LOSS",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        count, stype = tracker.get_streak()
        assert count == 2
        assert stype == "loss"


# ── Tests: Projections ────────────────────────────────────────────────


class TestProjections:
    def test_positive_growth_projects_milestones(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        # Create trades over multiple days showing growth
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-23T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=12.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0003", pnl_usd=15.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        proj = tracker.project_milestones()
        # With positive growth, all milestones should have projected days
        assert proj[250.0] is not None
        assert proj[250.0] > 0
        assert proj[500.0] is not None
        assert proj[500.0] > proj[250.0]
        assert proj[1000.0] is not None
        assert proj[1000.0] > proj[500.0]

    def test_milestone_reached(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        # One big trade that puts us past $250
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=160.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        proj = tracker.project_milestones()
        assert proj[250.0] == 0  # Already reached


# ── Tests: Risk flags ─────────────────────────────────────────────────


class TestRiskFlags:
    def test_daily_loss_flag(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        # Loss of 20% in one day (> 15% threshold)
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=-20.0, result="LOSS",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        day = tracker.get_daily_stats()[0]
        assert day.reduced_sizing_flag is True
        assert tracker.should_reduce_sizing_today() is True

    def test_no_flag_on_small_loss(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        # Loss of 5% (< 15% threshold)
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=-5.0, result="LOSS",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        day = tracker.get_daily_stats()[0]
        assert day.reduced_sizing_flag is False
        assert tracker.should_reduce_sizing_today() is False


# ── Tests: Dashboard formatting ───────────────────────────────────────


class TestDashboardFormat:
    def test_empty_dashboard(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        output = format_daily_dashboard(tracker)
        assert "$100 ACCOUNT TRACKER" in output
        assert "No trades yet" in output
        assert "Target: $1,000" in output

    def test_dashboard_with_trades(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=12.0, result="WIN",
                            closed_at="2026-03-24T12:00:00+00:00"),
            _make_sim_trade("SIM-0002", pnl_usd=14.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        output = format_daily_dashboard(tracker)
        assert "$100 ACCOUNT TRACKER" in output
        assert "Day 1" in output
        assert "Day 2" in output
        assert "Progress:" in output
        assert "Avg daily:" in output
        assert "Projections" in output

    def test_dashboard_risk_warning(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=-20.0, result="LOSS",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        output = format_daily_dashboard(tracker)
        assert "REDUCE SIZING" in output

    def test_dashboard_default_tracker(self, tmp_dir):
        """format_daily_dashboard with no arg creates default tracker."""
        # Just verify it doesn't crash (will use default paths, may be empty)
        output = format_daily_dashboard()
        assert "$100 ACCOUNT TRACKER" in output


class TestGetSummary:
    def test_summary_structure(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        trades = [
            _make_sim_trade("SIM-0001", pnl_usd=10.0, result="WIN",
                            closed_at="2026-03-25T12:00:00+00:00"),
        ]
        _write_jsonl(sim_path, trades)

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        summary = tracker.get_summary()

        assert "starting_equity" in summary
        assert "current_equity" in summary
        assert "target_equity" in summary
        assert "progress_pct" in summary
        assert "days_traded" in summary
        assert "total_trades" in summary
        assert "overall_win_rate" in summary
        assert "avg_daily_return_pct" in summary
        assert "compound_growth_rate_pct" in summary
        assert "best_day_pnl" in summary
        assert "worst_day_pnl" in summary
        assert "streak_count" in summary
        assert "streak_type" in summary
        assert "milestone_projections" in summary
        assert "reduce_sizing_today" in summary

        assert summary["current_equity"] == 110.0
        assert summary["total_trades"] == 1
        assert summary["overall_win_rate"] == 100.0


# ── Tests: Corrupt data handling ──────────────────────────────────────


class TestCorruptData:
    def test_corrupt_jsonl_line(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        with open(sim_path, "w") as f:
            f.write(json.dumps(_make_sim_trade("SIM-0001", pnl_usd=10.0,
                               closed_at="2026-03-25T12:00:00+00:00")) + "\n")
            f.write("THIS IS NOT JSON\n")
            f.write(json.dumps(_make_sim_trade("SIM-0002", pnl_usd=5.0,
                               closed_at="2026-03-25T14:00:00+00:00")) + "\n")

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )

        # Should load 2 valid trades, skip the corrupt line
        assert tracker.current_equity == 115.0

    def test_empty_file(self, tmp_dir):
        sim_path, journal_path, equity_path = tmp_dir
        with open(sim_path, "w") as f:
            f.write("")

        tracker = DailyTracker(
            sim_trades_path=sim_path,
            journal_path=journal_path,
            equity_state_path=equity_path,
        )
        assert tracker.days_traded == 0
        assert tracker.current_equity == 100.0
