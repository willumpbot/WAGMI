"""
Tests for the Sniper Signal Live Simulator.

Covers:
- Position opening from signal
- SL hit closes with correct loss
- TP hit closes with correct profit
- Time stop after 12h
- Equity compounding
- sim_status output format
"""

import json
import os
import time
import tempfile
import pytest
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch


# ── Fake SniperSignal for testing ──────────────────────────────────────

@dataclass
class FakeSniperSignal:
    symbol: str = "HYPE"
    side: str = "BUY"
    tier: str = "SNIPER"
    entry: float = 100.0
    sl: float = 98.0        # 2% stop
    tp_scalp: float = 103.0  # 3% TP
    tp_swing: float = 106.0
    leverage: float = 20.0
    risk_pct: float = 0.10   # 10%
    risk_amount: float = 10.0
    position_size_usd: float = 500.0
    qty: float = 5.0
    margin_required: float = 25.0
    pnl_scalp: float = 15.0
    pnl_swing: float = 30.0
    loss_amount: float = 10.0
    rr_scalp: float = 1.5
    rr_swing: float = 3.0
    account_equity: float = 100.0
    account_after_win: float = 115.0
    account_after_loss: float = 90.0
    growth_pct: float = 15.0
    confidence: float = 88.0
    num_agree: int = 3
    strategies: List[str] = field(default_factory=lambda: ["regime_trend", "monte_carlo", "confidence"])
    regime: str = "consolidation"
    ev_per_dollar: float = 1.5
    signal_context: str = "test"
    timestamp: str = "2026-03-24T00:00:00+00:00"
    daily_target_pct: float = 75.0
    hold_target_hours: str = "1-4h (scalp)"


@pytest.fixture
def sim(tmp_path, monkeypatch):
    """Create a fresh SniperSimulator with temp data directory."""
    # Patch the data paths to use temp dir
    import manual.simulator as sim_mod
    monkeypatch.setattr(sim_mod, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sim_mod, "_TRADES_PATH", str(tmp_path / "sim_trades.jsonl"))
    monkeypatch.setattr(sim_mod, "_STATUS_PATH", str(tmp_path / "sim_status.json"))

    from manual.simulator import SniperSimulator
    return SniperSimulator(starting_equity=100.0)


class TestPositionOpening:
    """Test that signals correctly open simulated positions."""

    def test_open_position_from_signal(self, sim):
        sig = FakeSniperSignal()
        pos = sim.on_signal(sig)
        assert pos is not None
        assert pos.symbol == "HYPE"
        assert pos.side == "BUY"
        assert pos.tier == "SNIPER"
        assert pos.entry == 100.0
        assert pos.sl == 98.0
        assert pos.tp_scalp == 103.0
        assert pos.equity_at_open == 100.0
        assert len(sim._open_positions) == 1

    def test_dedup_same_symbol_side(self, sim):
        """Should skip duplicate position on same symbol+side."""
        sig = FakeSniperSignal()
        pos1 = sim.on_signal(sig)
        pos2 = sim.on_signal(sig)
        assert pos1 is not None
        assert pos2 is None
        assert len(sim._open_positions) == 1

    def test_different_symbols_both_open(self, sim):
        sig1 = FakeSniperSignal(symbol="HYPE")
        sig2 = FakeSniperSignal(symbol="BTC", entry=50000, sl=49000, tp_scalp=51500)
        pos1 = sim.on_signal(sig1)
        pos2 = sim.on_signal(sig2)
        assert pos1 is not None
        assert pos2 is not None
        assert len(sim._open_positions) == 2

    def test_compound_sizing(self, sim):
        """Position sizing should use current sim equity, not signal equity."""
        # Manually set equity higher
        sim._equity = 200.0
        sig = FakeSniperSignal()
        pos = sim.on_signal(sig)
        # risk_amount should be based on $200 * 10% = $20, not the signal's $10
        assert pos.risk_amount == 20.0


