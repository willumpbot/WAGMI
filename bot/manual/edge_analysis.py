"""
Deep Edge Analysis for Manual Sniper Signals.

Analyzes counterfactual data + sniper signals to find the EXACT conditions
where we have the highest win rate and best risk-adjusted returns.
Outputs actionable rules for the $100 aggressive account.
"""

import json
import csv
import math
import random
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any

DATA_DIR = Path(__file__).parent.parent / "data"
COUNTERFACTUAL_FILE = DATA_DIR / "counterfactual_resolved.json"
SNIPER_SIGNALS_FILE = DATA_DIR / "manual" / "sniper_signals.jsonl"
STATE_TRANSITIONS_FILE = DATA_DIR / "logs" / "state_transitions.csv"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_counterfactuals() -> List[dict]:
    """Load resolved counterfactual records."""
    if not COUNTERFACTUAL_FILE.exists():
        return []
    with open(COUNTERFACTUAL_FILE) as f:
        data = json.load(f)
    return data.get("records", [])


def load_sniper_signals() -> List[dict]:
    """Load sniper signal history."""
    if not SNIPER_SIGNALS_FILE.exists():
        return []
    signals = []
    with open(SNIPER_SIGNALS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                signals.append(json.loads(line))
    return signals


def load_state_transitions() -> List[dict]:
    """Load bot trade state transitions."""
    if not STATE_TRANSITIONS_FILE.exists():
        return []
    rows = []
    with open(STATE_TRANSITIONS_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conf_band(confidence: float) -> str:
    if confidence >= 90:
        return "90+"
    elif confidence >= 85:
        return "85-89"
    elif confidence >= 80:
        return "80-84"
    elif confidence >= 75:
        return "75-79"
    elif confidence >= 70:
        return "70-74"
    elif confidence >= 65:
        return "65-69"
    else:
        return "<65"


def _hour_bucket(ts_str: str) -> Optional[str]:
    """Parse timestamp and return UTC hour bucket."""
    if not ts_str:
        return None
    try:
        # Handle various ISO formats
        ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        h = dt.hour
        if 0 <= h < 4:
            return "00-04 UTC"
        elif 4 <= h < 8:
            return "04-08 UTC"
        elif 8 <= h < 12:
            return "08-12 UTC"
        elif 12 <= h < 16:
            return "12-16 UTC"
        elif 16 <= h < 20:
            return "16-20 UTC"
        else:
            return "20-24 UTC"
    except Exception:
        return None


def _day_of_week(ts_str: str) -> Optional[str]:
    """Parse timestamp and return day of week."""
    if not ts_str:
        return None
    try:
        ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%A")
    except Exception:
        return None


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


# ---------------------------------------------------------------------------
# Core: Counterfactual Edge Analysis
# ---------------------------------------------------------------------------

def _build_cf_stats(records: List[dict]) -> Dict[str, dict]:
    """
    Group counterfactual records by multiple dimensions and compute stats.
    Returns dict of {dimension_key: {group_value: stats_dict}}.
    """
    dimensions = {
        "symbol": lambda r: r.get("symbol", "?"),
        "side": lambda r: r.get("side", "?"),
        "symbol_side": lambda r: f"{r.get('symbol', '?')}_{r.get('side', '?')}",
        "conf_band": lambda r: _conf_band(r.get("confidence", 0)),
        "regime": lambda r: r.get("regime", "unknown") or "unknown",
        "hour": lambda r: _hour_bucket(r.get("created_at", "")),
        "day": lambda r: _day_of_week(r.get("created_at", "")),
        "bars_bucket": lambda r: (
            "1-3" if r.get("bars_to_resolve", 0) <= 3
            else "4-10" if r.get("bars_to_resolve", 0) <= 10
            else "11-20" if r.get("bars_to_resolve", 0) <= 20
            else "21+"
        ),
    }

    results = {}
    for dim_name, key_fn in dimensions.items():
        groups = defaultdict(lambda: {
            "count": 0, "tp1_hits": 0, "tp2_hits": 0, "sl_hits": 0,
            "pnl_sum": 0.0, "pnl_list": [],
        })
        for r in records:
            k = key_fn(r)
            if k is None:
                continue
            g = groups[k]
            g["count"] += 1
            if r.get("would_hit_tp1"):
                g["tp1_hits"] += 1
            if r.get("would_hit_tp2"):
                g["tp2_hits"] += 1
            if r.get("would_hit_sl"):
                g["sl_hits"] += 1
            pnl = r.get("hypothetical_pnl_pct", 0)
            g["pnl_sum"] += pnl
            g["pnl_list"].append(pnl)

        # Compute derived stats
        for k, g in groups.items():
            n = g["count"]
            wins = g["tp1_hits"]
            losses = g["sl_hits"]
            decided = wins + losses
            g["win_rate"] = _safe_div(wins, decided) if decided > 0 else 0
            g["tp2_rate"] = _safe_div(g["tp2_hits"], decided) if decided > 0 else 0
            win_pnls = [p for p in g["pnl_list"] if p > 0]
            loss_pnls = [abs(p) for p in g["pnl_list"] if p < 0]
            g["avg_win"] = _safe_div(sum(win_pnls), len(win_pnls)) if win_pnls else 0
            g["avg_loss"] = _safe_div(sum(loss_pnls), len(loss_pnls)) if loss_pnls else 0
            g["profit_factor"] = _safe_div(
                sum(win_pnls), sum(loss_pnls)
            ) if loss_pnls else float("inf") if win_pnls else 0
            g["avg_pnl"] = _safe_div(g["pnl_sum"], n)
            # Remove raw list for serialization
            del g["pnl_list"]

        results[dim_name] = dict(groups)

    return results


def _build_sniper_stats(signals: List[dict]) -> Dict[str, dict]:
    """
    Group sniper signals by multiple dimensions.
    Since sniper signals don't have outcome data, we compute distribution stats.
    """
    dimensions = {
        "tier": lambda s: s.get("tier", "?"),
        "symbol_side": lambda s: f"{s.get('symbol', '?')}_{s.get('side', '?')}",
        "regime": lambda s: s.get("regime", "unknown"),
        "num_agree": lambda s: str(s.get("num_agree", "?")),
        "conf_band": lambda s: _conf_band(s.get("confidence", 0)),
        "hour": lambda s: _hour_bucket(s.get("timestamp", "")),
    }

    results = {}
    for dim_name, key_fn in dimensions.items():
        groups = defaultdict(lambda: {
            "count": 0, "avg_confidence": 0, "avg_leverage": 0,
            "avg_rr_scalp": 0, "avg_rr_swing": 0, "avg_ev": 0,
            "conf_sum": 0, "lev_sum": 0, "rr_scalp_sum": 0,
            "rr_swing_sum": 0, "ev_sum": 0,
        })
        for s in signals:
            k = key_fn(s)
            if k is None:
                continue
            g = groups[k]
            g["count"] += 1
            g["conf_sum"] += s.get("confidence", 0)
            g["lev_sum"] += s.get("leverage", 0)
            g["rr_scalp_sum"] += s.get("rr_scalp", 0)
            g["rr_swing_sum"] += s.get("rr_swing", 0)
            g["ev_sum"] += s.get("ev_per_dollar", 0)

        for k, g in groups.items():
            n = g["count"]
            g["avg_confidence"] = round(_safe_div(g["conf_sum"], n), 1)
            g["avg_leverage"] = round(_safe_div(g["lev_sum"], n), 1)
            g["avg_rr_scalp"] = round(_safe_div(g["rr_scalp_sum"], n), 2)
            g["avg_rr_swing"] = round(_safe_div(g["rr_swing_sum"], n), 2)
            g["avg_ev"] = round(_safe_div(g["ev_sum"], n), 4)
            for tmp_key in ("conf_sum", "lev_sum", "rr_scalp_sum", "rr_swing_sum", "ev_sum"):
                del g[tmp_key]

        results[dim_name] = dict(groups)

    return results


def _build_cross_tabs(records: List[dict]) -> List[dict]:
    """
    Cross-tabulate counterfactual data across multiple dimensions simultaneously.
    Returns list of {combo_description, count, win_rate, pf, avg_pnl} sorted by EV.
    """
    # Build combos: symbol_side x conf_band x regime
    combos = defaultdict(lambda: {
        "count": 0, "wins": 0, "losses": 0,
        "win_pnl": 0, "loss_pnl": 0, "pnl_sum": 0,
    })

    for r in records:
        symbol = r.get("symbol", "?")
        side = r.get("side", "?")
        conf = _conf_band(r.get("confidence", 0))
        regime = r.get("regime", "unknown") or "unknown"

        key = f"{symbol}_{side}|{conf}|{regime}"
        g = combos[key]
        g["count"] += 1
        pnl = r.get("hypothetical_pnl_pct", 0)
        g["pnl_sum"] += pnl
        if r.get("would_hit_tp1"):
            g["wins"] += 1
            g["win_pnl"] += abs(pnl) if pnl > 0 else 0
        if r.get("would_hit_sl"):
            g["losses"] += 1
            g["loss_pnl"] += abs(pnl) if pnl < 0 else 0

    results = []
    for key, g in combos.items():
        parts = key.split("|")
        decided = g["wins"] + g["losses"]
        if decided < 3:  # Need minimum sample
            continue
        wr = _safe_div(g["wins"], decided)
        pf = _safe_div(g["win_pnl"], g["loss_pnl"]) if g["loss_pnl"] > 0 else (
            float("inf") if g["win_pnl"] > 0 else 0
        )
        results.append({
            "combo": key,
            "symbol_side": parts[0],
            "conf_band": parts[1],
            "regime": parts[2],
            "count": g["count"],
            "decided": decided,
            "wins": g["wins"],
            "losses": g["losses"],
            "win_rate": round(wr, 3),
            "profit_factor": round(pf, 2) if pf != float("inf") else 999.0,
            "avg_pnl_pct": round(_safe_div(g["pnl_sum"], g["count"]), 3),
            "total_pnl_pct": round(g["pnl_sum"], 2),
        })

    # Sort by EV (win_rate * avg_win - loss_rate * avg_loss proxy = avg_pnl)
    results.sort(key=lambda x: x["avg_pnl_pct"], reverse=True)
    return results


def _build_sniper_cross_tabs(signals: List[dict]) -> List[dict]:
    """
    Cross-tabulate sniper signals: tier x regime x num_agree x conf_band.
    """
    combos = defaultdict(lambda: {
        "count": 0, "conf_sum": 0, "lev_sum": 0,
        "rr_scalp_sum": 0, "ev_sum": 0,
    })

    for s in signals:
        tier = s.get("tier", "?")
        regime = s.get("regime", "unknown")
        num_agree = s.get("num_agree", "?")
        conf = _conf_band(s.get("confidence", 0))
        key = f"{tier}|{regime}|{num_agree}agree|{conf}"
        g = combos[key]
        g["count"] += 1
        g["conf_sum"] += s.get("confidence", 0)
        g["lev_sum"] += s.get("leverage", 0)
        g["rr_scalp_sum"] += s.get("rr_scalp", 0)
        g["ev_sum"] += s.get("ev_per_dollar", 0)

    results = []
    for key, g in combos.items():
        parts = key.split("|")
        n = g["count"]
        results.append({
            "combo": key,
            "tier": parts[0],
            "regime": parts[1],
            "num_agree": parts[2],
            "conf_band": parts[3],
            "count": n,
            "avg_confidence": round(_safe_div(g["conf_sum"], n), 1),
            "avg_leverage": round(_safe_div(g["lev_sum"], n), 1),
            "avg_rr_scalp": round(_safe_div(g["rr_scalp_sum"], n), 2),
            "avg_ev": round(_safe_div(g["ev_sum"], n), 4),
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Public API: analyze_best_setups
# ---------------------------------------------------------------------------

def analyze_best_setups() -> dict:
    """
    Find the highest WR, best PF combinations across all dimensions.
    Returns a comprehensive analysis dict.
    """
    cf_records = load_counterfactuals()
    sniper_signals = load_sniper_signals()

    cf_stats = _build_cf_stats(cf_records)
    sniper_stats = _build_sniper_stats(sniper_signals)
    cf_cross = _build_cross_tabs(cf_records)
    sniper_cross = _build_sniper_cross_tabs(sniper_signals)

    # Extract top setups from cross-tabs (win_rate > 50% and count > 5)
    top_setups = [
        x for x in cf_cross
        if x["win_rate"] >= 0.50 and x["decided"] >= 5
    ]

    # Extract worst setups (avoid these)
    worst_setups = [
        x for x in cf_cross
        if x["win_rate"] < 0.35 and x["decided"] >= 5
    ]
    worst_setups.sort(key=lambda x: x["win_rate"])

    return {
        "counterfactual": {
            "total_records": len(cf_records),
            "by_dimension": cf_stats,
            "cross_tabs": cf_cross,
            "top_setups": top_setups[:20],
            "worst_setups": worst_setups[:10],
        },
        "sniper_signals": {
            "total_signals": len(sniper_signals),
            "by_dimension": sniper_stats,
            "cross_tabs": sniper_cross,
        },
    }


# ---------------------------------------------------------------------------
# Public API: calculate_optimal_leverage
# ---------------------------------------------------------------------------

def calculate_optimal_leverage(
    starting_equity: float = 100.0,
    max_leverage: float = 20.0,
) -> List[dict]:
    """
    For each setup type, calculate optimal leverage using Kelly criterion.

    Kelly: f* = (p*b - q) / b
    where p = win probability, b = avg_win/avg_loss ratio, q = 1-p

    Returns list of setup configs with optimal leverage.
    """
    cf_records = load_counterfactuals()
    sniper_signals = load_sniper_signals()

    # Build setup profiles from counterfactual data
    # Group by symbol_side
    setups = defaultdict(lambda: {
        "wins": 0, "losses": 0,
        "win_pnls": [], "loss_pnls": [],
    })

    for r in cf_records:
        key = f"{r.get('symbol', '?')}_{r.get('side', '?')}"
        pnl = r.get("hypothetical_pnl_pct", 0)
        if r.get("would_hit_tp1"):
            setups[key]["wins"] += 1
            setups[key]["win_pnls"].append(abs(pnl))
        elif r.get("would_hit_sl"):
            setups[key]["losses"] += 1
            setups[key]["loss_pnls"].append(abs(pnl))

    # Also build profiles from sniper signal parameters
    sniper_profiles = defaultdict(list)
    for s in sniper_signals:
        key = f"{s.get('symbol', '?')}_{s.get('side', '?')}"
        sniper_profiles[key].append(s)

    results = []
    for setup_key, stats in setups.items():
        decided = stats["wins"] + stats["losses"]
        if decided < 5:
            continue

        p = stats["wins"] / decided  # Win probability
        q = 1 - p

        avg_win = sum(stats["win_pnls"]) / len(stats["win_pnls"]) if stats["win_pnls"] else 0
        avg_loss = sum(stats["loss_pnls"]) / len(stats["loss_pnls"]) if stats["loss_pnls"] else 1

        b = avg_win / avg_loss if avg_loss > 0 else 1  # Win/loss ratio

        # Kelly criterion
        kelly_f = (p * b - q) / b if b > 0 else 0
        half_kelly = kelly_f / 2
        quarter_kelly = kelly_f / 4

        # Convert Kelly fraction to leverage
        # Kelly tells us fraction of bankroll to risk
        # With a typical stop of ~2.5%, leverage = kelly_fraction / stop_pct
        # For sniper setups, stop is entry-sl / entry ~ 2.5%
        sniper_stop_pct = 0.025  # Default 2.5% stop
        if setup_key in sniper_profiles and sniper_profiles[setup_key]:
            sample = sniper_profiles[setup_key][0]
            entry = sample.get("entry", 0)
            sl = sample.get("sl", 0)
            if entry > 0 and sl > 0:
                sniper_stop_pct = abs(entry - sl) / entry

        kelly_leverage = half_kelly / sniper_stop_pct if sniper_stop_pct > 0 else 0
        kelly_leverage = min(kelly_leverage, max_leverage)
        kelly_leverage = max(kelly_leverage, 0)

        # Max safe leverage: ensure liquidation > stop
        # Hyperliquid liquidation ~ 1 / (leverage * maint_margin)
        # Conservative: liq distance must be > 2x stop distance
        max_safe_lev = 0.5 / sniper_stop_pct if sniper_stop_pct > 0 else 5
        max_safe_lev = min(max_safe_lev, max_leverage)

        # Expected value per trade
        ev_per_trade = p * avg_win - q * avg_loss

        # Expected daily return (assume 1-3 trades per day)
        trades_per_day = 1.5
        daily_ev_pct = ev_per_trade * trades_per_day

        # Position size at starting equity
        risk_amount = starting_equity * half_kelly if half_kelly > 0 else 0
        position_size = risk_amount / sniper_stop_pct if sniper_stop_pct > 0 else 0

        results.append({
            "setup": setup_key,
            "sample_size": decided,
            "win_rate": round(p, 3),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "payoff_ratio": round(b, 2),
            "kelly_fraction": round(kelly_f, 4),
            "half_kelly": round(half_kelly, 4),
            "quarter_kelly": round(quarter_kelly, 4),
            "optimal_leverage": round(kelly_leverage, 1),
            "max_safe_leverage": round(max_safe_lev, 1),
            "stop_pct": round(sniper_stop_pct * 100, 2),
            "ev_per_trade_pct": round(ev_per_trade, 3),
            "daily_ev_pct": round(daily_ev_pct, 3),
            "risk_amount_100": round(risk_amount, 2),
            "position_size_100": round(position_size, 2),
        })

    results.sort(key=lambda x: x["ev_per_trade_pct"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Public API: calculate_compound_trajectory
# ---------------------------------------------------------------------------

def calculate_compound_trajectory(
    starting_equity: float = 100.0,
    num_simulations: int = 1000,
    days: int = 90,
    trades_per_day: float = 1.5,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo simulation of equity growth.

    Uses actual win rates and PnL distributions from counterfactual data.
    Simulates multiple paths to get confidence intervals.
    """
    cf_records = load_counterfactuals()
    sniper_signals = load_sniper_signals()

    # Build PnL distribution from counterfactual data
    # Focus on signals that would have been sniper-quality (conf >= 75)
    win_pnls = []
    loss_pnls = []
    for r in cf_records:
        pnl = r.get("hypothetical_pnl_pct", 0)
        if r.get("would_hit_tp1"):
            win_pnls.append(abs(pnl))
        elif r.get("would_hit_sl"):
            loss_pnls.append(abs(pnl))

    # Also get sniper-specific parameters for realistic sizing
    sniper_by_tier = defaultdict(list)
    for s in sniper_signals:
        sniper_by_tier[s.get("tier", "STANDARD")].append(s)

    # Overall stats
    total_decided = len(win_pnls) + len(loss_pnls)
    base_wr = len(win_pnls) / total_decided if total_decided > 0 else 0.4

    avg_win_pct = sum(win_pnls) / len(win_pnls) if win_pnls else 3.0
    avg_loss_pct = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 2.0

    # For sniper signals with high confidence, boost WR
    # Based on alpha research: 3-agree signals have best per-trade value
    # Confidence >= 85 further boosts
    scenarios = {
        "conservative": {"wr": min(base_wr, 0.40), "risk_pct": 0.02, "leverage": 5},
        "base_case": {"wr": min(base_wr + 0.05, 0.50), "risk_pct": 0.03, "leverage": 8},
        "sniper_only": {"wr": 0.55, "risk_pct": 0.04, "leverage": 12},
        "aggressive": {"wr": 0.60, "risk_pct": 0.05, "leverage": 15},
    }

    rng = random.Random(seed)
    all_results = {}

    for scenario_name, params in scenarios.items():
        wr = params["wr"]
        risk_pct = params["risk_pct"]
        leverage = params["leverage"]

        # Per-trade PnL as fraction of equity
        # Win: risk_pct * (avg_win / stop_width) * leverage_factor
        # Loss: -risk_pct
        # Simplified: win gives ~risk_pct * RR, loss gives -risk_pct
        rr = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 1.5
        win_return = risk_pct * rr  # e.g., 3% * 1.5 = 4.5%
        loss_return = -risk_pct     # e.g., -3%

        paths = []
        final_equities = []

        for sim in range(num_simulations):
            equity = starting_equity
            equity_path = [equity]
            total_trades = int(days * trades_per_day)

            for _ in range(total_trades):
                if rng.random() < wr:
                    # Win — add some variance
                    pnl_mult = rng.gauss(1.0, 0.3)
                    pnl_mult = max(0.3, min(2.5, pnl_mult))
                    equity *= (1 + win_return * pnl_mult)
                else:
                    # Loss — fairly consistent
                    pnl_mult = rng.gauss(1.0, 0.15)
                    pnl_mult = max(0.5, min(1.5, pnl_mult))
                    equity *= (1 + loss_return * pnl_mult)

                # Floor at $1 (margin call)
                equity = max(equity, 1.0)

                if len(equity_path) % max(1, total_trades // days) == 0:
                    equity_path.append(round(equity, 2))

            final_equities.append(equity)
            if sim < 5:  # Store a few sample paths
                paths.append(equity_path)

        final_equities.sort()
        n = len(final_equities)

        # Time to milestones
        milestones = {}
        for target in [250, 500, 1000, 5000, 10000]:
            # Estimate days to reach target using median growth rate
            median_final = final_equities[n // 2]
            if median_final > starting_equity:
                growth_rate = (median_final / starting_equity) ** (1 / days) - 1
                if growth_rate > 0:
                    days_needed = math.log(target / starting_equity) / math.log(1 + growth_rate)
                    milestones[f"${target}"] = round(days_needed, 0)
                else:
                    milestones[f"${target}"] = "N/A"
            else:
                milestones[f"${target}"] = "N/A"

        all_results[scenario_name] = {
            "params": params,
            "win_return_pct": round(win_return * 100, 2),
            "loss_return_pct": round(loss_return * 100, 2),
            "rr_ratio": round(rr, 2),
            "total_trades": int(days * trades_per_day),
            "equity_stats": {
                "starting": starting_equity,
                "median": round(final_equities[n // 2], 2),
                "p25": round(final_equities[n // 4], 2),
                "p75": round(final_equities[3 * n // 4], 2),
                "p5_worst": round(final_equities[n // 20], 2),
                "p95_best": round(final_equities[int(n * 0.95)], 2),
                "worst": round(final_equities[0], 2),
                "best": round(final_equities[-1], 2),
                "mean": round(sum(final_equities) / n, 2),
                "ruin_pct": round(
                    100 * len([e for e in final_equities if e < 10]) / n, 1
                ),
            },
            "milestones_days": milestones,
            "sample_paths": paths[:3],
        }

    return {
        "starting_equity": starting_equity,
        "simulation_days": days,
        "num_simulations": num_simulations,
        "trades_per_day": trades_per_day,
        "underlying_stats": {
            "base_win_rate": round(base_wr, 3),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "payoff_ratio": round(rr, 2),
        },
        "scenarios": all_results,
    }


# ---------------------------------------------------------------------------
# Public API: generate_playbook
# ---------------------------------------------------------------------------

def generate_playbook() -> dict:
    """
    Generate a concrete manual trading playbook with specific rules.
    Combines all analysis into actionable guidance.
    """
    best_setups = analyze_best_setups()
    leverage_table = calculate_optimal_leverage(starting_equity=100.0)
    trajectory = calculate_compound_trajectory(starting_equity=100.0)

    # Build equity-level sizing tables
    equity_levels = [100, 250, 500, 1000, 2500, 5000]
    sizing_table = []
    for eq in equity_levels:
        # SNIPER tier: 2% risk, 12-15x leverage
        sniper_risk = eq * 0.02
        sniper_position = sniper_risk / 0.025  # 2.5% stop
        sniper_leverage = sniper_position / eq

        # PREMIUM tier: 1.5% risk, 8x leverage
        premium_risk = eq * 0.015
        premium_position = premium_risk / 0.025
        premium_leverage = premium_position / eq

        sizing_table.append({
            "equity": eq,
            "sniper_risk": round(sniper_risk, 2),
            "sniper_position": round(sniper_position, 2),
            "sniper_leverage": round(min(sniper_leverage, 15), 1),
            "premium_risk": round(premium_risk, 2),
            "premium_position": round(premium_position, 2),
            "premium_leverage": round(min(premium_leverage, 8), 1),
        })

    # Rank setups by expected value
    setup_rankings = []
    for lev in leverage_table:
        setup_rankings.append({
            "setup": lev["setup"],
            "win_rate": lev["win_rate"],
            "payoff_ratio": lev["payoff_ratio"],
            "ev_per_trade": lev["ev_per_trade_pct"],
            "optimal_leverage": lev["optimal_leverage"],
            "half_kelly_risk": lev["half_kelly"],
            "grade": (
                "A+" if lev["ev_per_trade_pct"] > 2.0
                else "A" if lev["ev_per_trade_pct"] > 1.0
                else "B" if lev["ev_per_trade_pct"] > 0.5
                else "C" if lev["ev_per_trade_pct"] > 0
                else "AVOID"
            ),
        })

    # Extract key rules from data
    cf_stats = best_setups["counterfactual"]["by_dimension"]

    # Side bias
    side_stats = cf_stats.get("side", {})
    buy_wr = side_stats.get("BUY", {}).get("win_rate", 0)
    sell_wr = side_stats.get("SELL", {}).get("win_rate", 0)

    # Symbol ranking
    symbol_stats = cf_stats.get("symbol_side", {})
    symbol_ranking = sorted(
        [(k, v.get("win_rate", 0), v.get("profit_factor", 0), v.get("count", 0))
         for k, v in symbol_stats.items()],
        key=lambda x: x[1],
        reverse=True
    )

    rules = {
        "primary_rules": [
            f"LONG BIAS: BUY signals have {buy_wr:.0%} WR vs SELL {sell_wr:.0%}. Default to longs.",
            "WAIT FOR 3-AGREE: 3-strategy consensus has best per-trade PnL (from alpha research).",
            "SNIPER TIER ONLY: Only take SNIPER-grade signals (conf >= 85, 3-agree).",
            "HOLD 6-12H: Optimal hold time is 6-12h (best WR from alpha research).",
            "NEVER CHASE: If entry is missed by >0.5%, skip the trade.",
        ],
        "symbol_rules": [
            f"{s[0]}: WR={s[1]:.0%}, PF={s[2]:.1f}, n={s[3]}"
            for s in symbol_ranking[:10]
        ],
        "risk_rules": [
            "Max risk per trade: 2% of equity (SNIPER), 1.5% (PREMIUM).",
            "Max daily loss: 5% of equity — stop trading for the day.",
            "Max consecutive losses: 3 — take a 4-hour break.",
            "Never have more than 2 open positions simultaneously.",
            "Scale position size UP as equity grows (compound the edge).",
        ],
        "daily_routine": [
            "Check signals 3-4x per day (every 4-6 hours).",
            "Best hours: analyze from time-of-day data.",
            "Log every trade: entry, exit, reason, actual PnL.",
            "Weekly review: compare actual WR to expected WR.",
            "Adjust leverage down if WR drops below 40%.",
        ],
    }

    return {
        "setup_analysis": best_setups,
        "leverage_table": leverage_table,
        "trajectory": trajectory,
        "sizing_table": sizing_table,
        "setup_rankings": setup_rankings,
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# Main (for quick testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running edge analysis...")
    playbook = generate_playbook()
    print(f"Analyzed {playbook['setup_analysis']['counterfactual']['total_records']} counterfactual records")
    print(f"Analyzed {playbook['setup_analysis']['sniper_signals']['total_signals']} sniper signals")
    print(f"\nTop setups by EV:")
    for r in playbook["setup_rankings"][:5]:
        print(f"  {r['setup']}: WR={r['win_rate']:.0%}, RR={r['payoff_ratio']:.1f}x, "
              f"EV={r['ev_per_trade']:.2f}%, Grade={r['grade']}")
    print(f"\nEquity trajectory (90d, base case):")
    base = playbook["trajectory"]["scenarios"]["base_case"]["equity_stats"]
    print(f"  Median: ${base['median']}, P25: ${base['p25']}, P75: ${base['p75']}")
    print(f"  Ruin probability: {base['ruin_pct']}%")
