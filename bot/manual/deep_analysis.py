#!/usr/bin/env python3
"""
Deep Signal Analysis — Comprehensive signal quality scoring, pattern detection,
and edge discovery across all historical and live signal data.

Run: cd bot && python -m manual.deep_analysis
"""

import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent.parent  # bot/
DATA = BASE / "data"
MANUAL = DATA / "manual"
LOGS = DATA / "logs"

SIGNAL_OUTCOMES = LOGS / "signal_outcomes.jsonl"
SNIPER_SIGNALS = MANUAL / "sniper_signals.jsonl"
COUNTERFACTUAL = DATA / "counterfactual_resolved.json"
EDGE_RAW = MANUAL / "edge_analysis_raw.json"

OUT_JSON = MANUAL / "deep_analysis_results.json"
OUT_MD = MANUAL / "DEEP_ANALYSIS.md"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return records
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    print(f"  Loaded {len(records)} records from {path.name}")
    return records


def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    print(f"  Loaded {path.name}")
    return data


# ---------------------------------------------------------------------------
# 1) Signal Quality Scoring
# ---------------------------------------------------------------------------

def compute_quality_score(rec: dict, source: str = "counterfactual") -> float:
    """
    Composite quality score 0-100:
      Confidence (40%), Consensus (25%), EV (15%), Regime (10%), Chop (10%)
    """
    # --- Confidence component (0-40) ---
    if source == "counterfactual":
        conf = rec.get("confidence", 50)
    elif source == "signal_outcome":
        conf = rec.get("conf", 50)
    else:
        conf = rec.get("confidence", 50)

    # Normalize confidence: 50->0, 100->40
    conf_score = max(0, min(40, (conf - 50) * (40 / 50)))

    # --- Consensus component (0-25) ---
    if source == "signal_outcome":
        n_agree = rec.get("n_agree", 1)
    elif source == "sniper":
        n_agree = rec.get("num_agree", 1)
    else:
        # counterfactual doesn't have n_agree, estimate from confidence
        # higher conf in counterfactual likely had more agreement
        n_agree = 1 if conf < 60 else (2 if conf < 75 else 3)

    consensus_map = {1: 5, 2: 15, 3: 25, 4: 25}
    consensus_score = consensus_map.get(n_agree, 5)

    # --- EV component (0-15) ---
    if source == "signal_outcome":
        ev = rec.get("meta", {}).get("ev_per_dollar", 0)
    elif source == "sniper":
        ev = rec.get("ev_per_dollar", 0)
    else:
        # estimate from pnl_pct
        pnl = rec.get("hypothetical_pnl_pct", 0)
        ev = max(0, pnl / 10)  # rough proxy

    # Normalize: 0->0, 0.5+->15
    ev_score = max(0, min(15, ev * 30))

    # --- Regime component (0-10) ---
    regime = ""
    if source == "signal_outcome":
        regime = rec.get("regime", "")
    elif source == "sniper":
        regime = rec.get("regime", "")
    else:
        regime = rec.get("regime", "")

    regime_bonuses = {
        "trend": 10, "panic": 8, "high_volatility": 6,
        "consolidation": 4, "range": 3, "unknown": 2, "": 2,
        "low_liquidity": 1, "news_dislocation": 5,
    }
    regime_score = regime_bonuses.get(regime, 2)

    # --- Chop component (0-10) ---
    chop = 0.5  # default mid
    if source == "signal_outcome":
        chop = rec.get("meta", {}).get("chop_score_smoothed", 0.5)
    elif source == "sniper":
        chop = 0.3  # sniper signals tend to be low-chop

    # Low chop = good. chop 0->10, chop 1->0
    chop_score = max(0, min(10, (1 - chop) * 10))

    total = conf_score + consensus_score + ev_score + regime_score + chop_score
    return round(min(100, max(0, total)), 2)


def analyze_quality_scoring(cf_records: list[dict]) -> dict:
    """Apply quality scoring to counterfactual records, find optimal threshold."""
    print("\n=== Analysis 1: Signal Quality Scoring ===")

    scored = []
    for rec in cf_records:
        score = compute_quality_score(rec, "counterfactual")
        scored.append({
            "record_id": rec.get("record_id", ""),
            "symbol": rec.get("symbol", ""),
            "side": rec.get("side", ""),
            "confidence": rec.get("confidence", 0),
            "quality_score": score,
            "would_hit_tp1": rec.get("would_hit_tp1", False),
            "would_hit_sl": rec.get("would_hit_sl", False),
            "pnl_pct": rec.get("hypothetical_pnl_pct", 0),
        })

    # Test thresholds from 20 to 80
    threshold_results = []
    for thresh in range(15, 85, 5):
        above = [s for s in scored if s["quality_score"] >= thresh]
        below = [s for s in scored if s["quality_score"] < thresh]

        if not above:
            continue

        wins_above = sum(1 for s in above if s["pnl_pct"] > 0)
        losses_above = sum(1 for s in above if s["pnl_pct"] < 0)
        wr_above = wins_above / len(above) if above else 0

        total_win_pnl = sum(s["pnl_pct"] for s in above if s["pnl_pct"] > 0)
        total_loss_pnl = abs(sum(s["pnl_pct"] for s in above if s["pnl_pct"] < 0))
        pf = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else float("inf")

        avg_pnl = mean(s["pnl_pct"] for s in above) if above else 0
        total_pnl = sum(s["pnl_pct"] for s in above)

        threshold_results.append({
            "threshold": thresh,
            "n_signals": len(above),
            "win_rate": round(wr_above, 4),
            "profit_factor": round(pf, 3),
            "avg_pnl_pct": round(avg_pnl, 4),
            "total_pnl_pct": round(total_pnl, 2),
        })

    # Find best by profit factor (with min 20 signals)
    viable = [t for t in threshold_results if t["n_signals"] >= 20]
    best_pf = max(viable, key=lambda x: x["profit_factor"]) if viable else None
    best_total = max(viable, key=lambda x: x["total_pnl_pct"]) if viable else None

    # Score distribution
    score_dist = {}
    for bucket in range(0, 100, 10):
        in_bucket = [s for s in scored if bucket <= s["quality_score"] < bucket + 10]
        if in_bucket:
            wins = sum(1 for s in in_bucket if s["pnl_pct"] > 0)
            score_dist[f"{bucket}-{bucket+10}"] = {
                "count": len(in_bucket),
                "win_rate": round(wins / len(in_bucket), 4),
                "avg_pnl": round(mean(s["pnl_pct"] for s in in_bucket), 4),
            }

    result = {
        "total_scored": len(scored),
        "score_distribution": score_dist,
        "threshold_analysis": threshold_results,
        "optimal_threshold_by_pf": best_pf,
        "optimal_threshold_by_total_pnl": best_total,
        "top_scored_signals": sorted(scored, key=lambda x: -x["quality_score"])[:10],
    }

    print(f"  Scored {len(scored)} records")
    if best_pf:
        print(f"  Best PF threshold: {best_pf['threshold']} (PF={best_pf['profit_factor']}, WR={best_pf['win_rate']}, N={best_pf['n_signals']})")
    if best_total:
        print(f"  Best total PnL threshold: {best_total['threshold']} (total={best_total['total_pnl_pct']}%, N={best_total['n_signals']})")

    return result


