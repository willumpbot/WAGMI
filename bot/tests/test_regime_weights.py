"""
Tests for RegimeStrategyWeighter — regime-aware strategy weight adjustments.

Validates:
1. Static prior multipliers (backtest-derived)
2. Live performance tracking and auto-tuning
3. Multiplicative application on base weights
4. Integration with ensemble _get_strategy_weight
5. Edge cases (unknown regime, missing strategy, empty data)
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure bot/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.regime_strategy_weighter import RegimeStrategyWeighter, DEFAULT_REGIME_FIT


class TestRegimeStrategyWeighterPriors:
    """Test static regime-strategy fit multipliers."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.weighter = RegimeStrategyWeighter(data_dir=self.tmpdir)

    def test_ranging_boosts_confidence_scorer(self):
        """confidence_scorer should be boosted in ranging regime."""
        mult = self.weighter.get_regime_multiplier("range", "confidence_scorer")
        assert mult == 1.3, f"Expected 1.3x for confidence_scorer in range, got {mult}"

    def test_ranging_boosts_bollinger_squeeze(self):
        """bollinger_squeeze should be boosted in ranging regime."""
        mult = self.weighter.get_regime_multiplier("range", "bollinger_squeeze")
        assert mult == 1.3

    def test_ranging_reduces_regime_trend(self):
        """regime_trend should be reduced in ranging regime (trend-following in range = bad)."""
        mult = self.weighter.get_regime_multiplier("range", "regime_trend")
        assert mult == 0.6  # Demoted: PF=0.95 in backtest

    def test_trending_boosts_momentum(self):
        """Momentum strategies should be boosted in trending regime."""
        mult = self.weighter.get_regime_multiplier("trend", "regime_trend")
        assert mult == 1.0  # regime_trend keeps full weight only in trending regimes
        mult = self.weighter.get_regime_multiplier("trend", "probability_engine")
        assert mult == 1.3

    def test_trending_reduces_mean_reversion(self):
        """Mean reversion should be reduced in trending regime."""
        mult = self.weighter.get_regime_multiplier("trend", "mean_reversion")
        assert mult == 0.7

    def test_high_vol_boosts_bollinger(self):
        """bollinger_squeeze should be boosted in high_volatility (squeeze detection)."""
        mult = self.weighter.get_regime_multiplier("high_volatility", "bollinger_squeeze")
        assert mult == 1.3

    def test_consolidation_even_weights(self):
        """Consolidation should have near-even weights (1.0 ± 0.2 for most, regime_trend demoted)."""
        for strategy in ["confidence_scorer", "bollinger_squeeze", "probability_engine",
                         "mean_reversion"]:
            mult = self.weighter.get_regime_multiplier("consolidation", strategy)
            assert 0.8 <= mult <= 1.2, f"{strategy} in consolidation should be near 1.0, got {mult}"
        # regime_trend is globally demoted (PF=0.95) — 0.6x in non-trending regimes
        mult = self.weighter.get_regime_multiplier("consolidation", "regime_trend")
        assert mult == 0.6, f"regime_trend in consolidation should be 0.6 (demoted), got {mult}"

    def test_unknown_strategy_returns_1(self):
        """Unknown strategy should return 1.0 (no adjustment)."""
        mult = self.weighter.get_regime_multiplier("range", "nonexistent_strategy")
        assert mult == 1.0

    def test_unknown_regime_returns_near_1(self):
        """Unknown regime strategies should be near 1.0."""
        mult = self.weighter.get_regime_multiplier("unknown", "confidence_scorer")
        assert 0.8 <= mult <= 1.2

    def test_completely_unknown_regime_returns_1(self):
        """A regime not in the table at all should return 1.0."""
        mult = self.weighter.get_regime_multiplier("alien_regime", "confidence_scorer")
        assert mult == 1.0

    def test_case_insensitive_regime(self):
        """Regime lookup should be case-insensitive."""
        mult_lower = self.weighter.get_regime_multiplier("range", "confidence_scorer")
        mult_upper = self.weighter.get_regime_multiplier("RANGE", "confidence_scorer")
        assert mult_lower == mult_upper

    def test_regime_alias_ranging(self):
        """'ranging' should work the same as 'range'."""
        mult_range = self.weighter.get_regime_multiplier("range", "bollinger_squeeze")
        mult_ranging = self.weighter.get_regime_multiplier("ranging", "bollinger_squeeze")
        assert mult_range == mult_ranging


