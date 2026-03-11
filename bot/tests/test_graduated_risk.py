"""
Tests for graduated drawdown risk reduction and regime-aware feedback.

Tests:
- GraduatedRiskManager: drawdown bands, modifiers, leverage/risk application
- RegimeFeedbackManager: per-regime tracking, adaptive parameters, recommendations
"""

import pytest
import json
import tempfile
import os
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.graduated_risk import (
    DrawdownBand, GraduatedRiskManager, DEFAULT_BANDS,
)
from feedback.regime_feedback import (
    RegimeStats, RegimeFeedbackManager, REGIME_PRESETS,
)


# ==================== GraduatedRiskManager Tests ====================

class TestDrawdownBands:
    """Test the drawdown band definitions."""

    def test_default_bands_cover_full_range(self):
        """Bands should cover 0% to 100% drawdown."""
        assert DEFAULT_BANDS[0].dd_min == 0.0
        assert DEFAULT_BANDS[-1].dd_max == 1.0

    def test_default_bands_are_contiguous(self):
        """Each band's max should equal the next band's min."""
        for i in range(len(DEFAULT_BANDS) - 1):
            assert DEFAULT_BANDS[i].dd_max == DEFAULT_BANDS[i + 1].dd_min

    def test_risk_decreases_with_drawdown(self):
        """Risk multiplier should decrease as drawdown increases."""
        for i in range(len(DEFAULT_BANDS) - 1):
            assert DEFAULT_BANDS[i].risk_multiplier >= DEFAULT_BANDS[i + 1].risk_multiplier

    def test_leverage_reduction_increases_with_drawdown(self):
        """Leverage reduction should increase as drawdown increases."""
        for i in range(len(DEFAULT_BANDS) - 1):
            assert DEFAULT_BANDS[i].leverage_reduction <= DEFAULT_BANDS[i + 1].leverage_reduction

    def test_circuit_breaker_band_is_zero(self):
        """Circuit breaker band should have 0 risk multiplier."""
        cb = DEFAULT_BANDS[-1]
        assert cb.label == "circuit_breaker"
        assert cb.risk_multiplier == 0.0
        assert cb.leverage_reduction == 1.0


class TestGraduatedRiskManagerBasic:
    """Test basic GraduatedRiskManager functionality."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()

    def test_initial_state(self):
        """New manager should start with zero drawdown."""
        assert self.grm.peak_equity == 0.0
        assert self.grm.current_equity == 0.0
        assert self.grm.consecutive_losses == 0
        assert self.grm.get_drawdown() == 0.0

    def test_update_equity_sets_peak(self):
        """Equity updates should track peak."""
        self.grm.update_equity(10000)
        assert self.grm.peak_equity == 10000
        assert self.grm.current_equity == 10000

        self.grm.update_equity(10500)
        assert self.grm.peak_equity == 10500

    def test_drawdown_calculation(self):
        """Drawdown should be computed correctly."""
        self.grm.update_equity(10000)
        self.grm.update_equity(9500)
        dd = self.grm.get_drawdown()
        assert abs(dd - 0.05) < 1e-6  # 5% drawdown

    def test_peak_resets_on_new_high(self):
        """Drawdown timer should reset on new equity high."""
        self.grm.update_equity(10000)
        self.grm.update_equity(9500)
        assert self.grm.get_drawdown() > 0

        self.grm.update_equity(10100)
        assert self.grm.get_drawdown() == 0.0
        assert self.grm.drawdown_start_time is None

    def test_drawdown_with_zero_peak(self):
        """Drawdown should be 0 when peak is 0."""
        assert self.grm.get_drawdown() == 0.0


class TestGraduatedRiskBandSelection:
    """Test correct band selection based on drawdown."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()
        self.grm.update_equity(10000)

    def test_normal_band(self):
        """0-2% drawdown should be normal band."""
        self.grm.update_equity(9900)  # 1% dd
        band = self.grm.get_band()
        assert band.label == "normal"

    def test_early_warning_band(self):
        """2-3% drawdown should be early warning."""
        self.grm.update_equity(9750)  # 2.5% dd
        band = self.grm.get_band()
        assert band.label == "early_warning"

    def test_caution_band(self):
        """3-5% drawdown should be caution."""
        self.grm.update_equity(9600)  # 4% dd
        band = self.grm.get_band()
        assert band.label == "caution"

    def test_defensive_band(self):
        """5-7% drawdown should be defensive."""
        self.grm.update_equity(9400)  # 6% dd
        band = self.grm.get_band()
        assert band.label == "defensive"

    def test_survival_band(self):
        """7-10% drawdown should be survival."""
        self.grm.update_equity(9200)  # 8% dd
        band = self.grm.get_band()
        assert band.label == "survival"

    def test_circuit_breaker_band(self):
        """10%+ drawdown should be circuit breaker."""
        self.grm.update_equity(8800)  # 12% dd
        band = self.grm.get_band()
        assert band.label == "circuit_breaker"


