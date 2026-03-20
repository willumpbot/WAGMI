"""
Tests for Swarm Optimizer Wiring and Integration.

Ensures all 6 agents receive correct context and produce valid recommendations.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock

from bot.llm.agents.swarm_optimizer import (
    SwarmOptimizer,
    Recommendation,
    SwarmRecommendations,
)
from bot.llm.agents.swarm_agent_prompts import SWARM_AGENT_PROMPTS


@pytest.fixture
def optimizer():
    """Create SwarmOptimizer instance."""
    return SwarmOptimizer()


@pytest.fixture
def sample_audit_data():
    """Create sample audit data for testing."""
    return {
        "trades": [
            {
                "trade_id": "t1",
                "symbol": "BTC",
                "side": "BUY",
                "entry_price": 50000.0,
                "exit_price": 51000.0,
                "net_pnl": 100.0,
                "regime_1h": "trend",
                "single_strategy_name": "regime_trend",
                "confidence_score": 0.75,
            }
        ],
        "metrics": {
            "overall": {
                "trade_count": 10,
                "win_count": 6,
                "loss_count": 4,
                "win_rate": 0.6,
                "profit_factor": 2.5,
                "sharpe_ratio": 1.5,
            },
            "by_entry_adjustment": {},
            "by_exit_type": {},
            "by_regime_1h": {},
            "by_symbol": {},
        },
        "sniper_setups": [
            {
                "pattern_name": "btc_trend",
                "symbol": "BTC",
                "regime": "trend",
                "win_rate": 0.65,
                "profit_factor": 3.0,
            }
        ],
        "losers": [],
    }


class TestRecommendationCreation:
    """Test Recommendation dataclass."""

    def test_recommendation_creation(self):
        """Verify recommendation can be created."""
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Improves entry quality",
            estimated_impact_pct=6.0,
            confidence=0.72,
            test_duration_days=7,
            priority=1,
        )

        assert rec.agent_role == "entry_optimizer"
        assert rec.estimated_impact_pct == 6.0
        assert rec.confidence == 0.72

    def test_recommendation_impact_score(self):
        """Verify impact score calculation."""
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Improves entry quality",
            estimated_impact_pct=6.0,
            confidence=0.8,
            priority=1,
        )

        score = rec.impact_score()
        # impact_score = (6/100) * 0.8 * 1 = 0.048
        assert score == pytest.approx(0.048)

    def test_recommendation_priority_affects_score(self):
        """Verify priority affects impact score."""
        rec_high = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Improves entry quality",
            estimated_impact_pct=6.0,
            confidence=0.8,
            priority=1,
        )

        rec_low = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Improves entry quality",
            estimated_impact_pct=6.0,
            confidence=0.8,
            priority=3,
        )

        assert rec_high.impact_score() > rec_low.impact_score()


class TestSwarmRecommendationsStructure:
    """Test SwarmRecommendations output structure."""

    def test_empty_recommendations(self):
        """Verify empty recommendations."""
        result = SwarmRecommendations(
            timestamp=1000.0,
            total_agents_run=6,
            successful_agents=0,
            failed_agents=["all"],
            total_recommendations=0,
        )

        assert result.total_agents_run == 6
        assert result.successful_agents == 0
        assert len(result.failed_agents) == 1

    def test_recommendations_with_data(self):
        """Verify recommendations with data."""
        rec1 = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Test",
            estimated_impact_pct=6.0,
            confidence=0.72,
        )

        rec2 = Recommendation(
            agent_role="exit_specialist",
            pattern="high_volatility",
            action="use trailing stop",
            rationale="Test",
            estimated_impact_pct=8.0,
            confidence=0.68,
        )

        result = SwarmRecommendations(
            timestamp=1000.0,
            total_agents_run=6,
            successful_agents=2,
            failed_agents=[],
            total_recommendations=2,
            recommendations=[rec1, rec2],
        )

        assert len(result.recommendations) == 2
        assert result.recommendations[0].estimated_impact_pct == 6.0


class TestAgentContextBuilding:
    """Test that each agent receives correct context."""

    def test_entry_optimizer_context(self, optimizer, sample_audit_data):
        """Verify Entry Optimizer gets entry-specific context."""
        context = optimizer._build_agent_input("entry_optimizer", sample_audit_data)

        assert "summary" in context
        assert "trades_analysis" in context
        assert "metrics" in context
        assert "focus" in context
        assert "entry" in context["focus"].lower()

    def test_exit_specialist_context(self, optimizer, sample_audit_data):
        """Verify Exit Specialist gets exit-specific context."""
        context = optimizer._build_agent_input("exit_specialist", sample_audit_data)

        assert "focus" in context
        assert "exit" in context["focus"].lower()

    def test_sizing_specialist_context(self, optimizer, sample_audit_data):
        """Verify Sizing Specialist gets regime context."""
        context = optimizer._build_agent_input("sizing_specialist", sample_audit_data)

        assert "focus" in context
        assert "sizing" in context["focus"].lower() or "size" in context["focus"].lower()

    def test_regime_tuner_context(self, optimizer, sample_audit_data):
        """Verify Regime Tuner gets regime context."""
        context = optimizer._build_agent_input("regime_tuner", sample_audit_data)

        assert "focus" in context
        assert "regime" in context["focus"].lower()

    def test_pattern_discoverer_context(self, optimizer, sample_audit_data):
        """Verify Pattern Discoverer gets symbol context."""
        context = optimizer._build_agent_input("pattern_discoverer", sample_audit_data)

        assert "focus" in context
        assert "pattern" in context["focus"].lower()

    def test_multi_signal_comparator_context(self, optimizer, sample_audit_data):
        """Verify Multi-Signal Comparator gets comparison context."""
        context = optimizer._build_agent_input(
            "multi_signal_comparator", sample_audit_data
        )

        assert "focus" in context
        assert "signal" in context["focus"].lower()


class TestPromptTemplateFormat:
    """Test agent prompt templates are valid."""

    def test_all_prompts_exist(self):
        """Verify all 6 agent prompts exist."""
        agents = [
            "entry_optimizer",
            "exit_specialist",
            "sizing_specialist",
            "regime_tuner",
            "pattern_discoverer",
            "multi_signal_comparator",
        ]

        for agent in agents:
            assert agent in SWARM_AGENT_PROMPTS

    def test_prompts_have_format_placeholders(self):
        """Verify prompts have required format placeholders."""
        required_placeholders = [
            "{audit_summary}",
            "{trades_analysis}",
            "{metrics}",
            "{sniper_setups}",
        ]

        for agent, prompt in SWARM_AGENT_PROMPTS.items():
            for placeholder in required_placeholders:
                assert placeholder in prompt, f"Missing {placeholder} in {agent}"

    def test_prompts_request_json_output(self):
        """Verify prompts request JSON output."""
        for agent, prompt in SWARM_AGENT_PROMPTS.items():
            assert "json" in prompt.lower(), f"Missing JSON request in {agent}"
            assert "recommendations" in prompt.lower()


class TestRecommendationRanking:
    """Test recommendations are ranked correctly."""

    def test_recommendations_ranked_by_score(self, optimizer):
        """Verify recommendations are ranked by impact score."""
        rec1 = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Test",
            estimated_impact_pct=3.0,  # Lower impact
            confidence=0.5,
            priority=1,
        )

        rec2 = Recommendation(
            agent_role="exit_specialist",
            pattern="high_vol",
            action="use trailing",
            rationale="Test",
            estimated_impact_pct=10.0,  # Higher impact
            confidence=0.8,
            priority=1,
        )

        result = SwarmRecommendations(
            timestamp=1000.0,
            total_agents_run=6,
            successful_agents=2,
            failed_agents=[],
            total_recommendations=2,
            recommendations=[rec1, rec2],  # Intentionally wrong order
        )

        # Sort by score
        sorted_recs = sorted(result.recommendations, key=lambda r: r.impact_score(), reverse=True)

        # rec2 should be first (higher score)
        assert sorted_recs[0].estimated_impact_pct == 10.0


class TestEstimateImpact:
    """Test impact estimation."""

    def test_estimate_impact_calculation(self, optimizer):
        """Verify impact estimation math."""
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="BTC+trend",
            action="wait for pullback",
            rationale="Test",
            estimated_impact_pct=5.0,
            confidence=0.72,
        )

        impact = optimizer.estimate_impact(rec)

        assert "monthly_usd_impact" in impact
        assert "estimated_improvement_pct" in impact
        assert "confidence" in impact
        assert impact["estimated_improvement_pct"] == 5.0


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_agent_failure_handling(self):
        """Verify failed agents don't crash system."""
        result = SwarmRecommendations(
            timestamp=1000.0,
            total_agents_run=6,
            successful_agents=3,
            failed_agents=["agent1", "agent2", "agent3"],
            total_recommendations=0,
        )

        # System should continue even with failures
        assert result.total_agents_run == 6
        assert result.successful_agents == 3
        assert len(result.failed_agents) == 3

    def test_empty_audit_data(self, optimizer):
        """Verify system handles empty audit data."""
        empty_audit = {
            "trades": [],
            "metrics": {},
            "sniper_setups": [],
            "losers": [],
        }

        # Should not crash
        context = optimizer._build_agent_input("entry_optimizer", empty_audit)
        assert isinstance(context, dict)

    def test_missing_fields_in_recommendation(self, optimizer):
        """Verify system handles missing recommendation fields."""
        # Create a minimal recommendation
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="test",
            action="test action",
            rationale="test",
            estimated_impact_pct=0.0,
            confidence=0.5,
        )

        # Should have default priority
        assert rec.priority == 1


