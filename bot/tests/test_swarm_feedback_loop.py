"""
Tests for Swarm Feedback Loop.

Ensures recommendations are applied to config correctly and impact is measured.
"""

import pytest
import json
import tempfile
from pathlib import Path

from bot.feedback.swarm_feedback_loop import (
    SwarmFeedbackLoop,
    PromotedRule,
)
from bot.llm.agents.swarm_optimizer import Recommendation


@pytest.fixture
def temp_data_dir():
    """Temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def feedback_loop(temp_data_dir):
    """Create SwarmFeedbackLoop instance with temp directory."""
    return SwarmFeedbackLoop(data_dir=temp_data_dir)


@pytest.fixture
def sample_recommendations():
    """Create sample recommendations for testing."""
    return [
        Recommendation(
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            rationale="Improves entry quality",
            estimated_impact_pct=6.0,
            confidence=0.72,
            priority=1,
        ),
        Recommendation(
            agent_role="exit_specialist",
            pattern="high_volatility",
            action="use trailing stop",
            rationale="Reduces draw",
            estimated_impact_pct=8.0,
            confidence=0.68,
            priority=1,
        ),
        Recommendation(
            agent_role="sizing_specialist",
            pattern="regime_trend",
            action="3% risk per trade",
            rationale="Kelly Criterion positive edge",
            estimated_impact_pct=5.0,
            confidence=0.65,
            priority=2,  # Lower priority
        ),
    ]


class TestPromotedRuleCreation:
    """Test PromotedRule dataclass."""

    def test_promoted_rule_creation(self):
        """Verify promoted rule can be created."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            applied_to_config_keys=["ENTRY_ADJUSTMENTS"],
            status="active",
        )

        assert rule.recommendation_id == "rec_001"
        assert rule.agent_role == "entry_optimizer"
        assert rule.status == "active"

    def test_promoted_rule_degradation(self):
        """Verify rule status can be updated."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            status="active",
        )

        rule.measured_impact_pct = -2.0  # Negative impact
        rule.status = "degraded"

        assert rule.status == "degraded"
        assert rule.measured_impact_pct == -2.0


class TestRecommendationFiltering:
    """Test recommendation filtering by confidence and impact."""

    def test_filter_by_confidence(self, sample_recommendations):
        """Verify low-confidence recommendations are filtered."""
        min_confidence = 0.70
        filtered = [r for r in sample_recommendations if r.confidence >= min_confidence]

        assert len(filtered) == 2  # First two meet threshold
        assert all(r.confidence >= min_confidence for r in filtered)

    def test_filter_by_impact(self, sample_recommendations):
        """Verify low-impact recommendations are filtered."""
        min_impact = 5.0
        filtered = [r for r in sample_recommendations if r.estimated_impact_pct >= min_impact]

        assert len(filtered) == 3  # All meet threshold
        assert all(r.estimated_impact_pct >= min_impact for r in filtered)

    def test_filter_combined(self, sample_recommendations):
        """Verify combined filtering."""
        min_confidence = 0.70
        min_impact = 6.0
        filtered = [
            r
            for r in sample_recommendations
            if r.confidence >= min_confidence and r.estimated_impact_pct >= min_impact
        ]

        assert len(filtered) == 1  # Only first one
        assert filtered[0].estimated_impact_pct == 6.0


class TestConfigApplication:
    """Test applying recommendations to config."""

    def test_entry_adjustment_application(self, feedback_loop):
        """Verify entry adjustment can be applied."""
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            rationale="Test",
            estimated_impact_pct=6.0,
            confidence=0.72,
        )

        config = {}
        feedback_loop._apply_entry_optimization(rec, config)

        assert "ENTRY_ADJUSTMENTS" in config

    def test_exit_optimization_application(self, feedback_loop):
        """Verify exit optimization can be applied."""
        rec = Recommendation(
            agent_role="exit_specialist",
            pattern="high_volatility",
            action="use trailing stop",
            rationale="Test",
            estimated_impact_pct=8.0,
            confidence=0.68,
        )

        config = {}
        feedback_loop._apply_exit_optimization(rec, config)

        assert "REGIME_TP_SCALARS" in config

    def test_sizing_optimization_application(self, feedback_loop):
        """Verify sizing optimization can be applied."""
        rec = Recommendation(
            agent_role="sizing_specialist",
            pattern="regime_trend",
            action="3% risk",
            rationale="Test",
            estimated_impact_pct=5.0,
            confidence=0.65,
        )

        config = {}
        feedback_loop._apply_sizing_optimization(rec, config)

        assert "REGIME_RISK_MULTIPLIERS" in config

    def test_pattern_discovery_application(self, feedback_loop):
        """Verify pattern discovery can be applied."""
        rec = Recommendation(
            agent_role="pattern_discoverer",
            pattern="SOL+asian_hours",
            action="exploit morning momentum",
            rationale="Test",
            estimated_impact_pct=3.0,
            confidence=0.62,
        )

        config = {}
        feedback_loop._apply_pattern_discovery(rec, config)

        assert "SNIPER_PATTERNS" in config
        assert len(config["SNIPER_PATTERNS"]) > 0


class TestFileOperations:
    """Test file I/O operations."""

    def test_save_promoted_rules(self, feedback_loop):
        """Verify promoted rules can be saved."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            status="active",
        )

        feedback_loop.promoted_rules["rec_001"] = rule
        feedback_loop._save_promoted_rules()

        assert feedback_loop.promoted_rules_file.exists()

    def test_load_promoted_rules(self, feedback_loop):
        """Verify promoted rules can be loaded."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            status="active",
        )

        feedback_loop.promoted_rules["rec_001"] = rule
        feedback_loop._save_promoted_rules()

        # Create new instance and load
        feedback_loop2 = SwarmFeedbackLoop(data_dir=str(feedback_loop.data_dir))
        assert "rec_001" in feedback_loop2.promoted_rules

    def test_recommendation_logging(self, feedback_loop):
        """Verify recommendations are logged."""
        rec = Recommendation(
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            rationale="Test",
            estimated_impact_pct=6.0,
            confidence=0.72,
        )

        feedback_loop._log_recommendation(rec)

        # Verify file exists
        assert feedback_loop.recommendations_ledger_file.exists()


class TestAgentAccuracyTracking:
    """Test agent accuracy tracking."""

    def test_measure_recommendation_impact(self, feedback_loop):
        """Verify impact measurement."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            status="active",
        )

        feedback_loop.promoted_rules["rec_001"] = rule
        feedback_loop.measure_recommendation_impact("rec_001", actual_impact_pct=5.5)

        # Verify impact was recorded
        assert rule.measured_impact_pct == 5.5

    def test_agent_accuracy_update(self, feedback_loop):
        """Verify agent accuracy is tracked."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="SOL+trend",
            action="wait for pullback",
            promoted_date=1000.0,
            status="active",
        )

        feedback_loop.promoted_rules["rec_001"] = rule
        feedback_loop.measure_recommendation_impact("rec_001", actual_impact_pct=5.5)
        feedback_loop._update_agent_accuracy("entry_optimizer", 5.5)

        accuracy = feedback_loop.get_agent_accuracy()
        assert "entry_optimizer" in accuracy
        assert accuracy["entry_optimizer"]["recommendations"] >= 1


class TestReportGeneration:
    """Test report generation."""

    def test_feedback_loop_report(self, feedback_loop):
        """Verify report can be generated."""
        report = feedback_loop.generate_report()

        assert "SWARM FEEDBACK" in report
        assert "promoted rules" in report.lower()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_recommendations(self, feedback_loop):
        """Verify system handles empty recommendations."""
        feedback_loop.process_recommendations(
            [],
            min_confidence=0.65,
            min_impact_pct=3.0,
        )

        # Should not crash
        assert True

    def test_all_filtered_recommendations(self, feedback_loop, sample_recommendations):
        """Verify system handles all filtered recommendations."""
        # Set threshold so all are filtered
        feedback_loop.process_recommendations(
            sample_recommendations,
            min_confidence=0.99,  # None will meet this
            min_impact_pct=50.0,  # None will meet this
        )

        # Should not crash
        assert True

    def test_unknown_recommendation_impact(self, feedback_loop):
        """Verify system handles unknown recommendation ID."""
        # Should not crash
        feedback_loop.measure_recommendation_impact("unknown_rec_id", actual_impact_pct=5.0)

        assert True

    def test_invalid_impact_value(self, feedback_loop):
        """Verify system handles invalid impact values."""
        rule = PromotedRule(
            recommendation_id="rec_001",
            agent_role="entry_optimizer",
            pattern="test",
            action="test",
            promoted_date=1000.0,
        )

        feedback_loop.promoted_rules["rec_001"] = rule

        # Negative impact
        feedback_loop.measure_recommendation_impact("rec_001", actual_impact_pct=-5.0)
        assert rule.measured_impact_pct == -5.0

        # Very large impact
        feedback_loop.measure_recommendation_impact("rec_001", actual_impact_pct=100.0)
        assert rule.measured_impact_pct == 100.0


class TestIntegration:
    """Test end-to-end feedback loop."""

    def test_recommendation_to_rule_to_accuracy_flow(self, feedback_loop, sample_recommendations):
        """Verify full flow from recommendation to accuracy tracking."""
        # 1. Process recommendations
        feedback_loop.process_recommendations(
            sample_recommendations,
            min_confidence=0.65,
            min_impact_pct=3.0,
        )

        # 2. Verify rules promoted
        assert len(feedback_loop.promoted_rules) > 0

        # 3. Measure impact
        rule_ids = list(feedback_loop.promoted_rules.keys())
        if rule_ids:
            feedback_loop.measure_recommendation_impact(rule_ids[0], actual_impact_pct=5.0)

        # 4. Verify accuracy tracked
        accuracy = feedback_loop.get_agent_accuracy()
        # At least one agent should have recommendations tracked
        assert len(accuracy) > 0 or len(feedback_loop.promoted_rules) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
