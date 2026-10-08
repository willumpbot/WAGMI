"""Fetch the long history mission 5/6 need: daily + 4h candles and funding.

Hyperliquid's candleSnapshot caps a response at ~5000 bars, so page backwards.
Daily from 2020 is ~2,400 bars (one page); 4h from 2024 is ~4,400 (one page);
fundingHistory returns <=500 rows per call so it is paged forward.

Cache -> bot/data/laptop_mining/history/<SYM>_<iv>.csv  and  <SYM>_funding.csv
Not committed (raw dumps stay local).
"""
import json, os, time, urllib.request, csv, io, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history")
os.makedirs(OUT, exist_ok=True)

SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "AVAX", "LINK", "ARB", "SUI"]
URL = "https://api.hyperliquid.xyz/info"


def post(body):
    for k in range(5):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception as ex:
            if k == 4:
                print(f"    FAILED: {ex}", flush=True)
            time.sleep(2 + k * 3)
    return None


def candles(sym, iv, start_ms, end_ms):
    rows = {}
    step = {"1d": 86400_000, "4h": 14400_000}[iv] * 4500
    cur = start_ms
    while cur < end_ms:
        d = post({"type": "candleSnapshot",
                  "req": {"coin": sym, "interval": iv,
                          "startTime": cur, "endTime": min(cur + step, end_ms)}})
        for c in (d or []):
            rows[c["t"]] = (c["o"], c["h"], c["l"], c["c"], c["v"])
        cur += step
        time.sleep(0.35)
    return rows


def funding(sym, start_ms, end_ms):
    rows = {}
    cur = start_ms
    stall = 0
    while cur < end_ms and stall < 3:
        d = post({"type": "fundingHistory", "coin": sym,
                  "startTime": cur, "endTime": end_ms})
        if not d:
            stall += 1
            time.sleep(1)
            continue
        before = len(rows)
        last = cur
        for r in d:
            try:
                rows[int(r["time"])] = float(r["fundingRate"])
                last = max(last, int(r["time"]))
            except (KeyError, TypeError, ValueError):
                pass
        if len(rows) == before:
            stall += 1
        else:
            stall = 0
        if last <= cur:
            break
        cur = last + 1
        time.sleep(0.3)
    return rows


START_D = int(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
START_4H = int(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
START_F = int(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
END = int(time.time() * 1000)


def write_candles(sym, iv, rows):
    p = os.path.join(OUT, f"{sym}_{iv}.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,o,h,l,c,v\n")
        for t in sorted(rows):
            fh.write(f"{t}," + ",".join(str(x) for x in rows[t]) + "\n")
    ks = sorted(rows)
    if ks:
        a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
        b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
        print(f"  {sym:<6} {iv:<3} {len(rows):>6} bars  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
    else:
        print(f"  {sym:<6} {iv:<3} EMPTY", flush=True)


print("=== daily candles (2020+) ===", flush=True)
for s in SYMS:
    write_candles(s, "1d", candles(s, "1d", START_D, END))

print("=== 4h candles (2024+) ===", flush=True)
for s in SYMS:
    write_candles(s, "4h", candles(s, "4h", START_4H, END))

print("=== funding history (2024+) ===", flush=True)
for s in SYMS:
    f = funding(s, START_F, END)
    p = os.path.join(OUT, f"{s}_funding.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,rate\n")
        for t in sorted(f):
            fh.write(f"{t},{f[t]}\n")
    ks = sorted(f)
    if ks:
        a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
        b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
        print(f"  {s:<6} funding {len(f):>6} rows  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
    else:
        print(f"  {s:<6} funding EMPTY", flush=True)

print("done", flush=True)
