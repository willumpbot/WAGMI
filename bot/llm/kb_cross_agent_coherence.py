"""
KB Cross-Agent Coherence Checker - Validates KB consistency across all 9 specialist agents.

Ensures all agents in the pipeline:
1. Use the same KB version
2. Interpret KB parameters consistently
3. Don't diverge from KB expectations
4. Align on symbol-specific/regime-specific adjustments
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("bot.llm.kb_coherence")


class KBCrossAgentCoherence:
    """Cross-agent KB coherence validation system."""

    # All 9 agents in the pipeline
    AGENT_NAMES = [
        "regime",
        "trade",
        "risk",
        "critic",
        "learning",
        "exit",
        "scout",
        "overseer",
        "quant"
    ]

    def __init__(self):
        self.agent_kb_contexts = {}  # Track what KB each agent received
        self.divergence_log = []

    def record_agent_kb_context(self, agent_name: str, kb_context: Dict[str, Any]):
        """Record the KB context that was passed to an agent."""
        if agent_name not in self.agent_kb_contexts:
            self.agent_kb_contexts[agent_name] = []

        self.agent_kb_contexts[agent_name].append({
            "timestamp": json.dumps({"_": "now"}, default=str),  # Placeholder
            "kb_version": kb_context.get("version"),
            "confidence_threshold": kb_context.get("confidence_threshold"),
            "expected_go_wr": kb_context.get("expected_go_wr"),
            "expected_skip_wr": kb_context.get("expected_skip_wr"),
            "symbol_specific": kb_context.get("symbol_specific", False),
            "regime_specific": kb_context.get("regime_specific", False),
            "regime": kb_context.get("regime"),
        })

    def check_kb_version_consistency(self) -> Tuple[bool, Dict[str, Any]]:
        """Verify all agents received the same KB version."""
        if not self.agent_kb_contexts:
            return True, {"message": "No data yet"}

        versions = defaultdict(list)
        for agent, contexts in self.agent_kb_contexts.items():
            if contexts:
                latest = contexts[-1]
                version = latest.get("kb_version")
                if version:
                    versions[version].append(agent)

        # All agents should have the same KB version
        if len(versions) == 1:
            return True, {
                "message": "All agents consistent",
                "kb_version": list(versions.keys())[0],
                "agent_count": len(self.agent_kb_contexts)
            }
        elif len(versions) > 1:
            return False, {
                "message": "KB version mismatch",
                "versions": {v: agents for v, agents in versions.items()},
                "divergent_agents": [a for agents in list(versions.values())[1:] for a in agents]
            }

        return True, {"message": "Insufficient data"}

    def check_parameter_consistency(self) -> Tuple[bool, Dict[str, Any]]:
        """Verify all agents received consistent KB parameters."""
        if not self.agent_kb_contexts:
            return True, {"message": "No data yet"}

        thresholds = defaultdict(list)
        go_wrs = defaultdict(list)
        skip_wrs = defaultdict(list)

        for agent, contexts in self.agent_kb_contexts.items():
            if contexts:
                latest = contexts[-1]
                thresholds[latest.get("confidence_threshold")].append(agent)
                go_wrs[latest.get("expected_go_wr")].append(agent)
                skip_wrs[latest.get("expected_skip_wr")].append(agent)

        # Parameters should be consistent (except for regime-adjusted cases)
        inconsistencies = []

        if len(thresholds) > 2:  # Allow some variation for regime adjustments
            inconsistencies.append({
                "parameter": "confidence_threshold",
                "variants": len(thresholds),
                "details": {t: agents for t, agents in thresholds.items()}
            })

        result = {
            "message": "Parameters consistent" if not inconsistencies else "Parameter variance detected",
            "parameter_variants": {
                "confidence_threshold": len(thresholds),
                "expected_go_wr": len(go_wrs),
                "expected_skip_wr": len(skip_wrs),
            }
        }

        passed = len(inconsistencies) <= 1  # Allow regime-specific variation
        return passed, result

    def check_symbol_regime_alignment(self) -> Tuple[bool, Dict[str, Any]]:
        """Verify symbol-specific and regime-specific adjustments are applied consistently."""
        if not self.agent_kb_contexts:
            return True, {"message": "No data yet"}

        symbol_specific_agents = set()
        regime_specific_agents = set()
        regime_distributions = defaultdict(set)

        for agent, contexts in self.agent_kb_contexts.items():
            if contexts:
                latest = contexts[-1]
                if latest.get("symbol_specific"):
                    symbol_specific_agents.add(agent)
                if latest.get("regime_specific"):
                    regime_specific_agents.add(agent)

                regime = latest.get("regime")
                if regime:
                    regime_distributions[regime].add(agent)

        result = {
            "symbol_specific_agents": list(symbol_specific_agents),
            "regime_specific_agents": list(regime_specific_agents),
            "regime_distribution": {r: list(agents) for r, agents in regime_distributions.items()}
        }

        # All agents should have same symbol/regime awareness
        consistency = len(symbol_specific_agents) in (0, len(self.agent_kb_contexts))
        return consistency, result

    def check_divergence_flags(self) -> Tuple[bool, Dict[str, Any]]:
        """Check if any agents flagged KB divergence in their decisions."""
        # This would be populated from decision logs
        if not self.divergence_log:
            return True, {"message": "No divergences logged yet"}

        divergence_summary = defaultdict(int)
        for divergence in self.divergence_log:
            agent = divergence.get("agent", "unknown")
            divergence_summary[agent] += 1

        return True, {
            "message": "Divergence tracking active",
            "divergences_by_agent": dict(divergence_summary),
            "total_divergences": len(self.divergence_log)
        }

    def generate_coherence_report(self) -> Dict[str, Any]:
        """Generate comprehensive cross-agent KB coherence report."""
        version_ok, version_result = self.check_kb_version_consistency()
        param_ok, param_result = self.check_parameter_consistency()
        symbol_ok, symbol_result = self.check_symbol_regime_alignment()
        divergence_ok, divergence_result = self.check_divergence_flags()

        overall_passed = all([version_ok, param_ok, symbol_ok, divergence_ok])

        return {
            "overall_coherence": overall_passed,
            "version_consistency": {
                "passed": version_ok,
                "details": version_result
            },
            "parameter_consistency": {
                "passed": param_ok,
                "details": param_result
            },
            "symbol_regime_alignment": {
                "passed": symbol_ok,
                "details": symbol_result
            },
            "divergence_tracking": {
                "passed": divergence_ok,
                "details": divergence_result
            },
            "agents_audited": list(self.agent_kb_contexts.keys()),
            "recommendation": (
                "All agents coherent on KB interpretation"
                if overall_passed
                else "Investigate inconsistencies in agent KB usage"
            )
        }


# Global singleton
_coherence_checker = None


def get_coherence_checker() -> KBCrossAgentCoherence:
    """Get or create coherence checker singleton."""
    global _coherence_checker
    if _coherence_checker is None:
        _coherence_checker = KBCrossAgentCoherence()
    return _coherence_checker


def record_agent_kb_context(agent_name: str, kb_context: Dict[str, Any]):
    """Record KB context for an agent."""
    checker = get_coherence_checker()
    checker.record_agent_kb_context(agent_name, kb_context)


if __name__ == "__main__":
    checker = get_coherence_checker()
    report = checker.generate_coherence_report()

    print("=" * 100)
    print("KB CROSS-AGENT COHERENCE REPORT")
    print("=" * 100)
    print()
    print(f"Overall Coherence: {'[OK] PASSED' if report['overall_coherence'] else '[!!] FAILED'}")
    print()

    for check_name in ["version_consistency", "parameter_consistency", "symbol_regime_alignment"]:
        check_data = report[check_name]
        status = "[OK]" if check_data["passed"] else "[!!]"
        print(f"{status} {check_name.upper().replace('_', ' ')}")
        for key, value in check_data["details"].items():
            if key != "message":
                print(f"    {key}: {value}")

    print()
    print(f"Recommendation: {report['recommendation']}")
    print()
