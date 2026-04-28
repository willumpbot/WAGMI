"""
KB Consistency Auditor - Comprehensive audit trail for KB injection and agent alignment.

Tracks:
1. KB parameter injection accuracy (global, symbol-specific, regime-specific)
2. Agent decision alignment with KB expectations
3. Symbol-specific parameter usage by agents
4. Regime-specific parameter adjustments
5. Data consistency (no bad values injected)
6. Cross-agent KB coherence
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger("bot.llm.kb_auditor")


class KBConsistencyAuditor:
    """Comprehensive audit system for KB integration quality."""

    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.audit_log = self.data_dir / "llm" / "kb_consistency_audit.jsonl"
        self.summary_file = self.data_dir / "kb_consistency_summary.json"
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)

    def audit_kb_injection(
        self,
        snapshot_data: Dict[str, Any],
        kb_context: Dict[str, Any],
        symbol: str,
        regime: str,
        injection_type: str = "combined"
    ) -> Dict[str, Any]:
        """
        Audit KB injection for correctness and consistency.

        Args:
            snapshot_data: The market snapshot
            kb_context: The injected KB context
            symbol: Trading symbol
            regime: Market regime
            injection_type: 'global', 'symbol', 'regime', or 'combined'

        Returns:
            Audit result with pass/fail and detailed findings
        """
        audit_result = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "regime": regime,
            "injection_type": injection_type,
            "checks": {}
        }

        # Check 1: KB version validity
        kb_version = kb_context.get("version")
        if kb_version:
            audit_result["checks"]["version_valid"] = True
            audit_result["kb_version"] = kb_version
        else:
            audit_result["checks"]["version_valid"] = False

        # Check 2: Confidence threshold range
        conf_threshold = kb_context.get("confidence_threshold")
        is_valid_threshold = (
            conf_threshold is not None and
            isinstance(conf_threshold, (int, float)) and
            20 <= conf_threshold <= 80  # Reasonable range
        )
        audit_result["checks"]["threshold_valid"] = is_valid_threshold
        audit_result["confidence_threshold"] = conf_threshold

        # Check 3: Win rate ranges
        go_wr = kb_context.get("expected_go_wr", 0.50)
        skip_wr = kb_context.get("expected_skip_wr", 0.221)

        go_wr_valid = isinstance(go_wr, (int, float)) and 0.20 <= go_wr <= 0.80
        skip_wr_valid = isinstance(skip_wr, (int, float)) and 0.10 <= skip_wr <= 0.50

        audit_result["checks"]["go_wr_valid"] = go_wr_valid
        audit_result["checks"]["skip_wr_valid"] = skip_wr_valid
        audit_result["expected_go_wr"] = go_wr
        audit_result["expected_skip_wr"] = skip_wr

        # Check 4: WR coherence (GO should usually > SKIP)
        wr_coherent = go_wr >= skip_wr
        audit_result["checks"]["wr_coherent"] = wr_coherent

        # Check 5: Symbol-specific override presence (if regime-adjusted)
        if injection_type in ("symbol", "combined"):
            symbol_specific = kb_context.get("symbol_specific", False)
            audit_result["checks"]["symbol_specific_detected"] = symbol_specific

        if injection_type in ("regime", "combined"):
            regime_specific = kb_context.get("regime_specific", False)
            audit_result["checks"]["regime_specific_detected"] = regime_specific

        # Check 6: No null/NaN values
        has_nulls = any(
            v is None or (isinstance(v, float) and (v != v))  # NaN check
            for v in [conf_threshold, go_wr, skip_wr]
        )
        audit_result["checks"]["no_nulls"] = not has_nulls

        # Overall pass/fail
        audit_result["passed"] = all(audit_result["checks"].values())

        return audit_result

    def audit_agent_kb_alignment(
        self,
        agent_name: str,
        agent_decision: Dict[str, Any],
        kb_context: Dict[str, Any],
        snapshot_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Audit agent decision alignment with KB expectations.

        Args:
            agent_name: Name of agent
            agent_decision: Agent's output decision
            kb_context: KB context that was available to agent
            snapshot_data: Market snapshot

        Returns:
            Alignment audit result
        """
        audit_result = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "symbol": snapshot_data.get("symbol"),
            "regime": snapshot_data.get("regime"),
            "checks": {}
        }

        action = agent_decision.get("a", "skip").lower()
        confidence = float(agent_decision.get("c", 50))
        kb_threshold = kb_context.get("confidence_threshold", 45)
        expected_go_wr = kb_context.get("expected_go_wr", 0.50)
        expected_skip_wr = kb_context.get("expected_skip_wr", 0.221)

        # Check 1: Confidence range
        conf_valid = 0 <= confidence <= 100
        audit_result["checks"]["confidence_valid"] = conf_valid

        # Check 2: Action-confidence alignment
        # GO decisions should typically have confidence >= threshold
        # SKIP decisions should typically have confidence < threshold
        if action in ("go", "proceed"):
            alignment = confidence >= (kb_threshold / 100.0)
        elif action in ("skip", "flat"):
            alignment = confidence < (kb_threshold / 100.0)
        else:
            alignment = True  # FLIP/other are flexible

        audit_result["checks"]["action_confidence_aligned"] = alignment
        audit_result["action"] = action
        audit_result["confidence"] = confidence
        audit_result["kb_threshold"] = kb_threshold

        # Check 3: Decision justification
        justification = agent_decision.get("n", "")
        has_justification = bool(justification and len(justification) > 10)
        audit_result["checks"]["has_justification"] = has_justification

        # Check 4: Regime awareness
        regime = snapshot_data.get("regime")
        regime_mentioned = regime and regime.lower() in (justification or "").lower()
        audit_result["checks"]["regime_aware"] = regime_mentioned

        # Overall pass/fail
        audit_result["passed"] = all(audit_result["checks"].values())

        return audit_result

    def log_audit(self, audit_entry: Dict[str, Any]):
        """Log audit entry to audit trail."""
        try:
            with open(self.audit_log, "a") as f:
                f.write(json.dumps(audit_entry, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[KB-AUDITOR] Failed to log audit: {e}")

    def generate_consistency_report(self) -> Dict[str, Any]:
        """Generate summary report of KB consistency."""
        if not self.audit_log.exists():
            return {"no_data": True}

        stats = defaultdict(int)
        symbols_audited = set()
        regimes_audited = set()
        agents_audited = set()

        try:
            with open(self.audit_log) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        stats["total_audits"] += 1

                        if entry.get("passed"):
                            stats["passed_audits"] += 1
                        else:
                            stats["failed_audits"] += 1

                        if "symbol" in entry:
                            symbols_audited.add(entry["symbol"])
                        if "regime" in entry:
                            regimes_audited.add(entry["regime"])
                        if "agent" in entry:
                            agents_audited.add(entry["agent"])

                        # Track specific failures
                        checks = entry.get("checks", {})
                        for check_name, passed in checks.items():
                            if not passed:
                                stats[f"failed_{check_name}"] += 1

                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.warning(f"[KB-AUDITOR] Failed to generate report: {e}")
            return {"error": str(e)}

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_audits": stats["total_audits"],
            "passed": stats["passed_audits"],
            "failed": stats["failed_audits"],
            "pass_rate": (
                stats["passed_audits"] / stats["total_audits"]
                if stats["total_audits"] > 0
                else 0
            ),
            "symbols_audited": list(symbols_audited),
            "regimes_audited": list(regimes_audited),
            "agents_audited": list(agents_audited),
            "failure_types": {
                k: v for k, v in stats.items() if k.startswith("failed_") and v > 0
            }
        }

        return report

    def save_consistency_report(self):
        """Save consistency report to file."""
        report = self.generate_consistency_report()
        try:
            with open(self.summary_file, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"[KB-AUDITOR] Report saved: {self.summary_file}")
        except Exception as e:
            logger.warning(f"[KB-AUDITOR] Failed to save report: {e}")

        return report


# Global singleton
_auditor = None


def get_kb_auditor() -> KBConsistencyAuditor:
    """Get or create KB auditor singleton."""
    global _auditor
    if _auditor is None:
        _auditor = KBConsistencyAuditor(data_dir="data")
    return _auditor


def audit_kb_injection(
    snapshot_data: Dict[str, Any],
    kb_context: Dict[str, Any],
    symbol: str,
    regime: str
) -> bool:
    """Convenience function to audit KB injection."""
    auditor = get_kb_auditor()
    result = auditor.audit_kb_injection(snapshot_data, kb_context, symbol, regime)
    auditor.log_audit(result)
    return result["passed"]


if __name__ == "__main__":
    auditor = get_kb_auditor()
    report = auditor.generate_consistency_report()
    print("\n[KB CONSISTENCY AUDIT REPORT]")
    print(f"Total Audits: {report.get('total_audits', 0)}")
    print(f"Pass Rate: {report.get('pass_rate', 0):.1%}")
    print(f"Symbols Audited: {len(report.get('symbols_audited', []))}")
    print(f"Agents Audited: {len(report.get('agents_audited', []))}")
    if report.get("failure_types"):
        print("\nFailure Types:")
        for failure_type, count in report["failure_types"].items():
            print(f"  {failure_type}: {count}")
