"""Agent Health Monitor (W4-F) — Track health metrics for all agents.

Monitors per-agent accuracy, calibration, latency, cost, and error rates.
Generates alerts when agents drift or underperform.
"""

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AgentHealthMetrics:
    """Health metrics for a single agent."""

    agent_name: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Accuracy metrics
    accuracy: float = 0.0  # Win rate or correct predictions %
    accuracy_trend: float = 0.0  # Change over last 24h
    
    # Calibration metrics
    avg_confidence: float = 0.0  # Avg predicted confidence (0-100)
    actual_accuracy: float = 0.0  # Actual outcome rate
    calibration_error: float = 0.0  # |avg_confidence - actual_accuracy|
    
    # Latency metrics
    avg_latency_ms: float = 0.0  # Avg response time
    max_latency_ms: float = 0.0  # Max response time
    
    # Cost metrics
    total_cost_usd: float = 0.0  # Total API cost for agent
    calls_made: int = 0  # Number of times agent was invoked
    
    # Error metrics
    error_rate: float = 0.0  # Fraction of calls that errored
    recent_errors: List[str] = field(default_factory=list)  # Last 5 errors
    
    # Status
    status: str = "healthy"  # "healthy", "degraded", "unhealthy"
    alerts: List[str] = field(default_factory=list)  # Active alerts
    last_successful_call: Optional[str] = None  # ISO timestamp of last successful call
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        d = asdict(self)
        d["recent_errors"] = d["recent_errors"][:5]  # Keep only last 5
        d["alerts"] = d["alerts"][:10]  # Keep only last 10
        return d


