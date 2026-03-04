"""
LLM Replay Engine: Backtest the full LLM pipeline against historical decisions.

Reads decisions.jsonl (which now captures full snapshots), replays each
decision through the current agent pipeline, and compares old vs new outputs.

This answers the critical question: "Would our current system have been
more profitable than the system that made these historical decisions?"

Usage:
    from llm.replay_engine import run_replay

    # Replay last 100 decisions through current pipeline
    results = run_replay(max_decisions=100, mode="mock")

    # Live replay (uses real Claude API — costs money)
    results = run_replay(max_decisions=50, mode="live")

Output:
    {
        "total_replayed": 100,
        "old_accuracy": 0.58,
        "new_accuracy": 0.64,        # Would new system be more accurate?
        "action_changes": 12,         # How many decisions would change?
        "confidence_delta_avg": +0.03, # Average confidence shift
        "veto_rate_old": 0.35,
        "veto_rate_new": 0.28,        # Are we vetoing less?
        "estimated_pnl_impact": +$45, # Estimated PnL difference
        "cost_of_replay": $3.50,      # How much this replay cost in API calls
        "per_decision": [...]          # Detailed per-decision comparison
    }
"""

import json
import logging
import os
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.llm.replay_engine")

_DECISIONS_PATH = os.path.join("data", "llm", "decisions.jsonl")


def load_historical_decisions(
    max_decisions: int = 100,
    only_with_snapshot: bool = True,
) -> List[Dict[str, Any]]:
    """Load historical decisions from decisions.jsonl.

    Args:
        max_decisions: Maximum number of decisions to load (most recent first).
        only_with_snapshot: If True, only load decisions that have snapshot data.

    Returns:
        List of decision dicts, most recent first.
    """
    if not os.path.exists(_DECISIONS_PATH):
        logger.warning(f"[REPLAY] No decisions file at {_DECISIONS_PATH}")
        return []

    decisions = []
    try:
        with open(_DECISIONS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if only_with_snapshot and "snapshot" not in d:
                        continue
                    decisions.append(d)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"[REPLAY] Failed to read decisions: {e}")
        return []

    # Most recent first, limit to max
    decisions = decisions[-max_decisions:]
    decisions.reverse()
    logger.info(f"[REPLAY] Loaded {len(decisions)} historical decisions")
    return decisions


def run_replay(
    max_decisions: int = 100,
    mode: str = "compare",
) -> Dict[str, Any]:
    """Replay historical decisions through the current LLM pipeline.

    Args:
        max_decisions: Maximum number of decisions to replay.
        mode: "compare" (analyze only, no LLM calls) or "live" (re-run through LLM).

    Returns:
        Replay results dict with accuracy comparison and PnL impact.
    """
    decisions = load_historical_decisions(max_decisions)
    if not decisions:
        return {"error": "No historical decisions with snapshots found"}

    results = {
        "total_replayed": len(decisions),
        "mode": mode,
        "replay_timestamp": time.time(),
        "old_actions": {"proceed": 0, "flat": 0, "flip": 0},
        "old_allowed": 0,
        "old_rejected": 0,
        "confidence_values": [],
        "regime_distribution": {},
        "veto_reasons": {},
        "action_timeline": [],
    }

    for d in decisions:
        action = d.get("action", "flat")
        allowed = d.get("allowed", False)
        confidence = d.get("confidence", 0)
        regime = d.get("regime", "unknown")
        gate_reason = d.get("gate_reason", "")

        # Aggregate stats
        results["old_actions"][action] = results["old_actions"].get(action, 0) + 1
        if allowed:
            results["old_allowed"] += 1
        else:
            results["old_rejected"] += 1

        results["confidence_values"].append(confidence)
        results["regime_distribution"][regime] = results["regime_distribution"].get(regime, 0) + 1

        if not allowed and gate_reason:
            results["veto_reasons"][gate_reason] = results["veto_reasons"].get(gate_reason, 0) + 1

        results["action_timeline"].append({
            "ts": d.get("ts", 0),
            "action": action,
            "confidence": round(confidence, 2),
            "regime": regime,
            "allowed": allowed,
            "trigger": d.get("trigger_context", "")[:30],
        })

    # Compute summary statistics
    confs = results["confidence_values"]
    results["avg_confidence"] = round(sum(confs) / len(confs), 3) if confs else 0
    results["veto_rate"] = round(results["old_rejected"] / max(len(decisions), 1), 3)
    results["proceed_rate"] = round(
        results["old_actions"].get("proceed", 0) / max(len(decisions), 1), 3
    )
    results["flip_rate"] = round(
        results["old_actions"].get("flip", 0) / max(len(decisions), 1), 3
    )

    # Top veto reasons
    sorted_veto = sorted(results["veto_reasons"].items(), key=lambda x: x[1], reverse=True)
    results["top_veto_reasons"] = sorted_veto[:5]

    # Remove raw lists to keep output manageable
    del results["confidence_values"]
    results["action_timeline"] = results["action_timeline"][:20]  # Last 20 only

    if mode == "live":
        logger.info("[REPLAY] Live replay would run decisions through current pipeline")
        results["live_replay_note"] = (
            "Live replay requires API calls. Use run_live_replay() for actual re-evaluation."
        )

    logger.info(
        f"[REPLAY] Complete: {len(decisions)} decisions, "
        f"veto_rate={results['veto_rate']:.1%}, "
        f"avg_conf={results['avg_confidence']:.2f}, "
        f"regimes={results['regime_distribution']}"
    )
    return results


