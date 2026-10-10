"""Paginated 5m candle fetch for the exit-engine port (Mission D).

The live exit engine re-evaluates on a ~3-minute scan. 1h bars cannot represent
that: a trail stop and a target inside the same hour get resolved by convention,
and convention is exactly what silently chose the answer in the refuted
trailing study. 5m is the finest interval with usable depth from the API.

Hyperliquid caps candleSnapshot at 5000 bars, so walk the window forward.
"""
import json, time, csv, io, os, sys
import urllib.request

SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]
START = 1780272000000   # 2026-06-01 approx, in ms
END   = 1791590400000   # 2026-10-10
STEP  = 5000 * 5 * 60 * 1000   # 5000 bars of 5m
OUT   = "history5m"

def post(body, tries=4):
    for i in range(tries):
        try:
            rq = urllib.request.Request(
                "https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(rq, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

for sym in SYMS:
    rows = {}
    t = START
    while t < END:
        end = min(t + STEP, END)
        c = post({"type": "candleSnapshot",
                  "req": {"coin": sym, "interval": "5m",
                          "startTime": t, "endTime": end}})
        if not c:
            t = end
            continue
        for k in c:
            rows[int(k["t"])] = (k["o"], k["h"], k["l"], k["c"], k["v"])
        last = max(int(k["t"]) for k in c)
        # advance past the last bar received; guard against a stalled cursor
        t = max(last + 300000, t + 300000)
        time.sleep(0.35)
        print("  %-5s %6d bars, cursor %s" % (sym, len(rows), t), flush=True)
    path = os.path.join(OUT, "%s_5m_full.csv" % sym)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "o", "h", "l", "c", "v"])
        for k in sorted(rows):
            w.writerow([k] + list(rows[k]))
    print("WROTE %s  %d bars" % (path, len(rows)), flush=True)
print("DONE")