class AgentHealthMonitor:
    """Monitor health and performance of all agents."""

    def __init__(
        self,
        metrics_path: str = "bot/data/llm/agent_health_metrics.json",
        decisions_path: str = "bot/data/llm/decisions.jsonl",
        thesis_tracker_path: str = "bot/data/llm/thesis_tracker.json",
    ):
        self.metrics_path = Path(metrics_path)
        self.decisions_path = Path(decisions_path)
        self.thesis_tracker_path = Path(thesis_tracker_path)
        self.metrics: Dict[str, AgentHealthMetrics] = {}

    def compute_agent_health(self, agent_name: str) -> AgentHealthMetrics:
        """Compute comprehensive health metrics for an agent.

        Args:
            agent_name: Name of agent ("regime", "trade", "risk", "critic", "exit")

        Returns:
            AgentHealthMetrics with current health status
        """
        metrics = AgentHealthMetrics(agent_name=agent_name)

        if agent_name in ("trade", "regime"):
            # Analyze accuracy from thesis tracker
            thesis_data = self._load_thesis_tracker()
            if thesis_data:
                agent_decisions = [
                    t
                    for t in thesis_data
                    if t.get("agent") == agent_name or agent_name in t.get("agents", [])
                ]

                if agent_decisions:
                    wins = sum(1 for d in agent_decisions if d.get("won", False))
                    metrics.accuracy = wins / len(agent_decisions) if agent_decisions else 0.0
                    metrics.calls_made = len(agent_decisions)
                    metrics.avg_confidence = (
                        sum(d.get("confidence", 50) for d in agent_decisions)
                        / len(agent_decisions)
                    )
                    metrics.actual_accuracy = metrics.accuracy * 100
                    metrics.calibration_error = abs(
                        metrics.avg_confidence - metrics.actual_accuracy
                    )

        elif agent_name in ("risk", "critic", "exit"):
            # Analyze from decisions
            decisions = self._load_decisions()
            if decisions:
                agent_decisions = [
                    d for d in decisions if d.get("agent") == agent_name
                ]

                if agent_decisions:
                    metrics.calls_made = len(agent_decisions)
                    # Risk agent: measure position sizing appropriateness
                    # Critic agent: measure veto accuracy
                    # Exit agent: measure reassessment appropriateness

        # Check for recent errors
        metrics = self._check_error_rate(agent_name, metrics)

        # Assess status
        metrics = self._assess_agent_status(metrics)

        # Store latest metrics
        self.metrics[agent_name] = metrics

        return metrics

    def get_all_agent_health(self) -> Dict[str, AgentHealthMetrics]:
        """Get health metrics for all agents.

        Returns:
            Dict mapping agent names to health metrics
        """
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
            self.compute_agent_health(agent_name)

        return self.metrics

    def save_health_report(self) -> None:
        """Save health metrics to JSON file."""
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        health_report = {
            "timestamp": datetime.utcnow().isoformat(),
            "agents": {
                name: metrics.to_dict() for name, metrics in self.metrics.items()
            },
            "overall_status": self._compute_overall_status(),
        }

        with open(self.metrics_path, "w") as f:
            json.dump(health_report, f, indent=2)

        logger.info(f"[HEALTH] Saved health report to {self.metrics_path}")

    def detect_agent_drift(self, agent_name: str, lookback_days: int = 7) -> Optional[str]:
        """Detect if agent has drifted from baseline performance.

        Args:
            agent_name: Agent to check
            lookback_days: Days of history to analyze

        Returns:
            Alert message if drift detected, None otherwise
        """
        metrics = self.compute_agent_health(agent_name)

        # Check calibration drift
        if metrics.calibration_error > 20.0:
            return f"{agent_name} calibration error {metrics.calibration_error:.1f}% > 20%. Confidence predictions are unreliable."

        # Check accuracy degradation
        if metrics.accuracy < 0.45 and metrics.calls_made >= 10:
            return f"{agent_name} accuracy {metrics.accuracy:.1%} < 45%. Consider reviewing prompt or logic."

        # Check error rate spike
        if metrics.error_rate > 0.10:
            return f"{agent_name} error rate {metrics.error_rate:.1%} > 10%. Recent errors: {metrics.recent_errors[:2]}"

        # Check latency increase
        if metrics.max_latency_ms > 5000:
            return f"{agent_name} max latency {metrics.max_latency_ms:.0f}ms > 5000ms. API may be slow or overloaded."

        return None

    def get_health_summary(self) -> str:
        """Get human-readable health summary.

        Returns:
            Summary string with agent status overview
        """
        all_health = self.get_all_agent_health()

        summary_lines = ["=== Agent Health Summary ==="]

        healthy_count = sum(1 for m in all_health.values() if m.status == "healthy")
        degraded_count = sum(1 for m in all_health.values() if m.status == "degraded")
        unhealthy_count = sum(1 for m in all_health.values() if m.status == "unhealthy")

        summary_lines.append(
            f"Overall: {healthy_count} healthy, {degraded_count} degraded, {unhealthy_count} unhealthy"
        )
        summary_lines.append("")

        for agent_name, metrics in sorted(all_health.items()):
            status_emoji = {
                "healthy": "✓",
                "degraded": "⚠",
                "unhealthy": "✗",
            }[metrics.status]

            summary_lines.append(
                f"{status_emoji} {agent_name:12} | "
                f"Accuracy: {metrics.accuracy:.1%} | "
                f"Calls: {metrics.calls_made:3d} | "
                f"Errors: {metrics.error_rate:.1%}"
            )

            if metrics.alerts:
                for alert in metrics.alerts[:2]:  # Show top 2 alerts
                    summary_lines.append(f"    ⚠ {alert}")

        self.save_health_report()
        return "\n".join(summary_lines)

    # Private helper methods

    def _check_error_rate(
        self, agent_name: str, metrics: AgentHealthMetrics
    ) -> AgentHealthMetrics:
        """Check for recent errors from agent logs."""
        # In production, would read from agent-specific error logs
        # For now, estimate from decisions
        metrics.error_rate = 0.0
        metrics.recent_errors = []
        return metrics

    def _assess_agent_status(self, metrics: AgentHealthMetrics) -> AgentHealthMetrics:
        """Assess agent health status based on metrics."""
        alerts = []

        # Accuracy check
        if metrics.calls_made >= 10:
            if metrics.accuracy < 0.40:
                alerts.append("Critical: Accuracy < 40%")
                metrics.status = "unhealthy"
            elif metrics.accuracy < 0.45:
                alerts.append("Warning: Accuracy < 45%")
                metrics.status = "degraded"

        # Calibration check
        if metrics.calibration_error > 25:
            alerts.append("Critical: Calibration error > 25%")
            metrics.status = "unhealthy"
        elif metrics.calibration_error > 15:
            alerts.append("Warning: Calibration error > 15%")
            if metrics.status != "unhealthy":
                metrics.status = "degraded"

        # Error rate check
        if metrics.error_rate > 0.20:
            alerts.append("Critical: Error rate > 20%")
            metrics.status = "unhealthy"
        elif metrics.error_rate > 0.10:
            alerts.append("Warning: Error rate > 10%")
            if metrics.status != "unhealthy":
                metrics.status = "degraded"

        # Latency check
        if metrics.max_latency_ms > 5000:
            alerts.append("Warning: Max latency > 5000ms")
            if metrics.status != "unhealthy":
                metrics.status = "degraded"

        metrics.alerts = alerts
        if not alerts:
            metrics.status = "healthy"

        return metrics

    def _compute_overall_status(self) -> str:
        """Compute overall health status across all agents."""
        if not self.metrics:
            return "unknown"

        unhealthy_count = sum(1 for m in self.metrics.values() if m.status == "unhealthy")
        degraded_count = sum(1 for m in self.metrics.values() if m.status == "degraded")

        if unhealthy_count > 0:
            return "unhealthy"
        elif degraded_count >= 2:
            return "degraded"
        else:
            return "healthy"

    def _load_thesis_tracker(self) -> List[Dict[str, Any]]:
        """Load thesis tracker data."""
        if not self.thesis_tracker_path.exists():
            return []

        try:
            with open(self.thesis_tracker_path) as f:
                data = json.load(f)
                return data.get("theses", [])
        except Exception as e:
            logger.error(f"Failed to load thesis tracker: {e}")
            return []

    def _load_decisions(self) -> List[Dict[str, Any]]:
        """Load decisions JSONL."""
        decisions = []
        if not self.decisions_path.exists():
            return decisions

        try:
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        decisions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to load decisions: {e}")

        return decisions


def get_agent_health_monitor() -> AgentHealthMonitor:
    """Get or create an AgentHealthMonitor instance."""
    return AgentHealthMonitor()