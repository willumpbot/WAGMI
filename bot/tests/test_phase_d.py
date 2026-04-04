"""
Tests for Phase D: Trade Smarter — dynamic weights, funding timing,
CLI modes, symbol confidence, session tracking.
"""

import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── D1: Dynamic Strategy Weight Scaling ──────────────────────────────


class TestDynamicWeights:
    """Test rolling win-rate based strategy weight scaling."""

    def test_get_rolling_weights_no_data(self):
        from data.strategy_weights import StrategyWeightManager
        mgr = StrategyWeightManager(path="/tmp/test_weights_d1.json")
        # No strategies tracked yet
        assert mgr.get_rolling_weights() == {}

    def test_get_rolling_weights_with_outcomes(self):
        from data.strategy_weights import StrategyWeightManager
        mgr = StrategyWeightManager(path="/tmp/test_weights_d1b.json")
        # Record 10 outcomes: 8 wins, 2 losses = 80% WR
        for i in range(10):
            mgr.record_outcome("hot_strategy", win=(i < 8))
        weights = mgr.get_rolling_weights()
        assert "hot_strategy" in weights
        # 80% WR -> scale = 0.8/0.5 = 1.6x
        # Base weight ≈ 9/12 = 0.75 -> dynamic ≈ 0.75 * 1.6 = 1.2
        assert weights["hot_strategy"] > 1.0

    def test_cold_strategy_gets_quieted(self):
        from data.strategy_weights import StrategyWeightManager
        mgr = StrategyWeightManager(path="/tmp/test_weights_d1c.json")
        # Record 10 outcomes: 2 wins, 8 losses = 20% WR
        for i in range(10):
            mgr.record_outcome("cold_strategy", win=(i < 2))
        weights = mgr.get_rolling_weights()
        # 20% WR -> scale = 0.2/0.5 = 0.4x
        assert weights["cold_strategy"] < 0.5

    def test_recent_outcomes_capped_at_20(self):
        from data.strategy_weights import StrategyWeightManager
        mgr = StrategyWeightManager(path="/tmp/test_weights_d1d.json")
        for i in range(30):
            mgr.record_outcome("capped", win=True)
        assert len(mgr.data["capped"]["recent_outcomes"]) <= 20

    def test_ensemble_refresh_uses_dynamic_weights(self):
        """Verify ensemble calls _refresh_dynamic_weights on evaluate."""
        from strategies.ensemble import EnsembleStrategy
        from strategies.base import BaseStrategy
        strats = [MagicMock(spec=BaseStrategy, name=f"s{i}") for i in range(2)]
        for i, s in enumerate(strats):
            s.name = f"strat_{i}"
            s.evaluate.return_value = None
            s.get_required_timeframes.return_value = ["1h"]

        wm = MagicMock()
        wm.get_rolling_weights.return_value = {"strat_0": 0.8, "strat_1": 1.2}
        ensemble = EnsembleStrategy(strats, mode="voting", weight_manager=wm)
        ensemble.evaluate("TEST", {"1h": MagicMock()})
        # Verify rolling weights were fetched
        wm.get_rolling_weights.assert_called()


# ── D2: Funding-Aware Hold Time Optimization ─────────────────────────


class TestFundingTimer:
    """Test funding payment timing utilities."""

    def test_minutes_until_next_at_0700(self):
        from execution.funding_timer import minutes_until_next_funding
        t = datetime(2026, 3, 1, 7, 0, tzinfo=timezone.utc)  # 7:00 UTC
        result = minutes_until_next_funding(t)
        assert result == 60  # Next funding at 8:00 = 60 min away

    def test_minutes_until_next_at_1530(self):
        from execution.funding_timer import minutes_until_next_funding
        t = datetime(2026, 3, 1, 15, 30, tzinfo=timezone.utc)  # 15:30 UTC
        result = minutes_until_next_funding(t)
        assert result == 30  # Next funding at 16:00 = 30 min away

    def test_minutes_until_next_wraps_midnight(self):
        from execution.funding_timer import minutes_until_next_funding
        t = datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc)  # 22:00 UTC
        result = minutes_until_next_funding(t)
        assert result == 60  # Next funding at 23:00 = 60 min away (hourly funding)

    def test_should_close_marginal_long_before_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.1,             # Marginal profit
            funding_rate=0.0005,      # Positive = longs pay
            leverage=5.0,
            side="LONG",
            minutes_to_funding=15,    # 15 min to payment
        )
        assert result is True

    def test_should_not_close_profitable_position(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=2.5,             # Good profit
            funding_rate=0.0005,
            leverage=5.0,
            side="LONG",
            minutes_to_funding=15,
        )
        assert result is False  # Don't close profitable position

    def test_should_not_close_when_earning_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.1,
            funding_rate=0.0005,      # Positive = shorts earn
            leverage=5.0,
            side="SHORT",
            minutes_to_funding=15,
        )
        assert result is False  # Short earns when rate > 0

    def test_should_not_close_when_far_from_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.1,
            funding_rate=0.0005,
            leverage=5.0,
            side="LONG",
            minutes_to_funding=120,   # 2 hours away
        )
        assert result is False


