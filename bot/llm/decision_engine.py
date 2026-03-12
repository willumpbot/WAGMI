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
from collections import deque
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

# Usage tier system: smart model routing by trigger importance
try:
    from llm.usage_tiers import get_active_tier
    _HAS_USAGE_TIERS = True
except ImportError:
    _HAS_USAGE_TIERS = False

# Cost tracker: budget-aware model selection
try:
    from llm.cost_tracker import get_cost_tracker
    _HAS_COST_TRACKER = True
except ImportError:
    _HAS_COST_TRACKER = False

# Veto tracker: counterfactual validation (via growth orchestrator)
try:
    from llm.growth.orchestrator import get_growth_orchestrator
    _HAS_VETO_TRACKER = True
except ImportError:
    _HAS_VETO_TRACKER = False

# Multi-LLM ensemble: aggregate decisions from multiple models
try:
    from llm.llm_ensemble import aggregate_decisions, get_disagreement_metrics
    _HAS_LLM_ENSEMBLE = True
except ImportError:
    _HAS_LLM_ENSEMBLE = False

# Multi-Agent system: specialist agents for focused decision-making
try:
    from llm.agents.coordinator import (
        is_multi_agent_enabled,
        get_coordinator as get_agent_coordinator,
    )
    _HAS_MULTI_AGENT = True
except ImportError:
    _HAS_MULTI_AGENT = False

# High-priority triggers that warrant multi-LLM ensemble
_ENSEMBLE_TRIGGERS = {"pre_trade_veto", "regime shift", "high-confidence signal"}

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
_CACHE_TTL = 180  # 3 minutes (reduced from 5 for faster market response)

# Flip rate tracking: detect LLM overconfidence in direction changes
_flip_history: deque = deque(maxlen=20)
_FLIP_RATE_LIMIT = 0.30  # Reject flips if >30% of last 20 decisions are flips

# Recent decisions ring buffer: enables LLM consistency + self-awareness
_recent_decisions: deque = deque(maxlen=8)


_last_monolithic_regime: Optional[str] = None


def _record_monolithic_regime(regime: str, trigger: str = ""):
    """Record regime classification from monolithic LLM to deep memory.

    Only records on regime CHANGES to avoid flooding with identical entries.
    Multi-agent path handles this via learning_integration.py instead.
    """
    global _last_monolithic_regime
    if not regime or regime == "unknown":
        return
    if regime == _last_monolithic_regime:
        return  # No change — skip
    prev = _last_monolithic_regime or "unknown"
    _last_monolithic_regime = regime
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        dm.regime_history.record_transition(
            from_regime=prev,
            to_regime=regime,
            symbol="market",
            trigger=f"monolithic_llm: {trigger[:80]}",
            context={"source": "decision_engine"},
        )
        logger.debug(f"[LLM-ENGINE] Regime transition recorded: {prev} → {regime}")
    except Exception as e:
        logger.debug(f"[LLM-ENGINE] Regime history error: {e}")


def get_recent_decisions(n: int = 5) -> list:
    """Return last N decisions for snapshot consistency context."""
    return list(_recent_decisions)[-n:]


def get_cached_decision() -> Optional[LLMDecision]:
    """Return the most recent LLM decision if still fresh."""
    if _cached_decision and (time.time() - _cached_at) < _CACHE_TTL:
        return _cached_decision
    return None


