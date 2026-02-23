"""
Baseline vs LLM Uplift Analytics.

Reads trade_candidates.csv and computes:
1. Baseline stats: win rate, avg R, total PnL (all candidates)
2. LLM-filtered stats: win rate, avg R, total PnL (after LLM decisions)
3. Veto accuracy: what % of vetoed trades would have lost?
4. Per-regime / per-symbol / per-trigger breakdowns
5. Uplift = LLM performance - baseline performance

This is the KEY module for proving LLM value. If uplift is negative,
the LLM is hurting and should be turned off.
"""

import csv
import logging
import os
from collections import defaultdict
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.llm.uplift")

_CANDIDATE_LOG_FILE = os.path.join("data", "analysis", "trade_candidates.csv")


def load_candidates(path: str = _CANDIDATE_LOG_FILE) -> List[Dict[str, Any]]:
    """Load trade candidates with type conversion."""
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(_parse_row(row))
    except Exception as e:
        logger.warning(f"[UPLIFT] Failed to load candidates: {e}")
    return rows


def _parse_row(row: dict) -> dict:
    """Convert string values to appropriate types."""
    parsed = dict(row)
    for key in ("ensemble_confidence", "llm_confidence", "llm_size_mult",
                "realized_pnl", "realized_r", "hold_time_s", "leverage_used"):
        val = parsed.get(key, "")
        if val and val.strip():
            try:
                parsed[key] = float(val)
            except ValueError:
                parsed[key] = None
        else:
            parsed[key] = None
    for key in ("num_agree",):
        val = parsed.get(key, "")
        if val and val.strip():
            try:
                parsed[key] = int(val)
            except ValueError:
                parsed[key] = None
        else:
            parsed[key] = None
    return parsed


def compute_uplift(path: str = _CANDIDATE_LOG_FILE) -> Dict[str, Any]:
    """Compute full uplift analytics.

    Returns a dict with:
      baseline: Stats for all ensemble candidates (what would happen without LLM)
      llm_filtered: Stats for LLM-approved trades (what actually happened)
      veto_accuracy: How many vetoed trades would have lost
      by_regime: Breakdown by regime
      by_symbol: Breakdown by symbol
      by_trigger: Breakdown by trigger type
      uplift: Delta between LLM and baseline
    """
    candidates = load_candidates(path)
    if not candidates:
        return {"error": "no_data", "total_candidates": 0}

    # Split into categories
    all_decided = [c for c in candidates if c.get("realized_pnl") is not None]
    vetoed = [c for c in candidates if c.get("llm_action") == "flat"
              and c.get("realized_pnl") is not None]
    proceeded = [c for c in candidates if c.get("llm_action") in ("proceed", "no_llm")
                 and c.get("realized_pnl") is not None]
    no_llm = [c for c in candidates if c.get("llm_action") == "no_llm"
              and c.get("realized_pnl") is not None]

    # Baseline stats (all candidates that have realized PnL, including vetoed)
    baseline = _compute_stats(all_decided, "baseline")

    # LLM-filtered stats (only trades that proceeded)
    llm_filtered = _compute_stats(proceeded, "llm_filtered")

    # Veto accuracy: what % of vetoed trades would have been losses?
    veto_stats = _compute_veto_accuracy(vetoed)

    # Per-regime breakdown
    by_regime = _group_stats(all_decided, "regime")

    # Per-symbol breakdown
    by_symbol = _group_stats(all_decided, "symbol")

    # Uplift calculation
    uplift = _compute_uplift_delta(baseline, llm_filtered)

    return {
        "total_candidates": len(candidates),
        "with_outcome": len(all_decided),
        "baseline": baseline,
        "llm_filtered": llm_filtered,
        "veto_accuracy": veto_stats,
        "by_regime": by_regime,
        "by_symbol": by_symbol,
        "uplift": uplift,
    }