class TestRegimeStrategyWeighterTracking:
    """Test live performance tracking and auto-tuning."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.weighter = RegimeStrategyWeighter(
            data_dir=self.tmpdir,
            min_trades_for_override=5,  # Low threshold for testing
        )

    def test_record_outcome_creates_entry(self):
        """Recording an outcome should create performance data."""
        self.weighter.record_outcome("range", "confidence_scorer", True)
        assert "range" in self.weighter.performance
        assert "confidence_scorer" in self.weighter.performance["range"]
        assert self.weighter.performance["range"]["confidence_scorer"]["trials"] == 1
        assert self.weighter.performance["range"]["confidence_scorer"]["wins"] == 1

    def test_record_outcome_loss(self):
        """Recording a loss should increment trials but not wins."""
        self.weighter.record_outcome("range", "confidence_scorer", False)
        perf = self.weighter.performance["range"]["confidence_scorer"]
        assert perf["trials"] == 1
        assert perf["wins"] == 0

    def test_insufficient_data_uses_prior(self):
        """With fewer than min_trades, should use static prior."""
        # Record 3 trades (below threshold of 5)
        for _ in range(3):
            self.weighter.record_outcome("range", "confidence_scorer", True)
        mult = self.weighter.get_regime_multiplier("range", "confidence_scorer")
        assert mult == 1.3  # Static prior

    def test_sufficient_data_blends_with_prior(self):
        """With enough data, multiplier should blend observed with prior."""
        # Record 10 wins out of 10 (100% WR -> observed_mult = 2.0, clamped to 1.5)
        for _ in range(10):
            self.weighter.record_outcome("range", "confidence_scorer", True)
        mult = self.weighter.get_regime_multiplier("range", "confidence_scorer")
        # Should be higher than prior (1.3) due to 100% WR blending in
        assert mult > 1.3

    def test_poor_performance_reduces_multiplier(self):
        """Poor performance should reduce the multiplier below the prior."""
        # Record 10 losses out of 10 (0% WR -> observed_mult = 0.5)
        for _ in range(10):
            self.weighter.record_outcome("trend", "regime_trend", False)
        mult = self.weighter.get_regime_multiplier("trend", "regime_trend")
        # Prior is 1.3, but 0% WR should drag it down
        assert mult < 1.3

    def test_multiplier_clamped(self):
        """Multiplier should be clamped to [0.5, 1.5] range."""
        # Record extreme data
        for _ in range(50):
            self.weighter.record_outcome("range", "confidence_scorer", True)
        mult = self.weighter.get_regime_multiplier("range", "confidence_scorer")
        assert 0.5 <= mult <= 1.5

        for _ in range(50):
            self.weighter.record_outcome("range", "mean_reversion", False)
        mult = self.weighter.get_regime_multiplier("range", "mean_reversion")
        assert 0.5 <= mult <= 1.5


class TestRegimeWeightsApplication:
    """Test multiplicative weight application on base weights."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.weighter = RegimeStrategyWeighter(data_dir=self.tmpdir)

    def test_get_regime_weights_multiplicative(self):
        """Regime weights should be multiplicative on base weights."""
        base_weights = {
            "confidence_scorer": 0.5,
            "bollinger_squeeze": 0.4,
            "regime_trend": 0.6,
        }
        adjusted = self.weighter.get_regime_weights("range", base_weights)

        # confidence_scorer: 0.5 * 1.3 = 0.65
        assert abs(adjusted["confidence_scorer"] - 0.65) < 0.01
        # bollinger_squeeze: 0.4 * 1.3 = 0.52
        assert abs(adjusted["bollinger_squeeze"] - 0.52) < 0.01
        # regime_trend: 0.6 * 0.6 = 0.36 (demoted PF=0.95)
        assert abs(adjusted["regime_trend"] - 0.36) < 0.01

    def test_get_regime_weights_preserves_all_strategies(self):
        """All strategies in base_weights should appear in output."""
        base_weights = {"a": 1.0, "b": 0.5, "c": 0.3}
        adjusted = self.weighter.get_regime_weights("trend", base_weights)
        assert set(adjusted.keys()) == set(base_weights.keys())

    def test_trending_bear_boosts_oi_delta(self):
        """In trending_bear, oi_delta should get boosted."""
        base_weights = {"oi_delta": 0.5}
        adjusted = self.weighter.get_regime_weights("trending_bear", base_weights)
        assert adjusted["oi_delta"] > 0.5  # Should be 0.5 * 1.3 = 0.65


