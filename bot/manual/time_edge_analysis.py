"""
Part 3: Time-of-Day Edge Mining

Analyzes timestamps on counterfactual outcomes and signal outcomes
to find optimal trading hours, days, and sessions.

Run: cd bot && python -m manual.time_edge_analysis
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any


def load_counterfactuals(path="data/counterfactual_resolved.json") -> List[Dict]:
    with open(path) as f:
        data = json.load(f)
    return data["records"]


def load_signal_outcomes(path="data/logs/signal_outcomes.jsonl") -> List[Dict]:
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def parse_ts(rec: Dict) -> datetime:
    """Parse timestamp from various formats"""
    ts = rec.get("created_at", rec.get("ts", ""))
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except:
            pass
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def analyze_by_hour(records: List[Dict], is_cf: bool = True) -> Dict:
    """Bucket records by UTC hour"""
    by_hour = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})

    for rec in records:
        dt = parse_ts(rec)
        hour = dt.hour
        s = by_hour[hour]
        s["n"] += 1

        if is_cf:
            if rec.get("would_hit_tp1", False):
                s["wins"] += 1
            else:
                s["losses"] += 1
            s["total_pnl"] += rec.get("hypothetical_pnl_pct", 0)

    return dict(by_hour)


def analyze_by_hour_and_setup(records: List[Dict]) -> Dict:
    """Bucket by hour AND setup"""
    by_hour_setup = defaultdict(lambda: defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "pnl": 0.0}))

    for rec in records:
        dt = parse_ts(rec)
        hour = dt.hour
        setup = f"{rec['symbol']}_{rec['side']}"
        s = by_hour_setup[hour][setup]
        s["n"] += 1
        if rec.get("would_hit_tp1", False):
            s["wins"] += 1
        else:
            s["losses"] += 1
        s["pnl"] += rec.get("hypothetical_pnl_pct", 0)

    return {h: dict(setups) for h, setups in by_hour_setup.items()}


def analyze_by_day(records: List[Dict]) -> Dict:
    """Bucket by day of week"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_day = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})

    for rec in records:
        dt = parse_ts(rec)
        day_name = days[dt.weekday()]
        s = by_day[day_name]
        s["n"] += 1
        if rec.get("would_hit_tp1", False):
            s["wins"] += 1
        else:
            s["losses"] += 1
        s["total_pnl"] += rec.get("hypothetical_pnl_pct", 0)

    return dict(by_day)


def analyze_sessions(records: List[Dict]) -> Dict:
    """Analyze by trading session"""
    sessions = {
        "Asia (00-08 UTC)": (0, 8),
        "Europe (08-16 UTC)": (8, 16),
        "US (14-22 UTC)": (14, 22),
        "EU-US Overlap (14-16 UTC)": (14, 16),
        "Asia-EU Overlap (08-10 UTC)": (8, 10),
        "Late Night (22-00 UTC)": (22, 24),
    }

    results = {}
    for label, (start, end) in sessions.items():
        session_recs = [r for r in records if start <= parse_ts(r).hour < end]
        if not session_recs:
            results[label] = {"n": 0}
            continue

        wins = sum(1 for r in session_recs if r.get("would_hit_tp1", False))
        losses = len(session_recs) - wins
        pnl = sum(r.get("hypothetical_pnl_pct", 0) for r in session_recs)

        # By setup within session
        by_setup = defaultdict(lambda: {"n": 0, "wins": 0})
        for r in session_recs:
            setup = f"{r['symbol']}_{r['side']}"
            by_setup[setup]["n"] += 1
            if r.get("would_hit_tp1", False):
                by_setup[setup]["wins"] += 1

        results[label] = {
            "n": len(session_recs),
            "wins": wins,
            "losses": losses,
            "wr": round(wins / len(session_recs) * 100, 1),
            "total_pnl": round(pnl, 2),
            "avg_pnl": round(pnl / len(session_recs), 2),
            "by_setup": {k: dict(v) for k, v in by_setup.items()},
        }

    return results


def analyze_signal_timing(outcomes: List[Dict]) -> Dict:
    """Analyze signal outcome timing patterns"""
    by_hour = defaultdict(lambda: {"n": 0, "passed": 0, "rejected": 0,
                                    "by_setup": defaultdict(int)})

    for sig in outcomes:
        dt = parse_ts(sig)
        hour = dt.hour
        s = by_hour[hour]
        s["n"] += 1
        setup = f"{sig['sym']}_{sig['side']}"
        s["by_setup"][setup] += 1
        if sig.get("passed"):
            s["passed"] += 1
        else:
            s["rejected"] += 1

    return {h: {"n": v["n"], "passed": v["passed"], "rejected": v["rejected"],
                "by_setup": dict(v["by_setup"])}
            for h, v in by_hour.items()}


