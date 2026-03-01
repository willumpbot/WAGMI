"""
LLM Self-Performance Tracker: The LLM's mirror.

Parses data/llm/decisions.jsonl and computes rolling accuracy metrics
that get injected into the LLM's snapshot context so it can self-calibrate.

Metrics computed (over last 50 decided trades):
  - accuracy: % of "go" decisions that resulted in wins
  - veto_accuracy: % of "skip" decisions where the signal would have lost
  - flip_success_rate: % of "flip" decisions that were profitable
  - confidence_calibration: gap between stated confidence and actual win rate
  - regime_accuracy: per-regime win rate
  - streak: current win/loss streak for LLM-approved trades

Data sources:
  - decisions.jsonl (LLM audit trail)
  - SQLite trades table (actual outcomes)
  - veto_tracker (counterfactual outcomes for vetoed signals)
"""

import json
import logging
import os
import time
from collections import defaultdict
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.llm.self_performance")

_DECISIONS_PATH = os.path.join("data", "llm", "decisions.jsonl")
_CACHE_TTL_S = 300  # Cache stats for 5 minutes

# Module-level cache
_cached_stats: Optional[Dict[str, Any]] = None
_cached_at: float = 0.0


def get_performance_stats(force_refresh: bool = False) -> Dict[str, Any]:
    """Get LLM self-performance stats. Cached for 5 minutes.

    Returns a dict suitable for injection into the LLM snapshot:
    {
        "accuracy": 0.62,
        "veto_accuracy": 0.78,
        "flip_success_rate": 0.40,
        "calibration": +0.08,
        "streak": "WLW",
        "regime_accuracy": {"trend": 0.71, "range": 0.38},
        "regime_counts": {"trend": 14, "range": 8},
        "total_decisions": 50,
        "go_count": 30,
        "skip_count": 15,
        "flip_count": 5,
    }
    """
    global _cached_stats, _cached_at

    if not force_refresh and _cached_stats and (time.time() - _cached_at) < _CACHE_TTL_S:
        return _cached_stats

    try:
        stats = _compute_stats()
        _cached_stats = stats
        _cached_at = time.time()
        return stats
    except Exception as e:
        logger.warning(f"[SELF-PERF] Failed to compute stats: {e}")
        return _empty_stats()


def get_compact_stats() -> Dict[str, Any]:
    """Get compact stats for LLM snapshot injection (minimal tokens).

    Returns:
    {
        "acc": 0.62, "vacc": 0.78, "flip_sr": 0.40,
        "cal": +0.08, "str": "WLW",
        "rg_acc": {"trend": 0.71, "range": 0.38}
    }
    """
    stats = get_performance_stats()
    if not stats or stats.get("total_decisions", 0) < 5:
        return {}

    compact = {
        "acc": round(stats.get("accuracy", 0.5), 2),
        "vacc": round(stats.get("veto_accuracy", 0.5), 2),
        "cal": round(stats.get("calibration", 0.0), 2),
        "str": stats.get("streak", ""),
        "n": stats.get("total_decisions", 0),
    }

    # Only include flip stats if there were flips
    if stats.get("flip_count", 0) >= 3:
        compact["flip_sr"] = round(stats.get("flip_success_rate", 0.5), 2)

    # Regime accuracy (only regimes with 3+ decisions)
    rg_acc = {}
    for regime, acc in stats.get("regime_accuracy", {}).items():
        count = stats.get("regime_counts", {}).get(regime, 0)
        if count >= 3:
            rg_acc[regime] = round(acc, 2)
    if rg_acc:
        compact["rg_acc"] = rg_acc

    return compact


