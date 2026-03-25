"""
Generate a complete trading playbook from edge analysis.

Run: cd bot && python -m manual.generate_playbook
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from manual.edge_analysis import (
    analyze_best_setups,
    calculate_optimal_leverage,
    calculate_compound_trajectory,
    generate_playbook,
)

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "manual"


def _fmt_pct(val: float, decimals: int = 1) -> str:
    return f"{val * 100:.{decimals}f}%" if val < 1 else f"{val:.{decimals}f}%"


def _fmt_money(val: float) -> str:
    return f"${val:,.2f}"


def _table_row(cells: list, widths: list) -> str:
    parts = []
    for cell, w in zip(cells, widths):
        parts.append(str(cell).ljust(w))
    return "| " + " | ".join(parts) + " |"


def _table_sep(widths: list) -> str:
    return "|" + "|".join("-" * (w + 2) for w in widths) + "|"


def render_markdown(playbook: dict) -> str:
    """Render the full playbook as markdown."""
    lines = []

    def h1(text):
        lines.append(f"\n# {text}\n")

    def h2(text):
        lines.append(f"\n## {text}\n")

    def h3(text):
        lines.append(f"\n### {text}\n")

    def p(text):
        lines.append(f"{text}\n")

    def bullet(text):
        lines.append(f"- {text}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ===== HEADER =====
    h1("WAGMI Sniper Trading Playbook")
    p(f"*Generated: {now}*")
    p("*Based on analysis of counterfactual data, sniper signals, and alpha research.*")
    p("**Account: $100 aggressive Hyperliquid account**")

    # ===== EXECUTIVE SUMMARY =====
    h2("Executive Summary")

    traj = playbook["trajectory"]
    underlying = traj["underlying_stats"]
    p(f"**Data foundation:** {playbook['setup_analysis']['counterfactual']['total_records']} "
      f"counterfactual records, {playbook['setup_analysis']['sniper_signals']['total_signals']} sniper signals analyzed.")
    p(f"**Underlying edge:** {underlying['base_win_rate']:.0%} base win rate, "
      f"{underlying['payoff_ratio']:.1f}:1 payoff ratio, "
      f"{underlying['avg_win_pct']:.1f}% avg win vs {underlying['avg_loss_pct']:.1f}% avg loss.")
    lines.append("")

    # Quick scenario summary
    for name, scenario in traj["scenarios"].items():
        eq = scenario["equity_stats"]
        p(f"**{name.replace('_', ' ').title()}** (WR={scenario['params']['wr']:.0%}): "
          f"$100 -> median ${eq['median']:,.0f} in {traj['simulation_days']}d "
          f"(range: ${eq['p5_worst']:,.0f} - ${eq['p95_best']:,.0f}). "
          f"Ruin risk: {eq['ruin_pct']}%.")

    # ===== THE RULES (most important section) =====
    h2("The Rules")

    rules = playbook["rules"]

    h3("Primary Trading Rules")
    for i, rule in enumerate(rules["primary_rules"], 1):
        bullet(f"**Rule {i}:** {rule}")
    lines.append("")

    h3("Risk Management Rules")
    for rule in rules["risk_rules"]:
        bullet(rule)
    lines.append("")

    h3("Daily Routine")
    for step in rules["daily_routine"]:
        bullet(step)
    lines.append("")

    # ===== SETUP RANKINGS =====
    h2("Setup Rankings by Expected Value")

    p("Ranked by EV per trade (higher = better edge):")
    lines.append("")

    widths = [15, 6, 8, 10, 8, 8, 6]
    lines.append(_table_row(["Setup", "WR", "Payoff", "EV/Trade", "Lev", "Kelly", "Grade"], widths))
    lines.append(_table_sep(widths))

    for r in playbook["setup_rankings"]:
        lines.append(_table_row([
            r["setup"],
            f"{r['win_rate']:.0%}",
            f"{r['payoff_ratio']:.1f}x",
            f"{r['ev_per_trade']:.2f}%",
            f"{r['optimal_leverage']:.0f}x",
            f"{r['half_kelly_risk']:.2%}",
            r["grade"],
        ], widths))
    lines.append("")

    # ===== POSITION SIZING TABLE =====
    h2("Position Sizing at Each Equity Level")

    p("How much to risk and what position size at each equity milestone:")
    lines.append("")

    widths = [8, 10, 12, 5, 10, 12, 5]
    lines.append(_table_row(
        ["Equity", "Sniper $", "Sniper Pos", "Lev", "Prem $", "Prem Pos", "Lev"],
        widths
    ))
    lines.append(_table_sep(widths))

    for s in playbook["sizing_table"]:
        lines.append(_table_row([
            f"${s['equity']:,}",
            f"${s['sniper_risk']:.0f}",
            f"${s['sniper_position']:.0f}",
            f"{s['sniper_leverage']:.0f}x",
            f"${s['premium_risk']:.0f}",
            f"${s['premium_position']:.0f}",
            f"{s['premium_leverage']:.0f}x",
        ], widths))
    lines.append("")

    # ===== COUNTERFACTUAL DEEP DIVE =====
    h2("Counterfactual Edge Analysis")

    cf = playbook["setup_analysis"]["counterfactual"]

    h3("By Symbol + Side")
    dim = cf["by_dimension"].get("symbol_side", {})
    widths = [12, 6, 6, 6, 8, 10]
    lines.append(_table_row(["Setup", "Count", "WR", "TP2%", "PF", "Avg PnL%"], widths))
    lines.append(_table_sep(widths))
    for k in sorted(dim.keys()):
        v = dim[k]
        lines.append(_table_row([
            k,
            v["count"],
            f"{v['win_rate']:.0%}",
            f"{v['tp2_rate']:.0%}",
            f"{v['profit_factor']:.2f}",
            f"{v['avg_pnl']:.2f}",
        ], widths))
    lines.append("")

    h3("By Confidence Band")
    dim = cf["by_dimension"].get("conf_band", {})
    widths = [10, 6, 6, 8, 10]
    lines.append(_table_row(["Band", "Count", "WR", "PF", "Avg PnL%"], widths))
    lines.append(_table_sep(widths))
    for k in sorted(dim.keys()):
        v = dim[k]
        lines.append(_table_row([
            k,
            v["count"],
            f"{v['win_rate']:.0%}",
            f"{v['profit_factor']:.2f}",
            f"{v['avg_pnl']:.2f}",
        ], widths))
    lines.append("")

    h3("By Regime")
    dim = cf["by_dimension"].get("regime", {})
    if dim:
        widths = [15, 6, 6, 8, 10]
        lines.append(_table_row(["Regime", "Count", "WR", "PF", "Avg PnL%"], widths))
        lines.append(_table_sep(widths))
        for k in sorted(dim.keys()):
            v = dim[k]
            lines.append(_table_row([
                k or "(empty)",
                v["count"],
                f"{v['win_rate']:.0%}",
                f"{v['profit_factor']:.2f}",
                f"{v['avg_pnl']:.2f}",
            ], widths))
        lines.append("")

    h3("By Time of Day (UTC)")
    dim = cf["by_dimension"].get("hour", {})
    if dim:
        widths = [12, 6, 6, 8, 10]
        lines.append(_table_row(["Hour", "Count", "WR", "PF", "Avg PnL%"], widths))
        lines.append(_table_sep(widths))
        for k in sorted(dim.keys()):
            v = dim[k]
            lines.append(_table_row([
                k,
                v["count"],
                f"{v['win_rate']:.0%}",
                f"{v['profit_factor']:.2f}",
                f"{v['avg_pnl']:.2f}",
            ], widths))
        lines.append("")

    h3("By Day of Week")
    dim = cf["by_dimension"].get("day", {})
    if dim:
        widths = [12, 6, 6, 8, 10]
        lines.append(_table_row(["Day", "Count", "WR", "PF", "Avg PnL%"], widths))
        lines.append(_table_sep(widths))
        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for k in day_order:
            if k in dim:
                v = dim[k]
                lines.append(_table_row([
                    k,
                    v["count"],
                    f"{v['win_rate']:.0%}",
                    f"{v['profit_factor']:.2f}",
                    f"{v['avg_pnl']:.2f}",
                ], widths))
        lines.append("")

    # ===== TOP CROSS-TABS =====
    h3("Top Setups (Cross-Tabulated)")
    p("Minimum 5 decided trades. Sorted by avg PnL%.")
    lines.append("")

    top = cf.get("top_setups", [])
    if top:
        widths = [30, 5, 6, 8, 10]
        lines.append(_table_row(["Combo", "N", "WR", "PF", "Avg PnL%"], widths))
        lines.append(_table_sep(widths))
        for t in top[:15]:
            lines.append(_table_row([
                t["combo"],
                t["decided"],
                f"{t['win_rate']:.0%}",
                f"{t['profit_factor']:.1f}",
                f"{t['avg_pnl_pct']:.2f}",
            ], widths))
        lines.append("")

    h3("Worst Setups (AVOID)")
    worst = cf.get("worst_setups", [])
    if worst:
        widths = [30, 5, 6, 8, 10]
        lines.append(_table_row(["Combo", "N", "WR", "PF", "Avg PnL%"], widths))
        lines.append(_table_sep(widths))
        for t in worst[:10]:
            lines.append(_table_row([
                t["combo"],
                t["decided"],
                f"{t['win_rate']:.0%}",
                f"{t['profit_factor']:.1f}",
                f"{t['avg_pnl_pct']:.2f}",
            ], widths))
        lines.append("")

    # ===== SNIPER SIGNAL PROFILE =====
    h2("Sniper Signal Profile")

    sn = playbook["setup_analysis"]["sniper_signals"]

    h3("Signal Distribution by Tier")
    dim = sn["by_dimension"].get("tier", {})
    widths = [10, 6, 8, 8, 8]
    lines.append(_table_row(["Tier", "Count", "Avg Conf", "Avg Lev", "Avg RR"], widths))
    lines.append(_table_sep(widths))
    for k in sorted(dim.keys()):
        v = dim[k]
        lines.append(_table_row([
            k,
            v["count"],
            f"{v['avg_confidence']:.0f}%",
            f"{v['avg_leverage']:.0f}x",
            f"{v['avg_rr_scalp']:.1f}",
        ], widths))
    lines.append("")

    h3("By Regime")
    dim = sn["by_dimension"].get("regime", {})
    widths = [15, 6, 8, 8]
    lines.append(_table_row(["Regime", "Count", "Avg Conf", "Avg Lev"], widths))
    lines.append(_table_sep(widths))
    for k in sorted(dim.keys()):
        v = dim[k]
        lines.append(_table_row([
            k,
            v["count"],
            f"{v['avg_confidence']:.0f}%",
            f"{v['avg_leverage']:.0f}x",
        ], widths))
    lines.append("")

    h3("By Num Agree")
    dim = sn["by_dimension"].get("num_agree", {})
    widths = [10, 6, 8, 8]
    lines.append(_table_row(["Agree", "Count", "Avg Conf", "Avg Lev"], widths))
    lines.append(_table_sep(widths))
    for k in sorted(dim.keys()):
        v = dim[k]
        lines.append(_table_row([
            k,
            v["count"],
            f"{v['avg_confidence']:.0f}%",
            f"{v['avg_leverage']:.0f}x",
        ], widths))
    lines.append("")

    # ===== COMPOUND GROWTH =====
    h2("Compound Growth Projections ($100 Start)")

    for name, scenario in traj["scenarios"].items():
        h3(f"Scenario: {name.replace('_', ' ').title()}")
        params = scenario["params"]
        eq = scenario["equity_stats"]
        p(f"Win rate: {params['wr']:.0%} | Risk/trade: {params['risk_pct']:.0%} | "
          f"Leverage: {params['leverage']}x | "
          f"Win return: {scenario['win_return_pct']:.1f}% | "
          f"Loss return: {scenario['loss_return_pct']:.1f}%")
        p(f"Total trades over {traj['simulation_days']} days: {scenario['total_trades']}")
        lines.append("")

        widths = [12, 10]
        lines.append(_table_row(["Metric", "Value"], widths))
        lines.append(_table_sep(widths))
        lines.append(_table_row(["Start", _fmt_money(eq["starting"])], widths))
        lines.append(_table_row(["Median", _fmt_money(eq["median"])], widths))
        lines.append(_table_row(["P25", _fmt_money(eq["p25"])], widths))
        lines.append(_table_row(["P75", _fmt_money(eq["p75"])], widths))
        lines.append(_table_row(["P5 (worst)", _fmt_money(eq["p5_worst"])], widths))
        lines.append(_table_row(["P95 (best)", _fmt_money(eq["p95_best"])], widths))
        lines.append(_table_row(["Worst path", _fmt_money(eq["worst"])], widths))
        lines.append(_table_row(["Best path", _fmt_money(eq["best"])], widths))
        lines.append(_table_row(["Ruin (<$10)", f"{eq['ruin_pct']}%"], widths))
        lines.append("")

        milestones = scenario.get("milestones_days", {})
        if milestones:
            p("**Time to milestones (median pace):**")
            for target, days_needed in milestones.items():
                if isinstance(days_needed, (int, float)):
                    bullet(f"{target}: ~{int(days_needed)} days")
                else:
                    bullet(f"{target}: {days_needed}")
            lines.append("")

    # ===== LEVERAGE TABLE =====
    h2("Optimal Leverage by Setup (Kelly Criterion)")

    lev_table = playbook["leverage_table"]
    if lev_table:
        widths = [15, 6, 6, 8, 8, 8, 10, 10]
        lines.append(_table_row(
            ["Setup", "WR", "RR", "Kelly", "1/2 K", "Opt Lev", "EV/Trade", "Daily EV"],
            widths
        ))
        lines.append(_table_sep(widths))
        for lev in lev_table:
            lines.append(_table_row([
                lev["setup"],
                f"{lev['win_rate']:.0%}",
                f"{lev['payoff_ratio']:.1f}x",
                f"{lev['kelly_fraction']:.2%}",
                f"{lev['half_kelly']:.2%}",
                f"{lev['optimal_leverage']:.0f}x",
                f"{lev['ev_per_trade_pct']:.2f}%",
                f"{lev['daily_ev_pct']:.2f}%",
            ], widths))
        lines.append("")

    # ===== ALPHA RESEARCH INTEGRATION =====
    h2("Key Findings from Alpha Research")

    p("These findings are from the ALPHA_RESEARCH.md analysis of 20K+ counterfactual records:")
    lines.append("")
    bullet("**Solo signals (1-agree) are ALWAYS negative PnL.** Never take them.")
    bullet("**3-agree signals have the best per-trade value** ($234-$582 range in backtests).")
    bullet("**Hold time 6-12h is optimal** (best WR bracket).")
    bullet("**BUY > SELL:** BUY signals have 48% WR vs SELL 29%. Long bias is correct.")
    bullet("**BTC is the most reliable symbol** (+$420-$534 in backtests).")
    bullet("**HYPE has highest missed alpha** in counterfactuals (46.2% WR on rejected signals).")
    bullet("**European session (08-16 UTC) is toxic** (-$261 in backtests). Avoid or reduce size.")
    bullet("**probability_engine is the best strategy** (PF=6.13). Weight its signals higher.")
    bullet("**Confidence 66-67% signals have 78-96% WR** but lowering the floor hurts overall "
           "(lets in bad 60-65% signals too).")
    lines.append("")

    # ===== CONCRETE PLAYBOOK =====
    h2("Concrete Playbook: $100 to $1000")

    h3("Phase 1: $100 to $250 (Survival Mode)")
    bullet("**Goal:** Build equity without getting wiped out.")
    bullet("**Max risk per trade:** $2 (2% of $100)")
    bullet("**Max daily loss:** $5 (stop trading)")
    bullet("**Only take:** SNIPER tier, 3-agree, confidence >= 85%")
    bullet("**Leverage:** 5-8x (conservative)")
    bullet("**Trades per day:** 1-2 max")
    bullet("**Avoid:** SELL signals, European session, solo/2-agree signals")
    bullet("**Position size:** $80-$160 per trade")
    lines.append("")

    h3("Phase 2: $250 to $500 (Growth Mode)")
    bullet("**Max risk per trade:** $5 (2% of $250)")
    bullet("**Max daily loss:** $12.50")
    bullet("**Can add:** PREMIUM tier if 3-agree + conf >= 82%")
    bullet("**Leverage:** 8-12x")
    bullet("**Trades per day:** 2-3")
    bullet("**Position size:** $200-$500 per trade")
    lines.append("")

    h3("Phase 3: $500 to $1000 (Compounding Mode)")
    bullet("**Max risk per trade:** $10 (2% of $500)")
    bullet("**Max daily loss:** $25")
    bullet("**Full signal menu:** SNIPER + PREMIUM tiers")
    bullet("**Leverage:** 10-15x for SNIPER setups")
    bullet("**Trades per day:** 2-4")
    bullet("**Position size:** $400-$1200 per trade")
    lines.append("")

    h3("Phase 4: $1000+ (Scale Mode)")
    bullet("**Max risk per trade:** $20 (2% of $1000)")
    bullet("**Max daily loss:** $50")
    bullet("**Begin withdrawing profits:** Take 20% of gains above $1000 weekly")
    bullet("**Leverage:** Per Kelly criterion (see table above)")
    bullet("**Position size:** $800-$2400 per trade")
    lines.append("")

    # ===== DECISION TREE =====
    h2("Decision Tree: Should I Take This Trade?")
    lines.append("")
    lines.append("```")
    lines.append("Signal arrives via Telegram")
    lines.append("  |")
    lines.append("  +-- Is it SNIPER or PREMIUM tier?")
    lines.append("  |     NO -> SKIP")
    lines.append("  |     YES -> continue")
    lines.append("  |")
    lines.append("  +-- Is num_agree >= 3?")
    lines.append("  |     NO -> SKIP (unless equity > $500 and conf >= 88%)")
    lines.append("  |     YES -> continue")
    lines.append("  |")
    lines.append("  +-- Is confidence >= 85%?")
    lines.append("  |     NO -> SKIP (unless 3-agree and conf >= 80%)")
    lines.append("  |     YES -> continue")
    lines.append("  |")
    lines.append("  +-- Is it a SELL signal?")
    lines.append("  |     YES -> Reduce size by 50% (long bias)")
    lines.append("  |     NO -> continue")
    lines.append("  |")
    lines.append("  +-- Is it European session (08-16 UTC)?")
    lines.append("  |     YES -> Reduce size by 30%")
    lines.append("  |     NO -> continue")
    lines.append("  |")
    lines.append("  +-- Have I hit 3 consecutive losses today?")
    lines.append("  |     YES -> STOP for 4 hours")
    lines.append("  |     NO -> continue")
    lines.append("  |")
    lines.append("  +-- Is daily loss > 5% of equity?")
    lines.append("  |     YES -> STOP for the day")
    lines.append("  |     NO -> TAKE THE TRADE")
    lines.append("```")
    lines.append("")

    # ===== FOOTER =====
    h2("Notes")
    bullet("This playbook is generated from historical/simulated data. Past performance does not guarantee future results.")
    bullet("Monte Carlo simulations assume trade independence and stable market conditions.")
    bullet("Adjust position sizes DOWN after 2+ consecutive losses.")
    bullet("Re-run this analysis weekly: `cd bot && python -m manual.generate_playbook`")
    lines.append("")

    return "\n".join(lines)


def main():
    """Run the full edge analysis and generate the playbook."""
    print("=" * 60)
    print("WAGMI Sniper Edge Analysis & Playbook Generator")
    print("=" * 60)
    print()

    print("[1/4] Analyzing best setups...")
    best_setups = analyze_best_setups()
    cf_count = best_setups["counterfactual"]["total_records"]
    sn_count = best_setups["sniper_signals"]["total_signals"]
    print(f"  -> {cf_count} counterfactual records, {sn_count} sniper signals")

    print("[2/4] Calculating optimal leverage (Kelly criterion)...")
    leverage = calculate_optimal_leverage(starting_equity=100.0)
    print(f"  -> {len(leverage)} setup types analyzed")
    for lev in leverage[:3]:
        print(f"     {lev['setup']}: WR={lev['win_rate']:.0%}, "
              f"Kelly={lev['kelly_fraction']:.2%}, "
              f"Optimal lev={lev['optimal_leverage']:.0f}x, "
              f"EV={lev['ev_per_trade_pct']:.2f}%/trade")

    print("[3/4] Running Monte Carlo simulations (1000 paths x 90 days)...")
    trajectory = calculate_compound_trajectory(starting_equity=100.0)
    for name, scenario in trajectory["scenarios"].items():
        eq = scenario["equity_stats"]
        print(f"  -> {name}: $100 -> median ${eq['median']:,.0f} "
              f"(P5=${eq['p5_worst']:,.0f}, P95=${eq['p95_best']:,.0f})")

    print("[4/4] Generating playbook...")
    playbook = generate_playbook()
    md = render_markdown(playbook)

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "TRADING_PLAYBOOK.md"
    output_file.write_text(md, encoding="utf-8")
    print(f"  -> Saved to {output_file}")

    # Also save raw JSON for programmatic access
    json_file = OUTPUT_DIR / "edge_analysis_raw.json"

    def _serialize(obj):
        if isinstance(obj, float) and (obj == float("inf") or obj == float("-inf")):
            return str(obj)
        raise TypeError(f"Not serializable: {type(obj)}")

    json_file.write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "leverage_table": playbook["leverage_table"],
            "sizing_table": playbook["sizing_table"],
            "setup_rankings": playbook["setup_rankings"],
            "trajectory_summary": {
                name: {
                    "params": s["params"],
                    "equity_stats": s["equity_stats"],
                    "milestones_days": s["milestones_days"],
                }
                for name, s in playbook["trajectory"]["scenarios"].items()
            },
        }, indent=2, default=_serialize),
        encoding="utf-8"
    )
    print(f"  -> Raw JSON saved to {json_file}")

    print()
    print("=" * 60)
    print("DONE. Read your playbook:")
    print(f"  {output_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
