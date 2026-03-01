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

_VALID_ACTIONS = {"proceed", "flat", "flip"}
_VALID_REGIMES = {r.value for r in Regime}

# ── Short-key expansion maps ────────────────────────────────────
# The LLM outputs compact keys to save tokens. We expand them here
# so the rest of the pipeline uses full names.

_ACTION_ALIASES = {"go": "proceed", "skip": "flat"}  # "flip" stays "flip"

_TOP_KEY_MAP = {
    "a": "action",
    "c": "confidence",
    "rg": "regime",
    "sz": "size_multiplier",
    "ea": "entry_adjustment",
    "sw": "strategy_weights",
    "mu": "memory_update",
    "n": "notes",
}

_WEIGHT_KEY_MAP = {
    "rt": "regime_trend",
    "mc": "monte_carlo_zones",
    "cs": "confidence_scorer",
    "mq": "multi_tier_quality",
    "fr": "funding_rate",
    "oi": "open_interest",
    "vm": "volume_momentum",
    "ca": "cross_asset",
}


def _expand_short_keys(raw: dict) -> dict:
    """Expand compact LLM output keys to full names.

    Accepts both short keys (a, c, rg, sz) and full keys (action, confidence, regime).
    Short keys take precedence if both are present.
    """
    out = {}

    # Expand top-level keys
    for key, val in raw.items():
        full_key = _TOP_KEY_MAP.get(key, key)
        out[full_key] = val

    # Expand action aliases (go -> proceed, skip -> flat)
    if "action" in out and out["action"] in _ACTION_ALIASES:
        out["action"] = _ACTION_ALIASES[out["action"]]

    # Expand strategy_weights sub-keys
    sw = out.get("strategy_weights")
    if isinstance(sw, dict):
        expanded_sw = {}
        for key, val in sw.items():
            full_key = _WEIGHT_KEY_MAP.get(key, key)
            expanded_sw[full_key] = val
        out["strategy_weights"] = expanded_sw

    return out


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
        return False, f"Invalid action: {action!r} (must be proceed/flat/flip)"

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

    # strategy_weights (optional - LLM may omit in veto-only mode)
    sw = dec.get("strategy_weights")
    if sw is not None:
        if not isinstance(sw, dict):
            return False, f"strategy_weights not a dict: {type(sw).__name__}"
        for key in EXTENDED_WEIGHT_KEYS:
            val = sw.get(key)
            if val is None:
                continue
            if not isinstance(val, (int, float)):
                return False, f"strategy_weights.{key} not a number: {val!r}"
            if val < 0.0 or val > 1.0:
                return False, f"strategy_weights.{key} out of range: {val}"

    # size_multiplier (optional, 0.0-2.0)
    sm = dec.get("size_multiplier")
    if sm is not None:
        if not isinstance(sm, (int, float)):
            return False, f"size_multiplier not a number: {sm!r}"
        if sm < 0.0 or sm > 2.0:
            return False, f"size_multiplier out of range: {sm} (must be 0.0-2.0)"

    # entry_adjustment (optional string)
    ea = dec.get("entry_adjustment")
    if ea is not None and not isinstance(ea, str):
        return False, f"entry_adjustment must be string or null, got {type(ea).__name__}"

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

    # Step 1.5: Expand compact keys (a->action, go->proceed, etc.)
    parsed = _expand_short_keys(parsed)

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
        f"conf={decision.confidence:.2f} regime={decision.regime} "
        f"size_mult={decision.size_multiplier:.2f}"
    )
    return decision, None