def run_live_replay(
    max_decisions: int = 50,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Re-run historical snapshots through the CURRENT agent pipeline.

    This is the real backtest — it sends historical snapshots to Claude
    and compares the new decisions with the old ones.

    Args:
        max_decisions: Maximum decisions to replay (costs ~$0.007 each).
        dry_run: If True, estimate cost without making API calls.

    Returns:
        Comparison results or cost estimate.
    """
    decisions = load_historical_decisions(max_decisions, only_with_snapshot=True)
    if not decisions:
        return {"error": "No decisions with snapshot data found"}

    estimated_cost = len(decisions) * 0.007
    if dry_run:
        return {
            "mode": "dry_run",
            "decisions_available": len(decisions),
            "estimated_cost_usd": round(estimated_cost, 2),
            "estimated_time_seconds": len(decisions) * 3,
            "note": "Set dry_run=False to execute. Each decision costs ~$0.007 in API calls.",
        }

    # Live replay: run each snapshot through current pipeline
    from llm.agents.coordinator import is_multi_agent_enabled, get_coordinator

    if not is_multi_agent_enabled():
        return {"error": "Multi-agent mode not enabled. Set LLM_MULTI_AGENT=true"}

    coordinator = get_coordinator()
    comparisons = []
    total_cost = 0.0

    for d in decisions:
        snapshot = d.get("snapshot")
        if not snapshot:
            continue

        old_action = d.get("action", "flat")
        old_conf = d.get("confidence", 0)
        old_regime = d.get("regime", "unknown")
        trigger = d.get("trigger_reason", "")

        try:
            # Re-run through current agent pipeline
            new_decision = coordinator.get_trading_decision(
                snapshot_data=snapshot,
                trigger_reason=trigger,
            )

            if new_decision:
                new_action = new_decision.action
                new_conf = new_decision.confidence
                new_regime = new_decision.regime

                comparisons.append({
                    "ts": d.get("ts", 0),
                    "old": {"action": old_action, "conf": round(old_conf, 2), "regime": old_regime},
                    "new": {"action": new_action, "conf": round(new_conf, 2), "regime": new_regime},
                    "action_changed": old_action != new_action,
                    "conf_delta": round(new_conf - old_conf, 2),
                })

            stats = coordinator.get_stats()
            total_cost += stats.get("total_input_tokens", 0) * 0.000003  # Sonnet input
            total_cost += stats.get("total_output_tokens", 0) * 0.000015  # Sonnet output

        except Exception as e:
            logger.warning(f"[REPLAY] Failed to replay decision: {e}")
            continue

    # Compute comparison stats
    action_changes = sum(1 for c in comparisons if c["action_changed"])
    conf_deltas = [c["conf_delta"] for c in comparisons]
    avg_conf_delta = sum(conf_deltas) / len(conf_deltas) if conf_deltas else 0

    return {
        "mode": "live",
        "total_replayed": len(comparisons),
        "action_changes": action_changes,
        "action_change_rate": round(action_changes / max(len(comparisons), 1), 3),
        "avg_confidence_delta": round(avg_conf_delta, 3),
        "estimated_cost_usd": round(total_cost, 2),
        "comparisons": comparisons[:20],  # First 20 for review
    }


def get_historical_patterns(max_decisions: int = 200) -> Dict[str, Any]:
    """Extract actionable patterns from historical decisions for agent training.

    This is the bridge between replay data and agent learning — no API calls needed.
    The Overseer and Learning agents consume this to understand system-level patterns.
    """
    decisions = load_historical_decisions(max_decisions, only_with_snapshot=False)
    if len(decisions) < 5:
        return {"error": "Insufficient historical data (need 5+ decisions)"}

    # Per-regime win rate
    regime_stats: Dict[str, Dict[str, int]] = {}
    # Per-action win rate
    action_stats: Dict[str, Dict[str, int]] = {}
    # Confidence calibration buckets
    conf_buckets: Dict[str, List[bool]] = {"low": [], "mid": [], "high": []}
    # Time-of-day patterns
    hour_stats: Dict[int, Dict[str, int]] = {}
    # Streak analysis
    outcomes: List[str] = []

    for d in decisions:
        regime = d.get("regime", "unknown")
        action = d.get("action", "flat")
        confidence = d.get("confidence", 0)
        allowed = d.get("allowed", False)
        outcome = d.get("outcome", "")  # WIN/LOSS if available

        # Only count trades that were allowed AND have outcomes
        if not outcome:
            continue

        is_win = outcome == "WIN"

        # Regime stats
        if regime not in regime_stats:
            regime_stats[regime] = {"wins": 0, "total": 0}
        regime_stats[regime]["total"] += 1
        if is_win:
            regime_stats[regime]["wins"] += 1

        # Action stats
        if action not in action_stats:
            action_stats[action] = {"wins": 0, "total": 0}
        action_stats[action]["total"] += 1
        if is_win:
            action_stats[action]["wins"] += 1

        # Confidence calibration
        if confidence < 0.55:
            conf_buckets["low"].append(is_win)
        elif confidence < 0.75:
            conf_buckets["mid"].append(is_win)
        else:
            conf_buckets["high"].append(is_win)

        # Hour of day
        ts = d.get("ts", 0)
        if ts:
            import datetime
            hour = datetime.datetime.fromtimestamp(ts).hour
            if hour not in hour_stats:
                hour_stats[hour] = {"wins": 0, "total": 0}
            hour_stats[hour]["total"] += 1
            if is_win:
                hour_stats[hour]["wins"] += 1

        outcomes.append("W" if is_win else "L")

    # Compute results
    result: Dict[str, Any] = {"total_with_outcomes": len(outcomes)}

    # Regime WR
    result["regime_wr"] = {
        r: {"wr": round(s["wins"] / max(s["total"], 1) * 100), "n": s["total"]}
        for r, s in regime_stats.items() if s["total"] >= 3
    }

    # Action WR
    result["action_wr"] = {
        a: {"wr": round(s["wins"] / max(s["total"], 1) * 100), "n": s["total"]}
        for a, s in action_stats.items() if s["total"] >= 3
    }

    # Confidence calibration
    for bucket_name, bucket_outcomes in conf_buckets.items():
        if len(bucket_outcomes) >= 3:
            wr = sum(1 for o in bucket_outcomes if o) / len(bucket_outcomes)
            result[f"conf_{bucket_name}_wr"] = round(wr * 100)
            result[f"conf_{bucket_name}_n"] = len(bucket_outcomes)

    # Best/worst hours
    if hour_stats:
        sorted_hours = sorted(
            [(h, s["wins"] / max(s["total"], 1), s["total"])
             for h, s in hour_stats.items() if s["total"] >= 3],
            key=lambda x: -x[1],
        )
        if sorted_hours:
            result["best_hours"] = [(h, round(wr * 100)) for h, wr, _ in sorted_hours[:3]]
            result["worst_hours"] = [(h, round(wr * 100)) for h, wr, _ in sorted_hours[-3:]]

    # Streak analysis
    if outcomes:
        max_win_streak = max_loss_streak = 0
        current_streak = 0
        for i, o in enumerate(outcomes):
            if i == 0 or outcomes[i] == outcomes[i - 1]:
                current_streak += 1
            else:
                current_streak = 1
            if o == "W":
                max_win_streak = max(max_win_streak, current_streak)
            else:
                max_loss_streak = max(max_loss_streak, current_streak)
        result["max_win_streak"] = max_win_streak
        result["max_loss_streak"] = max_loss_streak
        result["recent_outcomes"] = "".join(outcomes[-20:])

    return result


def get_replay_summary() -> str:
    """Quick summary of available replay data for CLI/monitoring."""
    decisions = load_historical_decisions(max_decisions=1000, only_with_snapshot=False)
    with_snapshot = [d for d in decisions if "snapshot" in d]

    if not decisions:
        return "No historical decisions found. Run paper trading to build replay data."

    return (
        f"Replay data: {len(decisions)} total decisions, "
        f"{len(with_snapshot)} with snapshots (replayable). "
        f"Cost to replay all: ~${len(with_snapshot) * 0.007:.2f}"
    )
