"""
Tests for the feedback loop closers (Phase 6):
- LLM Self-Performance Tracker
- Veto Counterfactual Validator
- Cost Tracker with Auto-Downgrade
- Operator Channel
- CB Override Constraints
- Signal Quality LLM Agreement
- Portfolio Correlation Guard
"""

import json
import os
import time
import tempfile
import pytest
from unittest.mock import patch, MagicMock


# ── Self-Performance Tracker ────────────────────────────────────────

class TestSelfPerformance:
    """Test LLM self-performance stat computation."""

    def test_empty_stats(self):
        from llm.self_performance import _empty_stats
        stats = _empty_stats()
        assert stats["accuracy"] == 0.5
        assert stats["total_decisions"] == 0
        assert stats["streak"] == ""

    def test_win_rate_calculation(self):
        from llm.self_performance import _win_rate
        outcomes = [
            {"win": True}, {"win": True}, {"win": False},
            {"win": True}, {"win": False},
        ]
        assert _win_rate(outcomes) == pytest.approx(0.6)

    def test_win_rate_empty(self):
        from llm.self_performance import _win_rate
        assert _win_rate([]) == 0.5

    def test_veto_win_rate(self):
        from llm.self_performance import _veto_win_rate
        # 3 correct vetoes (signal would have lost), 1 incorrect
        outcomes = [
            {"would_have_won": False},
            {"would_have_won": False},
            {"would_have_won": False},
            {"would_have_won": True},
        ]
        assert _veto_win_rate(outcomes) == pytest.approx(0.75)

    def test_calibration(self):
        from llm.self_performance import _compute_calibration
        # Stated confidence 0.8 average, actual win rate 0.6
        outcomes = [
            {"decision": {"confidence": 0.8}, "win": True},
            {"decision": {"confidence": 0.8}, "win": True},
            {"decision": {"confidence": 0.8}, "win": True},
            {"decision": {"confidence": 0.8}, "win": False},
            {"decision": {"confidence": 0.8}, "win": False},
        ]
        cal = _compute_calibration(outcomes)
        assert cal == pytest.approx(0.2, abs=0.01)  # 0.8 - 0.6 = 0.2

    def test_streak_computation(self):
        from llm.self_performance import _compute_streak
        outcomes = [
            {"decision": {"ts": 1}, "win": True},
            {"decision": {"ts": 2}, "win": False},
            {"decision": {"ts": 3}, "win": True},
            {"decision": {"ts": 4}, "win": True},
            {"decision": {"ts": 5}, "win": False},
        ]
        streak = _compute_streak(outcomes)
        assert streak == "WLWWL"

    def test_streak_empty(self):
        from llm.self_performance import _compute_streak
        assert _compute_streak([]) == ""

    def test_regime_accuracy(self):
        from llm.self_performance import _compute_regime_accuracy
        outcomes = [
            {"regime": "trend", "win": True},
            {"regime": "trend", "win": True},
            {"regime": "trend", "win": False},
            {"regime": "range", "win": False},
            {"regime": "range", "win": False},
            {"regime": "range", "win": True},
        ]
        acc, counts = _compute_regime_accuracy(outcomes)
        assert counts["trend"] == 3
        assert counts["range"] == 3
        assert acc["trend"] == pytest.approx(2/3, abs=0.01)
        assert acc["range"] == pytest.approx(1/3, abs=0.01)

    def test_compact_stats_empty(self):
        from llm.self_performance import get_compact_stats
        # With no decisions file, should return empty dict
        with patch("llm.self_performance._DECISIONS_PATH", "/nonexistent/path"):
            import llm.self_performance as sp
            sp._cached_stats = None
            sp._cached_at = 0
            result = get_compact_stats()
            assert result == {} or result.get("n", 0) < 5


# ── Veto Tracker ────────────────────────────────────────────────────

