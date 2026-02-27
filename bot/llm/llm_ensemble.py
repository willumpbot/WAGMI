"""
Multi-LLM Ensemble: Aggregate decisions from multiple LLMs/personas.

Voting strategies:
1. Majority vote on action (proceed/flat/flip)
2. Confidence-weighted average of size_multiplier
3. Consensus regime (most common)

Disagreement handling:
- Strong disagreement (50/50) -> default to more conservative (flat or smaller size)
- One model consistently underperforming -> down-weight over time

This module is OPTIONAL. If only one LLM is configured, it's a passthrough.
Enable via LLM_PERSONAS env var.
"""

import logging
from collections import Counter
from typing import Dict, List, Any, Optional

from llm.decision_types import LLMDecision, StrategyWeights

logger = logging.getLogger("bot.llm.llm_ensemble")


def aggregate_decisions(
    decisions: List[Dict[str, Any]],
) -> Optional[LLMDecision]:
    """Aggregate multiple LLM decisions into one.

    Each decision dict has:
      - decision: LLMDecision
      - weight: float (provider weight)
      - name: str (provider name)

    Returns the aggregated LLMDecision, or None if no valid decisions.
    """
    valid = [(d["decision"], d.get("weight", 1.0), d.get("name", "?"))
             for d in decisions
             if d.get("decision") is not None]

    if not valid:
        return None

    if len(valid) == 1:
        return valid[0][0]

    # Majority vote on action (weighted)
    action_votes: Dict[str, float] = {}
    for decision, weight, _ in valid:
        action = decision.action
        action_votes[action] = action_votes.get(action, 0) + weight

    # Resolve action
    best_action = max(action_votes, key=action_votes.get)
    total_weight = sum(action_votes.values())

    # Check for strong disagreement
    best_weight = action_votes[best_action]
    if best_weight / total_weight < 0.6:
        # No strong consensus -> default to more conservative
        if "flat" in action_votes:
            best_action = "flat"
            logger.info(
                f"[LLM-ENSEMBLE] Disagreement: defaulting to flat "
                f"(votes: {action_votes})"
            )
        else:
            # If no flat vote, reduce size
            best_action = "proceed"
            logger.info(
                f"[LLM-ENSEMBLE] Weak consensus on {best_action}: "
                f"will reduce size (votes: {action_votes})"
            )

    # Weighted average of size_multiplier
    total_w = sum(w for _, w, _ in valid)
    avg_size_mult = sum(
        d.size_multiplier * w for d, w, _ in valid
    ) / total_w if total_w > 0 else 1.0

    # If weak consensus, reduce size multiplier
    if best_weight / total_weight < 0.6:
        avg_size_mult = min(avg_size_mult, 0.7)

    # Weighted average confidence
    avg_confidence = sum(
        d.confidence * w for d, w, _ in valid
    ) / total_w if total_w > 0 else 0.5

    # Most common regime
    regime_counts = Counter(d.regime for d, _, _ in valid)
    consensus_regime = regime_counts.most_common(1)[0][0]

    # Combine notes
    all_notes = " | ".join(
        f"[{name}] {d.notes}" for d, _, name in valid if d.notes
    )

    # Combine memory updates
    memory_parts = [d.memory_update for d, _, _ in valid if d.memory_update]
    combined_memory = "; ".join(memory_parts) if memory_parts else None

    result = LLMDecision(
        action=best_action,
        confidence=avg_confidence,
        regime=consensus_regime,
        strategy_weights=valid[0][0].strategy_weights,  # Use primary's weights
        memory_update=combined_memory,
        notes=all_notes,
        size_multiplier=avg_size_mult,
        entry_adjustment=valid[0][0].entry_adjustment,  # Use primary's entry adj
    )

    logger.info(
        f"[LLM-ENSEMBLE] Aggregated {len(valid)} decisions: "
        f"action={best_action} conf={avg_confidence:.2f} "
        f"size_mult={avg_size_mult:.2f} regime={consensus_regime}"
    )

    return result


def get_disagreement_metrics(
    decisions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute disagreement metrics for logging/analysis."""
    valid = [d["decision"] for d in decisions if d.get("decision")]
    if len(valid) < 2:
        return {"disagreement": False}

    actions = [d.action for d in valid]
    unique_actions = set(actions)

    confidences = [d.confidence for d in valid]
    conf_spread = max(confidences) - min(confidences)

    regimes = [d.regime for d in valid]
    regime_agreement = len(set(regimes)) == 1

    return {
        "disagreement": len(unique_actions) > 1,
        "action_spread": list(unique_actions),
        "confidence_spread": round(conf_spread, 2),
        "regime_agreement": regime_agreement,
        "num_providers": len(valid),
    }
