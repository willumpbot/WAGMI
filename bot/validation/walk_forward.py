"""
Walk-Forward Validation — Continuous OOS generalization proof.

Splits trade history into rolling train/test windows to verify that
in-sample performance generalizes to out-of-sample data.

WF ratio = OOS_pnl / IS_pnl. Values:
  > 0.7 = strong generalization (go-live ready)
  0.5-0.7 = acceptable (continue monitoring)
  < 0.5 = degraded (reduce all sizes by 50%)
  < 0.0 = overfitting (halt new entries)

Usage:
    wf = WalkForwardValidator("data")
    results = wf.run_rolling(trade_history)
    if wf.avg_wf_ratio(results) < 0.5:
        alert("System degraded — reduce sizes")
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.validation.walk_forward")

# Defaults
WF_TRAIN_DAYS = 30
WF_TEST_DAYS = 7
MIN_TRADES_PER_WINDOW = 5  # Need at least this many trades to evaluate


def run_rolling_walk_forward(
    trades: List[Dict[str, Any]],
    train_days: int = WF_TRAIN_DAYS,
    test_days: int = WF_TEST_DAYS,
) -> List[Dict[str, Any]]:
    """Run rolling walk-forward validation on trade history.

    Args:
        trades: List of trade dicts with at least 'timestamp' (epoch float) and 'net_pnl' (float)
        train_days: In-sample window size in days
        test_days: Out-of-sample window size in days

    Returns:
        List of window results with is_pnl, oos_pnl, wf_ratio per window.
    """
    if not trades:
        return []

    # Sort by timestamp
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

    # Find time range
    first_ts = sorted_trades[0].get("timestamp", 0)
    last_ts = sorted_trades[-1].get("timestamp", 0)
    total_days = (last_ts - first_ts) / 86400

    if total_days < train_days + test_days:
        logger.warning(
            f"Insufficient data: {total_days:.0f} days < {train_days}+{test_days} required"
        )
        return []

    results = []
    window_start = first_ts

    while window_start + (train_days + test_days) * 86400 <= last_ts:
        train_end = window_start + train_days * 86400
        test_end = train_end + test_days * 86400

        is_trades = [t for t in sorted_trades if window_start <= t["timestamp"] < train_end]
        oos_trades = [t for t in sorted_trades if train_end <= t["timestamp"] < test_end]

        if len(is_trades) < MIN_TRADES_PER_WINDOW or len(oos_trades) < MIN_TRADES_PER_WINDOW:
            window_start += test_days * 86400
            continue

        is_pnl = sum(t.get("net_pnl", 0) for t in is_trades)
        oos_pnl = sum(t.get("net_pnl", 0) for t in oos_trades)

        # WF ratio: OOS performance relative to IS performance
        if is_pnl > 0:
            wf_ratio = oos_pnl / is_pnl
        elif is_pnl < 0 and oos_pnl < 0:
            wf_ratio = 0.0  # Both negative — no edge to generalize
        elif is_pnl <= 0 and oos_pnl > 0:
            wf_ratio = 1.0  # IS was negative but OOS profitable — unusual but okay
        else:
            wf_ratio = 0.0

        is_wr = sum(1 for t in is_trades if t.get("net_pnl", 0) > 0) / len(is_trades)
        oos_wr = sum(1 for t in oos_trades if t.get("net_pnl", 0) > 0) / len(oos_trades)

        results.append({
            "window_start": window_start,
            "train_end": train_end,
            "test_end": test_end,
            "is_trades": len(is_trades),
            "oos_trades": len(oos_trades),
            "is_pnl": round(is_pnl, 2),
            "oos_pnl": round(oos_pnl, 2),
            "is_win_rate": round(is_wr, 3),
            "oos_win_rate": round(oos_wr, 3),
            "wf_ratio": round(wf_ratio, 3),
        })

        window_start += test_days * 86400

    return results


def avg_wf_ratio(results: List[Dict[str, Any]], last_n: int = 3) -> float:
    """Average WF ratio across last N windows."""
    if not results:
        return 0.0
    recent = results[-last_n:]
    ratios = [r["wf_ratio"] for r in recent]
    return sum(ratios) / len(ratios) if ratios else 0.0


def diagnose_wf_failure(
    results: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Diagnose why walk-forward ratio is low.

    Returns analysis of:
    - Which regimes dominated OOS windows
    - Which agreement levels were OOS trades
    - Whether it's regime mismatch vs. overfitting
    """
    diagnosis = {
        "avg_wf_ratio": avg_wf_ratio(results),
        "total_windows": len(results),
        "passing_windows": sum(1 for r in results if r["wf_ratio"] > 0.5),
        "failing_windows": sum(1 for r in results if r["wf_ratio"] <= 0.5),
    }

    # Analyze OOS trades by regime and agreement level
    regime_pnl = defaultdict(list)
    agree_pnl = defaultdict(list)

    for t in trades:
        regime = t.get("regime_1h", "unknown")
        agree = t.get("agreement_level", 0)
        pnl = t.get("net_pnl", 0)
        regime_pnl[regime].append(pnl)
        agree_pnl[agree].append(pnl)

    # Regime breakdown
    diagnosis["regime_breakdown"] = {}
    for regime, pnls in regime_pnl.items():
        wins = sum(1 for p in pnls if p > 0)
        diagnosis["regime_breakdown"][regime] = {
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls), 3) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        }

    # Agreement level breakdown
    diagnosis["agreement_breakdown"] = {}
    for level, pnls in sorted(agree_pnl.items()):
        wins = sum(1 for p in pnls if p > 0)
        diagnosis["agreement_breakdown"][level] = {
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls), 3) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        }

    # Diagnose root cause
    if all(r.get("trades", 0) == 0 for r in diagnosis["regime_breakdown"].values()
           if r != "unknown"):
        diagnosis["likely_cause"] = "insufficient_data"
    elif (diagnosis["regime_breakdown"].get("trending_bear", {}).get("trades", 0) >
          sum(v["trades"] for v in diagnosis["regime_breakdown"].values()) * 0.5):
        diagnosis["likely_cause"] = "regime_mismatch_bear_dominated"
        diagnosis["recommendation"] = "Regime gate fix (B1) should resolve this"
    else:
        diagnosis["likely_cause"] = "possible_overfitting"
        diagnosis["recommendation"] = "Reduce factor complexity, increase min sample sizes"

    return diagnosis


def check_wf_alert(results: List[Dict[str, Any]]) -> Optional[str]:
    """Check if walk-forward results warrant an alert.

    Returns alert message or None if all clear.
    """
    if not results:
        return "Walk-forward: no data — cannot validate generalization"

    ratio = avg_wf_ratio(results)
    if ratio < 0.0:
        return f"CRITICAL: Walk-forward ratio {ratio:.2f} — system is overfitting. HALT new entries."
    elif ratio < 0.4:
        return f"WARNING: Walk-forward ratio {ratio:.2f} < 0.4 — reduce all sizes by 50%"
    elif ratio < 0.5:
        return f"CAUTION: Walk-forward ratio {ratio:.2f} < 0.5 — monitor closely"

    return None
