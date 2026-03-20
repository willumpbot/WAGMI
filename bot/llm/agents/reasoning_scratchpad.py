"""
DEPRECATED: Use PipelineScratchpad from shared_context.py instead.

The coordinator uses PipelineScratchpad (in shared_context.py) for inter-agent
communication. This ReasoningScratchpad was created separately but never wired
into the coordinator. Its richer data structures (ScratchpadEntry with
key_findings, red_flags, recommendations) are useful concepts that should be
migrated into PipelineScratchpad if needed.

For now, all new code should use:
    from llm.agents.shared_context import get_pipeline_scratchpad
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("bot.llm.agents.reasoning_scratchpad")


# ─────────────────────────────────────────────────────────────────────────────
# SCRATCHPAD ENTRIES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScratchpadEntry:
    """A single entry written by an agent to the shared scratchpad."""
    agent: str  # "regime" | "quant" | "trade" | "risk" | "critic"
    timestamp: datetime
    summary: str  # Brief summary of this agent's thinking
    key_findings: Dict[str, Any] = field(default_factory=dict)  # Structured data
    uncertainties: List[str] = field(default_factory=list)  # What's unclear?
    red_flags: List[str] = field(default_factory=list)  # Concerns
    recommendations: List[str] = field(default_factory=list)  # For downstream agents

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "agent": self.agent,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary,
            "key_findings": self.key_findings,
            "uncertainties": self.uncertainties,
            "red_flags": self.red_flags,
            "recommendations": self.recommendations,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScratchpadEntry":
        """Deserialize from dict."""
        d = dict(d)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return ScratchpadEntry(**d)


# ─────────────────────────────────────────────────────────────────────────────
# THE SCRATCHPAD
# ─────────────────────────────────────────────────────────────────────────────

class ReasoningScratchpad:
    """Shared reasoning workspace for all agents in a pipeline.

    Each decision cycle (per symbol evaluation), a new scratchpad is created.
    Agents write their summaries, downstream agents read them.

    This ensures perfect information sharing + logical coherence.
    """

    def __init__(self, symbol: str, decision_id: str):
        """Initialize a scratchpad for a specific decision.

        Args:
            symbol: Trading pair (e.g., "SOL/USDC")
            decision_id: Unique identifier for this decision cycle
        """
        self.symbol = symbol
        self.decision_id = decision_id
        self.created_at = datetime.now()
        self.entries: Dict[str, ScratchpadEntry] = {}  # agent_name → entry

    def write(self, agent: str, summary: str, **data) -> None:
        """Write an entry to the scratchpad.

        Args:
            agent: Agent name ("regime", "trade", etc.)
            summary: Brief summary of thinking
            **data: Keyword arguments:
                - key_findings: Dict of important results
                - uncertainties: List of unclear items
                - red_flags: List of concerns
                - recommendations: List of guidance for downstream

        Example:
            scratchpad.write(
                "regime",
                "Trend regime with strengthening momentum",
                key_findings={"regime": "trend", "confidence": 0.85},
                red_flags=["ADX may roll over in 2-4h"],
                recommendations=["Trade should size up", "Expect mean-reversion in 4-12h"]
            )
        """
        entry = ScratchpadEntry(
            agent=agent,
            timestamp=datetime.now(),
            summary=summary,
            key_findings=data.get("key_findings", {}),
            uncertainties=data.get("uncertainties", []),
            red_flags=data.get("red_flags", []),
            recommendations=data.get("recommendations", []),
        )
        self.entries[agent] = entry

        logger.debug(f"[SCRATCHPAD] {agent.upper()} wrote: {summary[:80]}")

    def read_agent(self, agent: str) -> Optional[ScratchpadEntry]:
        """Read an agent's entry.

        Args:
            agent: Agent name to read

        Returns: ScratchpadEntry or None if not written yet
        """
        return self.entries.get(agent)

    def read_prior_agents(self, current_agent: str) -> List[ScratchpadEntry]:
        """Read all entries from agents that run BEFORE current agent in pipeline.

        Pipeline order: Regime → Quant → Trade → Risk → Critic

        Returns: List of entries in order
        """
        pipeline_order = ["regime", "quant", "trade", "risk", "critic"]

        if current_agent not in pipeline_order:
            return []

        current_idx = pipeline_order.index(current_agent)
        prior_agents = pipeline_order[:current_idx]

        entries = []
        for agent in prior_agents:
            if agent in self.entries:
                entries.append(self.entries[agent])

        return entries

    def get_prior_agents_summary(self, current_agent: str) -> str:
        """Get a formatted summary of all prior agents' thinking.

        This is injected into the current agent's context for coherence.

        Example output:
        ```
        ## PRIOR AGENT THINKING

        **Regime Agent**: Trend regime with strengthening momentum
        - Key: regime=trend (conf=0.85), momentum=strengthening
        - Red flags: ADX may roll over in 2-4h
        - Recommends: Size up, expect reversion in 4-12h

        **Quant Agent**: High EV setup with positive kelly
        - Key: ev=0.24, kelly=0.12, quality=high
        - Uncertainties: Historical distribution may not hold
        - Recommends: Confluence with other agents before going
        ```
        """
        prior_entries = self.read_prior_agents(current_agent)

        if not prior_entries:
            return ""

        lines = ["## PRIOR AGENT THINKING\n"]

        for entry in prior_entries:
            lines.append(f"**{entry.agent.title()} Agent**: {entry.summary}")

            if entry.key_findings:
                findings_str = ", ".join(f"{k}={v}" for k, v in entry.key_findings.items())
                lines.append(f"- Key: {findings_str}")

            if entry.red_flags:
                for flag in entry.red_flags:
                    lines.append(f"- ⚠️ Red flag: {flag}")

            if entry.uncertainties:
                for unc in entry.uncertainties:
                    lines.append(f"- ?: {unc}")

            if entry.recommendations:
                for rec in entry.recommendations:
                    lines.append(f"- → {rec}")

            lines.append("")

        return "\n".join(lines)

    def get_red_flag_summary(self) -> List[str]:
        """Get all red flags raised by any agent so far.

        Used by Critic Agent to focus on concerns.
        """
        all_flags = []
        for entry in self.entries.values():
            for flag in entry.red_flags:
                all_flags.append(f"{entry.agent}: {flag}")
        return all_flags

    def get_consistency_check_data(self) -> Dict[str, Any]:
        """Get data for consistency checker to validate inter-agent coherence.

        Returns:
            Dict with all entries formatted for coherence validation
        """
        return {
            "symbol": self.symbol,
            "decision_id": self.decision_id,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
            "created_at": self.created_at.isoformat(),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize entire scratchpad."""
        return {
            "symbol": self.symbol,
            "decision_id": self.decision_id,
            "created_at": self.created_at.isoformat(),
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ReasoningScratchpad":
        """Deserialize scratchpad."""
        scratchpad = ReasoningScratchpad(d["symbol"], d["decision_id"])
        scratchpad.created_at = datetime.fromisoformat(d["created_at"])
        for agent, entry_dict in d.get("entries", {}).items():
            scratchpad.entries[agent] = ScratchpadEntry.from_dict(entry_dict)
        return scratchpad


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL SCRATCHPAD MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class ScratchpadManager:
    """Manages scratchpads for current decision cycle."""

    def __init__(self):
        self.scratchpads: Dict[str, ReasoningScratchpad] = {}
        self.history: List[ReasoningScratchpad] = []

    def create_or_get(self, symbol: str, decision_id: str) -> ReasoningScratchpad:
        """Create or retrieve a scratchpad for this decision."""
        key = f"{symbol}:{decision_id}"

        if key not in self.scratchpads:
            scratchpad = ReasoningScratchpad(symbol, decision_id)
            self.scratchpads[key] = scratchpad
            logger.debug(f"[SCRATCHPAD_MANAGER] Created scratchpad for {key}")

        return self.scratchpads[key]

    def cleanup_old(self, older_than_hours: int = 1) -> None:
        """Remove scratchpads older than N hours (keep memory bounded)."""
        cutoff = datetime.now() - timedelta(hours=older_than_hours)

        to_delete = []
        for key, scratchpad in self.scratchpads.items():
            if scratchpad.created_at < cutoff:
                self.history.append(scratchpad)  # Archive
                to_delete.append(key)

        for key in to_delete:
            del self.scratchpads[key]

        if to_delete:
            logger.info(f"[SCRATCHPAD_MANAGER] Cleaned up {len(to_delete)} old scratchpads")

    def get_all_active(self) -> List[ReasoningScratchpad]:
        """Get all active scratchpads."""
        return list(self.scratchpads.values())

    def clear_all(self) -> None:
        """Clear all active scratchpads (end of cycle)."""
        self.scratchpads.clear()


# ─────────────────────────────────────────────────────────────────────────────
# COHERENCE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_scratchpad_coherence(scratchpad: ReasoningScratchpad) -> Dict[str, Any]:
    """Validate logical coherence between agents on scratchpad.

    Checks:
    1. Do red flags accumulate without acknowledgment?
    2. Do downstream agents acknowledge upstream concerns?
    3. Are there logical contradictions?

    Returns:
        Report dict with coherence_score (0-1) and issues
    """
    issues = []

    # Get regime and trade entries (main decision points)
    regime_entry = scratchpad.read_agent("regime")
    trade_entry = scratchpad.read_agent("trade")
    critic_entry = scratchpad.read_agent("critic")

    if not regime_entry or not trade_entry:
        return {"coherence_score": 0.5, "issues": ["Incomplete pipeline (no regime or trade)"]}

    coherence_score = 1.0

    # Check: If regime has red flags, did Trade Agent acknowledge them?
    if regime_entry.red_flags:
        trade_findings = trade_entry.key_findings if trade_entry else {}
        if not any("regime" in str(trade_findings) for _ in [None]):
            issues.append("Trade Agent didn't acknowledge Regime red flags")
            coherence_score -= 0.15

    # Check: If Trade Agent has low confidence, does Critic challenge?
    if trade_entry:
        trade_conf = trade_entry.key_findings.get("confidence", 0.5)
        if trade_conf < 0.50 and critic_entry:
            if not critic_entry.red_flags:
                issues.append("Trade Agent low confidence but Critic didn't challenge")
                coherence_score -= 0.10

    # Check: Contradictions (high flags but high confidence)
    all_flags = scratchpad.get_red_flag_summary()
    if len(all_flags) >= 3 and trade_entry:
        trade_conf = trade_entry.key_findings.get("confidence", 0.5)
        if trade_conf > 0.70:
            issues.append("Many red flags but Trade Agent still high confidence")
            coherence_score -= 0.20

    coherence_score = max(0.0, min(1.0, coherence_score))

    return {
        "coherence_score": coherence_score,
        "issues": issues,
        "symbol": scratchpad.symbol,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

_global_manager: Optional[ScratchpadManager] = None


def get_scratchpad_manager() -> ScratchpadManager:
    """Get or create the global scratchpad manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = ScratchpadManager()
    return _global_manager


__all__ = [
    "ScratchpadEntry",
    "ReasoningScratchpad",
    "ScratchpadManager",
    "validate_scratchpad_coherence",
    "get_scratchpad_manager",
]
