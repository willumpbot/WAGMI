"""Fetch Hyperliquid contract metadata + the extra symbols mission 9 needs.

meta        -> per-coin maxLeverage and szDecimals (drives the liquidation maths)
metaAndCtxs -> 24h volume per coin, used to pick the high-volume memes honestly
candles     -> 1d (2020+) and 4h (2024+) for NEAR and the top memes, so adverse
               excursion can be measured on an intraday path rather than closes
"""
import json, os, time, urllib.request, io, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
os.makedirs(HIST, exist_ok=True)
URL = "https://api.hyperliquid.xyz/info"


def post(body):
    for k in range(5):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception as ex:
            if k == 4:
                print(f"  FAILED {body.get('type')}: {ex}")
            time.sleep(2 + 3 * k)
    return None


meta = post({"type": "meta"})
universe = (meta or {}).get("universe", [])
print(f"universe: {len(universe)} perps")
lev = {}
for u in universe:
    try:
        lev[u["name"]] = {"maxLeverage": int(u.get("maxLeverage") or 0),
                          "szDecimals": u.get("szDecimals")}
    except Exception:
        pass

ctx = post({"type": "metaAndAssetCtxs"})
vols = {}
if isinstance(ctx, list) and len(ctx) == 2:
    names = [u["name"] for u in ctx[0].get("universe", [])]
    for name, c in zip(names, ctx[1]):
        try:
            vols[name] = float(c.get("dayNtlVlm") or 0)
        except (TypeError, ValueError):
            pass

with io.open(os.path.join(HERE, "hl_meta.json"), "w", encoding="utf-8") as fh:
    json.dump({"fetched": time.time(), "leverage": lev,
               "day_notional_volume": {k: round(v) for k, v in vols.items()}}, fh, indent=1)
print(f"wrote hl_meta.json  ({len(lev)} coins with leverage, {len(vols)} with volume)")

CORE = ["NEAR"]
MAJORS = {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"}
memes = [n for n, _ in sorted(vols.items(), key=lambda kv: -kv[1])
         if n not in MAJORS][:12]
print(f"top non-major perps by 24h volume: {memes[:12]}")

STEP = {"1d": 86_400_000, "4h": 14_400_000}
START = {"1d": int(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000),
         "4h": int(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)}
END = int(time.time() * 1000)


def candles(sym, iv):
    rows, cur, page = {}, START[iv], STEP[iv] * 4500
    while cur < END:
        d = post({"type": "candleSnapshot",
                  "req": {"coin": sym, "interval": iv, "startTime": cur,
                          "endTime": min(cur + page, END)}})
        for c in (d or []):
            rows[c["t"]] = (c["o"], c["h"], c["l"], c["c"], c["v"])
        cur += page
        time.sleep(0.35)
    return rows


want = CORE + memes[:6]
for sym in want:
    for iv in ("1d", "4h"):
        p = os.path.join(HIST, f"{sym}_{iv}.csv")
        if os.path.exists(p) and os.path.getsize(p) > 2000:
            print(f"  {sym} {iv} already cached")
            continue
        rows = candles(sym, iv)
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write("t_ms,o,h,l,c,v\n")
            for t in sorted(rows):
                fh.write(f"{t}," + ",".join(str(x) for x in rows[t]) + "\n")
        ks = sorted(rows)
        if ks:
            a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
            b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
            print(f"  {sym:<8} {iv:<3} {len(rows):>6} bars  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
        else:
            print(f"  {sym:<8} {iv:<3} EMPTY", flush=True)
print("done")
