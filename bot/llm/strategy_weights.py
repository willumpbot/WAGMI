"""
Strategy Weight Application: LLM influences ensemble weighting.

In FULL mode, the LLM can suggest per-strategy weights that modify
the ensemble's internal voting. This allows the LLM to express opinions
like "trust regime_trend more in this market" or "confidence_scorer
has been unreliable lately".

Weight rules:
- No strategy weight > 2.0 (max 2x boost)
- No strategy weight < 0.2 (min 0.2x, never fully disable)
- Weights are multiplicative on the ensemble's base weights
- Total weights normalized to sum=1.0 after multiplication
- Only applies in FULL mode (mode 5)

Integration:
  Called from multi_strategy_main before ensemble voting.
  LLM weights come from the LLMDecision.strategy_weights field.
"""

import logging
from typing import Dict, Optional

from llm.decision_types import StrategyWeights

logger = logging.getLogger("bot.llm.strategy_weights")

# Hard limits
_MIN_WEIGHT = 0.2
_MAX_WEIGHT = 2.0

# Default strategy names (must match ensemble)
_DEFAULT_STRATEGIES = [
    "regime_trend",
    "monte_carlo_zones",
    "confidence_scorer",
    "multi_tier_quality",
]


def clamp_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Clamp all weights to [MIN_WEIGHT, MAX_WEIGHT]."""
    clamped = {}
    for k, v in weights.items():
        if not isinstance(v, (int, float)):
            continue
        clamped[k] = max(_MIN_WEIGHT, min(float(v), _MAX_WEIGHT))
    return clamped


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalize weights to sum to 1.0."""
    total = sum(v for v in weights.values() if isinstance(v, (int, float)) and v > 0)
    if total <= 0:
        return weights
    return {k: v / total for k, v in weights.items()}


def apply_llm_weights(
    base_weights: Dict[str, float],
    llm_weights: Optional[StrategyWeights],
) -> Dict[str, float]:
    """Apply LLM strategy weights multiplicatively to base ensemble weights.

    Args:
        base_weights: Current ensemble weights (strategy_name -> weight)
        llm_weights: LLM-suggested weights (from StrategyWeights dataclass)

    Returns:
        New weights dict (normalized, clamped, sum=1.0)
    """
    if llm_weights is None:
        return base_weights

    llm_dict = llm_weights.to_dict()

    # Apply multiplicatively
    result = {}
    for strategy in _DEFAULT_STRATEGIES:
        base = base_weights.get(strategy, 0.25)
        llm_mult = llm_dict.get(strategy, 1.0)
        if not isinstance(llm_mult, (int, float)) or llm_mult <= 0:
            llm_mult = 1.0
        result[strategy] = base * llm_mult

    # Clamp
    result = clamp_weights(result)

    # Normalize
    result = normalize_weights(result)

    logger.info(
        f"[STRATEGY-WEIGHTS] Applied LLM weights: "
        + " | ".join(f"{k}={v:.2f}" for k, v in result.items())
    )

    return result


def validate_strategy_weights(weights: StrategyWeights) -> tuple:
    """Validate strategy weights from LLM output.

    Returns (ok, error_msg).
    """
    d = weights.to_dict()

    for k, v in d.items():
        if not isinstance(v, (int, float)):
            return False, f"Non-numeric weight for {k}: {v}"
        if v < 0:
            return False, f"Negative weight for {k}: {v}"
        if v > _MAX_WEIGHT:
            return False, f"Weight for {k} exceeds max ({v} > {_MAX_WEIGHT})"

    return True, ""
