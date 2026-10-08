"""Top-trader positioning: a NEW data source (forward-only), because direction from price history is closed.

Daily: pick ~60 Hyperliquid accounts from the public leaderboard that have made money over time
(all-time PnL > $1M, positive month, account > $1M) and are NOT market makers (monthly volume under 200x
account value; market-maker inventory is noise for this purpose).
Every cycle: read each account's open positions (public clearinghouseState), and aggregate per coin:
net notional long minus short, gross, and how many traders are long vs short.
The result becomes a hivemind voice ("Top traders' net position"), logged every cycle and graded forward
like every other voice. It starts with no track record and must earn trust.
Read-only public data; writes data/hivemind/whales_*.json(l).
"""
import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
HM = BOT / "data" / "hivemind"
LIST = HM / "whales_list.json"
LATEST = HM / "whales_latest.json"
LOG = HM / "whales_log.jsonl"
N = 60


def _leaderboard():
    with urllib.request.urlopen("https://stats-data.hyperliquid.xyz/Mainnet/leaderboard", timeout=40) as r:
        return json.loads(r.read())["leaderboardRows"]


def refresh_list(force=False):
    if not force and LIST.exists() and time.time() - LIST.stat().st_mtime < 20 * 3600:
        return json.loads(LIST.read_text(encoding="utf-8"))
    rows = _leaderboard()
    picked = []
    for r in rows:
        w = {k: v for k, v in r.get("windowPerformances", [])}
        try:
            av = float(r["accountValue"])
            at, mo = float(w["allTime"]["pnl"]), float(w["month"]["pnl"])
            mvol = float(w["month"]["vlm"])
        except Exception:
            continue
        # 0.5x-200x monthly turnover: excludes market makers (high) and vaults/idle treasuries (near zero,
        # e.g. the protocol's own liquidity vault, whose positions are inventory, not opinions)
        if at > 1e6 and mo > 0 and av > 1e6 and 0.5 * av < mvol < 200 * av:
            picked.append({"addr": r["ethAddress"], "account": round(av), "pnl_all": round(at), "pnl_month": round(mo),
                           "vol_month_x": round(mvol / av, 1)})
    picked.sort(key=lambda x: -x["pnl_all"])
    out = {"built": datetime.now(timezone.utc).isoformat(timespec="minutes"), "criteria":
           "allTime pnl > $1M, month pnl > 0, account > $1M, monthly volume 0.5x-200x account (excludes market makers and vaults)",
           "traders": picked[:N]}
    LIST.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def snapshot():
    import hl
    lst = refresh_list()
    per = defaultdict(lambda: {"net": 0.0, "gross": 0.0, "long": 0, "short": 0})
    ok = 0
    for t in lst["traders"]:
        try:
            st = hl.post({"type": "clearinghouseState", "user": t["addr"]}, ttl=600)
        except Exception:
            continue
        ok += 1
        for ap in st.get("assetPositions", []):
            p = ap.get("position") or {}
            szi, val = float(p.get("szi") or 0), abs(float(p.get("positionValue") or 0))
            if not szi or not val:
                continue
            c = per[p["coin"]]
            c["net"] += val if szi > 0 else -val
            c["gross"] += val
            c["long" if szi > 0 else "short"] += 1
    now = time.time()
    coins = {k: {**v, "net": round(v["net"]), "gross": round(v["gross"]),
                 "net_share": round(v["net"] / v["gross"], 3) if v["gross"] else 0} for k, v in per.items()}
    out = {"ts": now, "updated": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="minutes"),
           "traders_read": ok, "traders_listed": len(lst["traders"]), "coins": coins}
    LATEST.write_text(json.dumps(out), encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(now), "coins": {k: [v["net"], v["gross"], v["long"], v["short"]]
                                                         for k, v in coins.items() if v["gross"] > 50_000}}) + "\n")
    return out


if __name__ == "__main__":
    s = snapshot()
    print(s["traders_read"], "traders read")
    for c in ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]:
        print(c, s["coins"].get(c))