class TestVetoTracker:
    """Test veto counterfactual tracking."""

    def test_record_veto(self, tmp_path):
        from llm.veto_tracker import VetoTracker
        tracker = VetoTracker()
        tracker._pending = []
        tracker._resolved = []

        tracker.record_veto(
            symbol="BTC/USDT",
            side="LONG",
            entry_price=50000.0,
            sl_price=49000.0,
            tp1_price=52000.0,
            confidence=75.0,
            llm_confidence=0.3,
            llm_reason="Weak setup in range market",
            regime="range",
        )

        assert len(tracker._pending) == 1
        assert tracker._pending[0].symbol == "BTC/USDT"
        assert tracker._pending[0].side == "LONG"
        assert tracker._pending[0].outcome == "PENDING"

    def test_evaluate_long_win(self):
        from llm.veto_tracker import VetoTracker, VetoRecord
        tracker = VetoTracker()
        record = VetoRecord(
            symbol="BTC/USDT", side="LONG",
            entry_price=50000.0, sl_price=49000.0, tp1_price=52000.0,
        )
        # Price went to TP1
        assert tracker._evaluate_outcome(record, 52500.0) == "WOULD_WIN"

    def test_evaluate_long_lose(self):
        from llm.veto_tracker import VetoTracker, VetoRecord
        tracker = VetoTracker()
        record = VetoRecord(
            symbol="BTC/USDT", side="LONG",
            entry_price=50000.0, sl_price=49000.0, tp1_price=52000.0,
        )
        # Price went to SL
        assert tracker._evaluate_outcome(record, 48500.0) == "WOULD_LOSE"

    def test_evaluate_short_win(self):
        from llm.veto_tracker import VetoTracker, VetoRecord
        tracker = VetoTracker()
        record = VetoRecord(
            symbol="ETH/USDT", side="SHORT",
            entry_price=3000.0, sl_price=3200.0, tp1_price=2800.0,
        )
        # Price went below TP1
        assert tracker._evaluate_outcome(record, 2700.0) == "WOULD_WIN"

    def test_evaluate_short_lose(self):
        from llm.veto_tracker import VetoTracker, VetoRecord
        tracker = VetoTracker()
        record = VetoRecord(
            symbol="ETH/USDT", side="SHORT",
            entry_price=3000.0, sl_price=3200.0, tp1_price=2800.0,
        )
        # Price went above SL
        assert tracker._evaluate_outcome(record, 3300.0) == "WOULD_LOSE"

    def test_stats_empty(self):
        from llm.veto_tracker import VetoTracker
        tracker = VetoTracker()
        tracker._pending = []
        tracker._resolved = []
        stats = tracker.get_stats()
        assert stats["pending"] == 0
        assert stats["resolved"] == 0

    def test_stats_with_data(self):
        from llm.veto_tracker import VetoTracker
        tracker = VetoTracker()
        tracker._pending = []
        tracker._resolved = [
            {"outcome": "WOULD_LOSE", "symbol": "BTC"},
            {"outcome": "WOULD_LOSE", "symbol": "ETH"},
            {"outcome": "WOULD_WIN", "symbol": "SOL"},
        ]
        stats = tracker.get_stats()
        assert stats["resolved"] == 3
        assert stats["would_lose"] == 2
        assert stats["would_win"] == 1
        assert stats["veto_accuracy"] == pytest.approx(2/3, abs=0.01)


# ── Cost Tracker ────────────────────────────────────────────────────

