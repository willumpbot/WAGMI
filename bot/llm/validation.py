"""
Strict validation of LLM output.

The LLM returns raw text. We parse it as JSON, then validate every field
against the LLMDecision schema. If ANY check fails, the decision is rejected
and the bot continues with its own logic.

This is the firewall between "LLM said X" and "bot does X".
"""

import json
import logging
import re
from typing import Optional, Tuple

from llm.decision_types import (
    LLMDecision,
    StrategyWeights,
    Regime,
    EXTENDED_WEIGHT_KEYS,
)

logger = logging.getLogger("bot.llm.validation")

_VALID_ACTIONS = {"long", "short", "flat"}
_VALID_REGIMES = {r.value for r in Regime}


def parse_llm_response(raw_text: str) -> Tuple[Optional[dict], Optional[str]]:
    """Parse raw LLM text into a dict.

    Handles common LLM output quirks:
      - Leading/trailing whitespace
      - Markdown code fences (```json ... ```)
      - Multiple JSON objects (takes first)

    Returns (parsed_dict, error_string).
    """
    if not raw_text or not raw_text.strip():
        return None, "Empty response"

    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        # Remove ```json or ``` at start and ``` at end
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"Expected object, got {type(parsed).__name__}"
    except json.JSONDecodeError as e:
        # Try to extract JSON from mixed text
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    return parsed, None
            except json.JSONDecodeError:
                pass
        return None, f"JSON parse error: {e}"


def is_valid_decision(dec: dict) -> Tuple[bool, Optional[str]]:
    """Validate a parsed dict against the LLMDecision schema.

    Returns (is_valid, error_reason).
    Every field is checked. Partial validity = rejection.
    """
    # action
    action = dec.get("action")
    if action not in _VALID_ACTIONS:
        return False, f"Invalid action: {action!r} (must be long/short/flat)"

    # confidence
    conf = dec.get("confidence")
    if not isinstance(conf, (int, float)):
        return False, f"Confidence not a number: {conf!r}"
    if conf < 0.0 or conf > 1.0:
        return False, f"Confidence out of range: {conf} (must be 0.0-1.0)"

    # regime
    regime = dec.get("regime")
    if regime not in _VALID_REGIMES:
        return False, f"Invalid regime: {regime!r} (must be one of {_VALID_REGIMES})"

    # strategy_weights
    sw = dec.get("strategy_weights")
    if not isinstance(sw, dict):
        return False, f"strategy_weights not a dict: {type(sw).__name__}"

    for key in EXTENDED_WEIGHT_KEYS:
        val = sw.get(key)
        if val is None:
            # Allow missing extended keys, default to 0
            continue
        if not isinstance(val, (int, float)):
            return False, f"strategy_weights.{key} not a number: {val!r}"
        if val < 0.0 or val > 1.0:
            return False, f"strategy_weights.{key} out of range: {val}"

    # memory_update
    mu = dec.get("memory_update")
    if mu is not None and not isinstance(mu, str):
        return False, f"memory_update must be string or null, got {type(mu).__name__}"

    # notes
    notes = dec.get("notes")
    if not isinstance(notes, str):
        return False, f"notes must be string, got {type(notes).__name__}"

    return True, None


def validate_and_parse(raw_text: str) -> Tuple[Optional[LLMDecision], Optional[str]]:
    """Full pipeline: parse raw text -> validate -> return LLMDecision or error.

    This is the main entry point for the validation layer.
    """
    # Step 1: Parse JSON
    parsed, parse_err = parse_llm_response(raw_text)
    if parse_err:
        logger.warning(f"[LLM-VAL] Parse failed: {parse_err}")
        return None, parse_err

    # Step 2: Validate schema
    valid, val_err = is_valid_decision(parsed)
    if not valid:
        logger.warning(f"[LLM-VAL] Validation failed: {val_err}")
        return None, val_err

    # Step 3: Construct typed decision
    try:
        decision = LLMDecision.from_dict(parsed)
    except Exception as e:
        logger.warning(f"[LLM-VAL] Construction failed: {e}")
        return None, f"Construction error: {e}"

    logger.info(
        f"[LLM-VAL] Valid decision: {decision.action} "
        f"conf={decision.confidence:.2f} regime={decision.regime}"
    )
    return decision, None
