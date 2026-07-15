#!/usr/bin/env python
"""WAGMI weekly research auto-rerun (LLM-FREE, quota-safe).

Runs the confound-safe, no-LLM research scripts on a weekly cadence and writes a
dated markdown report to bot/data/reports/. Both protocols (coordination/
TABLE_B_NEWSTREAMS.md, coordination/RQ14_CF_MODEL.md) mandate a weekly rerun as
data accrues; this automates it with ZERO Claude/LLM calls, so it never competes
with the trading bot for the shared subscription quota.

Registered as Task Scheduler job WAGMI-WeeklyResearch.
Revert: schtasks /delete /tn WAGMI-WeeklyResearch /f   (and delete this file).

Add analyses by appending to ANALYSES below. Each runs in its own subprocess with
a timeout; one failure never blocks the others. Everything is read-only — no
script here touches trade state, positions, or the bot process.
"""
import os
import sys
import subprocess
import datetime

# bot/tools/research/weekly_research.py -> ROOT=bot/, REPO=WAGMI/
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(ROOT)
PY = sys.executable
REPORTS = os.path.join(ROOT, "data", "reports")

# (name, argv, one-line description). All must be LLM-FREE + read-only.
ANALYSES = [
    (
        "lane_b_newstream_ic",
        [PY, os.path.join(ROOT, "tools", "research", "lane_b_newstream_ic.py")],
        "Depth-stream IC scan (confound-safe: inv_mid + spread_dollar controls). "
        "A feature only 'graduates' if its IC beats inv_mid AND its price-removed "
        "form (spread_dollar) is non-zero — see the 2026-07-13 spread_bps refutation.",
    ),
    (
        "rq14_cf_model",
        [PY, os.path.join(ROOT, "tools", "research", "rq14_cf_model.py")],
        "Counterfactual TP1 predictability: confidence-only vs logistic/GBM AUC "
        "(is the confidence floor better than a coin flip? RQ14 says ~no).",
    ),
    (
        "data_integrity_report",
        [PY, os.path.join(ROOT, "tools", "data_integrity_report.py")],
        "Counterfactual/trade-store contamination + disk trend (dupe/test/unparsable "
        "rows, trades-vs-ledger delta, disk free). Numbers only — resolver fixes stay "
        "on the owner queue (RESOLVER_AUDIT_2026-07-13.md).",
    ),
]


def run_one(cmd, timeout_s=600):
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout_s)
        out = r.stdout or ""
        if r.returncode != 0:
            out += f"\n[nonzero exit {r.returncode}]\n" + (r.stderr or "")[-2000:]
        return out.strip() or "[no output]"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {timeout_s}s]"
    except Exception as e:  # never let one analysis abort the run
        return f"[ERROR: {e}]"


def main():
    os.makedirs(REPORTS, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    path = os.path.join(REPORTS, f"weekly_research_{now.strftime('%Y%m%d')}.md")
    lines = [
        f"# WAGMI weekly research — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "LLM-free auto-rerun (WAGMI-WeeklyResearch). No Claude/quota used. Read-only.",
        "",
    ]
    for name, cmd, desc in ANALYSES:
        lines += [f"## {name}", "", desc, "", "```", run_one(cmd), "```", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[weekly_research] wrote {path}")


if __name__ == "__main__":
    main()
