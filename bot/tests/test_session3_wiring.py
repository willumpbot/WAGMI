"""
Tests for Session 3 — Wiring built components into the live system.

Covers:
  - Go-live gate evaluation
  - Power analysis reactivation via shadow ledger
  - Correlation gate budget check
  - CVD signal strategy registration
  - Execution analytics fill tracking
  - Sector exposure limits
  - Walk-forward in continuous backtest deep cycle
"""

import math
import os
import sys
import tempfile
import time
import pytest

# Ensure bot/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Go-Live Gate ───────────────────────────────────────────────

class TestGoLiveGate:
    """Test go-live gate evaluation."""

    def test_evaluate_returns_structure(self):
        from validation.go_live_gate import GoLiveGate
        gate = GoLiveGate()
        result = gate.evaluate()
        assert "passed" in result
        assert "gates" in result
        assert "recommendation" in result
        assert "evaluated_at" in result
        assert len(result["gates"]) == 5

    def test_all_gates_without_data(self):
        from validation.go_live_gate import GoLiveGate
        gate = GoLiveGate()
        result = gate.evaluate()
        # Without any ledger/tracker, gates should be None (insufficient data)
        for gate_result in result["gates"].values():
            assert gate_result["passed"] is None or gate_result["passed"] is False

    def test_format_report(self):
        from validation.go_live_gate import GoLiveGate
        gate = GoLiveGate()
        result = gate.evaluate()
        text = gate.format_report(result)
        assert "GO-LIVE GATE EVALUATION" in text
        assert "walk_forward" in text
        assert "net_pnl" in text

    def test_gate_with_mock_ledger(self):
        from validation.go_live_gate import GoLiveGate

        class MockLedger:
            def get_trades(self, lookback_days=30):
                now = time.time()
                return [
                    {"net_pnl": "10.5", "timestamp": str(now - i * 3600),
                     "running_equity": str(10000 + i), "session_dd_pct": "2.0"}
                    for i in range(20)
                ]
            def get_agreement_breakdown(self, lookback_days=7):
                return {}
            def get_regime_breakdown(self, lookback_days=7):
                return {}

        gate = GoLiveGate(trade_ledger=MockLedger())
        result = gate.evaluate()
        # Net PnL gate should pass (positive PnL)
        assert result["gates"]["net_pnl"]["passed"] is True
        assert result["gates"]["net_pnl"]["value"] > 0


# ── Shadow Ledger + Power Analysis ────────────────────────────

class TestShadowLedgerReactivation:
    """Test power analysis wiring in shadow ledger."""

    def test_check_reactivation_insufficient_data(self):
        from feedback.shadow_ledger import ShadowLedger
        with tempfile.TemporaryDirectory() as tmpdir:
            sl = ShadowLedger(data_dir=tmpdir)
            # Record only 10 shadow trades (below 50 threshold)
            for i in range(10):
                sl.record_shadow_signal("lead_lag", "BTC", "BUY", 72.0, 65000.0 + i)
            sl.resolve_shadows("BTC", 66000.0)

            result = sl.check_reactivation("lead_lag")
            assert result is None  # Below threshold

    def test_check_reactivation_with_enough_data(self):
        from feedback.shadow_ledger import ShadowLedger
        with tempfile.TemporaryDirectory() as tmpdir:
            sl = ShadowLedger(data_dir=tmpdir)
            # Record 60 shadow trades (above 50 threshold)
            for i in range(60):
                sl.record_shadow_signal(
                    "test_strat", "BTC", "BUY", 72.0, 65000.0,
                    timestamp=time.time() - 100 + i
                )
            sl.resolve_shadows("BTC", 66000.0)  # All win

            result = sl.check_reactivation("test_strat")
            assert result is not None
            assert "strategy" in result
            assert result["shadow_trades"] >= 50
            assert result["shadow_win_rate"] > 0

    def test_resolve_triggers_reactivation_check(self):
        """Verify resolve_shadows triggers check_reactivation for resolved factors."""
        from feedback.shadow_ledger import ShadowLedger
        with tempfile.TemporaryDirectory() as tmpdir:
            sl = ShadowLedger(data_dir=tmpdir)
            # Record enough shadow trades
            for i in range(55):
                sl.record_shadow_signal(
                    "test_strat", "BTC", "BUY", 72.0, 65000.0,
                    timestamp=time.time() - 100 + i
                )
            # resolve_shadows should not crash when it tries check_reactivation
            count = sl.resolve_shadows("BTC", 66000.0)
            assert count == 55

    def test_get_factor_stats(self):
        from feedback.shadow_ledger import ShadowLedger
        with tempfile.TemporaryDirectory() as tmpdir:
            sl = ShadowLedger(data_dir=tmpdir)
            sl.record_shadow_signal("strat_a", "BTC", "BUY", 72.0, 65000.0)
            sl.resolve_shadows("BTC", 66000.0)
            stats = sl.get_factor_stats("strat_a")
            assert stats["count"] == 1
            assert stats["win_rate"] == 1.0
            assert stats["avg_return"] > 0


