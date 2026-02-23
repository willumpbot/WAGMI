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
from typing import Dict, Any, Optional

from llm.autonomy import LLMMode
from llm.decision_types import LLMDecision

logger = logging.getLogger("bot.llm.autonomy_router")


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
        # LLM approved, use baseline
        decision["source"] = "baseline_approved_by_llm"
        decision["llm_veto"] = False
        decision["llm_confidence"] = llm.confidence
        decision["llm_regime"] = llm.regime
        logger.debug(
            f"[AUTONOMY-ROUTER] Mode VETO_ONLY: LLM approved baseline "
            f"(conf={llm.confidence:.2f})"
        )
        return decision


def _mode_sizing(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """SIZING mode: LLM scales position size (but not direction).

    Rules:
    - Direction always from baseline
    - Size scaled by llm.size_multiplier
    - If LLM says "flat", use baseline but scale by 0.0 (skip)
    - If LLM says "flip", downgrade to flat (flip not allowed)
    - Confidence updated to max(baseline, llm) for risk gating
    """
    decision = baseline.copy()

    if llm is None:
        # LLM failed: use baseline size
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        decision["size_multiplier"] = 1.0
        return decision

    if llm.action == "flat":
        # Skip this trade
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        return decision

    if llm.action == "flip":
        # SIZING doesn't allow flips: skip
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = f"flip not allowed in SIZING"
        return decision

    # "proceed": scale baseline size by llm.size_multiplier
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * llm.size_multiplier
    decision["size"] = scaled_size
    decision["source"] = "sizing"
    decision["llm_veto"] = False
    decision["size_multiplier"] = llm.size_multiplier
    decision["llm_confidence"] = llm.confidence
    decision["llm_regime"] = llm.regime
    logger.info(
        f"[AUTONOMY-ROUTER] Mode SIZING: size {baseline_size:.2f} -> {scaled_size:.2f} "
        f"(mult={llm.size_multiplier:.2f})"
    )
    return decision


def _mode_direction(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """DIRECTION mode: LLM picks direction and size.

    Rules:
    - Direction from LLM (proceed = use baseline side, flip = reverse, flat = skip)
    - Size scaled by llm.size_multiplier (baseline * mult)
    - Entry refinement from llm.entry_adjustment
    """
    decision = baseline.copy()

    if llm is None:
        # LLM failed: use baseline
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        return decision

    if llm.action == "flat":
        # Skip
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        return decision

    if llm.action == "flip":
        # Reverse direction
        baseline_side = decision.get("action", "long")
        flipped_side = "short" if baseline_side == "long" else "long"
        decision["action"] = flipped_side
        logger.info(
            f"[AUTONOMY-ROUTER] Mode DIRECTION: flipped "
            f"{baseline_side} -> {flipped_side}"
        )

    # Scale size
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * llm.size_multiplier
    decision["size"] = scaled_size
    decision["source"] = "llm_direction"
    decision["llm_veto"] = False
    decision["size_multiplier"] = llm.size_multiplier
    decision["llm_confidence"] = llm.confidence
    decision["llm_regime"] = llm.regime
    decision["entry_adjustment"] = llm.entry_adjustment
    logger.info(
        f"[AUTONOMY-ROUTER] Mode DIRECTION: "
        f"side={decision.get('action')} size={scaled_size:.2f} mult={llm.size_multiplier:.2f}"
    )
    return decision


def _mode_full(baseline: Dict[str, Any], llm: Optional[LLMDecision]) -> Dict[str, Any]:
    """FULL mode: LLM drives everything.

    Rules:
    - Direction from LLM
    - Size from LLM (llm.size_multiplier)
    - Entry refinement from LLM
    - Confidence from LLM
    - Regime from LLM
    - Still subject to RiskManager + CircuitBreaker
    """
    decision = baseline.copy()

    if llm is None:
        # LLM failed: fallback to baseline
        decision["source"] = "baseline"
        decision["llm_veto"] = False
        logger.warning("[AUTONOMY-ROUTER] Mode FULL: LLM failed, fallback to baseline")
        return decision

    if llm.action == "flat":
        # Skip
        decision["action"] = "flat"
        decision["source"] = "llm_veto"
        decision["llm_veto"] = True
        decision["veto_reason"] = llm.notes
        return decision

    if llm.action == "flip":
        # Reverse direction
        baseline_side = decision.get("action", "long")
        decision["action"] = "short" if baseline_side == "long" else "long"

    # Full LLM control
    baseline_size = decision.get("size", 1.0)
    scaled_size = baseline_size * llm.size_multiplier
    decision["size"] = scaled_size
    decision["source"] = "llm_full"
    decision["llm_veto"] = False
    decision["size_multiplier"] = llm.size_multiplier
    decision["confidence"] = llm.confidence  # Override confidence
    decision["regime"] = llm.regime  # Override regime
    decision["entry_adjustment"] = llm.entry_adjustment
    decision["strategy_weights"] = llm.strategy_weights.to_dict()
    logger.info(
        f"[AUTONOMY-ROUTER] Mode FULL: "
        f"side={decision.get('action')} size={scaled_size:.2f} "
        f"conf={llm.confidence:.2f} regime={llm.regime}"
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
