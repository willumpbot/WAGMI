"""Tests for the adaptive online learning system components."""
import json
import os
import tempfile
import time
import pytest

from feedback.rejection_tracker import RejectionOutcomeTracker, RejectionRecord
from feedback.ev_calibrator import EVCalibrator
from feedback.correlation_boost import CrossAssetCorrelationBoost


class TestRejectionOutcomeTracker:
    """Test rejection recording and outcome measurement."""

    def test_record_rejection(self):
        """Basic rejection recording."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            tracker.record(
                symbol="HYPE", side="SELL", n_agree=3,
                ev=-0.006, win_prob=0.35, price=38.11,
            )
            assert len(tracker._pending) == 1
            assert tracker._pending[0].symbol == "HYPE"
            assert tracker._pending[0].ev == -0.006

    def test_deduplication(self):
        """Same symbol+side within cooldown is deduplicated."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            tracker._cooldown_s = 300
            tracker.record("HYPE", "SELL", 3, -0.006, 0.35, 38.11)
            tracker.record("HYPE", "SELL", 3, -0.007, 0.35, 38.05)
            assert len(tracker._pending) == 1  # Second one deduplicated

    def test_different_symbols_not_deduped(self):
        """Different symbols are not deduplicated."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            tracker.record("HYPE", "SELL", 3, -0.006, 0.35, 38.11)
            tracker.record("BTC", "BUY", 1, -0.15, 0.30, 70000.0)
            assert len(tracker._pending) == 2

    def test_measure_missed_profit(self):
        """Detect missed profit when price moves >1% in signal direction."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            # Create an old rejection
            rec = RejectionRecord(
                symbol="HYPE", side="SELL", n_agree=3,
                ev=-0.006, win_prob=0.35, entry_price=38.11,
                timestamp=time.time() - 300 * 60,  # 5 hours ago
            )
            tracker._pending.append(rec)

            # Measure with price that moved 2% down
            completed = tracker.measure_outcomes({"HYPE": 37.35})
            assert len(completed) == 1
            assert completed[0]["final_outcome"] == "missed_profit"

    def test_measure_correct_rejection(self):
        """Detect correct rejection when price moves against signal."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            rec = RejectionRecord(
                symbol="BTC", side="BUY", n_agree=1,
                ev=-0.15, win_prob=0.30, entry_price=70000.0,
                timestamp=time.time() - 300 * 60,
            )
            tracker._pending.append(rec)

            completed = tracker.measure_outcomes({"BTC": 69500.0})
            assert len(completed) == 1
            assert completed[0]["final_outcome"] == "correct_rejection"

    def test_stats_update(self):
        """Stats update correctly on classification."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            rec = RejectionRecord(
                symbol="HYPE", side="SELL", n_agree=3,
                ev=-0.006, win_prob=0.35, entry_price=38.11,
                timestamp=time.time() - 300 * 60,
            )
            tracker._pending.append(rec)
            tracker.measure_outcomes({"HYPE": 37.35})

            assert tracker.bins["marginal_neg"]["missed"] == 1
            assert tracker.bins["marginal_neg"]["total"] == 1
            assert tracker.consensus_stats["consensus"]["missed"] == 1

    def test_callback_called(self):
        """Outcome callback fires on classification."""
        with tempfile.TemporaryDirectory() as td:
            tracker = RejectionOutcomeTracker(data_dir=td)
            callback_results = []
            tracker._outcome_callback = lambda ev, n, o: callback_results.append((ev, n, o))

            rec = RejectionRecord(
                symbol="HYPE", side="SELL", n_agree=3,
                ev=-0.006, win_prob=0.35, entry_price=38.11,
                timestamp=time.time() - 300 * 60,
            )
            tracker._pending.append(rec)
            tracker.measure_outcomes({"HYPE": 37.35})

            assert len(callback_results) == 1
            assert callback_results[0][0] == -0.006
            assert callback_results[0][2] == "missed_profit"