class TestGraduatedRiskModifiers:
    """Test streak, time, and regime modifiers."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()
        self.grm.update_equity(10000)

    def test_streak_penalty_below_threshold(self):
        """No streak penalty with < 3 consecutive losses."""
        self.grm.record_trade(-50)
        self.grm.record_trade(-50)
        adj = self.grm.get_risk_adjustment()
        assert "streak_penalty" not in adj["modifiers"]

    def test_streak_penalty_at_threshold(self):
        """Streak penalty should activate at 3 consecutive losses."""
        for _ in range(3):
            self.grm.record_trade(-50)
        adj = self.grm.get_risk_adjustment()
        assert "streak_penalty" in adj["modifiers"]
        assert adj["modifiers"]["streak_penalty"] == 0.05  # (3-2) * 0.05

    def test_streak_penalty_grows(self):
        """Streak penalty should grow with more losses."""
        for _ in range(5):
            self.grm.record_trade(-50)
        adj = self.grm.get_risk_adjustment()
        assert abs(adj["modifiers"]["streak_penalty"] - 0.15) < 1e-9  # (5-2) * 0.05

    def test_streak_penalty_capped(self):
        """Streak penalty should be capped at 25%."""
        for _ in range(20):
            self.grm.record_trade(-50)
        adj = self.grm.get_risk_adjustment()
        assert adj["modifiers"]["streak_penalty"] == 0.25

    def test_streak_resets_on_win(self):
        """Consecutive loss streak should reset on a win."""
        for _ in range(5):
            self.grm.record_trade(-50)
        self.grm.record_trade(100)
        assert self.grm.consecutive_losses == 0

    def test_regime_penalty_ranging(self):
        """Ranging regime during drawdown should add 10% penalty."""
        self.grm.update_equity(9700)  # 3% dd (in caution band)
        self.grm.set_regime("range")
        adj = self.grm.get_risk_adjustment()
        assert adj["modifiers"].get("regime_penalty") == 0.10

    def test_regime_penalty_panic(self):
        """Panic regime during drawdown should add 20% penalty."""
        self.grm.update_equity(9700)  # 3% dd
        self.grm.set_regime("panic")
        adj = self.grm.get_risk_adjustment()
        assert adj["modifiers"].get("regime_penalty") == 0.20

    def test_no_regime_penalty_in_normal(self):
        """No regime penalty when drawdown < 2%."""
        self.grm.update_equity(9900)  # 1% dd
        self.grm.set_regime("range")
        adj = self.grm.get_risk_adjustment()
        assert "regime_penalty" not in adj["modifiers"]


class TestGraduatedRiskApplication:
    """Test leverage and risk multiplier application."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()
        self.grm.update_equity(10000)

    def test_apply_leverage_normal(self):
        """Normal band should not reduce leverage."""
        self.grm.update_equity(9900)  # 1% dd
        result = self.grm.apply_to_leverage(5.0)
        assert result == 5.0

    def test_apply_leverage_reduced(self):
        """Caution band should reduce leverage."""
        self.grm.update_equity(9600)  # 4% dd
        result = self.grm.apply_to_leverage(5.0)
        assert result < 5.0
        assert result >= 1.0  # Minimum leverage

    def test_apply_leverage_circuit_breaker(self):
        """Circuit breaker should zero out leverage."""
        self.grm.update_equity(8800)  # 12% dd
        result = self.grm.apply_to_leverage(5.0)
        assert result == 0.0

    def test_apply_risk_multiplier(self):
        """Risk multiplier should be reduced in drawdown."""
        self.grm.update_equity(9600)  # 4% dd, caution band (0.70x)
        result = self.grm.apply_to_risk_multiplier(1.0)
        assert result < 1.0
        assert result > 0.0

    def test_should_skip_circuit_breaker(self):
        """Should skip trade in circuit breaker band."""
        self.grm.update_equity(8800)  # 12% dd
        skip, reason = self.grm.should_skip_trade()
        assert skip is True
        assert "circuit breaker" in reason

    def test_should_not_skip_normal(self):
        """Should not skip trade in normal band."""
        self.grm.update_equity(9900)  # 1% dd
        skip, reason = self.grm.should_skip_trade()
        assert skip is False


