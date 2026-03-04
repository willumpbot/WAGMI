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
        llm._coordinator = mock_coord

        # First 5 calls should be throttled (interval is 6)
        for _ in range(5):
            result = llm.evaluate_exit({"symbol": "BTC"})
            assert result is None

        # 6th call should go through
        mock_coord.get_exit_intelligence.return_value = {"action": "hold"}
        mock_coord.get_stats.return_value = {"total_calls": 1, "total_input_tokens": 50, "total_output_tokens": 25}
        result = llm.evaluate_exit({"symbol": "BTC"})
        assert result == {"action": "hold"}
        mock_coord.get_exit_intelligence.assert_called_once()

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
