"""
Tests for the Post-Trade Learning System (TradeLearner).

Covers:
- Setup type classification from trade metadata
- R-multiple computation
- Win/loss diagnosis (fast SL, chop SL, TP hit, time stop)
- Per-setup-type performance tracking
- Immediate adjustments after wins (risk boost, system-in-sync)
- Immediate adjustments after losses (trigger widening, counter-trend penalty)
- Setup weight calculation for anticipatory entries
- Entry map regen flagging
- State persistence (save/load round-trip)
- Wiring into SniperSimulator._close_position
"""

import json
import os
import tempfile
import time
import pytest
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch, MagicMock


# ── Fake trade objects ────────────────────────────────────────────────

@dataclass
class FakeTrade:
    """Mimics SimTrade fields for testing."""
    trade_id: str = "SIM-0001"
    symbol: str = "HYPE"
    side: str = "BUY"
    tier: str = "PREMIUM"
    entry: float = 40.0
    exit_price: float = 41.5
    sl: float = 39.0
    tp_scalp: float = 42.0
    leverage: float = 5.0
    position_size_usd: float = 500.0
    qty: float = 12.5
    risk_amount: float = 12.5   # 500 * (40-39)/40 = 12.5
    equity_at_open: float = 100.0
    equity_at_close: float = 118.75
    pnl_usd: float = 18.75     # 500 * (41.5-40)/40
    pnl_pct: float = 18.75
    result: str = "WIN"
    exit_reason: str = "tp_scalp"
    hold_time_s: float = 14400.0   # 4 hours
    hold_time_hours: float = 4.0
    opened_at: str = "2026-03-26T00:00:00+00:00"
    closed_at: str = "2026-03-26T04:00:00+00:00"
    confidence: float = 80.0
    num_agree: int = 2
    regime: str = "trend"
    setup_type: str = ""
    source: str = ""


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Redirect learner data to temp directory."""
    data_dir = str(tmp_path / "data" / "manual")
    os.makedirs(data_dir, exist_ok=True)
    with patch("manual.trade_learner._DATA_DIR", data_dir), \
         patch("manual.trade_learner._LEARNER_PATH", os.path.join(data_dir, "trade_learner_state.json")), \
         patch("manual.trade_learner._LESSONS_PATH", os.path.join(data_dir, "trade_lessons.jsonl")):
        yield data_dir


@pytest.fixture
def learner(tmp_data_dir):
    from manual.trade_learner import TradeLearner
    return TradeLearner()


# ── Setup Classification ─────────────────────────────────────────────

class TestSetupClassification:
    def test_classify_from_setup_type_field(self, learner):
        trade = FakeTrade(setup_type="bb_lower_bounce")
        assert learner._classify_setup(trade) == "bb_lower_bounce"

    def test_classify_from_source_field(self, learner):
        trade = FakeTrade(source="BB_Lower")
        assert learner._classify_setup(trade) == "bb_lower_bounce"

    def test_classify_from_source_ema(self, learner):
        trade = FakeTrade(source="EMA20")
        assert learner._classify_setup(trade) == "ema_pullback"

    def test_classify_fallback_symbol_side(self, learner):
        trade = FakeTrade(symbol="HYPE", side="BUY")
        assert learner._classify_setup(trade) == "hype_buy"

    def test_classify_resistance_rejection(self, learner):
        trade = FakeTrade(source="Swing_High")
        assert learner._classify_setup(trade) == "resistance_rejection"


# ── R-Multiple Computation ───────────────────────────────────────────

class TestRMultiple:
    def test_r_multiple_win(self, learner):
        trade = FakeTrade(pnl_usd=12.5, risk_amount=12.5)
        assert learner._compute_r_multiple(trade) == 1.0

    def test_r_multiple_loss(self, learner):
        trade = FakeTrade(pnl_usd=-12.5, risk_amount=12.5)
        assert learner._compute_r_multiple(trade) == -1.0

    def test_r_multiple_big_win(self, learner):
        trade = FakeTrade(pnl_usd=25.0, risk_amount=12.5)
        assert learner._compute_r_multiple(trade) == 2.0

    def test_r_multiple_zero_risk_fallback(self, learner):
        # risk_amount=0 triggers fallback to SL distance calculation
        trade = FakeTrade(
            risk_amount=0, entry=40.0, sl=39.0,
            position_size_usd=500.0, pnl_usd=12.5
        )
        r = learner._compute_r_multiple(trade)
        assert r == pytest.approx(1.0, abs=0.01)

    def test_r_multiple_completely_missing(self, learner):
        trade = FakeTrade(risk_amount=0, entry=0, sl=0, position_size_usd=0, pnl_usd=10)
        assert learner._compute_r_multiple(trade) == 0.0


# ── Diagnosis ────────────────────────────────────────────────────────

class TestDiagnosis:
    def test_tp_hit_win(self, learner):
        trade = FakeTrade(result="WIN", exit_reason="tp_scalp", hold_time_hours=4.0)
        diag, code = learner._diagnose(trade, 1.5)
        assert code == "tp_hit"
        assert "TP hit" in diag

    def test_trailing_win(self, learner):
        trade = FakeTrade(result="WIN", exit_reason="sl_dynamic", pnl_usd=5.0)
        diag, code = learner._diagnose(trade, 0.5)
        assert code == "trailing_win"

    def test_time_stop_win(self, learner):
        trade = FakeTrade(result="WIN", exit_reason="time_stop", pnl_usd=3.0)
        diag, code = learner._diagnose(trade, 0.3)
        assert code == "time_stop_win"
        assert "TP was too far" in diag

    def test_fast_sl_loss(self, learner):
        # SL hit within 2 hours (7200s) — entry was bad
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=3600.0, hold_time_hours=1.0,
            pnl_usd=-12.5
        )
        diag, code = learner._diagnose(trade, -1.0)
        assert code == "fast_sl"
        assert "FAST" in diag

    def test_chop_sl_loss(self, learner):
        # SL hit after 6 hours of chop — setup was right, market wasn't ready
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=21600.0, hold_time_hours=6.0,
            pnl_usd=-12.5
        )
        diag, code = learner._diagnose(trade, -1.0)
        assert code == "chop_sl"
        assert "chop" in diag

    def test_normal_sl_loss(self, learner):
        # SL hit at 3 hours — normal stop-out
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=10800.0, hold_time_hours=3.0,
            pnl_usd=-12.5
        )
        diag, code = learner._diagnose(trade, -1.0)
        assert code == "normal_sl"

    def test_time_stop_loss(self, learner):
        trade = FakeTrade(
            result="LOSS", exit_reason="time_stop",
            hold_time_s=43200.0, hold_time_hours=12.0,
            pnl_usd=-3.0
        )
        diag, code = learner._diagnose(trade, -0.25)
        assert code == "time_stop_loss"


# ── Setup Stats Tracking ────────────────────────────────────────────

class TestSetupStats:
    def test_win_updates_stats(self, learner):
        trade = FakeTrade(result="WIN", exit_reason="tp_scalp")
        learner.on_trade_close(trade)
        stats = learner._setup_stats.get("hype_buy")
        assert stats is not None
        assert stats.wins == 1
        assert stats.losses == 0
        assert stats.total_r > 0

    def test_loss_updates_stats(self, learner):
        trade = FakeTrade(result="LOSS", exit_reason="sl", pnl_usd=-12.5)
        learner.on_trade_close(trade)
        stats = learner._setup_stats.get("hype_buy")
        assert stats is not None
        assert stats.wins == 0
        assert stats.losses == 1
        assert stats.total_r < 0

    def test_fast_sl_tracked(self, learner):
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=3600.0, pnl_usd=-12.5
        )
        learner.on_trade_close(trade)
        stats = learner._setup_stats.get("hype_buy")
        assert stats.fast_sl_count == 1

    def test_chop_sl_tracked(self, learner):
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=21600.0, pnl_usd=-12.5
        )
        learner.on_trade_close(trade)
        stats = learner._setup_stats.get("hype_buy")
        assert stats.chop_sl_count == 1

    def test_multiple_trades_accumulate(self, learner):
        for i in range(3):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="WIN", exit_reason="tp_scalp",
                pnl_usd=12.5, risk_amount=12.5
            ))
        stats = learner._setup_stats["hype_buy"]
        assert stats.wins == 3
        assert stats.total_trades == 3
        assert stats.win_rate == 1.0


# ── Adjustments After Win ───────────────────────────────────────────

class TestWinAdjustments:
    def test_single_win_no_sync(self, learner):
        learner.on_trade_close(FakeTrade(result="WIN"))
        assert not learner.system_in_sync
        assert learner._consecutive_wins == 1

    def test_two_wins_system_in_sync(self, learner):
        learner.on_trade_close(FakeTrade(trade_id="SIM-0001", result="WIN"))
        learner.on_trade_close(FakeTrade(trade_id="SIM-0002", result="WIN"))
        assert learner.system_in_sync
        assert learner._consecutive_wins == 2
        # Risk should be boosted
        assert learner.get_risk_pct() > 0.02

    def test_risk_boost_capped(self, learner):
        from manual.trade_learner import MAX_RISK_PCT
        for i in range(10):
            learner.on_trade_close(FakeTrade(trade_id=f"SIM-{i:04d}", result="WIN"))
        assert learner.get_risk_pct() <= MAX_RISK_PCT


# ── Adjustments After Loss ──────────────────────────────────────────

class TestLossAdjustments:
    def test_loss_resets_risk(self, learner):
        # Build up a win streak first
        learner.on_trade_close(FakeTrade(trade_id="SIM-0001", result="WIN"))
        learner.on_trade_close(FakeTrade(trade_id="SIM-0002", result="WIN"))
        assert learner.get_risk_pct() > 0.02
        # Now lose
        learner.on_trade_close(FakeTrade(trade_id="SIM-0003", result="LOSS", pnl_usd=-12.5))
        assert learner.get_risk_pct() == 0.02  # Back to base

    def test_loss_breaks_sync(self, learner):
        learner.on_trade_close(FakeTrade(trade_id="SIM-0001", result="WIN"))
        learner.on_trade_close(FakeTrade(trade_id="SIM-0002", result="WIN"))
        assert learner.system_in_sync
        learner.on_trade_close(FakeTrade(trade_id="SIM-0003", result="LOSS", pnl_usd=-12.5))
        assert not learner.system_in_sync

    def test_fast_sl_widens_trigger(self, learner):
        trade = FakeTrade(
            result="LOSS", exit_reason="sl",
            hold_time_s=3600.0, pnl_usd=-12.5
        )
        learner.on_trade_close(trade)
        adj = learner.get_trigger_zone_adjustment("hype_buy")
        assert adj > 0

    def test_multiple_fast_sl_accumulates_widening(self, learner):
        for i in range(3):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="LOSS", exit_reason="sl",
                hold_time_s=3600.0, pnl_usd=-12.5
            ))
        adj = learner.get_trigger_zone_adjustment("hype_buy")
        assert adj >= 0.006  # 3 * 0.002

    def test_loss_flags_entry_map_regen(self, learner):
        trade = FakeTrade(result="LOSS", pnl_usd=-12.5)
        learner.on_trade_close(trade)
        assert learner.needs_entry_map_regen()
        # Should reset after check
        assert not learner.needs_entry_map_regen()

    def test_counter_trend_penalty_increases(self, learner):
        from manual.trade_learner import COUNTER_TREND_PENALTY_BASE
        initial = learner.get_counter_trend_penalty()
        assert initial == COUNTER_TREND_PENALTY_BASE

        # Counter-trend loss: BUY in a trending market that lost (price went down)
        trade = FakeTrade(
            result="LOSS", regime="trend", side="BUY",
            entry=40.0, exit_price=39.0, pnl_usd=-12.5
        )
        learner.on_trade_close(trade)
        assert learner.get_counter_trend_penalty() < initial


# ── Setup Weights ────────────────────────────────────────────────────

class TestSetupWeights:
    def test_no_data_neutral_weight(self, learner):
        weights = learner.get_setup_weights()
        assert len(weights) == 0  # No setups tracked yet

    def test_winning_setup_boosted(self, learner):
        for i in range(5):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="WIN", pnl_usd=12.5, risk_amount=12.5
            ))
        weights = learner.get_setup_weights()
        assert "hype_buy" in weights
        assert weights["hype_buy"] > 1.0  # Boosted

    def test_losing_setup_penalized(self, learner):
        for i in range(5):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="LOSS", exit_reason="sl",
                hold_time_s=10800.0, pnl_usd=-12.5, risk_amount=12.5
            ))
        weights = learner.get_setup_weights()
        assert "hype_buy" in weights
        assert weights["hype_buy"] < 1.0  # Penalized

    def test_few_trades_neutral(self, learner):
        # Only 1 trade — not enough data
        learner.on_trade_close(FakeTrade(result="WIN"))
        weights = learner.get_setup_weights()
        assert weights.get("hype_buy", 1.0) == 1.0

    def test_weight_clamped(self, learner):
        for i in range(10):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="WIN", pnl_usd=50.0, risk_amount=12.5
            ))
        weights = learner.get_setup_weights()
        assert weights["hype_buy"] <= 1.5  # Upper clamp

    def test_fast_sl_heavy_penalty(self, learner):
        """Setups where >50% of trades hit SL fast get extra penalty."""
        for i in range(4):
            learner.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="LOSS", exit_reason="sl",
                hold_time_s=3600.0, pnl_usd=-12.5, risk_amount=12.5
            ))
        weights = learner.get_setup_weights()
        # All 4 trades are fast SL — should be heavily penalized
        assert weights["hype_buy"] <= 0.5


# ── State Persistence ────────────────────────────────────────────────

class TestPersistence:
    def test_save_load_roundtrip(self, tmp_data_dir):
        from manual.trade_learner import TradeLearner
        learner1 = TradeLearner()

        # Generate some data
        for i in range(3):
            learner1.on_trade_close(FakeTrade(
                trade_id=f"SIM-{i:04d}",
                result="WIN" if i < 2 else "LOSS",
                pnl_usd=12.5 if i < 2 else -12.5,
                exit_reason="tp_scalp" if i < 2 else "sl",
                hold_time_s=10800.0,
            ))

        # Create new learner — should load state
        learner2 = TradeLearner()
        assert "hype_buy" in learner2._setup_stats
        stats = learner2._setup_stats["hype_buy"]
        assert stats.wins == 2
        assert stats.losses == 1
        assert learner2._consecutive_losses == 1

    def test_lessons_logged_to_jsonl(self, tmp_data_dir):
        from manual.trade_learner import TradeLearner, _LESSONS_PATH
        learner = TradeLearner()
        learner.on_trade_close(FakeTrade(result="WIN"))

        assert os.path.exists(_LESSONS_PATH)
        with open(_LESSONS_PATH, "r") as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["result"] == "WIN"
        assert data["trade_id"] == "SIM-0001"
        assert data["setup_type"] == "hype_buy"


# ── Lesson Content ───────────────────────────────────────────────────

class TestLessonContent:
    def test_lesson_has_all_fields(self, learner):
        trade = FakeTrade(result="WIN", exit_reason="tp_scalp")
        lesson = learner.on_trade_close(trade)

        assert lesson.trade_id == "SIM-0001"
        assert lesson.symbol == "HYPE"
        assert lesson.side == "BUY"
        assert lesson.setup_type == "hype_buy"
        assert lesson.result == "WIN"
        assert lesson.r_multiple > 0
        assert lesson.diagnosis_code == "tp_hit"
        assert "recorded_win" in lesson.adjustment_applied
        assert lesson.hold_time_hours == 4.0

    def test_lesson_returns_from_on_trade_close(self, learner):
        from manual.trade_learner import TradeLesson
        trade = FakeTrade(result="LOSS", pnl_usd=-12.5, exit_reason="sl", hold_time_s=10800.0)
        lesson = learner.on_trade_close(trade)
        assert isinstance(lesson, TradeLesson)
        assert lesson.result == "LOSS"


# ── Status Output ────────────────────────────────────────────────────

class TestStatus:
    def test_get_status_structure(self, learner):
        learner.on_trade_close(FakeTrade(result="WIN"))
        status = learner.get_status()

        assert "setup_stats" in status
        assert "setup_weights" in status
        assert "risk_pct_override" in status
        assert "counter_trend_penalty" in status
        assert "consecutive_wins" in status
        assert "system_in_sync" in status


# ── Simulator Integration ────────────────────────────────────────────

class TestSimulatorIntegration:
    """Test that TradeLearner is wired into SniperSimulator._close_position."""

    def test_simulator_has_trade_learner(self, tmp_data_dir):
        """SniperSimulator should attach a TradeLearner on init."""
        with patch("manual.simulator._DATA_DIR", tmp_data_dir), \
             patch("manual.simulator._TRADES_PATH", os.path.join(tmp_data_dir, "sim_trades.jsonl")), \
             patch("manual.simulator._STATUS_PATH", os.path.join(tmp_data_dir, "sim_status.json")):
            from manual.simulator import SniperSimulator
            sim = SniperSimulator(starting_equity=100.0)
            assert sim._trade_learner is not None

    def test_close_position_calls_learner(self, tmp_data_dir):
        """When _close_position is called, trade_learner.on_trade_close should fire."""
        with patch("manual.simulator._DATA_DIR", tmp_data_dir), \
             patch("manual.simulator._TRADES_PATH", os.path.join(tmp_data_dir, "sim_trades.jsonl")), \
             patch("manual.simulator._STATUS_PATH", os.path.join(tmp_data_dir, "sim_status.json")):
            from manual.simulator import SniperSimulator, SimPosition
            sim = SniperSimulator(starting_equity=100.0)

            # Mock the trade learner
            mock_learner = MagicMock()
            sim._trade_learner = mock_learner

            # Create a position
            pos = SimPosition(
                trade_id="SIM-TEST",
                symbol="HYPE",
                side="BUY",
                tier="PREMIUM",
                entry=40.0,
                sl=39.0,
                tp_scalp=42.0,
                tp_swing=44.0,
                leverage=5.0,
                risk_pct=0.02,
                position_size_usd=500.0,
                qty=12.5,
                risk_amount=12.5,
                pnl_scalp=25.0,
                loss_amount=12.5,
                equity_at_open=100.0,
                opened_at=time.time() - 3600,
                opened_at_iso="2026-03-26T00:00:00+00:00",
                confidence=80.0,
                num_agree=2,
                regime="trend",
            )

            sim._close_position(pos, 42.0, "tp_scalp", time.time())
            mock_learner.on_trade_close.assert_called_once()