# ── Correlation Gate ──────────────────────────────────────────

class TestCorrelationGate:
    """Test correlation gate budget check."""

    def test_no_positions_full_size(self):
        from execution.correlation_gate import CorrelationGate
        gate = CorrelationGate()
        mult = gate.check_correlation_budget("BTC", "BUY", [])
        assert mult == 1.0

    def test_budget_check_with_positions(self):
        from execution.correlation_gate import CorrelationGate
        gate = CorrelationGate()
        # Feed some price data
        for i in range(50):
            gate.update_prices("BTC", 95000 + i * 10, time.time() - 50 + i)
            gate.update_prices("HYPE", 28.5 + i * 0.01, time.time() - 50 + i)
        mult = gate.check_correlation_budget(
            "HYPE", "BUY",
            [{"symbol": "BTC", "side": "BUY"}]
        )
        # Should be 1.0, 0.5, or 0.0 based on correlation
        assert mult in (0.0, 0.5, 1.0)

    def test_check_correlation_budget_api(self):
        from execution.correlation_gate import CorrelationGate
        gate = CorrelationGate()
        # Basic API test — should not crash
        result = gate.check_correlation_budget(
            new_symbol="ETH",
            new_side="LONG",
            open_positions=[{"symbol": "BTC", "side": "LONG"}],
        )
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


# ── CVD Signal Strategy ──────────────────────────────────────