def _compute_stats(candidates: List[dict], label: str) -> Dict[str, Any]:
    """Compute basic stats for a set of candidates."""
    if not candidates:
        return {"count": 0, "label": label}

    pnls = [c["realized_pnl"] for c in candidates if c.get("realized_pnl") is not None]
    rs = [c["realized_r"] for c in candidates if c.get("realized_r") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    return {
        "label": label,
        "count": len(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else 0,
        "total_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "avg_r": sum(rs) / len(rs) if rs else 0,
        "max_win": max(pnls) if pnls else 0,
        "max_loss": min(pnls) if pnls else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf"),
    }


def _compute_veto_accuracy(vetoed: List[dict]) -> Dict[str, Any]:
    """Analyze vetoed trades: how many would have been losers?

    This is the core LLM value metric. High veto accuracy = LLM is saving money.
    """
    if not vetoed:
        return {"total_vetoed": 0, "accuracy": 0, "saved_pnl": 0}

    would_have_lost = [c for c in vetoed if c.get("realized_pnl") is not None and c["realized_pnl"] <= 0]
    would_have_won = [c for c in vetoed if c.get("realized_pnl") is not None and c["realized_pnl"] > 0]

    # Count vetoed candidates that have simulated outcomes
    with_outcome = [c for c in vetoed if c.get("realized_pnl") is not None]
    total_with_outcome = len(with_outcome)

    # Saved PnL = sum of losses that were avoided
    saved_pnl = abs(sum(c["realized_pnl"] for c in would_have_lost))
    # Missed PnL = sum of wins that were missed
    missed_pnl = sum(c["realized_pnl"] for c in would_have_won)

    return {
        "total_vetoed": len(vetoed),
        "with_outcome": total_with_outcome,
        "would_have_lost": len(would_have_lost),
        "would_have_won": len(would_have_won),
        "accuracy": len(would_have_lost) / total_with_outcome if total_with_outcome else 0,
        "saved_pnl": saved_pnl,
        "missed_pnl": missed_pnl,
        "net_value": saved_pnl - missed_pnl,
    }


def _group_stats(candidates: List[dict], key: str) -> Dict[str, Dict[str, Any]]:
    """Group candidates by a key and compute stats for each group."""
    groups = defaultdict(list)
    for c in candidates:
        group_val = c.get(key, "unknown") or "unknown"
        groups[group_val].append(c)

    result = {}
    for group_name, group_candidates in groups.items():
        result[group_name] = _compute_stats(group_candidates, group_name)
    return result


def _compute_uplift_delta(baseline: dict, llm_filtered: dict) -> Dict[str, Any]:
    """Compute the delta between baseline and LLM-filtered performance."""
    if baseline.get("count", 0) == 0 or llm_filtered.get("count", 0) == 0:
        return {"has_data": False}

    return {
        "has_data": True,
        "win_rate_delta": llm_filtered["win_rate"] - baseline["win_rate"],
        "avg_pnl_delta": llm_filtered["avg_pnl"] - baseline["avg_pnl"],
        "avg_r_delta": llm_filtered["avg_r"] - baseline["avg_r"],
        "total_pnl_delta": llm_filtered["total_pnl"] - baseline["total_pnl"],
        "profit_factor_delta": (
            llm_filtered["profit_factor"] - baseline["profit_factor"]
            if baseline["profit_factor"] != float("inf")
            and llm_filtered["profit_factor"] != float("inf")
            else 0
        ),
        "is_positive": llm_filtered["avg_pnl"] > baseline["avg_pnl"],
    }


def format_uplift_report(analytics: Dict[str, Any]) -> str:
    """Format the uplift analytics into a human-readable report.

    Suitable for Telegram or console output.
    """
    if analytics.get("error"):
        return f"No uplift data: {analytics['error']}"

    lines = []
    lines.append("=== LLM UPLIFT REPORT ===")
    lines.append(f"Total candidates: {analytics['total_candidates']}")
    lines.append(f"With outcome: {analytics['with_outcome']}")
    lines.append("")

    # Baseline
    b = analytics.get("baseline", {})
    if b.get("count", 0) > 0:
        lines.append(f"BASELINE (all candidates):")
        lines.append(f"  Trades: {b['count']} | WR: {b['win_rate']:.1%} | Avg PnL: ${b['avg_pnl']:+.2f}")
        lines.append(f"  Total PnL: ${b['total_pnl']:+.2f} | PF: {b['profit_factor']:.2f}")

    # LLM-filtered
    lf = analytics.get("llm_filtered", {})
    if lf.get("count", 0) > 0:
        lines.append(f"LLM-FILTERED (proceeded):")
        lines.append(f"  Trades: {lf['count']} | WR: {lf['win_rate']:.1%} | Avg PnL: ${lf['avg_pnl']:+.2f}")
        lines.append(f"  Total PnL: ${lf['total_pnl']:+.2f} | PF: {lf['profit_factor']:.2f}")

    # Veto accuracy
    v = analytics.get("veto_accuracy", {})
    if v.get("total_vetoed", 0) > 0:
        lines.append(f"VETO ACCURACY:")
        lines.append(f"  Vetoed: {v['total_vetoed']} | Accuracy: {v['accuracy']:.1%}")
        lines.append(f"  Saved: ${v['saved_pnl']:+.2f} | Missed: ${v['missed_pnl']:+.2f} | Net: ${v['net_value']:+.2f}")

    # Uplift
    u = analytics.get("uplift", {})
    if u.get("has_data"):
        direction = "POSITIVE" if u["is_positive"] else "NEGATIVE"
        lines.append(f"UPLIFT ({direction}):")
        lines.append(f"  WR delta: {u['win_rate_delta']:+.1%} | Avg PnL delta: ${u['avg_pnl_delta']:+.2f}")

    return "\n".join(lines)
