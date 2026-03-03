"""
Thought Protocol: structured reasoning template injected into every agent prompt.

Forces all agents to follow the same reasoning chain:
  1. OBSERVE — What does the data say? (must cite specific numbers)
  2. RECALL  — What does memory/history say about similar situations?
  3. REASON  — Given observation + recall, what's the logical conclusion?
  4. DECIDE  — What action follows from the reasoning?
  5. JUSTIFY — Why this action and not the alternatives?

The protocol is injected as a compact prefix to the agent's system prompt.
Each agent can customize which steps are mandatory vs optional.

This eliminates:
  - Agents "winging it" with unstructured reasoning
  - Inconsistent reasoning styles between agents
  - Decisions without evidence
  - Overconfidence without self-awareness
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.thought_protocol")


# ── Protocol Definitions ─────────────────────────────────────────

class ThoughtStep:
    """One step in the reasoning protocol."""

    def __init__(
        self,
        name: str,
        instruction: str,
        required: bool = True,
        max_tokens_hint: int = 50,
    ):
        self.name = name
        self.instruction = instruction
        self.required = required
        self.max_tokens_hint = max_tokens_hint


# ── Per-Agent Protocol Configurations ────────────────────────────

REGIME_AGENT_PROTOCOL = [
    ThoughtStep(
        "OBSERVE",
        "State the key data: price change %, volume ratio, OI change, funding rate, BTC direction. Use numbers.",
        required=True,
        max_tokens_hint=60,
    ),
    ThoughtStep(
        "RECALL",
        "What regime was this 1h ago? Is it shifting? Any similar patterns in regime_history?",
        required=False,
        max_tokens_hint=30,
    ),
    ThoughtStep(
        "CLASSIFY",
        "Pick exactly ONE regime. State your confidence (0.0-1.0) and the decisive factor.",
        required=True,
        max_tokens_hint=30,
    ),
]

TRADE_AGENT_PROTOCOL = [
    ThoughtStep(
        "OBSERVE",
        "Regime from Regime Agent. Signal strength (how many strategies agree). Entry quality. Funding cost.",
        required=True,
        max_tokens_hint=80,
    ),
    ThoughtStep(
        "RECALL",
        "Check deep_memory/examples for similar setups. Check recent_lessons for this symbol/regime combo. Check recent_dec for consistency.",
        required=True,
        max_tokens_hint=60,
    ),
    ThoughtStep(
        "REASON",
        "Does the regime support this direction? Does cross-market confirm? Is funding manageable? Does history favor this?",
        required=True,
        max_tokens_hint=80,
    ),
    ThoughtStep(
        "DECIDE",
        "go/skip/flip. Set confidence based on the CONFIDENCE CALIBRATION scale. Apply self_perf correction if needed.",
        required=True,
        max_tokens_hint=40,
    ),
    ThoughtStep(
        "JUSTIFY",
        "Why this action and not the alternatives? What would change your mind?",
        required=True,
        max_tokens_hint=40,
    ),
]

RISK_AGENT_PROTOCOL = [
    ThoughtStep(
        "OBSERVE",
        "Portfolio leverage, correlation risk, funding cost, trade decision + confidence, regime.",
        required=True,
        max_tokens_hint=50,
    ),
    ThoughtStep(
        "SIZE",
        "Apply sizing rules: portfolio leverage bands, correlation penalty, regime-based strategy weights.",
        required=True,
        max_tokens_hint=40,
    ),
    ThoughtStep(
        "FLAG",
        "List any risk flags (high leverage, correlated positions, funding drag, losing streak).",
        required=True,
        max_tokens_hint=30,
    ),
]

CRITIC_AGENT_PROTOCOL = [
    ThoughtStep(
        "OBSERVE",
        "What did each prior agent decide? Regime classification, trade action, risk sizing.",
        required=True,
        max_tokens_hint=50,
    ),
    ThoughtStep(
        "CHALLENGE",
        "Check: Does action match regime? Is confidence calibrated (check self_perf.cal)? Contradicts recent decisions? Memory shows failures?",
        required=True,
        max_tokens_hint=60,
    ),
    ThoughtStep(
        "VERDICT",
        "approve or challenge. If challenging, provide adjusted_action and/or adjusted_confidence with reason.",
        required=True,
        max_tokens_hint=40,
    ),
]

LEARNING_AGENT_PROTOCOL = [
    ThoughtStep(
        "OBSERVE",
        "Trade outcome: symbol, side, pnl, regime, hold time, exit reason, funding paid.",
        required=True,
        max_tokens_hint=50,
    ),
    ThoughtStep(
        "DIAGNOSE",
        "WHAT happened + WHY it happened. Was it entry timing? Regime mismatch? Sizing? Funding?",
        required=True,
        max_tokens_hint=60,
    ),
    ThoughtStep(
        "PRESCRIBE",
        "WHAT TO DO NEXT TIME. Specific, actionable, with conditions. Generate hypothesis if pattern is emerging.",
        required=True,
        max_tokens_hint=50,
    ),
]


# ── Protocol Registry ────────────────────────────────────────────

AGENT_PROTOCOLS: Dict[str, List[ThoughtStep]] = {
    "regime": REGIME_AGENT_PROTOCOL,
    "trade": TRADE_AGENT_PROTOCOL,
    "risk": RISK_AGENT_PROTOCOL,
    "critic": CRITIC_AGENT_PROTOCOL,
    "learning": LEARNING_AGENT_PROTOCOL,
}


# ── Protocol Injection ──────────────────────────────────────────

def build_protocol_prefix(agent_role: str) -> str:
    """Build a compact reasoning protocol prefix for an agent.

    This gets prepended to the agent's system prompt to enforce
    structured reasoning.

    Returns a compact string like:
    "THINK: 1.OBSERVE(price%,vol,OI,funding,BTC) 2.RECALL(regime_history) 3.CLASSIFY(one regime,conf,factor)"
    """
    protocol = AGENT_PROTOCOLS.get(agent_role)
    if not protocol:
        return ""

    steps = []
    for i, step in enumerate(protocol, 1):
        marker = "*" if step.required else "?"
        # Compact the instruction to save tokens
        short_instruction = step.instruction
        if len(short_instruction) > 80:
            short_instruction = short_instruction[:77] + "..."
        steps.append(f"{i}.{step.name}{marker}({short_instruction})")

    return "REASONING CHAIN: " + " → ".join(steps)


def build_full_protocol_block(agent_role: str) -> str:
    """Build a more detailed protocol block (for prompt engineering/debugging).

    This is the expanded version used when developing/testing prompts.
    For production injection, use build_protocol_prefix() which is more compact.
    """
    protocol = AGENT_PROTOCOLS.get(agent_role)
    if not protocol:
        return ""

    lines = [f"## Reasoning Protocol for {agent_role.upper()} Agent"]
    lines.append("Follow this chain for EVERY decision. Do not skip required (*) steps.")
    lines.append("")

    for i, step in enumerate(protocol, 1):
        req = "REQUIRED" if step.required else "optional"
        lines.append(f"### Step {i}: {step.name} [{req}]")
        lines.append(step.instruction)
        lines.append("")

    lines.append("Your JSON output should reflect this reasoning chain in the notes/factors field.")

    return "\n".join(lines)


def validate_agent_output_against_protocol(
    agent_role: str,
    output_data: dict,
) -> Dict[str, bool]:
    """Check if an agent's output shows evidence of following the protocol.

    Returns a dict of step_name → followed (True/False).
    This is for monitoring/calibration, not enforcement.
    """
    protocol = AGENT_PROTOCOLS.get(agent_role, [])
    results = {}

    # Heuristic checks based on output content
    notes = str(output_data.get("n", output_data.get("notes", "")))
    factors = str(output_data.get("factors", ""))
    combined = notes + " " + factors

    for step in protocol:
        # Check if the output shows evidence of each step
        if step.name == "OBSERVE":
            # Should contain numbers/data references
            has_numbers = any(c.isdigit() for c in combined)
            results[step.name] = has_numbers
        elif step.name == "RECALL":
            # Should reference memory, history, or past patterns
            recall_markers = ["memory", "history", "similar", "before", "previous",
                            "last time", "pattern", "lesson", "learned"]
            results[step.name] = any(m in combined.lower() for m in recall_markers)
        elif step.name == "REASON":
            # Should contain causal language
            reason_markers = ["because", "therefore", "since", "given", "implies",
                            "suggests", "indicates", "confirms", "contradicts"]
            results[step.name] = any(m in combined.lower() for m in reason_markers)
        elif step.name in ("DECIDE", "CLASSIFY", "VERDICT", "SIZE"):
            # Should produce a clear output (action, regime, verdict, size)
            results[step.name] = bool(output_data)  # Has structured output
        elif step.name in ("JUSTIFY", "PRESCRIBE", "DIAGNOSE", "CHALLENGE", "FLAG"):
            # Should have non-trivial notes
            results[step.name] = len(combined.strip()) > 10
        else:
            results[step.name] = True  # Unknown step, assume followed

    return results
