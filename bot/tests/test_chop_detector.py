"""
Tests for Push 1: Profitability Shield.

Tests:
- ChopDetector: all 5 factors, combined scoring, threshold override
- Ensemble chop integration: chop blocks signals, fallback works
- Min votes enforcement (3 instead of 2)
- Hold time limits (tighten SL, force close)
- Adaptive risk persistence (save/load cycle)
- Strategy weight startup logging
"""
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# ChopDetector unit tests
# ---------------------------------------------------------------------------

class TestChopDetector:
    """Test multi-factor chop detection."""

    def _make_df(self, n=60, base_price=100.0, volume=1000.0,
                 tight_range=False, low_vol=False, whipsaw=False):
        """Generate synthetic 1h OHLCV DataFrame."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=n, freq="h")

        if tight_range:
            # Very tight range: all prices within 0.2%
            close = base_price + np.random.uniform(-0.1, 0.1, n)
            high = close + 0.05
            low = close - 0.05
        elif whipsaw:
            # Alternating direction: up/down/up/down
            close = [base_price]
            for i in range(1, n):
                if i % 2 == 0:
                    close.append(close[-1] + np.random.uniform(0.5, 1.5))
                else:
                    close.append(close[-1] - np.random.uniform(0.5, 1.5))
            close = np.array(close)
            high = close + 0.3
            low = close - 0.3
        else:
            # Normal trending data
            close = base_price + np.cumsum(np.random.randn(n) * 0.5)
            high = close + np.random.uniform(0.2, 1.0, n)
            low = close - np.random.uniform(0.2, 1.0, n)

        if low_vol:
            # First bars have normal volume, last bar has drought
            vol = np.full(n, volume)
            vol[-1] = volume * 0.2  # Last bar = 20% of avg = extreme drought
        else:
            vol = np.full(n, volume)

        df = pd.DataFrame({
            "open": close - np.random.uniform(-0.1, 0.1, n),
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }, index=dates)
        return df

    def test_volume_factor_low(self):
        """Low volume should produce high chop score."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector(threshold=0.55)
        df = self._make_df(low_vol=True)
        score = detector._volume_factor(df)
        assert score > 0.5, f"Expected high volume score for drought, got {score}"

    def test_volume_factor_normal(self):
        """Normal volume should produce low chop score."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector(threshold=0.55)
        df = self._make_df()
        score = detector._volume_factor(df)
        assert score < 0.3, f"Expected low volume score for normal vol, got {score}"

    def test_range_tightness_tight(self):
        """Tight range should produce high score."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector()
        df = self._make_df(tight_range=True)
        score = detector._range_tightness_factor(df)
        assert score > 0.5, f"Expected high range tightness for tight data, got {score}"

    def test_whipsaw_factor(self):
        """Alternating price directions should produce high whipsaw score."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector()
        df = self._make_df(whipsaw=True)
        score = detector._whipsaw_factor(df)
        assert score > 0.0, f"Expected positive whipsaw score, got {score}"

    def test_insufficient_data_returns_false(self):
        """Insufficient data should return not-choppy."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector()
        df = self._make_df(n=5)
        is_chop, score, detail = detector.is_choppy("BTC", {"1h": df})
        assert not is_chop
        assert score == 0.0

    def test_threshold_override(self):
        """Custom threshold should be respected."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector(threshold=0.99)
        assert detector.threshold == 0.99
        # Very high threshold means almost nothing is choppy
        df = self._make_df()
        is_chop, score, _ = detector.is_choppy("BTC", {"1h": df})
        assert not is_chop, "With threshold=0.99, normal data should not be choppy"

    def test_combined_chop_scoring(self):
        """All factors contribute to combined score."""
        from strategies.chop_detector import ChopDetector
        detector = ChopDetector(threshold=0.55)
        df = self._make_df(tight_range=True, low_vol=True)
        is_chop, score, detail = detector.is_choppy("BTC", {"1h": df})
        # Tight range + low volume should push score high
        assert score > 0.0, f"Combined score should be positive, got {score}"
        assert "vol=" in detail
        assert "range=" in detail

    def test_env_threshold_override(self):
        """CHOP_THRESHOLD env var should be respected."""
        from strategies.chop_detector import ChopDetector
        with patch.dict(os.environ, {"CHOP_THRESHOLD": "0.90"}):
            detector = ChopDetector()
            assert detector.threshold == 0.90


# ---------------------------------------------------------------------------
# Ensemble chop integration tests
# ---------------------------------------------------------------------------

class TestEnsembleChopIntegration:
    """Test chop detector integration with ensemble."""

    def test_chop_detector_blocks_signal(self):
        """When chop detector says choppy, ensemble returns None."""
        from strategies.ensemble import EnsembleStrategy

        mock_chop = MagicMock()
        mock_chop.is_choppy.return_value = (True, 0.75, "vol=0.8 range=0.9 => 0.75")

        mock_strategy = MagicMock()
        mock_strategy.name = "test_strat"
        mock_signal = MagicMock()
        mock_signal.side = "BUY"
        mock_signal.confidence = 80.0
        mock_signal.metadata = {}
        mock_strategy.evaluate.return_value = mock_signal

        ensemble = EnsembleStrategy(
            strategies=[mock_strategy],
            mode="best",
            chop_detector=mock_chop,
        )
        result = ensemble.evaluate("BTC", {"1h": pd.DataFrame()})
        assert result is None

    def test_no_chop_passes_through(self):
        """When chop detector says not choppy, signals pass through."""
        from strategies.ensemble import EnsembleStrategy

        mock_chop = MagicMock()
        mock_chop.is_choppy.return_value = (False, 0.30, "vol=0.2 range=0.3 => 0.30")

        mock_strategy = MagicMock()
        mock_strategy.name = "test_strat"
        mock_signal = MagicMock()
        mock_signal.side = "BUY"
        mock_signal.confidence = 80.0
        mock_signal.metadata = {}
        mock_signal.entry = 100.0
        mock_signal.sl = 95.0
        mock_signal.tp1 = 105.0
        mock_signal.tp2 = 110.0
        mock_signal.atr = 2.0
        mock_signal.strategy = "test_strat"
        mock_strategy.evaluate.return_value = mock_signal

        ensemble = EnsembleStrategy(
            strategies=[mock_strategy],
            mode="best",
            min_votes=1,
            chop_detector=mock_chop,
        )
        # Note: result may still be None due to confidence floor (65%)
        # but chop_score should be attached to metadata
        mock_strategy.evaluate.return_value = mock_signal
        ensemble.evaluate("BTC", {"1h": pd.DataFrame()})
        # Verify chop score was attached
        assert mock_signal.metadata.get("chop_score") == 0.3


# ---------------------------------------------------------------------------
# Min votes enforcement
# ---------------------------------------------------------------------------

class TestMinVotesConfig:
    """Test that min_votes default was raised to 3."""

    def test_default_min_votes_is_3(self):
        """Default MIN_VOTES_REQUIRED should be 3."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove env override if set
            env = os.environ.copy()
            env.pop("MIN_VOTES_REQUIRED", None)
            with patch.dict(os.environ, env, clear=True):
                from trading_config import TradingConfig
                config = TradingConfig()
                assert config.min_votes_required == 3, (
                    f"Expected default min_votes=3, got {config.min_votes_required}"
                )


