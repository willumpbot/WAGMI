"""
Shared Context: unified reasoning framework for all specialist agents.

Every agent in the multi-agent pipeline shares:
  1. Vocabulary — identical terms for regimes, actions, confidence scales
  2. Market axioms — hard rules that every agent must respect
  3. Regime-action mapping — what actions are acceptable in each regime
  4. Knowledge base — shared lessons that apply to ALL agents

This module builds a compact shared context block that gets prepended to every
agent's input, ensuring they all reason from the same foundation.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.shared_context")


# ── Shared Vocabulary ────────────────────────────────────────────

REGIME_VOCABULARY = {
    "trend": "Directional move with volume confirmation (OI expanding, funding aligned, pullbacks <30%)",
    "range": "Choppy <2% band, low volume, flat OI, ADX<20",
    "panic": "Crash >5%/1h, volume spike >3x, OI contracting, deep negative funding",
    "high_volatility": "Big swings both ways, ATR>2x avg, unstable correlations",
    "low_liquidity": "Dead market, volume <0.3x avg, wide wicks, off-hours",
    "news_dislocation": "External catalyst >3% in <30min, no prior setup, OI unchanged",
    "unknown": "Conflicting signals, insufficient data",
}

ACTION_VOCABULARY = {
    "go": "Proceed with the trade (aliases: proceed, long, short, buy, sell, enter, trade)",
    "skip": "Do not trade (aliases: flat, hold, pass, wait, no, none)",
    "flip": "Reverse the proposed direction (aliases: reverse)",
}

CONFIDENCE_SCALE = {
    "0.0-0.3": "No edge — must skip",
    "0.3-0.5": "Weak — only proceed if absolutely everything aligns",
    "0.5-0.6": "Marginal — proceed only with 3+ strategy agreement AND regime alignment",
    "0.6-0.7": "Moderate conviction — acceptable for normal sizing",
    "0.7-0.85": "Strong — regime + signals + cross-market all align, size up",
    "0.85-1.0": "Exceptional — everything perfect, rare, maximum conviction",
}


# ── Market Axioms (hard rules every agent must respect) ──────────

MARKET_AXIOMS = [
    "Never long alts into a BTC nuke (BTC dropping >3% in 1h)",
    "Circuit breaker active → always skip, confidence = 0.0",
    "Low liquidity regime → always skip (no edge, wide spreads eat PnL)",
    "Portfolio leverage >= 8.0 → skip (system auto-blocks, don't waste the call)",
    "Funding > 0.05% per 8h → factor as a real cost, not just a signal",
    "3+ consecutive losses → raise selectivity bar, reduce sizing",
    "Regime transition in progress → reduce confidence 15%, wait for confirmation",
    "Cross-market divergence (BTC up, target down) → strong caution signal",
    "Hold time > 4h with funding > 0.03% → funding drag destroys edge",
    "Near-zero stop width → infinite leverage risk, must reject",
]


# ── Regime-Action Mapping ────────────────────────────────────────

REGIME_ACTION_MAP = {
    "trend": {
        "preferred_actions": ["go"],
        "acceptable_actions": ["go", "skip"],
        "forbidden_actions": [],
        "sizing_range": "0.8-2.0",
        "notes": "Trend is the highest-edge regime. Align with direction, size up.",
    },
    "range": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": ["flip"],
        "sizing_range": "0.3-0.8",
        "notes": "Range trades need tight SL and quick exits. Mean-reversion only.",
    },
    "panic": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip"],
        "forbidden_actions": ["go", "flip"],
        "sizing_range": "0.0-0.3",
        "notes": "Panic = stay out. Only enter if confidence >= 0.8 AND playing the reversal.",
    },
    "high_volatility": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": [],
        "sizing_range": "0.3-0.7",
        "notes": "Reduce sizing. Only high-conviction setups. ATR-based stops must be wider.",
    },
    "low_liquidity": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip"],
        "forbidden_actions": ["go", "flip"],
        "sizing_range": "0.0",
        "notes": "Never trade in low liquidity. Wicks will stop you out.",
    },
    "news_dislocation": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": [],
        "sizing_range": "0.3-0.5",
        "notes": "Wait for dust to settle. If entering, use wide stops and small size.",
    },
    "unknown": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip"],
        "forbidden_actions": ["go", "flip"],
        "sizing_range": "0.0",
        "notes": "Unknown = no edge. Wait for clarity.",
    },
}


# ── Shared Memory Bus ────────────────────────────────────────────
# Pipeline scratchpad: upstream agents write, downstream agents read.
# Reset at the start of each pipeline run.

class PipelineScratchpad:
    """Per-pipeline-run shared memory between agents.

    The Regime Agent writes regime insights. The Trade Agent reads them.
    The Trade Agent writes decision rationale. The Risk/Critic Agent reads it.
    This creates a coherent chain of reasoning across agents.
    """

    def __init__(self):
        self._entries: List[Dict[str, Any]] = []
        self._created_at = time.time()

    def write(self, agent_role: str, key: str, value: Any) -> None:
        """Write a named value from an agent."""
        self._entries.append({
            "agent": agent_role,
            "key": key,
            "value": value,
            "ts": time.time(),
        })

    def read_all(self) -> List[Dict[str, Any]]:
        """Read all scratchpad entries (for downstream agents)."""
        return list(self._entries)

    def read_by_agent(self, agent_role: str) -> List[Dict[str, Any]]:
        """Read entries written by a specific agent."""
        return [e for e in self._entries if e["agent"] == agent_role]

    def read_by_key(self, key: str) -> Optional[Any]:
        """Read the most recent value for a key."""
        for entry in reversed(self._entries):
            if entry["key"] == key:
                return entry["value"]
        return None

    def to_compact_json(self, max_entries: int = 10) -> str:
        """Serialize recent entries for injection into agent prompts."""
        recent = self._entries[-max_entries:]
        compact = []
        for e in recent:
            compact.append(f"{e['agent']}: {e['key']}={json.dumps(e['value'], separators=(',', ':'))}")
        return " | ".join(compact) if compact else ""

    def clear(self) -> None:
        """Reset for next pipeline run."""
        self._entries.clear()
        self._created_at = time.time()


# ── Shared Lessons Store ─────────────────────────────────────────
# Cross-agent lessons that persist across pipeline runs.

class SharedLessons:
    """Lessons that apply to ALL agents, not just one specialist.

    Examples:
      - "SOL is highly correlated with BTC in trend regime" (Regime + Trade + Risk)
      - "Funding >0.04% ate 60% of edge on 4h holds" (Trade + Risk)
      - "Our confidence calibration is +0.12 overconfident" (Trade + Critic)
    """

    def __init__(self, max_lessons: int = 30):
        self._lessons: List[Dict[str, Any]] = []
        self._max = max_lessons

    def add(
        self,
        lesson: str,
        source_agent: str,
        applies_to: List[str],
        strength: str = "moderate",
    ) -> None:
        """Add a shared lesson.

        Args:
            lesson: The lesson text (max 200 chars).
            source_agent: Which agent discovered this.
            applies_to: Which agent roles should see it (e.g., ["trade", "risk"]).
            strength: "strong", "moderate", or "weak".
        """
        self._lessons.append({
            "lesson": lesson[:200],
            "source": source_agent,
            "applies_to": applies_to,
            "strength": strength,
            "ts": time.time(),
        })
        # Keep within limit, removing oldest weak lessons first
        if len(self._lessons) > self._max:
            self._prune()

    def get_for_agent(self, agent_role: str, max_lessons: int = 5) -> List[str]:
        """Get lessons relevant to a specific agent role."""
        relevant = [
            l for l in self._lessons
            if agent_role in l["applies_to"] or "all" in l["applies_to"]
        ]
        # Sort by strength (strong first) then recency
        strength_order = {"strong": 0, "moderate": 1, "weak": 2}
        relevant.sort(key=lambda l: (strength_order.get(l["strength"], 2), -l["ts"]))
        return [l["lesson"] for l in relevant[:max_lessons]]

    def _prune(self) -> None:
        """Remove oldest weak lessons to stay within limit."""
        # Keep all strong, trim weak/moderate by age
        strong = [l for l in self._lessons if l["strength"] == "strong"]
        others = [l for l in self._lessons if l["strength"] != "strong"]
        others.sort(key=lambda l: -l["ts"])  # Most recent first
        remaining_slots = self._max - len(strong)
        self._lessons = strong + others[:max(0, remaining_slots)]


# ── Context Builder ──────────────────────────────────────────────

def build_shared_context_block(
    agent_role: str,
    scratchpad: Optional[PipelineScratchpad] = None,
    shared_lessons: Optional[SharedLessons] = None,
    include_axioms: bool = True,
    include_regime_map: bool = False,
) -> str:
    """Build a compact shared context block for an agent.

    This block is prepended to the agent's input JSON, giving it:
    - Market axioms (hard rules)
    - Upstream agent scratchpad entries
    - Shared lessons relevant to this agent
    - Regime-action mapping (if requested)

    Returns a compact string to minimize token usage.
    """
    parts = []

    # Market axioms (compact)
    if include_axioms:
        axiom_block = "AXIOMS: " + " | ".join(MARKET_AXIOMS[:5])
        parts.append(axiom_block)

    # Upstream scratchpad
    if scratchpad:
        scratch_text = scratchpad.to_compact_json(max_entries=6)
        if scratch_text:
            parts.append(f"UPSTREAM: {scratch_text}")

    # Shared lessons for this agent
    if shared_lessons:
        lessons = shared_lessons.get_for_agent(agent_role, max_lessons=3)
        if lessons:
            parts.append("LESSONS: " + " | ".join(lessons))

    # Regime-action map (only for Trade and Critic agents who make action decisions)
    if include_regime_map:
        compact_map = {}
        for regime, mapping in REGIME_ACTION_MAP.items():
            compact_map[regime] = {
                "ok": mapping["acceptable_actions"],
                "no": mapping["forbidden_actions"],
                "sz": mapping["sizing_range"],
            }
        parts.append(f"REGIME_RULES: {json.dumps(compact_map, separators=(',', ':'))}")

    return " || ".join(parts) if parts else ""


# ── Singleton instances ──────────────────────────────────────────

_shared_lessons: Optional[SharedLessons] = None
_pipeline_scratchpad: Optional[PipelineScratchpad] = None


def get_shared_lessons() -> SharedLessons:
    """Get or create the singleton SharedLessons store."""
    global _shared_lessons
    if _shared_lessons is None:
        _shared_lessons = SharedLessons(max_lessons=30)
    return _shared_lessons


def get_pipeline_scratchpad() -> PipelineScratchpad:
    """Get or create the pipeline scratchpad."""
    global _pipeline_scratchpad
    if _pipeline_scratchpad is None:
        _pipeline_scratchpad = PipelineScratchpad()
    return _pipeline_scratchpad


def reset_pipeline_scratchpad() -> PipelineScratchpad:
    """Reset the scratchpad for a new pipeline run."""
    global _pipeline_scratchpad
    _pipeline_scratchpad = PipelineScratchpad()
    return _pipeline_scratchpad
