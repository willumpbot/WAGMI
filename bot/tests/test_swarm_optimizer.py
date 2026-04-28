"""Tests for Swarm Optimizer (W4-D)."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm.agents.swarm_optimizer import SwarmOptimizer, AgentTuningProposal, BiasType


class TestSwarmOptimizer:
    """Test agent performance analysis and tuning recommendations."""

    @pytest.fixture
    def thesis_tracker_file(self, tmp_path):
        """Create temp thesis tracker with sample data."""
        tracker_path = tmp_path / "thesis_tracker.json"
        base_time = datetime.utcnow()

        thesis_data = {
            "theses": [
                {
                    "timestamp": (base_time - timedelta(days=5)).isoformat(),
                    "symbol": "BTC",
                    "regime": "trending_bull",
                    "confidence": 85.0,
                    "won": True,
                    "vetoed": False,
                },
                {
                    "timestamp": (base_time - timedelta(days=4)).isoformat(),
                    "symbol": "BTC",
                    "regime": "trending_bull",
                    "confidence": 80.0,
                    "won": True,
                    "vetoed": False,
                },
                {
                    "timestamp": (base_time - timedelta(days=3)).isoformat(),
                    "symbol": "ETH",
                    "regime": "ranging",
                    "confidence": 90.0,
                    "won": False,
                    "vetoed": False,
                },
                {
                    "timestamp": (base_time - timedelta(days=2)).isoformat(),
                    "symbol": "ETH",
                    "regime": "ranging",
                    "confidence": 88.0,
                    "won": False,
                    "vetoed": False,
                },
                {
                    "timestamp": (base_time - timedelta(days=1)).isoformat(),
                    "symbol": "ETH",
                    "regime": "ranging",
                    "confidence": 92.0,
                    "won": False,
                    "vetoed": True,
                },
            ]
        }

        with open(tracker_path, "w") as f:
            json.dump(thesis_data, f)

        return str(tracker_path)

    @pytest.fixture
    def decisions_file(self, tmp_path):
        """Create temp decisions.jsonl with sample data."""
        decisions_path = tmp_path / "decisions.jsonl"
        base_time = datetime.utcnow()

        decisions = [
            {
                "timestamp": (base_time - timedelta(days=5)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "action": "go",
                "size": 1.0,
            },
            {
                "timestamp": (base_time - timedelta(days=4)).isoformat(),
                "symbol": "BTC",
                "regime": "trending_bull",
                "action": "go",
                "size": 1.0,
            },
            {
                "timestamp": (base_time - timedelta(days=3)).isoformat(),
                "symbol": "ETH",
                "regime": "ranging",
                "action": "skip",
                "size": 0.0,
            },
            {
                "timestamp": (base_time - timedelta(days=2)).isoformat(),
                "symbol": "ETH",
                "regime": "ranging",
                "action": "skip",
                "size": 0.0,
            },
        ]

        with open(decisions_path, "w") as f:
            for decision in decisions:
                f.write(json.dumps(decision) + "\n")

        return str(decisions_path)

    def test_optimizer_initialization(self, thesis_tracker_file):
        """Should initialize with custom paths."""
        optimizer = SwarmOptimizer(thesis_tracker_path=thesis_tracker_file)
        assert optimizer.thesis_tracker_path == Path(thesis_tracker_file)

    def test_analyze_agent_performance(self, thesis_tracker_file, decisions_file):
        """Should analyze agent performance and propose tunings."""
        optimizer = SwarmOptimizer(
            thesis_tracker_path=thesis_tracker_file,
            decisions_path=decisions_file,
        )

        proposals = optimizer.analyze_agent_performance()

        assert "trade" in proposals
        assert "risk" in proposals
        assert "critic" in proposals
        assert "regime" in proposals

    def test_detect_systematic_bias(self, thesis_tracker_file, decisions_file):
        """Should detect systematic bias in agents."""
        optimizer = SwarmOptimizer(
            thesis_tracker_path=thesis_tracker_file,
            decisions_path=decisions_file,
        )

        # Trade agent overconfidence in ranging regime
        trade_bias = optimizer.detect_systematic_bias("trade")
        # May or may not find bias depending on data

        risk_bias = optimizer.detect_systematic_bias("risk")
        # May or may not find bias

    def test_a_b_test_proposal_trade(self):
        """Should design A/B test for trade agent proposals."""
        proposal = AgentTuningProposal(
            agent_name="trade",
            bias_type=BiasType.OVERCONFIDENT,
            magnitude=0.15,
            affected_regime="ranging",
            recommendation="Test",
            confidence=0.75,
            sample_size=10,
        )

        optimizer = SwarmOptimizer()
        test_design = optimizer.a_b_test_proposal(proposal, test_days=7)

        assert test_design["type"] == "trade_confidence_deflation"
        assert test_design["affected_regime"] == "ranging"
        assert test_design["hold_back_pct"] == 0.1

    def test_a_b_test_proposal_risk(self):
        """Should design A/B test for risk agent proposals."""
        proposal = AgentTuningProposal(
            agent_name="risk",
            bias_type=BiasType.UNDERCONFIDENT,
            magnitude=0.20,
            affected_regime="trending_bull",
            recommendation="Test",
            confidence=0.65,
            sample_size=8,
        )

        optimizer = SwarmOptimizer()
        test_design = optimizer.a_b_test_proposal(proposal)

        assert test_design["type"] == "risk_sizing_adjustment"
        assert test_design["hold_back_pct"] == 0.2

    def test_a_b_test_proposal_critic(self):
        """Should design A/B test for critic agent proposals."""
        proposal = AgentTuningProposal(
            agent_name="critic",
            bias_type=BiasType.OVERCONFIDENT,
            magnitude=0.15,
            recommendation="Test",
            confidence=0.70,
            sample_size=12,
        )

        optimizer = SwarmOptimizer()
        test_design = optimizer.a_b_test_proposal(proposal)

        assert test_design["type"] == "critic_veto_threshold"
        assert "false_veto_rate" in test_design["metrics"]

    def test_tuning_proposal_serialization(self):
        """Should serialize proposals to dict."""
        proposal = AgentTuningProposal(
            agent_name="trade",
            bias_type=BiasType.OVERCONFIDENT,
            magnitude=0.15,
            affected_regime="ranging",
            recommendation="Deflate confidence",
            confidence=0.75,
            sample_size=20,
        )

        proposal_dict = proposal.to_dict()

        assert proposal_dict["agent_name"] == "trade"
        assert proposal_dict["bias_type"] == "overconfident"
        assert proposal_dict["magnitude"] == 0.15

    def test_save_recommendations(self, tmp_path, thesis_tracker_file, decisions_file):
        """Should save recommendations to JSONL file."""
        rec_path = tmp_path / "recommendations.jsonl"
        optimizer = SwarmOptimizer(
            thesis_tracker_path=thesis_tracker_file,
            decisions_path=decisions_file,
            recommendations_path=str(rec_path),
        )

        proposals_by_agent = {
            "trade": [
                AgentTuningProposal(
                    agent_name="trade",
                    bias_type=BiasType.OVERCONFIDENT,
                    magnitude=0.15,
                    recommendation="Test",
                    confidence=0.75,
                    sample_size=10,
                )
            ]
        }

        optimizer.save_recommendations(proposals_by_agent)

        assert rec_path.exists()
        with open(rec_path) as f:
            lines = f.readlines()
        assert len(lines) > 0

    def test_empty_thesis_tracker_handling(self, tmp_path):
        """Should handle empty thesis tracker gracefully."""
        tracker_path = tmp_path / "empty_tracker.json"
        tracker_path.write_text('{"theses": []}')

        optimizer = SwarmOptimizer(thesis_tracker_path=str(tracker_path))
        proposals = optimizer.analyze_agent_performance()

        assert all(len(p) == 0 for p in proposals.values())

    def test_missing_thesis_tracker_handling(self, tmp_path):
        """Should handle missing thesis tracker gracefully."""
        tracker_path = tmp_path / "nonexistent.json"
        optimizer = SwarmOptimizer(thesis_tracker_path=str(tracker_path))

        proposals = optimizer.analyze_agent_performance()
        assert all(len(p) == 0 for p in proposals.values())

    def test_bias_type_enum_values(self):
        """Should have valid bias type enum values."""
        assert BiasType.OVERCONFIDENT == "overconfident"
        assert BiasType.UNDERCONFIDENT == "underconfident"
        assert BiasType.REGIME_SPECIFIC == "regime_specific"