"""Fetch 1h candles for the top-45 Hyperliquid perps by volume.

WHY: horizon_crossover.py showed a visible reversal->momentum crossover but could not
resolve it -- with 6 coins the cross-sectional rank runs 0-5, far too coarse, and the
detection floor at a 1-week horizon was 149 bps against a 136 bps effect. Widening the
cross-section is the direct fix and costs one API call per coin.

1h candleSnapshot returns up to 5000 bars = ~208 days, comfortably covering the 139-day
window the 6-coin panel used.
"""
import csv, io, json, os, time, urllib.request

OUT = "history1h"
COINS = json.load(io.open("universe_top45.json"))


def post(body, tries=4):
    for i in range(tries):
        try:
            rq = urllib.request.Request(
                "https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=45) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


end = int(time.time() * 1000)
start = end - 5000 * 3600 * 1000
ok = fail = 0
for c in COINS:
    try:
        rows = post({"type": "candleSnapshot",
                     "req": {"coin": c, "interval": "1h",
                             "startTime": start, "endTime": end}}) or []
    except Exception as e:
        print("FAIL %-10s %s" % (c, str(e)[:40]), flush=True)
        fail += 1
        continue
    if len(rows) < 500:
        print("SKIP %-10s only %d bars" % (c, len(rows)), flush=True)
        continue
    p = os.path.join(OUT, f"{c}_1h.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "o", "h", "l", "c", "v"])
        for k in sorted(rows, key=lambda x: int(x["t"])):
            w.writerow([int(k["t"]), k["o"], k["h"], k["l"], k["c"], k.get("v", 0)])
    ok += 1
    print("OK   %-10s %5d bars" % (c, len(rows)), flush=True)
    time.sleep(0.3)
print("DONE  %d fetched, %d failed" % (ok, fail))
