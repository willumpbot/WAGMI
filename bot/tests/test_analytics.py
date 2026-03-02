"""
Tests for Wave 3/4 analytics modules:
  - A/B Testing: full lifecycle (create, assign, record, evaluate)
  - Counterfactual: veto recording, resolution with prices, accuracy
  - Meta-Learning: feed synthetic trades, analyze patterns, get insights
  - Portfolio Risk: record prices, compute correlations, verify values
"""

import math
import os
import sys
import tempfile
import time

import pytest

# Ensure bot/ is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── A/B Testing ────────────────────────────────────────────────


class TestABTesting:

    def test_ab_testing_full_lifecycle(self):
        """Create experiment -> assign groups -> record outcomes -> evaluate."""
        from analytics.ab_testing import ABTestManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ABTestManager(data_dir=tmpdir)

            # 1. Create experiment
            exp_id = mgr.create_experiment(
                name="Higher confidence floor",
                description="Test raising confidence floor from 55 to 65",
                parameter_name="confidence_floor",
                control_value=55.0,
                variant_value=65.0,
                min_trades=5,  # Low threshold for test
                max_duration_days=14,
            )

            assert exp_id.startswith("exp_")
            assert len(mgr.get_active_experiments()) == 1

            # 2. Assign and record outcomes for both groups
            # Record enough control and variant outcomes to evaluate
            for i in range(10):
                group = mgr.get_assignment(exp_id, symbol="BTC/USDT", trace_id=f"trace_{i}")
                assert group in ("control", "variant")

                # Make variant systematically better for a clear signal
                if group == "variant":
                    mgr.record_outcome(exp_id, group, "BTC/USDT", pnl=10.0, win=True)
                else:
                    mgr.record_outcome(exp_id, group, "BTC/USDT", pnl=-5.0, win=False)

            # Also add more data to ensure both groups have min_trades
            for i in range(20):
                mgr.record_outcome(
                    exp_id, "control", "BTC/USDT",
                    pnl=-2.0, win=False,
                )
                mgr.record_outcome(
                    exp_id, "variant", "BTC/USDT",
                    pnl=8.0, win=True,
                )

            # 3. Evaluate
            result = mgr.evaluate_experiment(exp_id)

            assert result.experiment_id == exp_id
            assert result.control_trades >= 5
            assert result.variant_trades >= 5
            assert result.variant_win_rate > result.control_win_rate
            assert result.variant_avg_pnl > result.control_avg_pnl
            assert result.recommended_action in (
                "graduate_variant", "keep_control", "needs_more_data"
            )

            # 4. Verify config retrieval
            control_cfg = mgr.get_config_for_group(exp_id, "control")
            variant_cfg = mgr.get_config_for_group(exp_id, "variant")
            assert control_cfg["confidence_floor"] == 55.0
            assert variant_cfg["confidence_floor"] == 65.0

    def test_ab_testing_deterministic_assignment(self):
        """Same inputs always produce the same group assignment."""
        from analytics.ab_testing import ABTestManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ABTestManager(data_dir=tmpdir)
            exp_id = mgr.create_experiment(
                name="Test",
                description="Determinism check",
                parameter_name="param",
                control_value=1.0,
                variant_value=2.0,
            )

            # Same inputs -> same output
            group1 = mgr.get_assignment(exp_id, "BTC/USDT", "trace_abc")
            group2 = mgr.get_assignment(exp_id, "BTC/USDT", "trace_abc")
            assert group1 == group2

            # Different trace -> can differ
            group3 = mgr.get_assignment(exp_id, "BTC/USDT", "trace_xyz")
            # (We don't assert group3 != group1 because it's hash-based)
            assert group3 in ("control", "variant")


# ── Counterfactual Engine ──────────────────────────────────────


