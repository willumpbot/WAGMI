"""The setup's history, for the terminal's History tab: milestones + curves of everything we grade.

Curves (cumulative, by day): bot paper P&L (trades.csv), Claude trade ideas (R), the owner's plans (R), and Claude's
Syndicate verdicts (hit rate). Plus commits per day from git (how hard we worked) and the curated milestones in
tools/hivemind/milestones.json (proven / refuted / fixed / built / open). Writes data/hivemind/history.json.
"""
import csv
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[1]
HM = BOT / "data" / "hivemind"


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _cum(points):
    """points: [(date_str, value)] -> [[date, cumulative]] by day."""
    by = defaultdict(float)
    for d, v in points:
        by[d] += v
    out, run = [], 0.0
    for d in sorted(by):
        run += by[d]
        out.append([d, round(run, 3)])
    return out


def build():
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        rows = list(csv.DictReader(open(BOT / "data" / "trades.csv", encoding="utf-8")))
        pts = []
        for r in rows:
            try:
                pts.append((r["timestamp"][:10], float(r.get("pnl") or 0)))
            except (KeyError, ValueError):
                pass
        out["bot_pnl"] = _cum([p for p in pts if p[0] >= "2026-07-24"])   # after the leverage fix: honest numbers only
    except Exception:
        out["bot_pnl"] = []
    ai = _load(HM / "ai_plans.json", {}).get("ideas", [])
    out["ai_r"] = _cum([(datetime.fromtimestamp(i["result"].get("closed_at") or i["ts"], timezone.utc).strftime("%Y-%m-%d"),
                         i["result"]["r"]) for i in ai if (i.get("result") or {}).get("r") is not None])
    pl = _load(HM / "plans.json", {}).get("plans", [])
    out["owner_r"] = _cum([(datetime.fromtimestamp(p["result"].get("closed_at") or p["ts"], timezone.utc).strftime("%Y-%m-%d"),
                            p["result"]["r"]) for p in pl if (p.get("result") or {}).get("r") is not None])
    try:
        log = subprocess.run(["git", "log", "--since=2026-05-01", "--format=%ad", "--date=short"], cwd=BOT,
                             capture_output=True, text=True, timeout=30).stdout.split()
        by = defaultdict(int)
        for d in log:
            by[d] += 1
        out["commits"] = sorted(by.items())
    except Exception:
        out["commits"] = []
    out["milestones"] = _load(HERE / "milestones.json", [])
    out["lessons"] = _load(HERE / "lessons.json", {})
    tmp = (HM / "history.json").with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(HM / "history.json")
    return out


if __name__ == "__main__":
    o = build()
    print(len(o["bot_pnl"]), "bot days;", len(o["commits"]), "commit days;", len(o["milestones"]), "milestones")
    print(o["bot_pnl"][-3:], o["commits"][-5:])