def invalidate_cache(reason: str = ""):
    """Invalidate the cached decision (e.g., on circuit breaker or regime shift)."""
    global _cached_decision, _cached_at
    if _cached_decision:
        logger.info(f"[LLM-ENGINE] Cache invalidated: {reason}")
    _cached_decision = None
    _cached_at = 0.0


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

    # Step 3.1: Inject deep memory knowledge into monolithic snapshot
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        if dm:
            snap_data = json.loads(snapshot_json)
            # Inject key deep memory insights
            knowledge = {}
            try:
                dna_store = dm.trade_dna
                if dna_store:
                    effectiveness = dna_store.get_strategy_effectiveness()
                    if effectiveness:
                        knowledge["strategy_effectiveness"] = {
                            k: f"WR={v.get('win_rate', 0):.0%} n={v.get('count', 0)}"
                            for k, v in list(effectiveness.items())[:6]
                        }
                    failures = dna_store.get_failures(limit=3)
                    if failures:
                        knowledge["recent_failures"] = [
                            f.get("lesson", "")[:80] for f in failures if f.get("lesson")
                        ]
            except Exception:
                pass
            if knowledge:
                snap_data["deep_memory"] = knowledge
                snapshot_json = json.dumps(snap_data, separators=(",", ":"), default=str)
    except Exception:
        pass

    # Step 3.5: Multi-Agent path (if enabled, replaces monolithic LLM call)
    _multi_agent_active = (
        _HAS_MULTI_AGENT
        and is_multi_agent_enabled()
        and trigger_reason not in ("periodic update", "PERIODIC")  # Don't burn budget on heartbeats
    )
    if _multi_agent_active:
        try:
            coordinator = get_agent_coordinator()
            # Resolve model for trigger (used as fallback for agents without override)
            _ma_model = None
            if _HAS_USAGE_TIERS:
                try:
                    tier = get_active_tier()
                    _ma_model = tier.get_model_for_trigger(trigger_reason)
                except Exception:
                    pass

            # The snapshot_json is compact JSON — parse to dict for agents
            snapshot_data = json.loads(snapshot_json)
            decision = coordinator.get_trading_decision(
                snapshot_data=snapshot_data,
                trigger_reason=trigger_reason,
                model_for_trigger=_ma_model,
            )

            if decision is not None:
                usage = coordinator.get_stats()
                # Jump to Step 5.5 (mode constraints + gating)
                # by setting markers so the monolithic path is skipped
                logger.info(
                    f"[LLM-ENGINE] Multi-agent pipeline: action={decision.action} "
                    f"conf={decision.confidence:.2f} regime={decision.regime}"
                )
                # Record API cost
                if _HAS_COST_TRACKER:
                    try:
                        cost_tracker = get_cost_tracker()
                        cost_tracker.record_call(
                            input_tokens=usage.get("total_input_tokens", 0),
                            output_tokens=usage.get("total_output_tokens", 0),
                            model="multi-agent",
                        )
                    except Exception:
                        pass

                _log_audit({
                    "ts": time.time(),
                    "action": "multi_agent_decision",
                    "pipeline_action": decision.action,
                    "confidence": decision.confidence,
                    "regime": decision.regime,
                    "agent_stats": usage,
                })

                # Skip to post-decision processing (Step 5.4+)
                raw_text = "__multi_agent__"
                val_err = None
                _ensemble_enabled = False  # Don't also run ensemble
            else:
                logger.warning("[LLM-ENGINE] Multi-agent pipeline returned None, falling back to monolithic")
                _multi_agent_active = False
        except Exception as ma_err:
            logger.warning(f"[LLM-ENGINE] Multi-agent failed: {ma_err}, falling back to monolithic")
            _multi_agent_active = False

    # Step 4: Call Claude (with smart model routing if usage tiers are configured)
    prompt = LLM_SYSTEM_PROMPT_COMPACT if use_compact_prompt else LLM_SYSTEM_PROMPT

    # Resolve model: tier-based routing overrides default
    call_kwargs = {
        "system_prompt": prompt,
        "snapshot_json": snapshot_json,
    }
    if _HAS_USAGE_TIERS:
        try:
            tier = get_active_tier()
            routed_model = tier.get_model_for_trigger(trigger_reason)
            # Apply cost-aware downgrade if approaching budget
            if _HAS_COST_TRACKER:
                try:
                    cost_tracker = get_cost_tracker()
                    routed_model = cost_tracker.get_safe_model(routed_model, trigger_reason)
                except Exception as ce:
                    logger.debug(f"[LLM-ENGINE] Cost tracker check failed: {ce}")
            call_kwargs["model"] = routed_model
            call_kwargs["max_tokens"] = tier.max_output_tokens
            logger.debug(
                f"[LLM-ENGINE] Tier {tier.name}: using {routed_model} for trigger={trigger_reason}"
            )
        except Exception as e:
            logger.warning(f"[LLM-ENGINE] Tier routing failed: {e}, using default model")

    # ── Multi-LLM Ensemble: call additional models for high-priority triggers ──
    _ensemble_enabled = (
        _HAS_LLM_ENSEMBLE
        and os.getenv("LLM_ENSEMBLE_ENABLED", "").lower() in ("1", "true", "yes")
        and os.getenv("LLM_PERSONAS", "").strip()
        and trigger_reason in _ENSEMBLE_TRIGGERS
    )

    if _ensemble_enabled:
        # Parse personas: "opus:1.0,sonnet:0.8" -> list of (model, weight)
        _personas_str = os.getenv("LLM_PERSONAS", "")
        _persona_list = []
        for p in _personas_str.split(","):
            p = p.strip()
            if not p:
                continue
            if ":" in p:
                _pmodel, _pweight = p.split(":", 1)
                _persona_list.append((_pmodel.strip(), float(_pweight)))
            else:
                _persona_list.append((p.strip(), 1.0))

        if len(_persona_list) >= 2:
            # Call each model and collect decisions
            _ensemble_decisions = []
            _ensemble_total_usage = {"input_tokens": 0, "output_tokens": 0}
            for _pmodel, _pweight in _persona_list:
                try:
                    _p_kwargs = dict(call_kwargs)
                    _p_kwargs["model"] = _pmodel
                    _p_raw, _p_usage = call_llm(**_p_kwargs)

                    # Track cost
                    _ensemble_total_usage["input_tokens"] += _p_usage.get("input_tokens", 0)
                    _ensemble_total_usage["output_tokens"] += _p_usage.get("output_tokens", 0)
                    if _HAS_COST_TRACKER and _p_usage:
                        try:
                            cost_tracker = get_cost_tracker()
                            cost_tracker.record_call(
                                input_tokens=_p_usage.get("input_tokens", 0),
                                output_tokens=_p_usage.get("output_tokens", 0),
                                model=_pmodel,
                            )
                        except Exception:
                            pass

                    if _p_raw:
                        _p_decision, _p_err = validate_and_parse(_p_raw)
                        if _p_decision and not _p_err:
                            _ensemble_decisions.append({
                                "decision": _p_decision,
                                "weight": _pweight,
                                "name": _pmodel,
                            })
                except Exception as _pe:
                    logger.debug(f"[LLM-ENSEMBLE] {_pmodel} call failed: {_pe}")

            if _ensemble_decisions:
                # Aggregate decisions via weighted voting
                decision = aggregate_decisions(_ensemble_decisions)
                _disagreement = get_disagreement_metrics(_ensemble_decisions)

                _log_audit({
                    "ts": time.time(),
                    "action": "ensemble_vote",
                    "providers": len(_ensemble_decisions),
                    "disagreement": _disagreement.get("disagreement", False),
                    "action_spread": _disagreement.get("action_spread", []),
                })

                if decision is not None:
                    logger.info(
                        f"[LLM-ENSEMBLE] {len(_ensemble_decisions)} models voted: "
                        f"action={decision.action} conf={decision.confidence:.2f} "
                        f"disagreement={_disagreement.get('disagreement', False)}"
                    )
                    # Skip the single-model path; jump directly to mode constraints
                    # (Steps 5.5-6 below apply to the aggregated decision)
                    usage = _ensemble_total_usage
                    val_err = None
                    # Jump past the single-model call and parse
                    # We set raw_text to a placeholder so the flow continues
                    raw_text = "__ensemble__"
                else:
                    # Ensemble aggregation failed, fall through to single model
                    _ensemble_enabled = False
            else:
                # No valid ensemble decisions, fall through to single model
                _ensemble_enabled = False

    if not _ensemble_enabled and not _multi_agent_active:
        # Single-model path (default)
        raw_text, usage = call_llm(**call_kwargs)

        # Record API call cost
        if _HAS_COST_TRACKER and usage:
            try:
                cost_tracker = get_cost_tracker()
                cost_tracker.record_call(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    model=call_kwargs.get("model", "unknown"),
                )
            except Exception as ce:
                logger.debug(f"[LLM-ENGINE] Cost recording failed: {ce}")

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
    if _multi_agent_active and raw_text == "__multi_agent__":
        # Decision already built by multi-agent coordinator — skip parsing
        val_err = None
    elif _ensemble_enabled and raw_text == "__ensemble__":
        # Decision already parsed and aggregated via ensemble
        val_err = None
    else:
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

    # Step 5.4: Programmatic confidence calibration + per-regime penalty
    try:
        from llm.self_performance import get_performance_stats
        perf = get_performance_stats()
        if perf and perf.get("total_decisions", 0) >= 15:
            # Auto-calibrate: apply 50% of calibration offset
            cal = perf.get("calibration", 0.0)
            if abs(cal) > 0.05:
                correction = cal * 0.5
                old_conf = decision.confidence
                decision.confidence = max(0.0, min(1.0, decision.confidence - correction))
                if abs(correction) > 0.01:
                    logger.info(
                        f"[LLM-ENGINE] Calibration correction: {old_conf:.2f} -> "
                        f"{decision.confidence:.2f} (cal={cal:+.2f}, applied={-correction:+.2f})"
                    )

            # Per-regime penalty/bonus: adjust confidence based on historical regime accuracy
            rg_acc = perf.get("regime_accuracy", {})
            rg_counts = perf.get("regime_counts", {})
            if decision.regime in rg_acc and decision.regime in rg_counts:
                regime_wr = rg_acc[decision.regime]
                regime_n = rg_counts[decision.regime]
                if regime_wr < 0.40 and regime_n >= 5 and decision.action != "flat":
                    penalty = 0.03  # Reduced from 0.05 — gentle nudge, not a sledgehammer
                    old_conf = decision.confidence
                    decision.confidence = max(0.0, decision.confidence - penalty)
                    logger.info(
                        f"[LLM-ENGINE] Regime penalty: {decision.regime} "
                        f"WR={regime_wr:.0%} ({regime_n} trades), "
                        f"conf {old_conf:.2f} -> {decision.confidence:.2f}"
                    )
                elif regime_wr > 0.65 and regime_n >= 5 and decision.action != "flat":
                    # Reward: we're good in this regime — boost confidence more
                    bonus = 0.07  # Increased from 0.05 — reward what works
                    old_conf = decision.confidence
                    decision.confidence = min(1.0, decision.confidence + bonus)
                    logger.info(
                        f"[LLM-ENGINE] Regime bonus: {decision.regime} "
                        f"WR={regime_wr:.0%} ({regime_n} trades), "
                        f"conf {old_conf:.2f} -> {decision.confidence:.2f}"
                    )
    except Exception as e:
        logger.debug(f"[LLM-ENGINE] Calibration/regime check error: {e}")

    # Step 5.45: Regime stability check — if LLM oscillates between regimes, prefer flat
    try:
        recent = list(_recent_decisions)[-6:]
        recent_regimes = [
            r.get("rg") for r in recent
            if (time.time() - r.get("ts", 0)) < 1200  # last 20 minutes
        ]
        unique_regimes = set(r for r in recent_regimes if r)
        if len(unique_regimes) >= 3 and decision.confidence < 0.75 and decision.action != "flat":
            # Don't force flat — penalize confidence instead. Regime transitions
            # ARE real trading opportunities, flat here loses inflection-point trades.
            penalty = 0.10
            old_conf = decision.confidence
            decision.confidence = max(0.0, decision.confidence - penalty)
            logger.info(
                f"[LLM-ENGINE] Regime instability ({unique_regimes}), "
                f"conf {old_conf:.2f} → {decision.confidence:.2f} (penalty, not flat)"
            )
    except Exception:
        pass

    # Step 5.5: Apply mode-specific constraints
    original_action = decision.action
    decision, mode_overrides = _apply_mode_constraints(decision, mode)

    # Step 5.6: Flip rate limiter — prevent LLM from flip-spamming
    # High-confidence flips (>= 0.70) bypass the rate limit — genuine reversals
    is_flip = decision.action == "flip"
    is_high_conf_flip = is_flip and decision.confidence >= 0.70
    if not is_high_conf_flip:
        _flip_history.append(is_flip)
    if is_flip and not is_high_conf_flip and len(_flip_history) >= 10:
        flip_rate = sum(_flip_history) / len(_flip_history)
        if flip_rate > _FLIP_RATE_LIMIT:
            logger.warning(
                f"[LLM-ENGINE] Flip rate too high: {flip_rate:.0%} of last "
                f"{len(_flip_history)} decisions are flips — downgrading to flat"
            )
            decision.action = "flat"
            mode_overrides.append("flip_rate_limited")

    # Step 5.7: Consistency check — penalize (don't block) rapid flip-flops
    _sym_for_consistency = trigger_context.split()[0] if trigger_context else ""
    if _sym_for_consistency and decision.action != "flat":
        try:
            now = time.time()
            for rd in reversed(list(_recent_decisions)):
                if rd.get("sym") != _sym_for_consistency:
                    continue
                if (now - rd.get("ts", 0)) > 300:  # Only check last 5 minutes
                    break
                prev_action = rd.get("a", "")
                # If we previously said flat/skip but now say proceed, need higher confidence
                if prev_action in ("flat", "skip", "REJECTED_go", "REJECTED_proceed") \
                        and decision.action in ("proceed", "go"):
                    if decision.confidence < rd.get("c", 0) + 0.10:
                        # Penalize confidence instead of forcing flat — markets change
                        old_conf = decision.confidence
                        decision.confidence = max(0.0, decision.confidence - 0.05)
                        logger.info(
                            f"[LLM-ENGINE] Consistency penalty: {_sym_for_consistency} "
                            f"was recently {prev_action} (conf={rd.get('c', 0):.2f}), "
                            f"conf {old_conf:.2f} → {decision.confidence:.2f}"
                        )
                        mode_overrides.append("consistency_penalty")
                break  # Only check most recent decision for this symbol
        except Exception:
            pass

    # Step 6: Risk gate
    gated = gate_decision(decision, risk_context)

    # Step 7: Mark called (for throttle)
    mark_called(snapshot)

    # Step 8: Cache decision
    _cached_decision = decision if gated.allowed else None
    _cached_at = time.time()

    # Determine if this was a veto (LLM said flat for a trade candidate)
    is_veto = decision.action == "flat" and mode >= LLMMode.VETO_ONLY

    # Step 9: Audit log — includes snapshot for LLM replay/backtesting
    _audit_entry = {
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
    }
    # Capture snapshot for LLM replay backtesting
    # snapshot_json is the compact JSON string that was sent to the LLM
    if snapshot_json:
        try:
            _audit_entry["snapshot"] = json.loads(snapshot_json)
        except Exception:
            pass
    _log_audit(_audit_entry)

    # Step 9.5: Record to recent decisions buffer (for consistency context)
    _recent_decisions.append({
        "ts": time.time(),
        "sym": trigger_context.split()[0] if trigger_context else "",
        "a": decision.action if gated.allowed else f"REJECTED_{decision.action}",
        "c": round(decision.confidence, 2),
        "rg": decision.regime,
        "allowed": gated.allowed,
        "gate": gated.reason if not gated.allowed else "",
    })

    # Step 9.55: Record regime in deep memory (monolithic mode only —
    # multi-agent path records via learning_integration.py)
    if not _multi_agent_active and decision.regime:
        try:
            _record_monolithic_regime(decision.regime, trigger_reason)
        except Exception:
            pass

    # Step 9.6: Record veto for counterfactual tracking (via growth orchestrator)
    if is_veto and _HAS_VETO_TRACKER:
        try:
            growth = get_growth_orchestrator()
            _sym = trigger_context.split()[0] if trigger_context else ""
            _side = trigger_context.split()[1] if trigger_context and len(trigger_context.split()) > 1 else ""
            _entry = 0.0
            if snapshot.markets:
                for m in snapshot.markets:
                    if _sym and _sym in m.symbol:
                        _entry = m.price
                        break
            growth.on_veto(
                symbol=_sym,
                side=_side,
                confidence=decision.confidence * 100 if decision.confidence <= 1 else decision.confidence,
                entry_price=_entry,
                sl_price=0.0,
                tp1_price=0.0,
                llm_reason=decision.notes or "",
                regime=decision.regime,
                trigger="monolithic_engine",
            )
        except Exception as ve:
            logger.debug(f"[LLM-ENGINE] Veto recording failed: {ve}")

    if gated.allowed:
        # Step 10: Apply memory update ONLY for allowed decisions
        # (don't learn from gated/rejected decisions the bot never executed)
        apply_memory_update(
            decision.memory_update,
            symbol=trigger_context.split()[0] if trigger_context else "",
            regime=decision.regime,
        )

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

    elif mode == LLMMode.DIRECTION:
        # DIRECTION: flips allowed but require high confidence (>= 0.65)
        if decision.action == "flip":
            if decision.confidence < 0.65:
                logger.info(
                    f"[LLM-ENGINE] DIRECTION: downgrading flip -> flat "
                    f"(confidence {decision.confidence:.2f} < 0.65 threshold)"
                )
                decision.action = "flat"
                overrides.append(f"flip_conf_{decision.confidence:.2f}_to_flat")

    elif mode == LLMMode.FULL:
        # FULL: flips allowed, very low soft gate (0.50) — hard gate in risk_gating at 0.65
        if decision.action == "flip":
            if decision.confidence < 0.50:
                logger.info(
                    f"[LLM-ENGINE] FULL: downgrading flip -> flat "
                    f"(confidence {decision.confidence:.2f} < 0.50 threshold)"
                )
                decision.action = "flat"
                overrides.append(f"flip_conf_{decision.confidence:.2f}_to_flat")

    return decision, overrides
