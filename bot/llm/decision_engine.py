"""
LLM Decision Engine: the main orchestrator.

This is the ONLY entry point the Python bot calls.
Everything else in this module is internal.

Flow:
  1. Check autonomy mode (OFF -> return immediately)
  2. Check throttle (too soon since last call -> return cached)
  3. Load memory summary
  4. Build compressed snapshot
  5. Call Claude API
  6. Parse JSON response
  7. Validate against schema
  8. Risk gate
  9. Apply memory update
  10. Log decision to audit trail
  11. Return decision or None + reason

The bot receives a DecisionResult and decides how to use it
based on the current LLMMode.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from llm.client import call_llm, get_usage_stats
from llm.system_prompt import LLM_SYSTEM_PROMPT, LLM_SYSTEM_PROMPT_COMPACT
from llm.decision_types import (
    LLMDecision,
    MarketSnapshot,
    GlobalContext,
    LLMInputSnapshot,
)
from llm.snapshot_builder import (
    build_snapshot,
    snapshot_to_json,
    should_call_llm as should_call_throttle,
    mark_called,
)
from llm.memory_store import get_memory_summary, apply_memory_update, load_memory
from llm.validation import validate_and_parse
from llm.risk_gating import gate_decision, RiskContext, GatedResult
from llm.autonomy import LLMMode, should_call_llm, get_llm_mode
from llm.validator import validate_schema, validate_semantics, validate_and_sanitize
from llm.recovery import handle_validation_error, should_disable_llm_temporarily
from llm.normalizers import normalize_llm_output, decision_from_normalized_dict
from llm.autonomy_router import apply_autonomy_mode

logger = logging.getLogger("bot.llm.engine")

# ── Audit log ────────────────────────────────────────────────────

_AUDIT_DIR = os.path.join("data", "llm")
_AUDIT_PATH = os.path.join(_AUDIT_DIR, "decisions.jsonl")


def _log_audit(entry: dict):
    """Append a decision record to the JSONL audit log."""
    os.makedirs(_AUDIT_DIR, exist_ok=True)
    try:
        with open(_AUDIT_PATH, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except IOError as e:
        logger.warning(f"[LLM-AUDIT] Failed to write: {e}")


# ── Cached decision ──────────────────────────────────────────────

_cached_decision: Optional[LLMDecision] = None
_cached_at: float = 0.0
_CACHE_TTL = 300  # 5 minutes


def get_cached_decision() -> Optional[LLMDecision]:
    """Return the most recent LLM decision if still fresh."""
    if _cached_decision and (time.time() - _cached_at) < _CACHE_TTL:
        return _cached_decision
    return None


# ── Main entry point ─────────────────────────────────────────────

@dataclass
class DecisionResult:
    """What the bot receives from the LLM engine."""
    decision: Optional[LLMDecision]
    reason: str                    # "success", "throttled", "off", parse/validation/gate reason
    source: str                    # "llm", "cache", "none"
    usage: dict = None             # API token usage stats
    is_veto: bool = False          # True when LLM vetoed a trade (action=flat in VETO_ONLY+)
    original_action: str = ""      # Pre-mode-constraint action (e.g. "flip" before downgrade)

    def __post_init__(self):
        if self.usage is None:
            self.usage = {}


def get_trading_decision(
    markets: List[MarketSnapshot],
    global_context: GlobalContext,
    risk_context: RiskContext,
    active_positions: Optional[List[Dict[str, Any]]] = None,
    mode: Optional[LLMMode] = None,
    use_compact_prompt: bool = False,
    trigger_reason: str = "",
    trigger_context: str = "",
    event_triggered: bool = False,
) -> DecisionResult:
    """Main entry point: get a trading decision from the LLM meta-brain.

    Args:
        markets: List of MarketSnapshot from the bot's data pipeline
        global_context: Cross-market context
        risk_context: Current risk state
        active_positions: List of open position dicts (symbol, side, entry, unrealized_pnl)
        mode: Override LLM mode (default: read from env)
        use_compact_prompt: Use shorter prompt to save tokens
        trigger_reason: Why the LLM was called (e.g. "pre-trade validation")
        trigger_context: Details about the trigger event
        event_triggered: If True, bypass periodic throttle (event cooldown is
                         already enforced by TriggerAccumulator)

    Returns:
        DecisionResult with decision (or None) + reason + source
    """
    global _cached_decision, _cached_at

    # Step 0: Check mode
    if mode is None:
        mode = get_llm_mode()

    if not should_call_llm(mode):
        return DecisionResult(decision=None, reason="off", source="none")

    # Step 1: Build snapshot
    memory_summary = get_memory_summary()
    snapshot = build_snapshot(
        markets=markets,
        global_context=global_context,
        memory_summary=memory_summary,
        active_positions=active_positions,
        trigger_reason=trigger_reason,
        trigger_context=trigger_context,
    )

    # Step 2: Check throttle (event-triggered calls bypass periodic throttle)
    if not event_triggered and not should_call_throttle(snapshot):
        cached = get_cached_decision()
        if cached:
            return DecisionResult(
                decision=cached, reason="throttled", source="cache"
            )
        return DecisionResult(decision=None, reason="throttled_no_cache", source="none")

    # Step 3: Serialize snapshot
    snapshot_json = snapshot_to_json(snapshot)

    # Step 4: Call Claude
    prompt = LLM_SYSTEM_PROMPT_COMPACT if use_compact_prompt else LLM_SYSTEM_PROMPT
    raw_text, usage = call_llm(
        system_prompt=prompt,
        snapshot_json=snapshot_json,
    )

    if raw_text is None:
        _log_audit({
            "ts": time.time(),
            "action": "api_error",
            "error": usage.get("error", "unknown"),
        })
        return DecisionResult(
            decision=None,
            reason=f"api_error: {usage.get('error', 'unknown')}",
            source="none",
            usage=usage,
        )

    # Step 5: Validate + Normalize + Sanitize
    decision, val_err = validate_and_parse(raw_text)

    if val_err:
        # Parse failed: try recovery
        recoverable, _, recovery_reason = handle_validation_error(val_err, raw_text)
        _log_audit({
            "ts": time.time(),
            "action": "validation_failed",
            "error": val_err,
            "recoverable": recoverable,
            "raw": raw_text[:500],
        })
        return DecisionResult(
            decision=None,
            reason=f"validation_error: {val_err}",
            source="none",
            usage=usage,
        )

    # Step 5.5: Additional validation + sanitization (strict)
    try:
        decision, sanitize_err = validate_and_sanitize(decision)
        if sanitize_err:
            logger.warning(f"[LLM-ENGINE] Sanitization failed: {sanitize_err}")
            _log_audit({
                "ts": time.time(),
                "action": "sanitization_failed",
                "error": sanitize_err,
            })
            return DecisionResult(
                decision=None,
                reason=f"sanitization_error: {sanitize_err}",
                source="none",
                usage=usage,
            )
    except Exception as e:
        logger.error(f"[LLM-ENGINE] Sanitization exception: {e}")
        return DecisionResult(
            decision=None,
            reason=f"sanitization_exception: {str(e)[:100]}",
            source="none",
            usage=usage,
        )

    # Step 5.5: Apply mode-specific constraints
    original_action = decision.action
    decision, mode_overrides = _apply_mode_constraints(decision, mode)

    # Step 6: Risk gate
    gated = gate_decision(decision, risk_context)

    # Step 7: Apply memory update (even if gated, memory is still valuable)
    apply_memory_update(
        decision.memory_update,
        symbol=trigger_context.split()[0] if trigger_context else "",
        regime=decision.regime,
    )

    # Step 8: Mark called (for throttle)
    mark_called(snapshot)

    # Step 9: Cache decision
    _cached_decision = decision if gated.allowed else None
    _cached_at = time.time()

    # Determine if this was a veto (LLM said flat for a trade candidate)
    is_veto = decision.action == "flat" and mode >= LLMMode.VETO_ONLY

    # Step 10: Audit log
    _log_audit({
        "ts": time.time(),
        "action": decision.action,
        "original_action": original_action,
        "confidence": decision.confidence,
        "regime": decision.regime,
        "size_multiplier": decision.size_multiplier,
        "entry_adjustment": decision.entry_adjustment,
        "allowed": gated.allowed,
        "gate_reason": gated.reason,
        "is_veto": is_veto,
        "mode_overrides": mode_overrides,
        "notes": decision.notes,
        "memory_update": decision.memory_update,
        "strategy_weights": decision.strategy_weights.to_dict(),
        "mode": mode.name,
        "trigger_reason": trigger_reason,
        "trigger_context": trigger_context,
        "usage": usage,
    })

    if gated.allowed:
        logger.info(
            f"[LLM-ENGINE] Decision: {decision.action} "
            f"conf={decision.confidence:.2f} regime={decision.regime} "
            f"size_mult={decision.size_multiplier:.2f} "
            f"mode={mode.name}"
            + (f" (was {original_action})" if original_action != decision.action else "")
        )
        return DecisionResult(
            decision=decision,
            reason="success",
            source="llm",
            usage=usage,
            is_veto=is_veto,
            original_action=original_action,
        )
    else:
        logger.info(
            f"[LLM-ENGINE] Gated: {decision.action} "
            f"conf={decision.confidence:.2f} reason={gated.reason}"
        )
        return DecisionResult(
            decision=None,
            reason=f"gated: {gated.reason}",
            source="none",
            usage=usage,
            is_veto=is_veto,
            original_action=original_action,
        )


def _apply_mode_constraints(
    decision: LLMDecision, mode: LLMMode
) -> tuple:
    """Enforce mode-specific constraints on the LLM decision.

    Returns (modified_decision, list_of_overrides_applied).

    VETO_ONLY: flip -> flat, size_multiplier -> 1.0, entry_adjustment -> None
    SIZING:    flip -> flat, entry_adjustment -> None (keep size_multiplier)
    DIRECTION: no constraints on action (keep everything)
    FULL:      no constraints
    """
    overrides = []

    if mode == LLMMode.VETO_ONLY:
        # VETO_ONLY: only proceed or flat allowed
        if decision.action == "flip":
            logger.info(
                f"[LLM-ENGINE] VETO_ONLY: downgrading flip -> flat "
                f"(flips not allowed in VETO_ONLY mode)"
            )
            decision.action = "flat"
            overrides.append("flip_to_flat")
        if decision.size_multiplier != 1.0:
            overrides.append(f"size_mult_{decision.size_multiplier:.2f}_to_1.0")
            decision.size_multiplier = 1.0
        if decision.entry_adjustment is not None:
            overrides.append("entry_adj_cleared")
            decision.entry_adjustment = None

    elif mode == LLMMode.SIZING:
        # SIZING: no flips, but size_multiplier is kept
        if decision.action == "flip":
            logger.info(
                f"[LLM-ENGINE] SIZING: downgrading flip -> flat "
                f"(flips not allowed in SIZING mode)"
            )
            decision.action = "flat"
            overrides.append("flip_to_flat")
        if decision.entry_adjustment is not None:
            overrides.append("entry_adj_cleared")
            decision.entry_adjustment = None

    # DIRECTION and FULL: no constraints
    return decision, overrides
