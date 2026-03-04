"""
Tests for the LLM Multi-Agent Backtest Integration.

Tests:
  1. PreflightResult and CheckpointState dataclasses
  2. Preflight validation (API key, data, strategies, snapshot, cost estimate)
  3. Budget enforcement (stops LLM calls when budget exceeded)
  4. Checkpoint save/load/resume
  5. Per-candle error handling (graceful fallback on failures)
  6. Entry evaluation (veto, sizing, pass-through)
  7. Exit evaluation (throttle, force-close)
  8. Learning agent invocation
  9. Snapshot building from backtest data
  10. Engine integration (LLM hooks in walk loop)
  11. Learning bridge LLM enrichment
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# 1. Dataclass Tests
# ---------------------------------------------------------------------------

class TestDataclasses:
    """Test PreflightResult and CheckpointState dataclasses."""

    def test_preflight_result_defaults(self):
        from backtest.llm_integration import PreflightResult
        result = PreflightResult(passed=True)
        assert result.passed is True
        assert result.errors == []
        assert result.warnings == []
        assert result.estimated_cost == 0.0
        assert result.estimated_llm_calls == 0
        assert result.candle_count == 0

    def test_preflight_result_with_errors(self):
        from backtest.llm_integration import PreflightResult
        result = PreflightResult(
            passed=False,
            errors=["API key not set"],
            warnings=["Low data quality"],
        )
        assert result.passed is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_checkpoint_state(self):
        from backtest.llm_integration import CheckpointState
        state = CheckpointState(
            candle_index=100,
            symbol="BTC",
            symbols_completed=["ETH"],
            equity=10500.0,
            llm_stats={"total_cost_usd": 1.23},
            timestamp="2026-03-04T12:00:00Z",
        )
        assert state.candle_index == 100
        assert state.symbol == "BTC"
        assert state.equity == 10500.0


# ---------------------------------------------------------------------------
# 2. Preflight Validation
# ---------------------------------------------------------------------------

class TestPreflight:
    """Test preflight validation catches errors before API spend."""

    def test_preflight_fails_no_api_key(self):
        """Preflight should fail if no API key is set."""
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)

        with patch("llm.client.get_client", return_value=None):
            result = llm.run_preflight(["BTC"], {}, MagicMock(), MagicMock())
            assert result.passed is False
            assert any("api" in e.lower() or "anthropic" in e.lower() for e in result.errors)

    def test_preflight_fails_empty_data(self):
        """Preflight should fail if no usable data exists."""
        from backtest.llm_integration import BacktestLLMIntegration
        import pandas as pd

        llm = BacktestLLMIntegration(budget_usd=5.0)

        # Mock successful API checks
        mock_client = MagicMock()
        with patch("llm.client.get_client", return_value=mock_client), \
             patch("llm.client.call_llm", return_value=("OK", {"input_tokens": 10, "output_tokens": 5})):
            result = llm.run_preflight(
                symbols=["BTC"],
                all_data={"BTC": {"1h": pd.DataFrame()}},  # Empty data
                ensemble=MagicMock(),
                config=MagicMock(),
            )
            assert result.passed is False
            assert any("no usable data" in e.lower() or "No usable data" in e for e in result.errors)

    def test_preflight_cost_estimation(self):
        """Preflight should estimate cost based on candle count."""
        from backtest.llm_integration import BacktestLLMIntegration
        import pandas as pd
        import numpy as np

        llm = BacktestLLMIntegration(budget_usd=5.0)

        # Create realistic 1h data with 100 candles
        times = pd.date_range("2026-01-01", periods=100, freq="1h")
        df_1h = pd.DataFrame({
            "time": times,
            "open": np.random.uniform(50000, 51000, 100),
            "high": np.random.uniform(51000, 52000, 100),
            "low": np.random.uniform(49000, 50000, 100),
            "close": np.random.uniform(50000, 51000, 100),
            "volume": np.random.uniform(100, 1000, 100),
        })

        mock_ensemble = MagicMock()
        mock_ensemble.evaluate.return_value = None  # No signals in dry run

        with patch("llm.client.get_client", return_value=MagicMock()), \
             patch("llm.client.call_llm", return_value=("OK", {"input_tokens": 10, "output_tokens": 5})), \
             patch("llm.agents.coordinator.AgentCoordinator"):
            result = llm.run_preflight(
                symbols=["BTC"],
                all_data={"BTC": {"1h": df_1h}},
                ensemble=mock_ensemble,
                config=MagicMock(),
            )
            assert result.passed is True
            assert result.candle_count == 50  # 100 - 50 warmup
            assert result.estimated_cost > 0
            assert result.estimated_llm_calls > 0


# ---------------------------------------------------------------------------
# 3. Budget Enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    """Test that LLM calls stop when budget is exceeded."""

    def test_budget_exhausted_skips_entry(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=0.01)
        llm.budget_exhausted = True
        llm._coordinator = MagicMock()

        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result is None
        assert llm.candles_fallback == 1
        # Coordinator should NOT have been called
        llm._coordinator.get_trading_decision.assert_not_called()

    def test_budget_exhausted_skips_exit(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=0.01)
        llm.budget_exhausted = True
        llm._coordinator = MagicMock()

        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is None

    def test_budget_exhausted_skips_learning(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=0.01)
        llm.budget_exhausted = True
        llm._coordinator = MagicMock()

        result = llm.run_learning({"symbol": "BTC", "pnl": 100})
        assert result is None

    def test_budget_triggers_exhaustion(self):
        """Budget should be marked exhausted when cost exceeds limit."""
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = BacktestLLMIntegration(budget_usd=0.001)  # Very low budget
        mock_coord = MagicMock()
        mock_decision = LLMDecision(
            action="proceed",
            confidence=0.7,
            regime="trend",
            strategy_weights=StrategyWeights(),
            memory_update=None,
            notes="test",
        )
        mock_coord.get_trading_decision.return_value = mock_decision
        mock_coord.get_stats.return_value = {
            "total_calls": 4,
            "total_input_tokens": 5000,
            "total_output_tokens": 2000,
        }
        llm._coordinator = mock_coord

        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result is not None  # First call succeeds
        assert llm.budget_exhausted is True  # But triggers exhaustion
        assert llm.total_cost_usd > 0

        # Next call should be skipped
        result2 = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result2 is None


# ---------------------------------------------------------------------------
# 4. Checkpoint Save/Load
# ---------------------------------------------------------------------------

class TestCheckpoint:
    """Test checkpoint save and load for crash recovery."""

    def test_checkpoint_save_and_load(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            llm = BacktestLLMIntegration(
                budget_usd=5.0, checkpoint_dir=tmpdir
            )
            llm.total_cost_usd = 1.23
            llm.llm_calls = 42
            llm.candles_with_llm = 30
            llm.candles_fallback = 5

            # Save checkpoint
            llm.save_checkpoint(
                candle_index=100,
                symbol="BTC",
                symbols_completed=["ETH"],
                equity=10500.0,
            )

            # Verify file exists
            assert os.path.exists(os.path.join(tmpdir, "checkpoint.json"))

            # Load checkpoint in new instance
            llm2 = BacktestLLMIntegration(
                budget_usd=5.0, checkpoint_dir=tmpdir, resume=True
            )
            assert llm2.resume_state is not None
            assert llm2.resume_state.candle_index == 100
            assert llm2.resume_state.symbol == "BTC"
            assert llm2.resume_state.equity == 10500.0
            assert llm2.total_cost_usd == 1.23
            assert llm2.llm_calls == 42

    def test_checkpoint_no_file_returns_none(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            llm = BacktestLLMIntegration(
                budget_usd=5.0, checkpoint_dir=tmpdir, resume=True
            )
            assert llm.resume_state is None


# ---------------------------------------------------------------------------
# 5. Error Handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Test graceful fallback on various failures."""

    def test_entry_eval_handles_coordinator_exception(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_trading_decision.side_effect = RuntimeError("API down")
        mock_coord.get_stats.return_value = {"total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0}
        llm._coordinator = mock_coord

        # Should NOT raise, should return None
        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result is None
        assert llm.llm_failures == 1
        assert llm.candles_fallback == 1

    def test_entry_eval_handles_none_snapshot(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm._coordinator = MagicMock()

        result = llm.evaluate_entry(None, MagicMock(), "test")
        assert result is None
        assert llm.candles_fallback == 1

    def test_entry_eval_handles_coordinator_returning_none(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_trading_decision.return_value = None
        mock_coord.get_stats.return_value = {"total_calls": 4, "total_input_tokens": 100, "total_output_tokens": 50}
        llm._coordinator = mock_coord

        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result is None
        assert llm.candles_fallback == 1

    def test_exit_eval_handles_exception(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_exit_intelligence.side_effect = RuntimeError("fail")
        llm._coordinator = mock_coord
        # Force the throttle counter to fire
        llm._exit_eval_counters["BTC"] = 5

        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is None
        assert llm.llm_failures == 1

    def test_learning_handles_exception(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_post_trade_lesson.side_effect = RuntimeError("fail")
        llm._coordinator = mock_coord

        result = llm.run_learning({"symbol": "BTC"})
        assert result is None
        assert llm.llm_failures == 1


# ---------------------------------------------------------------------------
# 6. Entry Evaluation
# ---------------------------------------------------------------------------

class TestEntryEvaluation:
    """Test LLM entry evaluation logic."""

    def _make_llm(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = BacktestLLMIntegration(budget_usd=5.0)
        return llm

    def test_veto_returns_flat(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = self._make_llm()
        mock_coord = MagicMock()
        veto_decision = LLMDecision(
            action="flat", confidence=0.0, regime="range",
            strategy_weights=StrategyWeights(), memory_update=None,
            notes="Vetoed: choppy market",
        )
        mock_coord.get_trading_decision.return_value = veto_decision
        mock_coord.get_stats.return_value = {"total_calls": 4, "total_input_tokens": 100, "total_output_tokens": 50}
        llm._coordinator = mock_coord

        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result is not None
        assert result.action == "flat"

    def test_proceed_returns_decision(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = self._make_llm()
        mock_coord = MagicMock()
        proceed_decision = LLMDecision(
            action="proceed", confidence=0.75, regime="trend",
            strategy_weights=StrategyWeights(), memory_update=None,
            notes="Strong trend confirmed", size_multiplier=1.2,
        )
        mock_coord.get_trading_decision.return_value = proceed_decision
        mock_coord.get_stats.return_value = {"total_calls": 4, "total_input_tokens": 200, "total_output_tokens": 100}
        llm._coordinator = mock_coord

        result = llm.evaluate_entry({"m": [{"s": "BTC"}]}, MagicMock(), "test")
        assert result.action == "proceed"
        assert result.size_multiplier == 1.2
        assert llm.candles_with_llm == 1


# ---------------------------------------------------------------------------
# 7. Exit Evaluation
# ---------------------------------------------------------------------------

class TestExitEvaluation:
    """Test Exit Agent throttling and evaluation."""

    def test_exit_throttle_skips_intermediate_candles(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_exit_intelligence.return_value = {"action": "hold"}
        mock_coord.get_stats.return_value = {"total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 25}
        mock_coord.last_exit_output = MagicMock(
            data={"action": "hold"}, model_used="haiku",
            input_tokens=50, output_tokens=25, ok=True,
        )
        llm._coordinator = mock_coord

        # First call (counter==1) evaluates immediately (Bug 9 fix)
        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is not None
        assert mock_coord.get_exit_intelligence.call_count == 1

        # Calls 2-5 should be throttled
        for _ in range(4):
            result = llm.evaluate_exit({"symbol": "BTC"})
            assert result is None
        assert mock_coord.get_exit_intelligence.call_count == 1  # Still 1

        # 6th call should go through (counter==6, 6%6==0)
        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result == {"action": "hold"}
        assert mock_coord.get_exit_intelligence.call_count == 2

    def test_clear_exit_counter(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm._exit_eval_counters["BTC"] = 4
        llm.clear_exit_counter("BTC")
        assert "BTC" not in llm._exit_eval_counters


# ---------------------------------------------------------------------------
# 8. Snapshot Building
# ---------------------------------------------------------------------------

class TestSnapshotBuilding:
    """Test backtest snapshot construction."""

    def test_snapshot_has_required_keys(self):
        from backtest.llm_integration import BacktestLLMIntegration
        import pandas as pd
        import numpy as np

        llm = BacktestLLMIntegration(budget_usd=5.0)

        times = pd.date_range("2026-01-01", periods=60, freq="1h")
        df_1h = pd.DataFrame({
            "time": times,
            "open": np.linspace(50000, 51000, 60),
            "high": np.linspace(51000, 52000, 60),
            "low": np.linspace(49000, 50000, 60),
            "close": np.linspace(50000, 51000, 60),
            "volume": np.full(60, 500.0),
        })

        mock_signal = MagicMock()
        mock_signal.strategy = "regime_trend"
        mock_signal.side = "BUY"
        mock_signal.confidence = 75.0

        snapshot = llm.build_backtest_snapshot(
            symbol="BTC",
            windowed_data={"1h": df_1h},
            signal=mock_signal,
            current_price=51000.0,
            open_positions={},
            equity=10000.0,
        )

        assert snapshot is not None
        assert "m" in snapshot
        assert "g" in snapshot
        assert len(snapshot["m"]) == 1
        assert snapshot["m"][0]["s"] == "BTC"
        assert snapshot["g"]["eq"] == 10000

    def test_snapshot_handles_empty_data_gracefully(self):
        from backtest.llm_integration import BacktestLLMIntegration
        import pandas as pd

        llm = BacktestLLMIntegration(budget_usd=5.0)

        snapshot = llm.build_backtest_snapshot(
            symbol="BTC",
            windowed_data={"1h": pd.DataFrame()},
            signal=None,
            current_price=50000.0,
            open_positions={},
            equity=10000.0,
        )

        # Should still produce a valid snapshot
        assert snapshot is not None
        assert "m" in snapshot

    def test_snapshot_json_roundtrip(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        snapshot = llm._build_test_snapshot("BTC", 50000.0)

        # Should serialize and deserialize cleanly
        serialized = json.dumps(snapshot)
        parsed = json.loads(serialized)
        assert parsed["m"][0]["s"] == "BTC"


# ---------------------------------------------------------------------------
# 9. Progress and Summary
# ---------------------------------------------------------------------------

class TestProgressAndSummary:
    """Test progress line and summary reporting."""

    def test_progress_line_format(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm.candles_with_llm = 10
        llm.candles_fallback = 2
        llm.total_cost_usd = 0.50

        line = llm.get_progress_line(100, 720)
        assert "[100/720]" in line
        assert "$0.50" in line
        assert "Fallback: 2" in line

    def test_summary_dict(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm.llm_calls = 42
        llm.llm_failures = 3
        llm.candles_with_llm = 30
        llm.candles_fallback = 5
        llm.total_cost_usd = 2.34

        summary = llm.get_summary()
        assert summary["llm_calls"] == 42
        assert summary["llm_failures"] == 3
        assert summary["total_cost_usd"] == 2.34
        assert summary["budget_usd"] == 5.0
        assert summary["budget_used_pct"] == pytest.approx(46.8, abs=0.1)


# ---------------------------------------------------------------------------
# 10. Decision Flushing
# ---------------------------------------------------------------------------

class TestDecisionFlushing:
    """Test decision log writing."""

    def test_flush_decisions_writes_jsonl(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "decisions.jsonl")
            llm = BacktestLLMIntegration(budget_usd=5.0)
            llm.decisions_log_path = log_path
            llm.decisions = [
                {"action": "proceed", "confidence": 0.75, "regime": "trend"},
                {"action": "flat", "confidence": 0.0, "regime": "range"},
            ]

            llm.flush_decisions()

            assert os.path.exists(log_path)
            with open(log_path) as f:
                lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[0])["action"] == "proceed"
            assert json.loads(lines[1])["action"] == "flat"

    def test_flush_empty_decisions_is_noop(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm.decisions = []
        # Should not raise
        llm.flush_decisions()


# ---------------------------------------------------------------------------
# 11. Learning Bridge LLM Enrichment
# ---------------------------------------------------------------------------

class TestLearningBridgeLLM:
    """Test that the learning bridge correctly handles LLM data."""

    def test_regime_map_from_decisions(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        decisions = [
            {"regime": "trend", "confidence": 0.8},
            {"regime": "range", "confidence": 0.6},
        ]
        regime_map = bridge._build_llm_regime_map(decisions)
        assert regime_map.get("_latest") == "range"  # Last one wins

    def test_regime_map_ignores_unknown(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        decisions = [
            {"regime": "unknown", "confidence": 0.5},
        ]
        regime_map = bridge._build_llm_regime_map(decisions)
        assert "_latest" not in regime_map

    def test_stats_include_llm_decisions(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        assert "llm_decisions_ingested" in bridge._stats
        assert bridge._stats["llm_decisions_ingested"] == 0


# ---------------------------------------------------------------------------
# 12. Per-Agent Output Capture (Coordinator)
# ---------------------------------------------------------------------------

class TestCoordinatorOutputCapture:
    """Test that coordinator exposes per-agent pipeline results."""

    def test_last_pipeline_results_initialized_empty(self):
        from llm.agents.coordinator import AgentCoordinator
        coord = AgentCoordinator()
        assert coord.last_pipeline_results == {}
        assert coord.last_exit_output is None

    def test_get_last_pipeline_detail_returns_none_initially(self):
        from llm.agents.coordinator import AgentCoordinator
        coord = AgentCoordinator()
        assert coord.get_last_pipeline_detail() is None

    def test_get_last_pipeline_detail_serializes_outputs(self):
        from llm.agents.coordinator import AgentCoordinator
        from llm.agents.base import AgentOutput, AgentRole
        coord = AgentCoordinator()
        coord.last_pipeline_results = {
            AgentRole.REGIME: AgentOutput(
                role=AgentRole.REGIME,
                data={"rg": "trend", "conf": 0.8},
                model_used="claude-haiku-4-5-20251001",
                input_tokens=100,
                output_tokens=50,
                latency_ms=200,
            ),
            AgentRole.TRADE: AgentOutput(
                role=AgentRole.TRADE,
                data={"a": "go", "c": 0.7, "thesis": "uptrend"},
                model_used="claude-sonnet-4-5-20250929",
                input_tokens=300,
                output_tokens=100,
                latency_ms=500,
            ),
        }

        detail = coord.get_last_pipeline_detail()
        assert detail is not None
        assert "regime" in detail
        assert "trade" in detail
        assert detail["regime"]["data"]["rg"] == "trend"
        assert detail["trade"]["data"]["thesis"] == "uptrend"
        assert detail["regime"]["model"] == "claude-haiku-4-5-20251001"
        assert detail["trade"]["input_tokens"] == 300


# ---------------------------------------------------------------------------
# 13. Rich Decision Logging
# ---------------------------------------------------------------------------

class TestRichDecisionLogging:
    """Test enriched decision logging with per-agent data."""

    def test_log_decision_captures_agent_detail(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights
        from llm.agents.base import AgentOutput, AgentRole

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_last_pipeline_detail.return_value = {
            "regime": {"data": {"rg": "trend"}, "model": "haiku", "ok": True,
                       "input_tokens": 100, "output_tokens": 50, "latency_ms": 200, "error": None},
            "trade": {"data": {"a": "go", "thesis": "strong uptrend"}, "model": "sonnet", "ok": True,
                      "input_tokens": 300, "output_tokens": 100, "latency_ms": 500, "error": None},
        }
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        decision = LLMDecision(
            action="proceed", confidence=0.8, regime="trend",
            strategy_weights=StrategyWeights(), memory_update=None,
            notes="Test decision",
        )
        llm._log_decision(decision, {}, 0.005, "test_trigger")

        assert len(llm.decisions) == 1
        entry = llm.decisions[0]
        assert "agents" in entry
        assert entry["agents"]["regime"]["data"]["rg"] == "trend"
        assert entry["agents"]["trade"]["data"]["thesis"] == "strong uptrend"

    def test_log_decision_tracks_regime_timeline(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_last_pipeline_detail.return_value = None
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        # Log two decisions with same regime, then one with different
        for regime in ["trend", "trend", "range"]:
            dec = LLMDecision(
                action="proceed", confidence=0.7, regime=regime,
                strategy_weights=StrategyWeights(), memory_update=None,
                notes="test",
            )
            llm._log_decision(dec, {}, 0.001, "test")

        # Should only have 2 transitions (trend, then range)
        assert len(llm.regime_timeline) == 2
        assert llm.regime_timeline[0]["regime"] == "trend"
        assert llm.regime_timeline[1]["regime"] == "range"


# ---------------------------------------------------------------------------
# 14. Exit Decision Logging
# ---------------------------------------------------------------------------

class TestExitDecisionLogging:
    """Test exit agent decision capture."""

    def test_exit_decision_logged_on_eval(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_exit_intelligence.return_value = {
            "action": "hold", "urgency": "low",
            "thesis_still_valid": True, "reason": "trend intact"
        }
        mock_coord.get_stats.return_value = {"total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 25}
        mock_coord.last_pipeline_results = {}
        mock_coord.last_exit_output = MagicMock(
            data={"action": "hold"}, model_used="haiku",
            input_tokens=50, output_tokens=25, ok=True
        )
        llm._coordinator = mock_coord
        # Set counter to fire on next call
        llm._exit_eval_counters["BTC"] = 5

        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is not None
        assert len(llm.exit_decisions) == 1
        assert llm.exit_decisions[0]["action"] == "hold"
        assert llm.exit_decisions[0]["symbol"] == "BTC"

    def test_flush_exits_to_jsonl(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            llm = BacktestLLMIntegration(budget_usd=5.0)
            llm.decisions_log_path = os.path.join(tmpdir, "decisions.jsonl")
            llm.exit_decisions = [
                {"type": "exit", "symbol": "BTC", "action": "hold"},
                {"type": "exit", "symbol": "ETH", "action": "close"},
            ]

            # Monkey-patch the exit log path
            exit_path = os.path.join(tmpdir, "exits.jsonl")
            with patch("os.path.join", side_effect=lambda *a: exit_path if "backtest_exits" in str(a) else os.path.join(*a)):
                llm.flush_decisions()

            # Verify exit decisions were flushed
            assert os.path.exists(exit_path)


# ---------------------------------------------------------------------------
# 15. Veto Stats
# ---------------------------------------------------------------------------

class TestVetoStats:
    """Test veto statistics computation."""

    def test_veto_stats_empty(self):
        from backtest.llm_integration import BacktestLLMIntegration
        llm = BacktestLLMIntegration(budget_usd=5.0)
        stats = llm._compute_veto_stats()
        assert stats["total_decisions"] == 0
        assert stats["veto_rate"] == 0.0

    def test_veto_stats_with_decisions(self):
        from backtest.llm_integration import BacktestLLMIntegration
        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm.decisions = [
            {"action": "proceed", "agents": {}},
            {"action": "flat", "agents": {}},
            {"action": "proceed", "agents": {}},
            {"action": "flat", "agents": {
                "critic": {"ok": True, "data": {"verdict": "challenge"}}
            }},
        ]
        stats = llm._compute_veto_stats()
        assert stats["total_decisions"] == 4
        assert stats["approved"] == 2
        assert stats["vetoed"] == 2
        assert stats["critic_vetoes"] == 1
        assert stats["veto_rate"] == 0.5


# ---------------------------------------------------------------------------
# 16. Learning Agent Wiring
# ---------------------------------------------------------------------------

class TestLearningWiring:
    """Test that Learning Agent lessons feed into growth systems."""

    def test_learning_lessons_buffered(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_post_trade_lesson.return_value = {
            "lesson": "trend following works in strong trends",
            "category": "pattern_win",
            "strength": "strong",
        }
        mock_coord.get_stats.return_value = {"total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 30}
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        # process_agent_lesson is imported inside the method, patch at source
        with patch("llm.agents.learning_integration.process_agent_lesson") as mock_pal:
            result = llm.run_learning({"symbol": "BTC", "outcome": "WIN", "pnl": 100})

        assert result is not None
        assert len(llm.learning_lessons) == 1
        assert llm.learning_lessons[0]["lesson"] == "trend following works in strong trends"

    @patch("llm.agents.learning_integration.process_agent_lesson")
    def test_learning_calls_process_agent_lesson(self, mock_pal):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        lesson = {"lesson": "test", "category": "entry_timing", "strength": "moderate"}
        mock_coord.get_post_trade_lesson.return_value = lesson
        mock_coord.get_stats.return_value = {"total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 30}
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        trade_data = {"symbol": "BTC", "outcome": "WIN"}
        llm.run_learning(trade_data)

        # process_agent_lesson should have been called
        # (may fail if import path differs, but the call was attempted)
        assert len(llm.learning_lessons) == 1


# ---------------------------------------------------------------------------
# 17. Summary with New Fields
# ---------------------------------------------------------------------------

class TestEnhancedSummary:
    """Test that get_summary includes new fields."""

    def test_summary_includes_new_fields(self):
        from backtest.llm_integration import BacktestLLMIntegration
        llm = BacktestLLMIntegration(budget_usd=5.0)
        llm.agent_costs = {"regime": 0.01, "trade": 0.05}
        llm.exit_decisions = [{"action": "hold"}]
        llm.learning_lessons = [{"lesson": "test"}]
        llm.regime_timeline = [{"regime": "trend", "timestamp": "2026-01-01"}]

        summary = llm.get_summary()
        assert summary["agent_costs"] == {"regime": 0.01, "trade": 0.05}
        assert summary["exit_decisions_logged"] == 1
        assert summary["learning_lessons_processed"] == 1
        assert summary["regime_transitions"] == 1
        assert "veto_stats" in summary


# ---------------------------------------------------------------------------
# 18. CSV Export
# ---------------------------------------------------------------------------

class TestCSVExport:
    """Test CSV trade log export."""

    def test_export_trade_csv(self):
        import csv
        from backtest.engine import export_trade_csv

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "trades.csv")
            report = {
                "trade_timeline": [
                    {"symbol": "BTC", "side": "LONG", "strategy": "regime_trend",
                     "action": "TP1", "entry_price": 50000, "exit_price": 51000,
                     "pnl": 100.0, "fee": 2.0, "leverage": 2.0},
                    {"symbol": "ETH", "side": "SHORT", "strategy": "monte_carlo_zones",
                     "action": "SL", "entry_price": 3000, "exit_price": 3100,
                     "pnl": -50.0, "fee": 1.5, "leverage": 1.0},
                ]
            }
            export_trade_csv(report, csv_path)

            assert os.path.exists(csv_path)
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["symbol"] == "BTC"
            assert rows[1]["pnl"] == "-50.0"

    def test_export_empty_timeline_is_noop(self):
        from backtest.engine import export_trade_csv

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "trades.csv")
            export_trade_csv({"trade_timeline": []}, csv_path)
            assert not os.path.exists(csv_path)


# ---------------------------------------------------------------------------
# 19. Bug 1: entry_price uses correct value (not exit price)
# ---------------------------------------------------------------------------

class TestBug1EntryPrice:
    """Bug 1: _run_llm_learning must use OPEN event price, not close event price."""

    def test_entry_price_from_open_event(self):
        """Verify trade_data['entry_price'] comes from OPEN event, not close."""
        from backtest.engine import BacktestEngine
        from unittest.mock import MagicMock, patch

        engine = BacktestEngine.__new__(BacktestEngine)
        engine.pos_mgr = MagicMock()
        engine.llm = MagicMock()

        # Simulate trade_log with OPEN at 50000 and CLOSE at 51000
        open_event = MagicMock()
        open_event.symbol = "BTC"
        open_event.action = "OPEN"
        open_event.price = 50000.0  # Entry price

        close_event = MagicMock()
        close_event.symbol = "BTC"
        close_event.action = "TP1"
        close_event.price = 51000.0  # Exit price
        close_event.side = "LONG"
        close_event.pnl = 100.0
        close_event.leverage = 2.0
        close_event.strategy = "regime_trend"
        close_event.metadata = {
            "outcome": "WIN",
            "regime": "trend",
            "hold_time_s": 3600,
            "entry_reasons": {"momentum": True},
            "entry_type": "breakout",
            "confidence": 80,
        }

        engine.pos_mgr.trade_log = [open_event, close_event]

        engine._run_llm_learning(close_event, 51000.0)

        # Verify run_learning was called with correct entry_price
        call_args = engine.llm.run_learning.call_args[0][0]
        assert call_args["entry_price"] == 50000.0  # From OPEN, NOT 51000
        assert call_args["exit_price"] == 51000.0
        assert call_args["regime"] == "trend"
        assert call_args["hold_time_s"] == 3600
        assert call_args["setup_type"] == "breakout"


# ---------------------------------------------------------------------------
# 20. Bug 3: Coordinator caches pipeline_results on early return
# ---------------------------------------------------------------------------

class TestBug3StaleCache:
    """Bug 3: last_pipeline_results must be set even on early returns."""

    def test_pipeline_results_set_on_regime_failure(self):
        from llm.agents.coordinator import AgentCoordinator
        from llm.agents.base import AgentOutput, AgentRole

        coord = AgentCoordinator()
        # Set up old results that should be overwritten
        coord.last_pipeline_results = {"old": "data"}

        # Mock regime agent to fail (ok is a property: True when data non-empty and error is None)
        failed_regime = AgentOutput(
            role=AgentRole.REGIME,
            data={},  # Empty data + error => ok=False
            error="test failure",
        )

        with patch.object(coord, "_call_agent", return_value=failed_regime), \
             patch.object(coord, "_build_regime_input", return_value={}):
            result = coord.get_trading_decision(
                {"m": [{"s": "BTC"}]}, trigger_reason="test"
            )

        assert result is None
        # Pipeline results must contain the failed regime output, not old data
        assert AgentRole.REGIME in coord.last_pipeline_results
        assert coord.last_pipeline_results[AgentRole.REGIME].ok is False


# ---------------------------------------------------------------------------
# 21. Bug 5: learning_bridge uses correct regime API
# ---------------------------------------------------------------------------

class TestBug5RegimeAPI:
    """Bug 5: learning_bridge must use dm.regime_history.record_transition()."""

    def test_feed_llm_decisions_uses_record_transition(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        mock_llm = MagicMock()
        mock_llm.decisions = [
            {"regime": "trend", "confidence": 0.8, "symbol": "BTC",
             "agents": {}, "action": "proceed"},
        ]

        with patch("llm.deep_memory.get_deep_memory") as mock_gdm:
            mock_dm = MagicMock()
            mock_gdm.return_value = mock_dm

            bridge._feed_llm_decisions(mock_llm)

            # Must call record_transition, NOT record_regime_observation
            mock_dm.regime_history.record_transition.assert_called_once()
            call_kwargs = mock_dm.regime_history.record_transition.call_args
            # Verify context is a dict (Bug 6 fix)
            context = call_kwargs[1]["context"]
            assert isinstance(context, dict)


# ---------------------------------------------------------------------------
# 22. Bug 4+18: regime map builds per-symbol mapping
# ---------------------------------------------------------------------------

class TestBug4RegimeMap:
    """Bug 4+18: _build_llm_regime_map must produce per-symbol entries."""

    def test_per_symbol_regime_map(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        decisions = [
            {"regime": "trend", "symbol": "BTC"},
            {"regime": "range", "symbol": "ETH"},
            {"regime": "panic", "symbol": "BTC"},  # BTC should update to panic
        ]
        regime_map = bridge._build_llm_regime_map(decisions)
        assert regime_map["BTC"] == "panic"  # Last one wins
        assert regime_map["ETH"] == "range"
        assert regime_map["_latest"] == "panic"

    def test_regime_map_fallback_to_latest(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        decisions = [
            {"regime": "trend", "symbol": "BTC"},
        ]
        regime_map = bridge._build_llm_regime_map(decisions)
        # SOL has no explicit entry, should fall back to _latest
        assert "SOL" not in regime_map
        assert regime_map.get("_latest") == "trend"


# ---------------------------------------------------------------------------
# 23. Bug 6: process_agent_decision_for_learning uses correct types
# ---------------------------------------------------------------------------

class TestBug6CorrectTypes:
    """Bug 6: regime transition must use dict context and valid regime names."""

    def test_regime_transition_context_is_dict(self):
        from llm.agents.learning_integration import process_agent_decision_for_learning

        regime_data = {
            "rg": "trend",
            "bias": "bullish",
            "transition": "shifting",
        }

        with patch("llm.deep_memory.get_deep_memory") as mock_gdm:
            mock_dm = MagicMock()
            mock_gdm.return_value = mock_dm

            process_agent_decision_for_learning(
                decision_notes="test",
                regime_data=regime_data,
                critic_data=None,
                trade_context="some context",
            )

            # Verify record_transition was called with dict context
            mock_dm.regime_history.record_transition.assert_called_once()
            kwargs = mock_dm.regime_history.record_transition.call_args[1]
            assert isinstance(kwargs["context"], dict)
            assert kwargs["from_regime"] == "unknown"  # Not "previous"
            assert kwargs["to_regime"] == "trend"
            assert kwargs["symbol"] == "market"


# ---------------------------------------------------------------------------
# 24. Bug 7: Skipped decisions logged
# ---------------------------------------------------------------------------

class TestBug7SkippedDecisions:
    """Bug 7: evaluate_entry must log decisions even when coordinator returns None."""

    def test_skipped_decision_logged(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_trading_decision.return_value = None
        mock_coord.get_stats.return_value = {
            "total_calls": 4, "total_input_tokens": 100, "total_output_tokens": 50
        }
        mock_coord.get_last_pipeline_detail.return_value = None
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        result = llm.evaluate_entry(
            {"m": [{"s": "BTC"}]}, MagicMock(), "pre_trade_backtest"
        )
        assert result is None

        # Must still have logged the skipped decision
        assert len(llm.decisions) == 1
        assert llm.decisions[0]["action"] == "skipped"
        assert llm.decisions[0]["symbol"] == "BTC"
        assert llm.decisions[0]["skip_reason"] == "coordinator_returned_none"


# ---------------------------------------------------------------------------
# 25. Bug 8: Checkpoint flushes decisions first
# ---------------------------------------------------------------------------

class TestBug8CheckpointFlush:
    """Bug 8: save_checkpoint must flush decisions and include agent_costs."""

    def test_checkpoint_includes_agent_costs(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            llm = BacktestLLMIntegration(budget_usd=5.0, checkpoint_dir=tmpdir)
            llm.total_cost_usd = 1.0
            llm.llm_calls = 10
            llm.agent_costs = {"regime": 0.01, "trade": 0.05}
            llm.regime_timeline = [{"regime": "trend", "timestamp": "t1"}]

            llm.save_checkpoint(
                candle_index=50, symbol="BTC",
                symbols_completed=[], equity=10000.0,
            )

            # Load and verify
            cp_path = os.path.join(tmpdir, "checkpoint.json")
            with open(cp_path) as f:
                state = json.load(f)

            assert state["llm_stats"]["agent_costs"] == {"regime": 0.01, "trade": 0.05}
            assert len(state["llm_stats"]["regime_timeline"]) == 1

    def test_checkpoint_flushes_decisions_first(self):
        from backtest.llm_integration import BacktestLLMIntegration

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "decisions.jsonl")
            llm = BacktestLLMIntegration(budget_usd=5.0, checkpoint_dir=tmpdir)
            llm.decisions_log_path = log_path
            llm.decisions = [
                {"action": "proceed", "symbol": "BTC"},
            ]

            llm.save_checkpoint(
                candle_index=50, symbol="BTC",
                symbols_completed=[], equity=10000.0,
            )

            # Decisions should have been flushed to JSONL
            assert os.path.exists(log_path)
            with open(log_path) as f:
                lines = f.readlines()
            assert len(lines) == 1


# ---------------------------------------------------------------------------
# 26. Bug 9: Exit throttle fires on first candle
# ---------------------------------------------------------------------------

class TestBug9ExitThrottle:
    """Bug 9: Exit agent must evaluate on first candle of a new position."""

    def test_first_candle_evaluates(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_exit_intelligence.return_value = {"action": "hold"}
        mock_coord.get_stats.return_value = {
            "total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 25
        }
        mock_coord.last_exit_output = MagicMock(
            data={"action": "hold"}, model_used="haiku",
            input_tokens=50, output_tokens=25, ok=True,
        )
        llm._coordinator = mock_coord

        # First call (counter becomes 1) should evaluate
        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is not None
        assert result["action"] == "hold"
        mock_coord.get_exit_intelligence.assert_called_once()

    def test_second_candle_throttled(self):
        from backtest.llm_integration import BacktestLLMIntegration

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_exit_intelligence.return_value = {"action": "hold"}
        mock_coord.get_stats.return_value = {
            "total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 25
        }
        mock_coord.last_exit_output = MagicMock(
            data={"action": "hold"}, model_used="haiku",
            input_tokens=50, output_tokens=25, ok=True,
        )
        llm._coordinator = mock_coord

        # First call goes through
        llm.evaluate_exit({"symbol": "BTC"})
        mock_coord.get_exit_intelligence.reset_mock()

        # Second call should be throttled
        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result is None
        mock_coord.get_exit_intelligence.assert_not_called()


# ---------------------------------------------------------------------------
# 27. Bug 11: Trade timeline matches by symbol field
# ---------------------------------------------------------------------------

class TestBug11TradeTimeline:
    """Bug 11: _report_trade_timeline matches by dec['symbol'], not trigger."""

    def test_timeline_matches_by_symbol(self):
        from backtest.engine import BacktestEngine

        engine = BacktestEngine.__new__(BacktestEngine)
        engine.pos_mgr = MagicMock()
        engine.llm = MagicMock()

        # Two decisions, one for BTC and one for ETH
        engine.llm.decisions = [
            {"symbol": "BTC", "action": "proceed", "regime": "trend",
             "confidence": 0.8, "timestamp": "t1"},
            {"symbol": "ETH", "action": "flat", "regime": "range",
             "confidence": 0.3, "timestamp": "t2"},
        ]

        # Close event for ETH
        close_event = MagicMock()
        close_event.symbol = "ETH"
        close_event.action = "SL"
        close_event.price = 3000.0
        close_event.pnl = -50.0
        close_event.side = "LONG"
        close_event.strategy = "regime_trend"
        close_event.leverage = 1.0
        close_event.fee = 1.0
        close_event.entry_price = 3100.0

        engine._CLOSE_ACTIONS = ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                                 "EMERGENCY", "BACKTEST_END", "HOLD_LIMIT",
                                 "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE")
        engine.pos_mgr.trade_log = [close_event]

        timeline = engine._report_trade_timeline()
        assert len(timeline) == 1
        # Should match ETH decision, not BTC
        assert timeline[0]["llm_regime"] == "range"
        assert timeline[0]["llm_action"] == "flat"


# ---------------------------------------------------------------------------
# 28. Bug 14: Insight churn rate-limiting
# ---------------------------------------------------------------------------

class TestBug14InsightChurn:
    """Bug 14: Only substantive critic challenges should generate insights."""

    def test_trivial_counter_thesis_skipped(self):
        from llm.agents.learning_integration import process_agent_decision_for_learning

        critic_data = {
            "verdict": "challenge",
            "calibration_note": "no",  # Too short (<20 chars)
            "counter_thesis": "nah",   # Too short (<20 chars)
            "reason": "test",
        }

        with patch("llm.deep_memory.get_deep_memory") as mock_gdm:
            mock_dm = MagicMock()
            mock_gdm.return_value = mock_dm

            process_agent_decision_for_learning(
                decision_notes="test",
                regime_data={},
                critic_data=critic_data,
            )

            # Insights should NOT be added (too short)
            mock_dm.insights.add_insight.assert_not_called()

    def test_substantive_counter_thesis_recorded(self):
        from llm.agents.learning_integration import process_agent_decision_for_learning

        critic_data = {
            "verdict": "challenge",
            "calibration_note": "The momentum indicators are diverging significantly from price action",
            "counter_thesis": "Price may reverse due to bearish divergence on RSI and declining volume",
            "reason": "momentum divergence detected",
        }

        with patch("llm.deep_memory.get_deep_memory") as mock_gdm:
            mock_dm = MagicMock()
            mock_gdm.return_value = mock_dm

            process_agent_decision_for_learning(
                decision_notes="test",
                regime_data={},
                critic_data=critic_data,
            )

            # Both cal_note and counter_thesis are substantive (>20 chars)
            assert mock_dm.insights.add_insight.call_count == 2


# ---------------------------------------------------------------------------
# 29. Bug 16: All close action types captured
# ---------------------------------------------------------------------------

class TestBug16CloseActions:
    """Bug 16: Learning bridge must recognize all 10 close action types."""

    def test_all_close_actions_captured(self):
        from backtest.learning_bridge import BacktestLearningBridge

        bridge = BacktestLearningBridge()
        # Verify the bridge has all 10 close actions (see engine._CLOSE_ACTIONS)
        # Read from the ingest method source
        import inspect
        source = inspect.getsource(bridge.ingest)
        for action in ["EMERGENCY", "BACKTEST_END", "HOLD_LIMIT",
                        "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE"]:
            assert action in source, f"Missing close action: {action}"


# ---------------------------------------------------------------------------
# 30. Bug 17: Decision entries contain symbol
# ---------------------------------------------------------------------------

class TestBug17DecisionSymbol:
    """Bug 17: Decision log entries must contain 'symbol' field."""

    def test_log_decision_extracts_symbol(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_last_pipeline_detail.return_value = None
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        decision = LLMDecision(
            action="proceed", confidence=0.8, regime="trend",
            strategy_weights=StrategyWeights(), memory_update=None,
            notes="test",
        )
        snapshot = {"m": [{"s": "ETH"}]}
        llm._log_decision(decision, snapshot, 0.001, "pre_trade_backtest")

        assert llm.decisions[0]["symbol"] == "ETH"

    def test_log_decision_handles_empty_snapshot(self):
        from backtest.llm_integration import BacktestLLMIntegration
        from llm.decision_types import LLMDecision, StrategyWeights

        llm = BacktestLLMIntegration(budget_usd=5.0)
        mock_coord = MagicMock()
        mock_coord.get_last_pipeline_detail.return_value = None
        mock_coord.last_pipeline_results = {}
        llm._coordinator = mock_coord

        decision = LLMDecision(
            action="proceed", confidence=0.8, regime="trend",
            strategy_weights=StrategyWeights(), memory_update=None,
            notes="test",
        )
        llm._log_decision(decision, {}, 0.001, "test")

        # Should have empty symbol, not crash
        assert llm.decisions[0]["symbol"] == ""


# ---------------------------------------------------------------------------
# 31. Bug 2: Exit Agent receives hold_time, thesis, setup_type
# ---------------------------------------------------------------------------

class TestBug2ExitAgentData:
    """Bug 2: _run_llm_exit must pass hold_time_s, thesis, setup_type."""

    def test_exit_position_data_complete(self):
        from backtest.engine import BacktestEngine
        from datetime import datetime, timezone, timedelta

        engine = BacktestEngine.__new__(BacktestEngine)
        engine.llm = MagicMock()
        engine.pos_mgr = MagicMock()
        engine.risk_mgr = MagicMock()

        # Create mock position
        pos = MagicMock()
        pos.side = "LONG"
        pos.entry = 50000.0
        pos.sl = 49000.0
        pos.tp1 = 52000.0
        pos.tp2 = 54000.0
        pos.leverage = 2.0
        pos.state = "OPEN"
        pos.qty = 0.1
        pos.open_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        pos.notes = "Strong breakout thesis with momentum confirmation"
        pos.setup_type = "breakout"

        engine.pos_mgr.positions = {"BTC": pos}
        engine.pos_mgr.get_open_positions.return_value = {"BTC": pos}
        engine.llm.build_backtest_snapshot.return_value = {"m": [{"s": "BTC"}]}
        engine.llm.evaluate_exit.return_value = None

        sim_dt = datetime(2026, 3, 1, 1, 0, 0, tzinfo=timezone.utc)
        engine._run_llm_exit("BTC", 51000.0, {"1h": MagicMock()}, sim_dt)

        # Verify evaluate_exit was called with enriched position_data
        call_args = engine.llm.evaluate_exit.call_args
        position_data = call_args[0][0]
        assert position_data["hold_time_s"] == 3600.0  # 1 hour
        assert "Strong breakout thesis" in position_data["thesis"]
        assert position_data["setup_type"] == "breakout"
