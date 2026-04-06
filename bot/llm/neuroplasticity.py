"""
Neuroplasticity Engine: The brain's ability to rewire from experience.

This module orchestrates all learning and adaptation mechanisms:

1. SYNAPTIC STRENGTHENING — setup edges strengthen/weaken based on outcomes
2. CONSOLIDATION — observations compress into principles after enough evidence
3. FORGETTING — knowledge decays if not reinforced (prevents stale anchoring)
4. SURPRISE LEARNING — unexpected outcomes trigger deeper analysis
5. CURRICULUM PROGRESSION — advance through learning levels as competence grows
6. EDGE METABOLISM — detect when edges are being consumed by the market

Runs periodically (every 30-60 min) and after every trade close.
"""

import json
import logging
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("bot.llm.neuroplasticity")

_STATE_PATH = os.path.join("data", "llm", "neuroplasticity_state.json")


def _load_state() -> Dict:
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "setup_edges": {},       # setup_key → {wr, n, last_updated, trend}
        "surprise_log": [],      # unexpected outcomes for deep learning
        "consolidation_queue": [],  # observations pending consolidation
        "edge_decay_alerts": [],
        "last_run": 0,
        "total_runs": 0,
    }


def _save_state(state: Dict):
    try:
        os.makedirs(os.path.dirname(_STATE_PATH) or ".", exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"Neuroplasticity state save error: {e}")


# ═══════════════════════════════════════════════════════════════
# 1. SYNAPTIC STRENGTHENING
# ═══════════════════════════════════════════════════════════════

def strengthen_setup(state: Dict, setup_key: str, won: bool, pnl_pct: float = 0):
    """Strengthen or weaken a setup's edge based on trade outcome.

    Uses exponential moving average — recent outcomes matter more.
    """
    edges = state.setdefault("setup_edges", {})
    edge = edges.get(setup_key, {"wr": 0.5, "n": 0, "ema_wr": 0.5, "pnl_sum": 0})

    # EMA with alpha that decreases as we get more data (more stable over time)
    alpha = max(0.05, 1.0 / (edge["n"] + 1))
    edge["ema_wr"] = alpha * (1.0 if won else 0.0) + (1 - alpha) * edge.get("ema_wr", 0.5)
    edge["n"] += 1
    edge["pnl_sum"] = edge.get("pnl_sum", 0) + pnl_pct
    edge["last_updated"] = time.time()

    # Track WR trend (is this setup getting better or worse?)
    raw_wr = edge.get("raw_wins", 0) / max(edge["n"], 1)
    edge["raw_wins"] = edge.get("raw_wins", 0) + (1 if won else 0)
    new_raw_wr = edge["raw_wins"] / edge["n"]
    edge["wr"] = new_raw_wr
    edge["trend"] = "strengthening" if edge["ema_wr"] > new_raw_wr else "weakening"

    edges[setup_key] = edge

    logger.info(
        f"[NEURO] SYNAPSE {setup_key}: {'WIN' if won else 'LOSS'} -> "
        f"WR={new_raw_wr:.1%} EMA={edge['ema_wr']:.1%} n={edge['n']} "
        f"trend={edge['trend']}"
    )


def get_setup_strength(state: Dict, setup_key: str) -> Dict:
    """Get the current strength of a setup.

    Returns dict with wr, ema_wr, n, trend, sizing_mult.
    """
    edge = state.get("setup_edges", {}).get(setup_key)
    if not edge or edge["n"] < 3:
        return {"wr": 0.5, "ema_wr": 0.5, "n": 0, "trend": "unknown", "sizing_mult": 1.0}

    # Sizing multiplier based on EMA WR
    ema = edge["ema_wr"]
    if ema >= 0.65:
        sizing_mult = 1.3
    elif ema >= 0.55:
        sizing_mult = 1.1
    elif ema >= 0.45:
        sizing_mult = 0.9
    elif ema >= 0.35:
        sizing_mult = 0.6
    else:
        sizing_mult = 0.3

    return {
        "wr": edge["wr"],
        "ema_wr": edge["ema_wr"],
        "n": edge["n"],
        "trend": edge["trend"],
        "sizing_mult": sizing_mult,
    }


# ═══════════════════════════════════════════════════════════════
# 2. CONSOLIDATION (observations → principles)
# ═══════════════════════════════════════════════════════════════

def add_observation(state: Dict, observation: str, category: str,
                    symbol: str = "", regime: str = ""):
    """Queue an observation for potential consolidation into a principle."""
    queue = state.setdefault("consolidation_queue", [])
    queue.append({
        "text": observation[:200],
        "category": category,
        "symbol": symbol,
        "regime": regime,
        "ts": time.time(),
    })
    # Keep queue bounded
    if len(queue) > 500:
        state["consolidation_queue"] = queue[-300:]