# ---------------------------------------------------------------------------
# 2) Time-of-Day Edge
# ---------------------------------------------------------------------------

def analyze_time_of_day(signals: list[dict], cf_records: list[dict]) -> dict:
    """Find optimal trading hours from signal timestamps."""
    print("\n=== Analysis 2: Time-of-Day Edge ===")

    # Signal outcomes by hour
    hourly_signals = defaultdict(list)
    for sig in signals:
        ts = sig.get("ts", 0)
        if ts > 0:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            hour = dt.hour
            hourly_signals[hour].append(sig)

    hourly_stats = {}
    for hour in sorted(hourly_signals.keys()):
        sigs = hourly_signals[hour]
        n = len(sigs)
        confs = [s.get("conf", 0) for s in sigs]
        high_conf = sum(1 for c in confs if c >= 80)
        n_agree_3plus = sum(1 for s in sigs if s.get("n_agree", 0) >= 3)
        evs = [s.get("meta", {}).get("ev_per_dollar", 0) for s in sigs]
        chops = [s.get("meta", {}).get("chop_score_smoothed", 0.5) for s in sigs]

        hourly_stats[str(hour)] = {
            "total_signals": n,
            "avg_confidence": round(mean(confs), 2) if confs else 0,
            "high_conf_pct": round(high_conf / n * 100, 1) if n else 0,
            "consensus_3plus_pct": round(n_agree_3plus / n * 100, 1) if n else 0,
            "avg_ev": round(mean(evs), 4) if evs else 0,
            "avg_chop": round(mean(chops), 4) if chops else 0,
        }

    # Counterfactual by hour
    cf_hourly = defaultdict(list)
    for rec in cf_records:
        created = rec.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created)
                cf_hourly[dt.hour].append(rec)
            except (ValueError, TypeError):
                pass

    cf_hourly_stats = {}
    for hour in sorted(cf_hourly.keys()):
        recs = cf_hourly[hour]
        n = len(recs)
        wins = sum(1 for r in recs if r.get("hypothetical_pnl_pct", 0) > 0)
        pnls = [r.get("hypothetical_pnl_pct", 0) for r in recs]

        cf_hourly_stats[str(hour)] = {
            "n_records": n,
            "win_rate": round(wins / n, 4) if n else 0,
            "avg_pnl_pct": round(mean(pnls), 4) if pnls else 0,
            "total_pnl_pct": round(sum(pnls), 2),
        }

    # Best hours for trading
    best_hours_by_ev = sorted(
        hourly_stats.items(),
        key=lambda x: x[1]["avg_ev"],
        reverse=True,
    )[:5]

    best_hours_by_conf = sorted(
        hourly_stats.items(),
        key=lambda x: x[1]["high_conf_pct"],
        reverse=True,
    )[:5]

    result = {
        "signal_hourly_breakdown": hourly_stats,
        "counterfactual_hourly_breakdown": cf_hourly_stats,
        "best_hours_by_ev": [{"hour": h, **s} for h, s in best_hours_by_ev],
        "best_hours_by_high_conf": [{"hour": h, **s} for h, s in best_hours_by_conf],
        "recommendation": _tod_recommendation(hourly_stats, cf_hourly_stats),
    }

    print(f"  Signal hours covered: {sorted(hourly_stats.keys())}")
    print(f"  CF hours covered: {sorted(cf_hourly_stats.keys())}")
    return result


def _tod_recommendation(hourly: dict, cf_hourly: dict) -> str:
    """Generate human-readable time-of-day recommendation."""
    parts = []
    if hourly:
        best_ev_hour = max(hourly.items(), key=lambda x: x[1]["avg_ev"])
        best_vol_hour = max(hourly.items(), key=lambda x: x[1]["total_signals"])
        parts.append(f"Highest EV signals at UTC {best_ev_hour[0]}:00 (avg EV={best_ev_hour[1]['avg_ev']:.4f})")
        parts.append(f"Most signals at UTC {best_vol_hour[0]}:00 ({best_vol_hour[1]['total_signals']} signals)")

    if cf_hourly:
        best_wr_hour = max(cf_hourly.items(), key=lambda x: x[1]["win_rate"])
        parts.append(f"Best CF win rate at UTC {best_wr_hour[0]}:00 (WR={best_wr_hour[1]['win_rate']:.1%})")

    return " | ".join(parts) if parts else "Insufficient data"


# ---------------------------------------------------------------------------
# 3) Signal Clustering
# ---------------------------------------------------------------------------