def _compute_stats() -> Dict[str, Any]:
    """Parse decisions.jsonl and cross-reference with trade outcomes."""
    decisions = _read_recent_decisions(200)

    if not decisions:
        return _empty_stats()

    # Separate by action
    go_decisions = [d for d in decisions if d.get("action") == "go" and d.get("allowed")]
    skip_decisions = [d for d in decisions if d.get("action") in ("flat", "skip") and d.get("is_veto")]
    flip_decisions = [d for d in decisions if d.get("action") == "flip" and d.get("allowed")]

    # Cross-reference "go" decisions with trade outcomes
    go_outcomes = _match_decisions_to_outcomes(go_decisions)
    flip_outcomes = _match_decisions_to_outcomes(flip_decisions)

    # Veto outcomes from veto_tracker
    veto_outcomes = _get_veto_outcomes(skip_decisions)

    # Compute accuracy
    accuracy = _win_rate(go_outcomes) if go_outcomes else 0.5
    flip_sr = _win_rate(flip_outcomes) if flip_outcomes else 0.5
    veto_accuracy = _veto_win_rate(veto_outcomes) if veto_outcomes else 0.5

    # Confidence calibration: mean stated confidence - actual win rate
    calibration = _compute_calibration(go_outcomes)

    # Regime accuracy
    regime_accuracy, regime_counts = _compute_regime_accuracy(go_outcomes + flip_outcomes)

    # Streak
    streak = _compute_streak(go_outcomes + flip_outcomes)

    return {
        "accuracy": accuracy,
        "veto_accuracy": veto_accuracy,
        "flip_success_rate": flip_sr,
        "calibration": calibration,
        "streak": streak,
        "regime_accuracy": regime_accuracy,
        "regime_counts": regime_counts,
        "total_decisions": len(decisions),
        "go_count": len(go_decisions),
        "skip_count": len(skip_decisions),
        "flip_count": len(flip_decisions),
    }


def _read_recent_decisions(max_lines: int = 200) -> List[Dict]:
    """Read the last N lines from decisions.jsonl."""
    if not os.path.exists(_DECISIONS_PATH):
        return []

    try:
        lines = []
        with open(_DECISIONS_PATH, "r") as f:
            # Read all lines (file shouldn't be huge), take last N
            all_lines = f.readlines()
            recent = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

        for line in recent:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # Only include actual decisions (not api_error, validation_failed etc.)
                if entry.get("action") in ("go", "flat", "skip", "flip"):
                    lines.append(entry)
            except json.JSONDecodeError:
                continue

        return lines
    except Exception as e:
        logger.warning(f"[SELF-PERF] Failed to read decisions: {e}")
        return []


def _match_decisions_to_outcomes(decisions: List[Dict]) -> List[Dict]:
    """Match LLM decisions to actual trade outcomes from the SQLite trades table.

    For each "go" decision, look for a trade OPEN within ±120s of the decision,
    then find the corresponding close event to determine win/loss.

    Returns list of dicts: {decision: {...}, win: bool, pnl: float}
    """
    if not decisions:
        return []

    try:
        from data.db import get_connection, CLOSE_ACTIONS
    except ImportError:
        return []

    results = []
    try:
        conn = get_connection()

        for d in decisions:
            ts = d.get("ts", 0)
            if not ts:
                continue

            # Find trade OPEN near this decision timestamp
            # Match by looking for symbol in trigger_context
            symbol_hint = ""
            tc = d.get("trigger_context", "")
            if tc:
                parts = tc.split()
                if parts:
                    symbol_hint = parts[0]

            if not symbol_hint:
                continue

            # Look for a matching trade open within 120 seconds
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            ts_start = (dt.timestamp() - 30)
            ts_end = (dt.timestamp() + 120)

            # Convert to ISO format for comparison
            start_iso = datetime.fromtimestamp(ts_start, tz=timezone.utc).isoformat()
            end_iso = datetime.fromtimestamp(ts_end, tz=timezone.utc).isoformat()

            # Find OPEN trade
            open_row = conn.execute(
                """SELECT * FROM trades
                   WHERE symbol LIKE ? AND action = 'OPEN'
                   AND timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp LIMIT 1""",
                (f"%{symbol_hint}%", start_iso, end_iso),
            ).fetchone()

            if not open_row:
                continue

            open_dict = dict(open_row)

            # Find corresponding close (any close action after the open, same symbol)
            close_row = conn.execute(
                """SELECT * FROM trades
                   WHERE symbol = ? AND action IN ({})
                   AND timestamp > ?
                   ORDER BY timestamp LIMIT 1""".format(
                    ",".join(f"'{a}'" for a in CLOSE_ACTIONS)
                ),
                (open_dict["symbol"], open_dict["timestamp"]),
            ).fetchone()

            if close_row:
                close_dict = dict(close_row)
                pnl = close_dict.get("pnl", 0.0)
                results.append({
                    "decision": d,
                    "win": pnl > 0,
                    "pnl": pnl,
                    "symbol": open_dict["symbol"],
                    "regime": d.get("regime", "unknown"),
                })

        conn.close()
    except Exception as e:
        logger.warning(f"[SELF-PERF] Failed to match outcomes: {e}")

    return results


