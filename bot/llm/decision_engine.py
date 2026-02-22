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
) -> DecisionResult:
    """Main entry point: get a trading decision from the LLM meta-brain.

    Args:
        markets: List of MarketSnapshot from the bot's data pipeline
        global_context: Cross-market context
        risk_context: Current risk state
        active_positions: List of open position dicts (symbol, side, entry, unrealized_pnl)
        mode: Override LLM mode (default: read from env)
        use_compact_prompt: Use shorter prompt to save tokens

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
    )

    # Step 2: Check throttle
    if not should_call_throttle(snapshot):
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

    # Step 5: Validate
    decision, val_err = validate_and_parse(raw_text)

    if val_err:
        _log_audit({
            "ts": time.time(),
            "action": "validation_failed",
            "error": val_err,
            "raw": raw_text[:500],
        })
        return DecisionResult(
            decision=None,
            reason=f"validation: {val_err}",
            source="none",
            usage=usage,
        )

    # Step 6: Risk gate
    gated = gate_decision(decision, risk_context)

    # Step 7: Apply memory update (even if gated, memory is still valuable)
    apply_memory_update(decision.memory_update)

    # Step 8: Mark called (for throttle)
    mark_called(snapshot)

    # Step 9: Cache decision
    _cached_decision = decision if gated.allowed else None
    _cached_at = time.time()

    # Step 10: Audit log
    _log_audit({
        "ts": time.time(),
        "action": decision.action,
        "confidence": decision.confidence,
        "regime": decision.regime,
        "allowed": gated.allowed,
        "gate_reason": gated.reason,
        "notes": decision.notes,
        "memory_update": decision.memory_update,
        "strategy_weights": decision.strategy_weights.to_dict(),
        "mode": mode.name,
        "usage": usage,
    })

    if gated.allowed:
        logger.info(
            f"[LLM-ENGINE] Decision: {decision.action} "
            f"conf={decision.confidence:.2f} regime={decision.regime} "
            f"mode={mode.name}"
        )
        return DecisionResult(
            decision=decision,
            reason="success",
            source="llm",
            usage=usage,
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
        )