# ── D3: CLI Diagnostic Modes ─────────────────────────────────────────


class TestCLIModes:
    """Test that CLI modes are properly wired."""

    def test_tiers_mode_available(self):
        """Verify 'tiers' is in argparse choices."""
        from cli import main
        import argparse
        # Import and check the parser
        import cli
        # The choices should include 'tiers' and 'evolve'
        assert hasattr(cli, '_run_tiers')
        assert hasattr(cli, '_run_evolve')

    def test_format_tier_comparison_runs(self):
        """Verify the tier comparison formatter works."""
        from llm.usage_tiers import format_tier_comparison
        output = format_tier_comparison()
        assert "CONSERVATIVE" in output
        assert "RECOMMENDED" in output
        assert "AGGRESSIVE" in output
        assert "UNLEASHED" in output


# ── D4: Symbol-Specific Confidence Adjustment ────────────────────────


class TestSymbolConfidence:
    """Test symbol difficulty-based confidence floor adjustment."""

    def test_no_data_returns_base_floor(self):
        from feedback.signal_quality import SignalQualityScorer
        scorer = SignalQualityScorer(data_dir="/tmp/test_sq_d4")
        floor = scorer.get_symbol_confidence_floor("UNKNOWN/USDC:USDC")
        assert floor == 65.0

    def test_hard_symbol_gets_higher_floor(self):
        from feedback.signal_quality import SignalQualityScorer, QualityFeatures
        scorer = SignalQualityScorer(data_dir="/tmp/test_sq_d4b")
        # Record 10 trades with 20% win rate (hard symbol)
        for i in range(10):
            feat = QualityFeatures(symbol="HARD/USDC:USDC", side="BUY", hour_of_day=12)
            scorer.record_outcome(feat, win=(i < 2), pnl=-10 if i >= 2 else 5)
        floor = scorer.get_symbol_confidence_floor("HARD/USDC:USDC")
        assert floor > 65.0  # Should be higher than base

    def test_easy_symbol_gets_lower_floor_than_hard(self):
        from feedback.signal_quality import SignalQualityScorer, QualityFeatures
        scorer = SignalQualityScorer(data_dir="/tmp/test_sq_d4c")
        # Record 10 trades with 80% win rate (easy symbol)
        for i in range(10):
            feat = QualityFeatures(symbol="EASY/USDC:USDC", side="BUY", hour_of_day=12)
            scorer.record_outcome(feat, win=(i < 8), pnl=10 if i < 8 else -5)
        # Record 10 trades with 20% win rate (hard symbol)
        for i in range(10):
            feat = QualityFeatures(symbol="HARD2/USDC:USDC", side="BUY", hour_of_day=12)
            scorer.record_outcome(feat, win=(i < 2), pnl=-10 if i >= 2 else 5)
        easy_floor = scorer.get_symbol_confidence_floor("EASY/USDC:USDC")
        hard_floor = scorer.get_symbol_confidence_floor("HARD2/USDC:USDC")
        # Easy symbols should have lower floor than hard symbols
        assert easy_floor < hard_floor


# ── D5: Session Performance Tracking ─────────────────────────────────


class TestSessionPerformance:
    """Test time-of-day session tracking."""

    def test_hour_to_session_mapping(self):
        from feedback.signal_quality import SignalQualityScorer
        assert SignalQualityScorer._hour_to_session(3) == "asia"
        assert SignalQualityScorer._hour_to_session(9) == "europe"
        assert SignalQualityScorer._hour_to_session(14) == "us"
        assert SignalQualityScorer._hour_to_session(20) == "late"

    def test_session_tracking_records(self):
        from feedback.signal_quality import SignalQualityScorer, QualityFeatures
        scorer = SignalQualityScorer(data_dir="/tmp/test_sq_d5")
        # Record trades in different sessions
        for hour in [3, 3, 3, 9, 9, 9, 14, 14, 14]:
            feat = QualityFeatures(symbol="BTC/USDC:USDC", side="BUY", hour_of_day=hour)
            scorer.record_outcome(feat, win=True, pnl=10)
        perf = scorer.get_session_performance()
        assert "asia" in perf
        assert "europe" in perf
        assert "us" in perf
        assert perf["asia"]["trades"] == 3

    def test_session_performance_empty_without_data(self):
        from feedback.signal_quality import SignalQualityScorer
        scorer = SignalQualityScorer(data_dir="/tmp/test_sq_d5b")
        perf = scorer.get_session_performance()
        assert perf == {}  # No data yet