def _get_veto_outcomes(skip_decisions: List[Dict]) -> List[Dict]:
    """Get counterfactual outcomes for vetoed signals from veto_tracker.

    Returns list of dicts: {decision: {...}, would_have_won: bool}
    """
    try:
        from llm.veto_tracker import get_veto_tracker
        tracker = get_veto_tracker()
        if not tracker:
            return []

        outcomes = []
        for record in tracker.get_resolved_vetoes():
            outcomes.append({
                "would_have_won": record.get("outcome") == "WOULD_WIN",
                "symbol": record.get("symbol", ""),
            })
        return outcomes
    except Exception:
        return []


def _win_rate(outcomes: List[Dict]) -> float:
    """Calculate win rate from matched outcomes."""
    if not outcomes:
        return 0.5
    wins = sum(1 for o in outcomes if o.get("win"))
    return wins / len(outcomes)


def _veto_win_rate(veto_outcomes: List[Dict]) -> float:
    """Calculate veto accuracy: % of skips where signal WOULD HAVE LOST.

    High veto_accuracy = LLM is good at avoiding losers.
    """
    if not veto_outcomes:
        return 0.5
    correct_vetoes = sum(1 for o in veto_outcomes if not o.get("would_have_won"))
    return correct_vetoes / len(veto_outcomes)


def _compute_calibration(go_outcomes: List[Dict]) -> float:
    """Compute confidence calibration offset.

    calibration = mean_stated_confidence - actual_win_rate
    Positive = overconfident, Negative = underconfident
    """
    if not go_outcomes:
        return 0.0

    stated_confs = []
    for o in go_outcomes:
        d = o.get("decision", {})
        c = d.get("confidence", 0.5)
        stated_confs.append(c)

    mean_conf = sum(stated_confs) / len(stated_confs)
    actual_wr = _win_rate(go_outcomes)

    return round(mean_conf - actual_wr, 3)


def _compute_regime_accuracy(outcomes: List[Dict]) -> tuple:
    """Compute per-regime win rates.

    Returns (regime_accuracy: Dict[str, float], regime_counts: Dict[str, int])
    """
    by_regime = defaultdict(list)
    for o in outcomes:
        regime = o.get("regime", "unknown")
        if regime:
            by_regime[regime].append(o)

    accuracy = {}
    counts = {}
    for regime, regime_outcomes in by_regime.items():
        counts[regime] = len(regime_outcomes)
        if len(regime_outcomes) >= 3:
            accuracy[regime] = _win_rate(regime_outcomes)

    return accuracy, counts


def _compute_streak(outcomes: List[Dict]) -> str:
    """Compute recent win/loss streak as a compact string.

    Returns something like "WWLWL" (last 5 outcomes, most recent last).
    """
    if not outcomes:
        return ""

    # Sort by decision timestamp
    sorted_outcomes = sorted(outcomes, key=lambda o: o.get("decision", {}).get("ts", 0))

    # Take last 8 outcomes
    recent = sorted_outcomes[-8:]
    return "".join("W" if o.get("win") else "L" for o in recent)


def _empty_stats() -> Dict[str, Any]:
    """Return empty stats structure."""
    return {
        "accuracy": 0.5,
        "veto_accuracy": 0.5,
        "flip_success_rate": 0.5,
        "calibration": 0.0,
        "streak": "",
        "regime_accuracy": {},
        "regime_counts": {},
        "total_decisions": 0,
        "go_count": 0,
        "skip_count": 0,
        "flip_count": 0,
    }