def generate_report(hourly, hourly_setup, daily, sessions, signal_timing, hype_buy_hourly) -> str:
    lines = []
    lines.append("# Time-of-Day Edge Analysis")
    lines.append(f"\n*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("\n---\n")

    # Section 1: Hourly WR
    lines.append("## 1. Counterfactual Win Rate by Hour (UTC)\n")
    lines.append("| Hour | N | Wins | Losses | WR | Avg PnL% | Total PnL% |")
    lines.append("|------|---|------|--------|----|----------|-----------|")
    for hour in sorted(hourly.keys()):
        h = hourly[hour]
        wr = h["wins"] / h["n"] * 100 if h["n"] > 0 else 0
        avg_pnl = h["total_pnl"] / h["n"] if h["n"] > 0 else 0
        lines.append(f"| {hour:02d}:00 | {h['n']} | {h['wins']} | {h['losses']} | {wr:.1f}% | {avg_pnl:+.2f}% | {h['total_pnl']:+.1f}% |")

    # Section 2: HYPE BUY by hour
    lines.append("\n---\n")
    lines.append("## 2. HYPE BUY Win Rate by Hour (THE MONEY HOURS)\n")
    lines.append("| Hour | N | Wins | WR | Avg PnL% |")
    lines.append("|------|---|------|----|----------|")
    for hour in sorted(hype_buy_hourly.keys()):
        h = hype_buy_hourly[hour]
        if h["n"] == 0:
            continue
        wr = h["wins"] / h["n"] * 100 if h["n"] > 0 else 0
        avg_pnl = h["pnl"] / h["n"] if h["n"] > 0 else 0
        marker = " **GOLDEN**" if wr >= 90 and h["n"] >= 5 else ""
        lines.append(f"| {hour:02d}:00 | {h['n']} | {h['wins']} | {wr:.1f}% | {avg_pnl:+.2f}%{marker} |")

    # Section 3: Day of week
    lines.append("\n---\n")
    lines.append("## 3. Day of Week Analysis\n")
    lines.append("| Day | N | Wins | WR | Total PnL% |")
    lines.append("|-----|---|------|----|-----------|")
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        d = daily.get(day, {"n": 0, "wins": 0, "total_pnl": 0})
        if d["n"] == 0:
            continue
        wr = d["wins"] / d["n"] * 100 if d["n"] > 0 else 0
        lines.append(f"| {day} | {d['n']} | {d['wins']} | {wr:.1f}% | {d['total_pnl']:+.1f}% |")

    # Section 4: Sessions
    lines.append("\n---\n")
    lines.append("## 4. Trading Session Analysis\n")
    lines.append("| Session | N | WR | Avg PnL% | Total PnL% |")
    lines.append("|---------|---|----|----------|-----------|")
    for session, data in sessions.items():
        if data["n"] == 0:
            continue
        lines.append(f"| {session} | {data['n']} | {data['wr']}% | {data['avg_pnl']:+.2f}% | {data['total_pnl']:+.1f}% |")

    # Section 5: Session breakdown by setup
    lines.append("\n### Session x Setup Breakdown\n")
    for session, data in sessions.items():
        if data["n"] == 0 or "by_setup" not in data:
            continue
        lines.append(f"\n**{session}:**")
        for setup, stats in sorted(data.get("by_setup", {}).items()):
            wr = stats["wins"] / stats["n"] * 100 if stats["n"] > 0 else 0
            lines.append(f"- {setup}: N={stats['n']}, WR={wr:.0f}%")

    # Section 6: Signal flow by hour
    lines.append("\n---\n")
    lines.append("## 5. Live Signal Volume by Hour\n")
    lines.append("| Hour | Signals | Passed | Rejected | Top Setup |")
    lines.append("|------|---------|--------|----------|-----------|")
    for hour in sorted(signal_timing.keys()):
        t = signal_timing[hour]
        top_setup = max(t["by_setup"].items(), key=lambda x: x[1])[0] if t["by_setup"] else "N/A"
        top_count = max(t["by_setup"].values()) if t["by_setup"] else 0
        lines.append(f"| {hour:02d}:00 | {t['n']} | {t['passed']} | {t['rejected']} | {top_setup} ({top_count}) |")

    # Section 7: Optimal schedule
    lines.append("\n---\n")
    lines.append("## 6. Optimal Trading Schedule\n")

    # Find best hours for HYPE BUY
    best_hours = []
    for hour, data in hype_buy_hourly.items():
        if data["n"] >= 3:
            wr = data["wins"] / data["n"] * 100
            best_hours.append((hour, wr, data["n"]))
    best_hours.sort(key=lambda x: -x[1])

    if best_hours:
        lines.append("### Best Hours for HYPE BUY (by WR, min 3 signals)\n")
        for hour, wr, n in best_hours[:8]:
            emoji = "+++" if wr >= 90 else "++" if wr >= 80 else "+"
            lines.append(f"- **{hour:02d}:00 UTC** — WR={wr:.0f}%, N={n} [{emoji}]")

    lines.append("\n### Recommended Check Times\n")
    lines.append("Based on signal volume and HYPE BUY WR:\n")
    # Top 4 hours by signal volume
    volume_hours = sorted(signal_timing.items(), key=lambda x: -x[1]["n"])[:4]
    for hour, data in volume_hours:
        lines.append(f"- **{hour:02d}:00 UTC** — {data['n']} signals ({data['passed']} passed)")

    lines.append("\n### User Timezone Mapping\n")
    lines.append("Assuming US Eastern (UTC-4) or Pacific (UTC-7):\n")
    for hour, wr, n in best_hours[:5]:
        et = (hour - 4) % 24
        pt = (hour - 7) % 24
        lines.append(f"- {hour:02d}:00 UTC = {et:02d}:00 ET = {pt:02d}:00 PT (WR={wr:.0f}%)")

    # Limitations
    lines.append("\n---\n")
    lines.append("## Limitations\n")
    lines.append("- Counterfactual data is ALL from a single time window (~18:00 UTC Monday)")
    lines.append("- Only 1000 resolved records — hour/day analysis has low N per bucket")
    lines.append("- Signal outcomes don't have price outcomes, only pass/reject")
    lines.append("- Need 2+ weeks of multi-hour data for robust time-of-day conclusions")

    lines.append("\n---\n*Analysis complete.*")
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("PART 3: Time-of-Day Edge Mining")
    print("=" * 60)

    print("\n[1/5] Loading data...")
    cfs = load_counterfactuals()
    outcomes = load_signal_outcomes()
    print(f"  Counterfactuals: {len(cfs)}")
    print(f"  Signal outcomes: {len(outcomes)}")

    print("\n[2/5] Analyzing by hour...")
    hourly = analyze_by_hour(cfs)
    hourly_setup = analyze_by_hour_and_setup(cfs)

    # Extract HYPE BUY hourly
    hype_buy_hourly = {}
    for hour, setups in hourly_setup.items():
        hb = setups.get("HYPE_BUY", {"n": 0, "wins": 0, "losses": 0, "pnl": 0})
        hype_buy_hourly[hour] = hb

    for hour in sorted(hourly.keys()):
        h = hourly[hour]
        wr = h["wins"] / h["n"] * 100 if h["n"] > 0 else 0
        print(f"  Hour {hour:02d}: N={h['n']}, WR={wr:.1f}%")

    print("\n[3/5] Analyzing by day...")
    daily = analyze_by_day(cfs)
    for day, d in daily.items():
        wr = d["wins"] / d["n"] * 100 if d["n"] > 0 else 0
        print(f"  {day}: N={d['n']}, WR={wr:.1f}%")

    print("\n[4/5] Analyzing sessions...")
    sessions = analyze_sessions(cfs)
    for session, data in sessions.items():
        if data["n"] > 0:
            print(f"  {session}: N={data['n']}, WR={data['wr']}%")

    print("\n[5/5] Analyzing signal timing...")
    signal_timing = analyze_signal_timing(outcomes)

    # Generate report
    report = generate_report(hourly, hourly_setup, daily, sessions, signal_timing, hype_buy_hourly)

    os.makedirs("data/manual", exist_ok=True)
    with open("data/manual/TIME_EDGE_ANALYSIS.md", "w") as f:
        f.write(report)
    print("\n  Saved: data/manual/TIME_EDGE_ANALYSIS.md")

    # Save JSON
    json_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "hourly": hourly,
        "hourly_by_setup": hourly_setup,
        "hype_buy_hourly": hype_buy_hourly,
        "daily": daily,
        "sessions": sessions,
        "signal_timing": {str(k): v for k, v in signal_timing.items()},
    }
    with open("data/manual/time_edge_results.json", "w") as f:
        json.dump(json_data, f, indent=2, default=str)
    print("  Saved: data/manual/time_edge_results.json")

    print("\nTIME EDGE ANALYSIS COMPLETE")


if __name__ == "__main__":
    main()
