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
    SCOUT = "scout"            # Idle-time preparation and forecasting
    OVERSEER = "overseer"      # System-level meta-optimizer (periodic)
    QUANT = "quant"            # Statistical analysis, probability, prediction
    # ── Phase 3 Strategic Agents ────────────────────────────────
    PORTFOLIO = "portfolio"    # Holistic portfolio risk aggregation (daily)
    FORECASTER = "forecaster"  # Regime shift prediction (daily)
    HYPOTHESIS = "hypothesis"  # Novel pattern discovery and generation (weekly)
    CORRELATOR = "correlator"  # Cross-asset correlation and lead-lag (daily)
    # ── Phase 4 Scalping + Conviction Agents ────────────────────
    SCALPER = "scalper"        # Micro-scalping on 1m/5m candles (very frequent)
    CONVICTION = "conviction"  # Ultra-high confidence trade authorization (rare)
    MICRO_TREND = "micro_trend" # Micro-trend detection for scalper context (frequent)
    # ── Phase 4A Core Trading Agents ─────────────────────────────
    POSITION_SIZER = "position_sizer"      # Exact position sizing in USD
    ENTRY_OPTIMIZER = "entry_optimizer"    # Entry timing and method optimization
    EXIT_ADVISOR = "exit_advisor"          # Exit recommendations for open positions
    RISK_GUARD = "risk_guard"              # Risk gate and position override checks
    AGENT_ROUTER = "agent_router"          # Orchestration router (decides which agents to call)
    CONSENSUS_BUILDER = "consensus_builder" # Final decision merger (execute or skip)
    # ── Override System: Educated bypass of mechanical blocks ────
    OVERRIDE = "override"                  # LLM-reasoned override for blocked signals


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
        max_tokens=512,   # JSON output: regime + bias + confidence. 512 is plenty.
        timeout_s=30.0,
        required=True,
    ),
    AgentRole.TRADE: AgentConfig(
        role=AgentRole.TRADE,
        max_tokens=800,   # JSON: action + thesis + sizing. Was 3072, caused truncation.
        timeout_s=60.0,
        required=True,
    ),
    AgentRole.RISK: AgentConfig(
        role=AgentRole.RISK,
        max_tokens=512,   # JSON: size_mult + flags. Lean output.
        timeout_s=40.0,
        required=False,
    ),
    AgentRole.LEARNING: AgentConfig(
        role=AgentRole.LEARNING,
        max_tokens=600,   # JSON: lessons + patterns. Post-trade only.
        timeout_s=30.0,
        required=False,
    ),
    AgentRole.CRITIC: AgentConfig(
        role=AgentRole.CRITIC,
        max_tokens=800,   # JSON: verdict + counter-thesis. Was 3072, caused truncation.
        timeout_s=60.0,
        required=False,
    ),
    AgentRole.EXIT: AgentConfig(
        role=AgentRole.EXIT,
        max_tokens=400,   # JSON: action + reasoning. Simplest output.
        timeout_s=25.0,
        required=False,
    ),
    AgentRole.SCOUT: AgentConfig(
        role=AgentRole.SCOUT,
        max_tokens=500,   # JSON: watchlist (1-3 items). Was 1536, overkill.
        timeout_s=30.0,
        required=False,
    ),
    AgentRole.OVERSEER: AgentConfig(
        role=AgentRole.OVERSEER,
        max_tokens=600,   # JSON: system health + recommendations.
        timeout_s=40.0,
        required=False,
    ),
    AgentRole.QUANT: AgentConfig(
        role=AgentRole.QUANT,
        max_tokens=512,   # JSON: EV + Kelly + stats. Numbers, not prose.
        timeout_s=25.0,
        required=False,
    ),
    # ── Phase 3 Strategic Agents ────────────────────────────────
    AgentRole.PORTFOLIO: AgentConfig(
        role=AgentRole.PORTFOLIO,
        max_tokens=600,   # JSON: portfolio risk summary.
        timeout_s=20.0,
        required=False,
    ),
    AgentRole.FORECASTER: AgentConfig(
        role=AgentRole.FORECASTER,
        max_tokens=500,   # JSON: regime forecast + probabilities.
        timeout_s=15.0,
        required=False,
    ),
    AgentRole.HYPOTHESIS: AgentConfig(
        role=AgentRole.HYPOTHESIS,
        max_tokens=600,   # JSON: hypothesis + evidence.
        timeout_s=20.0,
        required=False,
    ),
    AgentRole.CORRELATOR: AgentConfig(
        role=AgentRole.CORRELATOR,
        max_tokens=500,   # JSON: correlation matrix + alerts.
        timeout_s=15.0,
        required=False,
    ),
    # ── Phase 4 Scalping + Conviction Agents ────────────────────
    AgentRole.SCALPER: AgentConfig(
        role=AgentRole.SCALPER,
        max_tokens=1024,  # Fast, lightweight
        timeout_s=3.0,    # CRITICAL: Must respond in <3 seconds
        required=False,
    ),
    AgentRole.CONVICTION: AgentConfig(
        role=AgentRole.CONVICTION,
        max_tokens=600,   # JSON: conviction score + reasoning.
        timeout_s=10.0,
        required=False,
    ),
    AgentRole.MICRO_TREND: AgentConfig(
        role=AgentRole.MICRO_TREND,
        max_tokens=768,   # Fast, simple output
        timeout_s=3.0,    # CRITICAL: Must respond in <3 seconds
        required=False,
    ),
    # ── Phase 4A Core Trading Agents ─────────────────────────────
    AgentRole.POSITION_SIZER: AgentConfig(
        role=AgentRole.POSITION_SIZER,
        max_tokens=1024,
        timeout_s=5.0,
        required=False,
    ),
    AgentRole.ENTRY_OPTIMIZER: AgentConfig(
        role=AgentRole.ENTRY_OPTIMIZER,
        max_tokens=768,
        timeout_s=4.0,    # Fast for entry timing decisions
        required=False,
    ),
    AgentRole.EXIT_ADVISOR: AgentConfig(
        role=AgentRole.EXIT_ADVISOR,
        max_tokens=1024,
        timeout_s=5.0,
        required=False,
    ),
    AgentRole.RISK_GUARD: AgentConfig(
        role=AgentRole.RISK_GUARD,
        max_tokens=768,
        timeout_s=4.0,    # Safety gates must respond fast
        required=False,
    ),
    AgentRole.AGENT_ROUTER: AgentConfig(
        role=AgentRole.AGENT_ROUTER,
        max_tokens=1024,
        timeout_s=5.0,
        required=False,
    ),
    AgentRole.CONSENSUS_BUILDER: AgentConfig(
        role=AgentRole.CONSENSUS_BUILDER,
        max_tokens=800,   # Synthesizes all agent outputs into final decision
        timeout_s=10.0,
        required=False,
    ),
    AgentRole.OVERRIDE: AgentConfig(
        role=AgentRole.OVERRIDE,
        max_tokens=1024,   # Decisive reasoning, not verbose
        timeout_s=25.0,    # Sonnet needs time, but override is rare
        required=False,
    ),
}