class TestRegimeWeightsPersistence:
    """Test save/load persistence."""

    def test_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir, min_trades_for_override=5)

        # Record some data
        for _ in range(8):
            weighter.record_outcome("range", "confidence_scorer", True)
        for _ in range(3):
            weighter.record_outcome("range", "confidence_scorer", False)

        # Create new instance from same directory
        weighter2 = RegimeStrategyWeighter(data_dir=tmpdir, min_trades_for_override=5)

        # Should have loaded the same data
        perf = weighter2.performance.get("range", {}).get("confidence_scorer", {})
        assert perf.get("trials") == 11
        assert perf.get("wins") == 8

    def test_empty_state_file_handled(self):
        """Should handle missing state file gracefully."""
        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir)
        # Should not crash
        mult = weighter.get_regime_multiplier("range", "confidence_scorer")
        assert mult == 1.3


class TestRegimeWeightsReport:
    """Test reporting functionality."""

    def test_report_includes_recorded_data(self):
        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir, min_trades_for_override=5)
        for _ in range(6):
            weighter.record_outcome("range", "confidence_scorer", True)
        weighter.record_outcome("range", "confidence_scorer", False)

        report = weighter.get_report()
        assert "range" in report
        assert "confidence_scorer" in report["range"]
        assert report["range"]["confidence_scorer"]["trials"] == 7
        assert report["range"]["confidence_scorer"]["wins"] == 6
        assert 0.8 <= report["range"]["confidence_scorer"]["win_rate"] <= 0.9

    def test_all_regime_multipliers(self):
        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir)
        all_mults = weighter.get_all_regime_multipliers()
        # Should have entries for all regimes in DEFAULT_REGIME_FIT
        assert "range" in all_mults
        assert "trend" in all_mults
        assert "high_volatility" in all_mults
        assert "consolidation" in all_mults