class TestCVDSignal:
    """Test CVD signal strategy."""

    def test_strategy_instantiation(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        assert strat.name == "cvd_signal"

    def test_required_timeframes(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        assert "1h" in strat.get_required_timeframes()

    def test_evaluate_returns_none_on_empty_data(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        result = strat.evaluate("BTC", {})
        assert result is None

    def test_evaluate_returns_none_on_insufficient_data(self):
        import pandas as pd
        import numpy as np
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        # Only 5 candles — needs 30
        df = pd.DataFrame({
            "open": [100]*5, "high": [101]*5, "low": [99]*5,
            "close": [100.5]*5, "volume": [1000]*5,
        })
        result = strat.evaluate("BTC", {"1h": df})
        assert result is None


# ── Execution Analytics ───────────────────────────────────────

class TestExecutionAnalytics:
    """Test execution analytics fill tracking."""

    def test_record_fill(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea = ExecutionAnalytics(data_dir=tmpdir)
            result = ea.record_fill(
                trade_id="test-1",
                symbol="BTC",
                side="long",
                expected_price=95000,
                actual_fill=95019,
                notional=5000,
                regime="trending_bull",
            )
            assert "slippage_bps" in result
            assert result["slippage_bps"] > 0  # Paid more than expected for long

    def test_slippage_direction_for_short(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea = ExecutionAnalytics(data_dir=tmpdir)
            # For a short: getting a LOWER fill is worse (selling lower)
            result = ea.record_fill(
                trade_id="test-2",
                symbol="BTC",
                side="short",
                expected_price=95000,
                actual_fill=94980,
                notional=5000,
                regime="trending_bear",
            )
            # Selling lower than expected on a short = positive slippage (bad)
            assert result["slippage_bps"] > 0

    def test_get_slippage_summary(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea = ExecutionAnalytics(data_dir=tmpdir)
            for i in range(5):
                ea.record_fill(
                    trade_id=f"test-{i}",
                    symbol="BTC",
                    side="long",
                    expected_price=95000,
                    actual_fill=95000 + i * 5,
                    notional=5000,
                    regime="trending_bull",
                )
            summary = ea.get_slippage_summary()
            assert summary["total_fills"] == 5
            assert "overall_mean_bps" in summary
            assert "by_symbol" in summary
            assert "BTC" in summary["by_symbol"]

    def test_empty_summary(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea = ExecutionAnalytics(data_dir=tmpdir)
            summary = ea.get_slippage_summary()
            assert summary["total_fills"] == 0

    def test_worst_slippage_hours(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea = ExecutionAnalytics(data_dir=tmpdir)
            ea.record_fill("t1", "BTC", "long", 95000, 95050, 5000, "unknown")
            hours = ea.worst_slippage_hours(top_n=3)
            assert len(hours) <= 3

    def test_persistence(self):
        from execution.execution_analytics import ExecutionAnalytics
        with tempfile.TemporaryDirectory() as tmpdir:
            ea1 = ExecutionAnalytics(data_dir=tmpdir)
            ea1.record_fill("t1", "BTC", "long", 95000, 95020, 5000, "unknown")

            # New instance loads from disk
            ea2 = ExecutionAnalytics(data_dir=tmpdir)
            summary = ea2.get_slippage_summary()
            assert summary["total_fills"] == 1


# ── Sector Exposure ───────────────────────────────────────────

class TestSectorExposure:
    """Test sector/thematic exposure limits."""

    def test_no_positions_full_size(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        result = se.check_new_position("BTC", 10000, [])
        assert result.allowed is True
        assert result.size_multiplier == 1.0

    def test_l1_cap_triggers(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        # Finding 17 (2026-04-15): l1 cap was raised from 0.60 to 1.50 to
        # accommodate full-Kelly sizing (8% risk × 5x leverage = 40% notional
        # per position). Test now sizes positions to match the new cap: with
        # 150% cap on 50k equity = 75k headroom, we need 73k in positions to
        # leave only 2k headroom like the original intent.
        positions = [("BTC", 40000), ("SOL", 33000)]  # 73k total l1 exposure
        result = se.check_new_position("ETH", 5000, positions)
        # Should reduce or block — only 2k headroom out of 5k requested
        assert result.size_multiplier < 1.0

    def test_meme_cap_blocks(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        # Finding 17 (2026-04-15): meme cap raised from 0.20 to 0.40. Bumped
        # test positions to match: new cap = 40% of 50k = 20k. Existing 19k
        # in memes leaves 1k headroom against a 3k request.
        positions = [("DOGE", 10000), ("PEPE", 9000)]
        result = se.check_new_position("WIF", 3000, positions)
        # Should reduce (only 1k headroom out of 3k)
        assert result.size_multiplier < 1.0

    def test_unknown_symbol_allowed(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        result = se.check_new_position("UNKNOWN_TOKEN", 5000, [])
        assert result.allowed is True
        assert result.size_multiplier == 1.0

    def test_exposure_report(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        positions = [("BTC", 15000), ("SOL", 10000)]
        report = se.get_exposure_report(positions)
        assert "l1" in report
        assert report["l1"]["current_pct"] > 0

    def test_zero_notional_handled(self):
        from execution.sector_exposure import SectorExposure
        se = SectorExposure(total_equity=50000)
        result = se.check_new_position("BTC", 0, [])
        assert result.allowed is True


# ── Continuous Backtest WF Integration ────────────────────────

class TestContinuousBacktestWF:
    """Test walk-forward integration in continuous backtest deep cycle."""

    def test_deep_cycle_runs_wf(self):
        from feedback.continuous_backtest import ContinuousBacktester
        with tempfile.TemporaryDirectory() as tmpdir:
            cb = ContinuousBacktester(data_dir=tmpdir)
            # Record enough outcomes for a deep backtest
            for i in range(20):
                cb.record_outcome(
                    symbol="BTC",
                    win=i % 3 != 0,  # ~67% WR
                    pnl=10.0 if i % 3 != 0 else -15.0,
                    confidence_at_entry=70.0,
                    strategy="confidence_scorer",
                    regime="trending_bull",
                )
            # Force deep cycle
            cb.last_run["deep"] = 0
            result = cb._run_backtest("deep")
            assert result is not None
            assert result.win_rate > 0

    def test_wf_ratio_in_report(self):
        from feedback.continuous_backtest import ContinuousBacktester
        with tempfile.TemporaryDirectory() as tmpdir:
            cb = ContinuousBacktester(data_dir=tmpdir)
            cb._last_wf_ratio = 0.75
            report = cb.get_report()
            assert "walk_forward_ratio" in report
            assert report["walk_forward_ratio"] == 0.75


# ── Power Analysis ────────────────────────────────────────────

class TestPowerAnalysis:
    """Test power analysis module directly."""

    def test_min_sample_size(self):
        from validation.power_analysis import min_sample_for_significance
        n = min_sample_for_significance(base_wr=0.50, delta=0.10)
        assert n > 0
        assert n < 1000  # Reasonable range

    def test_can_reactivate_insufficient(self):
        from validation.power_analysis import can_reactivate_strategy
        result = can_reactivate_strategy(
            strategy_name="test",
            shadow_trades=10,
            shadow_win_rate=0.60,
            shadow_avg_pnl=0.005,
        )
        assert result["can_reactivate"] is False
        assert "WAIT" in result["recommendation"]

    def test_can_reactivate_significant(self):
        from validation.power_analysis import can_reactivate_strategy
        result = can_reactivate_strategy(
            strategy_name="test",
            shadow_trades=500,
            shadow_win_rate=0.62,
            shadow_avg_pnl=0.005,
        )
        assert result["can_reactivate"] is True
        assert "REACTIVATE" in result["recommendation"]

    def test_assess_sample_adequacy(self):
        from validation.power_analysis import assess_sample_adequacy
        result = assess_sample_adequacy(n_trades=50, win_rate=0.55)
        assert "adequate" in result
        assert "verdict" in result


# ── Daily Reporter Integration ────────────────────────────────

class TestDailyReporterGateIntegration:
    """Test daily reporter can be used alongside go-live gate."""

    def test_reporter_generates_report(self):
        from feedback.daily_report import DailyReporter

        class MockLedger:
            def get_trades(self, lookback_days=30):
                return []
            def get_agreement_breakdown(self, lookback_days=7):
                return {}
            def get_regime_breakdown(self, lookback_days=7):
                return {}

        reporter = DailyReporter(trade_ledger=MockLedger())
        report = reporter.generate_report()
        assert "metrics" in report
        assert "alerts" in report
        assert len(report["metrics"]) == 6


# ── CLI Gate Mode ─────────────────────────────────────────────

class TestCLIGateMode:
    """Test that gate mode is registered in CLI."""

    def test_gate_in_choices(self):
        """Verify 'gate' is a valid CLI mode."""
        import importlib
        import cli as cli_module
        importlib.reload(cli_module)
        # The argparse choices should include 'gate'
        # We test by checking the source code contains the mode
        import inspect
        source = inspect.getsource(cli_module.main)
        assert "gate" in source
