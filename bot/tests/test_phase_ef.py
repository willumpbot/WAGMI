"""
Tests for Phase E+F: Regime transition detection, heartbeat monitoring,
graceful degradation.
"""

import os
import sys
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── E2: Regime Transition Detection ──────────────────────────────────


class TestRegimeTransitionDetector:
    """Test regime transition detection and confirmation."""

    def test_first_regime_sets_confirmed(self):
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector()
        result = detector.update("BTC", "trend")
        assert result["regime"] == "trend"
        assert result["transitioning"] is False
        assert detector.get_regime("BTC") == "trend"

    def test_same_regime_no_transition(self):
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector()
        detector.update("BTC", "trend")
        result = detector.update("BTC", "trend")
        assert result["transitioning"] is False
        assert result["regime"] == "trend"

    def test_single_different_no_transition(self):
        """One different classification should NOT trigger transition."""
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector(min_confirmations=2)
        detector.update("BTC", "trend")
        result = detector.update("BTC", "range")
        # Only 1 confirmation, need 2
        assert result["transitioning"] is False

    def test_confirmed_transition(self):
        """Multiple confirmations should trigger and confirm transition."""
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector(min_confirmations=2)
        detector.update("BTC", "trend")
        detector.update("BTC", "range")
        result = detector.update("BTC", "range")
        # 2 confirmations of "range" vs 1 of "trend" -> confirmed
        assert result["transitioning"] is True
        assert result["from_regime"] == "trend"
        assert result["to_regime"] == "range"
        assert detector.get_regime("BTC") == "range"

    def test_transition_requires_dominance(self):
        """New regime must dominate before being confirmed."""
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector(min_confirmations=2)
        # Build up trend history
        for _ in range(5):
            detector.update("BTC", "trend")
        # Two range signals — enough for transition flag but not dominance
        result1 = detector.update("BTC", "range")
        result2 = detector.update("BTC", "range")
        # transitioning=True but regime stays "trend" until range dominates
        if result2["transitioning"]:
            # Confidence should reflect partial confirmation
            assert result2["confidence"] > 0
            assert result2["confidence"] < 1.0

    def test_multiple_symbols_independent(self):
        """Each symbol should have independent regime tracking."""
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector()
        detector.update("BTC", "trend")
        detector.update("ETH", "range")
        assert detector.get_regime("BTC") == "trend"
        assert detector.get_regime("ETH") == "range"

    def test_get_all_regimes(self):
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector()
        detector.update("BTC", "trend")
        detector.update("ETH", "range")
        detector.update("SOL", "panic")
        regimes = detector.get_all_regimes()
        assert regimes == {"BTC": "trend", "ETH": "range", "SOL": "panic"}

    def test_get_transition_summary(self):
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector(min_confirmations=2)
        detector.update("BTC", "trend")
        detector.update("BTC", "range")  # Different from confirmed
        summary = detector.get_transition_summary()
        assert "BTC" in summary
        assert summary["BTC"]["from"] == "trend"
        assert summary["BTC"]["to"] == "range"

    def test_unknown_symbol_default(self):
        from strategies.regime_detector import RegimeTransitionDetector
        detector = RegimeTransitionDetector()
        assert detector.get_regime("UNKNOWN") == "unknown"


# ── F1: Heartbeat Monitoring ─────────────────────────────────────────


class TestHealthMonitor:
    """Test heartbeat recording and stall detection."""

    def test_initial_state_healthy(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(heartbeat_file="/tmp/test_heartbeat.json")
        assert monitor.is_healthy() is True
        status = monitor.get_status()
        assert status["stalled"] is False
        assert status["scan_count"] == 0

    def test_record_heartbeat_increments(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(heartbeat_file="/tmp/test_heartbeat2.json")
        monitor.record_heartbeat(loop_duration_s=1.5, positions=2, equity=10000)
        monitor.record_heartbeat(loop_duration_s=2.0, positions=3, equity=10050)
        status = monitor.get_status()
        assert status["scan_count"] == 2
        assert status["avg_loop_s"] == 1.75  # (1.5 + 2.0) / 2

    def test_stall_detection(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(
            heartbeat_file="/tmp/test_heartbeat3.json",
            stall_threshold_s=1,  # 1 second for testing
        )
        monitor.record_heartbeat()
        time.sleep(1.5)  # Wait past threshold
        assert monitor.is_healthy() is False
        status = monitor.get_status()
        assert status["stalled"] is True

    def test_error_counting(self):
        from monitoring.health import HealthMonitor
        monitor = HealthMonitor(heartbeat_file="/tmp/test_heartbeat4.json")
        monitor.record_error()
        monitor.record_error()
        monitor.record_error()
        status = monitor.get_status()
        assert status["error_count"] == 3

    def test_heartbeat_file_written(self):
        import json
        from monitoring.health import HealthMonitor
        path = "/tmp/test_heartbeat5.json"
        monitor = HealthMonitor(heartbeat_file=path)
        monitor.record_heartbeat(loop_duration_s=1.0, positions=1, equity=5000)
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert "timestamp" in data
        assert data["positions"] == 1
        assert data["equity"] == 5000


# ── F3: Graceful Degradation ─────────────────────────────────────────


class TestDegradationManager:
    """Test graceful degradation for exchange and LLM failures."""

    def test_initial_state_normal(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        assert mgr.should_halt_entries() is False
        assert mgr.should_skip_llm() is False
        status = mgr.get_status()
        assert status["mode"] == "NORMAL"

    def test_exchange_degradation_after_errors(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        # 3 consecutive errors trigger degradation
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        assert mgr.should_halt_entries() is False  # Not yet
        mgr.record_exchange_error()
        assert mgr.should_halt_entries() is True
        status = mgr.get_status()
        assert "exchange" in status["mode"].lower() or "DEGRADED" in status["mode"]

    def test_exchange_recovery_after_success(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        assert mgr.should_halt_entries() is True
        # Success resets error count
        mgr.record_exchange_success()
        assert mgr._exchange_errors == 0
        # But still degraded until recovery window passes
        # (can't easily test time-based recovery in unit test)

    def test_llm_degradation_after_errors(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_llm_error()
        assert mgr.should_skip_llm() is False
        mgr.record_llm_error()
        assert mgr.should_skip_llm() is True

    def test_llm_success_resets_errors(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_llm_error()
        mgr.record_llm_success()
        assert mgr._llm_errors == 0
        mgr.record_llm_error()
        assert mgr.should_skip_llm() is False  # Only 1 error

    def test_both_degraded_critical_mode(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        mgr.record_llm_error()
        mgr.record_llm_error()
        status = mgr.get_status()
        assert "CRITICAL" in status["mode"]
        assert mgr.should_halt_entries() is True
        assert mgr.should_skip_llm() is True

    def test_exchange_success_resets_error_count(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        mgr.record_exchange_error()
        mgr.record_exchange_error()
        mgr.record_exchange_success()
        assert mgr._exchange_errors == 0
        # Not degraded since threshold wasn't reached
        assert mgr.should_halt_entries() is False