def analyze_signal_clustering(signals: list[dict], sniper_signals: list[dict]) -> dict:
    """Analyze signal burst patterns and clustering."""
    print("\n=== Analysis 3: Signal Clustering ===")

    if not signals:
        return {"error": "No signals to analyze"}

    # Sort by timestamp
    sorted_sigs = sorted(signals, key=lambda x: x.get("ts", 0))
    timestamps = [s["ts"] for s in sorted_sigs if s.get("ts", 0) > 0]

    if len(timestamps) < 2:
        return {"error": "Not enough timestamped signals"}

    # Inter-signal gaps
    gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    gaps_minutes = [g / 60 for g in gaps]

    # Signals per hour
    hour_buckets = defaultdict(int)
    for ts in timestamps:
        bucket = int(ts // 3600)
        hour_buckets[bucket] += 1
    signals_per_hour = list(hour_buckets.values())

    # Cluster detection: signals within 5 min of each other
    clusters = []
    current_cluster = [timestamps[0]]
    for i in range(1, len(timestamps)):
        if timestamps[i] - current_cluster[-1] < 300:  # 5 min
            current_cluster.append(timestamps[i])
        else:
            if len(current_cluster) >= 2:
                clusters.append(current_cluster)
            current_cluster = [timestamps[i]]
    if len(current_cluster) >= 2:
        clusters.append(current_cluster)

    # SNIPER signal follow-up analysis
    sniper_ts = []
    for sig in sniper_signals:
        ts_str = sig.get("timestamp", "")
        if ts_str:
            try:
                dt = datetime.fromisoformat(ts_str)
                sniper_ts.append(dt.timestamp())
            except (ValueError, TypeError):
                pass

    sniper_ts.sort()
    sniper_followups = 0
    sniper_pairs = 0
    for i in range(len(sniper_ts)):
        for j in range(i+1, len(sniper_ts)):
            if sniper_ts[j] - sniper_ts[i] <= 1800:  # 30 min
                sniper_pairs += 1
                break  # count each signal once
        sniper_followups += 1 if i > 0 and sniper_ts[i] - sniper_ts[i-1] <= 1800 else 0

    result = {
        "total_signals_analyzed": len(timestamps),
        "time_span_hours": round((timestamps[-1] - timestamps[0]) / 3600, 2),
        "avg_gap_minutes": round(mean(gaps_minutes), 2) if gaps_minutes else 0,
        "median_gap_minutes": round(median(gaps_minutes), 2) if gaps_minutes else 0,
        "min_gap_seconds": round(min(gaps), 1) if gaps else 0,
        "max_gap_minutes": round(max(gaps_minutes), 1) if gaps_minutes else 0,
        "signals_per_hour_stats": {
            "avg": round(mean(signals_per_hour), 2),
            "max": max(signals_per_hour),
            "min": min(signals_per_hour),
        },
        "cluster_analysis": {
            "total_clusters": len(clusters),
            "avg_cluster_size": round(mean(len(c) for c in clusters), 2) if clusters else 0,
            "max_cluster_size": max(len(c) for c in clusters) if clusters else 0,
            "pct_signals_in_clusters": round(
                sum(len(c) for c in clusters) / len(timestamps) * 100, 1
            ) if clusters else 0,
        },
        "sniper_followup": {
            "total_sniper_signals": len(sniper_ts),
            "signals_followed_within_30min": sniper_followups,
            "followup_rate": round(sniper_followups / max(1, len(sniper_ts) - 1) * 100, 1),
        },
        "recommendation": "",
    }

    # Generate recommendation
    cluster_pct = result["cluster_analysis"]["pct_signals_in_clusters"]
    if cluster_pct > 60:
        result["recommendation"] = (
            f"Signals cluster heavily ({cluster_pct:.0f}% in bursts). "
            "Wait for the cluster to form (2-3 signals within 5 min) before trading — "
            "this confirms the setup. Trade the 2nd or 3rd signal in a burst."
        )
    else:
        result["recommendation"] = (
            f"Signals are relatively spread out ({cluster_pct:.0f}% in clusters). "
            "Trade the first qualifying signal — waiting for a cluster may mean missing the move."
        )

    print(f"  {len(clusters)} clusters found, avg size {result['cluster_analysis']['avg_cluster_size']}")
    print(f"  Avg gap: {result['avg_gap_minutes']:.1f} min, median: {result['median_gap_minutes']:.1f} min")
    return result


# ---------------------------------------------------------------------------
# 4) Regime Transition Signals
# ---------------------------------------------------------------------------

def analyze_regime_transitions(signals: list[dict], cf_records: list[dict]) -> dict:
    """Find signals at regime transitions and compare profitability."""
    print("\n=== Analysis 4: Regime Transition Signals ===")

    # From signal outcomes: detect regime changes over time
    sorted_sigs = sorted(signals, key=lambda x: x.get("ts", 0))

    regime_changes = []
    prev_regime = None
    for sig in sorted_sigs:
        regime = sig.get("regime", "")
        if prev_regime is not None and regime != prev_regime and regime and prev_regime:
            regime_changes.append({
                "from": prev_regime,
                "to": regime,
                "ts": sig.get("ts", 0),
                "signal": sig,
            })
        if regime:
            prev_regime = regime

    # From counterfactual: group by regime
    regime_groups = defaultdict(list)
    for rec in cf_records:
        regime = rec.get("regime", "") or "unknown"
        regime_groups[regime].append(rec)

    regime_performance = {}
    for regime, recs in regime_groups.items():
        wins = sum(1 for r in recs if r.get("hypothetical_pnl_pct", 0) > 0)
        pnls = [r.get("hypothetical_pnl_pct", 0) for r in recs]
        win_pnl = sum(p for p in pnls if p > 0)
        loss_pnl = abs(sum(p for p in pnls if p < 0))

        regime_performance[regime] = {
            "count": len(recs),
            "win_rate": round(wins / len(recs), 4) if recs else 0,
            "avg_pnl_pct": round(mean(pnls), 4) if pnls else 0,
            "profit_factor": round(win_pnl / loss_pnl, 3) if loss_pnl > 0 else float("inf"),
        }

    # Signal-level regime distribution from signal_outcomes
    sig_regime_counts = Counter()
    sig_regime_ev = defaultdict(list)
    for sig in signals:
        regime = sig.get("regime", "") or "unknown"
        sig_regime_counts[regime] += 1
        ev = sig.get("meta", {}).get("ev_per_dollar", 0)
        sig_regime_ev[regime].append(ev)

    sig_regime_stats = {}
    for regime, evs in sig_regime_ev.items():
        sig_regime_stats[regime] = {
            "count": sig_regime_counts[regime],
            "avg_ev": round(mean(evs), 4) if evs else 0,
        }

    result = {
        "regime_transitions_detected": len(regime_changes),
        "transition_details": [
            {"from": rc["from"], "to": rc["to"]}
            for rc in regime_changes[:20]
        ],
        "counterfactual_by_regime": regime_performance,
        "signals_by_regime": sig_regime_stats,
        "recommendation": "",
    }

    # Recommendation
    if regime_performance:
        best_regime = max(regime_performance.items(), key=lambda x: x[1]["avg_pnl_pct"])
        worst_regime = min(regime_performance.items(), key=lambda x: x[1]["avg_pnl_pct"])
        result["recommendation"] = (
            f"Best regime for trading: '{best_regime[0]}' (WR={best_regime[1]['win_rate']:.1%}, "
            f"avg PnL={best_regime[1]['avg_pnl_pct']:.2f}%). "
            f"Worst: '{worst_regime[0]}' (WR={worst_regime[1]['win_rate']:.1%}, "
            f"avg PnL={worst_regime[1]['avg_pnl_pct']:.2f}%). "
            f"Detected {len(regime_changes)} regime transitions in live signals."
        )

    print(f"  Regime transitions: {len(regime_changes)}")
    print(f"  CF regimes: {list(regime_performance.keys())}")
    return result


# ---------------------------------------------------------------------------
# 5) Strategy Agreement Patterns
# ---------------------------------------------------------------------------

def analyze_strategy_agreement(signals: list[dict], sniper_signals: list[dict], cf_records: list[dict]) -> dict:
    """Find which strategy combinations produce the best outcomes."""
    print("\n=== Analysis 5: Strategy Agreement Patterns ===")

    # From sniper signals: actual strategy names
    combo_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnls": []})

    for sig in sniper_signals:
        strats = sig.get("strategies", [])
        strats_sorted = tuple(sorted(strats))
        combo_key = " + ".join(strats_sorted) if strats_sorted else "unknown"

        # Use R:R as proxy for quality (all sniper signals are pre-screened)
        rr = sig.get("rr_swing", 0)
        conf = sig.get("confidence", 0)

        combo_stats[combo_key]["count"] += 1
        if conf >= 85:
            combo_stats[combo_key]["wins"] += 1

    # From signal outcomes: n_agree analysis
    agree_stats = defaultdict(lambda: {"count": 0, "total_ev": 0, "confs": [], "chops": []})
    for sig in signals:
        n = sig.get("n_agree", 1)
        agree_stats[n]["count"] += 1
        agree_stats[n]["total_ev"] += sig.get("meta", {}).get("ev_per_dollar", 0)
        agree_stats[n]["confs"].append(sig.get("conf", 0))
        agree_stats[n]["chops"].append(sig.get("meta", {}).get("chop_score_smoothed", 0.5))

    agree_analysis = {}
    for n_agree, stats in sorted(agree_stats.items()):
        agree_analysis[str(n_agree)] = {
            "count": stats["count"],
            "avg_ev": round(stats["total_ev"] / stats["count"], 4) if stats["count"] else 0,
            "avg_conf": round(mean(stats["confs"]), 2) if stats["confs"] else 0,
            "avg_chop": round(mean(stats["chops"]), 4) if stats["chops"] else 0,
        }

    # From counterfactual: we don't have strategy names, but we can look at confidence bands
    # as a proxy for consensus quality
    conf_bands = {}
    for band_lo in range(50, 100, 5):
        band_hi = band_lo + 5
        in_band = [r for r in cf_records if band_lo <= r.get("confidence", 0) < band_hi]
        if in_band:
            wins = sum(1 for r in in_band if r.get("hypothetical_pnl_pct", 0) > 0)
            pnls = [r.get("hypothetical_pnl_pct", 0) for r in in_band]
            conf_bands[f"{band_lo}-{band_hi}"] = {
                "count": len(in_band),
                "win_rate": round(wins / len(in_band), 4),
                "avg_pnl": round(mean(pnls), 4),
            }

    # Strategy combo analysis from sniper
    combo_results = {}
    for combo, stats in sorted(combo_stats.items(), key=lambda x: -x[1]["count"]):
        combo_results[combo] = {
            "count": stats["count"],
            "high_conf_rate": round(stats["wins"] / stats["count"] * 100, 1) if stats["count"] else 0,
        }

    result = {
        "n_agree_analysis": agree_analysis,
        "confidence_band_analysis": conf_bands,
        "strategy_combos_from_sniper": combo_results,
        "recommendation": "",
    }

    # Recommendation
    if agree_analysis:
        best_agree = max(agree_analysis.items(), key=lambda x: x[1]["avg_ev"])
        result["recommendation"] = (
            f"Best consensus level: {best_agree[0]}-agree (avg EV={best_agree[1]['avg_ev']:.4f}, "
            f"avg conf={best_agree[1]['avg_conf']:.1f}). "
        )
        if "3" in agree_analysis and "2" in agree_analysis:
            ev3 = agree_analysis["3"]["avg_ev"]
            ev2 = agree_analysis["2"]["avg_ev"]
            if ev3 > ev2:
                result["recommendation"] += f"3-agree signals have {((ev3/max(ev2,0.001))-1)*100:.0f}% higher EV than 2-agree."
            else:
                result["recommendation"] += "2-agree signals surprisingly have higher EV — consensus count alone is not the full picture."

    # Named combo recommendation
    named_combos = {k: v for k, v in combo_results.items() if "regime_trend" in k or "monte_carlo" in k or "confidence_scorer" in k}
    if named_combos:
        best_named = max(named_combos.items(), key=lambda x: x[1]["high_conf_rate"])
        result["recommendation"] += f" Best named combo: {best_named[0]} ({best_named[1]['high_conf_rate']:.0f}% high-conf rate, N={best_named[1]['count']})."

    print(f"  Agree levels: {list(agree_analysis.keys())}")
    print(f"  Strategy combos: {len(combo_results)}")
    return result


# ---------------------------------------------------------------------------
# 6) Optimal Hold Time by Setup
# ---------------------------------------------------------------------------

def analyze_hold_times(cf_records: list[dict], sniper_signals: list[dict]) -> dict:
    """Find optimal hold times from counterfactual resolution data."""
    print("\n=== Analysis 6: Optimal Hold Time by Setup ===")

    # Group by symbol+side
    setup_hold = defaultdict(list)
    for rec in cf_records:
        sym = rec.get("symbol", "")
        side = rec.get("side", "")
        bars = rec.get("bars_to_resolve", 0)
        pnl = rec.get("hypothetical_pnl_pct", 0)
        hit_tp1 = rec.get("would_hit_tp1", False)
        hit_tp2 = rec.get("would_hit_tp2", False)

        if sym and side:
            setup_hold[f"{sym}_{side}"].append({
                "bars": bars,
                "pnl": pnl,
                "hit_tp1": hit_tp1,
                "hit_tp2": hit_tp2,
            })

    hold_analysis = {}
    for setup, trades in setup_hold.items():
        if not trades:
            continue

        bars_list = [t["bars"] for t in trades]
        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] < 0]

        win_bars = [t["bars"] for t in winners] if winners else [0]
        lose_bars = [t["bars"] for t in losers] if losers else [0]

        tp1_hit_rate = sum(1 for t in trades if t["hit_tp1"]) / len(trades)
        tp2_hit_rate = sum(1 for t in trades if t["hit_tp2"]) / len(trades)

        # Bars are hourly candles from the backtest
        hold_analysis[setup] = {
            "n_trades": len(trades),
            "avg_bars_to_resolve": round(mean(bars_list), 2),
            "median_bars": round(median(bars_list), 1) if bars_list else 0,
            "winner_avg_bars": round(mean(win_bars), 2) if win_bars else 0,
            "loser_avg_bars": round(mean(lose_bars), 2) if lose_bars else 0,
            "tp1_hit_rate": round(tp1_hit_rate, 4),
            "tp2_hit_rate": round(tp2_hit_rate, 4),
            "tp1_vs_tp2_gap": round(tp1_hit_rate - tp2_hit_rate, 4),
        }

    # Sniper hold target analysis
    sniper_hold_dist = Counter()
    for sig in sniper_signals:
        hold = sig.get("hold_target_hours", "")
        sniper_hold_dist[hold] += 1

    # TP recommendation: if tp1 hit rate >> tp2, take TP1
    tp_recommendations = {}
    for setup, stats in hold_analysis.items():
        gap = stats["tp1_vs_tp2_gap"]
        if gap > 0.2:
            tp_recommendations[setup] = f"Take TP1 (1.5R) — TP2 hit rate is {gap:.0%} lower. Quick scalp preferred."
        elif gap > 0.05:
            tp_recommendations[setup] = f"Split: 60% at TP1, 40% trail to TP2. Gap is moderate ({gap:.0%})."
        else:
            tp_recommendations[setup] = f"Hold for TP2 (2R+) — both TPs hit at similar rates (gap only {gap:.0%})."

    result = {
        "hold_time_by_setup": hold_analysis,
        "sniper_hold_target_distribution": dict(sniper_hold_dist),
        "tp_recommendations": tp_recommendations,
        "recommendation": "",
    }

    # Overall
    if hold_analysis:
        all_winners_bars = []
        for setup, trades in setup_hold.items():
            for t in trades:
                if t["pnl"] > 0:
                    all_winners_bars.append(t["bars"])

        if all_winners_bars:
            result["recommendation"] = (
                f"Winners resolve in avg {mean(all_winners_bars):.1f} bars (hours). "
                f"Median: {median(all_winners_bars):.0f}h. "
            )

        # Best TP strategy
        tp1_rates = [(s, d["tp1_hit_rate"]) for s, d in hold_analysis.items()]
        tp2_rates = [(s, d["tp2_hit_rate"]) for s, d in hold_analysis.items()]
        avg_tp1 = mean(r for _, r in tp1_rates) if tp1_rates else 0
        avg_tp2 = mean(r for _, r in tp2_rates) if tp2_rates else 0
        result["recommendation"] += (
            f"Across all setups: TP1 hit rate={avg_tp1:.1%}, TP2 hit rate={avg_tp2:.1%}. "
        )
        if avg_tp1 - avg_tp2 > 0.15:
            result["recommendation"] += "Data strongly favors taking 1.5R (TP1) over holding for 2R."
        else:
            result["recommendation"] += "TP1 and TP2 rates are close — holding for 2R is viable."

    print(f"  Setups analyzed: {list(hold_analysis.keys())}")
    return result


# ---------------------------------------------------------------------------
# 7) Drawdown Risk (Monte Carlo)
# ---------------------------------------------------------------------------

def analyze_drawdown_risk(cf_records: list[dict], edge_raw: dict) -> dict:
    """Monte Carlo drawdown simulation at various risk levels."""
    print("\n=== Analysis 7: Drawdown Risk Analysis (Monte Carlo) ===")

    # Extract win/loss distribution from counterfactual data
    pnls = [r.get("hypothetical_pnl_pct", 0) for r in cf_records if r.get("hypothetical_pnl_pct") is not None]
    if not pnls:
        return {"error": "No PnL data available"}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    overall_wr = len(wins) / len(pnls) if pnls else 0
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0

    # Use edge_raw for filtered stats if available
    leverage_table = edge_raw.get("leverage_table", [])
    # Focus on HYPE_BUY (best setup)
    hype_buy = next((s for s in leverage_table if s.get("setup") == "HYPE_BUY"), None)

    setups = {
        "all_signals": {"wr": overall_wr, "avg_win": avg_win, "avg_loss": abs(avg_loss)},
    }

    if hype_buy:
        setups["hype_buy_only"] = {
            "wr": hype_buy["win_rate"],
            "avg_win": hype_buy["avg_win_pct"],
            "avg_loss": hype_buy["avg_loss_pct"],
        }

    # Also add sniper-filtered estimate
    sniper_cf = [r for r in cf_records if r.get("confidence", 0) >= 65 and r.get("hypothetical_pnl_pct", 0) != 0]
    if sniper_cf:
        s_wins = [r["hypothetical_pnl_pct"] for r in sniper_cf if r["hypothetical_pnl_pct"] > 0]
        s_losses = [r["hypothetical_pnl_pct"] for r in sniper_cf if r["hypothetical_pnl_pct"] < 0]
        if s_wins and s_losses:
            setups["high_conf_65plus"] = {
                "wr": len(s_wins) / len(sniper_cf),
                "avg_win": mean(s_wins),
                "avg_loss": abs(mean(s_losses)),
            }

    N_SIMS = 10000
    N_TRADES = 200  # ~90 days of trading at 2-3 trades/day
    RISK_LEVELS = [0.02, 0.03, 0.05, 0.08, 0.10, 0.15]
    random.seed(42)

    all_results = {}
    for setup_name, params in setups.items():
        wr = params["wr"]
        avg_w = params["avg_win"] / 100  # convert pct to ratio
        avg_l = params["avg_loss"] / 100

        risk_results = {}
        for risk_pct in RISK_LEVELS:
            max_drawdowns = []
            final_equities = []
            ruin_count = 0  # equity < 20% of starting

            for _ in range(N_SIMS):
                equity = 1.0
                peak = 1.0
                max_dd = 0

                for _ in range(N_TRADES):
                    risk_amount = equity * risk_pct
                    if random.random() < wr:
                        # Win: gain proportional to avg_w/avg_l ratio
                        pnl = risk_amount * (avg_w / avg_l) if avg_l > 0 else risk_amount
                    else:
                        pnl = -risk_amount

                    equity += pnl
                    if equity <= 0:
                        equity = 0
                        break

                    peak = max(peak, equity)
                    dd = (peak - equity) / peak
                    max_dd = max(max_dd, dd)

                max_drawdowns.append(max_dd)
                final_equities.append(equity)
                if equity < 0.2:
                    ruin_count += 1

            risk_results[f"{int(risk_pct*100)}pct"] = {
                "risk_per_trade": risk_pct,
                "avg_max_drawdown": round(mean(max_drawdowns) * 100, 2),
                "median_max_drawdown": round(median(max_drawdowns) * 100, 2),
                "p95_max_drawdown": round(sorted(max_drawdowns)[int(0.95 * N_SIMS)] * 100, 2),
                "p99_max_drawdown": round(sorted(max_drawdowns)[int(0.99 * N_SIMS)] * 100, 2),
                "prob_50pct_drawdown": round(sum(1 for d in max_drawdowns if d >= 0.5) / N_SIMS * 100, 2),
                "prob_ruin_80pct_loss": round(ruin_count / N_SIMS * 100, 2),
                "median_final_equity_mult": round(median(final_equities), 3),
                "avg_final_equity_mult": round(mean(final_equities), 3),
                "p10_final_equity": round(sorted(final_equities)[int(0.10 * N_SIMS)], 3),
            }

        all_results[setup_name] = {
            "params": {
                "win_rate": round(wr, 4),
                "avg_win_pct": round(params["avg_win"], 2),
                "avg_loss_pct": round(params["avg_loss"], 2),
            },
            "risk_levels": risk_results,
        }

    # Find optimal risk level (< 1% ruin prob, max growth)
    recommendations = {}
    for setup_name, data in all_results.items():
        safe_levels = []
        for level_name, stats in data["risk_levels"].items():
            if stats["prob_ruin_80pct_loss"] < 1.0:
                safe_levels.append((level_name, stats))

        if safe_levels:
            best = max(safe_levels, key=lambda x: x[1]["median_final_equity_mult"])
            recommendations[setup_name] = (
                f"Optimal risk: {best[0]} per trade "
                f"(median {best[1]['median_final_equity_mult']:.1f}x growth over {N_TRADES} trades, "
                f"ruin prob {best[1]['prob_ruin_80pct_loss']:.1f}%, "
                f"max DD p95={best[1]['p95_max_drawdown']:.0f}%)"
            )
        else:
            recommendations[setup_name] = "All risk levels have >1% ruin probability. Reduce risk or improve edge."

    result = {
        "simulation_params": {"n_simulations": N_SIMS, "n_trades": N_TRADES},
        "setups": all_results,
        "optimal_risk_recommendations": recommendations,
    }

    for setup_name, rec in recommendations.items():
        print(f"  {setup_name}: {rec}")

    return result