class TestSLHit:
    """Test stop loss triggers correct closure."""

    def test_buy_sl_hit(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        assert len(sim._open_positions) == 1

        # Price drops to SL
        closed = sim.check_positions({"HYPE": 97.5})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "sl"
        assert trade.result == "LOSS"
        assert trade.exit_price == 98.0  # Closes at SL level, not market
        assert trade.pnl_usd < 0
        assert sim._losses == 1
        assert len(sim._open_positions) == 0

    def test_sell_sl_hit(self, sim):
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=97.0
        )
        sim.on_signal(sig)

        # Price rises to SL
        closed = sim.check_positions({"HYPE": 102.5})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "sl"
        assert trade.result == "LOSS"
        assert trade.exit_price == 102.0

    def test_sl_loss_amount_correct(self, sim):
        """Verify the P&L math: loss = position_size * stop_width_pct."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        closed = sim.check_positions({"HYPE": 97.0})
        trade = closed[0]

        # P&L = position_size * (sl - entry) / entry = pos * -0.02
        expected_pnl = position_size * (98.0 - 100.0) / 100.0
        assert abs(trade.pnl_usd - expected_pnl) < 0.01


class TestTPHit:
    """Test take profit triggers correct closure."""

    def test_buy_tp_scalp_hit(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "tp_scalp"
        assert trade.result == "WIN"
        assert trade.exit_price == 103.0
        assert trade.pnl_usd > 0
        assert sim._wins == 1

    def test_sell_tp_scalp_hit(self, sim):
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=97.0
        )
        sim.on_signal(sig)

        closed = sim.check_positions({"HYPE": 96.0})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "tp_scalp"
        assert trade.result == "WIN"
        assert trade.exit_price == 97.0

    def test_tp_profit_amount_correct(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        closed = sim.check_positions({"HYPE": 105.0})
        trade = closed[0]

        expected_pnl = position_size * (103.0 - 100.0) / 100.0
        assert abs(trade.pnl_usd - expected_pnl) < 0.01


class TestTimeStop:
    """Test 12-hour time stop."""

    def test_time_stop_closes_after_12h(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        # Manually backdate the open time by 13 hours
        sim._open_positions[0].opened_at = time.time() - (13 * 3600)

        # Price is between SL and TP — neither hit, but time exceeded
        closed = sim.check_positions({"HYPE": 100.5})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "time_stop"
        assert trade.exit_price == 100.5  # Closes at market
        assert trade.hold_time_hours >= 12.0

    def test_time_stop_with_profit_is_win(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (13 * 3600)

        closed = sim.check_positions({"HYPE": 101.0})
        assert closed[0].result == "WIN"
        assert closed[0].pnl_usd > 0

    def test_time_stop_with_loss_is_loss(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (13 * 3600)

        closed = sim.check_positions({"HYPE": 99.5})
        assert closed[0].result == "LOSS"
        assert closed[0].pnl_usd < 0

    def test_no_close_before_12h(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        # Price between SL and TP, within time limit
        closed = sim.check_positions({"HYPE": 100.5})
        assert len(closed) == 0
        assert len(sim._open_positions) == 1


class TestEquityCompounding:
    """Test that equity compounds correctly across trades."""

    def test_win_increases_equity(self, sim):
        assert sim._equity == 100.0

        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        closed = sim.check_positions({"HYPE": 104.0})

        assert sim._equity > 100.0
        assert closed[0].equity_at_close == sim._equity

    def test_loss_decreases_equity(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        closed = sim.check_positions({"HYPE": 97.0})

        assert sim._equity < 100.0

    def test_compound_over_multiple_trades(self, sim):
        """Two consecutive wins should compound."""
        # Trade 1: BUY HYPE, win
        sig1 = FakeSniperSignal(symbol="HYPE", side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig1)
        sim.check_positions({"HYPE": 104.0})
        equity_after_1 = sim._equity
        assert equity_after_1 > 100.0

        # Trade 2: BUY BTC (different symbol), win
        sig2 = FakeSniperSignal(symbol="BTC", side="BUY", entry=50000.0, sl=49000.0, tp_scalp=51500.0)
        sim.on_signal(sig2)
        sim.check_positions({"BTC": 52000.0})
        equity_after_2 = sim._equity
        assert equity_after_2 > equity_after_1

    def test_second_trade_uses_updated_equity(self, sim):
        """After a win, the next trade should size based on new equity."""
        sig1 = FakeSniperSignal(symbol="HYPE", side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig1)
        sim.check_positions({"HYPE": 104.0})
        new_equity = sim._equity

        sig2 = FakeSniperSignal(symbol="BTC", side="BUY", entry=50000.0, sl=49000.0, tp_scalp=51500.0)
        pos2 = sim.on_signal(sig2)
        assert pos2.equity_at_open == round(new_equity, 2)


class TestStatusOutput:
    """Test get_status() returns correct format."""

    def test_status_has_required_fields(self, sim):
        status = sim.get_status()
        required = [
            "current_equity", "starting_equity", "total_trades",
            "wins", "losses", "win_rate", "profit_factor",
            "best_trade", "worst_trade", "max_drawdown",
            "current_streak", "daily_pnl", "weekly_pnl",
            "equity_curve", "by_symbol", "by_tier",
            "open_positions", "started_at", "days_elapsed", "growth_pct",
        ]
        for key in required:
            assert key in status, f"Missing key: {key}"

    def test_status_initial_values(self, sim):
        status = sim.get_status()
        assert status["current_equity"] == 100.0
        assert status["starting_equity"] == 100.0
        assert status["total_trades"] == 0
        assert status["wins"] == 0
        assert status["losses"] == 0
        assert status["win_rate"] == 0.0
        assert status["growth_pct"] == 0.0

    def test_status_after_trade(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim.check_positions({"HYPE": 104.0})

        status = sim.get_status()
        assert status["total_trades"] == 1
        assert status["wins"] == 1
        assert status["losses"] == 0
        assert status["win_rate"] == 100.0
        assert status["current_equity"] > 100.0
        assert "HYPE" in status["by_symbol"]
        assert "SNIPER" in status["by_tier"]
        assert status["by_symbol"]["HYPE"]["wins"] == 1
        assert len(status["equity_curve"]) >= 2

    def test_status_open_positions(self, sim):
        sig = FakeSniperSignal()
        sim.on_signal(sig)
        status = sim.get_status()
        assert len(status["open_positions"]) == 1
        assert status["open_positions"][0]["symbol"] == "HYPE"

    def test_status_streak_tracking(self, sim):
        # Win
        sig1 = FakeSniperSignal(symbol="HYPE", side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig1)
        sim.check_positions({"HYPE": 104.0})
        assert sim.get_status()["current_streak"] == 1

        # Another win
        sig2 = FakeSniperSignal(symbol="BTC", side="BUY", entry=50000.0, sl=49000.0, tp_scalp=51500.0)
        sim.on_signal(sig2)
        sim.check_positions({"BTC": 52000.0})
        assert sim.get_status()["current_streak"] == 2

        # Loss
        sig3 = FakeSniperSignal(symbol="SOL", side="BUY", entry=150.0, sl=147.0, tp_scalp=154.5)
        sim.on_signal(sig3)
        sim.check_positions({"SOL": 146.0})
        assert sim.get_status()["current_streak"] == -1


class TestPersistence:
    """Test state saving and loading."""

    def test_trade_logged_to_jsonl(self, sim, tmp_path):
        import manual.simulator as sim_mod
        trades_path = sim_mod._TRADES_PATH

        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim.check_positions({"HYPE": 104.0})

        assert os.path.exists(trades_path)
        with open(trades_path, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1
        trade = json.loads(lines[0])
        assert trade["symbol"] == "HYPE"
        assert trade["result"] == "WIN"

    def test_status_saved_to_json(self, sim, tmp_path):
        import manual.simulator as sim_mod
        status_path = sim_mod._STATUS_PATH

        sig = FakeSniperSignal()
        sim.on_signal(sig)
        sim.check_positions({"HYPE": 104.0})

        assert os.path.exists(status_path)
        with open(status_path, "r") as f:
            data = json.load(f)
        assert data["current_equity"] > 100.0


class TestDrawdown:
    """Test max drawdown tracking."""

    def test_drawdown_after_loss(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim.check_positions({"HYPE": 97.0})

        status = sim.get_status()
        assert status["max_drawdown"] > 0

    def test_drawdown_tracks_from_peak(self, sim):
        # Win first (new peak)
        sig1 = FakeSniperSignal(symbol="HYPE", side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig1)
        sim.check_positions({"HYPE": 104.0})
        peak = sim._equity

        # Then lose
        sig2 = FakeSniperSignal(symbol="BTC", side="BUY", entry=50000.0, sl=49000.0, tp_scalp=51500.0)
        sim.on_signal(sig2)
        sim.check_positions({"BTC": 48000.0})

        expected_dd = (peak - sim._equity) / peak * 100
        assert abs(sim._max_drawdown - expected_dd) < 0.1


class TestNoPrice:
    """Test behavior when price data is unavailable."""

    def test_missing_price_keeps_position_open(self, sim):
        sig = FakeSniperSignal(symbol="HYPE")
        sim.on_signal(sig)

        # No HYPE price in dict
        closed = sim.check_positions({"BTC": 50000.0})
        assert len(closed) == 0
        assert len(sim._open_positions) == 1

    def test_empty_prices_no_crash(self, sim):
        sig = FakeSniperSignal()
        sim.on_signal(sig)
        closed = sim.check_positions({})
        assert len(closed) == 0
