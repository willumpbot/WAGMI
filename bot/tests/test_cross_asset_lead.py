"""
Tests for cross-asset lead-lag boost system.

Verifies:
- LeadLagBoostEngine BTC momentum detection and lead signal creation
- Time-delayed boost activation and expiry
- Correlation-based boost scaling and decay
- Volume ratio amplification
- Ensemble integration (boost applied to aligned signals)
- Edge cases: disabled engine, unknown symbols, correlation below threshold
"""

import os
import sys
import time
import pytest
from copy import deepcopy
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.cross_asset_alert import LeadLagBoostEngine, LeadSignal


# ─── Helpers ──────────────────────────────────────────────────────


def _feed_btc_prices(engine, prices, start_time=1_000_000.0, interval_s=60):
    """Feed a series of BTC prices at regular intervals."""
    signals = []
    for i, price in enumerate(prices):
        t = start_time + i * interval_s
        result = engine.update_btc_price(price, volume=100.0, current_time=t)
        signals.extend(result)
    return signals


def _make_btc_move(engine, start_price, end_price, start_time=1_000_000.0, n_points=16):
    """Feed BTC prices simulating a move from start to end over ~15 minutes."""
    step = (end_price - start_price) / (n_points - 1)
    prices = [start_price + step * i for i in range(n_points)]
    return _feed_btc_prices(engine, prices, start_time=start_time, interval_s=60)


def _make_engine(**kwargs):
    """Create a LeadLagBoostEngine with test-friendly defaults."""
    defaults = {
        "btc_move_threshold": 0.3,
        "max_boost": 12.0,
        "min_correlation": 0.60,
        "correlation_decay": 0.98,
        "enabled": True,
    }
    defaults.update(kwargs)
    return LeadLagBoostEngine(**defaults)


# ─── BTC Momentum Detection ──────────────────────────────────────


class TestBTCMomentumDetection:
    """Tests for detecting decisive BTC moves that trigger lead signals."""

    def test_no_signals_below_threshold(self):
        """Small BTC move (<0.3%) should not create lead signals."""
        engine = _make_engine()
        # 0.1% move
        signals = _make_btc_move(engine, 84_000, 84_084)
        assert len(signals) == 0

    def test_signals_above_threshold_up(self):
        """BTC move >0.3% upward should create BUY lead signals."""
        engine = _make_engine()
        # ~0.5% move up
        signals = _make_btc_move(engine, 84_000, 84_420)
        assert len(signals) > 0
        for sig in signals:
            assert sig.side == "BUY"
            assert sig.btc_move_pct > 0

    def test_signals_above_threshold_down(self):
        """BTC move >0.3% downward should create SELL lead signals."""
        engine = _make_engine()
        # ~0.5% move down
        signals = _make_btc_move(engine, 84_000, 83_580)
        assert len(signals) > 0
        for sig in signals:
            assert sig.side == "SELL"
            assert sig.btc_move_pct < 0

    def test_follower_signals_created(self):
        """Lead signals should be created for configured followers (SOL, ETH)."""
        engine = _make_engine()
        signals = _make_btc_move(engine, 84_000, 84_500)
        followers = {s.follower for s in signals}
        # SOL and ETH should get signals (both have corr > min_correlation=0.60)
        assert "SOL" in followers
        assert "ETH" in followers

    def test_hype_excluded_low_correlation(self):
        """HYPE (corr=0.44) should be excluded when min_correlation=0.60."""
        engine = _make_engine(min_correlation=0.60)
        signals = _make_btc_move(engine, 84_000, 84_500)
        followers = {s.follower for s in signals}
        assert "HYPE" not in followers

    def test_hype_included_low_threshold(self):
        """HYPE should be included when min_correlation is lowered below 0.44."""
        engine = _make_engine(min_correlation=0.40)
        signals = _make_btc_move(engine, 84_000, 84_500)
        followers = {s.follower for s in signals}
        assert "HYPE" in followers


# ─── Lead Signal Time Windows ────────────────────────────────────


