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
    """Test take profit triggers correct closure.

    With tiered exits enabled (default), positions at >= 2R close via
    tiered_3R before the tp_scalp check fires. These tests verify:
    - Tiered exits produce correct PnL
    - With tiered exits disabled, tp_scalp still works as before
    """

    def test_buy_tp_scalp_hit_tiered(self, sim):
        """At +2R, all 3 tranches fire — exit reason is tiered_3R."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        # Price at 104 = +2.0R (risk=2, gain=4)
        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "tiered_3R"
        assert trade.result == "WIN"
        assert trade.pnl_usd > 0
        assert trade.num_tranches_hit == 3
        assert sim._wins == 1

    def test_buy_tp_scalp_hit_no_tiers(self, sim, monkeypatch):
        """With tiered exits disabled, tp_scalp fires as before."""
        import manual.simulator as sim_mod
        monkeypatch.setattr(sim_mod, "TIERED_EXITS_ENABLED", False)

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

    def test_sell_tp_scalp_hit_tiered(self, sim):
        """SELL at +2R fires all 3 tranches."""
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=97.0
        )
        sim.on_signal(sig)

        # Price at 96 = +2.0R for SELL (risk=2, gain=4)
        closed = sim.check_positions({"HYPE": 96.0})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "tiered_3R"
        assert trade.result == "WIN"
        assert trade.num_tranches_hit == 3

    def test_sell_tp_scalp_hit_no_tiers(self, sim, monkeypatch):
        """With tiered exits disabled, SELL tp_scalp fires as before."""
        import manual.simulator as sim_mod
        monkeypatch.setattr(sim_mod, "TIERED_EXITS_ENABLED", False)

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

    def test_tp_profit_amount_correct_tiered(self, sim):
        """With tiered exits, total PnL equals sum of all tranche PnLs."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        # Price at 105 = +2.5R → all 3 tranches fire at this price
        closed = sim.check_positions({"HYPE": 105.0})
        trade = closed[0]

        # All tranches close at same price (105), so total PnL = full position * 5%
        expected_pnl = position_size * (105.0 - 100.0) / 100.0
        assert abs(trade.pnl_usd - expected_pnl) < 0.01

    def test_tp_profit_amount_correct_no_tiers(self, sim, monkeypatch):
        """With tiered exits disabled, PnL math uses tp_scalp price."""
        import manual.simulator as sim_mod
        monkeypatch.setattr(sim_mod, "TIERED_EXITS_ENABLED", False)

        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        closed = sim.check_positions({"HYPE": 105.0})
        trade = closed[0]

        expected_pnl = position_size * (103.0 - 100.0) / 100.0
        assert abs(trade.pnl_usd - expected_pnl) < 0.01


class TestTimeStop:
    """Test 12-hour time stop (optimal per edge study: +4.5R net)."""

    def test_time_stop_closes_after_12h(self, sim):
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (13 * 3600)

        closed = sim.check_positions({"HYPE": 100.5})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "time_stop"
        assert trade.exit_price == 100.5
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

    def test_no_close_before_6h(self, sim):
        """Position at 6h should NOT be closed — within 12h window."""
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
        # Allow tiny floating point difference from incremental tranche booking
        assert abs(closed[0].equity_at_close - sim._equity) < 0.01

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


