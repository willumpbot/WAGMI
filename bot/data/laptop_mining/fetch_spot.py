"""Does a same-asset spot/perp basis trade exist on Hyperliquid, and for what?

FUNDING_CARRY.md ended with the one plausible direction-free edge in this project:
funding is 99.3% persistent and pays ~0.28%/day in the top bucket, but a
cross-asset hedge has 25-38x more noise than signal. A SAME-ASSET spot/perp hedge
has near-zero drift by construction -- if the spot market exists.

This establishes the facts that question needs:
  1 which assets have an HL spot market at all (spotMeta)
  2 their spot fees / decimals and the token pairing
  3 spot candles, so the actual BASIS (spot vs perp) can be measured through time

Writes spot_meta.json plus history/<SYM>_spot_1d.csv for the overlap set.
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


sm = post({"type": "spotMeta"})
if not sm:
    raise SystemExit("spotMeta unavailable")
tokens = {t["index"]: t for t in sm.get("tokens", [])}
pairs = sm.get("universe", [])
print(f"spot tokens: {len(tokens)}   spot pairs: {len(pairs)}")

# perp universe, to find the overlap
pm = post({"type": "meta"})
perps = {u["name"] for u in (pm or {}).get("universe", [])}
print(f"perps: {len(perps)}")

rows = []
for p in pairs:
    try:
        a, b = p["tokens"]
        base, quote = tokens.get(a, {}), tokens.get(b, {})
        bn, qn = base.get("name"), quote.get("name")
        rows.append({"pair_name": p.get("name"), "index": p.get("index"),
                     "base": bn, "quote": qn,
                     "base_has_perp": bn in perps,
                     "szDecimals": base.get("szDecimals"),
                     "weiDecimals": base.get("weiDecimals")})
    except Exception:
        continue

overlap = [r for r in rows if r["base_has_perp"] and r["quote"] == "USDC"]
print(f"\nspot pairs quoted in USDC whose base ALSO has a perp: {len(overlap)}")
for r in sorted(overlap, key=lambda x: str(x["base"])):
    print(f"  {str(r['base']):<10} pair {str(r['pair_name']):<14} index {r['index']}")

with io.open(os.path.join(HERE, "spot_meta.json"), "w", encoding="utf-8") as fh:
    json.dump({"fetched": time.time(), "n_tokens": len(tokens), "n_pairs": len(pairs),
               "n_perps": len(perps), "pairs": rows,
               "basis_candidates": [r["base"] for r in overlap]}, fh, indent=1)
print("\nwrote spot_meta.json")

if not overlap:
    print("\nNo same-asset spot/perp pair exists on Hyperliquid in USDC.")
    print("=> the basis trade CANNOT be run on HL alone; it would need spot held elsewhere.")
    raise SystemExit(0)

# spot candles use the pair's @index form as the coin
START = int(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
END = int(time.time() * 1000)
STEP = 86_400_000 * 4500
for r in overlap[:12]:
    coin = f"@{r['index']}"
    rowsd = {}
    cur = START
    while cur < END:
        d = post({"type": "candleSnapshot",
                  "req": {"coin": coin, "interval": "1d",
                          "startTime": cur, "endTime": min(cur + STEP, END)}})
        for c in (d or []):
            rowsd[c["t"]] = (c["o"], c["h"], c["l"], c["c"], c["v"])
        cur += STEP
        time.sleep(0.35)
    if not rowsd:
        print(f"  {r['base']:<10} spot candles EMPTY (coin {coin})")
        continue
    p = os.path.join(HIST, f"{r['base']}_spot_1d.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,o,h,l,c,v\n")
        for t in sorted(rowsd):
            fh.write(f"{t}," + ",".join(str(x) for x in rowsd[t]) + "\n")
    ks = sorted(rowsd)
    a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
    b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
    print(f"  {r['base']:<10} {len(rowsd):>5} spot days  {a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
print("done")
