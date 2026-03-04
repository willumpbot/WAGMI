"""
Autonomy Router: Centralized mode handling.

This is the single source of truth for how each LLM mode affects trading decisions.

Modes (in order of increasing autonomy):
  OFF (0):          LLM disabled. Pure strategy.
  ADVISORY (1):     LLM called, logged, NO influence.
  VETO_ONLY (2):    LLM can reject trades before entry.
  SIZING (3):       LLM scales position size.
  DIRECTION (4):    LLM picks direction.
  FULL (5):         LLM drives direction + sizing.

Each mode has specific rules about what LLM can/cannot do.
"""

import logging
import time
from collections import deque
from typing import Dict, Any, Optional

from llm.autonomy import LLMMode
from llm.decision_types import LLMDecision

logger = logging.getLogger("bot.llm.autonomy_router")

# ── Divergence tracking (ADVISORY mode) ─────────────────────
# Tracks when LLM disagrees with baseline to measure LLM signal quality
_divergence_history: deque = deque(maxlen=50)  # (timestamp, agreed: bool, llm_action, baseline_action)


def apply_autonomy_mode(
    mode: LLMMode,
    baseline_decision: Dict[str, Any],
    llm_decision: Optional[LLMDecision],
) -> Dict[str, Any]:
    """Apply mode-specific logic to combine baseline + LLM decisions.

    Args:
        mode: Current LLMMode
        baseline_decision: Ensemble output (side, size, confidence, regime, etc)
        llm_decision: LLM output (or None if LLM not called / failed)

    Returns:
        Final decision dict with fields:
          - action: 'long', 'short', or 'flat'
          - size: position size (contracts or %)
          - entry: entry price
          - sl: stop loss
          - tp: take profit
          - confidence: final confidence
          - regime: final regime estimate
          - source: "baseline" or "llm" or "hybrid"
          - llm_veto: bool (True if LLM rejected)
          - mode_used: str (OFF, ADVISORY, VETO_ONLY, etc)
    """

    if mode == LLMMode.OFF:
        return _mode_off(baseline_decision, llm_decision)
    elif mode == LLMMode.ADVISORY:
        return _mode_advisory(baseline_decision, llm_decision)
    elif mode == LLMMode.VETO_ONLY:
        return _mode_veto_only(baseline_decision, llm_decision)
    elif mode == LLMMode.SIZING:
        return _mode_sizing(baseline_decision, llm_decision)
    elif mode == LLMMode.DIRECTION:
        return _mode_direction(baseline_decision, llm_decision)
    elif mode == LLMMode.FULL:
        return _mode_full(baseline_decision, llm_decision)
    else:
        logger.warning(f"[AUTONOMY-ROUTER] Unknown mode {mode}, defaulting to OFF")
        return _mode_off(baseline_decision, llm_decision)


# ── Mode Implementations ──────────────────────────────────────


