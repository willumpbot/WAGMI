"""Tests for Coordinator Enhancements (W4-C)."""

from datetime import datetime
from unittest.mock import Mock

from llm.agents.coordinator_enhancements import (
    CoordinatorEnhancements,
    patch_coordinator_with_enhancements,
)


class TestCoordinatorEnhancements:
    """Test integration of new agents into coordinator."""

    def test_merge_adversary_into_critic_context(self):
        """Should merge adversary context into critic prompt."""
        enhancements = CoordinatorEnhancements()

        adversary_review = {
            "status": "success",
            "counter_arguments": ["Vol is high", "Support broken"],
            "missing_checks": ["Fed event risk", "Liquidation cascade"],
            "estimated_drawdown": 0.12,
            "confidence_reduction": 0.20,
            "should_veto": False,
            "severity": "high",
        }

        original_prompt = "You are the Critic Agent. Stress-test this thesis."
        merged_prompt = enhancements.merge_adversary_into_critic_context(
            adversary_review,
            original_prompt,
        )

        assert "ADVERSARY AGENT REVIEW" in merged_prompt
        assert "Vol is high" in merged_prompt
        assert "Fed event risk" in merged_prompt
        assert "Estimated Drawdown" in merged_prompt

    def test_merge_adversary_with_failed_review(self):
        """Should handle failed adversary review gracefully."""
        enhancements = CoordinatorEnhancements()

        adversary_review = {"status": "error", "error": "Agent unavailable"}
        original_prompt = "You are the Critic Agent."

        merged_prompt = enhancements.merge_adversary_into_critic_context(
            adversary_review,
            original_prompt,
        )

        # Should return original prompt unchanged
        assert merged_prompt == original_prompt

    def test_get_agent_health_summary(self):
        """Should return agent health summary."""
        enhancements = CoordinatorEnhancements()

        summary = enhancements.get_agent_health_summary()

        assert "timestamp" in summary
        assert "agents_enabled" in summary
        assert summary["agents_enabled"]["regime"] is True
        assert summary["agents_enabled"]["opportunist"] is True
        assert "pipeline_health" in summary

    def test_patch_coordinator_with_enhancements(self):
        """Should successfully patch coordinator instance."""
        mock_coordinator = Mock()

        # Apply patches
        patch_coordinator_with_enhancements(mock_coordinator)

        # Verify methods are bound
        assert hasattr(mock_coordinator, "integrate_opportunist_agent")
        assert hasattr(mock_coordinator, "integrate_adversary_agent")
        assert hasattr(mock_coordinator, "merge_adversary_into_critic_context")
        assert hasattr(mock_coordinator, "get_agent_health_summary")
        assert hasattr(mock_coordinator, "schedule_background_tasks")

    def test_enhancements_instantiation(self):
        """Should instantiate CoordinatorEnhancements successfully."""
        enhancements = CoordinatorEnhancements()
        assert enhancements is not None

    def test_health_summary_has_all_agents(self):
        """Should list all agents in health summary."""
        enhancements = CoordinatorEnhancements()
        summary = enhancements.get_agent_health_summary()

        agents_enabled = summary["agents_enabled"]
        required_agents = [
            "regime",
            "trade",
            "risk",
            "critic",
            "learning",
            "exit",
            "scout",
            "opportunist",
            "adversary",
        ]

        for agent in required_agents:
            assert agent in agents_enabled

    def test_health_summary_timestamps_are_isoformat(self):
        """Should use ISO format timestamps in health summary."""
        enhancements = CoordinatorEnhancements()
        summary = enhancements.get_agent_health_summary()

        # Verify it's valid ISO format by parsing it
        timestamp = summary["timestamp"]
        parsed = datetime.fromisoformat(timestamp)
        assert parsed is not None

    def test_adversary_context_includes_severity(self):
        """Should include severity level in merged context."""
        enhancements = CoordinatorEnhancements()

        adversary_review = {
            "status": "success",
            "counter_arguments": ["Test"],
            "missing_checks": ["Check"],
            "estimated_drawdown": 0.10,
            "confidence_reduction": 0.15,
            "should_veto": True,
            "severity": "critical",
        }

        merged = enhancements.merge_adversary_into_critic_context(
            adversary_review,
            "Original prompt",
        )

        assert "Severity:" in merged
        assert "critical" in merged.lower()

    def test_adversary_context_includes_veto_recommendation(self):
        """Should include veto recommendation in merged context."""
        enhancements = CoordinatorEnhancements()

        adversary_review = {
            "status": "success",
            "counter_arguments": ["Fakeout risk"],
            "missing_checks": [],
            "estimated_drawdown": 0.20,
            "confidence_reduction": 0.25,
            "should_veto": True,
            "severity": "high",
        }

        merged = enhancements.merge_adversary_into_critic_context(
            adversary_review,
            "Test",
        )

        assert "veto is recommended" in merged.lower()
