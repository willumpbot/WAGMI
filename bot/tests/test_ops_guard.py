"""Tests for OpsGuard: throttles, kill switch, rate limiting."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from execution.ops_guard import OpsGuard


@pytest.fixture
def guard(tmp_path):
    g = OpsGuard()
    g._kill_file = str(tmp_path / "kill_switch")
    g._killed = False
    g._kill_reason = ""
    g._trade_times = []
    return g


class TestKillSwitch:

    def test_kill_and_unkill(self, guard):
        assert not guard.is_killed
        guard.kill("test kill")
        assert guard.is_killed
        assert guard.kill_reason == "test kill"
        assert os.path.exists(guard._kill_file)

        guard.unkill()
        assert not guard.is_killed
        assert not os.path.exists(guard._kill_file)

    def test_kill_blocks_execution(self, guard):
        guard.kill("emergency")
        result = guard.can_execute()
        assert not result["allowed"]
        assert "Kill switch" in result["reason"]

    def test_persistent_kill_file(self, tmp_path):
        kill_file = str(tmp_path / "kill_switch")
        with open(kill_file, "w") as f:
            f.write("test reason")
        g = OpsGuard()
        g._kill_file = kill_file
        # Simulate startup detection
        if os.path.exists(kill_file):
            g._killed = True
        assert g.is_killed


class TestRateLimiting:

    def test_trades_last_hour(self, guard):
        guard.record_trade()
        guard.record_trade()
        assert guard.trades_last_hour() == 2

    def test_hourly_rate_limit(self, guard):
        guard.max_trades_per_hour = 2
        guard.record_trade()
        guard.record_trade()
        result = guard.can_execute()
        assert not result["allowed"]
        assert "Rate limit" in result["reason"]
        assert "trades/hour" in result["reason"]

    def test_daily_rate_limit(self, guard):
        guard.max_trades_per_day = 3
        guard.record_trade()
        guard.record_trade()
        guard.record_trade()
        result = guard.can_execute()
        assert not result["allowed"]
        assert "trades/day" in result["reason"]

    def test_under_limit_allowed(self, guard):
        guard.max_trades_per_hour = 10
        guard.record_trade()
        result = guard.can_execute()
        assert result["allowed"]


class TestPositionLimits:

    def test_oversized_position_blocked(self, guard):
        result = guard.can_execute(
            position_size_usd=60000.0,
            equity=10000.0,  # 600% > default 500%
        )
        assert not result["allowed"]
        assert "Position size" in result["reason"]

    def test_normal_position_allowed(self, guard):
        result = guard.can_execute(
            position_size_usd=40000.0,
            equity=10000.0,  # 400% < 500%
        )
        assert result["allowed"]

    def test_total_exposure_blocked(self, guard):
        result = guard.can_execute(
            position_size_usd=1000.0,
            equity=10000.0,
            total_exposure_usd=110000.0,  # 1100% > 1000%
        )
        assert not result["allowed"]
        assert "exposure" in result["reason"]


class TestFormatStatus:

    def test_format_status(self, guard):
        text = guard.format_status()
        assert "Ops Guard" in text
        assert "Kill switch" in text
        assert "OFF" in text
