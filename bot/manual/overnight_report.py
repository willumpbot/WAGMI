"""
Part 6: Overnight Report Generator

Generates a morning briefing summarizing overnight activity.
Designed to be run by the babysit terminal when the user wakes up.

Run: cd bot && python -m manual.overnight_report
     cd bot && python -m manual.overnight_report --hours 8
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional


def load_signal_outcomes(path="data/logs/signal_outcomes.jsonl", since_ts: float = 0) -> List[Dict]:
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if rec.get("ts", 0) >= since_ts:
                    records.append(rec)
    return records


def load_sniper_signals(path="data/manual/sniper_signals.jsonl", since_ts: float = 0) -> List[Dict]:
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                ts_str = rec.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt.timestamp() >= since_ts:
                        records.append(rec)
                except:
                    records.append(rec)  # Include if can't parse
    return records


def load_sim_status(path="data/manual/sim_status.json") -> Optional[Dict]:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_sim_trades(path="data/manual/sim_trades.jsonl", since_ts: float = 0) -> List[Dict]:
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                records.append(rec)
    return records


def analyze_overnight_signals(signals: List[Dict]) -> Dict:
    """Analyze signal outcomes from overnight period"""
    by_setup = defaultdict(lambda: {"total": 0, "passed": 0, "rejected": 0})
    total = len(signals)
    passed = sum(1 for s in signals if s.get("passed", False))

    for sig in signals:
        setup = f"{sig.get('sym', '?')}_{sig.get('side', '?')}"
        by_setup[setup]["total"] += 1
        if sig.get("passed"):
            by_setup[setup]["passed"] += 1
        else:
            by_setup[setup]["rejected"] += 1

    return {
        "total_signals": total,
        "passed": passed,
        "rejected": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "by_setup": dict(by_setup),
    }


def analyze_sniper_alerts(sniper_signals: List[Dict]) -> Dict:
    """Analyze sniper signals fired overnight"""
    by_tier = defaultdict(int)
    by_setup = defaultdict(lambda: {"n": 0, "avg_conf": [], "avg_lev": []})

    for sig in sniper_signals:
        tier = sig.get("tier", "UNKNOWN")
        by_tier[tier] += 1
        setup = f"{sig.get('symbol', '?')}_{sig.get('side', '?')}"
        by_setup[setup]["n"] += 1
        by_setup[setup]["avg_conf"].append(sig.get("confidence", 0))
        by_setup[setup]["avg_lev"].append(sig.get("leverage", 0))

    result = {
        "total": len(sniper_signals),
        "by_tier": dict(by_tier),
        "by_setup": {},
    }

    for setup, data in by_setup.items():
        result["by_setup"][setup] = {
            "n": data["n"],
            "avg_conf": round(sum(data["avg_conf"]) / len(data["avg_conf"]), 1) if data["avg_conf"] else 0,
            "avg_lev": round(sum(data["avg_lev"]) / len(data["avg_lev"]), 1) if data["avg_lev"] else 0,
        }

    return result


def detect_bursts(signals: List[Dict], window_s: int = 300) -> List[Dict]:
    """Detect signal bursts"""
    hype_buys = sorted(
        [s for s in signals if s.get("sym") == "HYPE" and s.get("side") == "BUY"],
        key=lambda x: x.get("ts", 0)
    )

    bursts = []
    current = []
    for sig in hype_buys:
        ts = sig.get("ts", 0)
        if not current:
            current = [sig]
        elif ts - current[-1].get("ts", 0) < window_s:
            current.append(sig)
        else:
            if len(current) >= 3:
                bursts.append({
                    "size": len(current),
                    "start": datetime.fromtimestamp(current[0].get("ts", 0), tz=timezone.utc).strftime("%H:%M UTC"),
                    "avg_conf": round(sum(s.get("conf", 0) for s in current) / len(current), 1),
                })
            current = [sig]

    if len(current) >= 3:
        bursts.append({
            "size": len(current),
            "start": datetime.fromtimestamp(current[0].get("ts", 0), tz=timezone.utc).strftime("%H:%M UTC"),
            "avg_conf": round(sum(s.get("conf", 0) for s in current) / len(current), 1),
        })

    return bursts


def new_filter_would_pass(sig: Dict) -> bool:
    """Quick check if signal passes new setup-driven filter"""
    setup = f"{sig.get('sym', '')}_{sig.get('side', '')}"
    proven = {"HYPE_BUY", "SOL_SELL"}
    chop = sig.get("meta", {}).get("chop_score_smoothed", 0)

    if setup in proven:
        max_chop = 0.4 if setup == "HYPE_BUY" else 0.5
        return chop <= max_chop
    else:
        return sig.get("conf", 0) >= 78 and sig.get("n_agree", 0) >= 2


def generate_briefing(signal_analysis: Dict, sniper_analysis: Dict,
                      bursts: List[Dict], sim_status: Optional[Dict],
                      hours: int, new_filter_stats: Dict) -> str:
    lines = []
    now = datetime.now(timezone.utc)
    lines.append("# Morning Briefing")
    lines.append(f"\n*Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append(f"*Covering last {hours} hours*")
    lines.append("\n---\n")

    # Quick Summary
    lines.append("## Quick Summary\n")
    lines.append(f"- **Signals processed:** {signal_analysis['total_signals']}")
    lines.append(f"- **Passed bot gates:** {signal_analysis['passed']} ({signal_analysis['pass_rate']}%)")
    lines.append(f"- **Sniper alerts fired:** {sniper_analysis['total']}")
    lines.append(f"- **HYPE BUY bursts:** {len(bursts)}")

    if new_filter_stats:
        lines.append(f"- **New filter would pass:** {new_filter_stats.get('would_pass', 0)} signals")
        lines.append(f"- **Old filter passed:** {new_filter_stats.get('old_passed', 0)} signals")

    # Signal Breakdown
    lines.append("\n---\n")
    lines.append("## Signal Breakdown\n")
    lines.append("| Setup | Total | Passed | Rejected |")
    lines.append("|-------|-------|--------|----------|")
    for setup, data in sorted(signal_analysis["by_setup"].items()):
        lines.append(f"| {setup} | {data['total']} | {data['passed']} | {data['rejected']} |")

    # New Filter Analysis
    if new_filter_stats.get("by_setup"):
        lines.append("\n### New Filter Pass/Reject\n")
        lines.append("| Setup | Would Pass | Would Reject |")
        lines.append("|-------|-----------|-------------|")
        for setup, data in new_filter_stats["by_setup"].items():
            lines.append(f"| {setup} | {data['pass']} | {data['reject']} |")

    # Sniper Alerts
    if sniper_analysis["total"] > 0:
        lines.append("\n---\n")
        lines.append("## Sniper Alerts\n")
        lines.append(f"Total: {sniper_analysis['total']}\n")
        lines.append("| Tier | Count |")
        lines.append("|------|-------|")
        for tier, count in sniper_analysis["by_tier"].items():
            lines.append(f"| {tier} | {count} |")

        if sniper_analysis["by_setup"]:
            lines.append("\n| Setup | N | Avg Conf | Avg Lev |")
            lines.append("|-------|---|----------|---------|")
            for setup, data in sniper_analysis["by_setup"].items():
                lines.append(f"| {setup} | {data['n']} | {data['avg_conf']}% | {data['avg_lev']}x |")

    # HYPE BUY Bursts
    if bursts:
        lines.append("\n---\n")
        lines.append("## HYPE BUY Bursts\n")
        lines.append("| Time | Size | Avg Conf | Note |")
        lines.append("|------|------|----------|------|")
        for b in bursts:
            note = "Strong dip-buy signal" if b["size"] >= 10 else "Moderate burst"
            lines.append(f"| {b['start']} | {b['size']} | {b['avg_conf']}% | {note} |")

    # Simulator Status
    if sim_status:
        lines.append("\n---\n")
        lines.append("## Simulator Status\n")
        lines.append(f"- Equity: ${sim_status.get('equity', 'N/A')}")
        lines.append(f"- Open positions: {sim_status.get('open_positions', 'N/A')}")
        lines.append(f"- Total trades: {sim_status.get('total_trades', 'N/A')}")
        lines.append(f"- Win rate: {sim_status.get('win_rate', 'N/A')}%")

    # Action Items
    lines.append("\n---\n")
    lines.append("## Action Items\n")

    if len(bursts) > 0:
        lines.append(f"- Review {len(bursts)} HYPE BUY bursts — potential dip-buy opportunities")

    hype_buy_count = signal_analysis["by_setup"].get("HYPE_BUY", {}).get("total", 0)
    if hype_buy_count > 20:
        lines.append(f"- Heavy HYPE BUY activity ({hype_buy_count} signals) — check HYPE price for dip-buy patterns")

    sol_sell_count = signal_analysis["by_setup"].get("SOL_SELL", {}).get("total", 0)
    if sol_sell_count > 0:
        lines.append(f"- SOL SELL signals appeared ({sol_sell_count}) — bearish pressure may be building")

    if sniper_analysis["total"] == 0:
        lines.append("- No sniper alerts fired — quiet night, no action needed")

    lines.append("\n---\n*End of briefing. Check data/manual/ for detailed research reports.*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate overnight report")
    parser.add_argument("--hours", type=int, default=8, help="Hours to look back")
    args = parser.parse_args()

    hours = args.hours
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    since_ts = since.timestamp()

    print("=" * 60)
    print(f"OVERNIGHT REPORT (last {hours} hours)")
    print("=" * 60)

    # Load data
    print(f"\n[1/5] Loading signals since {since.strftime('%H:%M UTC')}...")
    signals = load_signal_outcomes(since_ts=since_ts)
    print(f"  Signal outcomes: {len(signals)}")

    print("[2/5] Loading sniper alerts...")
    sniper_signals = load_sniper_signals(since_ts=since_ts)
    print(f"  Sniper signals: {len(sniper_signals)}")

    print("[3/5] Loading simulator status...")
    sim_status = load_sim_status()

    # Analyze
    print("[4/5] Analyzing...")
    signal_analysis = analyze_overnight_signals(signals)
    sniper_analysis = analyze_sniper_alerts(sniper_signals)
    bursts = detect_bursts(signals)

    # New filter analysis
    new_filter_stats = {"would_pass": 0, "old_passed": 0, "by_setup": defaultdict(lambda: {"pass": 0, "reject": 0})}
    for sig in signals:
        setup = f"{sig.get('sym', '?')}_{sig.get('side', '?')}"
        if new_filter_would_pass(sig):
            new_filter_stats["would_pass"] += 1
            new_filter_stats["by_setup"][setup]["pass"] += 1
        else:
            new_filter_stats["by_setup"][setup]["reject"] += 1
        if sig.get("passed"):
            new_filter_stats["old_passed"] += 1
    new_filter_stats["by_setup"] = dict(new_filter_stats["by_setup"])

    # Generate
    print("[5/5] Generating briefing...")
    briefing = generate_briefing(
        signal_analysis, sniper_analysis, bursts,
        sim_status, hours, new_filter_stats
    )

    os.makedirs("data/manual", exist_ok=True)
    with open("data/manual/MORNING_BRIEFING.md", "w") as f:
        f.write(briefing)
    print(f"\n  Saved: data/manual/MORNING_BRIEFING.md")

    # Print summary to stdout
    print("\n" + "=" * 60)
    print("QUICK SUMMARY")
    print("=" * 60)
    print(f"Signals: {signal_analysis['total_signals']} ({signal_analysis['pass_rate']}% passed)")
    print(f"Sniper alerts: {sniper_analysis['total']}")
    print(f"HYPE BUY bursts: {len(bursts)}")
    if new_filter_stats["would_pass"] != new_filter_stats["old_passed"]:
        delta = new_filter_stats["would_pass"] - new_filter_stats["old_passed"]
        print(f"New filter would pass {new_filter_stats['would_pass']} (old: {new_filter_stats['old_passed']}, delta: {delta:+d})")


if __name__ == "__main__":
    main()
