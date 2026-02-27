"""
Multi-LLM Provider Abstraction.

Supports multiple LLM backends and persona variants:
- primary: The main LLM (Claude by default)
- secondary: Backup LLM (different model or provider)
- persona variants: Same LLM with different system prompts

Each provider returns standardized LLMDecision-compatible output.
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

logger = logging.getLogger("bot.llm.providers")


@dataclass
class LLMProvider:
    """Configuration for an LLM provider."""
    name: str                    # "primary", "secondary", "persona_risk_off"
    model: str = ""              # "claude-sonnet-4-5-20250929", etc.
    api_key_env: str = ""        # env var name for API key
    system_prompt_override: Optional[str] = None  # persona prompt
    weight: float = 1.0          # Voting weight in ensemble
    enabled: bool = True
    max_retries: int = 2
    timeout_s: int = 30

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "")


# ── Persona Definitions ──────────────────────────────────────

PERSONAS = {
    "risk_off": {
        "description": "Conservative persona: more vetoes, smaller sizes",
        "prompt_modifier": (
            "You are in CONSERVATIVE mode. Prioritize capital preservation. "
            "Veto marginal setups aggressively. Use size_multiplier <= 0.8. "
            "Only proceed on the clearest setups with strong regime alignment."
        ),
        "weight": 0.8,
    },
    "risk_on": {
        "description": "Aggressive persona: more proceed, larger sizes in strong regimes",
        "prompt_modifier": (
            "You are in AGGRESSIVE mode. Capitalize on strong trends. "
            "Be willing to proceed on moderate setups in trending regimes. "
            "Use size_multiplier >= 1.0. Only veto clearly bad setups."
        ),
        "weight": 1.2,
    },
    "scalper": {
        "description": "Short-term persona: tight SL/TP, quick exits",
        "prompt_modifier": (
            "You are in SCALP mode. Focus on short-term opportunities. "
            "Prefer tight stop losses and quick exits. Veto anything that "
            "requires extended holding time. Recommend tighter SL via entry_adjustment."
        ),
        "weight": 0.6,
    },
    "swing": {
        "description": "Long-term persona: wider SL/TP, fewer trades, let winners run",
        "prompt_modifier": (
            "You are in SWING mode. Focus on major trend-following opportunities. "
            "Be very selective -- veto most setups. Only proceed on high-confidence "
            "trend trades. Recommend wider targets via entry_adjustment."
        ),
        "weight": 0.7,
    },
}


def get_provider_config() -> List[LLMProvider]:
    """Build provider configuration from environment."""
    providers = []

    # Primary (always present if LLM is enabled)
    primary_key = os.getenv("ANTHROPIC_API_KEY", "")
    if primary_key:
        providers.append(LLMProvider(
            name="primary",
            model=os.getenv("LLM_MODEL", "claude-sonnet-4-5-20250929"),
            api_key_env="ANTHROPIC_API_KEY",
            weight=1.0,
        ))

    # Secondary (optional backup)
    secondary_key = os.getenv("SECONDARY_LLM_API_KEY", "")
    if secondary_key:
        providers.append(LLMProvider(
            name="secondary",
            model=os.getenv("SECONDARY_LLM_MODEL", ""),
            api_key_env="SECONDARY_LLM_API_KEY",
            weight=0.8,
        ))

    return providers


def get_active_personas() -> List[str]:
    """Get list of active persona names from environment.

    LLM_PERSONAS=risk_off,swing -> returns ["risk_off", "swing"]
    """
    raw = os.getenv("LLM_PERSONAS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip() in PERSONAS]