class TestCounterfactual:

    def test_counterfactual_veto_resolution(self):
        """Record a veto -> resolve with prices -> check accuracy."""
        from analytics.counterfactual import CounterfactualEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CounterfactualEngine(data_dir=tmpdir)

            # Record a vetoed long trade
            scenario_id = engine.record_veto(
                symbol="BTC/USDT",
                side="long",
                entry_price=50000.0,
                sl_price=49000.0,
                tp1_price=51500.0,
                tp2_price=53000.0,
                confidence=72.0,
                reason="LLM veto: regime mismatch",
            )

            assert scenario_id is not None

            # Verify scenario is pending
            stats = engine.get_summary_stats()
            assert stats["total_scenarios"] == 1
            assert stats["pending"] == 1

            # Resolve: price hit TP1 => veto was wrong (missed profit)
            resolved_count = engine.resolve_pending(
                {"BTC/USDT": 52000.0},  # Above TP1 (51500) but below TP2 (53000)
                lookback_hours=24,
            )
            assert resolved_count == 1

            # Verify veto accuracy: the veto was wrong because price went up
            veto_acc = engine.get_veto_accuracy()
            assert veto_acc["total_vetoes"] == 1
            assert veto_acc["resolved"] == 1
            assert veto_acc["wrong_vetoes"] == 1  # We missed a winner
            assert veto_acc["correct_vetoes"] == 0

    def test_counterfactual_veto_correct(self):
        """Veto was correct when price hits SL."""
        from analytics.counterfactual import CounterfactualEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CounterfactualEngine(data_dir=tmpdir)

            engine.record_veto(
                symbol="ETH/USDT",
                side="long",
                entry_price=3000.0,
                sl_price=2900.0,
                tp1_price=3150.0,
                tp2_price=3300.0,
                confidence=60.0,
                reason="Low confidence veto",
            )

            # Price dropped to SL => veto was correct (dodged a loss)
            resolved = engine.resolve_pending(
                {"ETH/USDT": 2850.0},  # Below SL of 2900
                lookback_hours=24,
            )
            assert resolved == 1

            veto_acc = engine.get_veto_accuracy()
            assert veto_acc["correct_vetoes"] == 1
            assert veto_acc["wrong_vetoes"] == 0
            assert veto_acc["accuracy_pct"] == 100.0

    def test_counterfactual_exit_timing(self):
        """Record exit timing alternative and verify delta computation."""
        from analytics.counterfactual import CounterfactualEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CounterfactualEngine(data_dir=tmpdir)

            # Exited at TP1, counterfactual asks: what if we held to TP2?
            scenario_id = engine.record_exit_alternative(
                symbol="SOL/USDT",
                actual_exit_action="TP1",
                actual_exit_price=150.0,
                tp1_price=150.0,
                tp2_price=170.0,
                entry_price=100.0,
                actual_pnl=50.0,
            )

            assert scenario_id is not None

            # Exit alternatives are immediately resolved
            stats = engine.get_summary_stats()
            assert stats["pending"] == 0
            assert stats["total_scenarios"] == 1


# ── Meta-Learning Engine ───────────────────────────────────────


class TestMetaLearning:

    def _make_synthetic_trades(self, count: int = 30) -> list:
        """Generate synthetic trades with varied properties."""
        trades = []
        base_ts = time.time() - 86400  # Start from 24h ago
        strategies = ["momentum", "mean_reversion", "breakout"]

        for i in range(count):
            pnl = 10.0 if i % 3 != 0 else -15.0  # ~67% win rate
            trades.append({
                "timestamp": (base_ts + i * 1800),  # 30min intervals
                "symbol": "BTC/USDT" if i % 2 == 0 else "ETH/USDT",
                "strategy": strategies[i % len(strategies)],
                "side": "long" if i % 2 == 0 else "short",
                "pnl": pnl,
                "confidence": 60.0 + (i % 4) * 10,
                "leverage": 2.0 + (i % 3),
                "regime": "trending" if i % 2 == 0 else "ranging",
            })
        return trades

    def test_meta_learning_pattern_analysis(self):
        """Feed synthetic trades -> analyze -> get insights."""
        from analytics.meta_learning import MetaLearningEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MetaLearningEngine(data_dir=tmpdir)

            trades = self._make_synthetic_trades(30)
            insights = engine.analyze_decision_patterns(trades, lookback_days=7)

            # With 30 trades across multiple strategies, time buckets, and
            # regimes, we should discover some patterns
            assert isinstance(insights, list)
            # The engine should have loaded properly
            assert engine._loaded is True

            # Get a report — should not error even with minimal data
            report = engine.get_meta_report()
            assert isinstance(report, str)
            assert "META-LEARNING" in report

    def test_meta_learning_tick(self):
        """The tick() method orchestrates analysis without errors."""
        from analytics.meta_learning import MetaLearningEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MetaLearningEngine(data_dir=tmpdir)
            trades = self._make_synthetic_trades(20)

            # tick() should run without errors
            engine.tick(recent_trades=trades, market_state={"regime": "trending"})

            # Verify tick state was updated
            assert engine._tick_state["total_ticks"] >= 1

    def test_meta_learning_empty_trades(self):
        """analyze_decision_patterns handles empty trade list gracefully."""
        from analytics.meta_learning import MetaLearningEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MetaLearningEngine(data_dir=tmpdir)
            insights = engine.analyze_decision_patterns([], lookback_days=7)
            assert insights == []


