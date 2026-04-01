"""
Tests for the Agent Performance Tracker.

Covers:
- Recording pipeline runs
- Scoring trades against agent decisions
- Regime, Trade, Risk, Critic, Exit scoring logic
- Veto counterfactual tracking
- Report generation
- Persistence (load/save to JSONL)
- Edge cases (empty data, missing agents, etc.)
"""

import json
import os
import tempfile
import time
import uuid

import pytest

# Ensure bot/ is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.agents.base import AgentOutput, AgentRole
from llm.agents.performance_tracker import (
    AgentDecisionRecord,
    AgentPerformanceTracker,
    CriticScore,
    ExitScore,
    RegimeScore,
    RiskScore,
    TradeScore,
    _mean,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir():
    """Create a temp directory for test data."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def tracker(tmp_data_dir):
    """Fresh tracker with temp storage."""
    return AgentPerformanceTracker(data_dir=tmp_data_dir)


def _make_agent_output(role, data, model="test-model"):
    """Create a minimal AgentOutput."""
    return AgentOutput(
        role=role,
        data=data,
        raw_text=json.dumps(data),
        model_used=model,
        latency_ms=100,
        input_tokens=500,
        output_tokens=200,
    )


def _make_pipeline_outputs():
    """Create a full set of pipeline agent outputs."""
    return {
        AgentRole.REGIME: _make_agent_output(
            AgentRole.REGIME,
            {"rg": "trend", "conf": 0.8, "bias": "bullish", "factors": "strong momentum"},
        ),
        AgentRole.TRADE: _make_agent_output(
            AgentRole.TRADE,
            {"a": "proceed", "c": 0.75, "thesis": "momentum continuation likely", "n": "trend aligned"},
        ),
        AgentRole.RISK: _make_agent_output(
            AgentRole.RISK,
            {"sz": 1.2, "risks": ["volatility_high"], "override": "none"},
        ),
        AgentRole.CRITIC: _make_agent_output(
            AgentRole.CRITIC,
            {"verdict": "approve", "adjusted_confidence": 0.7, "reason": "thesis solid"},
        ),
        AgentRole.EXIT: _make_agent_output(
            AgentRole.EXIT,
            {"recommendation": "hold", "action": "hold", "confidence": 0.6},
        ),
    }


def _make_winning_outcome():
    """Create a winning trade outcome."""
    return {
        "symbol": "HYPE",
        "side": "BUY",
        "entry_price": 100.0,
        "exit_price": 103.0,
        "pnl_pct": 3.0,
        "hold_hours": 4.5,
        "exit_type": "tp1",
        "max_favorable_pct": 3.5,
        "max_adverse_pct": -0.5,
    }


def _make_losing_outcome():
    """Create a losing trade outcome."""
    return {
        "symbol": "SOL",
        "side": "BUY",
        "entry_price": 100.0,
        "exit_price": 97.0,
        "pnl_pct": -3.0,
        "hold_hours": 2.0,
        "exit_type": "sl",
        "max_favorable_pct": 0.5,
        "max_adverse_pct": -3.5,
    }


# ── Test Recording ──────────────────────────────────────────────────

class TestRecording:
    def test_record_pipeline_run(self, tracker):
        """Pipeline run records all agent decisions."""
        pid = "test-pipeline-1"
        outputs = _make_pipeline_outputs()
        tracker.record_pipeline_run(pid, "HYPE", "BUY", outputs)

        assert pid in tracker._pipeline_index
        records = tracker._pipeline_index[pid]
        assert len(records) == 5  # All 5 agents

        roles = {r.agent_role for r in records}
        assert "regime" in roles
        assert "trade" in roles
        assert "risk" in roles
        assert "critic" in roles
        assert "exit" in roles

    def test_record_persists_to_jsonl(self, tracker, tmp_data_dir):
        """Records are written to the JSONL file."""
        pid = "persist-test"
        outputs = _make_pipeline_outputs()
        tracker.record_pipeline_run(pid, "SOL", "SELL", outputs)

        perf_file = os.path.join(tmp_data_dir, "agent_performance.jsonl")
        assert os.path.exists(perf_file)

        with open(perf_file) as f:
            lines = f.readlines()
        assert len(lines) == 5  # One per agent

        first = json.loads(lines[0])
        assert first["type"] == "decision"
        assert first["symbol"] == "SOL"
        assert first["side"] == "SELL"

    def test_record_empty_outputs(self, tracker):
        """Empty outputs dict produces no records."""
        tracker.record_pipeline_run("empty", "BTC", "BUY", {})
        assert "empty" not in tracker._pipeline_index

    def test_record_failed_agent_skipped(self, tracker):
        """Failed agents (error set) are skipped."""
        outputs = {
            AgentRole.REGIME: AgentOutput(
                role=AgentRole.REGIME,
                data={},
                error="timeout",
            ),
            AgentRole.TRADE: _make_agent_output(AgentRole.TRADE, {"a": "flat", "c": 0.3}),
        }
        tracker.record_pipeline_run("partial", "HYPE", "BUY", outputs)
        records = tracker._pipeline_index.get("partial", [])
        assert len(records) == 1
        assert records[0].agent_role == "trade"

    def test_record_veto(self, tracker):
        """Veto recording persists to JSONL."""
        critic_out = _make_agent_output(
            AgentRole.CRITIC,
            {"verdict": "veto", "counter_thesis": "overbought", "adjusted_confidence": 0.2},
        )
        tracker.record_veto("veto-1", "HYPE", "BUY", 100.0, critic_out)

        # Check file
        perf_file = os.path.join(tracker._data_dir, "agent_performance.jsonl")
        with open(perf_file) as f:
            lines = f.readlines()
        entry = json.loads(lines[-1])
        assert entry["type"] == "veto"
        assert entry["symbol"] == "HYPE"


# ── Test Scoring ────────────────────────────────────────────────────

class TestScoring:
    def test_score_winning_trade(self, tracker):
        """Scoring a winning trade produces correct per-agent scores."""
        pid = "win-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_winning_outcome())

        assert "regime" in scores
        assert "trade" in scores
        assert "risk" in scores
        assert "critic" in scores
        assert "exit" in scores

    def test_regime_correct_for_trend_up(self, tracker):
        """Regime 'trend' with bullish bias is correct when price goes up."""
        pid = "regime-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_winning_outcome())

        regime = scores["regime"]
        assert regime.correct_regime is True
        assert regime.predicted_regime == "trend"
        assert regime.actual_direction == "up"

    def test_regime_wrong_for_trend_down(self, tracker):
        """Regime 'trend/bullish' is wrong when price goes down significantly."""
        pid = "regime-2"
        tracker.record_pipeline_run(pid, "SOL", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_losing_outcome())

        regime = scores["regime"]
        # Bullish trend prediction + price went down 3% = wrong
        assert regime.correct_regime is False

    def test_trade_direction_correct(self, tracker):
        """Trade agent BUY + price up = correct direction."""
        pid = "trade-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_winning_outcome())

        trade = scores["trade"]
        assert trade.correct_direction is True
        assert trade.trade_won is True
        assert trade.thesis_accuracy > 0.5

    def test_trade_direction_wrong(self, tracker):
        """Trade agent BUY + price down = wrong direction."""
        pid = "trade-2"
        tracker.record_pipeline_run(pid, "SOL", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_losing_outcome())

        trade = scores["trade"]
        assert trade.correct_direction is False
        assert trade.trade_won is False
        assert trade.thesis_accuracy < 0.5

    def test_risk_sizing_efficiency_winner(self, tracker):
        """Risk agent scored well when size matches winning outcome."""
        pid = "risk-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_winning_outcome())

        risk = scores["risk"]
        assert risk.recommended_size_mult == 1.2
        assert risk.sizing_efficiency > 0  # Some positive efficiency
        assert risk.actual_pnl_pct == 3.0

    def test_critic_approve_winner(self, tracker):
        """Critic approval on a winning trade = good approval."""
        pid = "critic-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_winning_outcome())

        critic = scores["critic"]
        assert critic.verdict == "approve"
        assert critic.approval_made_money is True

    def test_critic_approve_loser(self, tracker):
        """Critic approval on a losing trade = bad approval."""
        pid = "critic-2"
        tracker.record_pipeline_run(pid, "SOL", "BUY", _make_pipeline_outputs())
        scores = tracker.score_trade(pid, _make_losing_outcome())

        critic = scores["critic"]
        assert critic.verdict == "approve"
        assert critic.approval_made_money is False

    def test_exit_scoring(self, tracker):
        """Exit agent is scored on timing."""
        pid = "exit-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        outcome = _make_winning_outcome()
        outcome["pnl_at_exit_signal"] = 2.0  # PnL when exit was checked
        scores = tracker.score_trade(pid, outcome)

        exit_s = scores["exit"]
        assert exit_s.final_pnl == 3.0
        assert exit_s.money_left_on_table >= 0

    def test_score_missing_pipeline(self, tracker):
        """Scoring a nonexistent pipeline returns empty dict."""
        result = tracker.score_trade("nonexistent", _make_winning_outcome())
        assert result == {}

    def test_scored_records_persisted(self, tracker, tmp_data_dir):
        """Scored outcomes are persisted to JSONL."""
        pid = "persist-score"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        tracker.score_trade(pid, _make_winning_outcome())

        perf_file = os.path.join(tmp_data_dir, "agent_performance.jsonl")
        with open(perf_file) as f:
            lines = f.readlines()

        scored_lines = [json.loads(l) for l in lines if "scored_trade" in l]
        assert len(scored_lines) == 1
        assert scored_lines[0]["won"] is True


# ── Test Veto Counterfactuals ───────────────────────────────────────

class TestVetoCounterfactuals:
    def test_veto_saves_money(self, tracker):
        """Veto on a trade that would have lost = saved money."""
        pid = "veto-save"
        outputs = _make_pipeline_outputs()
        outputs[AgentRole.CRITIC] = _make_agent_output(
            AgentRole.CRITIC,
            {"verdict": "veto", "counter_thesis": "overextended"},
        )
        tracker.record_pipeline_run(pid, "HYPE", "BUY", outputs)

        score = tracker.score_veto_counterfactual(pid, {
            "would_have_won": False,
            "counterfactual_pnl_pct": -2.5,
        })

        assert score is not None
        assert score.veto_saved_money is True
        assert score.counterfactual_pnl_pct == -2.5

    def test_veto_misses_profit(self, tracker):
        """Veto on a trade that would have won = missed profit."""
        pid = "veto-miss"
        outputs = _make_pipeline_outputs()
        outputs[AgentRole.CRITIC] = _make_agent_output(
            AgentRole.CRITIC,
            {"verdict": "veto", "counter_thesis": "weak thesis"},
        )
        tracker.record_pipeline_run(pid, "SOL", "BUY", outputs)

        score = tracker.score_veto_counterfactual(pid, {
            "would_have_won": True,
            "counterfactual_pnl_pct": 4.0,
        })

        assert score is not None
        assert score.veto_saved_money is False

    def test_veto_no_critic_record(self, tracker):
        """Veto counterfactual with no critic record returns None."""
        score = tracker.score_veto_counterfactual("no-such-pipeline", {
            "would_have_won": False,
            "counterfactual_pnl_pct": -1.0,
        })
        assert score is None


# ── Test Reporting ──────────────────────────────────────────────────

class TestReporting:
    def test_empty_report(self, tracker):
        """Report with no data returns informative message."""
        report = tracker.get_agent_report()
        assert report["total_scored_trades"] == 0
        assert "message" in report

    def test_report_after_scoring(self, tracker):
        """Report aggregates scored trades correctly."""
        # Record and score multiple trades
        for i in range(3):
            pid = f"win-{i}"
            tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
            tracker.score_trade(pid, _make_winning_outcome())

        for i in range(2):
            pid = f"lose-{i}"
            tracker.record_pipeline_run(pid, "SOL", "BUY", _make_pipeline_outputs())
            tracker.score_trade(pid, _make_losing_outcome())

        report = tracker.get_agent_report()
        assert report["total_scored_trades"] == 5

        # Check regime stats
        regime = report["agents"]["regime"]
        assert regime["count"] == 5
        assert 0 <= regime["accuracy"] <= 1

        # Check trade stats
        trade = report["agents"]["trade"]
        assert trade["count"] == 5
        assert trade["win_rate"] == 0.6  # 3 wins / 5 total

        # Check alpha attribution exists
        alpha = report.get("alpha_attribution", {})
        assert "total_pnl_pct" in alpha

    def test_report_with_lookback(self, tracker):
        """Lookback filter works."""
        pid = "old-trade"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        tracker.score_trade(pid, _make_winning_outcome())

        # Manually age the record
        tracker._scored_records[0]["timestamp"] = time.time() - 100 * 86400

        report = tracker.get_agent_report(lookback_days=7)
        assert report["total_scored_trades"] == 0

    def test_summary_line(self, tracker):
        """Summary line works with and without data."""
        # No data
        summary = tracker.get_agent_summary_line()
        assert "no data" in summary.lower()

        # With data
        pid = "sum-1"
        tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        tracker.score_trade(pid, _make_winning_outcome())

        summary = tracker.get_agent_summary_line()
        assert "1 trades" in summary or "(1 trades)" in summary

    def test_recommendations_generated(self, tracker):
        """Recommendations are generated after enough trades."""
        for i in range(6):
            pid = f"rec-{i}"
            tracker.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
            if i < 4:
                tracker.score_trade(pid, _make_winning_outcome())
            else:
                tracker.score_trade(pid, _make_losing_outcome())

        report = tracker.get_agent_report()
        recs = report.get("recommendations", [])
        assert len(recs) > 0

    def test_report_with_vetoes(self, tracker):
        """Report includes veto counterfactual stats."""
        # Record a veto
        pid = "veto-report"
        outputs = _make_pipeline_outputs()
        outputs[AgentRole.CRITIC] = _make_agent_output(
            AgentRole.CRITIC,
            {"verdict": "veto", "counter_thesis": "bad setup"},
        )
        tracker.record_pipeline_run(pid, "HYPE", "BUY", outputs)
        tracker.score_veto_counterfactual(pid, {
            "would_have_won": False,
            "counterfactual_pnl_pct": -3.0,
        })

        report = tracker.get_agent_report()
        assert report["total_veto_counterfactuals"] == 1

        critic = report["agents"]["critic"]
        assert critic["veto_count"] == 1
        assert critic["veto_accuracy"] == 1.0  # Saved money


# ── Test Persistence & Reload ───────────────────────────────────────

class TestPersistence:
    def test_reload_from_disk(self, tmp_data_dir):
        """Tracker reloads data from JSONL on init."""
        tracker1 = AgentPerformanceTracker(data_dir=tmp_data_dir)
        pid = "reload-test"
        tracker1.record_pipeline_run(pid, "HYPE", "BUY", _make_pipeline_outputs())
        tracker1.score_trade(pid, _make_winning_outcome())

        # Create new tracker — should reload
        tracker2 = AgentPerformanceTracker(data_dir=tmp_data_dir)
        assert len(tracker2._scored_records) == 1
        assert len(tracker2._pipeline_index) >= 1


# ── Test Regime Matching Logic ──────────────────────────────────────

class TestRegimeMatching:
    def test_trend_bullish_up(self):
        """Trend bullish + up = correct."""
        assert AgentPerformanceTracker._regime_matches_outcome("trend", "bullish", "up", 2.0) is True

    def test_trend_bullish_down(self):
        """Trend bullish + down = wrong."""
        assert AgentPerformanceTracker._regime_matches_outcome("trend", "bullish", "down", -2.0) is False

    def test_range_small_move(self):
        """Range + small move = correct."""
        assert AgentPerformanceTracker._regime_matches_outcome("range", "neutral", "flat", 0.3) is True

    def test_range_big_move(self):
        """Range + big move = wrong."""
        assert AgentPerformanceTracker._regime_matches_outcome("range", "neutral", "up", 5.0) is False

    def test_panic_down(self):
        """Panic + big down = correct."""
        assert AgentPerformanceTracker._regime_matches_outcome("panic", "bearish", "down", -5.0) is True

    def test_panic_up(self):
        """Panic + up = wrong."""
        assert AgentPerformanceTracker._regime_matches_outcome("panic", "bearish", "up", 3.0) is False

    def test_unknown_always_wrong(self):
        """Unknown regime is always scored as wrong."""
        assert AgentPerformanceTracker._regime_matches_outcome("unknown", "neutral", "up", 1.0) is False

    def test_high_vol_big_move(self):
        """High volatility + big move either way = correct."""
        assert AgentPerformanceTracker._regime_matches_outcome("high_volatility", "neutral", "up", 3.0) is True
        assert AgentPerformanceTracker._regime_matches_outcome("high_volatility", "neutral", "down", -2.0) is True


# ── Test Score Dataclasses ──────────────────────────────────────────

class TestScoreDataclasses:
    def test_regime_score_to_dict(self):
        score = RegimeScore(
            predicted_regime="trend",
            actual_price_move_pct=2.0,
            correct_regime=True,
            regime_confidence=0.8,
            regime_bias="bullish",
            actual_direction="up",
        )
        d = score.to_dict()
        assert d["predicted_regime"] == "trend"
        assert d["correct_regime"] is True

    def test_trade_score_to_dict(self):
        score = TradeScore(
            predicted_action="proceed",
            predicted_direction="BUY",
            actual_direction="up",
            correct_direction=True,
            thesis_accuracy=0.8,
            predicted_confidence=0.75,
            actual_pnl_pct=2.5,
            trade_won=True,
        )
        d = score.to_dict()
        assert d["trade_won"] is True
        assert d["thesis_accuracy"] == 0.8

    def test_critic_score_to_dict(self):
        score = CriticScore(
            verdict="approve",
            trade_proceeded=True,
            actual_pnl_pct=1.5,
            counterfactual_pnl_pct=0.0,
            veto_saved_money=None,
            approval_made_money=True,
            veto_accuracy=1.0,
        )
        d = score.to_dict()
        assert d["approval_made_money"] is True


# ── Test Utility ────────────────────────────────────────────────────

class TestUtility:
    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_mean_values(self):
        assert _mean([1.0, 2.0, 3.0]) == 2.0

    def test_mean_single(self):
        assert _mean([5.0]) == 5.0
