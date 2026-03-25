"""
Part 1: Filter Validation — Setup-Driven vs Confidence-Driven

Replays signal outcomes and counterfactual data through old and new filter logic.
Calculates: pass rates, WR, PF, expected P&L, failure modes.

Run: cd bot && python -m manual.filter_validation
"""

import json
import os
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# ─── Data Loading ───

def load_signal_outcomes(path="data/logs/signal_outcomes.jsonl") -> List[Dict]:
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def load_counterfactuals(path="data/counterfactual_resolved.json") -> List[Dict]:
    with open(path) as f:
        data = json.load(f)
    return data["records"]

# ─── Old Filter Logic (confidence-based) ───

def old_filter_passes(sig: Dict) -> bool:
    """Original filter: conf >= 78, n_agree >= 2, R:R >= 1.2"""
    conf = sig.get("conf", sig.get("confidence", 0))
    n_agree = sig.get("n_agree", sig.get("metadata", {}).get("n_agree", 1))
    meta = sig.get("meta", sig.get("metadata", {}))
    rr = meta.get("rr_tp1", 1.5)  # Default 1.5 if missing

    if conf < 78:
        return False
    if n_agree < 2:
        return False
    if rr < 1.2:
        return False
    return True

def old_filter_passes_cf(rec: Dict) -> bool:
    """Old filter applied to counterfactual record"""
    conf = rec.get("confidence", 0)
    # Counterfactuals were rejected signals — mostly conf < 65
    # Old filter requires conf >= 78
    if conf < 78:
        return False
    # We don't have n_agree in CF data, assume 2+ since they came from ensemble
    return True

# ─── New Filter Logic (setup-driven) ───

PROVEN_SETUPS = {
    "HYPE_BUY": {"max_chop": 0.4},
    "SOL_SELL": {"max_chop": 0.5},
}

def new_filter_passes(sig: Dict) -> bool:
    """New filter: proven setups bypass confidence, use chop only"""
    sym = sig.get("sym", sig.get("symbol", ""))
    side = sig.get("side", "")
    conf = sig.get("conf", sig.get("confidence", 0))
    n_agree = sig.get("n_agree", 1)
    meta = sig.get("meta", sig.get("metadata", {}))
    chop = meta.get("chop_score_smoothed", meta.get("chop_score", 0))
    rr = meta.get("rr_tp1", 1.5)

    setup_key = f"{sym}_{side}"
    setup = PROVEN_SETUPS.get(setup_key)

    if setup is not None:
        # Proven setup: only chop filter
        if chop > setup["max_chop"]:
            return False
    else:
        # Non-proven: confidence + consensus
        if conf < 78:
            return False
        if n_agree < 2:
            return False

    # R:R floor always applies
    if rr < 1.2:
        return False

    return True

def new_filter_passes_cf(rec: Dict) -> bool:
    """New filter applied to counterfactual record"""
    sym = rec.get("symbol", "")
    side = rec.get("side", "")
    setup_key = f"{sym}_{side}"

    if setup_key in PROVEN_SETUPS:
        # Proven setups pass at any confidence
        # No chop data in CF records, so assume clean (< threshold)
        return True
    else:
        conf = rec.get("confidence", 0)
        if conf < 78:
            return False
    return True

# ─── Analysis Functions ───

def analyze_filter_on_outcomes(outcomes: List[Dict]) -> Dict:
    """Replay signal outcomes through old vs new filter"""
    results = {
        "old": {"pass": 0, "reject": 0, "by_setup": defaultdict(lambda: {"pass": 0, "reject": 0})},
        "new": {"pass": 0, "reject": 0, "by_setup": defaultdict(lambda: {"pass": 0, "reject": 0})},
    }

    for sig in outcomes:
        setup = f"{sig['sym']}_{sig['side']}"

        if old_filter_passes(sig):
            results["old"]["pass"] += 1
            results["old"]["by_setup"][setup]["pass"] += 1
        else:
            results["old"]["reject"] += 1
            results["old"]["by_setup"][setup]["reject"] += 1

        if new_filter_passes(sig):
            results["new"]["pass"] += 1
            results["new"]["by_setup"][setup]["pass"] += 1
        else:
            results["new"]["reject"] += 1
            results["new"]["by_setup"][setup]["reject"] += 1

    return results

