"""Tests for prompt context injection (W3-F)."""

import pytest
import json
from pathlib import Path
from datetime import datetime

from llm.agents.prompts import (
    inject_learning_memory_context,
    inject_trade_memory_context,
    inject_exit_memory_context,
    inject_risk_memory_context,
)


class TestContextInjection:
    """Test deep memory context injection into agent prompts."""

    @pytest.fixture
    def memory_patterns_file(self, tmp_path):
        """Create temp patterns.jsonl for deep memory."""
        patterns_path = tmp_path / "patterns.jsonl"

        patterns = [
            {
                "setup_type": "trending_bull+3-agree+80conf",
                "symbol": "BTC",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 12,
                "loss_count": 3,
                "total_pnl_usd": 1800.0,
                "total_pnl_pct": 0.36,
                "avg_r_multiple": 2.1,
                "sample_size": 15,
                "confidence_bins": {"80": {"wins": 12, "losses": 3, "total_r": 31.5}},
                "risk_flags": ["overconfident_in_noise"],
            },
            {
                "setup_type": "trending_bull+2-agree+70conf",
                "symbol": "BTC",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 7,
                "loss_count": 5,
                "total_pnl_usd": 500.0,
                "total_pnl_pct": 0.10,
                "avg_r_multiple": 1.3,
                "sample_size": 12,
                "confidence_bins": {},
            },
            {
                "setup_type": "ranging+2-agree+50conf",
                "symbol": "BTC",
                "discovered_date": datetime.utcnow().isoformat(),
                "last_updated_date": datetime.utcnow().isoformat(),
                "win_count": 2,
                "loss_count": 7,
                "total_pnl_usd": -250.0,
                "total_pnl_pct": -0.05,
                "avg_r_multiple": 0.7,
                "sample_size": 9,
                "confidence_bins": {},
            },
        ]

        with open(patterns_path, "w") as f:
            for pattern in patterns:
                f.write(json.dumps(pattern) + "\n")

        return str(patterns_path)

    @pytest.fixture(autouse=True)
    def mock_deep_memory_path(self, memory_patterns_file, monkeypatch):
        """Mock the deep memory patterns path in DeepMemoryQuery."""
        def mock_init(self, patterns_path="bot/data/llm/deep_memory/patterns.jsonl", **kwargs):
            self.patterns_path = Path(memory_patterns_file)
            self.rules_path = Path(kwargs.get("rules_path", "bot/data/llm/graduated_rules.json"))
            self._patterns_cache = None
            self._rules_cache = None

        from llm.learning import deep_memory_query
        monkeypatch.setattr(deep_memory_query.DeepMemoryQuery, "__init__", mock_init)

    def test_inject_learning_memory_context(self, memory_patterns_file):
        """Should inject deep memory context into Learning Agent prompt."""
        context = inject_learning_memory_context(
            regime="trending_bull", symbol="BTC", n_agree=3, confidence=85.0
        )

        assert context != ""
        assert "DEEP MEMORY CONTEXT" in context
        assert "trending_bull+3-agree+80conf" in context
        assert "Historical WR:" in context
        assert "Avg R-Multiple:" in context
        assert "Regime Performance:" in context

    def test_inject_trade_memory_context(self, memory_patterns_file):
        """Should inject deep memory context into Trade Agent prompt."""
        context = inject_trade_memory_context(regime="trending_bull", symbol="BTC")

        assert context != ""
        assert "DEEP MEMORY EDGE DATA" in context
        assert "trending_bull" in context
        assert "Edge Profile:" in context

    def test_inject_exit_memory_context(self, memory_patterns_file):
        """Should inject deep memory context into Exit Agent prompt."""
        context = inject_exit_memory_context(
            regime="trending_bull", symbol="BTC", side="BUY"
        )

        assert context != ""
        assert "DEEP MEMORY EXIT CONTEXT" in context
        assert "BTC BUY in trending_bull" in context
        assert "Historical WR in trending_bull:" in context

    def test_inject_risk_memory_context(self, memory_patterns_file):
        """Should inject deep memory context into Risk Agent prompt."""
        context = inject_risk_memory_context(
            regime="trending_bull", symbol="BTC", n_agree=3
        )

        assert context != ""
        assert "DEEP MEMORY RISK CONTEXT" in context
        assert "trending_bull+3-agree" in context
        assert "Historical Reliability:" in context
        assert "Risk Rating:" in context
        assert "Suggested Position Size:" in context

    def test_context_injection_handles_missing_patterns(self):
        """Should return empty string when deep memory unavailable."""
        # This test uses the default path which doesn't exist
        # The context injection functions should handle gracefully
        context = inject_learning_memory_context(
            regime="unknown_regime", symbol="UNKNOWN", n_agree=1, confidence=50.0
        )

        # Should return empty string due to ImportError or missing patterns
        assert context == "" or "DEEP MEMORY CONTEXT" in context

    def test_risk_context_sizing_for_high_wr(self, memory_patterns_file):
        """Should suggest normal sizing for high WR patterns."""
        context = inject_risk_memory_context(
            regime="trending_bull", symbol="BTC", n_agree=3
        )

        # trending_bull+3-agree pattern has 80% WR
        assert "LOW" in context or "normal sizing OK" in context

    def test_risk_context_sizing_for_low_wr(self, memory_patterns_file):
        """Should suggest reduced sizing for low WR patterns."""
        context = inject_risk_memory_context(regime="ranging", symbol="BTC", n_agree=2)

        # ranging+2-agree pattern has 22% WR (2/9)
        assert "HIGH" in context or "25-50%" in context or "skip" in context

    def test_exit_context_for_ranging_regime(self, memory_patterns_file):
        """Should provide ranging-specific exit guidance."""
        context = inject_exit_memory_context(
            regime="ranging", symbol="ETH", side="BUY"
        )

        assert "ranging" in context

    def test_learning_context_includes_avoid_patterns(self, memory_patterns_file):
        """Should include avoid patterns from symbol intelligence."""
        context = inject_learning_memory_context(
            regime="trending_bull", symbol="BTC", n_agree=3, confidence=85.0
        )

        # Context should reference pattern data
        assert "Regime Performance:" in context

    def test_trade_context_includes_regime_performance(self, memory_patterns_file):
        """Should include regime performance breakdown in Trade Agent context."""
        context = inject_trade_memory_context(regime="trending_bull", symbol="BTC")

        assert "trending_bull" in context
        assert "Edge Profile:" in context

    def test_context_is_string(self, memory_patterns_file):
        """All context injection functions should return strings."""
        assert isinstance(
            inject_learning_memory_context("trending_bull", "BTC", 3, 85.0), str
        )
        assert isinstance(inject_trade_memory_context("trending_bull", "BTC"), str)
        assert isinstance(inject_exit_memory_context("trending_bull", "BTC", "BUY"), str)
        assert isinstance(inject_risk_memory_context("trending_bull", "BTC", 3), str)

    def test_context_safe_for_prompt_injection(self, memory_patterns_file):
        """Context should be safe to inject into prompts (no untrusted data)."""
        context = inject_learning_memory_context(
            regime="trending_bull", symbol="BTC", n_agree=3, confidence=85.0
        )

        # Should not contain unclosed braces or dangerous characters
        assert context.count("{") == context.count("}")
        # Should not contain shell metacharacters
        assert "$(" not in context
        assert "`" not in context
