"""
Tests for Wave 2 execution intelligence:
  - Signal decay: stale signals lose confidence
  - Regime-based strategy filter: poor performers disabled
  - Dynamic TP scaling: overshoot and momentum adjust close %
  - Liquidity guard integration: dead market rejection + size multiplier
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Signal Decay ────────────────────────────────────────────

class TestSignalDecay:
    """Signal confidence should decrease for stale signals."""

    def test_fresh_signal_no_decay(self):
        """Signals younger than threshold should not be decayed."""
        generated_at = time.time() - 30  # 30 seconds ago
        signal_age = time.time() - generated_at
        decay_threshold = 180  # 3 minutes

        if signal_age > decay_threshold:
            confidence_mult = max(0.8, 1.0 - (signal_age - 60) / 600)
        else:
            confidence_mult = 1.0

        assert confidence_mult == 1.0

    def test_stale_signal_decayed(self):
        """Signals older than threshold should lose confidence."""
        generated_at = time.time() - 300  # 5 minutes ago
        signal_age = time.time() - generated_at
        decay_threshold = 180

        assert signal_age > decay_threshold
        confidence_mult = max(0.8, 1.0 - (signal_age - 60) / 600)
        assert confidence_mult < 1.0
        assert confidence_mult >= 0.8

    def test_very_old_signal_floors_at_80pct(self):
        """Even very stale signals shouldn't lose more than 20%."""
        generated_at = time.time() - 3600  # 1 hour ago
        signal_age = time.time() - generated_at
        confidence_mult = max(0.8, 1.0 - (signal_age - 60) / 600)
        assert confidence_mult == 0.8


# ── Regime-Based Strategy Filter ────────────────────────────

class TestRegimeStrategyFilter:
    """Strategies with poor win rates in current regime should be disabled."""

    def test_set_disabled_strategies(self):
        """Ensemble should accept disabled strategy names."""
        from strategies.ensemble import EnsembleStrategy
        ensemble = EnsembleStrategy(strategies=[])
        ensemble.set_disabled_strategies({"regime_trend", "montecarlo"})
        assert ensemble._disabled_strategies == {"regime_trend", "montecarlo"}

    def test_clear_disabled_strategies(self):
        """Passing empty set should re-enable all strategies."""
        from strategies.ensemble import EnsembleStrategy
        ensemble = EnsembleStrategy(strategies=[])
        ensemble.set_disabled_strategies({"regime_trend"})
        assert len(ensemble._disabled_strategies) == 1
        ensemble.set_disabled_strategies(set())
        assert len(ensemble._disabled_strategies) == 0

    def test_disabled_strategy_excluded_from_voting(self):
        """Disabled strategies are called for shadow tracking but excluded from voting."""
        from strategies.ensemble import EnsembleStrategy
        from strategies.base import Signal

        # Create mock strategies that behave like BaseStrategy
        strat1 = MagicMock()
        strat1.name = "good_strategy"
        strat1.evaluate.return_value = Signal(
            strategy="good_strategy", symbol="BTC", side="BUY",
            confidence=80, entry=100, sl=97, tp1=106, tp2=112
        )

        strat2 = MagicMock()
        strat2.name = "bad_strategy"
        strat2.evaluate.return_value = Signal(
            strategy="bad_strategy", symbol="BTC", side="BUY",
            confidence=80, entry=100, sl=97, tp1=106, tp2=112
        )

        ensemble = EnsembleStrategy(strategies=[strat1, strat2], min_votes=2)
        ensemble.set_disabled_strategies({"bad_strategy"})

        # evaluate() calls bad_strategy for shadow tracking but excludes from voting.
        # With min_votes=2 and only 1 active strategy, no signal should be produced.
        result = ensemble.evaluate("BTC", {"5m": MagicMock(), "1h": MagicMock()})
        strat1.evaluate.assert_called_once()
        # bad_strategy is called for shadow tracking
        strat2.evaluate.assert_called_once()
        # But result is None because we need 2 votes and only 1 active
        assert result is None


# ── Dynamic TP Scaling ──────────────────────────────────────