class TestGraduatedRiskRecovery:
    """Test recovery factor computation."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()

    def test_recovery_insufficient_data(self):
        """Recovery factor should be neutral with insufficient data."""
        rf = self.grm.get_recovery_factor()
        assert rf == 0.5

    def test_recovery_improving(self):
        """Recovery factor should be > 0.5 when equity is improving."""
        for i in range(10):
            self.grm.update_equity(10000 + i * 50)
        rf = self.grm.get_recovery_factor()
        assert rf > 0.5

    def test_recovery_declining(self):
        """Recovery factor should be < 0.5 when equity is declining."""
        for i in range(10):
            self.grm.update_equity(10000 - i * 50)
        rf = self.grm.get_recovery_factor()
        assert rf < 0.5


class TestGraduatedRiskLLMContext:
    """Test LLM context generation."""

    def setup_method(self):
        self.grm = GraduatedRiskManager()
        self.grm.update_equity(10000)

    def test_no_context_in_normal(self):
        """No LLM context needed when in normal band."""
        self.grm.update_equity(9900)  # 1% dd
        ctx = self.grm.get_llm_context()
        assert ctx == ""

    def test_context_in_drawdown(self):
        """LLM context should include drawdown info."""
        self.grm.update_equity(9600)  # 4% dd
        ctx = self.grm.get_llm_context()
        assert "DRAWDOWN ALERT" in ctx
        assert "caution" in ctx

    def test_context_with_streak(self):
        """LLM context should mention loss streak."""
        self.grm.update_equity(9600)
        for _ in range(4):
            self.grm.record_trade(-50)
        ctx = self.grm.get_llm_context()
        assert "Loss streak" in ctx


class TestGraduatedRiskStatus:
    """Test status reporting."""

    def test_status_has_all_fields(self):
        grm = GraduatedRiskManager()
        grm.update_equity(10000)
        grm.update_equity(9500)
        status = grm.get_status()
        assert "drawdown_pct" in status
        assert "band" in status
        assert "leverage_reduction" in status
        assert "risk_multiplier" in status
        assert "consecutive_losses" in status
        assert "recovery_factor" in status
        assert "peak_equity" in status
        assert "current_equity" in status


# ==================== RegimeFeedbackManager Tests ====================

class TestRegimeStats:
    """Test RegimeStats tracking."""

    def test_initial_state(self):
        """New RegimeStats should have neutral defaults."""
        rs = RegimeStats("trend")
        assert rs.regime == "trend"
        assert rs.total_trades == 0
        assert rs.win_rate == 0.5  # Prior
        assert rs.total_pnl == 0.0

    def test_record_win(self):
        """Recording a win should update stats."""
        rs = RegimeStats("trend")
        rs.record_trade(100.0, 80.0, "regime_trend", hold_hours=2.0)
        assert rs.win_count == 1
        assert rs.loss_count == 0
        assert rs.total_pnl == 100.0
        assert rs.win_rate == 1.0

    def test_record_loss(self):
        """Recording a loss should update stats."""
        rs = RegimeStats("range")
        rs.record_trade(-50.0, 70.0, "regime_trend", hold_hours=1.0)
        assert rs.win_count == 0
        assert rs.loss_count == 1
        assert rs.total_pnl == -50.0
        assert rs.win_rate == 0.0

    def test_profit_factor(self):
        """Profit factor should be gross_win / gross_loss."""
        rs = RegimeStats("trend")
        rs.record_trade(100.0, 80.0, "s1")
        rs.record_trade(200.0, 85.0, "s1")
        rs.record_trade(-50.0, 60.0, "s1")
        assert abs(rs.profit_factor - 6.0) < 1e-6  # 300 / 50

    def test_profit_factor_no_losses(self):
        """Profit factor should be inf with wins and no losses."""
        rs = RegimeStats("trend")
        rs.record_trade(100.0, 80.0, "s1")
        assert rs.profit_factor == float("inf")

    def test_profit_factor_no_trades(self):
        """Profit factor should be 0 with no trades."""
        rs = RegimeStats("trend")
        assert rs.profit_factor == 0.0

    def test_rolling_window(self):
        """Trades list should be capped at 200."""
        rs = RegimeStats("trend")
        for i in range(210):
            rs.record_trade(10.0, 80.0, "s1")
        assert len(rs.trades) == 200

    def test_to_dict_and_from_dict(self):
        """Serialization round-trip should preserve data."""
        rs = RegimeStats("trend")
        rs.record_trade(100.0, 80.0, "s1")
        rs.record_trade(-30.0, 60.0, "s2")

        d = rs.to_dict()
        rs2 = RegimeStats.from_dict(d)
        assert rs2.regime == "trend"
        assert rs2.win_count == 1
        assert rs2.loss_count == 1
        assert rs2.total_pnl == 70.0


class TestRegimeStatsAdaptation:
    """Test adaptive parameter updates."""

    def _make_stats_with_wr(self, regime: str, wins: int, losses: int) -> RegimeStats:
        """Create RegimeStats with a specific win/loss record."""
        rs = RegimeStats(regime)
        for _ in range(wins):
            rs.record_trade(100.0, 80.0, "s1", hold_hours=2.0)
        for _ in range(losses):
            rs.record_trade(-50.0, 60.0, "s1", hold_hours=1.0)
        return rs

    def test_high_wr_lowers_floor(self):
        """High win rate should lower confidence floor."""
        rs = self._make_stats_with_wr("trend", wins=15, losses=2)
        assert rs.confidence_floor < 65.0  # Default is 65

    def test_low_wr_raises_floor(self):
        """Low win rate should raise confidence floor."""
        rs = self._make_stats_with_wr("range", wins=3, losses=15)
        assert rs.confidence_floor > 75.0

    def test_high_wr_increases_risk_mult(self):
        """High win rate should increase risk multiplier."""
        rs = self._make_stats_with_wr("trend", wins=14, losses=2)
        assert rs.risk_multiplier > 1.0

    def test_low_wr_decreases_risk_mult(self):
        """Low win rate should decrease risk multiplier."""
        rs = self._make_stats_with_wr("range", wins=2, losses=15)
        assert rs.risk_multiplier < 1.0

    def test_not_enough_data_no_adaptation(self):
        """With < 5 trades, parameters should not adapt."""
        rs = RegimeStats("trend")
        rs.confidence_floor = 65.0  # Set a known value
        rs.record_trade(100.0, 80.0, "s1")
        rs.record_trade(100.0, 80.0, "s1")
        # Only 2 trades — _update_parameters should skip
        assert rs.confidence_floor == 65.0

    def test_strategy_weights_tracked(self):
        """Strategy weights should be computed from recent trades."""
        rs = RegimeStats("trend")
        for _ in range(5):
            rs.record_trade(100.0, 80.0, "s1")
        for _ in range(5):
            rs.record_trade(-50.0, 60.0, "s2")
        # s1 should have higher weight than s2
        assert rs.strategy_weights.get("s1", 0) > rs.strategy_weights.get("s2", 0)


class TestRegimeFeedbackManager:
    """Test RegimeFeedbackManager end-to-end."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = RegimeFeedbackManager(data_dir=self.tmpdir)

    def test_init_creates_all_regimes(self):
        """All known regimes should be initialized."""
        for regime in RegimeFeedbackManager.KNOWN_REGIMES:
            assert regime in self.mgr.regimes

    def test_presets_applied(self):
        """Regime presets should be applied at init."""
        assert self.mgr.regimes["trend"].confidence_floor == 60.0
        assert self.mgr.regimes["range"].confidence_floor == 85.0
        assert self.mgr.regimes["trend"].risk_multiplier == 1.2
        assert self.mgr.regimes["range"].risk_multiplier == 0.6

    def test_record_trade_updates_regime(self):
        """Recording a trade should update the correct regime."""
        self.mgr.record_trade("trend", 100.0, 80.0, "s1")
        assert self.mgr.regimes["trend"].win_count == 1
        assert self.mgr.regimes["range"].win_count == 0

    def test_unknown_regime_falls_back(self):
        """Unknown regime names should fall back to 'unknown'."""
        self.mgr.record_trade("nonexistent_regime", 100.0, 80.0, "s1")
        assert self.mgr.regimes["unknown"].win_count == 1

    def test_regime_normalization(self):
        """Regime names should be case-insensitive and trimmed."""
        self.mgr.record_trade("  TREND  ", 100.0, 80.0, "s1")
        assert self.mgr.regimes["trend"].win_count == 1

    def test_get_confidence_floor(self):
        """Should return preset floor for unused regime."""
        floor = self.mgr.get_confidence_floor("trend")
        assert floor == 60.0

    def test_get_risk_multiplier(self):
        """Should return preset multiplier for unused regime."""
        mult = self.mgr.get_risk_multiplier("trend")
        assert mult == 1.2

    def test_get_strategy_weights_empty(self):
        """Should return empty dict when no trades recorded."""
        weights = self.mgr.get_strategy_weights("trend")
        assert weights == {}

    def test_get_confidence_floor_unknown_regime(self):
        """Unknown regime should use 'unknown' preset."""
        floor = self.mgr.get_confidence_floor("nonexistent")
        assert floor == 80.0  # Falls back to REGIME_PRESETS["unknown"] = 80.0

    def test_persistence(self):
        """State should survive save/load cycle."""
        self.mgr.record_trade("trend", 100.0, 80.0, "s1")
        self.mgr.record_trade("range", -50.0, 70.0, "s2")

        # Create new manager pointing to same dir
        mgr2 = RegimeFeedbackManager(data_dir=self.tmpdir)
        assert mgr2.regimes["trend"].win_count == 1
        assert mgr2.regimes["range"].loss_count == 1


