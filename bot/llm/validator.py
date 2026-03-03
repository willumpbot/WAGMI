"""
LLM Output Validator: Strict schema enforcement + sanity checking.

This is the firewall between "LLM said X" and "bot does X".
Rejects any invalid, incomplete, or nonsensical output.

Two-stage validation:
1. Schema validation (types, ranges, required fields)
2. Semantic validation (business logic rules)
"""

import logging
from typing import Optional, Tuple

from llm.decision_types import LLMDecision, Regime, EXTENDED_WEIGHT_KEYS

logger = logging.getLogger("bot.llm.validator")


# ── Schema Validation ─────────────────────────────────────────

_VALID_ACTIONS = {"proceed", "flat", "flip"}
_VALID_REGIMES = {r.value for r in Regime}
_VALID_ENTRY_ADJUSTMENTS = {
    "market now",
    "wait for pullback",
    "enter only if reclaim",
    "enter only if sweep of liquidity",
    "enter only if btc confirms",
    "scale in",
    None,
}


def validate_schema(decision: LLMDecision) -> Tuple[bool, Optional[str]]:
    """Validate LLMDecision against strict schema.

    Returns (is_valid, error_reason).
    """
    # Action
    if decision.action not in _VALID_ACTIONS:
        return False, f"Invalid action: {decision.action!r} (must be proceed/flat/flip)"

    # Confidence
    if not isinstance(decision.confidence, (int, float)):
        return False, f"Confidence not a number: {decision.confidence!r}"
    if decision.confidence < 0.0 or decision.confidence > 1.0:
        return False, f"Confidence out of range: {decision.confidence}"

    # Regime
    if decision.regime not in _VALID_REGIMES:
        return False, f"Invalid regime: {decision.regime!r}"

    # Size multiplier
    if not isinstance(decision.size_multiplier, (int, float)):
        return False, f"size_multiplier not a number: {decision.size_multiplier!r}"
    if decision.size_multiplier < 0.0 or decision.size_multiplier > 2.0:
        return False, f"size_multiplier out of range: {decision.size_multiplier}"

    # Entry adjustment
    if decision.entry_adjustment is not None:
        if not isinstance(decision.entry_adjustment, str):
            return False, f"entry_adjustment must be string or null"
        if decision.entry_adjustment not in _VALID_ENTRY_ADJUSTMENTS:
            return False, f"Unknown entry_adjustment: {decision.entry_adjustment!r}"

    # Memory update
    if decision.memory_update is not None:
        if not isinstance(decision.memory_update, str):
            return False, f"memory_update must be string or null"
        if len(decision.memory_update) > 200:
            return False, f"memory_update too long (>{200})"

    # Notes
    if not isinstance(decision.notes, str):
        return False, f"notes must be string"
    if len(decision.notes) > 1000:
        return False, f"notes too long (>{1000})"

    # Strategy weights (optional)
    sw = decision.strategy_weights
    if sw:
        total = sum(sw.to_dict().values())
        if total < 0.1 and decision.action != "flat":
            return False, f"strategy_weights sum too low: {total}"
        for key in EXTENDED_WEIGHT_KEYS:
            val = getattr(sw, key, 0.5)
            if not isinstance(val, (int, float)):
                return False, f"strategy_weights.{key} not a number"
            if val < 0.0 or val > 1.0:
                return False, f"strategy_weights.{key} out of range"

    return True, None


# ── Semantic Validation (Business Rules) ──────────────────────


def validate_semantics(
    decision: LLMDecision, mode_name: str = ""
) -> Tuple[bool, Optional[str]]:
    """Validate LLMDecision against business logic rules.

    These rules catch insane decisions that are technically valid JSON.

    Returns (is_valid, error_reason).
    """
    # Rule 1: flat is always OK
    if decision.action == "flat":
        return True, None

    # Rule 2: flip requires high confidence
    if decision.action == "flip" and decision.confidence < 0.65:
        return False, f"flip requires confidence >= 0.65 (got {decision.confidence})"

    # Rule 3: proceed/flip in panic regime requires very high confidence
    if decision.regime == Regime.PANIC.value:
        if decision.action != "flat" and decision.confidence < 0.80:
            return False, f"panic regime requires confidence >= 0.80 (got {decision.confidence})"

    # Rule 4: low_liquidity regime should always be flat
    if decision.regime == Regime.LOW_LIQUIDITY.value and decision.action != "flat":
        return False, f"low_liquidity regime must be flat"

    # Rule 5: unknown regime should be conservative
    if decision.regime == Regime.UNKNOWN.value and decision.confidence > 0.6:
        return False, f"unknown regime should not have confidence > 0.6"

    # Rule 6: size_multiplier should align with regime
    if decision.action != "flat":
        if decision.regime == Regime.HIGH_VOLATILITY.value and decision.size_multiplier > 1.0:
            return False, f"high_volatility regime should have size_multiplier <= 1.0"
        if decision.regime == Regime.LOW_LIQUIDITY.value and decision.size_multiplier > 0.5:
            return False, f"low_liquidity regime should have size_multiplier <= 0.5"
        if decision.regime == Regime.PANIC.value and decision.size_multiplier > 0.8:
            return False, f"panic regime should have size_multiplier <= 0.8"

    # Rule 7: strategy weights should support the action
    sw = decision.strategy_weights
    if sw:
        # If proceed/flip, at least one strategy should have weight > 0.5
        max_weight = max(sw.to_dict().values())
        if decision.action != "flat" and max_weight < 0.4:
            return False, f"proceed/flip requires at least one strategy weight >= 0.4"

    return True, None


def validate_and_sanitize(decision: LLMDecision) -> Tuple[LLMDecision, Optional[str]]:
    """Full validation + sanitization pipeline.

    Returns (decision, error_reason).
    If validation fails, returns (None, error_string).
    """
    # Step 1: Sanitize first (clamp/truncate fixable values)
    decision = _sanitize(decision)

    # Step 2: Schema validation (catches structural issues)
    valid, schema_err = validate_schema(decision)
    if not valid:
        logger.warning(f"[LLM-VALIDATOR] Schema validation failed: {schema_err}")
        return None, schema_err

    # Step 3: Semantic validation (catches business logic violations)
    valid, semantic_err = validate_semantics(decision)
    if not valid:
        logger.warning(f"[LLM-VALIDATOR] Semantic validation failed: {semantic_err}")
        return None, semantic_err

    logger.info(
        f"[LLM-VALIDATOR] PASS: {decision.action} "
        f"conf={decision.confidence:.2f} regime={decision.regime} "
        f"size_mult={decision.size_multiplier:.2f}"
    )
    return decision, None


def _sanitize(decision: LLMDecision) -> LLMDecision:
    """Clamp and normalize values to safe ranges.

    Does NOT reject — only adjusts to reasonable bounds.
    """
    # Clamp confidence
    decision.confidence = max(0.0, min(1.0, decision.confidence))

    # Clamp size_multiplier
    decision.size_multiplier = max(0.0, min(2.0, decision.size_multiplier))

    # Truncate notes/memory
    if decision.notes and len(decision.notes) > 1000:
        decision.notes = decision.notes[:1000]
    if decision.memory_update and len(decision.memory_update) > 200:
        decision.memory_update = decision.memory_update[:200]

    return decision