def _mode_off(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """OFF mode: Pure strategy-driven, LLM ignored."""
    decision = baseline.copy()
    decision["source"] = "baseline"
    decision["mode_used"] = "OFF"
    decision["llm_veto"] = False
    logger.debug("[AUTONOMY-ROUTER] Mode OFF: using baseline")
    return decision


def _mode_advisory(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """ADVISORY mode: LLM logged but does not influence execution.

    LLM decision is logged to decisions.jsonl for comparison.
    Bot executes baseline regardless.
    Tracks divergence rate for autonomy promotion decisions.
    """
    decision = baseline.copy()
    decision["source"] = "baseline"
    decision["mode_used"] = "ADVISORY"
    decision["llm_veto"] = False
    if llm:
        decision["llm_decision_logged"] = {
            "action": llm.action,
            "confidence": llm.confidence,
            "regime": llm.regime,
        }
        # Track whether LLM agrees with baseline
        baseline_action = baseline.get("action", "long")
        llm_action = llm.action  # "proceed", "flat", or "flip"
        agreed = llm_action == "proceed"
        _divergence_history.append((time.time(), agreed, llm_action, baseline_action))

        if not agreed:
            logger.info(
                f"[AUTONOMY-ROUTER] ADVISORY divergence: LLM={llm_action} "
                f"vs baseline={baseline_action} (conf={llm.confidence:.2f})"
            )

        # Add divergence stats to decision for logging
        decision["advisory_divergence_rate"] = get_divergence_rate()

    logger.debug("[AUTONOMY-ROUTER] Mode ADVISORY: baseline + LLM logged")
    return decision


def _mode_veto_only(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """VETO_ONLY mode: LLM can reject (veto) trades.

    Rules:
    - If LLM says "flat", reject trade (llm_veto=True)
    - If LLM says "proceed", use baseline
    - If LLM says "flip", downgrade to flat (flip not allowed in VETO_ONLY)
    - If LLM fails/missing, use baseline
    - Size/entry unchanged: always use baseline
    """
    decision = baseline.copy()

    if llm is None:
        # LLM failed or not called
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        logger.debug("[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM failed, using baseline")
        return decision

    # LLM decision available
    if llm.action == "flat":
        # VETO: reject trade
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        logger.info(
            f"[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM vetoed trade "
            f"(conf={llm.confidence:.2f}, reason={llm.notes[:50]})"
        )
        return decision

    elif llm.action == "flip":
        # VETO_ONLY doesn't allow flips: downgrade to flat
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = f"flip not allowed in VETO_ONLY (LLM said: {llm.notes})"
        logger.info("[AUTONOMY-ROUTER] Mode VETO_ONLY: flip downgraded to flat")
        return decision

    else:  # "proceed"
        # LLM approved — scale sizing by LLM confidence for gradation
        # Strong approval (>0.70) = full size, weak (0.50-0.60) = reduced
        decision["source"] = "baseline_approved_by_llm"
        decision["llm_veto"] = False
        decision["llm_confidence"] = llm.confidence
        decision["llm_regime"] = llm.regime

        # Confidence-based size scaling: avoid all-or-nothing
        if llm.confidence < 0.55:
            decision["size_multiplier"] = 0.6  # Weak approval → smaller position
            logger.info(
                f"[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM weak approval "
                f"(conf={llm.confidence:.2f}), sizing 0.6x"
            )
        elif llm.confidence < 0.65:
            decision["size_multiplier"] = 0.8  # Moderate approval → slight reduction
            logger.debug(
                f"[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM moderate approval "
                f"(conf={llm.confidence:.2f}), sizing 0.8x"
            )
        else:
            logger.debug(
                f"[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM strong approval "
                f"(conf={llm.confidence:.2f}), full size"
            )
        return decision


def _mode_sizing(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """SIZING mode: LLM scales position size (but not direction).

    Rules:
    - Direction always from baseline (flip -> flat downgrade)
    - Size scaled by llm.size_multiplier (clamped 0.0-2.0)
    - If LLM says "flat", veto the trade
    - Confidence = max(baseline_conf, llm_conf) for risk gating
    - entry_adjustment ignored (not allowed in SIZING)
    - Logs: baseline_size, llm_multiplier, final_size
    """
    decision = baseline.copy()
    decision["mode_used"] = "SIZING"

    if llm is None:
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        decision["size_multiplier"] = 1.0
        return decision

    if llm.action == "flat":
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        decision["llm_confidence"] = llm.confidence
        decision["llm_regime"] = llm.regime
        return decision

    if llm.action == "flip":
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = "flip not allowed in SIZING"
        decision["llm_confidence"] = llm.confidence
        return decision

    # "proceed": scale baseline size by clamped size_multiplier
    clamped_mult = max(0.0, min(llm.size_multiplier, 2.0))
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * clamped_mult
    baseline_conf = decision.get("confidence", 0.0)
    upgraded_conf = max(baseline_conf, llm.confidence)

    decision["size"] = scaled_size
    decision["source"] = "sizing"
    decision["llm_veto"] = False
    decision["size_multiplier"] = clamped_mult
    decision["baseline_size"] = baseline_size
    decision["final_size"] = scaled_size
    decision["llm_confidence"] = llm.confidence
    decision["llm_regime"] = llm.regime
    decision["confidence"] = upgraded_conf
    decision["llm_notes"] = llm.notes
    decision["llm_memory_update"] = llm.memory_update
    logger.info(
        f"[AUTONOMY-ROUTER] Mode SIZING: size {baseline_size:.4f} * {clamped_mult:.2f} = {scaled_size:.4f} "
        f"| conf {baseline_conf:.2f} -> {upgraded_conf:.2f} | regime={llm.regime}"
    )
    return decision


def _mode_direction(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """DIRECTION mode: LLM picks direction and size.

    Rules:
    - proceed = use baseline direction, flip = reverse, flat = skip
    - flip requires confidence >= 0.65 (enforced here as soft guard)
    - Size scaled by clamped size_multiplier (0.0-2.0)
    - entry_adjustment passed through for execution layer
    - Confidence = max(baseline, llm)
    - Baseline still provides SL/TP (LLM doesn't set exit levels)
    """
    decision = baseline.copy()
    decision["mode_used"] = "DIRECTION"

    if llm is None:
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        return decision

    if llm.action == "flat":
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        decision["llm_confidence"] = llm.confidence
        decision["llm_regime"] = llm.regime
        return decision

    baseline_side = decision.get("action", "long")

    if llm.action == "flip":
        # Soft confidence gate for flips (hard gate is in risk_gating)
        if llm.confidence < 0.65:
            logger.warning(
                f"[AUTONOMY-ROUTER] Mode DIRECTION: flip rejected, "
                f"confidence {llm.confidence:.2f} < 0.65"
            )
            decision["action"] = "flat"
            decision["source"] = "llm_veto"
            decision["llm_veto"] = True
            decision["veto_reason"] = f"flip confidence too low ({llm.confidence:.2f})"
            decision["llm_confidence"] = llm.confidence
            return decision

        flipped_side = "short" if baseline_side == "long" else "long"
        decision["action"] = flipped_side
        decision["llm_direction"] = "flip"
        decision["flip_reason"] = llm.notes
        logger.info(
            f"[AUTONOMY-ROUTER] Mode DIRECTION: FLIP {baseline_side} -> {flipped_side} "
            f"(conf={llm.confidence:.2f})"
        )
    else:
        decision["llm_direction"] = "proceed"

    # Scale size (clamped)
    clamped_mult = max(0.0, min(llm.size_multiplier, 2.0))
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * clamped_mult
    baseline_conf = decision.get("confidence", 0.0)
    upgraded_conf = max(baseline_conf, llm.confidence)

    decision["size"] = scaled_size
    decision["source"] = "llm_direction"
    decision["llm_veto"] = False
    decision["size_multiplier"] = clamped_mult
    decision["baseline_size"] = baseline_size
    decision["final_size"] = scaled_size
    decision["llm_confidence"] = llm.confidence
    decision["llm_regime"] = llm.regime
    decision["confidence"] = upgraded_conf
    decision["entry_adjustment"] = llm.entry_adjustment
    decision["llm_notes"] = llm.notes
    decision["llm_memory_update"] = llm.memory_update
    logger.info(
        f"[AUTONOMY-ROUTER] Mode DIRECTION: side={decision.get('action')} "
        f"size={scaled_size:.4f} mult={clamped_mult:.2f} "
        f"conf={upgraded_conf:.2f} entry_adj={llm.entry_adjustment}"
    )
    return decision


def _mode_full(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """FULL mode: LLM drives everything.

    LLM overrides:
    - Direction (proceed/flip/flat)
    - Size (size_multiplier, clamped 0.0-2.0)
    - Confidence (LLM confidence replaces baseline)
    - Regime (LLM regime replaces baseline)
    - Entry refinement (entry_adjustment)
    - Strategy weights (per-strategy scaling)

    Bot still enforces:
    - Risk gating (daily loss, drawdown, leverage caps)
    - Circuit breaker
    - Correlation guard
    - Weekend/liquidity sizing (applied later)
    - Min quantity enforcement
    """
    decision = baseline.copy()
    decision["mode_used"] = "FULL"

    if llm is None:
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        logger.warning("[AUTONOMY-ROUTER] Mode FULL: LLM failed, fallback to baseline")
        return decision

    if llm.action == "flat":
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        decision["llm_confidence"] = llm.confidence
        decision["llm_regime"] = llm.regime
        return decision

    baseline_side = decision.get("action", "long")

    if llm.action == "flip":
        # No soft gate here — risk_gating.py enforces the hard floor (0.65).
        # In FULL mode, trust the LLM's flip decisions more aggressively.
        flipped_side = "short" if baseline_side == "long" else "long"
        decision["action"] = flipped_side
        decision["llm_direction"] = "flip"
        decision["flip_reason"] = llm.notes
        logger.info(
            f"[AUTONOMY-ROUTER] Mode FULL: FLIP {baseline_side} -> {flipped_side} "
            f"(conf={llm.confidence:.2f})"
        )
    else:
        decision["llm_direction"] = "proceed"

    # Full LLM override — higher cap (2.5x) since FULL mode trusts the LLM
    clamped_mult = max(0.0, min(llm.size_multiplier, 2.5))
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * clamped_mult

    decision["size"] = scaled_size
    decision["source"] = "llm_full"
    decision["llm_veto"] = False
    decision["size_multiplier"] = clamped_mult
    decision["baseline_size"] = baseline_size
    decision["final_size"] = scaled_size
    decision["confidence"] = llm.confidence        # Override confidence
    decision["regime"] = llm.regime                 # Override regime
    decision["llm_confidence"] = llm.confidence
    decision["llm_regime"] = llm.regime
    decision["entry_adjustment"] = llm.entry_adjustment
    decision["llm_notes"] = llm.notes
    decision["llm_memory_update"] = llm.memory_update

    # Apply strategy weights (normalize sum to 1.0)
    if llm.strategy_weights:
        sw = llm.strategy_weights.to_dict()
        total = sum(v for v in sw.values() if isinstance(v, (int, float)) and v > 0)
        if total > 0:
            normalized_weights = {k: v / total for k, v in sw.items() if isinstance(v, (int, float))}
            decision["strategy_weights"] = normalized_weights
        else:
            decision["strategy_weights"] = sw

    logger.info(
        f"[AUTONOMY-ROUTER] Mode FULL: side={decision.get('action')} "
        f"size={scaled_size:.4f} conf={llm.confidence:.2f} "
        f"regime={llm.regime} entry_adj={llm.entry_adjustment}"
    )
    return decision


# ── Helpers ───────────────────────────────────────────────────


def get_mode_description(mode: LLMMode) -> str:
    """Get human-readable description of what each mode does."""
    descriptions = {
        LLMMode.OFF: "LLM disabled. Pure strategy-driven trading.",
        LLMMode.ADVISORY: "LLM logged but not used. Baseline only.",
        LLMMode.VETO_ONLY: "LLM can veto (reject) trades. No sizing or flips.",
        LLMMode.SIZING: "LLM scales size. Direction from ensemble.",
        LLMMode.DIRECTION: "LLM picks direction and size.",
        LLMMode.FULL: "LLM drives everything. Still gated by risk.",
    }
    return descriptions.get(mode, "Unknown mode")


def can_llm_flip(mode: LLMMode) -> bool:
    """Whether LLM can flip direction in this mode."""
    return mode in (LLMMode.DIRECTION, LLMMode.FULL)


def can_llm_scale_size(mode: LLMMode) -> bool:
    """Whether LLM can scale position size in this mode."""
    return mode in (LLMMode.SIZING, LLMMode.DIRECTION, LLMMode.FULL)


def is_llm_active(mode: LLMMode) -> bool:
    """Whether LLM has any influence on trades in this mode."""
    return mode != LLMMode.OFF and mode != LLMMode.ADVISORY


def get_divergence_rate() -> float:
    """Get the LLM-vs-baseline divergence rate from ADVISORY mode.

    Returns 0.0-1.0 representing how often LLM disagrees with baseline.
    Useful for deciding when to promote from ADVISORY to VETO_ONLY.
    """
    if len(_divergence_history) < 5:
        return 0.0
    disagreements = sum(1 for _, agreed, _, _ in _divergence_history if not agreed)
    return disagreements / len(_divergence_history)


def get_divergence_stats() -> Dict[str, Any]:
    """Get detailed divergence statistics for monitoring."""
    if not _divergence_history:
        return {"total": 0, "divergence_rate": 0.0}

    total = len(_divergence_history)
    disagreements = sum(1 for _, agreed, _, _ in _divergence_history if not agreed)
    flips = sum(1 for _, _, action, _ in _divergence_history if action == "flip")
    skips = sum(1 for _, _, action, _ in _divergence_history if action == "flat")

    return {
        "total": total,
        "divergence_rate": round(disagreements / total, 3),
        "flip_rate": round(flips / total, 3),
        "skip_rate": round(skips / total, 3),
        "agree_rate": round((total - disagreements) / total, 3),
    }