class TestTimeStopBehavior:
    """Test time-stop behavior — 12h optimal per edge study.

    Key finding: 12h time stop is optimal at +4.5R net.
    - All losers hit SL within 5 bars naturally
    - Slow resolvers still get time to work (12h)
    - 24h was diminishing returns (+2.4R vs +4.5R at 12h)
    """

    def test_position_held_at_4_hours(self, sim):
        """Position at 4h should NOT be closed — let slow winners ride."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (4 * 3600)

        closed = sim.check_positions({"HYPE": 100.2})
        assert len(closed) == 0  # Still open — slow winners need time

    def test_position_held_at_6_hours(self, sim):
        """Position at 6h should still be held within 12h window."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (6 * 3600)

        closed = sim.check_positions({"HYPE": 100.5})
        assert len(closed) == 0  # Still open

    def test_12h_stop_closes(self, sim):
        """12h time stop closes position."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (13 * 3600)

        closed = sim.check_positions({"HYPE": 100.5})
        assert len(closed) == 1
        assert closed[0].exit_reason == "time_stop"

    def test_sl_still_triggers_during_hold(self, sim):
        """SL should still trigger even during extended hold."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (8 * 3600)

        closed = sim.check_positions({"HYPE": 97.0})
        assert len(closed) == 1
        assert "sl" in closed[0].exit_reason.lower()

    def test_tp_still_triggers_during_hold(self, sim):
        """TP or tiered exit should still trigger during extended hold."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        sim._open_positions[0].opened_at = time.time() - (8 * 3600)

        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        # With tiered exits, this closes via tiered_3R; without, via tp_scalp
        assert closed[0].exit_reason in ("tp_scalp", "tiered_3R")


class TestBreakEvenStop:
    """Test dynamic SL: break-even at +0.5% from entry."""

    def test_buy_breakeven_triggers(self, sim):
        """After price reaches +1.0%, SL should move to entry (100.0)."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price moves to +1.1% — triggers break-even
        sim.check_positions({"HYPE": 101.1})
        assert pos.current_sl == 100.0  # SL moved to entry

    def test_buy_breakeven_not_triggered_below_threshold(self, sim):
        """At +0.8% gain, SL should NOT move — below 1.0% threshold."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        sim.check_positions({"HYPE": 100.8})
        assert pos.current_sl == 0.0  # No change

    def test_sell_breakeven_triggers(self, sim):
        """SELL side: after price drops 1.0%, SL moves to entry."""
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=96.0
        )
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price drops to 98.9 = -1.1% in our favor
        sim.check_positions({"HYPE": 98.9})
        assert pos.current_sl == 100.0  # SL moved to entry

    def test_breakeven_closes_on_reversal(self, sim):
        """After BE is set, a reversal back to entry closes the position."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)

        # First: price goes up to trigger BE
        sim.check_positions({"HYPE": 101.1})
        assert sim._open_positions[0].current_sl == 100.0

        # Then: price reverses back to entry — should close at BE
        closed = sim.check_positions({"HYPE": 99.9})
        assert len(closed) == 1
        assert closed[0].exit_reason == "sl_dynamic"
        assert closed[0].exit_price == 100.0


class TestTrailingStop:
    """Test dynamic trailing stop: after +1.5%, trail SL at 55% of gain."""

    def test_buy_trail_starts_at_1pct(self, sim):
        """At +2.0% gain, SL should trail at ~1.1% (55% of gain)."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price at +2.0% → trail at 55% of gain = 1.1%
        sim.check_positions({"HYPE": 102.0})
        expected_sl = 100.0 + (100.0 * 0.020 * 0.55)  # entry + 55% of 2.0% gain
        assert abs(pos.current_sl - expected_sl) < 0.01

    def test_trail_ratchets_up(self, sim):
        """Trail SL should only move up, never down."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price goes to +2.0%
        sim.check_positions({"HYPE": 102.0})
        sl_at_2pct = pos.current_sl

        # Price drops to +1.2% — SL should NOT decrease
        sim.check_positions({"HYPE": 101.2})
        assert pos.current_sl >= sl_at_2pct

    def test_trail_closes_on_pullback(self, sim):
        """After trailing up, a pullback to trail level closes position."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        # Price goes to +2.5% → trail at +1.25% = 101.25
        sim.check_positions({"HYPE": 102.5})
        trail_sl = sim._open_positions[0].current_sl
        assert trail_sl > 101.0  # should be around 101.25

        # Price drops below trail
        closed = sim.check_positions({"HYPE": trail_sl - 0.1})
        assert len(closed) == 1
        assert closed[0].exit_reason == "sl_dynamic"
        assert closed[0].pnl_usd > 0  # still a profitable exit

    def test_sell_trail(self, sim):
        """SELL side trailing: SL moves down as price drops."""
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=96.0
        )
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price drops 2.0% in our favor → trail at 55% of 2.0% = 1.1% from entry
        sim.check_positions({"HYPE": 98.0})
        expected_sl = 100.0 - (100.0 * 0.020 * 0.55)
        assert abs(pos.current_sl - expected_sl) < 0.01

    def test_tp_still_takes_priority(self, sim):
        """TP hit should still close even with trailing active."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        # Price jumps straight to TP — at 103.5, R=1.75, so tranches 1+2 fire
        # then tp_scalp fires for remaining 34%
        closed = sim.check_positions({"HYPE": 103.5})
        assert len(closed) == 1
        assert closed[0].exit_reason == "tp_scalp"


