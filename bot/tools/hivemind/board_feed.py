"""Live feed for the owner's Nunu Command Board (the laptop renders the board; the server supplies the facts).

Owner (10-13): the board is where he oversees an "all context machine". So the board must never be hand-maintained:
every 15-min cycle this writes data/hivemind/board_feed.json with
  health       - bot alive / can trade, Telegram listener heartbeat, last laptop sync, open bot positions
  owner_queue  - decisions waiting for him + what's in flight + "what you can do" (data/hivemind/owner_queue.json,
                 kept by server Claude)
  trades       - counts and the latest few trades (his plans, bot, skipped Claude ideas)
  ideas        - Claude's open trade ideas
  findings     - the latest milestones (what we learned, with kind: proven/refuted/open/fixed/built)
  calls        - Syndicate calls tracked in the last 24h (counts only - no names, no message text)
Exported to the laptop by laptop_sync. Never trades anything.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[1]
HM = BOT / "data" / "hivemind"
OUT = HM / "board_feed.json"


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _last_line(p):
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            return json.loads(f.read().decode("utf-8", "replace").strip().splitlines()[-1])
    except Exception:
        return {}


def run():
    now = time.time()
    up = _last_line(HM / "uptime.jsonl")
    hb = _load(HM / "tg" / "listener_heartbeat.json", {})
    try:
        sync = float((BOT / "data" / "laptop_mining" / "server_exports" / ".last_sync").read_text().strip())
    except Exception:
        sync = None
    plans = _load(HM / "plans.json", {}).get("plans", [])
    ai = _load(HM / "ai_plans.json", {})
    used = {p.get("source_idea_id") for p in plans if p.get("source_idea_id")}
    track = _load(HM / "tg" / "track.json", {}).get("calls", {})
    calls24 = [c for c in track.values() if now - c.get("call_ts", 0) < 86400]
    feed = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "health": {
            "bot_alive": up.get("alive"), "bot_can_trade": up.get("can_trade"), "bot_llm_ok": up.get("llm_ok"),
            "bot_heartbeat_age_s": up.get("hb_age_s"),
            "telegram_listener_last_msg_min": round((now - hb["last_msg"]) / 60) if hb.get("last_msg") else None,
            "telegram_listener_heartbeat_age_s": round(now - hb["now"]) if hb.get("now") else None,
            "laptop_sync_age_min": round((now - sync) / 60) if sync else None,
        },
        "owner_queue": _load(HM / "owner_queue.json", {}),
        "trades": {
            "my_plans": [{"coin": p["coin"], "side": p["side"], "status": (p.get("result") or {}).get("status"),
                          "r": (p.get("result") or {}).get("r"), "bot_ran": (p.get("exec_result") or {}).get("status"),
                          "bot_pnl_usd": (p.get("exec_result") or {}).get("pnl_usd"), "ts": p.get("ts")}
                         for p in plans[-8:]],
        },
        "ideas": [{"id": i["id"], "coin": i["coin"], "side": i["side"], "entry": i["entry"], "stop": i["stop"],
                   "target": i["target"], "status": (i.get("result") or {}).get("status"),
                   "taken": i["id"] in used, "why": i.get("reason", "")[:200], "ts": i["ts"]}
                  for i in ai.get("ideas", [])[-6:]],
        "ideas_stats": ai.get("stats", {}),
        "findings": _load(HERE / "milestones.json", [])[-12:],
        "calls_24h": {"n": len(calls24), "ran_1_5x": sum(1 for c in calls24 if (c.get("x_peak") or 0) >= 1.5)},
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(feed, default=str), encoding="utf-8")
    tmp.replace(OUT)
    return feed


if __name__ == "__main__":
    f = run()
    print(json.dumps(f["health"]), len(f["ideas"]), "ideas,", len(f["findings"]), "findings")
