"""
Tests for AdaptiveSizer — anti-martingale position sizing.

Validates heat computation, sizing multiplier output, per-symbol tracking,
floor/ceiling protection, streak handling, and state persistence.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import patch

from execution.adaptive_risk import AdaptiveSizer, get_adaptive_sizer


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sizer():
    """Fresh AdaptiveSizer with no persisted state."""
    with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
        return AdaptiveSizer(window=20, max_boost=1.5, min_floor=0.5)


@pytest.fixture
def small_window_sizer():
    """AdaptiveSizer with small window for quick testing."""
    with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
        return AdaptiveSizer(window=5, max_boost=1.5, min_floor=0.5)


# ─── Basic Heat Computation ───────────────────────────────────────────


class TestHeatComputation:
    """Tests for heat score calculation."""

    def test_no_data_returns_neutral(self, sizer):
        """No trades recorded → neutral heat (0.0)."""
        assert sizer.get_heat("BTC") == 0.0

    def test_insufficient_data_returns_neutral(self, sizer):
        """Less than 3 trades → neutral heat."""
        sizer.record_outcome("BTC", True)
        sizer.record_outcome("BTC", False)
        assert sizer.get_heat("BTC") == 0.0

    def test_all_wins_hot(self, sizer):
        """All wins → maximum heat (+1.0)."""
        for _ in range(10):
            sizer.record_outcome("BTC", True)
        heat = sizer.get_heat("BTC")
        assert heat == 1.0

    def test_all_losses_cold(self, sizer):
        """All losses → minimum heat (-1.0)."""
        for _ in range(10):
            sizer.record_outcome("BTC", False)
        heat = sizer.get_heat("BTC")
        assert heat == -1.0

    def test_balanced_near_neutral(self, sizer):
        """50/50 win rate → heat near 0.0."""
        for _ in range(10):
            sizer.record_outcome("BTC", True)
            sizer.record_outcome("BTC", False)
        heat = sizer.get_heat("BTC")
        assert -0.3 <= heat <= 0.3

    def test_winning_streak_positive_heat(self, sizer):
        """60%+ WR → positive heat."""
        for _ in range(4):
            sizer.record_outcome("BTC", True)
        for _ in range(2):
            sizer.record_outcome("BTC", False)
        for _ in range(4):
            sizer.record_outcome("BTC", True)
        heat = sizer.get_heat("BTC")
        assert heat > 0.0

    def test_losing_streak_negative_heat(self, sizer):
        """< 40% WR → negative heat."""
        for _ in range(2):
            sizer.record_outcome("BTC", True)
        for _ in range(8):
            sizer.record_outcome("BTC", False)
        heat = sizer.get_heat("BTC")
        assert heat < 0.0

    def test_heat_clamped_to_range(self, sizer):
        """Heat never exceeds [-1.0, +1.0]."""
        # Extreme winning streak
        for _ in range(20):
            sizer.record_outcome("BTC", True)
        assert sizer.get_heat("BTC") <= 1.0

        # Extreme losing streak
        for _ in range(20):
            sizer.record_outcome("SOL", False)
        assert sizer.get_heat("SOL") >= -1.0


# ─── Sizing Multiplier ────────────────────────────────────────────────


class TestSizingMultiplier:
    """Tests for sizing multiplier output."""

    def test_neutral_returns_1x(self, sizer):
        """No data → 1.0x multiplier."""
        assert sizer.get_sizing_multiplier("BTC") == 1.0

    def test_hot_returns_boost(self, sizer):
        """Hot streak → multiplier > 1.0, up to max_boost."""
        for _ in range(10):
            sizer.record_outcome("BTC", True)
        mult = sizer.get_sizing_multiplier("BTC")
        assert mult > 1.0
        assert mult <= 1.5

    def test_cold_returns_reduction(self, sizer):
        """Cold streak → multiplier < 1.0, down to min_floor."""
        for _ in range(10):
            sizer.record_outcome("BTC", False)
        mult = sizer.get_sizing_multiplier("BTC")
        assert mult < 1.0
        assert mult >= 0.5

    def test_max_boost_ceiling(self, sizer):
        """Multiplier never exceeds max_boost."""
        for _ in range(20):
            sizer.record_outcome("BTC", True)
        mult = sizer.get_sizing_multiplier("BTC")
        assert mult <= 1.5

    def test_min_floor_protection(self, sizer):
        """Multiplier never goes below min_floor."""
        for _ in range(20):
            sizer.record_outcome("BTC", False)
        mult = sizer.get_sizing_multiplier("BTC")
        assert mult >= 0.5

    def test_custom_max_boost(self):
        """Custom max_boost respected."""
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s = AdaptiveSizer(window=10, max_boost=2.0, min_floor=0.3)
        for _ in range(10):
            s.record_outcome("BTC", True)
        assert s.get_sizing_multiplier("BTC") <= 2.0

    def test_custom_min_floor(self):
        """Custom min_floor respected."""
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s = AdaptiveSizer(window=10, max_boost=1.5, min_floor=0.3)
        for _ in range(10):
            s.record_outcome("BTC", False)
        assert s.get_sizing_multiplier("BTC") >= 0.3

    def test_multiplier_increases_with_wins(self, sizer):
        """More consecutive wins → higher multiplier."""
        for _ in range(3):
            sizer.record_outcome("BTC", True)
        mult_3 = sizer.get_sizing_multiplier("BTC")

        for _ in range(7):
            sizer.record_outcome("BTC", True)
        mult_10 = sizer.get_sizing_multiplier("BTC")

        assert mult_10 >= mult_3

    def test_multiplier_decreases_with_losses(self, sizer):
        """More consecutive losses → lower multiplier."""
        for _ in range(3):
            sizer.record_outcome("BTC", False)
        mult_3 = sizer.get_sizing_multiplier("BTC")

        for _ in range(7):
            sizer.record_outcome("BTC", False)
        mult_10 = sizer.get_sizing_multiplier("BTC")

        assert mult_10 <= mult_3


# ─── Per-Symbol Tracking ──────────────────────────────────────────────


class TestPerSymbolTracking:
    """Tests for independent per-symbol heat tracking."""

    def test_independent_symbols(self, sizer):
        """BTC and SOL track independently."""
        for _ in range(10):
            sizer.record_outcome("BTC", True)
            sizer.record_outcome("SOL", False)

        assert sizer.get_heat("BTC") > 0
        assert sizer.get_heat("SOL") < 0
        assert sizer.get_sizing_multiplier("BTC") > 1.0
        assert sizer.get_sizing_multiplier("SOL") < 1.0

    def test_symbol_normalization(self, sizer):
        """Different symbol formats normalize to same base."""
        sizer.record_outcome("BTC/USDC:USDC", True)
        sizer.record_outcome("BTC/USDC:USDC", True)
        sizer.record_outcome("BTC/USDC:USDC", True)

        # Same as "BTC"
        assert sizer.get_heat("BTC") == sizer.get_heat("BTC/USDC:USDC")
        assert sizer.get_heat("BTC") == sizer.get_heat("BTC/USDT:USDT")

    def test_unknown_symbol_neutral(self, sizer):
        """Symbol with no data returns neutral."""
        sizer.record_outcome("BTC", True)
        assert sizer.get_sizing_multiplier("DOGE") == 1.0


# ─── Rolling Window ──────────────────────────────────────────────────


class TestRollingWindow:
    """Tests for rolling window behavior."""

    def test_window_limits_history(self, small_window_sizer):
        """Outcomes beyond window are dropped."""
        s = small_window_sizer
        # Record 5 losses (fills window)
        for _ in range(5):
            s.record_outcome("BTC", False)
        assert s.get_heat("BTC") < 0

        # Now record 5 wins (replaces all losses)
        for _ in range(5):
            s.record_outcome("BTC", True)
        assert s.get_heat("BTC") > 0

    def test_old_outcomes_forgotten(self, small_window_sizer):
        """Old outcomes don't affect current heat."""
        s = small_window_sizer
        # 100 losses (but window=5)
        for _ in range(100):
            s.record_outcome("BTC", False)
        # Now 5 wins
        for _ in range(5):
            s.record_outcome("BTC", True)
        # Should be hot, not cold (old losses forgotten)
        assert s.get_heat("BTC") > 0


# ─── Streak Detection ────────────────────────────────────────────────


class TestStreakDetection:
    """Tests for streak bonus in heat calculation."""

    def test_win_streak_boosts_heat(self, sizer):
        """Consecutive wins produce higher heat than scattered wins."""
        # Scattered pattern: WLWLWLWLWL (50% WR)
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s1 = AdaptiveSizer(window=10)
        for _ in range(5):
            s1.record_outcome("BTC", True)
            s1.record_outcome("BTC", False)

        # Streak pattern: LLLLLWWWWW (also 50% WR, but ends on win streak)
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s2 = AdaptiveSizer(window=10)
        for _ in range(5):
            s2.record_outcome("BTC", False)
        for _ in range(5):
            s2.record_outcome("BTC", True)

        # Streak pattern should have higher heat (streak bonus)
        assert s2.get_heat("BTC") > s1.get_heat("BTC")

    def test_loss_streak_deepens_cold(self, sizer):
        """Consecutive losses cool heat faster than scattered losses."""
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s1 = AdaptiveSizer(window=10)
        for _ in range(5):
            s1.record_outcome("BTC", False)
            s1.record_outcome("BTC", True)

        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s2 = AdaptiveSizer(window=10)
        for _ in range(5):
            s2.record_outcome("BTC", True)
        for _ in range(5):
            s2.record_outcome("BTC", False)

        # Streak of losses should be colder
        assert s2.get_heat("BTC") < s1.get_heat("BTC")


# ─── State Persistence ────────────────────────────────────────────────


class TestStatePersistence:
    """Tests for state save/load."""

    def test_save_and_load(self, tmp_path):
        """State persists across instances."""
        state_file = str(tmp_path / "adaptive_sizer.json")
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", state_file):
            s1 = AdaptiveSizer(window=10)
            for _ in range(8):
                s1.record_outcome("BTC", True)
            for _ in range(2):
                s1.record_outcome("BTC", False)
            heat_before = s1.get_heat("BTC")

            # New instance loads from file
            s2 = AdaptiveSizer(window=10)
            heat_after = s2.get_heat("BTC")

        assert heat_before == heat_after

    def test_load_missing_file(self, tmp_path):
        """Missing state file doesn't crash."""
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH",
                    str(tmp_path / "nonexistent.json")):
            s = AdaptiveSizer()
        assert s.get_heat("BTC") == 0.0

    def test_load_corrupt_file(self, tmp_path):
        """Corrupt state file doesn't crash."""
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("not valid json{{{")
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", str(state_file)):
            s = AdaptiveSizer()
        assert s.get_heat("BTC") == 0.0


# ─── Status Report ────────────────────────────────────────────────────


class TestStatusReport:
    """Tests for get_status() method."""

    def test_status_empty(self, sizer):
        """Empty sizer returns empty status."""
        assert sizer.get_status() == {}

    def test_status_fields(self, sizer):
        """Status includes all expected fields."""
        for _ in range(5):
            sizer.record_outcome("BTC", True)
        status = sizer.get_status()
        assert "BTC" in status
        btc = status["BTC"]
        assert "trades" in btc
        assert "wr" in btc
        assert "heat" in btc
        assert "multiplier" in btc
        assert "streak" in btc
        assert "recent" in btc
        assert btc["trades"] == 5
        assert btc["wr"] == 1.0
        assert btc["streak"] == 5

    def test_status_multiple_symbols(self, sizer):
        """Status tracks all symbols independently."""
        for _ in range(5):
            sizer.record_outcome("BTC", True)
        for _ in range(3):
            sizer.record_outcome("SOL", False)
        status = sizer.get_status()
        assert len(status) == 2
        assert status["BTC"]["wr"] == 1.0
        assert status["SOL"]["wr"] == 0.0


# ─── Singleton ─────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for get_adaptive_sizer() singleton."""

    def test_singleton_returns_same_instance(self):
        """get_adaptive_sizer() returns same instance on repeated calls."""
        import execution.adaptive_risk as ar
        # Reset singleton
        ar._sizer_instance = None
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s1 = get_adaptive_sizer()
            s2 = get_adaptive_sizer()
        assert s1 is s2
        ar._sizer_instance = None  # cleanup

    def test_singleton_respects_config(self):
        """Singleton picks up config values."""
        import execution.adaptive_risk as ar
        ar._sizer_instance = None

        class FakeConfig:
            adaptive_sizing_window = 10
            adaptive_sizing_max_boost = 2.0
            adaptive_sizing_min_floor = 0.3

        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s = get_adaptive_sizer(FakeConfig())
        assert s.window == 10
        assert s.max_boost == 2.0
        assert s.min_floor == 0.3
        ar._sizer_instance = None  # cleanup


# ─── Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests."""

    def test_minimum_window_enforced(self):
        """Window cannot go below 3."""
        with patch("execution.adaptive_risk._ADAPTIVE_SIZER_STATE_PATH", "/dev/null"):
            s = AdaptiveSizer(window=1)
        assert s.window >= 3

    def test_single_outcome_neutral(self, sizer):
        """Single trade → neutral (not enough data)."""
        sizer.record_outcome("BTC", True)
        assert sizer.get_heat("BTC") == 0.0
        assert sizer.get_sizing_multiplier("BTC") == 1.0

    def test_three_trades_starts_tracking(self, sizer):
        """Exactly 3 trades → starts producing heat."""
        sizer.record_outcome("BTC", True)
        sizer.record_outcome("BTC", True)
        sizer.record_outcome("BTC", True)
        assert sizer.get_heat("BTC") > 0.0

    def test_alternating_wl_near_neutral(self, sizer):
        """WLWLWLWLWL → near neutral (no streak, 50% WR)."""
        for _ in range(10):
            sizer.record_outcome("BTC", True)
            sizer.record_outcome("BTC", False)
        heat = sizer.get_heat("BTC")
        mult = sizer.get_sizing_multiplier("BTC")
        assert -0.3 <= heat <= 0.3
        assert 0.85 <= mult <= 1.15

    def test_rapid_regime_change(self, small_window_sizer):
        """Quick switch from hot to cold."""
        s = small_window_sizer
        # Get hot
        for _ in range(5):
            s.record_outcome("BTC", True)
        assert s.get_heat("BTC") > 0.5

        # Go cold
        for _ in range(5):
            s.record_outcome("BTC", False)
        assert s.get_heat("BTC") < -0.5


# ─── Integration with TradingConfig ──────────────────────────────────


class TestConfigIntegration:
    """Tests that config fields work correctly."""

    def test_config_defaults(self):
        """TradingConfig has adaptive sizing fields with correct defaults."""
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.adaptive_sizing_enabled is True
        assert config.adaptive_sizing_window == 20
        assert config.adaptive_sizing_max_boost == 1.5
        assert config.adaptive_sizing_min_floor == 0.5

    def test_config_env_override(self):
        """Config fields respond to environment variables."""
        from trading_config import TradingConfig
        with patch.dict(os.environ, {
            "ADAPTIVE_SIZING_ENABLED": "false",
            "ADAPTIVE_SIZING_WINDOW": "30",
            "ADAPTIVE_SIZING_MAX_BOOST": "2.0",
            "ADAPTIVE_SIZING_MIN_FLOOR": "0.3",
        }):
            config = TradingConfig()
        assert config.adaptive_sizing_enabled is False
        assert config.adaptive_sizing_window == 30
        assert config.adaptive_sizing_max_boost == 2.0
        assert config.adaptive_sizing_min_floor == 0.3