class TestRegimeFeedbackRecommendation:
    """Test regime-specific recommendations."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = RegimeFeedbackManager(data_dir=self.tmpdir)

    def test_recommendation_preset_when_no_data(self):
        """Should return preset recommendation without trade data."""
        rec = self.mgr.get_regime_recommendation("trend")
        assert rec["data_source"] == "preset"
        assert rec["confidence_floor"] == 60.0

    def test_recommendation_adaptive_with_data(self):
        """Should return adaptive recommendation with enough data."""
        for _ in range(10):
            self.mgr.record_trade("trend", 100.0, 85.0, "s1", hold_hours=3.0)
        rec = self.mgr.get_regime_recommendation("trend")
        assert rec["data_source"] == "adaptive"
        assert rec["trades_observed"] == 10
        assert "win_rate" in rec


class TestRegimeFeedbackPromptContext:
    """Test LLM prompt context generation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = RegimeFeedbackManager(data_dir=self.tmpdir)

    def test_prompt_context_no_data(self):
        """Should return preset description with no data."""
        ctx = self.mgr.get_prompt_context("trend")
        assert "REGIME FEEDBACK" in ctx
        assert "trend" in ctx

    def test_prompt_context_with_data(self):
        """Should return rich context with trade data."""
        for _ in range(8):
            self.mgr.record_trade("trend", 100.0, 85.0, "s1", hold_hours=3.0)
        for _ in range(2):
            self.mgr.record_trade("trend", -40.0, 65.0, "s1", hold_hours=1.0)

        ctx = self.mgr.get_prompt_context("trend")
        assert "Win rate" in ctx
        assert "10 trades" in ctx

    def test_regime_summary(self):
        """Summary should include all regimes."""
        summary = self.mgr.get_regime_summary()
        assert len(summary) == len(RegimeFeedbackManager.KNOWN_REGIMES)
        for regime_name in RegimeFeedbackManager.KNOWN_REGIMES:
            assert regime_name in summary
