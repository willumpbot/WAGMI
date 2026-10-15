"""Does everything tie together? (owner 10-15: "our system is incredibly vast so we have to consistently make sure
everything is tying together"). Hourly, cheap, read-only. For every filled owner plan: case file, sims row, dive
request (server side) and dive result (laptop side, S1/S2 standing orders); plus freshness of every live stream and
the laptop export. Writes data/hivemind/linkage.json (exported to the laptop) - 'gaps' is the to-do list.
"""
import json
import os
import time
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
LM = BOT / "data" / "laptop_mining"
FRESH = {"scan.json": 1800, "watch.json": 1800, "cases/index.json": 1800, "owner_plan_sims.json": 1800,
         "state/_all.json": 1800, "venue_funding.jsonl": 1800, "wallets/snapshots.jsonl": 5400, "depth_all.jsonl": 1800,
         "voice_log.jsonl": 1800, "whales_log.jsonl": 5400}


def _ids(path, key="plan_id"):
    out = set()
    try:
        for l in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(l).get(key))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def run():
    now = time.time()
    gaps, plans = [], json.loads((HM / "plans.json").read_text(encoding="utf-8")).get("plans", [])
    cases = {p.stem for p in (HM / "cases").glob("*.json")}
    sims = {s.get("plan_id") for s in json.loads((HM / "owner_plan_sims.json").read_text(encoding="utf-8")).get("sims", [])}
    dreq, dres = _ids(LM / "server_exports" / "dive_requests.jsonl"), _ids(LM / "dive_results.jsonl")
    filled = [p for p in plans if (p.get("result") or {}).get("filled_at") and p["result"].get("status") != "duplicate"]
    for p in filled:
        age_h = (now - float(p["result"]["filled_at"])) / 3600
        for name, ok, who in (("case file", p["id"] in cases, "server"), ("sim row", p["id"] in sims, "server"),
                              ("dive request", p["id"] in dreq, "server"),
                              ("dive result", p["id"] in dres or age_h < 3, "laptop")):
            if not ok:
                gaps.append({"plan_id": p["id"], "coin": p["coin"], "side": p["side"], "missing": name, "owner": who,
                             "status": p["result"].get("status"), "filled_h_ago": round(age_h, 1)})
    stale = []
    for f, mx in FRESH.items():
        try:
            a = now - os.path.getmtime(HM / f)
        except OSError:
            a = None
        if a is None or a > mx:
            stale.append({"file": f, "age_min": None if a is None else round(a / 60, 1), "max_min": mx // 60})
    try:
        exp_age = now - float((LM / "server_exports" / ".last_sync").read_text())
    except (OSError, ValueError):
        exp_age = None
    out = {"updated": now, "filled_plans": len(filled), "gaps": gaps, "stale": stale,
           "laptop_export_age_min": None if exp_age is None else round(exp_age / 60, 1),
           "ok": not gaps and not stale and (exp_age or 1e9) < 7200}
    (HM / "linkage.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    r = run()
    print("ok" if r["ok"] else f"{len(r['gaps'])} gaps, {len(r['stale'])} stale, export {r['laptop_export_age_min']} min")
    for g in r["gaps"]:
        print(" -", g)
