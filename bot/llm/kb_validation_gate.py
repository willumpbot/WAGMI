"""
KB Validation Gate — Active validation of agent decisions against empirical KB.

Runs AFTER agents output decisions but BEFORE execution.
Checks:
1. Agent confidence vs KB threshold
2. Action consistency with KB expectations
3. Regime-specific performance alignment
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("bot.llm.kb_validation_gate")


class KBValidationGate:
    """Validate agent decisions against empirical KB parameters."""

    def __init__(self):
        self.kb_params = None
        self._load_kb()

    def _load_kb(self):
        """Load current KB parameters."""
        try:
            from llm.kb_context_injector import get_kb_injector
            injector = get_kb_injector()
            self.kb_params = injector.get_kb_summary()
        except Exception as e:
            logger.warning("[KB-GATE] Failed to load KB: %s", e)

    def validate_agent_decision(
        self,
        agent_name: str,
        decision: Dict[str, Any],
        snapshot: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate agent decision against KB.

        Args:
            agent_name: "trade", "risk", "critic", etc.
            decision: Agent's output JSON
            snapshot: Market snapshot context

        Returns:
            (is_valid, reason, validation_details)
        """
        if not self.kb_params:
            return True, "KB not loaded, allowing decision", {}

        agent_action = decision.get("a", "skip").lower()  # go/skip/flip
        agent_confidence = float(decision.get("c", 0.5))
        kb_threshold = self.kb_params.get("confidence_threshold", 45)
        expected_go_wr = self.kb_params.get("expected_go_wr", 0.50)
        expected_skip_wr = self.kb_params.get("expected_skip_wr", 0.221)

        validation_details = {
            "agent": agent_name,
            "action": agent_action,
            "confidence": agent_confidence,
            "kb_threshold": kb_threshold,
            "expected_go_wr": expected_go_wr,
            "expected_skip_wr": expected_skip_wr,
        }

        # Regime-specific alignment
        regime = snapshot.get("regime", "unknown")
        validation_details["regime"] = regime

        if agent_name.lower() == "trade":
            return self._validate_trade_decision(
                agent_action, agent_confidence, kb_threshold, validation_details
            )
        elif agent_name.lower() == "risk":
            return self._validate_risk_decision(agent_action, agent_confidence, validation_details)
        elif agent_name.lower() == "critic":
            return self._validate_critic_decision(agent_action, validation_details)
        else:
            return True, "No validation rule for agent", validation_details

    def _validate_trade_decision(
        self,
        action: str,
        confidence: float,
        threshold: float,
        details: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate trade agent decision against KB expectations."""

        # Check 1: Confidence vs KB threshold
        above_threshold = confidence >= (threshold / 100.0)  # KB threshold is in 0-100 scale

        # Check 2: Action consistency
        if action in ("go", "proceed"):
            # GO should have confidence >= threshold
            action_aligned = above_threshold
            details["check_1_confidence_vs_threshold"] = above_threshold
            details["check_2_action_aligned"] = action_aligned
        elif action in ("skip", "flat"):
            # SKIP should have confidence < threshold (conservative)
            action_aligned = not above_threshold
            details["check_1_confidence_vs_threshold"] = not above_threshold
            details["check_2_action_aligned"] = action_aligned
        else:
            action_aligned = True  # FLIP/other actions are flexible
            details["check_2_action_aligned"] = True

        # Final validation
        if action_aligned and (confidence >= 0.30):  # Floor: no ultra-low confidence
            return True, "PASS", details
        elif not action_aligned:
            reason = f"Action misaligned: {action} with confidence {confidence:.1%} vs KB threshold {threshold}"
            logger.info("[KB-GATE] %s", reason)
            return False, reason, details
        else:
            reason = f"Confidence too low: {confidence:.1%}"
            return False, reason, details

    def _validate_risk_decision(
        self, action: str, confidence: float, details: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate risk agent decision."""
        # Risk agent should never recommend extreme leverage on low confidence
        if confidence < 0.30 and action == "go":
            return False, "Risk rejected: low confidence + go action", details
        return True, "PASS", details

    def _validate_critic_decision(
        self, action: str, details: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate critic agent veto decision."""
        # Critic can always veto, always passes validation
        return True, "PASS", details

    def audit_decision(self, decision: Dict[str, Any], validation_result: Dict[str, Any]):
        """Log KB validation for audit trail."""
        try:
            entry = {
                "timestamp": decision.get("timestamp"),
                "agent": validation_result.get("agent"),
                "kb_version": self.kb_params.get("kb_version") if self.kb_params else "unknown",
                "validation": validation_result,
                "status": "PASS" if validation_result.get("pass") else "BLOCKED",
            }
            # Append to KB validation audit log
            import json
            from pathlib import Path
            audit_file = Path("data/llm/kb_validation_audit.jsonl")
            audit_file.parent.mkdir(parents=True, exist_ok=True)
            with open(audit_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.warning("[KB-GATE] Failed to audit: %s", e)


# Global singleton
_gate = None


def get_kb_validation_gate() -> KBValidationGate:
    """Get or create KB validation gate."""
    global _gate
    if _gate is None:
        _gate = KBValidationGate()
    return _gate


def validate_agent_output(
    agent_name: str, decision: Dict[str, Any], snapshot: Dict[str, Any]
) -> Tuple[bool, str]:
    """Convenience function to validate agent output."""
    gate = get_kb_validation_gate()
    is_valid, reason, details = gate.validate_agent_decision(agent_name, decision, snapshot)
    details["pass"] = is_valid
    gate.audit_decision(decision, details)
    return is_valid, reason