# ---------------------------------------------------------------------------
# Bonus: Signal Quality on Live Signals
# ---------------------------------------------------------------------------

def score_live_signals(signals: list[dict]) -> dict:
    """Apply quality scoring to today's live signals."""
    print("\n=== Bonus: Quality Scoring on Live Signals ===")

    scored = []
    for sig in signals:
        score = compute_quality_score(sig, "signal_outcome")
        scored.append({
            "ts": sig.get("ts", 0),
            "sym": sig.get("sym", ""),
            "side": sig.get("side", ""),
            "conf": sig.get("conf", 0),
            "n_agree": sig.get("n_agree", 0),
            "ev": sig.get("meta", {}).get("ev_per_dollar", 0),
            "chop": sig.get("meta", {}).get("chop_score_smoothed", 0),
            "quality_score": score,
            "passed": sig.get("passed", False),
        })

    # Distribution
    dist = defaultdict(int)
    for s in scored:
        bucket = int(s["quality_score"] // 10) * 10
        dist[f"{bucket}-{bucket+10}"] += 1

    # Top signals
    top = sorted(scored, key=lambda x: -x["quality_score"])[:20]

    # By symbol
    by_sym = defaultdict(list)
    for s in scored:
        by_sym[s["sym"]].append(s["quality_score"])

    sym_stats = {}
    for sym, scores in by_sym.items():
        sym_stats[sym] = {
            "count": len(scores),
            "avg_quality": round(mean(scores), 2),
            "max_quality": round(max(scores), 2),
            "pct_above_60": round(sum(1 for s in scores if s >= 60) / len(scores) * 100, 1),
        }

    result = {
        "total_scored": len(scored),
        "distribution": dict(dist),
        "by_symbol": sym_stats,
        "top_20_signals": top,
    }

    print(f"  Scored {len(scored)} live signals")
    for sym, stats in sym_stats.items():
        print(f"  {sym}: avg quality={stats['avg_quality']}, {stats['pct_above_60']:.0f}% above 60")

    return result


# ---------------------------------------------------------------------------
# Markdown Report Generator
# ---------------------------------------------------------------------------

def generate_markdown(results: dict) -> str:
    """Generate the DEEP_ANALYSIS.md report."""
    lines = [
        "# Deep Signal Analysis Report",
        "",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "---",
        "",
    ]

    # Executive Summary
    lines.extend([
        "## Executive Summary",
        "",
    ])

    q = results.get("quality_scoring", {})
    if q.get("optimal_threshold_by_pf"):
        t = q["optimal_threshold_by_pf"]
        lines.append(f"- **Quality Score Sweet Spot:** Score >= {t['threshold']} yields PF={t['profit_factor']}, WR={t['win_rate']:.1%} across {t['n_signals']} signals")

    dd = results.get("drawdown_risk", {})
    recs = dd.get("optimal_risk_recommendations", {})
    for setup, rec in recs.items():
        lines.append(f"- **Risk ({setup}):** {rec}")

    tod = results.get("time_of_day", {})
    if tod.get("recommendation"):
        lines.append(f"- **Time-of-Day:** {tod['recommendation']}")

    clust = results.get("signal_clustering", {})
    if clust.get("recommendation"):
        lines.append(f"- **Clustering:** {clust['recommendation']}")

    regime = results.get("regime_transitions", {})
    if regime.get("recommendation"):
        lines.append(f"- **Regime:** {regime['recommendation']}")

    strat = results.get("strategy_agreement", {})
    if strat.get("recommendation"):
        lines.append(f"- **Strategy Agreement:** {strat['recommendation']}")

    hold = results.get("hold_times", {})
    if hold.get("recommendation"):
        lines.append(f"- **Hold Time:** {hold['recommendation']}")

    lines.extend(["", "---", ""])

    # 1) Quality Scoring
    lines.extend([
        "## 1. Signal Quality Scoring",
        "",
        "Composite score (0-100): Confidence 40% | Consensus 25% | EV 15% | Regime 10% | Chop 10%",
        "",
    ])

    if q.get("score_distribution"):
        lines.extend(["### Score Distribution vs Win Rate", ""])
        lines.append("| Score Band | Count | Win Rate | Avg PnL% |")
        lines.append("|------------|-------|----------|----------|")
        for band, stats in sorted(q["score_distribution"].items()):
            lines.append(f"| {band} | {stats['count']} | {stats['win_rate']:.1%} | {stats['avg_pnl']:+.2f}% |")
        lines.append("")

    if q.get("threshold_analysis"):
        lines.extend(["### Quality Threshold Optimization", ""])
        lines.append("| Threshold | N Signals | Win Rate | Profit Factor | Avg PnL% | Total PnL% |")
        lines.append("|-----------|-----------|----------|---------------|----------|------------|")
        for t in q["threshold_analysis"]:
            pf_str = f"{t['profit_factor']:.2f}" if t['profit_factor'] < 100 else "INF"
            lines.append(f"| >= {t['threshold']} | {t['n_signals']} | {t['win_rate']:.1%} | {pf_str} | {t['avg_pnl_pct']:+.2f}% | {t['total_pnl_pct']:+.1f}% |")
        lines.append("")

    lines.extend(["---", ""])

    # 2) Time-of-Day
    lines.extend(["## 2. Time-of-Day Edge", ""])

    if tod.get("signal_hourly_breakdown"):
        lines.extend(["### Signal Volume & Quality by Hour (UTC)", ""])
        lines.append("| Hour | Signals | Avg Conf | High Conf% | 3+ Agree% | Avg EV | Avg Chop |")
        lines.append("|------|---------|----------|------------|-----------|--------|----------|")
        for hour, stats in sorted(tod["signal_hourly_breakdown"].items(), key=lambda x: int(x[0])):
            lines.append(
                f"| {hour}:00 | {stats['total_signals']} | {stats['avg_confidence']:.1f} | "
                f"{stats['high_conf_pct']:.0f}% | {stats['consensus_3plus_pct']:.0f}% | "
                f"{stats['avg_ev']:.4f} | {stats['avg_chop']:.3f} |"
            )
        lines.append("")

    if tod.get("counterfactual_hourly_breakdown"):
        lines.extend(["### Counterfactual Outcomes by Hour", ""])
        lines.append("| Hour | Records | Win Rate | Avg PnL% | Total PnL% |")
        lines.append("|------|---------|----------|----------|------------|")
        for hour, stats in sorted(tod["counterfactual_hourly_breakdown"].items(), key=lambda x: int(x[0])):
            lines.append(f"| {hour}:00 | {stats['n_records']} | {stats['win_rate']:.1%} | {stats['avg_pnl_pct']:+.2f}% | {stats['total_pnl_pct']:+.1f}% |")
        lines.append("")

    lines.extend(["---", ""])

    # 3) Clustering
    lines.extend(["## 3. Signal Clustering", ""])

    if clust and "error" not in clust:
        lines.extend([
            f"- **Time span:** {clust.get('time_span_hours', 0):.1f} hours",
            f"- **Total signals:** {clust.get('total_signals_analyzed', 0)}",
            f"- **Avg gap:** {clust.get('avg_gap_minutes', 0):.1f} min (median: {clust.get('median_gap_minutes', 0):.1f} min)",
            f"- **Signals per hour:** avg {clust.get('signals_per_hour_stats', {}).get('avg', 0):.1f}, max {clust.get('signals_per_hour_stats', {}).get('max', 0)}",
            "",
        ])

        ca = clust.get("cluster_analysis", {})
        lines.extend([
            "### Burst Analysis (signals within 5 min)",
            f"- **Clusters found:** {ca.get('total_clusters', 0)}",
            f"- **Avg cluster size:** {ca.get('avg_cluster_size', 0):.1f}",
            f"- **Max cluster size:** {ca.get('max_cluster_size', 0)}",
            f"- **% signals in clusters:** {ca.get('pct_signals_in_clusters', 0):.0f}%",
            "",
        ])

        sf = clust.get("sniper_followup", {})
        lines.extend([
            "### SNIPER Follow-up Pattern",
            f"- **Total SNIPER signals:** {sf.get('total_sniper_signals', 0)}",
            f"- **Followed within 30 min:** {sf.get('signals_followed_within_30min', 0)} ({sf.get('followup_rate', 0):.0f}%)",
            "",
        ])

    lines.extend(["---", ""])

    # 4) Regime Transitions
    lines.extend(["## 4. Regime Transition Analysis", ""])

    if regime.get("counterfactual_by_regime"):
        lines.extend(["### Performance by Regime (Counterfactual)", ""])
        lines.append("| Regime | Count | Win Rate | Avg PnL% | Profit Factor |")
        lines.append("|--------|-------|----------|----------|---------------|")
        for r_name, stats in sorted(regime["counterfactual_by_regime"].items(), key=lambda x: -x[1]["avg_pnl_pct"]):
            pf_str = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] < 100 else "INF"
            lines.append(f"| {r_name} | {stats['count']} | {stats['win_rate']:.1%} | {stats['avg_pnl_pct']:+.2f}% | {pf_str} |")
        lines.append("")

    if regime.get("signals_by_regime"):
        lines.extend(["### Live Signal Regime Distribution", ""])
        lines.append("| Regime | Signals | Avg EV |")
        lines.append("|--------|---------|--------|")
        for r_name, stats in sorted(regime["signals_by_regime"].items(), key=lambda x: -x[1]["avg_ev"]):
            lines.append(f"| {r_name or '(empty)'} | {stats['count']} | {stats['avg_ev']:.4f} |")
        lines.append("")

    lines.extend(["---", ""])

    # 5) Strategy Agreement
    lines.extend(["## 5. Strategy Agreement Patterns", ""])

    if strat.get("n_agree_analysis"):
        lines.extend(["### Consensus Level Analysis (Live Signals)", ""])
        lines.append("| N Agree | Count | Avg EV | Avg Conf | Avg Chop |")
        lines.append("|---------|-------|--------|----------|----------|")
        for n, stats in sorted(strat["n_agree_analysis"].items()):
            lines.append(f"| {n} | {stats['count']} | {stats['avg_ev']:.4f} | {stats['avg_conf']:.1f} | {stats['avg_chop']:.3f} |")
        lines.append("")

    if strat.get("confidence_band_analysis"):
        lines.extend(["### Counterfactual Win Rate by Confidence Band", ""])
        lines.append("| Confidence | Count | Win Rate | Avg PnL% |")
        lines.append("|------------|-------|----------|----------|")
        for band, stats in sorted(strat["confidence_band_analysis"].items()):
            lines.append(f"| {band} | {stats['count']} | {stats['win_rate']:.1%} | {stats['avg_pnl']:+.2f}% |")
        lines.append("")

    if strat.get("strategy_combos_from_sniper"):
        lines.extend(["### Strategy Combinations (from SNIPER signals)", ""])
        lines.append("| Combination | Count | High Conf Rate |")
        lines.append("|-------------|-------|----------------|")
        for combo, stats in sorted(strat["strategy_combos_from_sniper"].items(), key=lambda x: -x[1]["count"]):
            lines.append(f"| {combo} | {stats['count']} | {stats['high_conf_rate']:.0f}% |")
        lines.append("")

    lines.extend(["---", ""])

    # 6) Hold Times
    lines.extend(["## 6. Optimal Hold Time", ""])

    if hold.get("hold_time_by_setup"):
        lines.extend(["### Resolution Speed by Setup", ""])
        lines.append("| Setup | N | Avg Bars | Winner Bars | Loser Bars | TP1 Hit | TP2 Hit | TP Recommendation |")
        lines.append("|-------|---|----------|-------------|------------|---------|---------|-------------------|")
        for setup, stats in sorted(hold["hold_time_by_setup"].items()):
            tp_rec = hold.get("tp_recommendations", {}).get(setup, "")
            short_rec = tp_rec[:50] + "..." if len(tp_rec) > 50 else tp_rec
            lines.append(
                f"| {setup} | {stats['n_trades']} | {stats['avg_bars_to_resolve']:.1f} | "
                f"{stats['winner_avg_bars']:.1f} | {stats['loser_avg_bars']:.1f} | "
                f"{stats['tp1_hit_rate']:.1%} | {stats['tp2_hit_rate']:.1%} | {short_rec} |"
            )
        lines.append("")

    if hold.get("tp_recommendations"):
        lines.extend(["### TP Recommendations by Setup", ""])
        for setup, rec in hold["tp_recommendations"].items():
            lines.append(f"- **{setup}:** {rec}")
        lines.append("")

    lines.extend(["---", ""])

    # 7) Drawdown Risk
    lines.extend(["## 7. Drawdown Risk Analysis", ""])

    dd_setups = dd.get("setups", {})
    for setup_name, data in dd_setups.items():
        params = data.get("params", {})
        lines.extend([
            f"### {setup_name} (WR={params.get('win_rate', 0):.1%}, win={params.get('avg_win_pct', 0):.1f}%, loss={params.get('avg_loss_pct', 0):.1f}%)",
            "",
            "| Risk/Trade | Avg Max DD | P95 Max DD | P99 Max DD | 50% DD Prob | Ruin Prob | Median Growth |",
            "|------------|-----------|------------|------------|-------------|-----------|---------------|",
        ])
        for level_name, stats in sorted(data.get("risk_levels", {}).items()):
            lines.append(
                f"| {stats['risk_per_trade']:.0%} | {stats['avg_max_drawdown']:.1f}% | "
                f"{stats['p95_max_drawdown']:.1f}% | {stats['p99_max_drawdown']:.1f}% | "
                f"{stats['prob_50pct_drawdown']:.1f}% | {stats['prob_ruin_80pct_loss']:.1f}% | "
                f"{stats['median_final_equity_mult']:.2f}x |"
            )
        lines.append("")

    if recs:
        lines.extend(["### Optimal Risk Recommendations", ""])
        for setup, rec in recs.items():
            lines.append(f"- **{setup}:** {rec}")
        lines.append("")

    lines.extend(["---", ""])

    # Bonus: Live signal quality
    live = results.get("live_signal_quality", {})
    if live:
        lines.extend(["## Bonus: Today's Live Signal Quality", ""])

        if live.get("by_symbol"):
            lines.append("| Symbol | Count | Avg Quality | Max Quality | % Above 60 |")
            lines.append("|--------|-------|-------------|-------------|------------|")
            for sym, stats in sorted(live["by_symbol"].items(), key=lambda x: -x[1]["avg_quality"]):
                lines.append(f"| {sym} | {stats['count']} | {stats['avg_quality']:.1f} | {stats['max_quality']:.1f} | {stats['pct_above_60']:.0f}% |")
            lines.append("")

        if live.get("distribution"):
            lines.extend(["### Quality Score Distribution", ""])
            lines.append("| Score Range | Count |")
            lines.append("|-------------|-------|")
            for band, count in sorted(live["distribution"].items()):
                lines.append(f"| {band} | {count} |")
            lines.append("")

        lines.extend(["---", ""])

    # Actionable Summary
    lines.extend([
        "## Actionable Recommendations",
        "",
        "### Immediate Actions",
        "",
    ])

    action_num = 1

    if q.get("optimal_threshold_by_pf"):
        t = q["optimal_threshold_by_pf"]
        lines.append(f"{action_num}. **Set quality score floor to {t['threshold']}** — filters to PF={t['profit_factor']}, WR={t['win_rate']:.1%} over {t['n_signals']} historical signals")
        action_num += 1

    if strat.get("n_agree_analysis"):
        best_agree = max(strat["n_agree_analysis"].items(), key=lambda x: x[1]["avg_ev"])
        lines.append(f"{action_num}. **Require {best_agree[0]}-agree minimum** — highest avg EV at {best_agree[1]['avg_ev']:.4f}")
        action_num += 1

    if tod.get("best_hours_by_ev") and tod["best_hours_by_ev"]:
        best_h = tod["best_hours_by_ev"][0]
        lines.append(f"{action_num}. **Focus manual trading at UTC {best_h['hour']}:00** — highest avg EV signals")
        action_num += 1

    if recs:
        for setup, rec in recs.items():
            lines.append(f"{action_num}. **{setup} risk sizing:** {rec}")
            action_num += 1

    if hold.get("tp_recommendations"):
        for setup, rec in list(hold["tp_recommendations"].items())[:3]:
            lines.append(f"{action_num}. **{setup} TP strategy:** {rec}")
            action_num += 1

    lines.extend([
        "",
        "### Strategic Actions",
        "",
        f"{action_num}. Implement quality score as a real-time filter in the signal pipeline",
    ])
    action_num += 1
    lines.append(f"{action_num}. Add time-of-day weighting to the ensemble scoring")
    action_num += 1
    lines.append(f"{action_num}. Track regime transitions as a separate signal trigger")
    action_num += 1
    lines.append(f"{action_num}. Build a cluster detector that alerts when 3+ signals fire in 5 min")

    lines.extend(["", "---", "", "*Analysis complete. All data saved to deep_analysis_results.json*"])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("DEEP SIGNAL ANALYSIS")
    print("=" * 60)
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    # Load data
    print("Loading data...")
    signals = load_jsonl(SIGNAL_OUTCOMES)
    sniper = load_jsonl(SNIPER_SIGNALS)
    cf_data = load_json(COUNTERFACTUAL)
    edge_raw = load_json(EDGE_RAW)

    cf_records = cf_data.get("records", []) if cf_data else []
    print(f"  Counterfactual records: {len(cf_records)}")
    print()

    # Run analyses
    results = {}

    results["quality_scoring"] = analyze_quality_scoring(cf_records)
    results["time_of_day"] = analyze_time_of_day(signals, cf_records)
    results["signal_clustering"] = analyze_signal_clustering(signals, sniper)
    results["regime_transitions"] = analyze_regime_transitions(signals, cf_records)
    results["strategy_agreement"] = analyze_strategy_agreement(signals, sniper, cf_records)
    results["hold_times"] = analyze_hold_times(cf_records, sniper)
    results["drawdown_risk"] = analyze_drawdown_risk(cf_records, edge_raw)
    results["live_signal_quality"] = score_live_signals(signals)

    # Metadata
    results["metadata"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": {
            "signal_outcomes": len(signals),
            "sniper_signals": len(sniper),
            "counterfactual_records": len(cf_records),
            "edge_raw_loaded": bool(edge_raw),
        },
    }

    # Save JSON
    print(f"\nSaving results to {OUT_JSON}...")
    MANUAL.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Saved {OUT_JSON.name} ({OUT_JSON.stat().st_size // 1024} KB)")

    # Save Markdown
    print(f"Generating {OUT_MD}...")
    md = generate_markdown(results)
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(f"  Saved {OUT_MD.name} ({OUT_MD.stat().st_size // 1024} KB)")

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