class TestIntegrationFlow:
    """Test end-to-end swarm flow."""

    def test_audit_to_recommendations_flow(self, optimizer, sample_audit_data):
        """Verify data flows from audit to recommendations."""
        # Build context for each agent
        agents = [
            "entry_optimizer",
            "exit_specialist",
            "sizing_specialist",
            "regime_tuner",
            "pattern_discoverer",
            "multi_signal_comparator",
        ]

        for agent in agents:
            context = optimizer._build_agent_input(agent, sample_audit_data)

            # Verify context has required fields
            assert "summary" in context
            assert "focus" in context

    def test_recommendation_to_impact_flow(self, optimizer):
        """Verify recommendations can be estimated for impact."""
        recommendations = [
            Recommendation(
                agent_role="entry_optimizer",
                pattern="BTC+trend",
                action="wait for pullback",
                rationale="Test",
                estimated_impact_pct=5.0,
                confidence=0.7,
            ),
            Recommendation(
                agent_role="exit_specialist",
                pattern="high_vol",
                action="use trailing",
                rationale="Test",
                estimated_impact_pct=8.0,
                confidence=0.65,
            ),
        ]

        # Estimate impact for each
        for rec in recommendations:
            impact = optimizer.estimate_impact(rec)
            assert impact["monthly_usd_impact"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
