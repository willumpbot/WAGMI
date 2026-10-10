"""AI trade ideas: twice a day Opus proposes up to 2 complete swing trades, graded exactly like the owner's plans.

Why: the owner often has no read of his own. Instead of a blank planner he gets concrete, risk-sized ideas he can
adopt or pass on, and every idea is graded forward (plans.py::_walk: HL 5m candles, stop-first ties, adverse-side
fill-candle rule, 48h window, 9 bps fees, R units). Ideas live in data/hivemind/ai_plans.jsonl, separate from the
owner's record; adopting one in the terminal copies it into his plans (setup "ai idea").
Never trades anything itself.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plans  # noqa: E402

BOT = HERE.parents[1]
HM = BOT / "data" / "hivemind"
IDEAS = HM / "ai_plans.jsonl"
OUT = HM / "ai_plans.json"
EVERY_H = 11.5

SYSTEM = """You are the WAGMI desk's trade-idea generator for a discretionary swing trader on Hyperliquid perps
(1-2 day holds). He often has no read of his own, so you propose up to TWO complete trades he could take, or NONE if
nothing is worth it (none is a perfectly good answer). Every idea is graded forward on real prices, so be honest.
Facts from forward grading: no single voice or AI has proven directional skill; move SIZE is forecastable (each coin's
vol/risk blocks); stops tighter than a normal day's move lose ~0.13-0.20R/trade; no target size or time limit tested
better than another; liquidation clusters may be mildly visited by price (+3-8 pts vs random, unproven) and are a bad
place for a stop; the 20-day low breaks more than chance. So: stop OUTSIDE one expected daily move and not sitting on a
liquidation cluster, target at a real level, leverage within the coin's safe leverage, prefer limit entries at a level
over chasing. Use only coins present in the input. Plain words for a visual learner.
Output ONLY JSON:
{"ideas": [{"coin": "SOL", "side": "LONG|SHORT", "entry_type": "limit|market", "entry": <num>, "stop": <num>,
  "target": <num>, "leverage": <num>, "confidence": 1-5, "setup": "<=30 chars",
  "why": "<=220 chars, one plain sentence first", "invalidation": "<=100 chars"}],
 "note": "<=160 chars: why these, or why none"}"""


def _rows():
    try:
        return [json.loads(l) for l in IDEAS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def _prompt():
    import chief
    st = json.loads((HM / "state" / "_all.json").read_text(encoding="utf-8"))
    hive = json.loads(chief._compact(st))
    try:
        scan = json.loads((HM / "scan.json").read_text(encoding="utf-8"))
        keep = ("coin", "px", "chg_24h", "ret_7d", "exp_move", "trend_up", "d50_pct", "hi20", "lo20", "range_pos",
                "funding_h", "vol_ratio", "safe_lev_long", "safe_lev_short", "flags")
        scan_rows = [{k: r.get(k) for k in keep} for r in scan.get("coins", [])[:25]]
    except Exception:
        scan_rows = []
    return json.dumps({"hivemind_majors": hive, "scanner_top25": scan_rows}, default=str)[:90000]


def generate(force=False):
    rows = _rows()
    last = max((r["ts"] for r in rows if r.get("kind") == "run"), default=0)
    if not force and time.time() - last < EVERY_H * 3600:
        return None
    sys.path.insert(0, str(BOT))
    from llm.claude_cli_client import call_agent
    import hl
    resp = call_agent(user_prompt=_prompt(), system_prompt=SYSTEM, model="opus",
                      max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=600, allow_tools=False)
    now = time.time()
    run = {"kind": "run", "ts": now, "ok": bool(resp.ok)}
    out = []
    if resp.ok:
        raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
        try:
            got = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except ValueError:
            got = {"ideas": []}
        run["note"] = str(got.get("note") or "")[:200]
        mids = hl.post({"type": "allMids"}, ttl=30)
        for i in (got.get("ideas") or [])[:2]:
            try:
                coin, side = str(i["coin"]).upper(), str(i["side"]).upper()
                entry, stop, target = float(i["entry"]), float(i["stop"]), float(i["target"])
                px = float(mids[coin])
            except (KeyError, TypeError, ValueError):
                continue
            etype = "market" if i.get("entry_type") == "market" else "limit"
            if etype == "market":
                entry = px
            sg = 1 if side == "LONG" else -1
            if side not in ("LONG", "SHORT") or sg * (entry - stop) <= 0 or sg * (target - entry) <= 0:
                continue
            out.append({"kind": "plan", "source": "ai", "id": "ai" + uuid.uuid4().hex[:8], "ts": now, "coin": coin,
                        "side": side, "entry": entry, "stop": stop, "target": target, "price_at_plan": px,
                        "entry_type": etype, "entry_window_h": 24.0, "max_hold_h": 48.0,
                        "leverage": float(i.get("leverage") or 1), "confidence": int(i.get("confidence") or 1),
                        "setup": str(i.get("setup") or "")[:40], "reason": str(i.get("why") or "")[:260],
                        "invalidation": str(i.get("invalidation") or "")[:120]})
    else:
        run["error"] = str(resp.error)[:200]
    run["n"] = len(out)
    with open(IDEAS, "a", encoding="utf-8") as f:
        for r in out + [run]:
            f.write(json.dumps(r) + "\n")
    return run


def resolve():
    import hl
    rows = _rows()
    try:
        prev = {p["id"]: p for p in json.loads(OUT.read_text(encoding="utf-8")).get("ideas", [])}
    except Exception:
        prev = {}
    now, ideas = time.time(), []
    for pl in (r for r in rows if r.get("kind") == "plan"):
        old = (prev.get(pl["id"]) or {}).get("result") or {}
        if old.get("status") in ("won", "lost", "timed out", "expired"):
            res = old
        else:
            try:
                res = plans._walk(pl, hl.candles(pl["coin"], "5m", pl["ts"] * 1000 - 300000, ttl=50) or [], now)
            except Exception as e:
                res = dict(old or {"status": "waiting"}, error=str(e)[:100])
        ideas.append(dict(pl, result=res))
    done = [x["result"]["r"] for x in ideas if "r" in x["result"]]
    stats = {"n": len(done)}
    if done:
        stats.update(win_rate=round(sum(r > 0 for r in done) / len(done), 3), avg_r=round(sum(done) / len(done), 3),
                     total_r=round(sum(done), 2))
    runs = [r for r in rows if r.get("kind") == "run"]
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ideas": ideas, "stats": stats,
           "last_note": (runs[-1].get("note") if runs else None), "last_run": (runs[-1]["ts"] if runs else None)}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


def run():
    try:
        generate()
    finally:
        return resolve()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(generate(force="--force" in sys.argv))
    o = resolve()
    print(o["stats"], o["last_note"])
    for i in o["ideas"][-4:]:
        print(i["coin"], i["side"], i["entry_type"], i["entry"], i["stop"], i["target"], i["confidence"], i["result"], "|", i["reason"])