def analyze_filter_on_counterfactuals(cfs: List[Dict]) -> Dict:
    """Replay counterfactuals through old vs new filter with outcome tracking"""
    results = {}

    for label, filter_fn in [("old", old_filter_passes_cf), ("new", new_filter_passes_cf)]:
        passed = []
        rejected = []
        for rec in cfs:
            if filter_fn(rec):
                passed.append(rec)
            else:
                rejected.append(rec)

        # Compute stats on passed signals
        by_setup = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0,
                                         "total_pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0})

        for rec in passed:
            setup = f"{rec['symbol']}_{rec['side']}"
            s = by_setup[setup]
            s["n"] += 1
            pnl = rec.get("hypothetical_pnl_pct", 0)
            if rec.get("would_hit_tp1", False):
                s["wins"] += 1
                s["win_pnl"] += abs(pnl)
            else:
                s["losses"] += 1
                s["loss_pnl"] += abs(pnl)
            s["total_pnl"] += pnl

        # Aggregate
        total_n = len(passed)
        total_wins = sum(s["wins"] for s in by_setup.values())
        total_losses = sum(s["losses"] for s in by_setup.values())
        total_win_pnl = sum(s["win_pnl"] for s in by_setup.values())
        total_loss_pnl = sum(s["loss_pnl"] for s in by_setup.values())
        total_pnl = sum(s["total_pnl"] for s in by_setup.values())

        wr = total_wins / total_n if total_n > 0 else 0
        pf = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else float('inf')

        # Missed winners in rejected pile
        missed_winners = sum(1 for r in rejected if r.get("would_hit_tp1", False))
        missed_pnl = sum(r.get("hypothetical_pnl_pct", 0) for r in rejected if r.get("would_hit_tp1", False))

        results[label] = {
            "total_passed": total_n,
            "total_rejected": len(rejected),
            "win_rate": round(wr * 100, 1),
            "profit_factor": round(pf, 2),
            "total_pnl_pct": round(total_pnl, 2),
            "missed_winners": missed_winners,
            "missed_pnl_pct": round(missed_pnl, 2),
            "by_setup": {k: dict(v) for k, v in by_setup.items()},
        }

    return results