def run_consolidation(state: Dict) -> List[Dict]:
    """Consolidate repeated observations into principles.

    If 5+ similar observations exist, compress them into one principle.
    This is how the brain forms generalizations from specific experiences.
    """
    queue = state.get("consolidation_queue", [])
    if len(queue) < 10:
        return []

    # Group by category + symbol
    groups = defaultdict(list)
    for obs in queue:
        key = f"{obs['category']}_{obs.get('symbol', '')}"
        groups[key].append(obs)

    consolidated = []
    for key, observations in groups.items():
        if len(observations) >= 5:
            # Enough evidence — form a principle
            texts = [o["text"] for o in observations]
            # Simple consolidation: find common theme
            category = observations[0]["category"]
            symbol = observations[0].get("symbol", "")

            principle = {
                "type": "principle",
                "content": f"[{category}] Pattern from {len(observations)} observations: {texts[0]}",
                "evidence_count": len(observations),
                "category": category,
                "symbol": symbol,
                "consolidated_from": len(observations),
            }
            consolidated.append(principle)

            # Inject into knowledge base
            try:
                from llm.self_teaching import get_teaching_engine
                engine = get_teaching_engine()
                engine.knowledge.add(
                    knowledge_type="principle",
                    content=principle["content"][:200],
                    confidence=min(0.9, 0.5 + len(observations) * 0.05),
                    category=category,
                    source="consolidation",
                    evidence=f"{len(observations)} observations",
                )
            except Exception as e:
                logger.debug(f"Consolidation KB injection error: {e}")

            # Remove consolidated observations from queue
            remaining = [o for o in queue if f"{o['category']}_{o.get('symbol', '')}" != key]
            state["consolidation_queue"] = remaining

            logger.info(
                f"[NEURO] CONSOLIDATED: {len(observations)} observations -> principle: "
                f"{principle['content'][:80]}"
            )

    return consolidated


# ═══════════════════════════════════════════════════════════════
# 3. FORGETTING (knowledge decay)
# ═══════════════════════════════════════════════════════════════

def decay_knowledge(max_age_days: int = 30):
    """Decay old knowledge that hasn't been reinforced.

    Knowledge entries that haven't been validated/updated in max_age_days
    get their confidence reduced. If confidence drops below 0.3, they're
    marked as stale and eventually removed.

    This prevents the brain from anchoring to outdated edges.
    """
    try:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()
        kb = engine.knowledge
        kb._ensure_loaded()

        now = time.time()
        max_age_s = max_age_days * 86400
        decayed = 0

        for entry in kb._entries:
            if entry.get("knowledge_type") == "axiom":
                continue  # Axioms never decay

            last_validated = entry.get("last_validated", entry.get("created_at", 0))
            age = now - last_validated

            if age > max_age_s:
                old_conf = entry.get("confidence", 0.5)
                # Decay by 10% per period past max age
                periods_overdue = age / max_age_s
                decay_factor = max(0.1, 1.0 - (periods_overdue - 1) * 0.1)
                new_conf = old_conf * decay_factor

                if new_conf < 0.3:
                    entry["stale"] = True
                entry["confidence"] = round(new_conf, 3)
                decayed += 1

        if decayed > 0:
            kb._save()
            logger.info(f"[NEURO] DECAY: {decayed} knowledge entries decayed")

    except Exception as e:
        logger.debug(f"Knowledge decay error: {e}")


# ═══════════════════════════════════════════════════════════════
# 4. SURPRISE LEARNING
# ═══════════════════════════════════════════════════════════════

def detect_surprise(state: Dict, setup_key: str, won: bool,
                    expected_wr: float) -> Optional[Dict]:
    """Detect when an outcome is surprising and trigger deeper learning.

    Surprise = actual outcome differs significantly from expected.
    The brain learns MORE from surprises than from expected outcomes.
    """
    # Expected win, got loss (or vice versa)
    expected_win = expected_wr > 0.55
    surprise_magnitude = 0

    if expected_win and not won:
        # Expected to win but lost — investigate why
        surprise_magnitude = expected_wr - 0.5  # Higher expected WR = more surprising
    elif not expected_win and won:
        # Expected to lose but won — found hidden edge?
        surprise_magnitude = 0.5 - expected_wr

    if surprise_magnitude < 0.1:
        return None  # Not surprising enough

    surprise = {
        "setup": setup_key,
        "expected_wr": expected_wr,
        "actual": "win" if won else "loss",
        "surprise_magnitude": round(surprise_magnitude, 3),
        "ts": time.time(),
        "investigation_needed": surprise_magnitude > 0.2,
    }

    state.setdefault("surprise_log", []).append(surprise)
    # Keep bounded
    if len(state["surprise_log"]) > 100:
        state["surprise_log"] = state["surprise_log"][-50:]

    if surprise["investigation_needed"]:
        logger.warning(
            f"[NEURO] SURPRISE: {setup_key} expected {expected_wr:.0%} WR "
            f"but {'won' if won else 'lost'} (magnitude={surprise_magnitude:.2f}). "
            f"INVESTIGATION NEEDED."
        )

        # Add to knowledge base as observation for later consolidation
        add_observation(
            state,
            f"Surprise {setup_key}: expected {'win' if expected_win else 'loss'} "
            f"at {expected_wr:.0%} but {'won' if won else 'lost'}",
            category="surprise",
            symbol=setup_key.split("_")[0] if "_" in setup_key else "",
        )

    return surprise


# ═══════════════════════════════════════════════════════════════
# 5. CURRICULUM PROGRESSION
# ═══════════════════════════════════════════════════════════════

def check_curriculum_advancement() -> Optional[Dict]:
    """Check if the LLM should advance to the next curriculum level.

    Level advancement criteria (from self_teaching.py):
    1→2: 20+ trades analyzed, 5+ patterns found
    2→3: 50+ trades, 3+ validated hypotheses
    3→4: 100+ trades, 70%+ prediction accuracy
    4→5: 200+ trades, 3+ sniper profiles, 60%+ replication rate
    """
    try:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()
        report = engine.get_curriculum_report()

        if not report:
            return None

        curriculum = report.get("curriculum", {})
        level = curriculum.get("level", 1)
        trades = curriculum.get("trades_analyzed", 0)
        hypotheses_validated = curriculum.get("hypotheses_validated", 0)
        prediction_accuracy = curriculum.get("prediction_accuracy", 0)
        sniper_profiles = curriculum.get("sniper_profiles", 0)

        should_advance = False
        reason = ""

        if level == 1 and trades >= 20:
            should_advance = True
            reason = f"Level 1→2: {trades} trades analyzed (threshold: 20)"
        elif level == 2 and trades >= 50 and hypotheses_validated >= 3:
            should_advance = True
            reason = f"Level 2→3: {trades} trades, {hypotheses_validated} validated hypotheses"
        elif level == 3 and trades >= 100 and prediction_accuracy >= 0.70:
            should_advance = True
            reason = f"Level 3→4: {trades} trades, {prediction_accuracy:.0%} prediction accuracy"
        elif level == 4 and trades >= 200 and sniper_profiles >= 3:
            should_advance = True
            reason = f"Level 4→5: {trades} trades, {sniper_profiles} sniper profiles"

        if should_advance:
            # Advance the curriculum
            engine.curriculum.advance_level()
            logger.info(f"[NEURO] CURRICULUM ADVANCE: {reason}")
            return {"old_level": level, "new_level": level + 1, "reason": reason}

        return None

    except Exception as e:
        logger.debug(f"Curriculum check error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 6. EDGE METABOLISM
# ═══════════════════════════════════════════════════════════════

def detect_edge_decay(state: Dict, min_trades: int = 10) -> List[Dict]:
    """Detect setups where the edge is being consumed by the market.

    An edge decays when recent WR (EMA) drops significantly below
    historical WR. This happens when:
    - More traders discover the pattern
    - Market regime changes
    - Strategy becomes crowded
    """
    alerts = []
    edges = state.get("setup_edges", {})

    for setup_key, edge in edges.items():
        if edge["n"] < min_trades:
            continue

        historical_wr = edge["wr"]
        recent_wr = edge["ema_wr"]
        decay = historical_wr - recent_wr

        if decay > 0.10:  # 10%+ WR decay
            severity = "warning" if decay < 0.20 else "critical"
            alert = {
                "setup": setup_key,
                "historical_wr": round(historical_wr, 3),
                "recent_wr": round(recent_wr, 3),
                "decay_pct": round(decay * 100, 1),
                "severity": severity,
                "n_trades": edge["n"],
                "recommendation": "reduce_size" if severity == "warning" else "pause",
            }
            alerts.append(alert)

            logger.warning(
                f"[NEURO] EDGE DECAY: {setup_key} WR {historical_wr:.0%} -> "
                f"{recent_wr:.0%} ({decay:.0%} decay, {severity})"
            )

    state["edge_decay_alerts"] = alerts
    return alerts


# ═══════════════════════════════════════════════════════════════
# MAIN CYCLE: Run all neuroplasticity mechanisms
# ═══════════════════════════════════════════════════════════════

def run_neuroplasticity_cycle(trade_data: Optional[Dict] = None) -> Dict:
    """Run a full neuroplasticity cycle.

    Called after every trade close AND periodically (30-60 min).

    Args:
        trade_data: If provided, a closed trade to learn from.
            Keys: symbol, side, strategy, pnl, regime, strategies_agree, outcome

    Returns dict with all actions taken.
    """
    state = _load_state()
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["last_run"] = time.time()

    results = {
        "synaptic": None,
        "surprise": None,
        "consolidation": [],
        "curriculum": None,
        "edge_decay": [],
    }

    # If we have a new trade, process it through synaptic strengthening
    if trade_data:
        symbol = trade_data.get("symbol", "").replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        side = trade_data.get("side", "BUY")
        strategy = trade_data.get("strategy", "")
        strategies = trade_data.get("strategies_agree", [strategy])
        pnl = trade_data.get("pnl", 0)
        won = pnl > 0

        has_bb = "bollinger_squeeze" in strategies
        has_mtq = "multi_tier_quality" in strategies

        # Build setup key
        if has_bb and has_mtq:
            setup_key = f"{symbol}_{side}_BB+MTQ"
        elif has_bb:
            setup_key = f"{symbol}_{side}_BB"
        elif len(strategies) == 1:
            setup_key = f"{symbol}_{side}_{strategies[0]}"
        else:
            setup_key = f"{symbol}_{side}_{len(strategies)}-agree"

        # 1. Synaptic strengthening
        pnl_pct = pnl / max(trade_data.get("entry", 1), 1) * 100
        strengthen_setup(state, setup_key, won, pnl_pct)
        results["synaptic"] = {"setup": setup_key, "won": won}

        # 4. Surprise detection
        strength = get_setup_strength(state, setup_key)
        expected_wr = strength["wr"] if strength["n"] >= 5 else 0.5
        results["surprise"] = detect_surprise(state, setup_key, won, expected_wr)

        # Add observation for consolidation
        regime = trade_data.get("regime", "unknown")
        add_observation(
            state,
            f"{setup_key}: {'WIN' if won else 'LOSS'} in {regime}, pnl={pnl_pct:.2f}%",
            category="trade_outcome",
            symbol=symbol,
            regime=regime,
        )

    # 2. Consolidation (compress observations into principles)
    results["consolidation"] = run_consolidation(state)

    # 3. Knowledge decay (run less frequently — every 10 cycles)
    if state["total_runs"] % 10 == 0:
        decay_knowledge(max_age_days=30)

    # 5. Curriculum advancement check
    results["curriculum"] = check_curriculum_advancement()

    # 6. Edge metabolism (detect decaying edges)
    results["edge_decay"] = detect_edge_decay(state)

    _save_state(state)
    return results


def get_neuro_context_for_agents(symbol: str = "", side: str = "") -> str:
    """Get neuroplasticity context for agent prompt injection.

    Returns a compact string with:
    - Setup edge strengths (synaptic weights)
    - Active edge decay alerts
    - Recent surprises needing investigation
    """
    state = _load_state()
    parts = []

    # Setup strengths for this symbol
    if symbol and side:
        base_sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").split("/")[0]
        for suffix in ["_BB", "_BB+MTQ", "_2-agree", "_confidence_scorer"]:
            key = f"{base_sym}_{side}{suffix}"
            strength = get_setup_strength(state, key)
            if strength["n"] >= 3:
                parts.append(
                    f"{key}: WR={strength['wr']:.0%} EMA={strength['ema_wr']:.0%} "
                    f"n={strength['n']} trend={strength['trend']} "
                    f"size={strength['sizing_mult']:.1f}x"
                )

    # Edge decay alerts
    alerts = state.get("edge_decay_alerts", [])
    if alerts:
        for a in alerts[:3]:
            parts.append(
                f"EDGE DECAY: {a['setup']} {a['historical_wr']:.0%}->{a['recent_wr']:.0%} "
                f"({a['severity']})"
            )

    # Recent surprises
    surprises = [s for s in state.get("surprise_log", [])
                 if s.get("investigation_needed") and time.time() - s["ts"] < 86400]
    if surprises:
        for s in surprises[-2:]:
            parts.append(f"SURPRISE: {s['setup']} expected {s['expected_wr']:.0%} got {s['actual']}")

    return "\n".join(parts) if parts else ""


# Module-level singleton state (lazy loaded)
_state: Optional[Dict] = None


def get_state() -> Dict:
    global _state
    if _state is None:
        _state = _load_state()
    return _state
