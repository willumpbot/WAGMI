"""Acquisition track: 15m and 5m candles, to settle the swarm's top criticism.

The reviewer's strongest point against GEOMETRY.md was that 1h bars CANNOT resolve
whether the stop or the target was hit first inside a bar -- so the conservative
tie rule ("a bar covering both counts as a stop") is an assumption doing real work,
not a measurement.

Hyperliquid only serves 15m from ~2026-08-16 and 5m from ~2026-09-20, so the
Feb-Jun corpus can never be validated intrabar. But the SERVER's live signals
(Sep 1 - Oct 8, the window geometry_shadow.py already covers) sit inside that
range. So this fetch makes an honest intrabar check possible on the one dataset
where the data exists.

Throttled deliberately: a single serialized worker, 0.45s between calls. Running
several of these in parallel would just share the same rate limit and finish no
faster -- today's two concurrent jobs used 4.6 CPU-seconds between them while
blocking on the API for minutes.

Writes history/<SYM>_<iv>.csv. Resumable: skips any file already larger than 50KB.
"""
import json, os, time, urllib.request, io, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history")
os.makedirs(OUT, exist_ok=True)
URL = "https://api.hyperliquid.xyz/info"

SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]
# (interval, start, bar_ms) -- starts chosen from what HL actually serves
JOBS = [("15m", datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC), 900_000),
        ("5m", datetime.datetime(2026, 9, 15, tzinfo=datetime.UTC), 300_000)]
PAUSE = 0.45


def post(body, tries=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception as e:
            if k == tries - 1:
                print(f"      FAILED: {e}", flush=True)
            time.sleep(2 + 3 * k)
    return None


END = int(time.time() * 1000)
for iv, start_dt, bar in JOBS:
    start = int(start_dt.timestamp() * 1000)
    page = bar * 4500
    print(f"=== {iv} from {start_dt:%Y-%m-%d} ===", flush=True)
    for sym in SYMS:
        p = os.path.join(OUT, f"{sym}_{iv}.csv")
        if os.path.exists(p) and os.path.getsize(p) > 50_000:
            print(f"  {sym:<6} {iv:<4} cached", flush=True)
            continue
        rows, cur = {}, start
        while cur < END:
            d = post({"type": "candleSnapshot",
                      "req": {"coin": sym, "interval": iv,
                              "startTime": cur, "endTime": min(cur + page, END)}})
            for c in (d or []):
                try:
                    rows[c["t"]] = (c["o"], c["h"], c["l"], c["c"], c["v"])
                except (KeyError, TypeError):
                    pass
            cur += page
            time.sleep(PAUSE)
        if not rows:
            print(f"  {sym:<6} {iv:<4} EMPTY", flush=True)
            continue
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write("t_ms,o,h,l,c,v\n")
            for t in sorted(rows):
                fh.write(f"{t}," + ",".join(str(x) for x in rows[t]) + "\n")
        ks = sorted(rows)
        a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
        b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
        print(f"  {sym:<6} {iv:<4} {len(rows):>6} bars  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
print("acquisition done", flush=True)