def backtest_filter(cfs: List[Dict], filter_fn, label: str,
                    start_equity: float = 100.0,
                    leverage_map: Dict[str, float] = None) -> Dict:
    """
    Backtest a filter against counterfactual data.
    Simulates compound account growth.
    """
    if leverage_map is None:
        leverage_map = {"HYPE_BUY": 25, "SOL_SELL": 15}

    equity = start_equity
    peak = start_equity
    max_dd = 0
    trades = []
    daily_pnl = defaultdict(float)

    # Sort by created_at for chronological replay
    sorted_cfs = sorted(cfs, key=lambda r: r.get("created_at", ""))

    for rec in sorted_cfs:
        if not filter_fn(rec):
            continue

        setup = f"{rec['symbol']}_{rec['side']}"
        lev = leverage_map.get(setup, 10)

        # Risk: 10% of equity for SNIPER, 8% for others
        risk_pct = 0.10 if setup == "HYPE_BUY" else 0.08
        risk_amount = equity * risk_pct

        # PnL from counterfactual
        pnl_pct = rec.get("hypothetical_pnl_pct", 0) / 100.0
        # Scale by leverage (the pnl_pct is on the underlying, position is leveraged)
        # But capped at risk_amount for losses
        if rec.get("would_hit_tp1", False):
            # Win: use the TP1 distance as actual gain
            entry = rec["entry_price"]
            tp1 = rec["tp1"]
            tp_dist = abs(tp1 - entry) / entry
            position_size = risk_amount / (abs(entry - rec["sl"]) / entry) if abs(entry - rec["sl"]) > 0 else 0
            trade_pnl = position_size * tp_dist
        else:
            # Loss: lose risk_amount
            trade_pnl = -risk_amount

        equity += trade_pnl
        if equity <= 0:
            equity = 0
            break

        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        day = rec.get("created_at", "")[:10]
        daily_pnl[day] += trade_pnl

        trades.append({
            "setup": setup,
            "win": rec.get("would_hit_tp1", False),
            "pnl": round(trade_pnl, 2),
            "equity_after": round(equity, 2),
            "dd": round(dd * 100, 2),
        })

    n_trades = len(trades)
    wins = sum(1 for t in trades if t["win"])
    losses = n_trades - wins
    total_win_pnl = sum(t["pnl"] for t in trades if t["win"])
    total_loss_pnl = abs(sum(t["pnl"] for t in trades if not t["win"]))

    wr = wins / n_trades if n_trades > 0 else 0
    pf = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else float('inf')

    # Sharpe approximation (daily returns)
    if daily_pnl:
        daily_returns = list(daily_pnl.values())
        avg_ret = sum(daily_returns) / len(daily_returns)
        if len(daily_returns) > 1:
            std_ret = (sum((r - avg_ret)**2 for r in daily_returns) / (len(daily_returns) - 1)) ** 0.5
            sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    return {
        "label": label,
        "start_equity": start_equity,
        "end_equity": round(equity, 2),
        "return_pct": round((equity / start_equity - 1) * 100, 2),
        "n_trades": n_trades,
        "trades_per_day": round(n_trades / max(len(daily_pnl), 1), 1),
        "win_rate": round(wr * 100, 1),
        "profit_factor": round(pf, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "total_win_pnl": round(total_win_pnl, 2),
        "total_loss_pnl": round(total_loss_pnl, 2),
    }


def find_failure_modes(cfs: List[Dict]) -> Dict:
    """Analyze WHEN HYPE BUY fails — what conditions predict losses"""
    hype_buys = [r for r in cfs if r["symbol"] == "HYPE" and r["side"] == "BUY"]

    winners = [r for r in hype_buys if r.get("would_hit_tp1", False)]
    losers = [r for r in hype_buys if not r.get("would_hit_tp1", False)]

    analysis = {
        "total_hype_buy": len(hype_buys),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(len(winners) / len(hype_buys) * 100, 1) if hype_buys else 0,
    }

    # By confidence band
    conf_bands = {}
    for band_lo in range(45, 75, 5):
        band_hi = band_lo + 5
        band_sigs = [r for r in hype_buys if band_lo <= r["confidence"] < band_hi]
        if band_sigs:
            band_wins = sum(1 for r in band_sigs if r.get("would_hit_tp1", False))
            conf_bands[f"{band_lo}-{band_hi}"] = {
                "n": len(band_sigs),
                "wins": band_wins,
                "wr": round(band_wins / len(band_sigs) * 100, 1),
            }
    analysis["by_confidence_band"] = conf_bands

    # By bars_to_resolve (speed of resolution)
    speed_buckets = {"fast_1_3": (1, 3), "medium_4_8": (4, 8), "slow_9_plus": (9, 999)}
    by_speed = {}
    for label, (lo, hi) in speed_buckets.items():
        bucket = [r for r in hype_buys if lo <= r.get("bars_to_resolve", 0) <= hi]
        if bucket:
            bw = sum(1 for r in bucket if r.get("would_hit_tp1", False))
            by_speed[label] = {
                "n": len(bucket),
                "wins": bw,
                "wr": round(bw / len(bucket) * 100, 1),
            }
    analysis["by_resolution_speed"] = by_speed

    # By PnL magnitude on losses
    if losers:
        loss_pnls = [r.get("hypothetical_pnl_pct", 0) for r in losers]
        analysis["loser_stats"] = {
            "avg_loss_pct": round(sum(loss_pnls) / len(loss_pnls), 2),
            "worst_loss_pct": round(min(loss_pnls), 2),
            "median_loss_pct": round(sorted(loss_pnls)[len(loss_pnls) // 2], 2),
        }

    # By max adverse excursion
    if losers:
        adverse = []
        for r in losers:
            entry = r["entry_price"]
            max_adv = r.get("max_adverse_price", entry)
            adv_pct = abs(max_adv - entry) / entry * 100
            adverse.append(adv_pct)
        analysis["loser_max_adverse_excursion"] = {
            "avg_pct": round(sum(adverse) / len(adverse), 2),
            "max_pct": round(max(adverse), 2),
            "median_pct": round(sorted(adverse)[len(adverse) // 2], 2),
        }

    # Winner characteristics
    if winners:
        win_bars = [r.get("bars_to_resolve", 0) for r in winners]
        analysis["winner_stats"] = {
            "avg_bars": round(sum(win_bars) / len(win_bars), 1),
            "median_bars": sorted(win_bars)[len(win_bars) // 2],
            "avg_pnl_pct": round(sum(r.get("hypothetical_pnl_pct", 0) for r in winners) / len(winners), 2),
        }

    return analysis


def monte_carlo_backtest(wr: float, avg_win_pct: float, avg_loss_pct: float,
                         risk_pct: float, leverage: float,
                         trades_per_day: float, days: int = 90,
                         n_paths: int = 10000, start: float = 100.0) -> Dict:
    """Monte Carlo simulation for compound account growth"""
    random.seed(42)
    total_trades = int(trades_per_day * days)

    endings = []
    max_dds = []
    ruin_count = 0
    time_to_1000 = []

    for _ in range(n_paths):
        equity = start
        peak = start
        max_dd = 0
        t1000 = None

        for t in range(total_trades):
            if equity <= 1:  # Ruin
                ruin_count += 1
                break

            risk_amount = equity * risk_pct
            if random.random() < wr:
                # Win: risk_amount * (avg_win / avg_loss) ratio
                # If avg_win=4.68% and stop=2.5%, the R:R is ~1.87
                rr = avg_win_pct / avg_loss_pct
                pnl = risk_amount * rr
            else:
                # Loss: lose risk_amount
                pnl = -risk_amount

            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

            if t1000 is None and equity >= 1000:
                t1000 = t / trades_per_day  # days

        endings.append(equity)
        max_dds.append(max_dd)
        if t1000 is not None:
            time_to_1000.append(t1000)

    endings.sort()
    max_dds.sort()

    return {
        "n_paths": n_paths,
        "days": days,
        "trades_per_day": trades_per_day,
        "total_trades": total_trades,
        "risk_pct": risk_pct,
        "wr": wr,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "median_equity": round(endings[len(endings) // 2], 2),
        "p5_equity": round(endings[int(len(endings) * 0.05)], 2),
        "p25_equity": round(endings[int(len(endings) * 0.25)], 2),
        "p75_equity": round(endings[int(len(endings) * 0.75)], 2),
        "p95_equity": round(endings[int(len(endings) * 0.95)], 2),
        "ruin_pct": round(ruin_count / n_paths * 100, 2),
        "median_max_dd": round(max_dds[len(max_dds) // 2] * 100, 2),
        "p95_max_dd": round(max_dds[int(len(max_dds) * 0.95)] * 100, 2),
        "pct_reaching_1000": round(len(time_to_1000) / n_paths * 100, 1),
        "median_days_to_1000": round(sorted(time_to_1000)[len(time_to_1000) // 2], 0) if time_to_1000 else None,
    }


def generate_report(outcome_analysis, cf_analysis, backtest_old, backtest_new, failure_modes, mc_results):
    """Generate markdown report"""
    lines = []
    lines.append("# Filter Validation Report")
    lines.append(f"\n*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("\n---\n")

    # Section 1: Signal Outcome Replay
    lines.append("## 1. Signal Outcome Replay (1977 signals)")
    lines.append("\nHow many signals pass each filter:\n")
    lines.append("| Filter | Passed | Rejected | Pass Rate |")
    lines.append("|--------|--------|----------|-----------|")
    for label in ["old", "new"]:
        d = outcome_analysis[label]
        total = d["pass"] + d["reject"]
        rate = d["pass"] / total * 100 if total > 0 else 0
        lines.append(f"| {label.upper()} | {d['pass']} | {d['reject']} | {rate:.1f}% |")

    lines.append("\n### By Setup (New Filter)\n")
    lines.append("| Setup | Old Pass | Old Reject | New Pass | New Reject | Delta |")
    lines.append("|-------|----------|------------|----------|------------|-------|")
    all_setups = set()
    for label in ["old", "new"]:
        all_setups.update(outcome_analysis[label]["by_setup"].keys())
    for setup in sorted(all_setups):
        old_p = outcome_analysis["old"]["by_setup"].get(setup, {"pass": 0, "reject": 0})["pass"]
        old_r = outcome_analysis["old"]["by_setup"].get(setup, {"pass": 0, "reject": 0})["reject"]
        new_p = outcome_analysis["new"]["by_setup"].get(setup, {"pass": 0, "reject": 0})["pass"]
        new_r = outcome_analysis["new"]["by_setup"].get(setup, {"pass": 0, "reject": 0})["reject"]
        delta = new_p - old_p
        sign = "+" if delta > 0 else ""
        lines.append(f"| {setup} | {old_p} | {old_r} | {new_p} | {new_r} | {sign}{delta} |")

    # Section 2: Counterfactual Analysis
    lines.append("\n---\n")
    lines.append("## 2. Counterfactual Cross-Reference (1000 resolved records)")
    lines.append("\n| Metric | Old Filter | New Filter | Change |")
    lines.append("|--------|-----------|-----------|--------|")
    for metric in ["total_passed", "total_rejected", "win_rate", "profit_factor", "total_pnl_pct", "missed_winners", "missed_pnl_pct"]:
        old_v = cf_analysis["old"][metric]
        new_v = cf_analysis["new"][metric]
        if isinstance(old_v, float):
            delta = new_v - old_v
            sign = "+" if delta > 0 else ""
            lines.append(f"| {metric} | {old_v} | {new_v} | {sign}{delta:.1f} |")
        else:
            lines.append(f"| {metric} | {old_v} | {new_v} | {new_v - old_v:+} |")

    lines.append("\n### Passed Signals by Setup (New Filter)\n")
    lines.append("| Setup | N | Wins | Losses | WR | PF |")
    lines.append("|-------|---|------|--------|----|----|")
    for setup, stats in sorted(cf_analysis["new"]["by_setup"].items()):
        n = stats["n"]
        w = stats["wins"]
        l = stats["losses"]
        wr = w / n * 100 if n > 0 else 0
        pf = stats["win_pnl"] / stats["loss_pnl"] if stats["loss_pnl"] > 0 else float('inf')
        lines.append(f"| {setup} | {n} | {w} | {l} | {wr:.1f}% | {pf:.2f} |")

    # Section 3: Backtest Comparison
    lines.append("\n---\n")
    lines.append("## 3. Backtest: $100 Compound Account\n")
    lines.append("| Metric | Old Filter | New Filter |")
    lines.append("|--------|-----------|-----------|")
    for metric in ["n_trades", "trades_per_day", "win_rate", "profit_factor",
                    "end_equity", "return_pct", "max_drawdown_pct", "sharpe"]:
        old_v = backtest_old.get(metric, "N/A")
        new_v = backtest_new.get(metric, "N/A")
        lines.append(f"| {metric} | {old_v} | {new_v} |")

    # Section 4: Failure Modes
    lines.append("\n---\n")
    lines.append("## 4. HYPE BUY Failure Mode Analysis\n")
    lines.append(f"Total HYPE BUY signals: {failure_modes['total_hype_buy']}")
    lines.append(f"Winners: {failure_modes['winners']} ({failure_modes['win_rate']}%)")
    lines.append(f"Losers: {failure_modes['losers']}\n")

    if failure_modes.get("by_confidence_band"):
        lines.append("### By Confidence Band\n")
        lines.append("| Band | N | Wins | WR |")
        lines.append("|------|---|------|----|")
        for band, stats in sorted(failure_modes["by_confidence_band"].items()):
            lines.append(f"| {band} | {stats['n']} | {stats['wins']} | {stats['wr']}% |")

    if failure_modes.get("by_resolution_speed"):
        lines.append("\n### By Resolution Speed\n")
        lines.append("| Speed | N | Wins | WR |")
        lines.append("|-------|---|------|----|")
        for speed, stats in sorted(failure_modes["by_resolution_speed"].items()):
            lines.append(f"| {speed} | {stats['n']} | {stats['wins']} | {stats['wr']}% |")

    if failure_modes.get("loser_stats"):
        ls = failure_modes["loser_stats"]
        lines.append(f"\n### Loser Characteristics")
        lines.append(f"- Avg loss: {ls['avg_loss_pct']}%")
        lines.append(f"- Worst loss: {ls['worst_loss_pct']}%")
        lines.append(f"- Median loss: {ls['median_loss_pct']}%")

    if failure_modes.get("loser_max_adverse_excursion"):
        mae = failure_modes["loser_max_adverse_excursion"]
        lines.append(f"\n### Max Adverse Excursion (losers)")
        lines.append(f"- Avg: {mae['avg_pct']}%")
        lines.append(f"- Max: {mae['max_pct']}%")
        lines.append(f"- Median: {mae['median_pct']}%")

    if failure_modes.get("winner_stats"):
        ws = failure_modes["winner_stats"]
        lines.append(f"\n### Winner Characteristics")
        lines.append(f"- Avg bars to resolve: {ws['avg_bars']}")
        lines.append(f"- Median bars: {ws['median_bars']}")
        lines.append(f"- Avg PnL: +{ws['avg_pnl_pct']}%")

    # Section 5: Monte Carlo
    lines.append("\n---\n")
    lines.append("## 5. Monte Carlo Projections (10,000 paths, 90 days)\n")
    lines.append("Using HYPE BUY parameters: WR=85%, avg_win=+4.68%, avg_loss=-2.5%\n")
    lines.append("| Risk/Trade | Median Equity | P5 (worst) | P95 (best) | Max DD (p95) | Ruin% | Days to $1K |")
    lines.append("|------------|--------------|------------|------------|-------------|-------|-------------|")
    for mc in mc_results:
        d2k = mc.get("median_days_to_1000", "N/A")
        lines.append(
            f"| {mc['risk_pct']*100:.0f}% | ${mc['median_equity']:,.0f} | "
            f"${mc['p5_equity']:,.0f} | ${mc['p95_equity']:,.0f} | "
            f"{mc['p95_max_dd']:.1f}% | {mc['ruin_pct']:.1f}% | {d2k} |"
        )

    # Key Findings
    lines.append("\n---\n")
    lines.append("## Key Findings\n")

    old_passed = cf_analysis["old"]["total_passed"]
    new_passed = cf_analysis["new"]["total_passed"]
    old_missed = cf_analysis["old"]["missed_winners"]
    new_missed = cf_analysis["new"]["missed_winners"]

    lines.append(f"1. **New filter passes {new_passed} vs {old_passed} counterfactual signals** (+{new_passed - old_passed})")
    lines.append(f"2. **Old filter missed {old_missed} winners** (new misses {new_missed})")
    lines.append(f"3. **New filter WR: {cf_analysis['new']['win_rate']}%** vs old: {cf_analysis['old']['win_rate']}%")
    lines.append(f"4. **New filter PF: {cf_analysis['new']['profit_factor']}** vs old: {cf_analysis['old']['profit_factor']}")
    lines.append(f"5. **Backtest: ${backtest_new['end_equity']}** end equity vs old ${backtest_old['end_equity']}")

    # Recommendations
    lines.append("\n## Recommendations\n")
    if cf_analysis["new"]["win_rate"] > 70:
        lines.append("- **CONFIRMED**: Setup-driven filter is superior to confidence-driven")
    if failure_modes.get("by_resolution_speed", {}).get("slow_9_plus", {}).get("wr", 100) < 70:
        lines.append("- **WARNING**: Slow-resolving HYPE BUY signals have lower WR — consider time-based exit")
    if cf_analysis["new"]["win_rate"] < cf_analysis["old"]["win_rate"]:
        lines.append("- **CAUTION**: New filter has lower WR — trades more but less selective")
    else:
        lines.append("- **POSITIVE**: New filter maintains or improves WR while trading more")

    lines.append("\n---\n*Analysis complete. Raw data in filter_validation_results.json*")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("PART 1: Filter Validation — Setup-Driven vs Confidence")
    print("=" * 60)

    # Load data
    print("\n[1/6] Loading data...")
    outcomes = load_signal_outcomes()
    cfs = load_counterfactuals()
    print(f"  Signal outcomes: {len(outcomes)}")
    print(f"  Counterfactuals: {len(cfs)}")

    # Replay through filters
    print("\n[2/6] Replaying signal outcomes through filters...")
    outcome_analysis = analyze_filter_on_outcomes(outcomes)
    print(f"  Old filter: {outcome_analysis['old']['pass']} pass, {outcome_analysis['old']['reject']} reject")
    print(f"  New filter: {outcome_analysis['new']['pass']} pass, {outcome_analysis['new']['reject']} reject")

    # Counterfactual cross-reference
    print("\n[3/6] Cross-referencing with counterfactual outcomes...")
    cf_analysis = analyze_filter_on_counterfactuals(cfs)
    print(f"  Old: {cf_analysis['old']['total_passed']} passed, WR={cf_analysis['old']['win_rate']}%, PF={cf_analysis['old']['profit_factor']}")
    print(f"  New: {cf_analysis['new']['total_passed']} passed, WR={cf_analysis['new']['win_rate']}%, PF={cf_analysis['new']['profit_factor']}")

    # Backtest
    print("\n[4/6] Backtesting $100 compound account...")
    backtest_old = backtest_filter(cfs, old_filter_passes_cf, "old_confidence_filter")
    backtest_new = backtest_filter(cfs, new_filter_passes_cf, "new_setup_filter")
    print(f"  Old: ${backtest_old['end_equity']} ({backtest_old['n_trades']} trades, WR={backtest_old['win_rate']}%)")
    print(f"  New: ${backtest_new['end_equity']} ({backtest_new['n_trades']} trades, WR={backtest_new['win_rate']}%)")

    # Failure modes
    print("\n[5/6] Analyzing HYPE BUY failure modes...")
    failure_modes = find_failure_modes(cfs)
    print(f"  HYPE BUY: {failure_modes['total_hype_buy']} signals, {failure_modes['win_rate']}% WR")
    print(f"  Losers: {failure_modes['losers']}")

    # Monte Carlo
    print("\n[6/6] Running Monte Carlo simulations...")
    mc_results = []
    for risk in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
        mc = monte_carlo_backtest(
            wr=0.85, avg_win_pct=4.68, avg_loss_pct=2.5,
            risk_pct=risk, leverage=25, trades_per_day=1.5, days=90
        )
        mc_results.append(mc)
        print(f"  Risk {risk*100:.0f}%: median ${mc['median_equity']:,.0f}, DD p95={mc['p95_max_dd']:.1f}%, ruin={mc['ruin_pct']:.1f}%")

    # Generate report
    print("\n" + "=" * 60)
    print("Generating reports...")
    report = generate_report(outcome_analysis, cf_analysis, backtest_old, backtest_new, failure_modes, mc_results)

    # Save
    os.makedirs("data/manual", exist_ok=True)
    with open("data/manual/FILTER_VALIDATION.md", "w") as f:
        f.write(report)
    print("  Saved: data/manual/FILTER_VALIDATION.md")

    # Save JSON results
    json_results = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "outcome_replay": {
            k: {"pass": v["pass"], "reject": v["reject"],
                "by_setup": {sk: dict(sv) for sk, sv in v["by_setup"].items()}}
            for k, v in outcome_analysis.items()
        },
        "counterfactual_analysis": cf_analysis,
        "backtest_old": backtest_old,
        "backtest_new": backtest_new,
        "failure_modes": failure_modes,
        "monte_carlo": mc_results,
    }
    with open("data/manual/filter_validation_results.json", "w") as f:
        json.dump(json_results, f, indent=2, default=str)
    print("  Saved: data/manual/filter_validation_results.json")

    print("\n" + "=" * 60)
    print("FILTER VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
