"""
Tests for cross-asset lead-lag alert module.

Verifies BTC move detection, beta-adjusted follower predictions,
cooldown logic, prediction evaluation, and edge cases.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.cross_asset_alert import (
    CrossAssetLeadLagMonitor,
    BETA_SOL,
    BETA_ETH,
    BTC_MOVE_THRESHOLD,
)


# ─── Helpers ──────────────────────────────────────────────────────


def _make_prices(start: float, end: float, n: int = 4) -> list:
    """Generate a linear price series from start to end with n points."""
    if n < 2:
        return [end]
    step = (end - start) / (n - 1)
    return [start + step * i for i in range(n)]


# ─── Tests ────────────────────────────────────────────────────────


class TestBTCMoveDetection:
    """Tests for detecting decisive BTC moves."""

    def test_no_alert_below_threshold(self):
        """BTC move below 0.3% should not trigger an alert."""
        monitor = CrossAssetLeadLagMonitor()
        # 0.1% move (below threshold)
        prices = _make_prices(100_000, 100_100, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is False
        assert result["recommended_side"] == "NONE"

    def test_alert_above_threshold_up(self):
        """BTC move above 0.3% upward should trigger LONG alert."""
        monitor = CrossAssetLeadLagMonitor()
        # ~0.5% move up
        prices = _make_prices(100_000, 100_500, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        assert result["recommended_side"] == "LONG"
        assert result["btc_move_pct"] > 0

    def test_alert_above_threshold_down(self):
        """BTC move above 0.3% downward should trigger SHORT alert."""
        monitor = CrossAssetLeadLagMonitor()
        # ~0.5% move down
        prices = _make_prices(100_000, 99_500, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        assert result["recommended_side"] == "SHORT"
        assert result["btc_move_pct"] < 0


class TestBetaCalculations:
    """Tests for follower move predictions using beta multipliers."""

    def test_sol_beta_applied(self):
        """Expected SOL move should be BTC move * SOL beta."""
        monitor = CrossAssetLeadLagMonitor()
        # 1% BTC move
        prices = _make_prices(100_000, 101_000, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        expected_sol = result["btc_move_pct"] * BETA_SOL
        assert abs(result["expected_sol_move"] - round(expected_sol, 4)) < 0.001

    def test_eth_beta_applied(self):
        """Expected ETH move should be BTC move * ETH beta."""
        monitor = CrossAssetLeadLagMonitor()
        prices = _make_prices(100_000, 101_000, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        expected_eth = result["btc_move_pct"] * BETA_ETH
        assert abs(result["expected_eth_move"] - round(expected_eth, 4)) < 0.001

    def test_custom_beta_values(self):
        """Custom beta values should override defaults."""
        monitor = CrossAssetLeadLagMonitor(beta_sol=2.0, beta_eth=1.5)
        prices = _make_prices(100_000, 101_000, n=4)
        result = monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        assert abs(result["expected_sol_move"] - result["btc_move_pct"] * 2.0) < 0.001
        assert abs(result["expected_eth_move"] - result["btc_move_pct"] * 1.5) < 0.001


class TestCooldown:
    """Tests for alert cooldown logic."""

    def test_cooldown_suppresses_second_alert(self):
        """Second alert within cooldown window should be suppressed."""
        monitor = CrossAssetLeadLagMonitor()
        prices = _make_prices(100_000, 101_000, n=4)
        t = 1000000.0

        r1 = monitor.check_btc_lead(prices, 150.0, 2000.0, current_time=t)
        assert r1["alert"] is True

        # Same move 60s later -- should be suppressed by cooldown
        r2 = monitor.check_btc_lead(prices, 150.0, 2000.0, current_time=t + 60)
        assert r2["alert"] is False

    def test_alert_fires_after_cooldown(self):
        """Alert should fire again after cooldown expires."""
        monitor = CrossAssetLeadLagMonitor()
        prices = _make_prices(100_000, 101_000, n=4)
        t = 1000000.0

        r1 = monitor.check_btc_lead(prices, 150.0, 2000.0, current_time=t)
        assert r1["alert"] is True

        # After cooldown (default 300s)
        r2 = monitor.check_btc_lead(prices, 150.0, 2000.0, current_time=t + 301)
        assert r2["alert"] is True


class TestPredictionEvaluation:
    """Tests for prediction tracking and accuracy scoring."""

    def test_correct_prediction_tracked(self):
        """Prediction should be marked correct when SOL/ETH move in predicted direction."""
        monitor = CrossAssetLeadLagMonitor(eval_window=60)
        prices = _make_prices(100_000, 101_000, n=4)
        t = 1000000.0

        # Trigger alert
        monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0, current_time=t)

        # After eval window: SOL and ETH moved UP (correct for LONG prediction)
        monitor.check_btc_lead(
            [100_500, 100_500],  # no new alert (below threshold)
            sol_price=152.0,  # up from 150
            eth_price=2030.0,  # up from 2000
            current_time=t + 120,
        )

        stats = monitor.get_stats()
        assert stats["total_predictions"] == 1
        assert stats["sol_accuracy"] == 1.0
        assert stats["eth_accuracy"] == 1.0

    def test_wrong_prediction_tracked(self):
        """Prediction should be marked wrong when followers move opposite."""
        monitor = CrossAssetLeadLagMonitor(eval_window=60)
        prices = _make_prices(100_000, 101_000, n=4)
        t = 1000000.0

        # Trigger LONG alert
        monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0, current_time=t)

        # After eval window: SOL and ETH moved DOWN (wrong for LONG)
        monitor.check_btc_lead(
            [100_500, 100_500],
            sol_price=148.0,
            eth_price=1970.0,
            current_time=t + 120,
        )

        stats = monitor.get_stats()
        assert stats["total_predictions"] == 1
        assert stats["sol_accuracy"] == 0.0
        assert stats["eth_accuracy"] == 0.0

    def test_pending_predictions_not_evaluated_early(self):
        """Predictions should not be evaluated before the eval window."""
        monitor = CrossAssetLeadLagMonitor(eval_window=3600)
        prices = _make_prices(100_000, 101_000, n=4)
        t = 1000000.0

        monitor.check_btc_lead(prices, sol_price=150.0, eth_price=2000.0, current_time=t)

        # Check 10 seconds later -- too early for evaluation
        monitor.check_btc_lead(
            [100_500, 100_500], sol_price=155.0, eth_price=2050.0, current_time=t + 10,
        )

        stats = monitor.get_stats()
        assert stats["total_predictions"] == 0
        assert stats["pending_evaluations"] == 1


class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_insufficient_prices(self):
        """Should return no alert with fewer than 2 price points."""
        monitor = CrossAssetLeadLagMonitor()
        result = monitor.check_btc_lead([100_000], sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is False

    def test_empty_prices(self):
        """Should handle empty price list gracefully."""
        monitor = CrossAssetLeadLagMonitor()
        result = monitor.check_btc_lead([], sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is False

    def test_zero_start_price(self):
        """Should handle zero start price without division error."""
        monitor = CrossAssetLeadLagMonitor()
        result = monitor.check_btc_lead([0, 100], sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is False

    def test_reset_clears_state(self):
        """Reset should clear all predictions and stats."""
        monitor = CrossAssetLeadLagMonitor(eval_window=1)
        prices = _make_prices(100_000, 101_000, n=4)
        monitor.check_btc_lead(prices, 150.0, 2000.0, current_time=1000.0)
        monitor.check_btc_lead([100_000, 100_000], 152.0, 2030.0, current_time=1100.0)
        assert monitor.get_stats()["total_predictions"] == 1

        monitor.reset()
        stats = monitor.get_stats()
        assert stats["total_predictions"] == 0
        assert stats["pending_evaluations"] == 0

    def test_only_uses_lookback_window(self):
        """Should only use the last N+1 prices, not the entire list."""
        monitor = CrossAssetLeadLagMonitor(lookback_candles=3)
        # Long price history, but only last 4 matter
        old_prices = [90_000] * 20
        recent = _make_prices(100_000, 101_000, n=4)
        all_prices = old_prices + recent
        result = monitor.check_btc_lead(all_prices, sol_price=150.0, eth_price=2000.0)
        assert result["alert"] is True
        # The move should be ~1%, not the drop from 90k to 101k
        assert 0.9 < result["btc_move_pct"] < 1.1

    def test_result_dict_has_all_keys(self):
        """Result dict should always contain all expected keys."""
        monitor = CrossAssetLeadLagMonitor()
        result = monitor.check_btc_lead([], sol_price=0.0, eth_price=0.0)
        expected_keys = {
            "alert", "btc_move_pct", "expected_sol_move",
            "expected_eth_move", "recommended_side", "prediction_stats",
        }
        assert set(result.keys()) == expected_keys
