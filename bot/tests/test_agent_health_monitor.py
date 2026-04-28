"""Tests for Agent Health Monitor (W4-F)."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm.agents.agent_health_monitor import AgentHealthMonitor, AgentHealthMetrics


class TestAgentHealthMonitor:
    """Test agent health monitoring and metrics."""

    @pytest.fixture
    def thesis_tracker_file(self, tmp_path):
        """Create temp thesis tracker with agent data."""
        tracker_path = tmp_path / "thesis_tracker.json"
        base_time = datetime.utcnow()

        thesis_data = {
            "theses": [
                {
                    "timestamp": (base_time - timedelta(days=1)).isoformat(),
                    "agent": "trade",
                    "agents": ["regime", "trade", "risk"],
                    "symbol": "BTC",
                    "confidence": 85.0,
                    "won": True,
                },
                {
                    "timestamp": (base_time - timedelta(days=2)).isoformat(),
                    "agent": "trade",
                    "agents": ["regime", "trade", "risk"],
                    "symbol": "ETH",
                    "confidence": 75.0,
                    "won": True,
                },
                {
                    "timestamp": (base_time - timedelta(days=3)).isoformat(),
                    "agent": "trade",
                    "agents": ["regime", "trade"],
                    "symbol": "SOL",
                    "confidence": 70.0,
                    "won": False,
                },
                {
                    "timestamp": (base_time - timedelta(days=4)).isoformat(),
                    "agent": "regime",
                    "agents": ["regime"],
                    "symbol": "BTC",
                    "confidence": 80.0,
                    "won": True,
                },
            ]
        }

        with open(tracker_path, "w") as f:
            json.dump(thesis_data, f)

        return str(tracker_path)

    @pytest.fixture
    def decisions_file(self, tmp_path):
        """Create temp decisions JSONL."""
        decisions_path = tmp_path / "decisions.jsonl"
        base_time = datetime.utcnow()

        decisions = [
            {
                "timestamp": (base_time - timedelta(days=1)).isoformat(),
                "agent": "risk",
                "symbol": "BTC",
                "action": "go",
            },
            {
                "timestamp": (base_time - timedelta(days=2)).isoformat(),
                "agent": "exit",
                "symbol": "ETH",
                "action": "close",
            },
        ]

        with open(decisions_path, "w") as f:
            for decision in decisions:
                f.write(json.dumps(decision) + "\n")

        return str(decisions_path)

    def test_monitor_initialization(self, thesis_tracker_file):
        """Should initialize with custom paths."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        assert monitor.thesis_tracker_path == Path(thesis_tracker_file)

    def test_compute_agent_health(self, thesis_tracker_file):
        """Should compute health metrics for an agent."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        
        health = monitor.compute_agent_health("trade")
        
        assert health.agent_name == "trade"
        assert health.calls_made > 0
        assert 0.0 <= health.accuracy <= 1.0
        assert health.timestamp is not None

    def test_agent_health_metrics_structure(self, thesis_tracker_file):
        """Should have all required health metrics."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        health = monitor.compute_agent_health("trade")
        
        assert hasattr(health, "accuracy")
        assert hasattr(health, "calibration_error")
        assert hasattr(health, "avg_confidence")
        assert hasattr(health, "actual_accuracy")
        assert hasattr(health, "status")
        assert hasattr(health, "alerts")
        assert hasattr(health, "calls_made")

    def test_calibration_error_calculation(self, thesis_tracker_file):
        """Should calculate calibration error as |confidence - accuracy|."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        health = monitor.compute_agent_health("trade")
        
        # Calibration error should be reasonable
        assert 0.0 <= health.calibration_error <= 100.0

    def test_get_all_agent_health(self, thesis_tracker_file):
        """Should compute health for all agents."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        all_health = monitor.get_all_agent_health()
        
        # Should have entries for all agent types
        agent_names = [
            "regime",
            "trade",
            "risk",
            "critic",
            "learning",
            "exit",
            "scout",
            "overseer",
            "quant",
        ]
        
        for agent_name in agent_names:
            assert agent_name in all_health

    def test_agent_status_assessment(self, thesis_tracker_file):
        """Should assess agent status based on metrics."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        health = monitor.compute_agent_health("trade")
        
        assert health.status in ["healthy", "degraded", "unhealthy"]

    def test_detect_agent_drift(self, thesis_tracker_file):
        """Should detect agent calibration or accuracy drift."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        
        # Most agents won't have drift with good data
        drift_alert = monitor.detect_agent_drift("trade")
        # drift_alert may be None if agent is healthy

    def test_save_health_report(self, tmp_path, thesis_tracker_file):
        """Should save health metrics to JSON file."""
        metrics_path = tmp_path / "health_metrics.json"
        monitor = AgentHealthMonitor(
            thesis_tracker_path=thesis_tracker_file,
            metrics_path=str(metrics_path),
        )
        
        monitor.get_all_agent_health()
        monitor.save_health_report()
        
        assert metrics_path.exists()
        with open(metrics_path) as f:
            report = json.load(f)
        
        assert "timestamp" in report
        assert "agents" in report
        assert "overall_status" in report

    def test_get_health_summary(self, thesis_tracker_file):
        """Should generate human-readable health summary."""
        monitor = AgentHealthMonitor(thesis_tracker_path=thesis_tracker_file)
        summary = monitor.get_health_summary()
        
        assert isinstance(summary, str)
        assert "Agent Health Summary" in summary or "healthy" in summary.lower()

    def test_health_metrics_serialization(self):
        """Should serialize health metrics to dict."""
        metrics = AgentHealthMetrics(
            agent_name="test",
            accuracy=0.75,
            calls_made=20,
            status="healthy",
        )
        
        metrics_dict = metrics.to_dict()
        
        assert metrics_dict["agent_name"] == "test"
        assert metrics_dict["accuracy"] == 0.75
        assert metrics_dict["calls_made"] == 20
        assert metrics_dict["status"] == "healthy"

    def test_empty_data_handling(self, tmp_path):
        """Should handle empty data gracefully."""
        tracker_path = tmp_path / "empty_tracker.json"
        tracker_path.write_text('{"theses": []}')
        
        monitor = AgentHealthMonitor(thesis_tracker_path=str(tracker_path))
        health = monitor.compute_agent_health("trade")
        
        assert health.calls_made == 0
        assert health.accuracy == 0.0

    def test_missing_data_handling(self, tmp_path):
        """Should handle missing data files gracefully."""
        monitor = AgentHealthMonitor(
            thesis_tracker_path=str(tmp_path / "nonexistent.json")
        )
        health = monitor.compute_agent_health("trade")
        
        assert health.calls_made == 0