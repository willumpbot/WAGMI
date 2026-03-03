"""
Learning Mode: Relaxed LLM behavior for initial test runs.

During the first few days of deployment, the LLM should NOT be strict
about vetoing or directing trades. Instead, it should:

1. OBSERVE: Digest every signal, every strategy output, every outcome
2. ANALYZE: Study the thought process behind successful trades
3. LEARN: Build a mental model of what makes a "sniper trade"
4. INFLUENCE LIGHTLY: Can nudge small decisions (sizing, not direction)
5. NEVER BLOCK: Unless it detects a truly catastrophic setup

The LLM is in "student mode" - it's learning from the strategies,
not trying to outsmart them. After enough data, it graduates to
more active roles.

Modes:
  ABSORB (default first 48h):
    - LLM receives ALL data (every signal, outcome, regime change)
    - LLM writes memory/insights after every evaluation
    - LLM CANNOT veto trades (all vetoes downgraded to proceed)
    - LLM CAN adjust size by ±20% max (soft influence)
    - LLM generates "what I would have done" counterfactuals

  APPRENTICE (days 3-7):
    - LLM can veto only obviously bad setups (confidence < 0.3)
    - LLM can adjust size by ±40%
    - LLM starts suggesting entry refinements (logged, not enforced)
    - Tracks accuracy: "would my veto have been right?"

  ACTIVE (day 7+):
    - Normal autonomy modes resume (VETO_ONLY, SIZING, etc)
    - But with the knowledge accumulated during learning

Graduation criteria (auto-detected):
  - 50+ trades observed
  - Counterfactual accuracy > 55% (LLM's vetoes would have been right)
  - Pattern library has 20+ entries
  - Strategy fingerprints populated for all active strategies
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("bot.llm.learning_mode")

_STATE_PATH = os.path.join("data", "llm", "learning_state.json")


class LearningPhase(IntEnum):
    """Learning progression phases."""
    ABSORB = 0      # Pure observation, no blocking
    APPRENTICE = 1  # Light influence, track accuracy
    ACTIVE = 2      # Full autonomy (graduates to normal modes)


@dataclass
class LearningState:
    """Persistent state for learning mode."""
    phase: int = 0  # LearningPhase value
    started_at: float = 0.0
    trades_observed: int = 0
    signals_observed: int = 0
    counterfactuals: List[Dict] = field(default_factory=list)
    counterfactual_correct: int = 0
    counterfactual_total: int = 0
    phase_transitions: List[Dict] = field(default_factory=list)
    graduated: bool = False
    graduation_reason: str = ""

    @property
    def counterfactual_accuracy(self) -> float:
        if self.counterfactual_total == 0:
            return 0.0
        return self.counterfactual_correct / self.counterfactual_total

    @property
    def hours_elapsed(self) -> float:
        if self.started_at == 0:
            return 0.0
        return (time.time() - self.started_at) / 3600

    @property
    def current_phase(self) -> LearningPhase:
        return LearningPhase(self.phase)


def _load_state() -> LearningState:
    """Load learning state from disk."""
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH) as f:
                data = json.load(f)
            state = LearningState()
            for key, val in data.items():
                if hasattr(state, key):
                    setattr(state, key, val)
            return state
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[LEARNING] Failed to load state: {e}")
    return LearningState(started_at=time.time())


def _save_state(state: LearningState):
    """Save learning state to disk."""
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    try:
        data = {
            "phase": state.phase,
            "started_at": state.started_at,
            "trades_observed": state.trades_observed,
            "signals_observed": state.signals_observed,
            "counterfactual_correct": state.counterfactual_correct,
            "counterfactual_total": state.counterfactual_total,
            "phase_transitions": state.phase_transitions[-50:],
            "counterfactuals": state.counterfactuals[-100:],
            "graduated": state.graduated,
            "graduation_reason": state.graduation_reason,
        }
        with open(_STATE_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except IOError as e:
        logger.warning(f"[LEARNING] Failed to save state: {e}")


# ═══════════════════════════════════════════════════════════════
# Core Learning Mode Logic
# ═══════════════════════════════════════════════════════════════

_state: Optional[LearningState] = None


def get_learning_state() -> LearningState:
    """Get current learning state (lazy-loaded singleton)."""
    global _state
    if _state is None:
        _state = _load_state()
        if _state.started_at == 0:
            _state.started_at = time.time()
            _save_state(_state)
    return _state


def is_learning_mode_active() -> bool:
    """Check if learning mode is still active (not graduated)."""
    state = get_learning_state()
    return not state.graduated


def get_current_phase() -> LearningPhase:
    """Get current learning phase."""
    state = get_learning_state()
    if state.graduated:
        return LearningPhase.ACTIVE
    return state.current_phase


def record_signal_observed(
    symbol: str,
    side: str,
    confidence: float,
    regime: str,
    strategies: List[str],
    num_agree: int,
):
    """Record that a signal was observed (even if not traded)."""
    state = get_learning_state()
    state.signals_observed += 1

    if state.signals_observed % 50 == 0:
        logger.info(
            f"[LEARNING] Observed {state.signals_observed} signals, "
            f"{state.trades_observed} trades, phase={state.current_phase.name}, "
            f"counterfactual accuracy={state.counterfactual_accuracy:.0%}"
        )
        _save_state(state)


def record_trade_observed(
    symbol: str,
    side: str,
    outcome: str,
    pnl: float,
    confidence: float,
):
    """Record that a trade outcome was observed."""
    state = get_learning_state()
    state.trades_observed += 1
    _check_graduation(state)
    _save_state(state)


def record_counterfactual(
    llm_would_have_vetoed: bool,
    actual_outcome: str,  # "WIN" or "LOSS"
    pnl: float,
    symbol: str = "",
    reasoning: str = "",
):
    """Record what the LLM would have done vs. what actually happened.

    This tracks how accurate the LLM's instincts are BEFORE it gets
    actual power. Used to determine graduation readiness.
    """
    state = get_learning_state()

    # Did the LLM's instinct match reality?
    llm_was_right = (
        (llm_would_have_vetoed and actual_outcome == "LOSS") or
        (not llm_would_have_vetoed and actual_outcome == "WIN")
    )

    state.counterfactual_total += 1
    if llm_was_right:
        state.counterfactual_correct += 1

    entry = {
        "ts": time.time(),
        "would_veto": llm_would_have_vetoed,
        "actual": actual_outcome,
        "pnl": pnl,
        "correct": llm_was_right,
        "symbol": symbol,
        "reasoning": reasoning[:200],
    }
    state.counterfactuals.append(entry)
    if len(state.counterfactuals) > 200:
        state.counterfactuals = state.counterfactuals[-200:]

    _save_state(state)

    if llm_was_right:
        logger.debug(f"[LEARNING] Counterfactual CORRECT: veto={llm_would_have_vetoed}, outcome={actual_outcome}")
    else:
        logger.debug(f"[LEARNING] Counterfactual WRONG: veto={llm_would_have_vetoed}, outcome={actual_outcome}")


def apply_learning_constraints(
    llm_action: str,
    llm_confidence: float,
    llm_size_multiplier: float,
    signal_confidence: float,
) -> Tuple[str, float, str]:
    """Apply learning phase constraints to LLM decisions.

    Returns: (constrained_action, constrained_size_mult, reason)

    In ABSORB phase: Never veto, limit size adjustment to ±20%
    In APPRENTICE phase: Only veto obvious disasters, limit size to ±40%
    In ACTIVE phase: No constraints (normal mode)
    """
    state = get_learning_state()
    phase = state.current_phase

    if state.graduated or phase == LearningPhase.ACTIVE:
        return llm_action, llm_size_multiplier, "graduated"

    if phase == LearningPhase.ABSORB:
        # ABSORB: LLM observes and learns, but vetoes are RESPECTED.
        # Overriding vetoes was counterproductive — the LLM's veto logic is
        # valuable (catches chases, bad RR, etc.) and forcing trades through
        # just wastes money on entries the slippage guard rejects anyway.
        if llm_action == "flat":
            logger.info(
                f"[LEARNING-ABSORB] LLM veto (conf={llm_confidence:.2f}) — "
                f"respecting veto, recording counterfactual."
            )
            return "flat", 1.0, "absorb_respect_veto"

        if llm_action == "flip":
            logger.info("[LEARNING-ABSORB] LLM flip request — respecting, recording counterfactual")
            return "flip", 1.0, "absorb_respect_flip"

        # Size adjustment: cap at ±20%
        constrained_mult = max(0.8, min(1.2, llm_size_multiplier))
        return llm_action, constrained_mult, "absorb_size_limited"

    elif phase == LearningPhase.APPRENTICE:
        # APPRENTICE: Can veto only truly terrible signals
        if llm_action == "flat" and llm_confidence >= 0.7:
            # High-confidence veto from LLM — allow it even in apprentice
            return "flat", 1.0, "apprentice_high_conf_veto"

        if llm_action == "flat" and signal_confidence < 55:
            # Signal is borderline anyway, allow the veto
            return "flat", 1.0, "apprentice_weak_signal_veto"

        if llm_action == "flat":
            # Low-confidence veto — override
            logger.info(
                f"[LEARNING-APPRENTICE] LLM veto overridden "
                f"(llm_conf={llm_confidence:.2f} too low for apprentice veto)"
            )
            return "proceed", 1.0, "apprentice_override_weak_veto"

        if llm_action == "flip":
            return "proceed", 1.0, "apprentice_override_flip"

        # Size adjustment: cap at ±40%
        constrained_mult = max(0.6, min(1.4, llm_size_multiplier))
        return llm_action, constrained_mult, "apprentice_size_limited"

    return llm_action, llm_size_multiplier, "unknown_phase"


def _check_graduation(state: LearningState):
    """Check if the LLM should graduate to the next phase or full active."""
    phase = state.current_phase

    if state.graduated:
        return

    if phase == LearningPhase.ABSORB:
        # Accelerated: Graduate to APPRENTICE after 24h AND 10+ trades (was 48h/20)
        if state.hours_elapsed >= 24 and state.trades_observed >= 10:
            state.phase = LearningPhase.APPRENTICE.value
            state.phase_transitions.append({
                "ts": time.time(),
                "from": "ABSORB",
                "to": "APPRENTICE",
                "trades": state.trades_observed,
                "hours": round(state.hours_elapsed, 1),
            })
            logger.info(
                f"[LEARNING] GRADUATED: ABSORB -> APPRENTICE "
                f"({state.trades_observed} trades, {state.hours_elapsed:.0f}h)"
            )

    elif phase == LearningPhase.APPRENTICE:
        # Accelerated: Graduate to ACTIVE after:
        # - 25+ trades observed (was 50)
        # - Counterfactual accuracy > 52% (was 55%)
        # - 3+ days elapsed (was 7)
        can_graduate = (
            state.trades_observed >= 25
            and state.counterfactual_total >= 10
            and state.counterfactual_accuracy >= 0.52
            and state.hours_elapsed >= 72  # 3 days (was 7)
        )

        if can_graduate:
            state.phase = LearningPhase.ACTIVE.value
            state.graduated = True
            state.graduation_reason = (
                f"Observed {state.trades_observed} trades over {state.hours_elapsed:.0f}h. "
                f"Counterfactual accuracy: {state.counterfactual_accuracy:.0%} "
                f"({state.counterfactual_correct}/{state.counterfactual_total})"
            )
            state.phase_transitions.append({
                "ts": time.time(),
                "from": "APPRENTICE",
                "to": "ACTIVE (graduated)",
                "trades": state.trades_observed,
                "accuracy": round(state.counterfactual_accuracy, 3),
                "hours": round(state.hours_elapsed, 1),
            })
            logger.info(f"[LEARNING] GRADUATED TO ACTIVE: {state.graduation_reason}")

        # Fallback: if accuracy is terrible after 100+ counterfactuals,
        # still graduate but log a warning
        elif state.counterfactual_total >= 100 and state.counterfactual_accuracy < 0.45:
            logger.warning(
                f"[LEARNING] Counterfactual accuracy poor ({state.counterfactual_accuracy:.0%}). "
                f"LLM instincts not reliable — graduating to ACTIVE with caution flag."
            )
            state.phase = LearningPhase.ACTIVE.value
            state.graduated = True
            state.graduation_reason = (
                f"Graduated with caution — accuracy {state.counterfactual_accuracy:.0%} "
                f"below threshold. LLM should stay in VETO_ONLY or ADVISORY."
            )


def force_graduate():
    """Manually graduate to ACTIVE mode."""
    state = get_learning_state()
    state.graduated = True
    state.phase = LearningPhase.ACTIVE.value
    state.graduation_reason = "Manual graduation"
    _save_state(state)
    logger.info("[LEARNING] Manually graduated to ACTIVE")


def reset_learning():
    """Reset learning state (for re-training)."""
    global _state
    _state = LearningState(started_at=time.time())
    _save_state(_state)
    logger.info("[LEARNING] Learning state reset")


def get_learning_report() -> Dict[str, Any]:
    """Get learning mode status report."""
    state = get_learning_state()
    return {
        "phase": state.current_phase.name,
        "graduated": state.graduated,
        "graduation_reason": state.graduation_reason,
        "hours_elapsed": round(state.hours_elapsed, 1),
        "signals_observed": state.signals_observed,
        "trades_observed": state.trades_observed,
        "counterfactual_accuracy": round(state.counterfactual_accuracy, 3),
        "counterfactual_total": state.counterfactual_total,
        "phase_transitions": state.phase_transitions,
    }
