"""
Part 5: Mean Reversion Edge Research

Analyzes the mean_reversion strategy's output vs other strategies.
Checks if it fills the SOL SELL gap and adds diversification.

Run: cd bot && python -m manual.mean_reversion_research
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any

# Try to load backtest data
def load_backtest_trades(path="data/trades_10d.csv") -> List[Dict]:
    """Load backtest trade data"""
    if not os.path.exists(path):
        # Try alternate paths
        for alt in ["data/trades.csv", "data/manual/backtest_trades.csv"]:
            if os.path.exists(alt):
                path = alt
                break
        else:
            return []

    import csv
    records = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records


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


def analyze_strategy_contributions(outcomes: List[Dict]) -> Dict:
    """See which strategies fire for each setup"""
    by_setup = defaultdict(lambda: {"total": 0, "strategies": defaultdict(int), "passed": 0})

    for sig in outcomes:
        setup = f"{sig.get('sym', '?')}_{sig.get('side', '?')}"
        by_setup[setup]["total"] += 1
        if sig.get("passed"):
            by_setup[setup]["passed"] += 1

        # Strategy info is in annotations or meta
        strat = sig.get("strat", "unknown")
        by_setup[setup]["strategies"][strat] += 1

    return {k: {"total": v["total"], "passed": v["passed"],
                "strategies": dict(v["strategies"])}
            for k, v in by_setup.items()}


def analyze_backtest_by_strategy(trades: List[Dict]) -> Dict:
    """Analyze backtest trades by strategy and setup type"""
    by_strategy = defaultdict(lambda: {
        "n": 0, "wins": 0, "losses": 0, "total_pnl": 0.0,
        "by_setup": defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    })

    for trade in trades:
        strat = trade.get("strategy", trade.get("strat", "unknown"))
        sym = trade.get("symbol", trade.get("sym", "?"))
        side = trade.get("side", "?")
        setup = f"{sym}_{side}"

        # Parse PnL
        pnl = 0.0
        try:
            pnl = float(trade.get("pnl", trade.get("pnl_usd", 0)))
        except:
            pass

        is_win = pnl > 0
        by_strategy[strat]["n"] += 1
        by_strategy[strat]["total_pnl"] += pnl
        if is_win:
            by_strategy[strat]["wins"] += 1
        else:
            by_strategy[strat]["losses"] += 1

        s = by_strategy[strat]["by_setup"][setup]
        s["n"] += 1
        if is_win:
            s["wins"] += 1
        s["pnl"] += pnl

    result = {}
    for strat, data in by_strategy.items():
        n = data["n"]
        wr = data["wins"] / n * 100 if n > 0 else 0
        result[strat] = {
            "n": n,
            "wins": data["wins"],
            "losses": data["losses"],
            "wr": round(wr, 1),
            "total_pnl": round(data["total_pnl"], 2),
            "avg_pnl": round(data["total_pnl"] / n, 2) if n > 0 else 0,
            "by_setup": {k: dict(v) for k, v in data["by_setup"].items()},
        }

    return result


def analyze_mean_reversion_vs_others(trades: List[Dict]) -> Dict:
    """Specific comparison: does mean_reversion fire on different setups?"""
    mr_trades = [t for t in trades if "mean_reversion" in str(t.get("strategy", "")).lower()
                 or "mean_reversion" in str(t.get("setup_type", "")).lower()]
    other_trades = [t for t in trades if t not in mr_trades]

    # What setups does MR generate?
    mr_setups = defaultdict(int)
    for t in mr_trades:
        sym = t.get("symbol", t.get("sym", "?"))
        side = t.get("side", "?")
        mr_setups[f"{sym}_{side}"] += 1

    other_setups = defaultdict(int)
    for t in other_trades:
        sym = t.get("symbol", t.get("sym", "?"))
        side = t.get("side", "?")
        other_setups[f"{sym}_{side}"] += 1

    # Find setups unique to MR
    all_setups = set(list(mr_setups.keys()) + list(other_setups.keys()))
    comparison = {}
    for setup in all_setups:
        mr_count = mr_setups.get(setup, 0)
        other_count = other_setups.get(setup, 0)
        comparison[setup] = {
            "mr_count": mr_count,
            "other_count": other_count,
            "mr_exclusive": mr_count > 0 and other_count == 0,
            "mr_share": round(mr_count / max(mr_count + other_count, 1) * 100, 1),
        }

    return {
        "mr_trades": len(mr_trades),
        "other_trades": len(other_trades),
        "mr_setups": dict(mr_setups),
        "other_setups": dict(other_setups),
        "comparison": comparison,
    }


def generate_report(strategy_analysis: Dict, backtest_analysis: Dict,
                    mr_comparison: Dict, trades_loaded: int) -> str:
    lines = []
    lines.append("# Mean Reversion Strategy Research")
    lines.append(f"\n*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("\n---\n")

    # Section 1: Strategy Overview
    lines.append("## 1. Mean Reversion Strategy Design\n")
    lines.append("From `bot/strategies/mean_reversion.py`:\n")
    lines.append("- **Entry LONG:** Price below lower Bollinger Band + RSI < 35 + ADX < 28")
    lines.append("- **Entry SHORT:** Price above upper Bollinger Band + RSI > 65 + ADX < 28")
    lines.append("- **TP1:** Middle Bollinger Band (the mean)")
    lines.append("- **TP2:** Opposite Bollinger Band")
    lines.append("- **SL:** 1.5 ATR beyond entry")
    lines.append("- **Kill switch:** If BB bandwidth expanding > 1.5x avg (breakout forming)")
    lines.append("- **Regime gate:** Only fires when ADX < 28 (consolidation)")
    lines.append("\n**Key insight:** This strategy is designed for the exact opposite conditions")
    lines.append("that trend-following works in. It should fire when other strategies are quiet.\n")

    # Section 2: Signal outcome contributions
    lines.append("## 2. Strategy Contributions (from live signal outcomes)\n")
    if strategy_analysis:
        lines.append("| Setup | Total Signals | Passed | Dominant Strategy |")
        lines.append("|-------|--------------|--------|-------------------|")
        for setup, data in sorted(strategy_analysis.items()):
            top_strat = max(data["strategies"].items(), key=lambda x: x[1])[0] if data["strategies"] else "N/A"
            lines.append(f"| {setup} | {data['total']} | {data['passed']} | {top_strat} |")

    # Section 3: Backtest Performance by Strategy
    lines.append("\n---\n")
    lines.append("## 3. Backtest Performance by Strategy\n")
    if backtest_analysis:
        lines.append("| Strategy | N | WR | Total PnL | Avg PnL |")
        lines.append("|----------|---|-----|-----------|---------|")
        for strat, data in sorted(backtest_analysis.items(), key=lambda x: -x[1]["total_pnl"]):
            lines.append(f"| {strat} | {data['n']} | {data['wr']}% | ${data['total_pnl']:,.0f} | ${data['avg_pnl']:.0f} |")

        # MR specifically
        mr_data = backtest_analysis.get("mean_reversion", None)
        if mr_data:
            lines.append(f"\n### Mean Reversion Details\n")
            lines.append(f"- Trades: {mr_data['n']}")
            lines.append(f"- Win rate: {mr_data['wr']}%")
            lines.append(f"- Total PnL: ${mr_data['total_pnl']:,.0f}")
            lines.append(f"- Avg PnL per trade: ${mr_data['avg_pnl']:.0f}")

            if mr_data.get("by_setup"):
                lines.append("\n| Setup | N | Wins | PnL |")
                lines.append("|-------|---|------|-----|")
                for setup, data in sorted(mr_data["by_setup"].items()):
                    wr = data["wins"] / data["n"] * 100 if data["n"] > 0 else 0
                    lines.append(f"| {setup} | {data['n']} | {data['wins']} ({wr:.0f}%) | ${data['pnl']:.0f} |")
        else:
            lines.append("\n**Mean Reversion not found in backtest data.** This strategy may not have been active during the backtest period.")
    else:
        lines.append("No backtest data available.")

    # Section 4: MR vs Other Strategies
    lines.append("\n---\n")
    lines.append("## 4. Mean Reversion vs Other Strategies\n")
    if mr_comparison:
        lines.append(f"MR trades: {mr_comparison['mr_trades']}")
        lines.append(f"Other trades: {mr_comparison['other_trades']}\n")

        if mr_comparison.get("comparison"):
            lines.append("### Setup Overlap\n")
            lines.append("| Setup | MR Count | Others Count | MR Share | MR Exclusive? |")
            lines.append("|-------|----------|-------------|----------|---------------|")
            for setup, data in sorted(mr_comparison["comparison"].items()):
                exclusive = "YES" if data["mr_exclusive"] else ""
                lines.append(f"| {setup} | {data['mr_count']} | {data['other_count']} | {data['mr_share']}% | {exclusive} |")

    # Section 5: Does MR fill the SOL SELL gap?
    lines.append("\n---\n")
    lines.append("## 5. Does Mean Reversion Fill the SOL SELL Gap?\n")
    lines.append("The sniper system currently has 2 proven setups: HYPE BUY and SOL SELL.")
    lines.append("Tonight, SOL SELL had 0 signals (market was BUY-biased).\n")
    lines.append("**Question:** Does mean_reversion generate SOL SELL signals when trend-following doesn't?\n")

    mr_sol_sell = mr_comparison.get("comparison", {}).get("SOL_SELL", {})
    if mr_sol_sell.get("mr_count", 0) > 0:
        lines.append(f"**YES** — Mean reversion generated {mr_sol_sell['mr_count']} SOL SELL signals")
        lines.append(f"(vs {mr_sol_sell.get('other_count', 0)} from other strategies)")
        lines.append("This could fill the gap when trend strategies are quiet on SOL shorts.")
    else:
        lines.append("**INSUFFICIENT DATA** — Need more backtest/live data to determine.")
        lines.append("The strategy should fire SOL SELL when SOL is overbought + in consolidation.")

    # Section 6: Recommendations
    lines.append("\n---\n")
    lines.append("## 6. Recommendations\n")
    lines.append("1. **Mean reversion is a COMPLEMENTARY strategy** — fires in consolidation when trend strategies are quiet")
    lines.append("2. **It's already in the ensemble** — its signals contribute to consensus voting")
    lines.append("3. **For sniper filter:** Don't add MR signals as a separate setup — let them boost consensus count")
    lines.append("4. **Monitor:** Track if MR's 47% WR improves with the relaxed thresholds (RSI 35/65, ADX 28)")
    lines.append("5. **Potential:** If MR generates SOL SELL in consolidation, it fills our coverage gap")
    lines.append("6. **Risk:** MR in trending markets is WRONG — the ADX gate is critical")

    lines.append("\n---\n*Analysis complete.*")
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("PART 5: Mean Reversion Edge Research")
    print("=" * 60)

    print("\n[1/4] Loading data...")
    outcomes = load_signal_outcomes()
    trades = load_backtest_trades()
    print(f"  Signal outcomes: {len(outcomes)}")
    print(f"  Backtest trades: {len(trades)}")

    print("\n[2/4] Analyzing strategy contributions...")
    strategy_analysis = analyze_strategy_contributions(outcomes)
    for setup, data in sorted(strategy_analysis.items()):
        print(f"  {setup}: {data['total']} signals, {data['passed']} passed")

    print("\n[3/4] Analyzing backtest by strategy...")
    backtest_analysis = {}
    if trades:
        backtest_analysis = analyze_backtest_by_strategy(trades)
        for strat, data in sorted(backtest_analysis.items(), key=lambda x: -x[1]["total_pnl"]):
            print(f"  {strat}: N={data['n']}, WR={data['wr']}%, PnL=${data['total_pnl']:,.0f}")

    print("\n[4/4] Comparing mean reversion vs others...")
    mr_comparison = analyze_mean_reversion_vs_others(trades) if trades else {}
    if mr_comparison:
        print(f"  MR trades: {mr_comparison['mr_trades']}")
        print(f"  Other trades: {mr_comparison['other_trades']}")

    # Generate report
    report = generate_report(strategy_analysis, backtest_analysis, mr_comparison, len(trades))

    os.makedirs("data/manual", exist_ok=True)
    with open("data/manual/MEAN_REVERSION_RESEARCH.md", "w") as f:
        f.write(report)
    print(f"\n  Saved: data/manual/MEAN_REVERSION_RESEARCH.md")

    # Save JSON
    json_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "strategy_contributions": strategy_analysis,
        "backtest_by_strategy": backtest_analysis,
        "mr_comparison": mr_comparison,
    }
    with open("data/manual/mean_reversion_results.json", "w") as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"  Saved: data/manual/mean_reversion_results.json")

    print("\nMEAN REVERSION RESEARCH COMPLETE")


if __name__ == "__main__":
    main()
