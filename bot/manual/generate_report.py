"""
Standalone report generator for the manual sniper optimizer.

Run:
    cd bot && python -m manual.generate_report

Generates the weekly optimization report, prints key recommendations
to stdout, and saves the full report to data/manual/weekly_reports/.
"""

import sys
import os

# Ensure bot/ is on the path when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from manual.optimizer import SniperOptimizer

    print("=" * 50)
    print("  SNIPER OPTIMIZER — Weekly Report Generator")
    print("=" * 50)
    print()

    opt = SniperOptimizer()

    # ── Signal Quality ──
    quality = opt.analyze_signal_quality()
    if quality["status"] == "cold_start":
        print("[Signal Quality] No signals yet. Generate signals first.")
    else:
        print(f"[Signal Quality] {quality['total_signals']} signals over {quality['days_active']} days")
        print(f"  Avg/day: {quality['avg_per_day']:.1f} | SNR: {quality['signal_to_noise']:.1%}")
        print(f"  Tiers: {quality['tier_distribution']}")
        print(f"  Confidence avg: {quality['confidence']['avg']:.1f}")
    print()

    # ── Leverage Efficiency ──
    leverage = opt.analyze_leverage_efficiency()
    if leverage["status"] == "no_trades":
        print("[Leverage] No closed trades yet.")
    else:
        print(f"[Leverage] {leverage['total_closed']} closed trades analyzed")
        for band, stats in leverage["leverage_bands"].items():
            if stats["count"] > 0:
                print(
                    f"  {band}: {stats['count']} trades, "
                    f"WR {stats['win_rate']:.0%}, "
                    f"avg PnL ${stats['avg_pnl']:+.2f}, "
                    f"Sharpe {stats['sharpe']:.2f}"
                )
    print()

    # ── Timing ──
    timing = opt.analyze_timing()
    if timing["status"] != "cold_start":
        if timing["hot_hours"]:
            hours = ", ".join(f"{h:02d}:00" for h in timing["hot_hours"][:5])
            print(f"[Timing] Peak signal hours (UTC): {hours}")
        if timing["hourly_win_rate"]:
            best = timing["best_win_hours"][:3]
            for h in best:
                print(f"  Best WR hour: {h:02d}:00 UTC ({timing['hourly_win_rate'][h]:.0%})")
    else:
        print("[Timing] No data yet.")
    print()

    # ── Suggestions ──
    suggestions = opt.suggest_parameter_changes()
    if suggestions:
        print("=" * 50)
        print("  PARAMETER RECOMMENDATIONS")
        print("=" * 50)
        for param, info in sorted(
            suggestions.items(),
            key=lambda x: x[1]["confidence_pct"],
            reverse=True,
        ):
            print(f"\n  {param}: {info['current']} -> {info['suggested']}")
            print(f"    Reason: {info['reason']}")
            print(f"    Confidence: {info['confidence_pct']}% ({info.get('data_points', '?')} data points)")
    else:
        print("No parameter changes suggested (need more trade data).")
    print()

    # ── Generate full report ──
    print("Generating full weekly report...")
    report = opt.generate_weekly_report()

    # Find where it was saved
    reports_dir = os.path.join("data", "manual", "weekly_reports")
    if os.path.exists(reports_dir):
        files = sorted(os.listdir(reports_dir))
        if files:
            print(f"Report saved to: {os.path.join(reports_dir, files[-1])}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