class TestCostTracker:
    """Test LLM API cost tracking and model downgrade."""

    def test_record_call(self):
        from llm.cost_tracker import CostTracker
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 0.0
        tracker._calls_today = 0

        # Sonnet call: 1000 input, 500 output
        # Cost: (1000/1M)*3 + (500/1M)*15 = 0.003 + 0.0075 = 0.0105
        tracker.record_call(1000, 500, "claude-sonnet-4-5-20250929")
        assert tracker._today_spend == pytest.approx(0.0105, abs=0.001)
        assert tracker._calls_today == 1

    def test_no_downgrade_under_budget(self):
        from llm.cost_tracker import CostTracker, _MODEL_OPUS
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 5.0  # 20% of budget
        model = tracker.get_safe_model(_MODEL_OPUS, "PRE_TRADE")
        assert model == _MODEL_OPUS

    def test_soft_limit_downgrades_non_critical(self):
        from llm.cost_tracker import CostTracker, _MODEL_OPUS, _MODEL_SONNET
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 18.0  # 72% of budget > soft limit 70%
        # Non-critical trigger should downgrade
        model = tracker.get_safe_model(_MODEL_OPUS, "PERIODIC")
        assert model == _MODEL_SONNET

    def test_soft_limit_keeps_critical(self):
        from llm.cost_tracker import CostTracker, _MODEL_OPUS
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 18.0  # 72% > soft limit
        # Critical trigger keeps model
        model = tracker.get_safe_model(_MODEL_OPUS, "PRE_TRADE")
        assert model == _MODEL_OPUS

    def test_hard_limit_forces_haiku(self):
        from llm.cost_tracker import CostTracker, _MODEL_OPUS, _MODEL_HAIKU
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 23.0  # 92% > hard limit 90%
        # Even critical triggers go to Haiku
        model = tracker.get_safe_model(_MODEL_OPUS, "PRE_TRADE")
        assert model == _MODEL_HAIKU

    def test_daily_reset(self):
        from llm.cost_tracker import CostTracker
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 20.0
        tracker._calls_today = 100
        tracker._today_date = "2025-01-01"  # Old date
        tracker._maybe_reset_daily()
        assert tracker._today_spend == 0.0
        assert tracker._calls_today == 0

    def test_budget_used_pct(self):
        from llm.cost_tracker import CostTracker
        tracker = CostTracker(daily_budget=25.0)
        tracker._today_spend = 12.5
        assert tracker.get_budget_used_pct() == pytest.approx(0.5)


# ── Operator Channel ────────────────────────────────────────────────

class TestOperatorChannel:
    """Test operational anomaly detection and messaging."""

    def test_no_issues_in_normal_state(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 1,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 20,
            "budget_used_pct": 0.30,
            "correlation_risk": "low",
            "hours_since_last_trade": 2,
            "signals_generated": 5,
            "estimated_daily_funding_cost": 0.1,
        })
        assert len(issues) == 0

    def test_loss_streak_detection(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 5,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 20,
        })
        assert any(i["category"] == "performance" for i in issues)

    def test_llm_accuracy_alert(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.35,
            "llm_decisions_count": 20,
        })
        assert any(i["category"] == "llm_performance" for i in issues)

    def test_budget_warning(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "budget_used_pct": 0.85,
        })
        assert any(i["category"] == "cost" for i in issues)

    def test_correlation_overload(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "correlation_risk": "high",
        })
        assert any(i["category"] == "risk" for i in issues)

    def test_inactivity_detection(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "hours_since_last_trade": 12,
            "signals_generated": 20,
        })
        assert any(i["category"] == "activity" for i in issues)

    def test_funding_bleeding(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "estimated_daily_funding_cost": 0.8,
        })
        assert any(i["category"] == "funding" for i in issues)

    def test_dedup_suppresses_repeat(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        # First call should send
        channel._last_sent_by_category = {}
        channel._last_check = 0  # Force check
        channel.check_and_report({"consecutive_losses": 5})

        # Second call within window should NOT send again
        sent_count_before = len(channel._message_log)
        channel._last_check = 0  # Force check
        channel.check_and_report({"consecutive_losses": 5})
        assert len(channel._message_log) == sent_count_before

    def test_flip_failure_detection(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "flip_success_rate": 0.20,
            "flip_count": 10,
        })
        assert any(i["category"] == "llm_flips" for i in issues)

    def test_veto_success_detection(self):
        from llm.operator_channel import OperatorChannel
        channel = OperatorChannel(alert_router=None)
        issues = channel._detect_issues({
            "consecutive_losses": 0,
            "llm_accuracy": 0.65,
            "llm_decisions_count": 10,
            "veto_accuracy": 0.85,
            "veto_count": 15,
        })
        assert any(i["category"] == "veto_success" for i in issues)


