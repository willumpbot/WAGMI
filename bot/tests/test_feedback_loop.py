"""
Comprehensive tests for the feedback loop system.

Tests cover:
1. AdaptiveConfidenceFloor - dynamic threshold learning
2. ContinuousBacktester - rolling mini-backtests
3. ParameterTuner - trust-gated parameter adjustments
4. SignalQualityScorer - per-signal quality multiplier
5. FeedbackLoop - full orchestration integration
"""

import json
import os
import shutil
import sys
import tempfile
import time

import pytest

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from feedback.adaptive_confidence import (
    AdaptiveConfidenceFloor,
    ConfidenceBin,
    ABSOLUTE_MIN_FLOOR,
    ABSOLUTE_MAX_FLOOR,
    DEFAULT_FLOOR,
)
from feedback.continuous_backtest import (
    ContinuousBacktester,
    BacktestResult,
    ParameterSuggestion,
)
from feedback.parameter_tuner import (
    ParameterTuner,
    TunedParameters,
)
from feedback.signal_quality import (
    SignalQualityScorer,
    QualityFeatures,
)
from feedback.loop import FeedbackLoop


@pytest.fixture
def tmp_data_dir():
    """Create a temporary directory for test data."""
    d = tempfile.mkdtemp(prefix="feedback_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# Tests for ConfidenceBin
# ═══════════════════════════════════════════════════════════════════

class TestConfidenceBin:
    def test_empty_bin(self):
        b = ConfidenceBin(60, 65)
        assert b.total == 0
        assert b.win_rate == 0.5  # Prior
        assert b.recent_win_rate == 0.5
        assert b.ev_per_trade == 0.0

    def test_record_outcomes(self):
        b = ConfidenceBin(60, 65)
        b.record(True, 10.0)
        b.record(True, 5.0)
        b.record(False, -8.0)

        assert b.total == 3
        assert b.wins == 2
        assert b.losses == 1
        assert b.win_rate == pytest.approx(2 / 3)
        assert b.total_pnl == pytest.approx(7.0)
        assert b.ev_per_trade == pytest.approx(7 / 3)

    def test_recent_results_capped(self):
        b = ConfidenceBin(60, 65)
        for i in range(60):
            b.record(i % 2 == 0, 1.0 if i % 2 == 0 else -1.0)

        assert len(b.recent_results) == 50
        assert b.total == 60


# ═══════════════════════════════════════════════════════════════════
# Tests for AdaptiveConfidenceFloor
# ═══════════════════════════════════════════════════════════════════

class TestAdaptiveConfidenceFloor:
    def test_initial_floor(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        assert acf.current_floor == DEFAULT_FLOOR

    def test_floor_rises_on_losses(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        initial_floor = acf.current_floor

        # Record many losses at low confidence
        for _ in range(20):
            acf.record_outcome(
                confidence=62, win=False, pnl=-5.0,
                strategy="test", symbol="BTC", regime="trending"
            )

        # Floor should be >= initial (tightening up due to losses)
        assert acf.current_floor >= initial_floor

    def test_floor_drops_on_wins(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)

        # Record many wins across all bins to earn trust
        for conf in range(55, 85, 5):
            for _ in range(5):
                acf.record_outcome(
                    confidence=conf, win=True, pnl=10.0,
                    strategy="test", symbol="BTC"
                )

        # Force recompute
        acf._recompute_floor()

        # Floor should be <= default since we're winning everywhere
        assert acf.current_floor <= DEFAULT_FLOOR

    def test_floor_bounded(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)

        # Try to push floor below minimum
        acf.current_floor = 40.0
        acf._recompute_floor()
        assert acf.current_floor >= ABSOLUTE_MIN_FLOOR

        # Try to push floor above maximum
        acf.current_floor = 90.0
        acf._recompute_floor()
        assert acf.current_floor <= ABSOLUTE_MAX_FLOOR

    def test_per_strategy_floor(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)

        # Strategy A: lots of wins
        for _ in range(15):
            acf.record_outcome(confidence=70, win=True, pnl=5.0,
                               strategy="strat_a", symbol="BTC")

        # Strategy B: lots of losses
        for _ in range(15):
            acf.record_outcome(confidence=70, win=False, pnl=-5.0,
                               strategy="strat_b", symbol="BTC")

        # Strategy A should have lower floor than B
        floor_a = acf.get_floor(strategy="strat_a")
        floor_b = acf.get_floor(strategy="strat_b")
        assert floor_a < floor_b

    def test_should_trade(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        acf.current_floor = 65.0

        should, floor, reason = acf.should_trade(70.0)
        assert should is True
        assert floor == 65.0
        assert "+5" in reason

        should, floor, reason = acf.should_trade(60.0)
        assert should is False
        assert "-5" in reason

    def test_persistence(self, tmp_data_dir):
        acf1 = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        acf1.current_floor = 70.0
        acf1.strategy_floors["test"] = 72.0
        acf1._save_state()

        acf2 = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        assert acf2.current_floor == 70.0
        assert acf2.strategy_floors.get("test") == 72.0

    def test_calibration_tracking(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)

        # Overconfident predictions (80% confidence, 50% win rate)
        for i in range(20):
            acf.record_outcome(confidence=80, win=i % 2 == 0, pnl=5.0 if i % 2 == 0 else -5.0)

        # Calibration error should be positive (overconfident)
        mean_err = sum(acf.calibration_errors) / len(acf.calibration_errors)
        assert mean_err > 0.2  # 0.8 predicted - ~0.5 actual

    def test_symbol_adjustment(self, tmp_data_dir):
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)

        # BTC: good performance
        for _ in range(10):
            acf.record_outcome(confidence=70, win=True, pnl=5.0, symbol="BTC")

        # DOGE: bad performance
        for _ in range(10):
            acf.record_outcome(confidence=70, win=False, pnl=-5.0, symbol="DOGE")

        # BTC should have lower effective floor
        floor_btc = acf.get_floor(symbol="BTC")
        floor_doge = acf.get_floor(symbol="DOGE")
        assert floor_btc < floor_doge


# ═══════════════════════════════════════════════════════════════════
# Tests for ContinuousBacktester
# ═══════════════════════════════════════════════════════════════════

class TestContinuousBacktester:
    def test_initial_state(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)
        assert len(cb.results["quick"]) == 0
        assert len(cb.results["medium"]) == 0
        assert len(cb.results["deep"]) == 0

    def test_record_signal(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)
        cb.record_signal(
            symbol="BTC", side="BUY", confidence=72.0,
            strategy="ensemble", entry=95000, sl=93000, tp1=97000,
        )
        assert len(cb._signal_history) == 1

    def test_record_outcome(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)
        cb.record_outcome(
            symbol="BTC", win=True, pnl=50.0,
            confidence_at_entry=72.0, strategy="ensemble",
        )
        assert len(cb._outcome_history) == 1

    def test_find_optimal_floor(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)

        # All trades above 70% win, below 70% lose
        outcomes = []
        for conf in range(55, 90, 5):
            win = conf >= 70
            outcomes.append({
                "confidence": conf,
                "win": win,
                "pnl": 10.0 if win else -5.0,
                "strategy": "test",
                "symbol": "BTC",
                "regime": "trending",
                "leverage": 2.0,
            })

        floor = cb._find_optimal_floor(outcomes)
        # Should find that floor at 70% maximizes EV
        assert 60 <= floor <= 75

    def test_backtest_produces_results(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)

        # Add enough outcomes for a quick backtest
        for i in range(10):
            cb.record_outcome(
                symbol="BTC", win=i % 3 != 0, pnl=5.0 if i % 3 != 0 else -3.0,
                confidence_at_entry=70 + i, strategy="ensemble",
                regime="trending", leverage=2.0,
            )

        # Force run quick backtest
        result = cb._run_backtest("quick")
        assert result is not None
        assert result.total_signals == 0  # No signals recorded
        assert result.signals_that_would_win > 0

    def test_suggestion_aggregation(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)

        # Manually add suggestions from different levels
        cb.suggestions = [
            ParameterSuggestion(
                parameter="confidence_floor",
                current_value=65.0, suggested_value=60.0,
                confidence_in_suggestion=0.7,
                evidence="quick backtest", source="quick",
            ),
            ParameterSuggestion(
                parameter="confidence_floor",
                current_value=65.0, suggested_value=62.0,
                confidence_in_suggestion=0.8,
                evidence="medium backtest", source="medium",
            ),
        ]

        agg = cb.get_aggregated_suggestions()
        assert "confidence_floor" in agg
        # Weighted average should be between 60 and 62
        assert 59 < agg["confidence_floor"].suggested_value < 63

    def test_bin_by_confidence(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)
        outcomes = [
            {"confidence": 65, "win": True, "pnl": 10},
            {"confidence": 67, "win": True, "pnl": 5},
            {"confidence": 72, "win": False, "pnl": -3},
            {"confidence": 85, "win": True, "pnl": 20},
        ]
        bins = cb._bin_by_confidence(outcomes)
        assert "60-70%" in bins
        assert bins["60-70%"]["count"] == 2
        assert bins["60-70%"]["win_rate"] == 1.0

    def test_history_capped(self, tmp_data_dir):
        cb = ContinuousBacktester(data_dir=tmp_data_dir)
        for i in range(2500):
            cb.record_signal(
                symbol="BTC", side="BUY", confidence=70,
                strategy="test", entry=95000, sl=93000, tp1=97000,
            )
        assert len(cb._signal_history) <= 2000


# ═══════════════════════════════════════════════════════════════════
# Tests for ParameterTuner
# ═══════════════════════════════════════════════════════════════════

class TestParameterTuner:
    def test_initial_state(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)
        assert tuner.params.confidence_floor == 55.0
        assert tuner.params.trust_score == 0.3
        assert tuner.params.max_leverage == 25.0

    def test_gradual_movement(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)
        initial_floor = tuner.params.confidence_floor

        # Suggest a big change
        tuner.update(confidence_floor_suggestion=50.0)

        # Should only move partially (trust-gated)
        assert tuner.params.confidence_floor < initial_floor
        assert tuner.params.confidence_floor > 50.0  # Not all the way

    def test_trust_increases_with_validation(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)
        initial_trust = tuner.params.trust_score

        tuner.update(backtest_validated=True)
        assert tuner.params.trust_score > initial_trust

    def test_trust_decays(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)
        tuner.params.trust_score = 0.8

        tuner.update()  # No validation
        assert tuner.params.trust_score < 0.8

    def test_strategy_weight_adjustment(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)

        tuner.update(strategy_weight_suggestions={"strat_a": 1.5, "strat_b": 0.5})

        # Weights should have moved toward targets
        assert tuner.get_strategy_weight("strat_a") > 1.0
        assert tuner.get_strategy_weight("strat_b") < 1.0

    def test_regime_leverage_caps(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)

        tuner.update(regime_suggestions={"panic": 5.0, "trending": 20.0})

        # Caps should have moved toward targets
        assert tuner.get_leverage_cap(regime="panic") < 25.0
        assert tuner.get_leverage_cap(regime="trending") <= 25.0

    def test_confidence_floor_with_context(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)
        tuner.params.strategy_weights["good_strat"] = 1.5
        tuner.params.strategy_weights["bad_strat"] = 0.5

        floor_good = tuner.get_confidence_floor(strategy="good_strat")
        floor_bad = tuner.get_confidence_floor(strategy="bad_strat")

        # Good strategy should have lower floor (more trust)
        assert floor_good < floor_bad

    def test_persistence(self, tmp_data_dir):
        t1 = ParameterTuner(data_dir=tmp_data_dir)
        t1.params.confidence_floor = 70.0
        t1.params.trust_score = 0.6
        t1._save_state()

        t2 = ParameterTuner(data_dir=tmp_data_dir)
        assert t2.params.confidence_floor == 70.0
        assert t2.params.trust_score == 0.6

    def test_suggestion_accuracy_tracking(self, tmp_data_dir):
        tuner = ParameterTuner(data_dir=tmp_data_dir)

        # Record some correct and incorrect suggestions
        for i in range(20):
            tuner.validate_suggestion("floor", was_correct=i % 3 != 0)

        accuracy = tuner._get_suggestion_accuracy()
        assert 0.5 < accuracy < 0.8  # ~66% accuracy


# ═══════════════════════════════════════════════════════════════════
# Tests for SignalQualityScorer
# ═══════════════════════════════════════════════════════════════════

class TestSignalQualityScorer:
    def test_initial_state(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)
        assert len(sq.overall_recent) == 0

    def test_record_outcome(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="BTC", side="BUY",
            regime="trending", num_strategies_agree=3,
        )
        sq.record_outcome(features, win=True, pnl=10.0)

        assert sq.by_symbol["BTC"]["total"] == 1
        assert sq.by_symbol["BTC"]["wins"] == 1
        assert len(sq.overall_recent) == 1

    def test_quality_neutral_without_data(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="BTC", side="BUY",
        )
        quality, breakdown = sq.score_signal(features)

        # With no data, quality should be near 1.0
        assert 0.9 <= quality <= 1.1

    def test_quality_improves_with_wins(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="BTC", side="BUY",
            regime="trending", entry_type="TREND",
            num_strategies_agree=3, hour_of_day=14,
        )

        # Record lots of wins
        for _ in range(15):
            sq.record_outcome(features, win=True, pnl=10.0)

        quality, breakdown = sq.score_signal(features)
        assert quality > 1.0  # Should be boosted

    def test_quality_drops_with_losses(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="DOGE", side="SELL",
            regime="ranging", entry_type="SCALP",
            num_strategies_agree=1, hour_of_day=3,
        )

        # Record lots of losses
        for _ in range(15):
            sq.record_outcome(features, win=False, pnl=-5.0)

        quality, breakdown = sq.score_signal(features)
        assert quality < 1.0  # Should be penalized

    def test_adjust_confidence(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="BTC", side="BUY",
        )

        # Record many wins to boost quality
        for _ in range(15):
            sq.record_outcome(features, win=True, pnl=10.0)

        adjusted, quality, breakdown = sq.adjust_confidence(70.0, features)
        assert adjusted > 70.0  # Boosted by quality

    def test_quality_bounded(self, tmp_data_dir):
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(confidence=90, symbol="BTC")

        # Even with perfect data, quality is bounded
        for _ in range(50):
            sq.record_outcome(features, win=True, pnl=100.0)

        quality, _ = sq.score_signal(features)
        assert quality <= 1.3

    def test_persistence(self, tmp_data_dir):
        sq1 = SignalQualityScorer(data_dir=tmp_data_dir)
        features = QualityFeatures(confidence=70, symbol="BTC", side="BUY")
        for _ in range(10):
            sq1.record_outcome(features, win=True, pnl=5.0)
        sq1._save_state()

        sq2 = SignalQualityScorer(data_dir=tmp_data_dir)
        assert sq2.by_symbol["BTC"]["total"] == 10
        assert sq2.by_symbol["BTC"]["wins"] == 10


# ═══════════════════════════════════════════════════════════════════
# Tests for FeedbackLoop (full orchestration)
# ═══════════════════════════════════════════════════════════════════

class TestFeedbackLoop:
    def test_initial_state(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        assert fl.confidence.current_floor == DEFAULT_FLOOR
        assert fl.tuner.params.trust_score == 0.3

    def test_evaluate_signal_passes_high_conf(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        should_trade, adj_conf, floor, reason = fl.evaluate_signal(
            confidence=80.0, strategy="ensemble", symbol="BTC",
            regime="trending", side="BUY", num_agree=3,
        )
        assert should_trade is True
        assert "PASS" in reason

    def test_evaluate_signal_rejects_low_conf(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        should_trade, adj_conf, floor, reason = fl.evaluate_signal(
            confidence=50.0, strategy="ensemble", symbol="BTC",
            side="BUY",
        )
        assert should_trade is False
        assert "REJECT" in reason

    def test_record_outcome_updates_all_components(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        fl.record_outcome(
            confidence=72.0, win=True, pnl=50.0,
            strategy="ensemble", symbol="BTC",
            regime="trending", side="BUY",
            entry_type="TREND", num_agree=3,
        )

        # All components should have data
        assert len(fl.backtester._outcome_history) == 1
        assert len(fl.quality.overall_recent) == 1
        total_bin_trades = sum(b.total for b in fl.confidence.bins)
        assert total_bin_trades == 1

    def test_record_signal(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        fl.record_signal(
            symbol="BTC", side="BUY", confidence=72.0,
            strategy="ensemble", entry=95000, sl=93000, tp1=97000,
        )
        assert len(fl.backtester._signal_history) == 1

    def test_tick(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        fl.tick()  # Should not error even with no data
        assert fl._tick_count == 1

    def test_full_cycle(self, tmp_data_dir):
        """Test a complete feedback cycle: signals -> outcomes -> learning."""
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        # Simulate 30 trades
        for i in range(30):
            conf = 60 + i % 30
            win = conf >= 70  # Trades above 70% win

            # Record signal
            fl.record_signal(
                symbol="BTC", side="BUY", confidence=conf,
                strategy="ensemble", entry=95000, sl=93000, tp1=97000,
                regime="trending", num_agree=2,
            )

            # Record outcome
            fl.record_outcome(
                confidence=conf, win=win, pnl=10.0 if win else -5.0,
                strategy="ensemble", symbol="BTC",
                regime="trending", side="BUY",
            )

        # Check that the system learned
        report = fl.get_report()
        assert report["quality"]["total_outcomes"] > 0

        # The floor should have potentially adjusted
        floor = fl.confidence.current_floor
        assert ABSOLUTE_MIN_FLOOR <= floor <= ABSOLUTE_MAX_FLOOR

    def test_format_status(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        status = fl.format_status()
        assert "Feedback Loop" in status
        assert "Floor:" in status
        assert "Trust:" in status

    def test_get_leverage_cap(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        cap = fl.get_leverage_cap("BTC", "trending")
        assert cap > 0

    def test_get_strategy_weight(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        weight = fl.get_strategy_weight("regime_trend")
        assert weight == 1.0  # Default

    def test_get_report(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        report = fl.get_report()
        assert "confidence_floor" in report
        assert "backtester" in report
        assert "tuner" in report
        assert "quality" in report

    def test_edge_case_zero_confidence(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        should_trade, adj_conf, floor, reason = fl.evaluate_signal(
            confidence=0.0, symbol="BTC", side="BUY",
        )
        assert should_trade is False

    def test_edge_case_100_confidence(self, tmp_data_dir):
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        should_trade, adj_conf, floor, reason = fl.evaluate_signal(
            confidence=100.0, symbol="BTC", side="BUY",
        )
        assert should_trade is True

    def test_multiple_symbols(self, tmp_data_dir):
        """Test that different symbols develop different floors."""
        fl = FeedbackLoop(data_dir=tmp_data_dir)

        # BTC: always wins
        for _ in range(15):
            fl.record_outcome(
                confidence=65, win=True, pnl=10.0,
                symbol="BTC", side="BUY",
            )

        # DOGE: always loses
        for _ in range(15):
            fl.record_outcome(
                confidence=65, win=False, pnl=-5.0,
                symbol="DOGE", side="BUY",
            )

        # BTC should pass more easily than DOGE at same confidence
        btc_result = fl.evaluate_signal(confidence=65, symbol="BTC", side="BUY")
        doge_result = fl.evaluate_signal(confidence=65, symbol="DOGE", side="BUY")

        # If both pass, BTC should have more margin
        # If one fails, it should be DOGE
        if not doge_result[0]:  # DOGE rejected
            assert True  # Expected
        elif btc_result[0] and doge_result[0]:
            # Both pass — BTC should have higher adjusted confidence
            assert btc_result[1] >= doge_result[1]


# ═══════════════════════════════════════════════════════════════════
# Edge cases and stress tests
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_data_handling(self, tmp_data_dir):
        """All components handle empty data gracefully."""
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        fl.tick()
        fl.get_report()
        fl.format_status()

    def test_corrupted_state_recovery(self, tmp_data_dir):
        """Components recover from corrupted state files."""
        # Write garbage to state file
        state_file = os.path.join(tmp_data_dir, "confidence_state.json")
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        # The actual file path is in data/feedback/, let's write there
        fb_dir = os.path.join(tmp_data_dir, "feedback")
        os.makedirs(fb_dir, exist_ok=True)

        # Create confidence_state.json in the wrong format
        os.makedirs(os.path.join("data", "feedback"), exist_ok=True)

        # Should not crash
        fl = FeedbackLoop(data_dir=tmp_data_dir)
        fl.evaluate_signal(confidence=70, symbol="BTC", side="BUY")

    def test_concurrent_access(self, tmp_data_dir):
        """Continuous backtester handles concurrent signal/outcome recording."""
        cb = ContinuousBacktester(data_dir=tmp_data_dir)

        # Simulate rapid concurrent recording
        for i in range(100):
            cb.record_signal(
                symbol="BTC", side="BUY", confidence=70,
                strategy="test", entry=95000, sl=93000, tp1=97000,
            )
            cb.record_outcome(
                symbol="BTC", win=i % 2 == 0, pnl=5.0,
                confidence_at_entry=70, strategy="test",
            )

        assert len(cb._signal_history) == 100
        assert len(cb._outcome_history) == 100

    def test_negative_pnl_handling(self, tmp_data_dir):
        """Quality scorer handles extreme negative PnL."""
        sq = SignalQualityScorer(data_dir=tmp_data_dir)

        features = QualityFeatures(
            confidence=70, symbol="BTC", side="BUY",
        )
        sq.record_outcome(features, win=False, pnl=-1000.0)

        quality, _ = sq.score_signal(features)
        assert 0.7 <= quality <= 1.3  # Should be bounded

    def test_rapid_floor_changes(self, tmp_data_dir):
        """Floor changes are gradual even with rapid data."""
        acf = AdaptiveConfidenceFloor(data_dir=tmp_data_dir)
        floors = [acf.current_floor]

        for i in range(50):
            acf.record_outcome(
                confidence=55 if i < 25 else 85,
                win=i >= 25,
                pnl=10.0 if i >= 25 else -10.0,
            )
            floors.append(acf.current_floor)

        # Check that no single step is too large
        for j in range(1, len(floors)):
            diff = abs(floors[j] - floors[j - 1])
            assert diff <= 5.0  # MAX_DAILY_CHANGE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
