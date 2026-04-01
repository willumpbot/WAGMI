"""
CLI tool for viewing LLM agent performance reports.

Usage:
    python -m tools.agent_performance              # Full report
    python -m tools.agent_performance --days 7      # Last 7 days
    python -m tools.agent_performance --json        # JSON output
    python -m tools.agent_performance --summary     # One-line summary
"""

import argparse
import json
import sys
import os

# Ensure bot/ is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.agents.performance_tracker import get_performance_tracker


def format_report(report: dict) -> str:
    """Format the performance report for terminal display."""
    lines = []
    lines.append("=" * 72)
    lines.append("  LLM AGENT PERFORMANCE REPORT")
    lines.append("=" * 72)

    n = report.get("total_scored_trades", 0)
    nv = report.get("total_veto_counterfactuals", 0)
    period = report.get("period_days", "all")
    lines.append(f"  Period: {period} | Scored trades: {n} | Veto counterfactuals: {nv}")
    lines.append("")

    if n == 0 and nv == 0:
        lines.append("  " + report.get("message", "No data yet."))
        lines.append("")
        lines.append("  To collect data:")
        lines.append("    1. Run the bot with LLM_MULTI_AGENT=true")
        lines.append("    2. Wait for trades to open and close")
        lines.append("    3. The tracker auto-scores agents on trade closure")
        lines.append("=" * 72)
        return "\n".join(lines)

    agents = report.get("agents", {})

    # ── Regime Agent ────────────────────────────────────────────
    regime = agents.get("regime", {})
    if regime.get("count", 0) > 0:
        lines.append("-" * 72)
        lines.append("  REGIME AGENT")
        lines.append("-" * 72)
        alpha_tag = " [+ALPHA]" if regime.get("adding_alpha") else " [-NOISE]"
        lines.append(f"  Accuracy:    {regime['accuracy']:.1%} ({regime['correct']}/{regime['count']}){alpha_tag}")
        lines.append(f"  Avg Conf:    {regime['avg_confidence']:.1%}")
        by_regime = regime.get("by_regime", {})
        if by_regime:
            lines.append("  By regime:")
            for rg, stats in sorted(by_regime.items()):
                lines.append(f"    {rg:20s}  {stats['accuracy']:.0%} ({stats['count']} trades)")
        lines.append("")

    # ── Trade Agent ─────────────────────────────────────────────
    trade = agents.get("trade", {})
    if trade.get("count", 0) > 0:
        lines.append("-" * 72)
        lines.append("  TRADE AGENT")
        lines.append("-" * 72)
        alpha_tag = " [+ALPHA]" if trade.get("adding_alpha") else " [-NOISE]"
        lines.append(f"  Direction:   {trade['direction_accuracy']:.1%}{alpha_tag}")
        lines.append(f"  Win Rate:    {trade['win_rate']:.1%}")
        lines.append(f"  Thesis Acc:  {trade['avg_thesis_accuracy']:.1%}")
        lines.append(f"  Avg Conf:    {trade['avg_confidence']:.1%}")
        cal = trade.get("calibration", {})
        if cal:
            cal_tag = " (CALIBRATED)" if cal.get("well_calibrated") else " (MISCALIBRATED)"
            lines.append(f"  High-conf WR: {cal.get('high_conf_wr', 0):.1%}")
            lines.append(f"  Low-conf WR:  {cal.get('low_conf_wr', 0):.1%}{cal_tag}")
        lines.append("")

    # ── Risk Agent ──────────────────────────────────────────────
    risk = agents.get("risk", {})
    if risk.get("count", 0) > 0:
        lines.append("-" * 72)
        lines.append("  RISK AGENT")
        lines.append("-" * 72)
        alpha_tag = " [+ALPHA]" if risk.get("adding_alpha") else " [-NOISE]"
        lines.append(f"  Sizing Eff:  {risk['avg_sizing_efficiency']:.1%}{alpha_tag}")
        lines.append(f"  Avg Size:    {risk['avg_recommended_size']:.2f}x")
        lines.append(f"  Opt Kelly:   {risk['avg_optimal_kelly']:.2f}")
        disc_tag = "YES" if risk.get("size_discriminates_winners") else "NO"
        lines.append(f"  Size discrim: {disc_tag}")
        lines.append(f"    Winner size:  {risk.get('winner_avg_size', 0):.2f}x")
        lines.append(f"    Loser size:   {risk.get('loser_avg_size', 0):.2f}x")
        lines.append("")

    # ── Critic Agent ────────────────────────────────────────────
    critic = agents.get("critic", {})
    if critic.get("count", 0) > 0:
        lines.append("-" * 72)
        lines.append("  CRITIC AGENT")
        lines.append("-" * 72)
        alpha_tag = " [+ALPHA]" if critic.get("adding_alpha") else " [-NOISE]"
        lines.append(f"  Decisions:   {critic['count']}{alpha_tag}")
        lines.append(f"  Approvals:   {critic.get('approval_count', 0)} (acc: {critic.get('approval_accuracy', 0):.1%})")
        lines.append(f"  Vetoes:      {critic.get('veto_count', 0)} (acc: {critic.get('veto_accuracy', 0):.1%})")
        lines.append(f"  Challenges:  {critic.get('challenge_count', 0)} (acc: {critic.get('challenge_accuracy', 0):.1%})")
        net = critic.get("net_veto_value_pct", 0)
        net_tag = "SAVED" if net > 0 else "COST"
        lines.append(f"  Net veto val: {net:+.2f}% ({net_tag} money)")
        lines.append("")

    # ── Exit Agent ──────────────────────────────────────────────
    exit_s = agents.get("exit", {})
    if exit_s.get("count", 0) > 0:
        lines.append("-" * 72)
        lines.append("  EXIT AGENT")
        lines.append("-" * 72)
        alpha_tag = " [+ALPHA]" if exit_s.get("adding_alpha") else " [-NOISE]"
        lines.append(f"  Timing:      {exit_s['avg_timing_score']:+.2f}{alpha_tag}")
        lines.append(f"  Money left:  {exit_s.get('avg_money_left_on_table_pct', 0):.2f}%")
        lines.append(f"  Money saved: {exit_s.get('avg_money_saved_pct', 0):.2f}%")
        net = exit_s.get("net_exit_value_pct", 0)
        lines.append(f"  Net value:   {net:+.2f}%")
        lines.append("")

    # ── Alpha Attribution ───────────────────────────────────────
    alpha = report.get("alpha_attribution", {})
    if alpha and alpha.get("total_pnl_pct") is not None:
        lines.append("-" * 72)
        lines.append("  ALPHA ATTRIBUTION")
        lines.append("-" * 72)
        lines.append(f"  Total PnL:   {alpha['total_pnl_pct']:+.2f}%")
        lines.append(f"  Avg/trade:   {alpha.get('avg_pnl_per_trade', 0):+.2f}%")

        ra = alpha.get("regime_alpha", {})
        if ra:
            lines.append(f"  Regime edge: {ra.get('regime_edge', 0):+.2f}%")
            lines.append(f"    Correct regime avg PnL: {ra.get('correct_avg_pnl', 0):+.2f}%")
            lines.append(f"    Wrong regime avg PnL:   {ra.get('wrong_avg_pnl', 0):+.2f}%")

        ta = alpha.get("trade_alpha", {})
        if ta:
            lines.append(f"  Direction edge: {ta.get('direction_edge', 0):+.2f}%")

        ca = alpha.get("critic_alpha", {})
        if ca:
            lines.append(f"  Critic saves:   {ca.get('total_money_saved_by_vetoes_pct', 0):+.2f}%")
        lines.append("")

    # ── Recommendations ─────────────────────────────────────────
    recs = report.get("recommendations", [])
    if recs:
        lines.append("-" * 72)
        lines.append("  RECOMMENDATIONS")
        lines.append("-" * 72)
        for i, rec in enumerate(recs, 1):
            lines.append(f"  {i}. {rec}")
        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="LLM Agent Performance Report")
    parser.add_argument("--days", type=int, default=None, help="Lookback period in days")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--summary", action="store_true", help="One-line summary only")
    args = parser.parse_args()

    tracker = get_performance_tracker()

    if args.summary:
        print(tracker.get_agent_summary_line())
        return

    report = tracker.get_agent_report(lookback_days=args.days)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))


if __name__ == "__main__":
    main()
