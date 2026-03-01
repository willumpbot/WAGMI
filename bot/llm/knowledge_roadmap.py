"""
Knowledge Roadmap: The LLM's structured path from student to expert.

This is the master controller that determines when the LLM has learned
enough to be trusted with real money. It integrates:

  - learning_mode.py (ABSORB -> APPRENTICE -> ACTIVE)
  - self_teaching.py (curriculum levels 1-5)
  - progression.py (VETO_ONLY -> SIZING -> DIRECTION -> FULL)
  - deep_memory.py (knowledge base, trade DNA, insights)
  - Signal analyzer accuracy tracking

THE ROADMAP:

  ┌─────────────────────────────────────────────────────────────┐
  │  PHASE 1: OBSERVER                                         │
  │  Duration: First 48-72 hours                               │
  │  LLM Mode: ADVISORY (watches everything, blocks nothing)   │
  │  Curriculum: Level 1 - Pattern Recognition                 │
  │  Learning: ABSORB                                          │
  │  Money: $0 (paper only)                                    │
  │                                                            │
  │  Goals:                                                    │
  │  - Observe 50+ signals                                     │
  │  - Analyze 20+ trades to completion                        │
  │  - Build initial pattern library (10+ entries)             │
  │  - Understand each strategy's behavior                     │
  │  - Start building knowledge base axioms/observations       │
  │  - Signal analysis accuracy tracking begins                │
  │                                                            │
  │  Gate to Phase 2:                                          │
  │  [x] 50+ signals observed                                  │
  │  [x] 20+ trades observed to completion                     │
  │  [x] Pattern library has 10+ entries                       │
  │  [x] All 4 strategies fingerprinted                        │
  │  [x] 48+ hours elapsed                                     │
  └──────────────────────┬──────────────────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────────────────┐
  │  PHASE 2: ANALYST                                          │
  │  Duration: Days 3-7                                        │
  │  LLM Mode: VETO_ONLY (can block bad trades only)           │
  │  Curriculum: Level 2 - Causal Analysis                     │
  │  Learning: APPRENTICE                                      │
  │  Money: $0 (paper only, but tracking P&L closely)          │
  │                                                            │
  │  Goals:                                                    │
  │  - Generate and test 10+ hypotheses                        │
  │  - Achieve 55%+ counterfactual accuracy                    │
  │  - Veto accuracy 55%+ (vetoed trades really were bad)      │
  │  - Signal analysis accuracy 55%+                           │
  │  - Build causal models (regime -> outcome)                 │
  │  - Knowledge base: 5+ validated principles                 │
  │                                                            │
  │  Gate to Phase 3:                                          │
  │  [x] 10+ hypotheses generated and tested                   │
  │  [x] Counterfactual accuracy >= 55%                        │
  │  [x] Veto accuracy >= 55%                                  │
  │  [x] Signal analysis accuracy >= 55%                       │
  │  [x] 5+ validated principles in knowledge base             │
  │  [x] 168+ hours (7 days) elapsed                           │
  └──────────────────────┬──────────────────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────────────────┐
  │  PHASE 3: STRATEGIST                                       │
  │  Duration: Days 7-21                                       │
  │  LLM Mode: SIZING (influences position size)               │
  │  Curriculum: Level 3 - Predictive Modeling                 │
  │  Learning: ACTIVE                                          │
  │  Money: Small stake ($50-200, paper-validated positions)    │
  │                                                            │
  │  Goals:                                                    │
  │  - 30+ predictions made with 55%+ accuracy                 │
  │  - Sizing uplift is positive (LLM sizing > baseline)       │
  │  - Win rate stable or improved (+/- 5%)                    │
  │  - Build 3+ sniper trade profiles                          │
  │  - Signal analysis accuracy 60%+                           │
  │  - Knowledge base: 20+ entries, 10+ validated              │
  │                                                            │
  │  Gate to Phase 4:                                          │
  │  [x] 30+ predictions at 55%+ accuracy                      │
  │  [x] Sizing uplift positive (net $ positive)               │
  │  [x] Win rate not degraded more than 5%                    │
  │  [x] Signal analysis accuracy >= 60%                       │
  │  [x] 3+ sniper profiles built                              │
  │  [x] 504+ hours (21 days) elapsed                          │
  └──────────────────────┬──────────────────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────────────────┐
  │  PHASE 4: OPERATOR                                         │
  │  Duration: Days 21-45                                      │
  │  LLM Mode: DIRECTION (picks trade direction)               │
  │  Curriculum: Level 4 - Sniper Replication                  │
  │  Learning: GRADUATED                                       │
  │  Money: Moderate stake ($200-1000)                         │
  │                                                            │
  │  Goals:                                                    │
  │  - Direction uplift positive                               │
  │  - Profit factor >= 1.2                                    │
  │  - No major drawdowns from LLM decisions                   │
  │  - 5+ sniper profiles with proven track records            │
  │  - Signal analysis accuracy 65%+                           │
  │  - Proposed 3+ novel trading rules                         │
  │                                                            │
  │  Gate to Phase 5:                                          │
  │  [x] Direction uplift positive                              │
  │  [x] Profit factor >= baseline * 0.9                       │
  │  [x] No consecutive error bursts (< 3)                     │
  │  [x] Signal analysis accuracy >= 65%                       │
  │  [x] Error rate < 5%                                       │
  │  [x] 1080+ hours (45 days) elapsed                         │
  └──────────────────────┬──────────────────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────────────────┐
  │  PHASE 5: AUTONOMOUS EXPERT                                │
  │  Duration: Day 45+                                         │
  │  LLM Mode: FULL (direction + sizing)                       │
  │  Curriculum: Level 5 - Strategy Synthesis                  │
  │  Learning: CONTINUOUSLY IMPROVING                          │
  │  Money: Full allocation                                    │
  │                                                            │
  │  The LLM is now a fully learned team member:               │
  │  - Drives direction and sizing decisions                   │
  │  - Proposes new trading rules and strategies               │
  │  - Self-monitors and auto-degrades if performance drops    │
  │  - Still bounded by risk engine (never bypasses safety)    │
  │                                                            │
  │  Auto-demotion triggers:                                   │
  │  - Win rate drops below 45% over 50 trades -> Phase 4      │
  │  - 3+ consecutive error bursts -> Phase 3                  │
  │  - Daily loss > 8% -> Phase 2 (emergency)                  │
  └─────────────────────────────────────────────────────────────┘

The LLM only gets real money attached AFTER Phase 2 (minimum 7 days
of proven accuracy). It only gets full autonomy after 45+ days of
demonstrated value at every level.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List

logger = logging.getLogger("bot.llm.knowledge_roadmap")

_ROADMAP_STATE_PATH = os.path.join("data", "llm", "roadmap_state.json")


# ═══════════════════════════════════════════════════════════════
# Roadmap Phase Definitions
# ═══════════════════════════════════════════════════════════════

PHASE_CONFIGS = {
    1: {
        "name": "OBSERVER",
        "llm_mode": 1,  # ADVISORY
        "curriculum_level": 1,
        "learning_phase": "ABSORB",
        "money_allowed": False,
        "max_stake_usd": 0,
        "description": "Pure observation. LLM watches everything, blocks nothing.",
        "min_hours": 48,
        "gates": {
            "signals_observed": 50,
            "trades_observed": 20,
            "pattern_library_size": 10,
            "strategies_fingerprinted": 4,
        },
    },
    2: {
        "name": "ANALYST",
        "llm_mode": 2,  # VETO_ONLY
        "curriculum_level": 2,
        "learning_phase": "APPRENTICE",
        "money_allowed": False,
        "max_stake_usd": 0,
        "description": "Can veto bad trades. Testing hypotheses. Building causal models.",
        "min_hours": 168,  # 7 days
        "gates": {
            "hypotheses_tested": 10,
            "counterfactual_accuracy": 0.55,
            "veto_accuracy": 0.55,
            "signal_analysis_accuracy": 0.55,
            "validated_principles": 5,
        },
    },
    3: {
        "name": "STRATEGIST",
        "llm_mode": 3,  # SIZING
        "curriculum_level": 3,
        "learning_phase": "ACTIVE",
        "money_allowed": True,
        "max_stake_usd": 200,
        "description": "Influences position sizing. Small real money to validate.",
        "min_hours": 504,  # 21 days
        "gates": {
            "predictions_at_55pct": 30,
            "sizing_uplift_positive": True,
            "win_rate_stable": True,
            "signal_analysis_accuracy": 0.60,
            "sniper_profiles": 3,
        },
    },
    4: {
        "name": "OPERATOR",
        "llm_mode": 4,  # DIRECTION
        "curriculum_level": 4,
        "learning_phase": "GRADUATED",
        "money_allowed": True,
        "max_stake_usd": 1000,
        "description": "Picks trade direction. Moderate stake with proven track record.",
        "min_hours": 1080,  # 45 days
        "gates": {
            "direction_uplift_positive": True,
            "profit_factor_ok": True,
            "no_error_bursts": True,
            "signal_analysis_accuracy": 0.65,
            "error_rate_under_5pct": True,
        },
    },
    5: {
        "name": "AUTONOMOUS EXPERT",
        "llm_mode": 5,  # FULL
        "curriculum_level": 5,
        "learning_phase": "CONTINUOUSLY_IMPROVING",
        "money_allowed": True,
        "max_stake_usd": -1,  # unlimited (within risk rules)
        "description": "Full autonomy. Drives direction + sizing. Self-improving.",
        "min_hours": 0,  # no minimum once reached
        "gates": {},  # final phase, no gates
    },
}


@dataclass
class RoadmapState:
    """Persistent state of the knowledge roadmap."""
    current_phase: int = 1
    phase_started_at: float = 0.0
    roadmap_started_at: float = 0.0
    phase_history: List[Dict] = field(default_factory=list)

    # Gate status (cached from last evaluation)
    last_gate_check: float = 0.0
    last_gate_results: Dict[str, Any] = field(default_factory=dict)

    # Demotion tracking
    demotions: List[Dict] = field(default_factory=list)
    auto_demotion_enabled: bool = True

    # Override (for manual phase changes)
    manual_override: bool = False
    override_reason: str = ""

    @property
    def hours_in_phase(self) -> float:
        if self.phase_started_at == 0:
            return 0.0
        return (time.time() - self.phase_started_at) / 3600

    @property
    def total_hours(self) -> float:
        if self.roadmap_started_at == 0:
            return 0.0
        return (time.time() - self.roadmap_started_at) / 3600


def _load_state() -> RoadmapState:
    """Load roadmap state from disk."""
    try:
        if os.path.exists(_ROADMAP_STATE_PATH):
            with open(_ROADMAP_STATE_PATH) as f:
                data = json.load(f)
            state = RoadmapState()
            for key, val in data.items():
                if hasattr(state, key):
                    setattr(state, key, val)
            return state
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[ROADMAP] Failed to load state: {e}")
    now = time.time()
    return RoadmapState(roadmap_started_at=now, phase_started_at=now)


def _save_state(state: RoadmapState):
    """Save roadmap state to disk."""
    os.makedirs(os.path.dirname(_ROADMAP_STATE_PATH), exist_ok=True)
    try:
        data = {
            "current_phase": state.current_phase,
            "phase_started_at": state.phase_started_at,
            "roadmap_started_at": state.roadmap_started_at,
            "phase_history": state.phase_history[-50:],
            "last_gate_check": state.last_gate_check,
            "last_gate_results": state.last_gate_results,
            "demotions": state.demotions[-20:],
            "auto_demotion_enabled": state.auto_demotion_enabled,
            "manual_override": state.manual_override,
            "override_reason": state.override_reason,
        }
        with open(_ROADMAP_STATE_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except IOError as e:
        logger.warning(f"[ROADMAP] Failed to save state: {e}")


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_state: Optional[RoadmapState] = None


def get_roadmap_state() -> RoadmapState:
    global _state
    if _state is None:
        _state = _load_state()
    return _state


# ═══════════════════════════════════════════════════════════════
# Gate Evaluation
# ═══════════════════════════════════════════════════════════════


def _evaluate_phase1_gates(state: RoadmapState) -> Dict[str, Dict]:
    """Evaluate Phase 1 (OBSERVER) graduation gates."""
    gates = {}

    # Get learning state
    try:
        from llm.learning_mode import get_learning_state
        ls = get_learning_state()
    except Exception:
        ls = None

    # Get teaching engine
    try:
        from llm.self_teaching import get_teaching_engine
        te = get_teaching_engine()
        kb_stats = te.knowledge.get_stats()
    except Exception:
        te = None
        kb_stats = {}

    # Get deep memory
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        fps = dm.strategy_fps.get_all()
    except Exception:
        dm = None
        fps = {}

    signals_observed = ls.signals_observed if ls else 0
    trades_observed = ls.trades_observed if ls else 0
    pattern_count = kb_stats.get("total_entries", 0)
    strategies_fp = len([s for s, d in fps.items() if d.get("total", 0) >= 3])

    gates["signals_observed"] = {
        "passed": signals_observed >= 50,
        "current": signals_observed,
        "required": 50,
        "description": "Signals observed",
    }
    gates["trades_observed"] = {
        "passed": trades_observed >= 20,
        "current": trades_observed,
        "required": 20,
        "description": "Trades observed to completion",
    }
    gates["pattern_library"] = {
        "passed": pattern_count >= 10,
        "current": pattern_count,
        "required": 10,
        "description": "Knowledge base entries",
    }
    gates["strategies_fingerprinted"] = {
        "passed": strategies_fp >= 4,
        "current": strategies_fp,
        "required": 4,
        "description": "Strategies with fingerprints (3+ trades each)",
    }
    gates["min_hours"] = {
        "passed": state.hours_in_phase >= 48,
        "current": round(state.hours_in_phase, 1),
        "required": 48,
        "description": "Hours in phase",
    }

    return gates


def _evaluate_phase2_gates(state: RoadmapState) -> Dict[str, Dict]:
    """Evaluate Phase 2 (ANALYST) graduation gates."""
    gates = {}

    try:
        from llm.learning_mode import get_learning_state
        ls = get_learning_state()
    except Exception:
        ls = None

    try:
        from llm.self_teaching import get_teaching_engine
        te = get_teaching_engine()
        curr = te.curriculum
        kb = te.knowledge
    except Exception:
        te = None
        curr = None
        kb = None

    try:
        from signals.llm_analyzer import get_analysis_accuracy
        analysis_acc = get_analysis_accuracy()
    except Exception:
        analysis_acc = {"overall_accuracy": 0, "total_analyses": 0}

    hyp_tested = 0
    if curr:
        hyp_tested = curr.hypotheses_validated + curr.hypotheses_invalidated

    cf_accuracy = ls.counterfactual_accuracy if ls else 0
    validated_principles = 0
    if kb:
        principles = kb.get_principles(min_confidence=0.6)
        validated_principles = sum(1 for p in principles if p.get("validation_count", 0) >= 2)

    sig_acc = analysis_acc.get("overall_accuracy", 0)

    gates["hypotheses_tested"] = {
        "passed": hyp_tested >= 10,
        "current": hyp_tested,
        "required": 10,
        "description": "Hypotheses tested (validated + invalidated)",
    }
    gates["counterfactual_accuracy"] = {
        "passed": cf_accuracy >= 0.55,
        "current": f"{cf_accuracy:.0%}",
        "required": "55%",
        "description": "LLM counterfactual accuracy",
    }
    gates["veto_accuracy"] = {
        "passed": cf_accuracy >= 0.55,  # same metric in VETO_ONLY mode
        "current": f"{cf_accuracy:.0%}",
        "required": "55%",
        "description": "Veto accuracy (vetoes that were correct)",
    }
    gates["signal_analysis_accuracy"] = {
        "passed": sig_acc >= 0.55 or analysis_acc.get("total_analyses", 0) < 10,
        "current": f"{sig_acc:.0%}" if analysis_acc.get("total_analyses", 0) >= 10 else "insufficient data",
        "required": "55%",
        "description": "Signal analysis verdict accuracy",
    }
    gates["validated_principles"] = {
        "passed": validated_principles >= 5,
        "current": validated_principles,
        "required": 5,
        "description": "Validated principles in knowledge base",
    }
    gates["min_hours"] = {
        "passed": state.hours_in_phase >= 168,
        "current": round(state.hours_in_phase, 1),
        "required": 168,
        "description": "Hours in phase (7 days)",
    }

    return gates


def _evaluate_phase3_gates(state: RoadmapState) -> Dict[str, Dict]:
    """Evaluate Phase 3 (STRATEGIST) graduation gates."""
    gates = {}

    try:
        from llm.self_teaching import get_teaching_engine
        te = get_teaching_engine()
        curr = te.curriculum
    except Exception:
        curr = None

    try:
        from llm.uplift_analytics import compute_uplift
        analytics = compute_uplift()
    except Exception:
        analytics = {}

    try:
        from signals.llm_analyzer import get_analysis_accuracy
        analysis_acc = get_analysis_accuracy()
    except Exception:
        analysis_acc = {"overall_accuracy": 0}

    pred_acc = curr.prediction_accuracy if curr else 0
    pred_count = curr.predictions_made if curr else 0
    sniper_count = curr.sniper_profiles_built if curr else 0

    uplift = analytics.get("uplift", {})
    sizing_positive = uplift.get("is_positive", False)
    wr_delta = uplift.get("win_rate_delta", 0)
    sig_acc = analysis_acc.get("overall_accuracy", 0)

    gates["predictions_at_55pct"] = {
        "passed": pred_count >= 30 and pred_acc >= 0.55,
        "current": f"{pred_count} predictions at {pred_acc:.0%}",
        "required": "30+ at 55%+",
        "description": "Prediction count and accuracy",
    }
    gates["sizing_uplift_positive"] = {
        "passed": sizing_positive,
        "current": f"${uplift.get('avg_pnl_delta', 0):+.2f}",
        "required": ">$0",
        "description": "LLM sizing improves average PnL",
    }
    gates["win_rate_stable"] = {
        "passed": wr_delta >= -0.05,
        "current": f"{wr_delta:+.1%}",
        "required": ">= -5%",
        "description": "Win rate not degraded",
    }
    gates["signal_analysis_accuracy"] = {
        "passed": sig_acc >= 0.60 or analysis_acc.get("total_analyses", 0) < 20,
        "current": f"{sig_acc:.0%}",
        "required": "60%",
        "description": "Signal analysis verdict accuracy",
    }
    gates["sniper_profiles"] = {
        "passed": sniper_count >= 3,
        "current": sniper_count,
        "required": 3,
        "description": "Sniper trade profiles built",
    }
    gates["min_hours"] = {
        "passed": state.hours_in_phase >= 504,
        "current": round(state.hours_in_phase, 1),
        "required": 504,
        "description": "Hours in phase (21 days)",
    }

    return gates


def _evaluate_phase4_gates(state: RoadmapState) -> Dict[str, Dict]:
    """Evaluate Phase 4 (OPERATOR) graduation gates."""
    gates = {}

    try:
        from llm.uplift_analytics import compute_uplift
        analytics = compute_uplift()
    except Exception:
        analytics = {}

    try:
        from llm.recovery import get_error_stats
        err = get_error_stats()
    except Exception:
        err = type('', (), {"error_rate": 100, "consecutive_errors": 99})()

    try:
        from signals.llm_analyzer import get_analysis_accuracy
        analysis_acc = get_analysis_accuracy()
    except Exception:
        analysis_acc = {"overall_accuracy": 0}

    uplift = analytics.get("uplift", {})
    direction_positive = uplift.get("is_positive", False)

    baseline_pf = analytics.get("baseline", {}).get("profit_factor", 0)
    llm_pf = analytics.get("llm_filtered", {}).get("profit_factor", 0)
    pf_ok = True
    if baseline_pf > 0 and llm_pf > 0 and baseline_pf != float("inf") and llm_pf != float("inf"):
        pf_ok = llm_pf >= baseline_pf * 0.9

    sig_acc = analysis_acc.get("overall_accuracy", 0)

    gates["direction_uplift_positive"] = {
        "passed": direction_positive,
        "current": f"${uplift.get('avg_pnl_delta', 0):+.2f}",
        "required": ">$0",
        "description": "Direction overrides improve PnL",
    }
    gates["profit_factor_ok"] = {
        "passed": pf_ok,
        "current": f"{llm_pf:.2f}" if llm_pf != float("inf") else "inf",
        "required": f">= {baseline_pf * 0.9:.2f}" if baseline_pf > 0 else "n/a",
        "description": "Profit factor not degraded",
    }
    gates["no_error_bursts"] = {
        "passed": err.consecutive_errors < 3,
        "current": err.consecutive_errors,
        "required": "< 3",
        "description": "No consecutive LLM error bursts",
    }
    gates["signal_analysis_accuracy"] = {
        "passed": sig_acc >= 0.65 or analysis_acc.get("total_analyses", 0) < 30,
        "current": f"{sig_acc:.0%}",
        "required": "65%",
        "description": "Signal analysis verdict accuracy",
    }
    gates["error_rate_under_5pct"] = {
        "passed": err.error_rate < 5.0,
        "current": f"{err.error_rate:.1f}%",
        "required": "< 5%",
        "description": "LLM API error rate",
    }
    gates["min_hours"] = {
        "passed": state.hours_in_phase >= 1080,
        "current": round(state.hours_in_phase, 1),
        "required": 1080,
        "description": "Hours in phase (45 days)",
    }

    return gates


def evaluate_gates() -> Dict[str, Any]:
    """Evaluate current phase gates and check for promotion readiness.

    Returns gate results and whether promotion is available.
    """
    state = get_roadmap_state()
    phase = state.current_phase

    if phase >= 5:
        return {
            "phase": 5,
            "phase_name": "AUTONOMOUS EXPERT",
            "all_passed": True,
            "gates": {},
            "promotion_available": False,
            "message": "Already at maximum phase. Continuously improving.",
        }

    evaluators = {
        1: _evaluate_phase1_gates,
        2: _evaluate_phase2_gates,
        3: _evaluate_phase3_gates,
        4: _evaluate_phase4_gates,
    }

    evaluator = evaluators.get(phase)
    if not evaluator:
        return {"error": f"Unknown phase {phase}"}

    gates = evaluator(state)
    all_passed = all(g["passed"] for g in gates.values())

    config = PHASE_CONFIGS[phase]

    result = {
        "phase": phase,
        "phase_name": config["name"],
        "hours_in_phase": round(state.hours_in_phase, 1),
        "total_hours": round(state.total_hours, 1),
        "all_passed": all_passed,
        "gates": gates,
        "passed_count": sum(1 for g in gates.values() if g["passed"]),
        "total_gates": len(gates),
        "promotion_available": all_passed,
        "next_phase": phase + 1 if all_passed else None,
        "next_phase_name": PHASE_CONFIGS.get(phase + 1, {}).get("name", ""),
    }

    # Cache results
    state.last_gate_check = time.time()
    state.last_gate_results = result
    _save_state(state)

    return result


# ═══════════════════════════════════════════════════════════════
# Phase Transitions
# ═══════════════════════════════════════════════════════════════


def promote_phase() -> Dict[str, Any]:
    """Promote to the next phase if all gates pass."""
    state = get_roadmap_state()
    current = state.current_phase

    if current >= 5:
        return {"success": False, "reason": "Already at maximum phase"}

    gate_result = evaluate_gates()
    if not gate_result.get("all_passed"):
        failed = [
            f"{name}: {g['current']} (need {g['required']})"
            for name, g in gate_result.get("gates", {}).items()
            if not g["passed"]
        ]
        return {
            "success": False,
            "reason": f"Not all gates passed. Failed: {'; '.join(failed)}",
        }

    next_phase = current + 1
    next_config = PHASE_CONFIGS[next_phase]

    state.phase_history.append({
        "from_phase": current,
        "to_phase": next_phase,
        "at": time.time(),
        "hours_spent": round(state.hours_in_phase, 1),
        "gate_results": gate_result.get("gates", {}),
    })

    state.current_phase = next_phase
    state.phase_started_at = time.time()
    state.manual_override = False
    _save_state(state)

    logger.info(
        f"[ROADMAP] PROMOTED: Phase {current} ({PHASE_CONFIGS[current]['name']}) -> "
        f"Phase {next_phase} ({next_config['name']}) after {state.hours_in_phase:.0f}h"
    )

    return {
        "success": True,
        "from_phase": current,
        "to_phase": next_phase,
        "phase_name": next_config["name"],
        "llm_mode": next_config["llm_mode"],
        "money_allowed": next_config["money_allowed"],
        "max_stake_usd": next_config["max_stake_usd"],
    }


def demote_phase(target_phase: int, reason: str) -> Dict[str, Any]:
    """Demote to a lower phase (manual or auto-triggered)."""
    state = get_roadmap_state()
    current = state.current_phase

    if target_phase >= current:
        return {"success": False, "reason": f"Can only demote to lower phase (current={current})"}
    if target_phase < 1:
        target_phase = 1

    target_config = PHASE_CONFIGS[target_phase]

    state.demotions.append({
        "from_phase": current,
        "to_phase": target_phase,
        "reason": reason,
        "at": time.time(),
    })
    state.phase_history.append({
        "from_phase": current,
        "to_phase": target_phase,
        "at": time.time(),
        "hours_spent": round(state.hours_in_phase, 1),
        "type": "demotion",
        "reason": reason,
    })

    state.current_phase = target_phase
    state.phase_started_at = time.time()
    _save_state(state)

    logger.warning(
        f"[ROADMAP] DEMOTED: Phase {current} -> Phase {target_phase} "
        f"({target_config['name']}). Reason: {reason}"
    )

    return {
        "success": True,
        "from_phase": current,
        "to_phase": target_phase,
        "phase_name": target_config["name"],
        "reason": reason,
    }


def force_phase(phase: int, reason: str = "manual override") -> Dict[str, Any]:
    """Force set a specific phase (bypass gates)."""
    if phase < 1 or phase > 5:
        return {"success": False, "reason": "Phase must be 1-5"}

    state = get_roadmap_state()
    old_phase = state.current_phase

    state.current_phase = phase
    state.phase_started_at = time.time()
    state.manual_override = True
    state.override_reason = reason
    state.phase_history.append({
        "from_phase": old_phase,
        "to_phase": phase,
        "at": time.time(),
        "type": "manual_override",
        "reason": reason,
    })
    _save_state(state)

    config = PHASE_CONFIGS[phase]
    logger.info(f"[ROADMAP] Manual override: Phase {old_phase} -> Phase {phase} ({config['name']})")

    return {
        "success": True,
        "phase": phase,
        "phase_name": config["name"],
        "reason": reason,
    }


# ═══════════════════════════════════════════════════════════════
# Auto-demotion checks
# ═══════════════════════════════════════════════════════════════


def check_auto_demotion() -> Optional[Dict[str, Any]]:
    """Check if performance warrants automatic demotion.

    Called periodically by the main loop. Returns demotion info if triggered.
    """
    state = get_roadmap_state()

    if not state.auto_demotion_enabled or state.current_phase <= 1:
        return None

    try:
        from llm.recovery import get_error_stats
        err = get_error_stats()
    except Exception:
        return None

    # Auto-demotion: 3+ consecutive error bursts -> drop 2 phases
    if err.consecutive_errors >= 3 and state.current_phase >= 3:
        return demote_phase(
            max(1, state.current_phase - 2),
            f"Auto-demotion: {err.consecutive_errors} consecutive LLM errors"
        )

    # Check win rate degradation (needs enough data)
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        stats = dm.trade_dna.get_summary_stats()
        if stats.get("total_trades", 0) >= 50:
            wr = stats.get("win_rate", 0)
            if wr < 0.45 and state.current_phase >= 4:
                return demote_phase(
                    3,
                    f"Auto-demotion: Win rate {wr:.0%} < 45% over {stats['total_trades']} trades"
                )
    except Exception:
        pass

    return None


# ═══════════════════════════════════════════════════════════════
# Status & Reporting
# ═══════════════════════════════════════════════════════════════


def get_roadmap_config() -> Dict[str, Any]:
    """Get the current phase configuration."""
    state = get_roadmap_state()
    return PHASE_CONFIGS.get(state.current_phase, PHASE_CONFIGS[1])


def get_recommended_llm_mode() -> int:
    """Get the LLM mode recommended by the current roadmap phase."""
    config = get_roadmap_config()
    return config["llm_mode"]


def is_money_allowed() -> bool:
    """Check if the current phase allows real money."""
    config = get_roadmap_config()
    return config.get("money_allowed", False)


def get_max_stake() -> float:
    """Get maximum allowed stake for current phase."""
    config = get_roadmap_config()
    return config.get("max_stake_usd", 0)


def format_roadmap_status() -> str:
    """Format roadmap status for Telegram/console display."""
    state = get_roadmap_state()
    config = PHASE_CONFIGS.get(state.current_phase, {})
    gate_result = evaluate_gates()

    lines = [
        f"*LLM Knowledge Roadmap*",
        f"",
        f"*Phase {state.current_phase}: {config.get('name', '?')}*",
        f"{config.get('description', '')}",
        f"",
        f"Hours in phase: {state.hours_in_phase:.0f}h / {config.get('min_hours', 0)}h",
        f"Total hours: {state.total_hours:.0f}h",
        f"LLM Mode: {config.get('llm_mode', 0)}",
        f"Money: {'${:,.0f} max'.format(config.get('max_stake_usd', 0)) if config.get('money_allowed') else 'Not yet'}",
    ]

    if state.manual_override:
        lines.append(f"(Manual override: {state.override_reason})")

    gates = gate_result.get("gates", {})
    if gates:
        lines.append("")
        lines.append(f"*Graduation Gates ({gate_result.get('passed_count', 0)}/{gate_result.get('total_gates', 0)}):*")
        for name, g in gates.items():
            status = "PASS" if g["passed"] else "FAIL"
            lines.append(f"  [{status}] {g['description']}: {g['current']} (need {g['required']})")

    if gate_result.get("promotion_available"):
        next_name = gate_result.get("next_phase_name", "?")
        lines.append("")
        lines.append(f"READY TO PROMOTE to Phase {gate_result.get('next_phase', '?')}: {next_name}")
        lines.append("Use /promote to advance")

    if state.demotions:
        last_demo = state.demotions[-1]
        lines.append("")
        lines.append(f"Last demotion: Phase {last_demo['from_phase']} -> {last_demo['to_phase']}")
        lines.append(f"Reason: {last_demo['reason']}")

    return "\n".join(lines)


def format_roadmap_overview() -> str:
    """Format the full roadmap overview showing all phases."""
    state = get_roadmap_state()
    current = state.current_phase

    lines = [
        "*LLM Knowledge Roadmap Overview*",
        "",
    ]

    for phase_num, config in PHASE_CONFIGS.items():
        if phase_num < current:
            status = "COMPLETED"
        elif phase_num == current:
            status = "CURRENT"
        else:
            status = "LOCKED"

        money = ""
        if config["money_allowed"]:
            if config["max_stake_usd"] < 0:
                money = " | Full allocation"
            else:
                money = f" | Max ${config['max_stake_usd']:,.0f}"
        else:
            money = " | Paper only"

        lines.append(
            f"[{status}] Phase {phase_num}: {config['name']}"
            f"{money}"
        )
        if phase_num == current:
            lines.append(f"  -> {config['description']}")
            lines.append(f"  -> {state.hours_in_phase:.0f}h elapsed")

    lines.extend([
        "",
        f"Total time: {state.total_hours:.0f}h",
        f"Demotions: {len(state.demotions)}",
    ])

    return "\n".join(lines)
