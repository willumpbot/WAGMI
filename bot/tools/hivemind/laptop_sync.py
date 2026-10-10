"""Hourly server -> laptop data sync, so the laptop never waits on a human (or on Claude being prompted) for data.

Copies the agreed exports into bot/data/laptop_mining/server_exports/, commits ONLY that directory and pushes the
server branch. The laptop pulls server_exports/ at the start of every session (DATA_REQUEST.md). Never includes
Telegram data (other people's messages). Skips quietly if git is busy (index.lock) or nothing changed.
"""
import shutil
import subprocess
import time
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
EXP = BOT / "data" / "laptop_mining" / "server_exports"
STAMP = EXP / ".last_sync"
EVERY_S = 3600
FILES = {
    "trade_ledger.csv": BOT / "data" / "trade_ledger.csv",
    "trades.csv": BOT / "data" / "trades.csv",
    "position_journal.jsonl": BOT / "data" / "position_journal.jsonl",
    "confidence_state.json": BOT / "data" / "feedback" / "confidence_state.json",
    "execution_analytics.csv": BOT / "data" / "execution_analytics.csv",
    "owner_plans.jsonl": BOT / "data" / "hivemind" / "owner_plans.jsonl",
    "owner_fills.jsonl": BOT / "data" / "hivemind" / "owner_fills.jsonl",
    "plans.json": BOT / "data" / "hivemind" / "plans.json",
    "ai_plans.json": BOT / "data" / "hivemind" / "ai_plans.json",
    "scan_grades.json": BOT / "data" / "hivemind" / "scan_grades.json",
    "scan_log.jsonl": BOT / "data" / "hivemind" / "scan_log.jsonl",
    "chief_calls.jsonl": BOT / "data" / "hivemind" / "chief_calls.jsonl",
    "chief_scorecard.json": BOT / "data" / "hivemind" / "chief_scorecard.json",
    "geometry_shadow.json": BOT / "data" / "hivemind" / "geometry_shadow.json",
    "geometry_shadow_results.jsonl": BOT / "data" / "hivemind" / "geometry_shadow_results.jsonl",
    "live_scorecard.json": BOT / "data" / "agent_grades" / "live" / "live_scorecard.json",
    "agent_grades_resolved.jsonl": BOT / "data" / "agent_grades" / "live" / "resolved.jsonl",
    "exit_decisions.jsonl": BOT / "data" / "logs" / "exit_decisions.jsonl",
    "llm_exits_resolved.jsonl": BOT / "data" / "llm_exits_resolved.jsonl",
    "position_manager.py": BOT / "execution" / "position_manager.py",
}


def _git(*args):
    return subprocess.run(["git", *args], cwd=BOT, capture_output=True, text=True, timeout=120)


def run(force=False):
    try:
        if not force and time.time() - float(STAMP.read_text()) < EVERY_S:
            return "not due"
    except (OSError, ValueError):
        pass
    if (BOT.parent / ".git" / "index.lock").exists():
        return "git busy"
    EXP.mkdir(parents=True, exist_ok=True)
    for name, src in FILES.items():
        if src.exists():
            shutil.copy2(src, EXP / name)
    STAMP.write_text(str(time.time()))
    rel = str(EXP.relative_to(BOT))
    _git("add", "-f", "--", rel)
    if not _git("diff", "--cached", "--quiet", "--", rel).returncode:
        return "no changes"
    c = _git("commit", "-m", "Hourly server exports for the laptop (auto)", "--", rel)
    if c.returncode:
        return "commit failed: " + c.stderr[-200:]
    p = _git("push", "-q", "origin", "HEAD")
    return "pushed" if not p.returncode else "push failed: " + p.stderr[-200:]


if __name__ == "__main__":
    import sys
    print(run(force="--force" in sys.argv))