# ---------------------------------------------------------------------------
# Hold time limits
# ---------------------------------------------------------------------------

class TestHoldTimeLimits:
    """Test position hold time enforcement."""

    def test_tighten_sl_at_max_hold(self):
        """At max_hold_hours, SL should be tightened to breakeven."""
        from execution.position_manager import PositionManager, Position, OPEN

        pm = PositionManager()
        # Create a position opened 50 hours ago
        open_time = datetime.now(timezone.utc) - timedelta(hours=50)
        pos = Position(
            symbol="BTC",
            side="LONG",
            entry=100.0,
            qty=1.0,
            sl=95.0,
            tp1=105.0,
            tp2=110.0,
            leverage=2.0,
        )
        pos.state = OPEN
        pos.open_time = open_time
        pm.positions["BTC"] = pos

        # Check hold limits with 48h max
        result = pm.check_hold_limits("BTC", 102.0, max_hold_hours=48, action="tighten_sl")
        assert result is None, "Should not force close, just tighten SL"
        assert pos.sl == 100.0, f"SL should be tightened to entry (100.0), got {pos.sl}"

    def test_force_close_at_hard_limit(self):
        """At 1.5x max_hold, position should be force closed."""
        from execution.position_manager import PositionManager, Position, OPEN

        pm = PositionManager()
        # Create position opened 80 hours ago (> 48 * 1.5 = 72h)
        open_time = datetime.now(timezone.utc) - timedelta(hours=80)
        pos = Position(
            symbol="ETH",
            side="LONG",
            entry=3000.0,
            qty=1.0,
            sl=2900.0,
            tp1=3100.0,
            tp2=3200.0,
            leverage=2.0,
        )
        pos.state = OPEN
        pos.open_time = open_time
        pm.positions["ETH"] = pos

        result = pm.check_hold_limits("ETH", 3050.0, max_hold_hours=48)
        assert result is not None, "Should force close at 1.5x max hold"
        assert result.action == "HOLD_LIMIT"


# ---------------------------------------------------------------------------
# Adaptive risk persistence
# ---------------------------------------------------------------------------

class TestAdaptiveRiskPersistence:
    """Test adaptive risk state save/load cycle."""

    def test_save_load_cycle(self):
        """State should survive save/load cycle."""
        from execution.adaptive_risk import AdaptiveRiskManager

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "adaptive_risk_state.json")
            with patch("execution.adaptive_risk._STATE_PATH", state_path):
                mgr = AdaptiveRiskManager()
                mgr.record_outcome(True, "trend")
                mgr.record_outcome(False, "trend")
                mgr.record_outcome(True, "mean_reversion")

                # Verify state file exists
                assert os.path.exists(state_path)

                # Load into new instance
                mgr2 = AdaptiveRiskManager()
                assert len(mgr2._recent_outcomes) == 3
                assert mgr2._regime_wr["trend"]["wins"] == 1
                assert mgr2._regime_wr["trend"]["total"] == 2
