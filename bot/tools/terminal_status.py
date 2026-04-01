"""
Terminal Status — Quick overview of all terminal outputs.

Run: cd bot && python -m tools.terminal_status
"""

import os
from datetime import datetime, timezone


def check_file(path, label):
    """Check if file exists and show its modification time."""
    if os.path.exists(path):
        mtime = os.path.getmtime(path)
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        size = os.path.getsize(path)
        return f"  {label}: {size/1024:.1f}KB, updated {dt.strftime('%H:%M UTC')}"
    return f"  {label}: NOT FOUND"


def main():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"  TERMINAL STATUS — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # Terminal 1: Bot + Babysit
    print("Terminal 1: Bot + Babysit")
    print(check_file("data/logs/signal_outcomes.jsonl", "Signal outcomes"))
    print(check_file("data/logs/state_transitions.csv", "State transitions"))
    print(check_file("data/logs/risk_rejections.csv", "Risk rejections"))
    if os.path.exists("data/logs/signal_outcomes.jsonl"):
        with open("data/logs/signal_outcomes.jsonl") as f:
            lines = f.readlines()
        print(f"  Total signals logged: {len(lines)}")

    # Terminal 3: Backtesting
    print("\nTerminal 3: Backtesting")
    print(check_file("data/ALPHA_RESEARCH.md", "Alpha Research"))

    # Terminal 4: Integration (this terminal)
    print("\nTerminal 4: Integration")
    print(check_file("data/INTEGRATION_LOG.md", "Integration Log"))
    print(check_file("data/manual/PENDING_RESTART.md", "Pending Restart"))

    # Terminal 5: System Hardening
    print("\nTerminal 5: System Hardening")
    print(check_file("data/manual/CODE_AUDIT.md", "Code Audit"))
    print(check_file("data/manual/HARDENING_REPORT.md", "Hardening Report"))
    print(check_file("data/manual/GO_LIVE_CHECKLIST.md", "Go-Live Checklist"))
    print(check_file("data/BUGS_FOUND.md", "Bugs Found"))

    # Quant Research outputs
    print("\nQuant Research")
    print(check_file("data/manual/OVERNIGHT_SUMMARY.md", "Overnight Summary"))
    print(check_file("data/manual/FILTER_VALIDATION.md", "Filter Validation"))
    print(check_file("data/manual/DIP_BUY_ANALYSIS.md", "Dip-Buy Analysis"))
    print(check_file("data/manual/RISK_OPTIMIZATION.md", "Risk Optimization"))
    print(check_file("data/manual/EDGE_DISCOVERY.md", "Edge Discovery"))
    print(check_file("data/manual/TIME_EDGE_ANALYSIS.md", "Time Edge"))
    print(check_file("data/manual/MORNING_BRIEFING.md", "Morning Briefing"))

    # Tests
    print(f"\n{'='*60}")
    print("  Run: cd bot && python -m pytest tests/ -q")
    print("  Run: cd bot && python -m manual.executive_dashboard")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
