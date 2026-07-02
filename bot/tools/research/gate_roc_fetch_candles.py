"""Fetch HL 15m candles for gate-ROC study (Jun 1 - Jul 2 2026). Cache to JSON."""
import json, time, urllib.request

SYMS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
START = 1780300800000  # 2026-05-31 16:00 UTC (buffer before Jun 1 17:28)
END   = 1783036800000  # 2026-07-02 16:00 UTC (buffer after Jul 1 23:12 + 24h horizon)
OUT = r"C:\Users\vince\WAGMI\bot\tools\research\gate_roc_candles_15m.json"

def fetch(coin, start, end):
    body = json.dumps({"type": "candleSnapshot", "req": {"coin": coin, "interval": "15m", "startTime": start, "endTime": end}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

out = {}
for s in SYMS:
    candles = []
    cur = START
    while cur < END:
        chunk = fetch(s, cur, END)
        if not chunk:
            break
        candles.extend(chunk)
        last_t = chunk[-1]["t"]
        if last_t <= cur:
            break
        cur = last_t + 1
        if len(chunk) < 500:
            break
        time.sleep(0.3)
    # dedupe by t
    seen = {}
    for c in candles:
        seen[c["t"]] = c
    ordered = [seen[t] for t in sorted(seen)]
    out[s] = [[c["t"], float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])] for c in ordered]
    print(s, len(out[s]), "candles", ordered[0]["t"], "->", ordered[-1]["t"])
    time.sleep(0.5)

json.dump(out, open(OUT, "w"))
print("saved", OUT)
