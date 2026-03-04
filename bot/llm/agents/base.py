"""
Base types for the multi-agent LLM system.

Each agent receives a subset of the full snapshot and produces a typed
output dict. The coordinator merges agent outputs into one LLMDecision.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.base")


class AgentRole(str, Enum):
    """Specialist agent roles."""
    REGIME = "regime"          # Market regime analysis
    TRADE = "trade"            # Trade evaluation (proceed/flat/flip)
    RISK = "risk"              # Risk & position sizing
    LEARNING = "learning"      # Post-trade learning extraction
    CRITIC = "critic"          # Self-critique / meta-review
    EXIT = "exit"              # Exit intelligence for open positions


@dataclass
class AgentOutput:
    """Typed output from a single agent."""
    role: AgentRole
    data: Dict[str, Any]          # Parsed JSON from agent
    raw_text: str = ""            # Raw LLM response
    model_used: str = ""          # Which model served this
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None   # Non-None if agent call failed

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.data)


@dataclass
class AgentConfig:
    """Per-agent configuration."""
    role: AgentRole
    enabled: bool = True
    model_override: Optional[str] = None   # Override tier-based routing
    max_tokens: int = 1024                 # Agents need far fewer tokens
    timeout_s: float = 15.0
    required: bool = False                 # If True, failure aborts the pipeline


# Default agent configs: Regime + Trade are required; others are optional
DEFAULT_AGENT_CONFIGS: Dict[AgentRole, AgentConfig] = {
    AgentRole.REGIME: AgentConfig(
        role=AgentRole.REGIME,
        max_tokens=2048,
        timeout_s=15.0,
        required=True,
    ),
    AgentRole.TRADE: AgentConfig(
        role=AgentRole.TRADE,
        max_tokens=3072,
        timeout_s=20.0,
        required=True,
    ),
    AgentRole.RISK: AgentConfig(
        role=AgentRole.RISK,
        max_tokens=2048,
        timeout_s=15.0,
        required=False,
    ),
    AgentRole.LEARNING: AgentConfig(
        role=AgentRole.LEARNING,
        max_tokens=2048,
        timeout_s=15.0,
        required=False,
    ),
    AgentRole.CRITIC: AgentConfig(
        role=AgentRole.CRITIC,
        max_tokens=3072,
        timeout_s=20.0,
        required=False,
    ),
    AgentRole.EXIT: AgentConfig(
        role=AgentRole.EXIT,
        max_tokens=1024,
        timeout_s=10.0,
        required=False,
    ),
}
