"""Mission 10 data: fundingHistory for the top perps by volume, full history.

fundingHistory returns <=500 rows per call, so page forward per coin. Hourly
funding over ~2 years is ~17k rows per coin, so this is the slow part of mission
10 and belongs in the background.

Cache -> history/<SYM>_funding.csv  (t_ms,rate), not committed.
"""
import json, os, time, urllib.request, io, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
os.makedirs(HIST, exist_ok=True)
URL = "https://api.hyperliquid.xyz/info"
START = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
END = int(time.time() * 1000)
TOP_N = 40


def post(body):
    for k in range(5):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception:
            time.sleep(2 + 3 * k)
    return None


meta = json.load(io.open(os.path.join(HERE, "hl_meta.json"), encoding="utf-8"))
vols = meta.get("day_notional_volume", {})
coins = [c for c, _ in sorted(vols.items(), key=lambda kv: -kv[1])][:TOP_N]
print(f"top {len(coins)} perps by 24h volume: {coins}")


def funding(sym):
    rows, cur, stall = {}, START, 0
    while cur < END and stall < 3:
        d = post({"type": "fundingHistory", "coin": sym, "startTime": cur, "endTime": END})
        if not d:
            stall += 1
            continue
        before, last = len(rows), cur
        for r in d:
            try:
                t = int(r["time"])
                rows[t] = float(r["fundingRate"])
                last = max(last, t)
            except (KeyError, TypeError, ValueError):
                pass
        if len(rows) == before or last <= cur:
            stall += 1
            if last <= cur:
                break
        else:
            stall = 0
        cur = last + 1
        time.sleep(0.25)
    return rows


for i, sym in enumerate(coins, 1):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if os.path.exists(p) and os.path.getsize(p) > 50_000:
        print(f"  [{i}/{len(coins)}] {sym} cached")
        continue
    f = funding(sym)
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,rate\n")
        for t in sorted(f):
            fh.write(f"{t},{f[t]}\n")
    ks = sorted(f)
    if ks:
        a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
        b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
        print(f"  [{i}/{len(coins)}] {sym:<8} {len(f):>6} rows  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
    else:
        print(f"  [{i}/{len(coins)}] {sym:<8} EMPTY", flush=True)
print("done")