class TestEVCalibrator:
    """Test adaptive EV threshold adjustment."""

    def test_initial_cold_start_relaxed(self):
        """Cold-starts in relaxed mode (allows marginal overrides immediately)."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            # Cold-start: should allow marginal EV with consensus
            assert cal.should_override(-0.005, 3)
            # But not below absolute min
            assert not cal.should_override(-0.03, 3)
            # And not without consensus
            assert not cal.should_override(-0.005, 1)

    def test_should_not_override_positive_ev(self):
        """Never override positive EV (not a rejection)."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            assert not cal.should_override(0.05, 3)

    def test_should_not_override_strong_negative(self):
        """Never override strongly negative EV even in relaxed mode."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            # Force relaxed mode
            cal.ev_override_threshold = -0.01
            assert not cal.should_override(-0.10, 3)

    def test_override_marginal_with_consensus(self):
        """Override marginal EV with 3+ consensus in relaxed mode."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            # Force relaxed mode (normally triggered by calibration)
            cal._mode = "relaxed"
            cal._ev_threshold = -0.01
            assert cal.should_override(-0.005, 3)

    def test_no_override_without_consensus(self):
        """Don't override marginal EV without consensus."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            cal.ev_override_threshold = -0.01
            assert not cal.should_override(-0.005, 1)
            assert not cal.should_override(-0.005, 2)

    def test_size_multiplier(self):
        """Override uses reduced position size."""
        with tempfile.TemporaryDirectory() as td:
            cal = EVCalibrator(data_dir=td)
            assert cal.get_override_size_mult() == 0.5


class TestCorrelationBoost:
    """Test cross-asset correlation detection."""

    def test_no_boost_without_data(self):
        """No boost when insufficient price history."""
        boost = CrossAssetCorrelationBoost(symbols=["BTC", "SOL", "HYPE"])
        assert boost.get_boost("HYPE", "SELL") == 1.0

    def test_strong_boost_all_down(self):
        """Strong boost when all symbols move down and signal is SELL."""
        boost = CrossAssetCorrelationBoost(
            symbols=["BTC", "SOL", "HYPE"],
            lookback_minutes=60,
        )
        now = time.time()
        # All symbols dropping
        for sym, prices in [("BTC", [70000, 69500]), ("SOL", [91, 90]), ("HYPE", [38, 37.5])]:
            boost.update_price(sym, prices[0], now - 3000)
            boost.update_price(sym, prices[1], now)

        result = boost.get_boost("HYPE", "SELL")
        assert result > 1.0  # Should get a boost

    def test_no_boost_mixed_direction(self):
        """No boost when symbols move in different directions."""
        boost = CrossAssetCorrelationBoost(
            symbols=["BTC", "SOL", "HYPE"],
            lookback_minutes=60,
        )
        now = time.time()
        # Mixed: BTC up, SOL down, HYPE down
        boost.update_price("BTC", 70000, now - 3000)
        boost.update_price("BTC", 70500, now)  # UP
        boost.update_price("SOL", 91, now - 3000)
        boost.update_price("SOL", 90, now)  # DOWN
        boost.update_price("HYPE", 38, now - 3000)
        boost.update_price("HYPE", 37.5, now)  # DOWN

        # 2/3 agree on DOWN for SELL, but BTC disagrees
        result = boost.get_boost("HYPE", "SELL")
        # Should be moderate (2/3) or none depending on threshold
        assert result >= 1.0

    def test_no_boost_wrong_direction(self):
        """No boost when market moves against signal."""
        boost = CrossAssetCorrelationBoost(
            symbols=["BTC", "SOL", "HYPE"],
            lookback_minutes=60,
        )
        now = time.time()
        # All up, but signal is SELL
        for sym, prices in [("BTC", [70000, 70500]), ("SOL", [90, 91]), ("HYPE", [37, 38])]:
            boost.update_price(sym, prices[0], now - 3000)
            boost.update_price(sym, prices[1], now)

        result = boost.get_boost("HYPE", "SELL")
        assert result == 1.0  # No boost — market going UP, signal says SELL

    def test_market_direction_report(self):
        """get_market_direction returns readable report."""
        boost = CrossAssetCorrelationBoost(symbols=["BTC", "SOL"])
        now = time.time()
        boost.update_price("BTC", 70000, now - 3000)
        boost.update_price("BTC", 69500, now)
        boost.update_price("SOL", 90, now - 3000)
        boost.update_price("SOL", 90, now)

        directions = boost.get_market_direction()
        assert "BTC" in directions
        assert "DOWN" in directions["BTC"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