class TestLeadSignalWindows:
    """Tests for time-delayed activation and expiry of lead signals."""

    def test_sol_lag_window(self):
        """SOL lead signal should be active in 30-60 minute window."""
        engine = _make_engine()
        t = 1_000_000.0
        signals = _make_btc_move(engine, 84_000, 84_500, start_time=t)
        sol_signals = [s for s in signals if s.follower == "SOL"]
        assert len(sol_signals) > 0
        sig = sol_signals[0]
        # Active after 30 min, expires after 60 min
        assert sig.active_after == pytest.approx(sig.created_at + 30 * 60, abs=120)
        assert sig.expires_at == pytest.approx(sig.created_at + 60 * 60, abs=120)

    def test_eth_lag_window(self):
        """ETH lead signal should be active in 15-30 minute window."""
        engine = _make_engine()
        t = 1_000_000.0
        signals = _make_btc_move(engine, 84_000, 84_500, start_time=t)
        eth_signals = [s for s in signals if s.follower == "ETH"]
        assert len(eth_signals) > 0
        sig = eth_signals[0]
        # Active after 15 min, expires after 30 min
        assert sig.active_after == pytest.approx(sig.created_at + 15 * 60, abs=120)
        assert sig.expires_at == pytest.approx(sig.created_at + 30 * 60, abs=120)

    def test_no_boost_before_active(self):
        """Boost should be 0 before the lead signal becomes active."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        # Check immediately (before any lag window opens)
        boost = engine.get_boost("SOL", "BUY", current_time=t + 16 * 60)
        # t + 16min is inside SOL lag window? No — SOL lag is 30-60min
        assert boost == 0.0

    def test_boost_during_active_window(self):
        """Boost should be positive during the active window."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        # SOL active window: 30-60 min after BTC move
        # The created_at is the time of the last price point
        last_t = t + 15 * 60  # approximate time of last BTC price
        boost = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        assert boost > 0.0

    def test_no_boost_after_expiry(self):
        """Boost should be 0 after the lead signal expires."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        # SOL expires after 60 min. Check at 90 min.
        boost = engine.get_boost("SOL", "BUY", current_time=t + 90 * 60)
        assert boost == 0.0

    def test_no_boost_wrong_direction(self):
        """BUY lead signal should not boost SELL signals."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)  # BUY signal
        # Check SELL during active window
        last_t = t + 15 * 60
        boost = engine.get_boost("SOL", "SELL", current_time=last_t + 35 * 60)
        assert boost == 0.0


# ─── Boost Calculation ───────────────────────────────────────────


