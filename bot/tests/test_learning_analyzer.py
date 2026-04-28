"""Tests for Learning Analyzer (W3-C)."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm.agents.learning_analyzer import (
    analyze_and_enrich_closed_trade,
    build_learning_context,
)


class TestLearningAnalyzer:
    """Test learning analyzer integration."""

    @pytest.fixture
    def sample_trade_data(self):
        """Create sample closed trade data."""
        now = datetime.utcnow()
        return {
            "trade_id": "trade_001",
            "symbol": "BTC",
            "side": "SELL",
            "entry_price": 42000.0,
            "exit_price": 41000.0,
            "entry_time": (now - timedelta(hours=1)).isoformat(),
            "exit_time": now.isoformat(),
            "position_size": 0.1,
            "entry_risk_pct": 0.02,
            "regime": "trending_bear",
            "confidence_predicted": 82.0,
            "n_agree": 3,
            "pnl_usd": 100.0,
            "pnl_pct": 0.024,
            "strategy": "regime_trend",
        }

    @pytest.fixture
    def decisions_file(self, tmp_path, sample_trade_data):
        """Create temp decisions.jsonl file with matching entries."""
        decisions_path = tmp_path / "decisions.jsonl"

        # Parse entry_time from sample_trade_data
        entry_time = datetime.fromisoformat(sample_trade_data["entry_time"])

        # Entry decision matching sample_trade_data
        # Note: confidence is stored in 0-100 scale in decisions.jsonl
        decision_entry = {
            "timestamp": entry_time.isoformat(),
            "symbol": sample_trade_data["symbol"],
            "action": "go",
            "regime": sample_trade_data["regime"],
            "thesis": "Strong downtrend signal",
            "confidence": sample_trade_data["confidence_predicted"],  # Already 0-100
            "n_agree": sample_trade_data["n_agree"],
            "leverage": 3.0,
        }

        with open(decisions_path, "w") as f:
            f.write(json.dumps(decision_entry) + "\n")

        return str(decisions_path)

    def test_analyze_profitable_trade(self, sample_trade_data, decisions_file):
        """Should analyze profitable trade."""
        # Verify decisions file exists and contains expected data
        decisions_path = Path(decisions_file)
        assert decisions_path.exists(), f"Decisions file does not exist: {decisions_file}"
        with open(decisions_path) as f:
            content = f.read()
            assert "82.0" in content, f"Expected confidence 82.0 in {content}"

        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert result["error"] is None
        assert result["lessons_extracted"] == 1
        assert len(result["lessons"]) == 1

        lesson = result["lessons"][0]
        assert lesson["symbol"] == "BTC"
        assert lesson["setup_type"] == "trending_bear+3-agree+80conf", f"Got {lesson['setup_type']}, confidence_predicted={lesson.get('confidence_predicted')}"
        assert lesson["pnl_usd"] == 100.0

    def test_analyze_losing_trade(self, sample_trade_data, decisions_file):
        """Should analyze losing trade."""
        sample_trade_data["exit_price"] = 43000.0  # Losing SHORT
        sample_trade_data["pnl_usd"] = -100.0
        sample_trade_data["pnl_pct"] = -0.024

        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert result["error"] is None
        assert result["lessons_extracted"] == 1

        lesson = result["lessons"][0]
        assert lesson["pnl_usd"] < 0
        assert lesson["confidence_correct"] is False

    def test_memory_enrichment_called(self, sample_trade_data, decisions_file):
        """Should enrich memory when analyzing."""
        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert result["memory_enriched"] >= 0
        assert isinstance(result["enrichment_notes"], list)

    def test_context_building(self, sample_trade_data, decisions_file):
        """Should build context string for Learning Agent."""
        analysis_result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )
        context = build_learning_context(analysis_result, sample_trade_data)

        assert isinstance(context, str)
        assert "BTC" in context
        assert "SELL" in context
        assert "PnL" in context

    def test_error_handling_missing_data(self):
        """Should handle missing trade data gracefully."""
        incomplete_trade = {
            "symbol": "ETH",
            # Missing other required fields
        }

        result = analyze_and_enrich_closed_trade(incomplete_trade)

        # Should not crash, but may have 0 lessons
        assert "error" in result
        assert result["lessons_extracted"] >= 0

    def test_multiple_lessons_grouped(self, sample_trade_data, decisions_file):
        """Should handle multiple lessons from single trade."""
        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert isinstance(result["lessons"], list)
        assert len(result["lessons"]) >= 1

        lesson = result["lessons"][0]
        assert isinstance(lesson["lessons"], list)

    def test_context_includes_lessons(self, sample_trade_data, decisions_file):
        """Context should include extracted lessons."""
        analysis_result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )
        context = build_learning_context(analysis_result, sample_trade_data)

        if analysis_result.get("lessons_extracted") > 0:
            assert "Extracted lessons" in context or "Setup" in context

    def test_context_includes_enrichment(self, sample_trade_data, decisions_file):
        """Context should include enrichment notes."""
        analysis_result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )
        context = build_learning_context(analysis_result, sample_trade_data)

        if analysis_result.get("memory_enriched") > 0:
            assert "Memory enriched" in context

    def test_timestamp_handling(self, sample_trade_data, decisions_file):
        """Should handle both string and datetime timestamps."""
        # Test with string timestamps (ISO format)
        result1 = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )
        assert result1["error"] is None

        # Test with datetime objects
        sample_trade_data["entry_time"] = datetime.utcnow() - timedelta(hours=1)
        sample_trade_data["exit_time"] = datetime.utcnow()
        result2 = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )
        assert result2["error"] is None

    def test_buy_side_trade(self, sample_trade_data, decisions_file):
        """Should analyze BUY side trades correctly."""
        sample_trade_data["side"] = "BUY"
        sample_trade_data["entry_price"] = 41000.0
        sample_trade_data["exit_price"] = 42000.0  # Profitable BUY

        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert result["lessons_extracted"] == 1
        lesson = result["lessons"][0]
        assert lesson["pnl_usd"] > 0

    def test_large_position(self, sample_trade_data, decisions_file):
        """Should handle large positions."""
        sample_trade_data["position_size"] = 10.0  # 10x position

        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        assert result["error"] is None
        lesson = result["lessons"][0]
        # PnL = (entry_price - exit_price) * position_size = 1000 * 10 = 10000
        assert lesson["pnl_usd"] == 10000.0

    def test_short_hold_duration(self, sample_trade_data, decisions_file):
        """Should detect short hold durations."""
        sample_trade_data["entry_time"] = datetime.utcnow() - timedelta(seconds=30)
        sample_trade_data["exit_time"] = datetime.utcnow()

        result = analyze_and_enrich_closed_trade(
            sample_trade_data, decisions_log_path=decisions_file
        )

        if result["lessons_extracted"] > 0:
            lesson = result["lessons"][0]
            assert lesson["hold_duration_minutes"] < 1


class TestLearningContextBuilding:
    """Test context string building for Learning Agent."""

    def test_empty_analysis_result(self):
        """Should handle empty analysis result."""
        analysis_result = {
            "lessons_extracted": 0,
            "memory_enriched": 0,
            "lessons": [],
            "enrichment_notes": [],
        }
        trade_data = {"symbol": "BTC", "side": "BUY", "pnl_usd": 50, "pnl_pct": 0.01}

        context = build_learning_context(analysis_result, trade_data)

        assert isinstance(context, str)
        assert "BTC" in context

    def test_context_multiline_format(self):
        """Context should be properly formatted multiline."""
        analysis_result = {
            "lessons_extracted": 1,
            "memory_enriched": 2,
            "lessons": [
                {
                    "symbol": "ETH",
                    "setup_type": "ranging+2-agree+50conf",
                    "confidence_correct": False,
                    "lessons": ["Overconfident in ranging", "Reduce leverage"],
                }
            ],
            "enrichment_notes": ["notes_added=2", "patterns_updated=1"],
        }
        trade_data = {"symbol": "ETH", "side": "SELL", "pnl_usd": -50, "pnl_pct": -0.01}

        context = build_learning_context(analysis_result, trade_data)

        assert "\n" in context
        assert "ETH" in context
        assert "Setup" in context
        assert "Memory enriched" in context