# ── CB Override Constraints ────────────────────────────────────────

class TestCBOverrideConstraints:
    """Test graduated circuit breaker override."""

    def test_no_constraints_when_not_tripped(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker()
        constraints = cb.get_override_constraints(confidence=90)
        assert constraints["max_leverage"] == 25.0
        assert constraints["size_multiplier"] == 1.0
        assert not constraints["constrained"]

    def test_constraints_when_tripped(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker()
        cb._trip("test trip")
        constraints = cb.get_override_constraints(confidence=95)
        assert constraints["max_leverage"] == 2.0
        assert constraints["size_multiplier"] == 0.5
        assert constraints["constrained"]
        assert "circuit_breaker_override" in constraints["reason"]


# ── Signal Quality LLM Agreement ──────────────────────────────────

class TestSignalQualityLLM:
    """Test LLM agreement tracking in signal quality."""

    def test_llm_fields_in_quality_features(self):
        from feedback.signal_quality import QualityFeatures
        f = QualityFeatures(
            symbol="BTC", side="LONG",
            llm_action="go",
            llm_confidence=0.8,
            llm_agreed_with_ensemble=True,
        )
        assert f.llm_action == "go"
        assert f.llm_confidence == 0.8
        assert f.llm_agreed_with_ensemble is True

    def test_llm_agreement_tracking(self, tmp_path):
        from feedback.signal_quality import SignalQualityScorer, QualityFeatures
        scorer = SignalQualityScorer(data_dir=str(tmp_path / "quality_llm"))

        # Record some outcomes with LLM agreement data
        for i in range(10):
            features = QualityFeatures(
                symbol="BTC", side="LONG", regime="trend",
                llm_action="go",
                llm_agreed_with_ensemble=True,
            )
            scorer.record_outcome(features, win=i % 3 != 0, pnl=10 if i % 3 != 0 else -10)

        assert "agreed" in scorer.by_llm_agreement
        assert scorer.by_llm_agreement["agreed"]["total"] == 10

    def test_llm_disagreement_scoring(self, tmp_path):
        from feedback.signal_quality import SignalQualityScorer, QualityFeatures
        scorer = SignalQualityScorer(data_dir=str(tmp_path / "quality_llm2"))

        # Record outcomes where LLM disagreed
        for i in range(8):
            features = QualityFeatures(
                symbol="BTC", side="LONG", regime="trend",
                llm_action="skip",
                llm_agreed_with_ensemble=False,
            )
            scorer.record_outcome(features, win=i < 2, pnl=10 if i < 2 else -10)

        # Now score a signal where LLM disagrees
        features = QualityFeatures(
            symbol="BTC", side="LONG", regime="trend",
            llm_action="skip",
            llm_agreed_with_ensemble=False,
        )
        quality, breakdown = scorer.score_signal(features)
        assert "llm_agreement" in breakdown


# ── Feedback Loop LLM Parameters ──────────────────────────────────

class TestFeedbackLoopLLM:
    """Test LLM parameters flow through feedback loop."""

    def test_record_outcome_accepts_llm_params(self, tmp_path):
        """Verify record_outcome accepts the new llm_* parameters."""
        from feedback.loop import FeedbackLoop
        loop = FeedbackLoop(data_dir=str(tmp_path / "feedback_llm"))
        # Should not raise
        loop.record_outcome(
            confidence=75.0,
            win=True,
            pnl=50.0,
            strategy="ensemble",
            symbol="BTC",
            regime="trend",
            side="LONG",
            llm_action="go",
            llm_confidence=0.8,
            llm_agreed=True,
        )

    def test_record_outcome_backwards_compatible(self, tmp_path):
        """Verify old callers without llm params still work."""
        from feedback.loop import FeedbackLoop
        loop = FeedbackLoop(data_dir=str(tmp_path / "feedback_compat"))
        # Should not raise (no llm params)
        loop.record_outcome(
            confidence=75.0,
            win=True,
            pnl=50.0,
            strategy="ensemble",
            symbol="BTC",
        )