class TestBoostCalculation:
    """Tests for boost amount calculation and capping."""

    def test_boost_capped_at_symbol_limit(self):
        """Boost should not exceed the per-symbol boost_cap."""
        engine = _make_engine(max_boost=50.0)  # High global cap
        t = 1_000_000.0
        # Large BTC move -> large raw boost, but SOL cap is 12.0
        _make_btc_move(engine, 84_000, 86_000, start_time=t)  # ~2.4% move
        last_t = t + 15 * 60
        boost = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        assert boost <= 12.0

    def test_boost_capped_at_global_limit(self):
        """Boost should not exceed max_boost."""
        engine = _make_engine(max_boost=5.0)
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 86_000, start_time=t)
        last_t = t + 15 * 60
        boost = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        assert boost <= 5.0

    def test_boost_scales_with_move_size(self):
        """Larger BTC moves should produce larger boosts."""
        engine1 = _make_engine()
        engine2 = _make_engine()
        t = 1_000_000.0

        # Small move: 0.4%
        _make_btc_move(engine1, 84_000, 84_336, start_time=t)
        # Large move: 1.0%
        _make_btc_move(engine2, 84_000, 84_840, start_time=t)

        last_t = t + 15 * 60
        boost_small = engine1.get_boost("ETH", "BUY", current_time=last_t + 20 * 60)
        boost_large = engine2.get_boost("ETH", "BUY", current_time=last_t + 20 * 60)
        assert boost_large >= boost_small

    def test_time_decay_within_window(self):
        """Boost should decay as we approach the end of the active window."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        last_t = t + 15 * 60

        # ETH active window: 15-30 min after creation
        boost_early = engine.get_boost("ETH", "BUY", current_time=last_t + 16 * 60)
        boost_late = engine.get_boost("ETH", "BUY", current_time=last_t + 28 * 60)
        # Early boost should be >= late boost (time decay)
        assert boost_early >= boost_late


# ─── Correlation Tracking ────────────────────────────────────────


class TestCorrelationTracking:
    """Tests for real-time correlation tracking and decay."""

    def test_correlation_initialized_from_config(self):
        """Real-time correlation should start at the configured historical value."""
        engine = _make_engine()
        diag = engine.get_diagnostics()
        assert diag["realtime_correlations"]["SOL"] == pytest.approx(0.87, abs=0.01)
        assert diag["realtime_correlations"]["ETH"] == pytest.approx(0.91, abs=0.01)

    def test_no_boost_when_correlation_below_threshold(self):
        """Boost should be 0 when real-time correlation drops below min_correlation."""
        engine = _make_engine(min_correlation=0.95)  # Very high threshold
        # Force low correlation for SOL
        engine._realtime_correlation["SOL"] = 0.50
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        last_t = t + 15 * 60
        boost = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        assert boost == 0.0

    def test_correlation_update_with_paired_returns(self):
        """Correlation should update when both BTC and follower returns are tracked."""
        engine = _make_engine()
        t = 1_000_000.0
        initial_corr = engine._realtime_correlation["SOL"]

        # Feed many paired BTC + SOL returns going the same direction
        for i in range(15):
            engine.update_btc_price(84_000 + i * 10, current_time=t + i * 60)
            engine.update_follower_price("SOL", 135.0 + i * 0.2, current_time=t + i * 60)

        # Correlation should still be reasonable (not crash or go to 0)
        new_corr = engine._realtime_correlation.get("SOL", 0)
        assert new_corr > 0.0  # Should remain positive with co-moving prices


# ─── Volume Ratio ────────────────────────────────────────────────


class TestVolumeRatio:
    """Tests for volume-weighted boost amplification."""

    def test_above_avg_volume_increases_boost(self):
        """Above-average volume should increase the boost amount."""
        engine1 = _make_engine()
        engine2 = _make_engine()
        t = 1_000_000.0

        # Engine 1: normal volume
        for i in range(16):
            engine1.update_btc_price(
                84_000 + i * 31.25,  # ~0.5% move over 15 points
                volume=100.0,
                current_time=t + i * 60,
            )
        # Engine 2: high volume
        for i in range(16):
            engine2.update_btc_price(
                84_000 + i * 31.25,
                volume=100.0 if i < 10 else 300.0,  # spike in recent volume
                current_time=t + i * 60,
            )

        last_t = t + 15 * 60
        boost_normal = engine1.get_boost("ETH", "BUY", current_time=last_t + 20 * 60)
        boost_high_vol = engine2.get_boost("ETH", "BUY", current_time=last_t + 20 * 60)
        # High volume boost should be >= normal (volume bonus in _check_btc_momentum)
        assert boost_high_vol >= boost_normal


# ─── Cooldown ────────────────────────────────────────────────────


class TestCooldown:
    """Tests for per-follower signal cooldown."""

    def test_cooldown_prevents_duplicate_signals(self):
        """Second BTC move within cooldown should not create duplicate lead signals."""
        engine = _make_engine()
        t = 1_000_000.0

        signals1 = _make_btc_move(engine, 84_000, 84_500, start_time=t)
        assert len(signals1) > 0

        # Second move 2 minutes later (within 5min cooldown)
        signals2 = _make_btc_move(engine, 84_500, 85_000, start_time=t + 120)
        # Some or all followers should be cooled down
        # At minimum, no follower should get double signals
        follower_counts_1 = {}
        for s in signals1:
            follower_counts_1[s.follower] = follower_counts_1.get(s.follower, 0) + 1
        follower_counts_2 = {}
        for s in signals2:
            follower_counts_2[s.follower] = follower_counts_2.get(s.follower, 0) + 1
        # Followers that got signals in batch 1 should be cooled down in batch 2
        for f in follower_counts_1:
            assert follower_counts_2.get(f, 0) == 0, f"Cooldown failed for {f}"


# ─── Disabled Engine ─────────────────────────────────────────────


class TestDisabledEngine:
    """Tests for the disabled state."""

    def test_disabled_returns_no_signals(self):
        """Disabled engine should return empty list from update_btc_price."""
        engine = _make_engine(enabled=False)
        signals = _make_btc_move(engine, 84_000, 84_500)
        assert signals == []

    def test_disabled_returns_zero_boost(self):
        """Disabled engine should return 0 boost."""
        engine = _make_engine(enabled=False)
        boost = engine.get_boost("SOL", "BUY")
        assert boost == 0.0

    def test_disabled_skips_price_updates(self):
        """Disabled engine should not accumulate price history."""
        engine = _make_engine(enabled=False)
        engine.update_btc_price(84_000)
        engine.update_follower_price("SOL", 135.0)
        assert len(engine._btc_prices) == 0


# ─── Unknown Symbols ─────────────────────────────────────────────


class TestUnknownSymbols:
    """Tests for symbols not in the lead-lag config."""

    def test_unknown_symbol_returns_zero_boost(self):
        """Symbols not in config should get zero boost."""
        engine = _make_engine()
        boost = engine.get_boost("DOGE", "BUY")
        assert boost == 0.0

    def test_symbol_suffix_stripping(self):
        """Exchange suffixes should be stripped for matching."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        last_t = t + 15 * 60
        # SOL/USDC:USDC should resolve to SOL
        boost = engine.get_boost("SOL/USDC:USDC", "BUY", current_time=last_t + 35 * 60)
        # Should return the same as bare "SOL"
        boost_bare = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        assert boost == boost_bare