class TestEnsembleIntegration:
    """Test integration with EnsembleStrategy._get_strategy_weight."""

    def _make_signal(self, strategy, side="BUY", confidence=75.0):
        """Create a mock signal for testing."""
        return MagicMock(
            strategy=strategy,
            side=side,
            confidence=confidence,
            metadata={},
            symbol="BTC/USDC:USDC",
        )

    def test_ensemble_applies_regime_weight(self):
        """Ensemble should apply regime multiplier when weighter is set."""
        from strategies.ensemble import EnsembleStrategy

        mock_strategy = MagicMock()
        mock_strategy.name = "confidence_scorer"
        ensemble = EnsembleStrategy(strategies=[mock_strategy], mode="weighted_veto")

        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir)
        ensemble.set_regime_strategy_weighter(weighter)
        ensemble.set_regime("BTC/USDC:USDC", "range")
        ensemble._current_eval_symbol = "BTC/USDC:USDC"

        # Without regime weighter, base weight should be 1.0 (default)
        # With regime weighter in "range", confidence_scorer gets 1.3x
        w = ensemble._get_strategy_weight("confidence_scorer")
        # Base is 1.0 (no weight manager), * 1.3 regime mult = 1.3
        assert abs(w - 1.3) < 0.01, f"Expected ~1.3, got {w}"

    def test_ensemble_no_weighter_returns_base(self):
        """Without regime weighter, should return base weight unchanged."""
        from strategies.ensemble import EnsembleStrategy

        mock_strategy = MagicMock()
        mock_strategy.name = "confidence_scorer"
        ensemble = EnsembleStrategy(strategies=[mock_strategy], mode="weighted_veto")

        # No weighter set
        ensemble._current_eval_symbol = "BTC/USDC:USDC"
        w = ensemble._get_strategy_weight("confidence_scorer")
        assert w == 1.0  # Default weight

    def test_ensemble_no_symbol_skips_regime(self):
        """If no current eval symbol, should skip regime adjustment."""
        from strategies.ensemble import EnsembleStrategy

        mock_strategy = MagicMock()
        mock_strategy.name = "confidence_scorer"
        ensemble = EnsembleStrategy(strategies=[mock_strategy], mode="weighted_veto")

        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir)
        ensemble.set_regime_strategy_weighter(weighter)
        # No _current_eval_symbol set

        w = ensemble._get_strategy_weight("confidence_scorer")
        assert w == 1.0  # No regime adjustment applied

    def test_regime_weight_stacks_with_weight_manager(self):
        """Regime weight should multiply with weight manager weight."""
        from strategies.ensemble import EnsembleStrategy

        mock_strategy = MagicMock()
        mock_strategy.name = "confidence_scorer"

        mock_wm = MagicMock()
        mock_wm.get_weight.return_value = 0.6  # Base weight from manager

        ensemble = EnsembleStrategy(
            strategies=[mock_strategy],
            mode="weighted_veto",
            weight_manager=mock_wm,
        )

        tmpdir = tempfile.mkdtemp()
        weighter = RegimeStrategyWeighter(data_dir=tmpdir)
        ensemble.set_regime_strategy_weighter(weighter)
        ensemble.set_regime("BTC/USDC:USDC", "range")
        ensemble._current_eval_symbol = "BTC/USDC:USDC"

        w = ensemble._get_strategy_weight("confidence_scorer")
        # 0.6 (base) * 1.3 (range boost) = 0.78
        assert abs(w - 0.78) < 0.01, f"Expected ~0.78, got {w}"


class TestDefaultRegimeFit:
    """Validate the DEFAULT_REGIME_FIT table structure."""

    def test_all_regimes_have_strategies(self):
        """Each regime should have at least 5 strategy entries."""
        for regime, strategies in DEFAULT_REGIME_FIT.items():
            assert len(strategies) >= 5, f"Regime {regime} only has {len(strategies)} strategies"

    def test_multipliers_in_valid_range(self):
        """All multipliers should be in [0.5, 1.5] range."""
        for regime, strategies in DEFAULT_REGIME_FIT.items():
            for strategy, mult in strategies.items():
                assert 0.5 <= mult <= 1.5, (
                    f"{regime}/{strategy} multiplier {mult} outside [0.5, 1.5]"
                )

    def test_core_strategies_in_all_regimes(self):
        """Core strategies should appear in all regime tables."""
        core = {"confidence_scorer", "bollinger_squeeze", "regime_trend", "probability_engine"}
        for regime, strategies in DEFAULT_REGIME_FIT.items():
            for s in core:
                assert s in strategies, f"{s} missing from regime {regime}"


class TestTradingConfigFlag:
    """Test the trading config flag."""

    def test_regime_weighting_flag_exists(self):
        """TradingConfig should have regime_strategy_weighting_enabled flag."""
        from trading_config import TradingConfig
        config = TradingConfig()
        assert hasattr(config, "regime_strategy_weighting_enabled")
        assert config.regime_strategy_weighting_enabled is True  # Default True

    def test_flag_can_be_disabled(self):
        """Flag should be disableable via env var."""
        with patch.dict(os.environ, {"REGIME_STRATEGY_WEIGHTING_ENABLED": "false"}):
            from trading_config import TradingConfig
            config = TradingConfig()
            assert config.regime_strategy_weighting_enabled is False
