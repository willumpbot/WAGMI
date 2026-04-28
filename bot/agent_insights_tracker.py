"""
Agent Insights Tracker
Maintains structured record of agent learnings across cycles.
Tracks patterns, discoveries, and confidence in findings.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentInsightsTracker:
    """Track and consolidate agent learnings across autonomous cycles."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.insights_file = self.data_dir / "agent_insights_tracker.json"
        self.reports_dir = self.data_dir / "learning_reports"
        self.reports_dir.mkdir(exist_ok=True)
        self._load_or_init()

    def _load_or_init(self):
        """Load existing insights or initialize new tracker."""
        if self.insights_file.exists():
            with open(self.insights_file) as f:
                self.insights = json.load(f)
        else:
            self.insights = {
                "created": datetime.now().isoformat(),
                "cycles": {},
                "consolidated_patterns": {},
                "hypothesis_tracker": {},
                "confidence_matrix": {},
                "meta_learnings": []
            }
            self._save()

    def record_cycle_insights(self, cycle_num: int, analysis: Dict[str, Any]):
        """Record agent analysis from a completed cycle."""

        cycle_key = f"cycle_{cycle_num}"
        self.insights["cycles"][cycle_key] = {
            "timestamp": datetime.now().isoformat(),
            "num": cycle_num,
            "raw_analysis": analysis,
            "extractions": {}
        }

        # Extract key patterns
        extractions = self.insights["cycles"][cycle_key]["extractions"]

        # Regime patterns
        if "regime_understanding" in analysis:
            extractions["regimes"] = analysis["regime_understanding"]
            self._consolidate_regime_patterns(cycle_num, analysis["regime_understanding"])

        # Setup patterns
        if "setup_understanding" in analysis:
            extractions["setups"] = analysis["setup_understanding"]
            self._consolidate_setup_patterns(cycle_num, analysis["setup_understanding"])

        # Confidence insights
        if "confidence_calibration" in analysis:
            extractions["confidence"] = analysis["confidence_calibration"]

        # Edge discoveries
        if "edge_discovery" in analysis:
            extractions["edges"] = analysis["edge_discovery"]
            self._track_edge_hypotheses(cycle_num, analysis["edge_discovery"])

        self._save()
        logger.info(f"Recorded insights from Cycle {cycle_num}")

    def _consolidate_regime_patterns(self, cycle_num: int, regime_data: Dict[str, Any]):
        """Track regime patterns across cycles."""

        if "regime_patterns" not in self.insights["consolidated_patterns"]:
            self.insights["consolidated_patterns"]["regime_patterns"] = {}

        for regime, stats in regime_data.items():
            if regime not in self.insights["consolidated_patterns"]["regime_patterns"]:
                self.insights["consolidated_patterns"]["regime_patterns"][regime] = {
                    "observations": [],
                    "avg_wr": 0,
                    "consistency": 0,
                    "recommendation": ""
                }

            obs = self.insights["consolidated_patterns"]["regime_patterns"][regime]
            obs["observations"].append({
                "cycle": cycle_num,
                "wr": stats.get("observed_wr", 0),
                "sample_size": stats.get("sample_size", 0),
                "quality": stats.get("quality", "unknown")
            })

            # Recalculate average
            wrs = [o["wr"] for o in obs["observations"]]
            obs["avg_wr"] = sum(wrs) / len(wrs) if wrs else 0
            obs["num_observations"] = len(wrs)

            # Consistency: lower std dev = more consistent
            if len(wrs) > 1:
                mean = obs["avg_wr"]
                variance = sum((w - mean) ** 2 for w in wrs) / len(wrs)
                obs["consistency"] = 1 - (variance ** 0.5 / 100)  # Normalized to 0-1

    def _consolidate_setup_patterns(self, cycle_num: int, setup_data: Dict[str, Any]):
        """Track setup patterns across cycles."""

        if "setup_patterns" not in self.insights["consolidated_patterns"]:
            self.insights["consolidated_patterns"]["setup_patterns"] = {}

        for setup, stats in setup_data.items():
            if setup not in self.insights["consolidated_patterns"]["setup_patterns"]:
                self.insights["consolidated_patterns"]["setup_patterns"][setup] = {
                    "observations": [],
                    "avg_wr": 0,
                    "consistency": 0
                }

            obs = self.insights["consolidated_patterns"]["setup_patterns"][setup]
            obs["observations"].append({
                "cycle": cycle_num,
                "wr": stats.get("observed_wr", 0),
                "sample_size": stats.get("sample_size", 0),
                "quality": stats.get("quality", "unknown")
            })

            # Recalculate average
            wrs = [o["wr"] for o in obs["observations"]]
            obs["avg_wr"] = sum(wrs) / len(wrs) if wrs else 0
            obs["num_observations"] = len(wrs)

            if len(wrs) > 1:
                mean = obs["avg_wr"]
                variance = sum((w - mean) ** 2 for w in wrs) / len(wrs)
                obs["consistency"] = 1 - (variance ** 0.5 / 100)

    def _track_edge_hypotheses(self, cycle_num: int, edge_data: Any):
        """Track hypothesis validation across cycles."""

        if not isinstance(edge_data, dict):
            return

        for edge_name, edge_info in edge_data.items():
            if isinstance(edge_info, dict):
                if edge_name not in self.insights["hypothesis_tracker"]:
                    self.insights["hypothesis_tracker"][edge_name] = {
                        "first_observed": cycle_num,
                        "observations": [],
                        "validation_confidence": 0
                    }

                hyp = self.insights["hypothesis_tracker"][edge_name]
                hyp["observations"].append({
                    "cycle": cycle_num,
                    "data": edge_info
                })

                # Confidence increases with repeated observations
                hyp["validation_confidence"] = min(100, len(hyp["observations"]) * 20)

    def generate_cycle_report(self, cycle_num: int) -> str:
        """Generate markdown report for a cycle."""

        cycle_key = f"cycle_{cycle_num}"
        if cycle_key not in self.insights["cycles"]:
            return f"No insights found for Cycle {cycle_num}"

        cycle = self.insights["cycles"][cycle_key]
        report = f"""# Agent Learning Report — Cycle {cycle_num}

**Generated**: {datetime.now().isoformat()}
**Data**: {cycle['timestamp']}

## Regime Understanding

"""
        if "regimes" in cycle["extractions"]:
            for regime, stats in cycle["extractions"]["regimes"].items():
                wr = stats.get("observed_wr", 0)
                quality = stats.get("quality", "unknown")
                report += f"- **{regime}**: {wr:.1f}% WR ({stats.get('sample_size', 0)} trades) — {quality}\n"

        report += "\n## Setup Quality\n\n"
        if "setups" in cycle["extractions"]:
            for setup, stats in cycle["extractions"]["setups"].items():
                wr = stats.get("observed_wr", 0)
                report += f"- **{setup}**: {wr:.1f}% WR ({stats.get('sample_size', 0)} trades)\n"

        report += "\n## Pattern Consolidation\n\n"
        if "regime_patterns" in self.insights["consolidated_patterns"]:
            report += "### Regime Consistency (Across All Cycles So Far)\n\n"
            for regime, pattern in self.insights["consolidated_patterns"]["regime_patterns"].items():
                avg_wr = pattern.get("avg_wr", 0)
                consistency = pattern.get("consistency", 0)
                num_obs = pattern.get("num_observations", 0)
                report += f"- **{regime}**: avg {avg_wr:.1f}% WR, consistency {consistency:.0%}, {num_obs} observations\n"

        # Save report
        report_file = self.reports_dir / f"cycle_{cycle_num}_report.md"
        with open(report_file, 'w') as f:
            f.write(report)

        logger.info(f"Generated report: {report_file}")
        return report

    def summary(self) -> str:
        """Generate summary of all learnings so far."""

        summary = f"""# Agent Learning Summary

**Cycles Completed**: {len(self.insights['cycles'])}
**Updated**: {datetime.now().isoformat()}

## Validated Patterns

"""
        # Regimes with high consistency
        if "regime_patterns" in self.insights["consolidated_patterns"]:
            good_regimes = [
                (r, p) for r, p in self.insights["consolidated_patterns"]["regime_patterns"].items()
                if p.get("consistency", 0) > 0.7 and p.get("num_observations", 0) > 1
            ]
            if good_regimes:
                summary += "### High-Confidence Regime Findings\n\n"
                for regime, pattern in good_regimes:
                    summary += f"- **{regime}**: {pattern.get('avg_wr', 0):.1f}% WR (consistency {pattern.get('consistency', 0):.0%})\n"

        # Validated hypotheses
        if self.insights["hypothesis_tracker"]:
            summary += "\n### Validated Hypotheses\n\n"
            for edge_name, hyp in self.insights["hypothesis_tracker"].items():
                if hyp.get("validation_confidence", 0) >= 60:
                    summary += f"- **{edge_name}**: {hyp.get('validation_confidence', 0):.0f}% confidence ({len(hyp.get('observations', []))} cycles)\n"

        return summary

    def _save(self):
        """Save insights to JSON."""
        with open(self.insights_file, 'w') as f:
            json.dump(self.insights, f, indent=2)


if __name__ == "__main__":
    tracker = AgentInsightsTracker()
    print("Agent Insights Tracker initialized")
    print(f"Insights file: {tracker.insights_file}")
    print(f"Reports dir: {tracker.reports_dir}")
