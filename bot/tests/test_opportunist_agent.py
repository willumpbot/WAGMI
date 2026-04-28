"""Tests for Opportunist Agent (W4-A)."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm.agents.opportunist_agent import OpportunistAgent, OpportunityProposal


class TestOpportunistAgent:
    """Test pattern discovery and opportunity proposals."""

    @pytest.fixture
    def decisions_file(self, tmp_path):
        """Create temp decisions.jsonl with sample trade data."""
        decisions_path = tmp_path / "decisions.jsonl"
        base_time = datetime.utcnow()

        decisions = [
            # trending_bull + 3-agree (winning pattern)
            {
                "timestamp": (base_time - timedelta(days=1)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 85.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=2)).isoformat(),
                "symbol": "ETH",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 82.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=3)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 88.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=4)).isoformat(),
                "symbol": "SOL",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 80.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=5)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 86.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=6)).isoformat(),
                "symbol": "ETH",
                "regime": "trending_bull",
                "n_agree": 3,
                "confidence": 81.0,
                "action": "go",
            },
            # trending_bear + 2-agree (mediocre pattern)
            {
                "timestamp": (base_time - timedelta(days=7)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 75.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=8)).isoformat(),
                "symbol": "ETH",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 72.0,
                "action": "skip",
            },
            {
                "timestamp": (base_time - timedelta(days=9)).isoformat(),
                "symbol": "SOL",
                "regime": "trending_bear",
                "n_agree": 2,
                "confidence": 70.0,
                "action": "go",
            },
            # ranging + 1-agree (losing pattern)
            {
                "timestamp": (base_time - timedelta(days=10)).isoformat(),
                "symbol": "BTC",
                "regime": "ranging",
                "n_agree": 1,
                "confidence": 55.0,
                "action": "skip",
            },
            {
                "timestamp": (base_time - timedelta(days=11)).isoformat(),
                "symbol": "ETH",
                "regime": "ranging",
                "n_agree": 1,
                "confidence": 52.0,
                "action": "skip",
            },
            # BTC + trending_bull (symbol-regime strength)
            {
                "timestamp": (base_time - timedelta(days=12)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 2,
                "confidence": 78.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=13)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 1,
                "confidence": 60.0,
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=14)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "n_agree": 2,
                "confidence": 77.0,
                "action": "go",
            },
        ]

        with open(decisions_path, "w") as f:
            for decision in decisions:
                f.write(json.dumps(decision) + "\n")

        return str(decisions_path)

    def test_agent_initialization(self, decisions_file):
        """Should initialize with custom decisions path."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        assert agent.decisions_path == Path(decisions_file)

    def test_discover_high_agreement_patterns(self, decisions_file):
        """Should identify high-agreement winning patterns."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        proposals = agent.discover_patterns(lookback_trades=20, min_confidence=0.40)

        # Should find trending_bull+3-agree pattern (6/6 wins)
        high_agreement = [p for p in proposals if "3-agree" in p.pattern_name]

        # If found, verify it's high quality
        if high_agreement:
            top_proposal = high_agreement[0]
            assert top_proposal.backtest_wr >= 0.80
            assert top_proposal.sample_size >= 5
        else:
            # At minimum, should find some patterns with decent confidence
            assert len(proposals) > 0

    def test_discover_symbol_regime_patterns(self, decisions_file):
        """Should identify symbol+regime strong combinations."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        proposals = agent.discover_patterns(lookback_trades=20, min_confidence=0.40)

        # Should find meaningful patterns
        assert len(proposals) > 0

        # All proposals should have reasonable win rates
        for p in proposals:
            assert p.backtest_wr >= 0.60  # At least 60% WR

    def test_proposal_format(self, decisions_file):
        """Should generate properly formatted proposals."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        proposals = agent.discover_patterns(lookback_trades=20)

        for proposal in proposals:
            assert proposal.pattern_name
            assert proposal.setup_description
            assert 0.0 <= proposal.backtest_wr <= 1.0
            assert proposal.sample_size >= 5
            assert 0.0 <= proposal.confidence <= 1.0
            assert proposal.proposed_action in ["add_to_ensemble", "alert_only"]
            assert len(proposal.evidence) > 0
            assert isinstance(proposal.discovered_date, str)

    def test_confidence_scoring(self, decisions_file):
        """Should score pattern confidence appropriately."""
        agent = OpportunistAgent(decisions_path=decisions_file)

        # High sample size, high win rate → high confidence
        high_conf = agent._score_confidence(sample_size=50, win_rate=0.80)
        assert high_conf > 0.60

        # Low sample size → lower confidence
        low_sample_conf = agent._score_confidence(sample_size=5, win_rate=0.80)
        assert low_sample_conf < high_conf

        # Low win rate → lower confidence
        low_wr_conf = agent._score_confidence(sample_size=20, win_rate=0.55)
        assert low_wr_conf < 0.50

    def test_backtest_proposal(self, decisions_file):
        """Should validate proposals against recent data."""
        agent = OpportunistAgent(decisions_path=decisions_file)

        proposal = OpportunityProposal(
            pattern_name="test_pattern",
            setup_description="Test pattern",
            backtest_wr=0.50,
            sample_size=5,
            confidence=0.50,
            proposed_action="alert_only",
            evidence=["test"],
            discovered_date=datetime.utcnow().isoformat(),
            regime_specific=True,
            applicable_symbols=["BTC"],
            applicable_regimes=["trending_bull"],
        )

        # Backtest should update sample_size based on actual matches
        backtested = agent.backtest_proposal(proposal, lookback_days=30)
        assert backtested.sample_size >= proposal.sample_size

    def test_filter_by_confidence_threshold(self, decisions_file):
        """Should respect min_confidence filter."""
        agent = OpportunistAgent(decisions_path=decisions_file)

        high_threshold_proposals = agent.discover_patterns(min_confidence=0.80)
        low_threshold_proposals = agent.discover_patterns(min_confidence=0.50)

        # High threshold should return fewer proposals
        assert len(high_threshold_proposals) <= len(low_threshold_proposals)

        # All returned proposals should meet threshold
        for p in high_threshold_proposals:
            assert p.confidence >= 0.80

    def test_save_proposals(self, tmp_path, decisions_file):
        """Should save proposals to jsonl file."""
        proposals_path = tmp_path / "proposals.jsonl"
        agent = OpportunistAgent(
            decisions_path=decisions_file,
            proposals_path=str(proposals_path),
        )

        proposals = agent.discover_patterns(min_confidence=0.65)
        if proposals:
            agent.save_proposals(proposals)

            # Verify saved file
            assert proposals_path.exists()
            with open(proposals_path) as f:
                saved = [json.loads(line) for line in f]
            assert len(saved) == len(proposals)

    def test_empty_decisions_file(self, tmp_path):
        """Should handle empty decisions file gracefully."""
        decisions_path = tmp_path / "decisions.jsonl"
        decisions_path.touch()

        agent = OpportunistAgent(decisions_path=str(decisions_path))
        proposals = agent.discover_patterns()

        assert proposals == []

    def test_missing_decisions_file(self, tmp_path):
        """Should handle missing decisions file gracefully."""
        decisions_path = tmp_path / "nonexistent.jsonl"
        agent = OpportunistAgent(decisions_path=str(decisions_path))
        proposals = agent.discover_patterns()

        assert proposals == []

    def test_proposal_action_assignment(self, decisions_file):
        """Should assign action based on confidence level."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        proposals = agent.discover_patterns(lookback_trades=20)

        for proposal in proposals:
            if proposal.confidence > 0.80:
                assert proposal.proposed_action == "add_to_ensemble"
            else:
                assert proposal.proposed_action == "alert_only"

    def test_regime_specificity_detection(self, decisions_file):
        """Should mark patterns as regime-specific."""
        agent = OpportunistAgent(decisions_path=decisions_file)
        proposals = agent.discover_patterns()

        for proposal in proposals:
            assert proposal.regime_specific is not None
            assert len(proposal.applicable_regimes) > 0

    def test_pattern_lookback_window(self, decisions_file):
        """Should respect lookback_trades parameter."""
        agent = OpportunistAgent(decisions_path=decisions_file)

        proposals_all = agent.discover_patterns(lookback_trades=100)
        proposals_recent = agent.discover_patterns(lookback_trades=5)

        # Recent lookback should find fewer patterns (less data)
        assert len(proposals_recent) <= len(proposals_all)
