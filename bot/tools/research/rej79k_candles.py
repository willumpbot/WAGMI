"""Fetch and cache HL 1h candles for the rejection-window symbols (May 29 -> now)."""
import json, time, urllib.request, os
import datetime as dt

OUT = os.path.join(os.path.dirname(__file__), "rej79k_candles.json")
SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]


def fetch(coin, start_ms, end_ms):
    body = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms},
    }).encode()
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    start = int(dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = int(time.time() * 1000)
    out = {}
    for s in SYMS:
        rows = fetch(s, start, end)
        out[s] = [[int(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])] for r in rows]
        print(s, len(out[s]), "candles",
              out[s][0][0] if out[s] else None, "->", out[s][-1][0] if out[s] else None)
        time.sleep(0.5)
    json.dump(out, open(OUT, "w"))
    print("saved", OUT)


if __name__ == "__main__":
    main()