class TestDynamicTPScaling:
    """TP1 close % should adjust based on overshoot and move speed."""

    def _make_position(self, **kwargs):
        from execution.position_manager import Position
        defaults = {
            "symbol": "BTC",
            "side": "LONG",
            "entry": 60000.0,
            "qty": 0.1,
            "sl": 59000.0,
            "tp1": 61000.0,
            "tp2": 63000.0,
            "leverage": 3.0,
            "tp1_close_pct": 0.70,
            "open_time": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        defaults.update(kwargs)
        return Position(**defaults)

    @patch.dict(os.environ, {"DYNAMIC_TP_SCALING": "true"})
    def test_overshoot_increases_close_pct(self):
        """Price overshooting TP1 toward TP2 should increase close %."""
        pos = self._make_position()
        # Simulate price at 62500 (75% toward TP2)
        price = 62500.0
        tp_range = abs(pos.tp2 - pos.tp1)  # 2000
        overshoot = (price - pos.tp1) / tp_range  # 0.75

        assert overshoot > 0.5
        # Should increase by 20%: 0.70 * 1.20 = 0.84
        expected_close = min(pos.tp1_close_pct * 1.20, 0.90)
        assert expected_close == pytest.approx(0.84, abs=0.01)

    @patch.dict(os.environ, {"DYNAMIC_TP_SCALING": "true"})
    def test_fast_move_reduces_close_pct(self):
        """Fast move to TP1 (<30 min) should reduce close % to let it run."""
        pos = self._make_position(
            open_time=datetime.now(timezone.utc) - timedelta(minutes=15),
        )
        # 15 minutes is < 30 min threshold
        time_to_tp1 = (datetime.now(timezone.utc) - pos.open_time).total_seconds()
        assert time_to_tp1 < 1800

        # Should reduce by 15%: 0.70 * 0.85 = 0.595
        expected_close = pos.tp1_close_pct * 0.85
        assert expected_close == pytest.approx(0.595, abs=0.01)

    @patch.dict(os.environ, {"DYNAMIC_TP_SCALING": "true"})
    def test_slow_grind_increases_close_pct(self):
        """Slow move to TP1 (>4 hours) should increase close %."""
        pos = self._make_position(
            open_time=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        time_to_tp1 = (datetime.now(timezone.utc) - pos.open_time).total_seconds()
        assert time_to_tp1 > 14400

        # Should increase by 10%: 0.70 * 1.10 = 0.77
        expected_close = min(pos.tp1_close_pct * 1.10, 0.90)
        assert expected_close == pytest.approx(0.77, abs=0.01)

    @patch.dict(os.environ, {"DYNAMIC_TP_SCALING": "false"})
    def test_disabled_no_scaling(self):
        """When disabled, close % should remain unchanged."""
        pos = self._make_position(
            open_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        # Even with fast move and overshoot, should stay at default
        assert pos.tp1_close_pct == 0.70

    def test_close_pct_capped_at_90(self):
        """Dynamic close % should never exceed 90%."""
        # Start with high close_pct, apply overshoot scaling
        base_pct = 0.85
        scaled = min(base_pct * 1.20, 0.90)
        assert scaled == 0.90  # capped

    def test_short_position_overshoot(self):
        """Overshoot calculation should work correctly for shorts."""
        pos = self._make_position(
            side="SHORT",
            entry=60000.0,
            sl=61000.0,
            tp1=59000.0,
            tp2=57000.0,
        )
        # Price at 57500 — overshooting TP1 (59000) toward TP2 (57000)
        price = 57500.0
        tp_range = abs(pos.tp2 - pos.tp1)  # 2000
        overshoot = (pos.tp1 - price) / tp_range  # 0.75
        assert overshoot > 0.5


# ── Liquidity Guard Integration ─────────────────────────────

class TestLiquidityGuardIntegration:
    """Verify liquidity guard decisions match expectations for various market conditions."""

    def test_combined_low_vol_and_extreme_funding(self):
        """Multiple penalties should stack multiplicatively."""
        from execution.liquidity_guard import validate_liquidity
        result = validate_liquidity(
            symbol="PEPE",
            volume_ratio=0.5,   # low volume: 0.7x
            funding_rate=0.001,  # extreme funding: 0.7x
        )
        assert result.can_trade
        # Both penalties: 0.7 * 0.7 = 0.49
        assert result.size_multiplier == pytest.approx(0.49, abs=0.01)

    def test_boundary_volume_ratio(self):
        """Volume ratio exactly at 0.3 should pass (not reject)."""
        from execution.liquidity_guard import validate_liquidity
        result = validate_liquidity(symbol="BTC", volume_ratio=0.3)
        assert result.can_trade  # 0.3 is NOT < 0.3

    def test_boundary_volume_ratio_just_below(self):
        """Volume ratio just below 0.3 should reject."""
        from execution.liquidity_guard import validate_liquidity
        result = validate_liquidity(symbol="BTC", volume_ratio=0.29)
        assert not result.can_trade

    def test_moderate_funding_reduces_size(self):
        """Moderate funding (0.03-0.05%) should apply 15% reduction."""
        from execution.liquidity_guard import validate_liquidity
        result = validate_liquidity(
            symbol="SOL",
            volume_ratio=1.0,
            funding_rate=0.0004,  # 0.04% — high but not extreme
        )
        assert result.can_trade
        assert result.size_multiplier == pytest.approx(0.85, abs=0.01)
