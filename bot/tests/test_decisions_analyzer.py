"""Tests for Decisions Analyzer (W3-G)."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm.learning.decisions_analyzer import DecisionsAnalyzer


class TestDecisionsAnalyzer:
    """Test decisions.jsonl audit trail analysis."""

    @pytest.fixture
    def decisions_file(self, tmp_path):
        """Create temp decisions.jsonl file with sample data."""
        decisions_path = tmp_path / "decisions.jsonl"
        base_time = datetime.utcnow()

        decisions = [
            # trending_bull + 3-agree + 80-90 conf (BTC)
            {
                "timestamp": (base_time).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 85.0,
                "action": "go",
            },
            {
                "timestamp": (base_time + timedelta(hours=1)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 82.0,
                "action": "go",
            },
            {
                "timestamp": (base_time + timedelta(hours=2)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 88.0,
                "action": "skip",
            },
            # trending_bear + 2-agree + 70-80 conf (ETH)
            {
                "timestamp": (base_time + timedelta(hours=3)).isoformat(),
                "symbol": "ETH",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 75.0,
                "action": "go",
            },
            {
                "timestamp": (base_time + timedelta(hours=4)).isoformat(),
                "symbol": "ETH",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 72.0,
                "action": "go",
            },
            # ranging + 1-agree + 50-60 conf (SOL)
            {
                "timestamp": (base_time + timedelta(hours=5)).isoformat(),
                "symbol": "SOL",
                "regime": "ranging",
                "n_agree": 1,
                "confidence": 55.0,
                "action": "go",
            },
            {
                "timestamp": (base_time + timedelta(hours=6)).isoformat(),
                "symbol": "SOL",
                "regime": "ranging",
                "n_agree": 1,
                "confidence": 52.0,
                "action": "skip",
            },
            # trending_bull + 1-agree + 90-100 conf (BTC) — high confidence, low accuracy
            {
                "timestamp": (base_time + timedelta(hours=7)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 1,
                "confidence": 95.0,
                "action": "skip",
            },
            {
                "timestamp": (base_time + timedelta(hours=8)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 1,
                "confidence": 92.0,
                "action": "skip",
            },
            {
                "timestamp": (base_time + timedelta(hours=9)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 1,
                "confidence": 98.0,
                "action": "skip",
            },
        ]

        with open(decisions_path, "w") as f:
            for decision in decisions:
                f.write(json.dumps(decision) + "\n")

        return str(decisions_path)

    def test_analyzer_initialization(self, decisions_file):
        """Should initialize with custom decisions path."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        assert analyzer.decisions_path == Path(decisions_file)

    def test_summarize_by_symbol(self, decisions_file):
        """Should aggregate accuracy by symbol."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.summarize_by_symbol()

        assert "BTC" in result
        assert "ETH" in result
        assert "SOL" in result

        # BTC: 2 go + 1 skip + 3 skip = 2 wins, 4 losses (total 6 trades)
        assert result["BTC"]["trade_count"] == 6
        assert result["BTC"]["win_rate"] == 2 / 6

        # ETH: 2 go + 0 skip = 2 wins, 0 losses (total 2 trades)
        assert result["ETH"]["trade_count"] == 2
        assert result["ETH"]["win_rate"] == 1.0

        # SOL: 1 go + 1 skip = 1 win, 1 loss (total 2 trades)
        assert result["SOL"]["trade_count"] == 2
        assert result["SOL"]["win_rate"] == 0.5

    def test_summarize_by_regime(self, decisions_file):
        """Should aggregate accuracy by regime."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.summarize_by_regime()

        assert "trending_bull" in result
        assert "trending_bear" in result
        assert "ranging" in result

        # trending_bull: 2 go (idx 0,1) + 4 skip (idx 2,7,8,9) = 2 wins, 4 losses (total 6 trades)
        assert result["trending_bull"]["trade_count"] == 6
        assert result["trending_bull"]["win_rate"] == 2 / 6

        # trending_bear: 2 go = 2 wins (total 2 trades)
        assert result["trending_bear"]["win_rate"] == 1.0

    def test_summarize_by_pattern(self, decisions_file):
        """Should find and analyze specific patterns."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)

        # Query pattern: trending_bull+3-agree+80conf
        result = analyzer.summarize_by_pattern("trending_bull+3-agree+80conf")

        assert result["pattern"] == "trending_bull+3-agree+80conf"
        # 85.0, 82.0, 88.0 all bin to 80
        assert result["sample_size"] == 3
        assert result["wins"] == 2  # actions: go, go, skip
        assert result["losses"] == 1
        assert abs(result["win_rate"] - 2/3) < 0.01

    def test_summarize_by_pattern_no_match(self, decisions_file):
        """Should return error for unknown pattern."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)

        result = analyzer.summarize_by_pattern("unknown_regime+4-agree+50conf")

        assert "error" in result
        assert "No trades found" in result["error"]

    def test_identify_overconfident_bins(self, decisions_file):
        """Should detect confidence bins where predicted > actual."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.identify_overconfident_bins(threshold=0.15)

        # 90-100 bin: 3 skips out of 3 = 0% actual vs ~95% predicted → gap of ~0.95
        assert len(result) > 0
        assert any("90" in bin_key for bin_key in result.keys())

    def test_identify_overconfident_bins_high_threshold(self, decisions_file):
        """Should return empty when threshold is very high."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.identify_overconfident_bins(threshold=0.99)

        # With 99% threshold, almost nothing qualifies
        assert len(result) == 0

    def test_find_regime_transitions(self, decisions_file):
        """Should identify regime changes in history."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        transitions = analyzer.find_regime_transitions(window_trades=10)

        # Should find transitions: trending_bull → trending_bear → ranging → trending_bull
        assert len(transitions) >= 3

        # Check transition structure
        for transition in transitions:
            assert "from_regime" in transition
            assert "to_regime" in transition
            assert "timestamp" in transition
            assert transition["from_regime"] != transition["to_regime"]

    def test_summarize_with_lookback_filter(self, tmp_path):
        """Should respect since_days parameter."""
        decisions_path = tmp_path / "decisions.jsonl"
        base_time = datetime.utcnow()
        old_time = base_time - timedelta(days=10)

        decisions = [
            {
                "timestamp": old_time.isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 80.0,
                "action": "go",
            },
            {
                "timestamp": base_time.isoformat(),
                "symbol": "ETH",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 70.0,
                "action": "go",
            },
        ]

        with open(decisions_path, "w") as f:
            for decision in decisions:
                f.write(json.dumps(decision) + "\n")

        analyzer = DecisionsAnalyzer(decisions_path=str(decisions_path))

        # Include all (default)
        result_all = analyzer.summarize_by_symbol()
        assert len(result_all) == 2

        # Last 5 days only (exclude old_time)
        result_recent = analyzer.summarize_by_symbol(since_days=5)
        assert "BTC" not in result_recent
        assert "ETH" in result_recent

    def test_average_confidence_calculation(self, decisions_file):
        """Should calculate average confidence per symbol."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.summarize_by_symbol()

        # BTC average: (85 + 82 + 88 + 95 + 92 + 98) / 6 = 90.0
        btc_avg_conf = result["BTC"]["avg_confidence"]
        assert 89.0 < btc_avg_conf < 91.0

    def test_regime_breakdown_by_symbol(self, decisions_file):
        """Should track regime breakdown within each symbol."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.summarize_by_symbol()

        btc_result = result["BTC"]
        assert "regime_breakdown" in btc_result

        # BTC has trades in trending_bull only
        assert "trending_bull" in btc_result["regime_breakdown"]

    def test_symbol_breakdown_by_regime(self, decisions_file):
        """Should track symbol breakdown within each regime."""
        analyzer = DecisionsAnalyzer(decisions_path=decisions_file)
        result = analyzer.summarize_by_regime()

        bull_result = result["trending_bull"]
        assert "symbol_breakdown" in bull_result

        # trending_bull has trades in BTC only
        assert "BTC" in bull_result["symbol_breakdown"]

    def test_empty_decisions_file(self, tmp_path):
        """Should handle empty decisions file gracefully."""
        decisions_path = tmp_path / "decisions.jsonl"
        decisions_path.touch()  # Create empty file

        analyzer = DecisionsAnalyzer(decisions_path=str(decisions_path))
        result = analyzer.summarize_by_symbol()

        assert result == {}

    def test_missing_decisions_file(self, tmp_path):
        """Should handle missing decisions file gracefully."""
        decisions_path = tmp_path / "nonexistent.jsonl"

        analyzer = DecisionsAnalyzer(decisions_path=str(decisions_path))
        result = analyzer.summarize_by_symbol()

        assert result == {}

    def test_malformed_json_lines(self, tmp_path):
        """Should skip malformed JSON lines."""
        decisions_path = tmp_path / "decisions.jsonl"

        with open(decisions_path, "w") as f:
            f.write('{"valid": "json"}\n')
            f.write("this is not json\n")
            f.write('{"another": "valid"}\n')

        analyzer = DecisionsAnalyzer(decisions_path=str(decisions_path))
        decisions = analyzer._load_decisions()

        # Should have 2 valid decisions, skip the malformed one
        assert len(decisions) == 2