# ── Portfolio Risk Engine ──────────────────────────────────────


class TestPortfolioRisk:

    def test_portfolio_risk_correlation(self):
        """Record prices -> compute correlation matrix -> verify values."""
        from analytics.portfolio_risk import PortfolioRiskEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PortfolioRiskEngine(data_dir=tmpdir)

            # Generate correlated price series: BTC and ETH move together,
            # DOGE moves inversely.
            base_time = time.time() - 3600 * 24  # 24h ago
            num_points = 100

            for i in range(num_points):
                ts = base_time + i * 600  # 10-minute intervals
                # BTC: uptrend with noise
                btc_price = 50000 + i * 50 + (i % 7) * 20
                # ETH: correlated with BTC (same direction, different scale)
                eth_price = 3000 + i * 3 + (i % 7) * 1.2
                # DOGE: inversely correlated (goes down as BTC goes up)
                doge_price = 0.15 - i * 0.0005 + (i % 7) * 0.0001

                engine.record_price("BTC/USDT", btc_price, timestamp=ts)
                engine.record_price("ETH/USDT", eth_price, timestamp=ts)
                engine.record_price("DOGE/USDT", doge_price, timestamp=ts)

            # Compute correlation matrix
            corr_matrix = engine.compute_correlation_matrix(
                symbols=["BTC/USDT", "ETH/USDT", "DOGE/USDT"],
                lookback_hours=48,
            )

            assert corr_matrix is not None
            assert len(corr_matrix.symbols) >= 2

            # BTC-ETH should be positively correlated (both trending up)
            btc_eth_corr = corr_matrix.get_correlation("BTC/USDT", "ETH/USDT")
            assert btc_eth_corr > 0.5, (
                f"Expected BTC-ETH positive correlation, got {btc_eth_corr}"
            )

            # Self-correlation is always 1.0
            assert corr_matrix.get_correlation("BTC/USDT", "BTC/USDT") == 1.0

            # Non-existent symbol returns 0.0
            assert corr_matrix.get_correlation("BTC/USDT", "FAKE/USDT") == 0.0

    def test_portfolio_risk_cluster_risk(self):
        """Cluster risk is high for same-direction correlated positions."""
        from analytics.portfolio_risk import CorrelationMatrix

        # Create a manually constructed correlation matrix
        symbols = ["BTC/USDT", "ETH/USDT"]
        matrix = [
            [1.0, 0.9],
            [0.9, 1.0],
        ]
        cm = CorrelationMatrix(
            symbols=symbols,
            matrix=matrix,
            timestamp=time.time(),
            lookback_hours=168,
        )

        # Two longs with high correlation = high risk
        risk_same = cm.get_cluster_risk({
            "BTC/USDT": "long",
            "ETH/USDT": "long",
        })
        assert risk_same > 0.5, f"Expected high cluster risk, got {risk_same}"

        # Long + short with high correlation = hedged (low risk)
        risk_hedged = cm.get_cluster_risk({
            "BTC/USDT": "long",
            "ETH/USDT": "short",
        })
        assert risk_hedged < 0.1, f"Expected low cluster risk for hedge, got {risk_hedged}"

    def test_portfolio_risk_volatility_forecast(self):
        """Record enough prices to compute a volatility forecast."""
        from analytics.portfolio_risk import PortfolioRiskEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PortfolioRiskEngine(data_dir=tmpdir)

            base_time = time.time() - 3600 * 48
            # Generate price series with known volatility
            for i in range(200):
                ts = base_time + i * 600
                # Price with ~1% hourly moves
                price = 50000 * (1.0 + 0.01 * math.sin(i * 0.3))
                engine.record_price("BTC/USDT", price, timestamp=ts)

            forecast = engine.forecast_volatility("BTC/USDT")
            assert forecast is not None
            assert forecast.symbol == "BTC/USDT"
            assert forecast.current_vol >= 0
            assert forecast.vol_regime in ("low", "normal", "high", "extreme")

    def test_portfolio_risk_empty(self):
        """Engine handles queries with no data gracefully."""
        from analytics.portfolio_risk import PortfolioRiskEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PortfolioRiskEngine(data_dir=tmpdir)

            # Correlation matrix with no data
            cm = engine.compute_correlation_matrix(
                symbols=["BTC/USDT"], lookback_hours=24,
            )
            assert cm is not None
            # Single symbol = no pairs to correlate
            assert len(cm.matrix) <= 1
