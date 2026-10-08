"""Mission 14 data: wrapped spot markets, depth, volume and spot candles.

My first screen (fetch_spot.py) matched spot BASE names against the perp universe
and so concluded BTC/ETH/SOL have no HL spot market. That was wrong: HL lists them
as WRAPPED tokens -- UBTC, UETH, USOL, UAVAX, UENA, UWLD, UZEC, UPUMP, UMON -- so
the name never matched. This builds the correct mapping and pulls what mission 14
asks for:

  * spotMetaAndAssetCtxs -> spot 24h volume and mid per pair
  * l2Book per spot pair -> depth within 0.5% and 1% (the capacity limit)
  * candleSnapshot        -> spot 1d history for the basis series
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
                print(f"    FAILED {body.get('type')} {body.get('coin','')}: {ex}")
            time.sleep(2 + 3 * k)
    return None


# ---- wrapped-name mapping: spot token -> perp name ----
def perp_for(base):
    b = str(base).upper()
    if b in ("HYPE", "PURR", "TRUMP", "BERA", "AZTEC", "STABLE", "MON", "PUMP"):
        return b
    if b.startswith("U") and len(b) > 2:
        cand = b[1:]
        aliases = {"FART": "FARTCOIN", "PHL": "HYPE", "ANSEM": None, "DZ": None,
                   "MEGA": None, "SPYX": None, "UUSPX": None, "VIRT": "VIRTUAL"}
        return aliases.get(cand, cand)
    return None


sm = post({"type": "spotMeta"})
pm = post({"type": "meta"})
if not sm or not pm:
    raise SystemExit("meta unavailable")
tokens = {t["index"]: t for t in sm.get("tokens", [])}
perps = {u["name"]: u for u in pm.get("universe", [])}

ctxs = post({"type": "spotMetaAndAssetCtxs"})
vol, mid = {}, {}
if isinstance(ctxs, list) and len(ctxs) == 2:
    names = [u.get("name") for u in ctxs[0].get("universe", [])]
    for nm, c in zip(names, ctxs[1]):
        try:
            vol[nm] = float(c.get("dayNtlVlm") or 0)
            mid[nm] = float(c.get("midPx") or 0) if c.get("midPx") else None
        except (TypeError, ValueError):
            pass

cands = []
for p in sm.get("universe", []):
    try:
        a, b = p["tokens"]
    except Exception:
        continue
    base, quote = tokens.get(a, {}), tokens.get(b, {})
    bn, qn = base.get("name"), quote.get("name")
    if qn not in ("USDC",):
        continue
    pn = perp_for(bn)
    if not pn or pn not in perps:
        continue
    cands.append({"spot_token": bn, "perp": pn, "pair": p.get("name"),
                  "index": p.get("index"), "szDecimals": base.get("szDecimals"),
                  "spot_24h_vol": round(vol.get(p.get("name"), 0.0)),
                  "spot_mid": mid.get(p.get("name")),
                  "perp_max_leverage": perps[pn].get("maxLeverage")})

cands.sort(key=lambda x: -x["spot_24h_vol"])
print("=" * 104)
print("SPOT/PERP PAIRS (wrapped names resolved)")
print("=" * 104)
print(f"  {'spot':<10}{'perp':<10}{'pair':<12}{'spot 24h vol':>16}{'maxLev':>8}")
print("-" * 104)
for c in cands:
    print(f"  {str(c['spot_token']):<10}{c['perp']:<10}{str(c['pair']):<12}"
          f"${c['spot_24h_vol']/1e6:>14.2f}M{str(c['perp_max_leverage']):>8}")

# ---- depth within 0.5% and 1% from the real book ----
print("\n" + "=" * 104)
print("SPOT BOOK DEPTH (capacity limit)")
print("=" * 104)
print(f"  {'spot':<10}{'mid':>12}{'bid 0.5%':>13}{'ask 0.5%':>13}{'bid 1%':>13}{'ask 1%':>13}")
print("-" * 104)
for c in cands:
    bk = post({"type": "l2Book", "coin": c["pair"]})
    time.sleep(0.25)
    if not bk or "levels" not in bk or len(bk["levels"]) < 2:
        c["depth"] = None
        print(f"  {str(c['spot_token']):<10}{'no book':>12}")
        continue
    bids, asks = bk["levels"][0], bk["levels"][1]
    try:
        best_bid = float(bids[0]["px"]); best_ask = float(asks[0]["px"])
    except (IndexError, KeyError, TypeError, ValueError):
        c["depth"] = None
        continue
    m = (best_bid + best_ask) / 2
    def side_depth(levels, lo, hi):
        tot = 0.0
        for lv in levels:
            try:
                px, sz = float(lv["px"]), float(lv["sz"])
            except (KeyError, TypeError, ValueError):
                continue
            if lo <= px <= hi:
                tot += px * sz
        return tot
    d = {"mid": m,
         "bid_0p5": side_depth(bids, m * 0.995, m),
         "ask_0p5": side_depth(asks, m, m * 1.005),
         "bid_1p0": side_depth(bids, m * 0.99, m),
         "ask_1p0": side_depth(asks, m, m * 1.01),
         "spread_bps": (best_ask - best_bid) / m * 1e4}
    c["depth"] = {k: (round(v, 6) if k == "mid" else round(v)) for k, v in d.items()}
    print(f"  {str(c['spot_token']):<10}{m:>12.4f}${d['bid_0p5']/1e3:>11.0f}k"
          f"${d['ask_0p5']/1e3:>11.0f}k${d['bid_1p0']/1e3:>11.0f}k${d['ask_1p0']/1e3:>11.0f}k")

with io.open(os.path.join(HERE, "basis_pairs.json"), "w", encoding="utf-8") as fh:
    json.dump({"fetched": time.time(), "pairs": cands}, fh, indent=1)
print("\nwrote basis_pairs.json")

# ---- spot candles for the basis series ----
START = int(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).timestamp() * 1000)
END = int(time.time() * 1000)
STEP = 86_400_000 * 4500
print("\n" + "=" * 104)
print("SPOT 1d CANDLES")
print("=" * 104)
for c in cands:
    coin = f"@{c['index']}" if c["pair"].startswith("@") else c["pair"]
    rows, cur = {}, START
    while cur < END:
        d = post({"type": "candleSnapshot",
                  "req": {"coin": coin, "interval": "1d",
                          "startTime": cur, "endTime": min(cur + STEP, END)}})
        for x in (d or []):
            rows[x["t"]] = (x["o"], x["h"], x["l"], x["c"], x["v"])
        cur += STEP
        time.sleep(0.3)
    if not rows:
        print(f"  {c['spot_token']:<10} EMPTY ({coin})")
        continue
    p = os.path.join(HIST, f"{c['perp']}_wspot_1d.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,o,h,l,c,v\n")
        for t in sorted(rows):
            fh.write(f"{t}," + ",".join(str(x) for x in rows[t]) + "\n")
    ks = sorted(rows)
    a = datetime.datetime.fromtimestamp(ks[0] / 1000, datetime.UTC)
    b = datetime.datetime.fromtimestamp(ks[-1] / 1000, datetime.UTC)
    print(f"  {c['spot_token']:<10} -> {c['perp']:<10} {len(rows):>5} days  "
          f"{a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
print("done")