class TestTieredExits:
    """Test the tiered R-multiple exit system.

    Research proved tiered exits convert negative Kelly to positive:
    - Full exit at TP1: -16.33% PnL, 40% WR, Kelly=-31.8%
    - Tiered 33/33/34:  +1.27% PnL, 77% WR, Kelly=+6.0%
    """

    def test_tranche1_at_half_r(self, sim):
        """At +0.5R, 33% of position closes and SL moves to BE."""
        # entry=100, sl=98, risk=2. +0.5R = price 101.0
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        initial_equity = sim._equity

        closed = sim.check_positions({"HYPE": 101.0})
        assert len(closed) == 0  # position still open
        assert pos.tranches_closed == 1
        assert abs(pos.remaining_size - 0.67) < 0.01
        assert pos.current_sl == 100.0  # SL moved to BE
        assert sim._equity > initial_equity  # tranche PnL booked
        assert len(pos.tranche_pnl) == 1
        assert pos.tranche_pnl[0] > 0

    def test_tranche2_at_1r(self, sim):
        """At +1.0R, second 33% closes."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Price reaches +1.0R = 102.0
        closed = sim.check_positions({"HYPE": 102.0})
        assert len(closed) == 0
        assert pos.tranches_closed == 2
        assert abs(pos.remaining_size - 0.34) < 0.01
        assert len(pos.tranche_pnl) == 2

    def test_tranche3_at_2r_full_close(self, sim):
        """At +2.0R, final 34% closes — position fully closed."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)

        # Price reaches +2.0R = 104.0
        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "tiered_3R"
        assert trade.result == "WIN"
        assert trade.num_tranches_hit == 3
        assert trade.max_r_achieved >= 2.0
        assert len(trade.tranche_details) == 3
        assert len(sim._open_positions) == 0

    def test_tiered_pnl_math_correct(self, sim):
        """Total PnL from tiered exit equals expected amount."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=105.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        # All 3 tranches fire at +2.0R (price=104, 4% gain)
        closed = sim.check_positions({"HYPE": 104.0})
        trade = closed[0]

        # Each tranche closes at same price → total = full position * 4%
        expected_total = position_size * 0.04
        assert abs(trade.pnl_usd - expected_total) < 0.01

    def test_gradual_tranche_exits(self, sim):
        """Tranches fire across multiple price checks."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        # Step 1: +0.5R (price=101) → tranche 1
        sim.check_positions({"HYPE": 101.0})
        assert pos.tranches_closed == 1
        t1_pnl = pos.tranche_pnl[0]
        expected_t1 = position_size * 0.33 * 0.01  # 33% * 1% gain
        assert abs(t1_pnl - expected_t1) < 0.01

        # Step 2: +1.0R (price=102) → tranche 2
        sim.check_positions({"HYPE": 102.0})
        assert pos.tranches_closed == 2
        t2_pnl = pos.tranche_pnl[1]
        expected_t2 = position_size * 0.33 * 0.02  # 33% * 2% gain
        assert abs(t2_pnl - expected_t2) < 0.01

        # Step 3: +2.0R (price=104) → tranche 3 and full close
        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        trade = closed[0]
        t3_pnl = pos.tranche_pnl[2]
        expected_t3 = position_size * 0.34 * 0.04  # 34% * 4% gain
        assert abs(t3_pnl - expected_t3) < 0.01

        total_pnl = t1_pnl + t2_pnl + t3_pnl
        assert abs(trade.pnl_usd - total_pnl) < 0.01

    def test_sl_closes_remaining_after_tranche1(self, sim):
        """SL hit after tranche 1 closes remaining 67% — net PnL includes tranche profit."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        # Tranche 1 fires at +0.5R
        sim.check_positions({"HYPE": 101.0})
        assert pos.tranches_closed == 1
        tranche1_pnl = pos.tranche_pnl[0]

        # Price reverses to BE (SL was moved to entry=100.0)
        closed = sim.check_positions({"HYPE": 99.5})
        assert len(closed) == 1
        trade = closed[0]
        assert trade.exit_reason == "sl_dynamic"

        # Remaining 67% closes at entry (BE) → 0 PnL for remaining
        # But tranche 1 was profitable, so total should be positive
        # remaining_pnl = 0.67 * position_size * (100-100)/100 = 0
        assert trade.pnl_usd > 0  # net positive due to tranche 1 profit
        assert abs(trade.pnl_usd - tranche1_pnl) < 0.01
        assert trade.num_tranches_hit == 1
        assert trade.result == "WIN"

    def test_sl_closes_remaining_after_tranche2(self, sim):
        """SL hit after 2 tranches — net PnL includes both tranche profits."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Tranches 1 and 2 fire
        sim.check_positions({"HYPE": 102.0})
        assert pos.tranches_closed == 2
        tranche_sum = sum(pos.tranche_pnl)

        # Price reverses back to entry (BE)
        closed = sim.check_positions({"HYPE": 99.9})
        trade = closed[0]
        assert trade.exit_reason == "sl_dynamic"
        assert trade.pnl_usd > 0  # profitable due to locked-in tranches
        assert trade.num_tranches_hit == 2

    def test_full_sl_hit_no_tranches(self, sim):
        """SL hit without any tranche fires — full loss on whole position."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]
        position_size = pos.position_size_usd

        # Price goes straight to SL (R = -1.0)
        closed = sim.check_positions({"HYPE": 97.0})
        trade = closed[0]
        assert trade.exit_reason == "sl"
        assert trade.result == "LOSS"
        # Full position size * -2% stop
        expected_loss = position_size * (98.0 - 100.0) / 100.0
        assert abs(trade.pnl_usd - expected_loss) < 0.01
        assert trade.num_tranches_hit == 0

    def test_sell_side_tiered_exits(self, sim):
        """Tiered exits work correctly for SELL positions."""
        # entry=100, sl=102, risk=2. +0.5R for SELL = price 99.0
        sig = FakeSniperSignal(
            side="SELL", entry=100.0, sl=102.0, tp_scalp=95.0
        )
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # +0.5R = price 99.0 → tranche 1
        sim.check_positions({"HYPE": 99.0})
        assert pos.tranches_closed == 1
        assert pos.current_sl == 100.0  # BE

        # +1.0R = price 98.0 → tranche 2
        sim.check_positions({"HYPE": 98.0})
        assert pos.tranches_closed == 2

        # +2.0R = price 96.0 → tranche 3, full close
        closed = sim.check_positions({"HYPE": 96.0})
        assert len(closed) == 1
        assert closed[0].exit_reason == "tiered_3R"
        assert closed[0].result == "WIN"
        assert closed[0].num_tranches_hit == 3

    def test_tiered_disabled_falls_through_to_tp(self, sim, monkeypatch):
        """With TIERED_EXITS_ENABLED=false, TP fires as normal."""
        import manual.simulator as sim_mod
        monkeypatch.setattr(sim_mod, "TIERED_EXITS_ENABLED", False)

        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=103.0)
        sim.on_signal(sig)

        closed = sim.check_positions({"HYPE": 104.0})
        assert len(closed) == 1
        assert closed[0].exit_reason == "tp_scalp"
        assert closed[0].num_tranches_hit == 0

    def test_time_stop_after_tranche1_net_positive(self, sim):
        """Time stop after tranche 1 — net PnL should include tranche profit."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # Tranche 1 at +0.5R
        sim.check_positions({"HYPE": 101.0})
        assert pos.tranches_closed == 1

        # Simulate time stop at flat price (entry level)
        pos.opened_at = time.time() - (13 * 3600)
        closed = sim.check_positions({"HYPE": 100.0})
        assert len(closed) == 1
        trade = closed[0]
        assert "time_stop" in trade.exit_reason
        # Remaining 67% at entry = 0 PnL, but tranche 1 was +0.5R on 33%
        assert trade.pnl_usd > 0
        assert trade.num_tranches_hit == 1

    def test_tranche_details_in_trade_log(self, sim):
        """Trade log includes tranche breakdown."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)

        closed = sim.check_positions({"HYPE": 104.0})
        trade = closed[0]
        details = trade.tranche_details
        assert len(details) == 3
        assert details[0]["tranche"] == 1
        assert details[0]["r_target"] == 0.5
        assert details[0]["size_pct"] == 0.33
        assert details[1]["tranche"] == 2
        assert details[1]["r_target"] == 1.0
        assert details[2]["tranche"] == 3
        assert details[2]["r_target"] == 2.0

    def test_below_half_r_no_tranche(self, sim):
        """Price at +0.4R should not trigger any tranche."""
        sig = FakeSniperSignal(side="BUY", entry=100.0, sl=98.0, tp_scalp=106.0)
        sim.on_signal(sig)
        pos = sim._open_positions[0]

        # +0.4R = entry + 0.4*2 = 100.8
        sim.check_positions({"HYPE": 100.8})
        assert pos.tranches_closed == 0
        assert pos.remaining_size == 1.0
        assert len(pos.tranche_pnl) == 0