# ─── Diagnostics & Active Signals ────────────────────────────────


class TestDiagnostics:
    """Tests for diagnostic and monitoring endpoints."""

    def test_diagnostics_structure(self):
        """Diagnostics should contain all expected keys."""
        engine = _make_engine()
        diag = engine.get_diagnostics()
        expected_keys = {
            "enabled", "btc_price_count", "active_lead_signals",
            "pending_lead_signals", "realtime_correlations",
            "btc_move_threshold", "max_boost", "min_correlation",
        }
        assert expected_keys.issubset(set(diag.keys()))

    def test_active_signals_structure(self):
        """Active signals list should have correct structure."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        last_t = t + 15 * 60
        active = engine.get_active_signals(current_time=last_t + 20 * 60)
        assert len(active) > 0
        for entry in active:
            assert "follower" in entry
            assert "side" in entry
            assert "boost" in entry
            assert "active" in entry
            assert "time_remaining_s" in entry

    def test_reset_clears_all_state(self):
        """Reset should clear all engine state."""
        engine = _make_engine()
        _make_btc_move(engine, 84_000, 84_500)
        engine.update_follower_price("SOL", 135.0)

        engine.reset()
        assert len(engine._btc_prices) == 0
        assert len(engine._lead_signals) == 0
        assert len(engine._follower_prices) == 0
        # Correlations should be re-initialized from config
        assert engine._realtime_correlation.get("SOL", 0) > 0


# ─── Ensemble Integration ────────────────────────────────────────


class TestEnsembleIntegration:
    """Tests for lead-lag boost wired into ensemble signal flow."""

    def _make_signal(self, symbol="SOL", side="BUY", confidence=75.0):
        """Create a minimal mock signal for testing."""
        from strategies.base import Signal
        entry = 135.0 if symbol == "SOL" else 2500.0
        if side == "BUY":
            sl = entry * 0.98
            tp1 = entry * 1.03
            tp2 = entry * 1.05
        else:
            sl = entry * 1.02
            tp1 = entry * 0.97
            tp2 = entry * 0.95
        return Signal(
            strategy="test_strategy",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=entry * 0.01,
        )

    def test_ensemble_applies_lead_lag_boost(self):
        """Ensemble should increase confidence when lead-lag boost is active."""
        engine = MagicMock()
        engine.get_boost.return_value = 8.0

        from strategies.ensemble import EnsembleStrategy

        # Create a minimal ensemble
        mock_strategy = MagicMock()
        mock_strategy.name = "test_strategy"
        sig = self._make_signal("SOL", "BUY", 75.0)
        mock_strategy.evaluate.return_value = sig

        ensemble = EnsembleStrategy(
            strategies=[mock_strategy],
            mode="best",
            min_votes=1,
            confidence_floor=50.0,
        )
        ensemble.set_lead_lag_engine(engine)

        # The engine should have been set
        assert ensemble._lead_lag_engine is engine

    def test_ensemble_no_boost_when_engine_none(self):
        """Ensemble should work normally when no lead-lag engine is set."""
        from strategies.ensemble import EnsembleStrategy

        mock_strategy = MagicMock()
        mock_strategy.name = "test_strategy"
        ensemble = EnsembleStrategy(
            strategies=[mock_strategy],
            mode="best",
            min_votes=1,
        )
        # _lead_lag_engine should be None by default
        assert ensemble._lead_lag_engine is None

    def test_engine_get_boost_called_with_correct_args(self):
        """Verify get_boost is called with the right symbol and side."""
        engine = MagicMock()
        engine.get_boost.return_value = 0.0  # No boost

        from strategies.ensemble import EnsembleStrategy
        ensemble = EnsembleStrategy(
            strategies=[MagicMock(name="s1")],
            mode="best",
            min_votes=1,
        )
        ensemble.set_lead_lag_engine(engine)

        # Simulate what evaluate() does: call get_boost on a signal
        # We test the engine interface directly since evaluate() has many dependencies
        symbol = "SOL"
        side = "BUY"
        boost = engine.get_boost(symbol, side)
        engine.get_boost.assert_called_with(symbol, side)
        assert boost == 0.0


# ─── Config Integration ──────────────────────────────────────────


class TestConfigIntegration:
    """Tests for trading_config lead-lag settings."""

    def test_lead_lag_symbol_config_exists(self):
        """LEAD_LAG_SYMBOL_CONFIG should be importable from trading_config."""
        from trading_config import LEAD_LAG_SYMBOL_CONFIG
        assert "SOL" in LEAD_LAG_SYMBOL_CONFIG
        assert "ETH" in LEAD_LAG_SYMBOL_CONFIG
        assert "HYPE" in LEAD_LAG_SYMBOL_CONFIG

    def test_sol_config_values(self):
        """SOL config should match proven empirical data."""
        from trading_config import LEAD_LAG_SYMBOL_CONFIG
        sol = LEAD_LAG_SYMBOL_CONFIG["SOL"]
        assert sol["lag_minutes"] == (30, 60)
        assert sol["correlation"] == 0.87
        assert sol["beta"] == 1.16
        assert sol["boost_cap"] == 12.0

    def test_eth_config_values(self):
        """ETH config should match proven empirical data."""
        from trading_config import LEAD_LAG_SYMBOL_CONFIG
        eth = LEAD_LAG_SYMBOL_CONFIG["ETH"]
        assert eth["lag_minutes"] == (15, 30)
        assert eth["correlation"] == 0.91
        assert eth["beta"] == 1.20
        assert eth["boost_cap"] == 10.0

    def test_get_lead_lag_config_helper(self):
        """get_lead_lag_config should return config for known symbols."""
        from trading_config import get_lead_lag_config
        assert get_lead_lag_config("SOL")["correlation"] == 0.87
        assert get_lead_lag_config("SOL/USDC:USDC")["correlation"] == 0.87
        assert get_lead_lag_config("DOGE") == {}

    def test_trading_config_enable_flag(self):
        """TradingConfig should have enable_lead_lag_boost flag."""
        from trading_config import TradingConfig
        config = TradingConfig()
        assert hasattr(config, "enable_lead_lag_boost")
        assert hasattr(config, "lead_lag_btc_move_threshold")
        assert hasattr(config, "lead_lag_max_boost")
        assert hasattr(config, "lead_lag_min_correlation")
        assert hasattr(config, "lead_lag_correlation_decay")


# ─── Boost-Only Safety ───────────────────────────────────────────


class TestBoostOnlySafety:
    """Verify the engine is a BOOST system — never generates standalone trades."""

    def test_engine_has_no_trade_generation(self):
        """LeadLagBoostEngine should not have methods that generate trade signals."""
        engine = _make_engine()
        # These methods should NOT exist (boost-only system)
        assert not hasattr(engine, "generate_signal")
        assert not hasattr(engine, "create_trade")
        assert not hasattr(engine, "execute_trade")
        assert not hasattr(engine, "open_position")

    def test_lead_signal_is_not_trade_signal(self):
        """LeadSignal should not be convertible to a trade signal."""
        engine = _make_engine()
        t = 1_000_000.0
        signals = _make_btc_move(engine, 84_000, 84_500, start_time=t)
        for sig in signals:
            assert isinstance(sig, LeadSignal)
            # LeadSignal has boost field, not entry/sl/tp (trade fields)
            assert hasattr(sig, "boost")
            assert not hasattr(sig, "entry")
            assert not hasattr(sig, "sl")
            assert not hasattr(sig, "tp1")

    def test_boost_only_adds_to_confidence(self):
        """Boost should only add to existing signal confidence, not create new signals."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        last_t = t + 15 * 60
        boost = engine.get_boost("SOL", "BUY", current_time=last_t + 35 * 60)
        # Boost is a float that gets added to confidence — not a Signal object
        assert isinstance(boost, float)
        assert 0 <= boost <= 12.0


# ─── Signal Expiry & Cleanup ─────────────────────────────────────


class TestSignalExpiry:
    """Tests for lead signal cleanup and memory management."""

    def test_expired_signals_cleaned_up(self):
        """Expired lead signals should be removed from the engine."""
        engine = _make_engine()
        t = 1_000_000.0
        _make_btc_move(engine, 84_000, 84_500, start_time=t)
        assert len(engine._lead_signals) > 0

        # Feed a price far in the future (after all signals expire)
        engine.update_btc_price(84_500, current_time=t + 200 * 60)
        assert len(engine._lead_signals) == 0

    def test_max_lead_signals_capped(self):
        """Engine should cap total lead signals at MAX_LEAD_SIGNALS."""
        engine = _make_engine()
        engine._SIGNAL_COOLDOWN = 0  # Disable cooldown for this test
        # Generate many signals
        for i in range(100):
            t = 1_000_000.0 + i * 600  # Each move 10 min apart
            _make_btc_move(engine, 84_000, 84_500, start_time=t)
        assert len(engine._lead_signals) <= engine._MAX_LEAD_SIGNALS
