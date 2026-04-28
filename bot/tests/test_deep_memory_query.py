"""Tests for Deep Memory Query Engine (W3-D)."""

import pytest
import json
from datetime import datetime
from pathlib import Path

from llm.learning.deep_memory_query import DeepMemoryQuery


class TestDeepMemoryQuery:
    """Test deep memory pattern queries."""

    @pytest.fixture
    def patterns_file(self, tmp_path):
        """Create temp patterns.jsonl file."""
        patterns_path = tmp_path / "patterns.jsonl"

        patterns = [
            {
                "setup_type": "trending_bear+3-agree+80conf",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 10,
                "loss_count": 3,
                "total_pnl_usd": 1200.0,
                "total_pnl_pct": 0.24,
                "avg_r_multiple": 1.8,
                "sample_size": 13,
                "confidence_bins": {
                    "80": {"wins": 10, "losses": 3, "total_r": 23.4}
                },
            },
            {
                "setup_type": "trending_bear+2-agree+70conf",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 5,
                "loss_count": 4,
                "total_pnl_usd": 400.0,
                "total_pnl_pct": 0.08,
                "avg_r_multiple": 1.2,
                "sample_size": 9,
                "confidence_bins": {},
            },
            {
                "setup_type": "ranging+2-agree+50conf",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 2,
                "loss_count": 6,
                "total_pnl_usd": -100.0,
                "total_pnl_pct": -0.02,
                "avg_r_multiple": 0.8,
                "sample_size": 8,
                "confidence_bins": {},
            },
        ]

        with open(patterns_path, "w") as f:
            for pattern in patterns:
                f.write(json.dumps(pattern) + "\n")

        return str(patterns_path)

    @pytest.fixture
    def rules_file(self, tmp_path):
        """Create temp graduated_rules.json file."""
        rules_path = tmp_path / "graduated_rules.json"

        rules_data = {
            "rules": [
                {
                    "rule_id": "rule_001",
                    "trigger": "trending_bear+3-agree+80conf",
                    "action": "promote_confidence",
                    "effect": "+10%",
                    "confidence": 0.85,
                    "sample_size": 13,
                    "win_rate": 0.77,
                    "discovered_date": datetime.utcnow().isoformat(),
                    "evidence": "13 trades, 77% WR, 1.8R avg",
                }
            ],
            "last_updated": datetime.utcnow().isoformat(),
        }

        with open(rules_path, "w") as f:
            json.dump(rules_data, f)

        return str(rules_path)

    def test_query_exact_pattern(self, patterns_file):
        """Should find exact setup_type match."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        result = query.query_similar_patterns(
            regime="trending_bear",
            n_agree=3,
            confidence=82,
        )

        assert result["setup_type"] == "trending_bear+3-agree+80conf"
        assert result["win_rate"] == 10 / 13
        assert result["sample_size"] == 13
        assert result["avg_r_multiple"] == 1.8

    def test_query_partial_match(self, patterns_file):
        """Should fallback to regime + n_agree match."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        # Query for trending_bear+3-agree+75conf (bins to 70, no exact match)
        result = query.query_similar_patterns(
            regime="trending_bear",
            n_agree=3,
            confidence=75,
        )

        # Should aggregate similar patterns (different confidence bin)
        # When aggregating, returns "similar_patterns"
        assert result["sample_size"] > 0
        assert result["win_rate"] >= 0.0

    def test_query_regime_only_fallback(self, patterns_file):
        """Should fallback to regime-only match."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        # Query for trending_bear+4-agree (doesn't exist)
        result = query.query_similar_patterns(
            regime="trending_bear",
            n_agree=4,
            confidence=80,
        )

        # Should aggregate all trending_bear patterns
        assert result["sample_size"] > 0
        assert "trending_bear" in result["setup_type"] or result["setup_type"] == "similar_patterns"

    def test_query_no_match(self, patterns_file):
        """Should return empty result for unknown regime."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        result = query.query_similar_patterns(
            regime="unknown_regime",
            n_agree=1,
            confidence=50,
        )

        assert result["sample_size"] == 0
        assert result["win_rate"] == 0.0

    def test_symbol_intelligence_empty(self, patterns_file, rules_file):
        """Should return default intelligence when no symbol data."""
        query = DeepMemoryQuery(patterns_path=patterns_file, rules_path=rules_file)

        result = query.get_symbol_intelligence("BTC")

        assert result["symbol"] == "BTC"
        assert result["win_rate"] == 0.0
        assert result["sample_size"] == 0
        assert result["vol_adjustment_factor"] > 0

    def test_regime_context_injection(self, patterns_file):
        """Should generate regime-conditional context."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        context = query.inject_regime_context("trending_bear")

        assert "trending_bear" in context
        assert "3-agree" in context or "2-agree" in context
        assert "WR" in context or "%" in context

    def test_regime_context_no_data(self, tmp_path):
        """Should handle missing patterns gracefully."""
        patterns_path = tmp_path / "patterns.jsonl"

        query = DeepMemoryQuery(patterns_path=str(patterns_path))

        context = query.inject_regime_context("trending_bull")

        assert "No historical data" in context or "historical" in context.lower()

    def test_win_rate_calculation(self, patterns_file):
        """Should correctly calculate win rates."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        result = query.query_similar_patterns(
            regime="trending_bear",
            n_agree=3,
            confidence=80,
        )

        expected_wr = 10 / 13  # 0.769...
        assert abs(result["win_rate"] - expected_wr) < 0.01

    def test_low_winrate_pattern_detection(self, patterns_file):
        """Should identify low win-rate patterns."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        result = query.query_similar_patterns(
            regime="ranging",
            n_agree=2,
            confidence=50,
        )

        # ranging+2-agree+50conf has 2 wins, 6 losses = 25% WR
        assert result["win_rate"] == 2 / 8

    def test_confidence_bin_scaling(self, patterns_file):
        """Should scale confidence to nearest bin."""
        query = DeepMemoryQuery(patterns_path=patterns_file)

        # Query with confidence 83 (should bin to 80)
        result = query.query_similar_patterns(
            regime="trending_bear",
            n_agree=3,
            confidence=83,
        )

        assert result["setup_type"] == "trending_bear+3-agree+80conf"

    def test_vol_adjustment_factors(self):
        """Should return reasonable vol adjustment factors."""
        query = DeepMemoryQuery()

        assert query._estimate_vol_adjustment("BTC") == 1.0
        assert query._estimate_vol_adjustment("HYPE") > 1.0
        assert query._estimate_vol_adjustment("ETH") > 1.0
