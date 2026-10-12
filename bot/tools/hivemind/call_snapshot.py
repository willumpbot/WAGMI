"""Snapshot each fresh Syndicate call's PUBLIC on-chain state as close to the call as we can (laptop Mission Y, tier 1).

GeckoTerminal serves liquidity / FDV / holders / txn counts as of NOW, so they can never be backfilled to call time -
using today's values in a study is look-ahead. Capturing them live is what makes "winners vs duds at call time"
answerable at all. For every call in track.json younger than MAX_AGE_S without a snapshot: the call's pool
(pool_created_at, reserve, fdv, mcap, price change m5..h24, buys/sells/buyers/sellers m5..h24, volume) and the
token's holder count/distribution. snap_lag_s records how long after the call it was taken (the cycle is 15 min).
Writes data/hivemind/tg/call_snapshots.jsonl (ca-keyed, public fields only - no caller, no message text).
"""
import json
import time
from pathlib import Path

import tg_track

HERE = Path(__file__).resolve().parent
TG = HERE.parents[1] / "data" / "hivemind" / "tg"
OUT = TG / "call_snapshots.jsonl"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
MAX_AGE_S = 3 * 3600      # still informative for a slow cycle; snap_lag_s says how stale it is
PER_RUN = 6               # GeckoTerminal free tier is shared with tg_track and the microcap collector


def run():
    try:
        calls = json.loads((TG / "track.json").read_text(encoding="utf-8")).get("calls") or {}
    except Exception:
        return 0
    try:
        done = {json.loads(l)["ca"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    except OSError:
        done = set()
    now, n = time.time(), 0
    for c in sorted(calls.values(), key=lambda c: -c["call_ts"]):
        if n >= PER_RUN:
            break
        ca = c.get("ca")
        if not ca or ca in done or now - c["call_ts"] > MAX_AGE_S:
            continue
        pool = c.get("gt_pool")
        if not pool:
            got = tg_track._gt(f"{GT}/tokens/{ca}/pools?page=1") or {}
            pools = got.get("data") or []
            pools.sort(key=lambda p: -float((p.get("attributes") or {}).get("reserve_in_usd") or 0))
            pool = pools[0]["attributes"]["address"] if pools else None
        row = {"ca": ca, "call_ts": c["call_ts"], "snap_ts": now, "snap_lag_s": round(now - c["call_ts"]), "pool": pool}
        if pool:
            a = ((tg_track._gt(f"{GT}/pools/{pool}") or {}).get("data") or {}).get("attributes") or {}
            if not a:   # rate-limited (GeckoTerminal answers 429 as JSON, not an error): retry next cycle
                continue
            for k in ("pool_created_at", "reserve_in_usd", "fdv_usd", "market_cap_usd", "base_token_price_usd",
                      "price_change_percentage", "transactions", "volume_usd"):
                row[k] = a.get(k)
        info = ((tg_track._gt(f"{GT}/tokens/{ca}/info") or {}).get("data") or {}).get("attributes") or {}
        row["holders"] = info.get("holders")
        row["gt_score"] = info.get("gt_score")
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + chr(10))
        done.add(ca)
        n += 1
    return n


if __name__ == "__main__":
    print(run(), "snapshots")
