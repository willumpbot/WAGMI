"""
LLM Usage Tier Configuration.

Provides predefined usage tiers that control:
  - Model selection (per-trigger: use Opus for high-value, Sonnet/Haiku for routine)
  - Rate limits (hourly/daily caps)
  - Cooldown overrides (per-trigger cooldown adjustments)
  - Estimated monthly cost

Tiers:
  CONSERVATIVE  - Minimize cost, Haiku only, tight throttle (~$18/mo)
  RECOMMENDED   - Good balance, Sonnet default, relaxed throttle (~$130/mo)
  AGGRESSIVE    - Max intelligence, Sonnet + Opus for critical, wide open (~$600/mo)
  UNLEASHED     - Full Opus everywhere, minimal throttle (~$1,400/mo)

The SMART tier (default for AGGRESSIVE) uses model routing:
  - Opus for: PRE_TRADE, REGIME_SHIFT, STRATEGY_DISAGREEMENT
  - Sonnet for: everything else

Usage:
    from llm.usage_tiers import get_active_tier, get_model_for_trigger
    tier = get_active_tier()
    model = get_model_for_trigger("PRE_TRADE")  # -> "claude-opus-4-20250115" (if aggressive)
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("bot.llm.usage_tiers")


# ── Model IDs ────────────────────────────────────────────────────

MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_OPUS = "claude-opus-4-20250115"

# Pricing per 1M tokens (input, output)
MODEL_PRICING = {
    MODEL_HAIKU: (1.0, 5.0),
    MODEL_SONNET: (3.0, 15.0),
    MODEL_OPUS: (15.0, 75.0),
}


# ── Trigger categories ───────────────────────────────────────────

# High-value triggers: the LLM's decision here directly affects PnL
HIGH_VALUE_TRIGGERS = {
    "PRE_TRADE",
    "pre-trade validation",
    "REGIME_SHIFT",
    "regime shift",
    "STRATEGY_DISAGREEMENT",
    "strategy disagreement",
    "PRE_CLOSE",
    "pre-close assessment",
}

# Medium-value triggers: informational, shapes future decisions
MEDIUM_VALUE_TRIGGERS = {
    "POSITION_CLOSED",
    "position closed",
    "HIGH_CONFIDENCE",
    "high-confidence signal",
    "STRATEGY_CONSENSUS",
    "strategy consensus",
    "CROSS_MARKET_DIVERGENCE",
    "cross-market divergence",
    "LEARNING_CYCLE",
    "learning cycle",
    "FUNDING_ALERT",
    "funding alert",
}

# Low-value triggers: routine, heartbeat
LOW_VALUE_TRIGGERS = {
    "MEMORY_EVENT",
    "memory-worthy event",
    "PERIODIC",
    "periodic update",
}


# ── Tier definitions ─────────────────────────────────────────────

@dataclass
class UsageTier:
    """Complete configuration for one usage tier."""
    name: str
    description: str

    # Default model for all triggers
    default_model: str = MODEL_HAIKU

    # Override model for specific trigger categories
    high_value_model: Optional[str] = None    # model for PRE_TRADE, REGIME_SHIFT etc.
    medium_value_model: Optional[str] = None  # model for POSITION_CLOSED etc.
    low_value_model: Optional[str] = None     # model for PERIODIC etc.

    # Rate limits
    max_calls_hour: int = 15
    max_calls_day: int = 150
    min_cooldown_s: int = 30

    # Per-trigger cooldown overrides (seconds)
    trigger_cooldowns: Dict[str, int] = field(default_factory=dict)

    # Snapshot throttle overrides
    min_snapshot_interval_s: int = 300   # 5 min default
    force_snapshot_interval_s: int = 900  # 15 min default

    # Max output tokens
    max_output_tokens: int = 600

    # Estimated monthly cost (USD)
    estimated_monthly_cost: float = 0.0

    def get_model_for_trigger(self, trigger_reason: str) -> str:
        """Return the best model for a given trigger type."""
        trigger_upper = trigger_reason.upper().replace(" ", "_").replace("-", "_")

        if trigger_reason in HIGH_VALUE_TRIGGERS or trigger_upper in {
            "PRE_TRADE", "REGIME_SHIFT", "STRATEGY_DISAGREEMENT", "PRE_CLOSE"
        }:
            return self.high_value_model or self.default_model

        if trigger_reason in MEDIUM_VALUE_TRIGGERS or trigger_upper in {
            "POSITION_CLOSED", "HIGH_CONFIDENCE", "STRATEGY_CONSENSUS",
            "CROSS_MARKET_DIVERGENCE",
        }:
            return self.medium_value_model or self.default_model

        if trigger_reason in LOW_VALUE_TRIGGERS or trigger_upper in {
            "MEMORY_EVENT", "PERIODIC",
        }:
            return self.low_value_model or self.default_model

        return self.default_model


# ── Predefined tiers ─────────────────────────────────────────────

TIER_CONSERVATIVE = UsageTier(
    name="CONSERVATIVE",
    description="Minimize cost. Haiku only, tight throttle. Good for testing.",
    default_model=MODEL_HAIKU,
    max_calls_hour=15,
    max_calls_day=150,
    min_cooldown_s=30,
    min_snapshot_interval_s=300,
    force_snapshot_interval_s=900,
    max_output_tokens=500,
    estimated_monthly_cost=18.0,
)

TIER_RECOMMENDED = UsageTier(
    name="RECOMMENDED",
    description="Balanced cost/intelligence. Sonnet default, relaxed throttle.",
    default_model=MODEL_SONNET,
    max_calls_hour=30,
    max_calls_day=400,
    min_cooldown_s=20,
    min_snapshot_interval_s=180,
    force_snapshot_interval_s=600,
    max_output_tokens=600,
    estimated_monthly_cost=130.0,
)

TIER_AGGRESSIVE = UsageTier(
    name="AGGRESSIVE",
    description="Smart model routing. Opus for critical decisions, Sonnet for routine. Tuned for maximum learning velocity.",
    default_model=MODEL_SONNET,
    high_value_model=MODEL_OPUS,
    medium_value_model=MODEL_SONNET,
    low_value_model=MODEL_SONNET,
    max_calls_hour=60,         # Up from 50 — more learning opportunities
    max_calls_day=1000,        # Up from 800 — full day of aggressive learning
    min_cooldown_s=10,         # Down from 15 — faster response to events
    trigger_cooldowns={
        "PRE_TRADE": 10,       # Down from 15 — never miss a trade evaluation
        "PRE_CLOSE": 10,       # Down from 15 — evaluate exits aggressively
        "REGIME_SHIFT": 20,    # Down from 30 — regime awareness is critical
        "HIGH_CONFIDENCE": 20, # Down from 30 — act on high-conf signals fast
        "STRATEGY_CONSENSUS": 20,   # Down from 30
        "STRATEGY_DISAGREEMENT": 20, # Down from 30 — disagreements need fast resolution
        "CROSS_MARKET_DIVERGENCE": 45, # Down from 60
        "MEMORY_EVENT": 90,    # Down from 120 — learn faster from events
        "PERIODIC": 120,       # Down from 180 — more frequent check-ins
    },
    min_snapshot_interval_s=90,  # Down from 120 — tighter feedback loop
    force_snapshot_interval_s=240,  # Down from 300 — more frequent forced updates
    max_output_tokens=1000,    # Up from 800 — richer reasoning and memory updates
    estimated_monthly_cost=750.0,
)

TIER_UNLEASHED = UsageTier(
    name="UNLEASHED",
    description="Full Opus everywhere. Maximum intelligence, minimal throttle.",
    default_model=MODEL_OPUS,
    high_value_model=MODEL_OPUS,
    medium_value_model=MODEL_OPUS,
    low_value_model=MODEL_SONNET,  # Even unleashed, PERIODIC doesn't need Opus
    max_calls_hour=60,
    max_calls_day=1200,
    min_cooldown_s=10,
    trigger_cooldowns={
        "PRE_TRADE": 10,
        "PRE_CLOSE": 10,
        "REGIME_SHIFT": 20,
        "HIGH_CONFIDENCE": 20,
        "STRATEGY_CONSENSUS": 20,
        "STRATEGY_DISAGREEMENT": 20,
        "CROSS_MARKET_DIVERGENCE": 45,
        "MEMORY_EVENT": 60,
        "PERIODIC": 120,
    },
    min_snapshot_interval_s=60,
    force_snapshot_interval_s=180,
    max_output_tokens=1000,
    estimated_monthly_cost=1400.0,
)


TIERS = {
    "CONSERVATIVE": TIER_CONSERVATIVE,
    "RECOMMENDED": TIER_RECOMMENDED,
    "AGGRESSIVE": TIER_AGGRESSIVE,
    "UNLEASHED": TIER_UNLEASHED,
}


# ── Active tier accessor ─────────────────────────────────────────

_active_tier: Optional[UsageTier] = None


def get_active_tier() -> UsageTier:
    """Get the currently active usage tier.

    Reads from LLM_USAGE_TIER env var. Defaults to RECOMMENDED.
    """
    global _active_tier
    if _active_tier is not None:
        return _active_tier

    tier_name = os.getenv("LLM_USAGE_TIER", "RECOMMENDED").upper()
    _active_tier = TIERS.get(tier_name, TIER_RECOMMENDED)

    if tier_name not in TIERS:
        logger.warning(
            f"Unknown LLM_USAGE_TIER={tier_name!r}, falling back to RECOMMENDED. "
            f"Valid tiers: {', '.join(TIERS.keys())}"
        )

    logger.info(
        f"[LLM] Usage tier: {_active_tier.name} — "
        f"{_active_tier.max_calls_hour}/hr, {_active_tier.max_calls_day}/day, "
        f"est. ${_active_tier.estimated_monthly_cost:.0f}/mo"
    )
    return _active_tier


def get_model_for_trigger(trigger_reason: str) -> str:
    """Convenience: get the model to use for a given trigger."""
    return get_active_tier().get_model_for_trigger(trigger_reason)


def format_tier_comparison() -> str:
    """Format a comparison table of all available tiers."""
    lines = []
    lines.append("=" * 80)
    lines.append("  LLM USAGE TIERS")
    lines.append("=" * 80)
    lines.append("")
    lines.append(
        f"  {'Tier':<15} {'Model':<18} {'Calls/hr':>9} {'Calls/day':>10} "
        f"{'Cooldown':>9} {'Est $/mo':>9}"
    )
    lines.append("  " + "-" * 72)

    current_tier = os.getenv("LLM_USAGE_TIER", "RECOMMENDED").upper()

    for name, tier in TIERS.items():
        marker = " >> " if name == current_tier else "    "
        model_short = (
            tier.default_model.split("-")[1]
            if "-" in tier.default_model
            else tier.default_model
        )
        lines.append(
            f"{marker}{name:<15} {model_short:<18} {tier.max_calls_hour:>9} "
            f"{tier.max_calls_day:>10} {tier.min_cooldown_s:>8}s "
            f"${tier.estimated_monthly_cost:>8.0f}"
        )

    active = TIERS.get(current_tier, TIER_RECOMMENDED)
    lines.append("")
    lines.append(f"  Active: {active.name} — {active.description}")

    if active.high_value_model and active.high_value_model != active.default_model:
        lines.append(f"  Smart routing: Opus for critical, Sonnet for routine")

    lines.append("")
    lines.append(f"  Set via: LLM_USAGE_TIER=AGGRESSIVE  (in .env)")
    lines.append("=" * 80)

    return "\n".join(lines)
