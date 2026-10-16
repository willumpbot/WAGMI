"""Broad wallet miner (owner 10-15: "60 wallets is probably too little ... something we would want to extensively data
mine"). Runs hourly in its OWN detached process (launched by run_cycle), never inside the 15-min cycle.

Cohort (rebuilt daily from the public HL leaderboard, ~47k rows):
  skilled   up to 1,000 accounts: all-time PnL > $100k, account > $100k, monthly volume 0.5x-200x account
            (excludes market makers and vaults), ranked by all-time PnL
  control   200 accounts drawn at random (fixed daily seed) from the REST of the leaderboard with account > $25k -
            the comparison group: without it nobody can tell skill from "big wallets look smart in hindsight"
Snapshot (hourly): every cohort wallet's open perp positions via public clearinghouseState, one row per position:
  {ts, addr, cohort, coin, szi, entry, value, upnl, lev, liq, acct}
Positions worth >= $5k only (wallets hold ~26 positions each; dust is noise and volume). Appended to
data/hivemind/wallets/positions.jsonl (sharded daily to the laptop by laptop_sync STREAMS) + cohort_YYYY-MM-DD.json.
Public read-only data; paced well under HL's info rate limit. The existing 60-wallet voice (whales.py) is untouched.
"""
import json
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = BOT / "data" / "hivemind" / "wallets"
N_SKILLED, N_CONTROL = 1000, 200
MIN_VALUE = 5_000
PACE_S = 0.25           # ~4 requests/s; clearinghouseState weight 2 -> ~480 weight/min, under the 1200/min limit
LOCK = OUT / ".miner.lock"


def _day(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")


FROZEN = OUT / "cohort_frozen.json"   # laptop 195: the forward study needs the SAME wallets every hour


def cohort():
    if FROZEN.exists():
        return json.loads(FROZEN.read_text(encoding="utf-8"))
    day = _day()
    path = OUT / f"cohort_{day}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    with urllib.request.urlopen("https://stats-data.hyperliquid.xyz/Mainnet/leaderboard", timeout=90) as r:
        rows = json.loads(r.read())["leaderboardRows"]
    skilled, rest = [], []
    for r in rows:
        w = {k: v for k, v in r.get("windowPerformances", [])}
        try:
            av = float(r["accountValue"])
            at = float(w["allTime"]["pnl"])
            mvol = float(w["month"]["vlm"])
            mo = float(w["month"]["pnl"])
        except Exception:
            continue
        rec = {"addr": r["ethAddress"], "acct": round(av), "pnl_all": round(at), "pnl_month": round(mo),
               "vol_month_x": round(mvol / av, 1) if av else None}
        if at > 1e5 and av > 1e5 and 0.5 * av < mvol < 200 * av:
            skilled.append(rec)
        elif av > 25_000:
            rest.append(rec)
    skilled.sort(key=lambda x: -x["pnl_all"])
    skilled = skilled[:N_SKILLED]
    rng = random.Random(day)
    control = rng.sample(rest, min(N_CONTROL, len(rest)))
    out = {"day": day, "built": time.time(), "n_leaderboard": len(rows),
           "criteria": {"skilled": "allTime pnl > $100k, account > $100k, monthly volume 0.5x-200x account; top 1000 by allTime pnl",
                        "control": "random 200 (seed = date) of the rest with account > $25k"},
           "wallets": [dict(x, cohort="skilled") for x in skilled] + [dict(x, cohort="control") for x in control]}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def snapshot():
    import hl
    OUT.mkdir(parents=True, exist_ok=True)
    c = cohort()
    ts = round(time.time())
    rows, accts, ok, fail = [], [], 0, 0
    for w in c["wallets"]:
        try:
            st = hl.post({"type": "clearinghouseState", "user": w["addr"]}, ttl=1800)
            ok += 1
        except Exception:
            fail += 1
            time.sleep(PACE_S * 4)
            continue
        acct = float((st.get("marginSummary") or {}).get("accountValue") or 0)
        accts.append({"ts": ts, "addr": w["addr"], "cohort": w["cohort"], "acct": round(acct, 2),
                      "ntl": round(float((st.get("marginSummary") or {}).get("totalNtlPos") or 0), 2),
                      "withdrawable": round(float(st.get("withdrawable") or 0), 2)})
        for ap in st.get("assetPositions", []):
            p = ap.get("position") or {}
            szi = float(p.get("szi") or 0)
            if not szi or abs(float(p.get("positionValue") or 0)) < MIN_VALUE:
                continue
            lev = p.get("leverage") or {}
            rows.append({"ts": ts, "addr": w["addr"], "cohort": w["cohort"], "coin": p.get("coin"), "szi": szi,
                         "entry": float(p.get("entryPx") or 0), "value": abs(float(p.get("positionValue") or 0)),
                         "upnl": float(p.get("unrealizedPnl") or 0), "lev": lev.get("value"),
                         "liq": float(p["liquidationPx"]) if p.get("liquidationPx") else None, "acct": round(acct)})
        time.sleep(PACE_S)
    with open(OUT / "positions.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(OUT / "accounts.jsonl", "a", encoding="utf-8") as f:   # every wallet, every hour (realised P&L base)
        for r in accts:
            f.write(json.dumps(r) + chr(10))
    with open(OUT / "snapshots.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "wallets_read": ok, "failed": fail, "positions": len(rows),
                            "cohort_day": c["day"]}) + "\n")
    return {"ts": ts, "read": ok, "failed": fail, "positions": len(rows)}


def due(every_s=3600):
    try:
        last = json.loads((OUT / "snapshots.jsonl").read_text(encoding="utf-8").splitlines()[-1])["ts"]
    except Exception:
        return True
    return time.time() - last >= every_s


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        print(snapshot())
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass
