"""Tests for Thesis Tracker Enhancement (W3-E)."""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from llm.thesis_tracker import ThesisTracker, ThesisRecord


class TestThesisTrackerEnhancement:
    """Test regime/symbol/setup-type tracking enhancements."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create a tracker with temp data directory."""
        tracker = ThesisTracker(data_dir=str(tmp_path))
        return tracker

    def test_regime_dependent_accuracy(self, tracker):
        """Should track accuracy per regime."""
        now = datetime.now(timezone.utc)

        # Record 5 theses in trending_bull (4 correct, 1 incorrect)
        for i in range(4):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="Bullish trend continuing",
                confidence=75.0,
                regime="trending_bull",
                entry_price=40000.0,
                setup_type="trending_bull+3-agree",
            )
            tracker.close_thesis(
                thesis_id=thesis_id,
                exit_price=41000.0,
                pnl_pct=0.025,
            )

        # One loss
        thesis_id = tracker.record_thesis(
            symbol="BTC",
            side="BUY",
            thesis="Bullish trend continuing",
            confidence=75.0,
            regime="trending_bull",
            entry_price=40000.0,
            setup_type="trending_bull+3-agree",
        )
        tracker.close_thesis(
            thesis_id=thesis_id,
            exit_price=39500.0,
            pnl_pct=-0.0125,
        )

        # Record 3 theses in ranging (1 correct, 2 incorrect)
        for i in range(2):
            thesis_id = tracker.record_thesis(
                symbol="ETH",
                side="BUY",
                thesis="Range support bounce",
                confidence=50.0,
                regime="ranging",
                entry_price=2000.0,
                setup_type="ranging+2-agree",
            )
            tracker.close_thesis(
                thesis_id=thesis_id,
                exit_price=1950.0,
                pnl_pct=-0.025,
            )

        thesis_id = tracker.record_thesis(
            symbol="ETH",
            side="BUY",
            thesis="Range support bounce",
            confidence=50.0,
            regime="ranging",
            entry_price=2000.0,
            setup_type="ranging+2-agree",
        )
        tracker.close_thesis(
            thesis_id=thesis_id,
            exit_price=2100.0,
            pnl_pct=0.05,
        )

        stats = tracker.get_accuracy_stats(lookback_days=30)

        assert stats["sufficient_data"]
        assert "trending_bull" in stats["by_regime"]
        assert "ranging" in stats["by_regime"]

        # Check trending_bull: 4/5 correct = 80%
        assert abs(stats["by_regime"]["trending_bull"]["accuracy"] - 0.8) < 0.01

        # Check ranging: 1/3 correct = 33%
        assert abs(stats["by_regime"]["ranging"]["accuracy"] - 0.333) < 0.01

    def test_symbol_specific_tracking(self, tracker):
        """Should track accuracy per symbol."""
        # BTC: 3 correct
        for i in range(3):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="BTC bullish",
                confidence=70.0,
                regime="trending_bull",
                entry_price=40000.0,
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=41000.0, pnl_pct=0.025)

        # ETH: 1 correct, 2 incorrect
        thesis_id = tracker.record_thesis(
            symbol="ETH",
            side="BUY",
            thesis="ETH bullish",
            confidence=60.0,
            regime="trending_bull",
            entry_price=2000.0,
        )
        tracker.close_thesis(thesis_id=thesis_id, exit_price=2100.0, pnl_pct=0.05)

        for i in range(2):
            thesis_id = tracker.record_thesis(
                symbol="ETH",
                side="BUY",
                thesis="ETH bullish",
                confidence=60.0,
                regime="trending_bull",
                entry_price=2000.0,
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=1900.0, pnl_pct=-0.05)

        stats = tracker.get_accuracy_stats(lookback_days=30)

        assert stats["by_symbol"]["BTC"]["accuracy"] == 1.0
        assert abs(stats["by_symbol"]["ETH"]["accuracy"] - 0.333) < 0.01

    def test_overconfidence_detection(self, tracker):
        """Should detect confidence bins where predicted > actual."""
        # Create high-confidence theses that lose
        for i in range(7):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="High confidence call",
                confidence=85.0,
                regime="trending_bull",
                entry_price=40000.0,
            )
            # Lose half of them
            if i < 3:
                tracker.close_thesis(
                    thesis_id=thesis_id,
                    exit_price=41000.0,
                    pnl_pct=0.025,
                )
            else:
                tracker.close_thesis(
                    thesis_id=thesis_id,
                    exit_price=39500.0,
                    pnl_pct=-0.0125,
                )

        overconfident = tracker.detect_overconfident_bins(lookback_days=30, threshold=0.15)

        # 80-90% confidence bin should be detected (actual ~42% vs predicted ~85%)
        assert len(overconfident) > 0
        assert any(
            "80" in bin_name and data["gap"] > 0.15
            for bin_name, data in overconfident.items()
        )

    def test_regime_comparison(self, tracker):
        """Should compare performance across regimes."""
        # Strong trending_bull performance
        for i in range(5):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="Trend follow",
                confidence=75.0,
                regime="trending_bull",
                entry_price=40000.0,
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=41000.0, pnl_pct=0.025)

        # Weak ranging performance
        for i in range(4):
            thesis_id = tracker.record_thesis(
                symbol="ETH",
                side="BUY",
                thesis="Range trade",
                confidence=50.0,
                regime="ranging",
                entry_price=2000.0,
            )
            if i < 1:
                tracker.close_thesis(thesis_id=thesis_id, exit_price=2100.0, pnl_pct=0.05)
            else:
                tracker.close_thesis(thesis_id=thesis_id, exit_price=1900.0, pnl_pct=-0.05)

        comparison = tracker.get_regime_comparison(lookback_days=30)

        assert "error" not in comparison
        assert comparison["best_regime"] == "trending_bull"
        assert comparison["worst_regime"] == "ranging"
        assert len(comparison["regime_comparison"]) >= 2

    def test_symbol_comparison(self, tracker):
        """Should compare performance across symbols."""
        # BTC: perfect record
        for i in range(4):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="BTC call",
                confidence=70.0,
                regime="trending_bull",
                entry_price=40000.0,
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=41000.0, pnl_pct=0.025)

        # SOL: struggling
        for i in range(3):
            thesis_id = tracker.record_thesis(
                symbol="SOL",
                side="BUY",
                thesis="SOL call",
                confidence=60.0,
                regime="trending_bull",
                entry_price=100.0,
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=95.0, pnl_pct=-0.05)

        comparison = tracker.get_symbol_comparison(lookback_days=30)

        assert "error" not in comparison
        assert comparison["best_symbol"] == "BTC"
        assert comparison["worst_symbol"] == "SOL"
        assert len(comparison["symbol_comparison"]) >= 2

    def test_setup_type_tracking(self, tracker):
        """Should track accuracy per setup type."""
        # trending_bull+3-agree: 4 correct
        for i in range(4):
            thesis_id = tracker.record_thesis(
                symbol="BTC",
                side="BUY",
                thesis="Strong consensus",
                confidence=80.0,
                regime="trending_bull",
                entry_price=40000.0,
                setup_type="trending_bull+3-agree",
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=41000.0, pnl_pct=0.025)

        # ranging+2-agree: 1 correct, 2 incorrect
        thesis_id = tracker.record_thesis(
            symbol="ETH",
            side="BUY",
            thesis="Weak consensus",
            confidence=50.0,
            regime="ranging",
            entry_price=2000.0,
            setup_type="ranging+2-agree",
        )
        tracker.close_thesis(thesis_id=thesis_id, exit_price=2100.0, pnl_pct=0.05)

        for i in range(2):
            thesis_id = tracker.record_thesis(
                symbol="ETH",
                side="BUY",
                thesis="Weak consensus",
                confidence=50.0,
                regime="ranging",
                entry_price=2000.0,
                setup_type="ranging+2-agree",
            )
            tracker.close_thesis(thesis_id=thesis_id, exit_price=1900.0, pnl_pct=-0.05)

        stats = tracker.get_accuracy_stats(lookback_days=30)

        assert "trending_bull+3-agree" in stats["by_setup_type"]
        assert "ranging+2-agree" in stats["by_setup_type"]

        # Strong setup should show 100%
        assert stats["by_setup_type"]["trending_bull+3-agree"]["accuracy"] == 1.0

        # Weak setup should show ~33%
        assert abs(stats["by_setup_type"]["ranging+2-agree"]["accuracy"] - 0.333) < 0.01

    def test_insufficient_data_handling(self, tracker):
        """Should gracefully handle insufficient data."""
        # Only 1 thesis
        thesis_id = tracker.record_thesis(
            symbol="BTC",
            side="BUY",
            thesis="Single test",
            confidence=70.0,
            regime="trending_bull",
            entry_price=40000.0,
        )
        tracker.close_thesis(thesis_id=thesis_id, exit_price=41000.0, pnl_pct=0.025)

        stats = tracker.get_accuracy_stats(lookback_days=30, min_samples=5)

        assert stats["sufficient_data"] is False
