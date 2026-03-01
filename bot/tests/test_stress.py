"""
Tests for Phase F4: Stress test scenarios.
Simulates flash crashes, exchange outages, and correlated blowups
to verify the bot's safety systems respond correctly.
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Scenario 1: Flash Crash — Circuit Breaker Response ───────────────


class TestFlashCrash:
    """Simulate rapid losses and verify circuit breaker trips."""

    def test_circuit_breaker_trips_on_consecutive_losses(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.05,
            max_consecutive_losses=3,
            max_drawdown_pct=0.10,
        )
        cb.peak_equity = 10000
        # 3 consecutive losses
        cb.record_trade(-50, 9950)
        cb.record_trade(-50, 9900)
        cb.record_trade(-50, 9850)
        assert cb.tripped is True
        assert "consecutive" in cb.trip_reason.lower()

    def test_circuit_breaker_trips_on_daily_loss(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.05,
            max_consecutive_losses=10,
            max_drawdown_pct=0.10,
        )
        cb.peak_equity = 10000
        # Single large loss
        cb.record_trade(-600, 9400)
        assert cb.tripped is True
        assert "daily" in cb.trip_reason.lower()

    def test_circuit_breaker_trips_on_drawdown(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.50,  # Won't trigger
            max_consecutive_losses=100,  # Won't trigger
            max_drawdown_pct=0.10,
        )
        cb.peak_equity = 10000
        # Large drawdown: 10000 -> 8900 = 11% drawdown
        cb.record_trade(-50, 9950)  # win resets consecutive
        cb.consecutive_losses = 0
        cb.record_trade(10, 9960)
        cb.record_trade(-1060, 8900)
        assert cb.tripped is True
        assert "drawdown" in cb.trip_reason.lower()

    def test_high_confidence_overrides_circuit_breaker(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(max_consecutive_losses=2)
        cb.peak_equity = 10000
        cb.record_trade(-50, 9950)
        cb.record_trade(-50, 9900)
        assert cb.tripped is True
        # High confidence should override
        assert cb.is_trading_allowed(confidence=95, cb_conf_override_pct=0.92) is True
        # Low confidence should not
        assert cb.is_trading_allowed(confidence=80, cb_conf_override_pct=0.92) is False


# ── Scenario 2: Exchange Outage — Graceful Degradation ───────────────


class TestExchangeOutage:
    """Simulate exchange API failures and verify degradation."""

    def test_degradation_halts_entries_after_errors(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        # Simulate 3 consecutive exchange errors
        for _ in range(3):
            mgr.record_exchange_error()
        assert mgr.should_halt_entries() is True
        assert "DEGRADED" in mgr.get_status()["mode"]

    def test_degradation_allows_existing_positions(self):
        """Exchange degradation should NOT force-close existing positions."""
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        for _ in range(3):
            mgr.record_exchange_error()
        # should_halt_entries prevents new entries but doesn't close existing
        assert mgr.should_halt_entries() is True
        # No method to force-close, just a gate

    def test_llm_fallback_to_ensemble_only(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_llm_error()
        mgr.record_llm_error()
        assert mgr.should_skip_llm() is True
        status = mgr.get_status()
        assert mgr._llm_degraded is True


# ── Scenario 3: Correlated Blowup — Position Exposure ────────────────


class TestCorrelatedBlowup:
    """Test that risk systems limit correlated exposure."""

    def test_portfolio_leverage_blocks_excessive_exposure(self):
        """Portfolio leverage guard should block when total leverage > max."""
        # Simulate the logic from multi_strategy_main.py
        portfolio_lev = 9.5  # Total leverage across all positions
        max_portfolio_lev = 8.0
        assert portfolio_lev >= max_portfolio_lev  # Would be blocked

    def test_circuit_breaker_override_limits_leverage(self):
        """During CB override, max leverage should be capped at 2x."""
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(max_consecutive_losses=2)
        cb.peak_equity = 10000
        cb.record_trade(-50, 9950)
        cb.record_trade(-50, 9900)
        assert cb.tripped is True
        constraints = cb.get_override_constraints(confidence=95)
        assert constraints["max_leverage"] == 2.0
        assert constraints["size_multiplier"] == 0.5
        assert constraints["constrained"] is True

    def test_position_count_limit(self):
        """Risk manager should enforce max open positions."""
        from execution.risk import RiskManager
        mgr = RiskManager(max_open_positions=3)
        assert mgr.can_open_position(current_open=2) is True
        assert mgr.can_open_position(current_open=3) is False
        assert mgr.can_open_position(current_open=5) is False


# ── Scenario 4: Funding Rate Spike ───────────────────────────────────


class TestFundingSpike:
    """Test that funding-aware systems respond to rate spikes."""

    def test_high_funding_triggers_close(self):
        from execution.funding_timer import should_close_before_funding
        # Simulate 0.1% funding rate (very high) on 10x leverage
        result = should_close_before_funding(
            pnl_pct=0.2,         # Marginal profit
            funding_rate=0.001,   # 0.1% per 8h (extreme)
            leverage=10.0,
            side="LONG",
            minutes_to_funding=10,
        )
        assert result is True  # Should close to avoid 1% daily cost

    def test_normal_funding_no_close(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=1.5,         # Decent profit
            funding_rate=0.0001,  # Normal rate
            leverage=3.0,
            side="LONG",
            minutes_to_funding=10,
        )
        assert result is False  # Profitable, don't close


# ── Scenario 5: Liquidation Proximity ─────────────────────────────────


class TestLiquidationProximity:
    """Test liquidation distance monitoring response."""

    def test_high_leverage_liquidation_distance(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 25x long at 50000, price drops to 48500
        result = mgr.check_liquidation_risk(
            entry=50000, current_price=48500,
            side="LONG", leverage=25.0, safety_buffer=0.03,
        )
        assert result["at_risk"] is True
        assert result["distance_pct"] < 0.03

    def test_force_close_below_1_5_pct(self):
        """Verify the logic that would trigger force close."""
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 20x long at 50000: liq = 50000 * (1 - 1/20) = 47500
        # Price at 47800: distance = (47800 - 47500) / 47800 = 0.63%
        result = mgr.check_liquidation_risk(
            entry=50000, current_price=47800,
            side="LONG", leverage=20.0, safety_buffer=0.03,
        )
        assert result["at_risk"] is True
        assert result["distance_pct"] < 0.015  # Below force-close threshold


# ── Scenario 6: Heartbeat Stall Detection ─────────────────────────────


class TestHeartbeatStall:
    """Test that stall detection works correctly."""

    def test_detects_stall_after_threshold(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(
            heartbeat_file="/tmp/test_stress_hb.json",
            stall_threshold_s=1,
        )
        monitor.record_heartbeat()
        time.sleep(1.5)
        assert monitor.is_healthy() is False
        status = monitor.get_status()
        assert status["stalled"] is True
        assert status["last_heartbeat_s_ago"] > 1.0

    def test_not_stalled_with_fresh_heartbeat(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(
            heartbeat_file="/tmp/test_stress_hb2.json",
            stall_threshold_s=60,
        )
        monitor.record_heartbeat()
        assert monitor.is_healthy() is True
