"""RQ18: Golden-era archaeology.

Reconstructs the conditions of the two claimed profitable stretches:
  (A) the "+$1,756 metadata-poor big-short era" (unknown_no_metadata bucket)
  (B) June 1-6 2026 (+$1,537, 62% WR)
from bot/data/trades.csv + bot/data/trade_ledger.csv + HL candleSnapshot
(price ground truth), plus the pre-April-23 archive ledger.

Read-only on bot data. Writes only a candle cache json next to this script.
Outputs analysis to stdout (consumed into coordination/RQ18_GOLDEN_ERA.md).
"""
import csv, json, math, random, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\vince\WAGMI")
TRADES = ROOT / "bot/data/trades.csv"
LEDGER = ROOT / "bot/data/trade_ledger.csv"
OLD = ROOT / "historical/old-bot-pre-2026-04-23/trades.csv"
CACHE = Path(__file__).with_name("rq18_candles.json")
SYMS = ["BTC", "ETH", "SOL", "HYPE"]

# ---------- candles (full OHLC, 1h) ----------
def fetch_hl(coin, start_ms, end_ms):
    body = json.dumps({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def load_candles():
    if CACHE.exists():
        raw = json.loads(CACHE.read_text())
        return {k: [(int(c[0]), c[1], c[2], c[3], c[4]) for c in v] for k, v in raw.items()}
    out = {}
    # HL API caps ~5000 candles per req; fetch in 2 windows to cover Mar 20 - Jul 2
    windows = [(datetime(2026, 3, 20, tzinfo=timezone.utc), datetime(2026, 5, 15, tzinfo=timezone.utc)),
               (datetime(2026, 5, 15, tzinfo=timezone.utc), datetime(2026, 7, 2, tzinfo=timezone.utc))]
    for s in SYMS:
        rows = []
        for a, b in windows:
            rows += fetch_hl(s, int(a.timestamp()*1000), int(b.timestamp()*1000))
            time.sleep(0.4)
        seen, cds = set(), []
        for r in rows:
            t = int(r["t"])
            if t in seen: continue
            seen.add(t)
            cds.append((t, float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])))
        cds.sort()
        out[s] = cds
        print(f"{s}: {len(cds)} 1h candles", file=sys.stderr)
    CACHE.write_text(json.dumps({k: [[c[0], c[1], c[2], c[3], c[4]] for c in v] for k, v in out.items()}))
    return out

# ---------- indicators on 4h aggregation ----------
def to_4h(c1h):
    out = []
    bucket = defaultdict(list)
    for t, o, h, l, c in c1h:
        bucket[t // (4*3600*1000) * (4*3600*1000)].append((t, o, h, l, c))
    for k in sorted(bucket):
        cs = sorted(bucket[k])
        out.append((k, cs[0][1], max(x[2] for x in cs), min(x[3] for x in cs), cs[-1][4]))
    return out

def ema(vals, n):
    k = 2 / (n + 1)
    e = [vals[0]]
    for v in vals[1:]:
        e.append(e[-1] + k * (v - e[-1]))
    return e

def adx14(c4h):
    """Wilder ADX(14) on 4h candles. Returns list aligned to c4h (None until warm)."""
    n = 14
    trs, pdms, ndms = [], [], []
    for i in range(1, len(c4h)):
        _, o, h, l, c = c4h[i]
        ph, pl, pc = c4h[i-1][2], c4h[i-1][3], c4h[i-1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdms.append(up if (up > dn and up > 0) else 0.0)
        ndms.append(dn if (dn > up and dn > 0) else 0.0)
    if len(trs) < n * 2: return [None] * len(c4h)
    atr, pdi_s, ndi_s = sum(trs[:n]), sum(pdms[:n]), sum(ndms[:n])
    dxs, adx_out = [], [None] * (n + 1)
    for i in range(n, len(trs)):
        atr = atr - atr / n + trs[i]
        pdi_s = pdi_s - pdi_s / n + pdms[i]
        ndi_s = ndi_s - ndi_s / n + ndms[i]
        pdi = 100 * pdi_s / atr if atr else 0
        ndi = 100 * ndi_s / atr if atr else 0
        dx = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0
        dxs.append((dx, pdi, ndi))
        if len(dxs) == n:
            adx = sum(d[0] for d in dxs) / n
        elif len(dxs) > n:
            adx = (adx * (n - 1) + dx) / n
        else:
            adx_out.append(None); continue
        adx_out.append((adx, pdi, ndi))
    while len(adx_out) < len(c4h): adx_out.append(None)
    return adx_out

def regime_at(c4h, adx, emas20, emas50, ts_ms):
    """Live-detectable regime snapshot at ts_ms (uses only candles closed before ts)."""
    idx = None
    for i, c in enumerate(c4h):
        if c[0] + 4*3600*1000 <= ts_ms: idx = i
        else: break
    if idx is None or adx[idx] is None: return None
    a, pdi, ndi = adx[idx]
    close = c4h[idx][4]
    return {"adx": a, "bear_di": ndi > pdi, "below_ema20": close < emas20[idx],
            "below_ema50": close < emas50[idx],
            "trending_bear": a > 25 and ndi > pdi and close < emas50[idx]}

# ---------- realized vol / trend per day ----------
def daily_stats(c1h):
    days = defaultdict(list)
    for t, o, h, l, c in c1h:
        d = datetime.fromtimestamp(t/1000, tz=timezone.utc).date()
        days[d].append((t, o, h, l, c))
    out = {}
    for d in sorted(days):
        cs = sorted(days[d])
        rets = [math.log(cs[i][4]/cs[i-1][4]) for i in range(1, len(cs))]
        rv = (sum(r*r for r in rets) / max(len(rets), 1)) ** 0.5 * math.sqrt(24) * 100
        out[d] = {"ret": (cs[-1][4]/cs[0][1] - 1) * 100, "rv_daily_pct": rv,
                  "close": cs[-1][4]}
    return out

def main():
    random.seed(42)
    candles = load_candles()
    c4h = {s: to_4h(candles[s]) for s in SYMS}
    adx = {s: adx14(c4h[s]) for s in SYMS}
    e20 = {s: ema([c[4] for c in c4h[s]], 20) for s in SYMS}
    e50 = {s: ema([c[4] for c in c4h[s]], 50) for s in SYMS}

    # ---- current ledger ----
    rows = list(csv.DictReader(open(TRADES, encoding="utf-8")))
    for r in rows:
        r["pnl"] = float(r["pnl"]); r["dt"] = datetime.fromisoformat(r["timestamp"])
    led = list(csv.DictReader(open(LEDGER, encoding="utf-8")))
    # join hold_hours by (symbol, close-timestamp within 120s)
    for r in rows:
        r["hold_h"] = None
        for l in led:
            if l["symbol"] == r["symbol"] and abs(float(l["timestamp"]) - r["dt"].timestamp()) < 120:
                r["hold_h"] = float(l["hold_hours"]); r["exit_type"] = l["exit_type"]
                r["running_eq"] = float(l["running_equity"]); break

    cut = datetime(2026, 6, 7, tzinfo=timezone.utc)
    era_a = [r for r in rows if r["dt"] < cut]                   # Jun 1-6
    era_b = [r for r in rows if r["dt"] >= cut]
    no_meta = [r for r in rows if not r["entry_reasons"].strip() or r["entry_reasons"].strip() in ("{}",)]

    def stats(tr, name):
        if not tr: return
        w = [r for r in tr if r["pnl"] > 0]
        pnl = sum(r["pnl"] for r in tr)
        days = max((max(r["dt"] for r in tr) - min(r["dt"] for r in tr)).total_seconds()/86400, 0.01)
        holds = [r["hold_h"] for r in tr if r.get("hold_h") is not None]
        sides = defaultdict(lambda: [0, 0.0])
        for r in tr:
            sides[r["side"]][0] += 1; sides[r["side"]][1] += r["pnl"]
        hrs = defaultdict(int)
        for r in tr: hrs[r["dt"].hour] += 1
        print(f"\n== {name}: n={len(tr)} WR={len(w)/len(tr)*100:.1f}% pnl=${pnl:+.2f} "
              f"rate={len(tr)/days:.2f}/day medhold={sorted(holds)[len(holds)//2] if holds else '?'}h")
        for s, (n, p) in sides.items(): print(f"   {s}: n={n} ${p:+.2f}")
        sym = defaultdict(lambda: [0, 0.0])
        for r in tr: sym[r["symbol"]][0] += 1; sym[r["symbol"]][1] += r["pnl"]
        print("   symbols:", {k: (v[0], round(v[1], 2)) for k, v in sym.items()})
        print("   entry hours UTC:", dict(sorted(hrs.items())))
        print("   leverage:", sorted(set(r["leverage"] for r in tr)))

    stats(era_a, "ERA Jun1-6")
    stats(era_b, "ERA Jun7+")
    stats(no_meta, "unknown_no_metadata bucket")
    print("\nOverlap: no_meta trades inside Jun1-6:",
          sum(1 for r in no_meta if r["dt"] < cut),
          " pnl:", round(sum(r["pnl"] for r in no_meta if r["dt"] < cut), 2))
    print("no_meta trades Jun7+:", sum(1 for r in no_meta if r["dt"] >= cut),
          " pnl:", round(sum(r["pnl"] for r in no_meta if r["dt"] >= cut), 2))

    # per-trade table Jun1-6 with live-detectable regime at entry
    print("\n-- Jun1-6 per-trade (entry-time 4h regime, live-detectable) --")
    for r in era_a:
        ent_ms = int((r["dt"] - timedelta(hours=r["hold_h"] or 0)).timestamp() * 1000)
        rg = regime_at(c4h[r["symbol"]], adx[r["symbol"]], e20[r["symbol"]], e50[r["symbol"]], ent_ms)
        rgs = (f"ADX={rg['adx']:.0f} bearDI={rg['bear_di']} <EMA50={rg['below_ema50']} "
               f"TRENDBEAR={rg['trending_bear']}") if rg else "n/a"
        print(f"  {r['dt']:%m-%d %H:%M} {r['symbol']:4s} {r['side']:5s} pnl={r['pnl']:+9.2f} "
              f"hold={r['hold_h'] if r['hold_h'] is not None else '?':>5}h lev={r['leverage']:>4s} "
              f"exit={r.get('exit_type','?'):8s} | {rgs}")

    # same regime check for Jun7+ trades: was trending_bear present?
    tb_a = tb_b = na = nb = 0
    for r in era_a:
        if r["symbol"] not in c4h: continue
        ent_ms = int((r["dt"] - timedelta(hours=r["hold_h"] or 0)).timestamp() * 1000)
        rg = regime_at(c4h[r["symbol"]], adx[r["symbol"]], e20[r["symbol"]], e50[r["symbol"]], ent_ms)
        if rg: na += 1; tb_a += rg["trending_bear"]
    for r in era_b:
        if r["symbol"] not in c4h: continue
        ent_ms = int((r["dt"] - timedelta(hours=r["hold_h"] or 0)).timestamp() * 1000)
        rg = regime_at(c4h[r["symbol"]], adx[r["symbol"]], e20[r["symbol"]], e50[r["symbol"]], ent_ms)
        if rg: nb += 1; tb_b += rg["trending_bear"]
    print(f"\ntrending_bear at entry: Jun1-6 {tb_a}/{na}  Jun7+ {tb_b}/{nb}")

    # SHORT-in-trending_bear PnL split across whole ledger
    buckets = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        if r["symbol"] not in c4h: continue
        ent_ms = int((r["dt"] - timedelta(hours=r["hold_h"] or 0)).timestamp() * 1000)
        rg = regime_at(c4h[r["symbol"]], adx[r["symbol"]], e20[r["symbol"]], e50[r["symbol"]], ent_ms)
        if not rg: continue
        era = "Jun1-6" if r["dt"] < cut else "Jun7+"
        key = (r["side"], "TB" if rg["trending_bear"] else "notTB")
        b = buckets[key]; b[0] += 1; b[1] += r["pnl"] > 0; b[2] += r["pnl"]
        b2 = buckets[(era,) + key]; b2[0] += 1; b2[1] += r["pnl"] > 0; b2[2] += r["pnl"]
    print("\n-- side x trending_bear (all 92 closes) --")
    for k in sorted(buckets):
        n, w, p = buckets[k]
        print(f"  {k}: n={n} WR={w/n*100:.0f}% ${p:+.2f}")

    # ---- market regime per day (BTC/ETH/SOL) ----
    print("\n-- daily market stats (ret%, realized vol %/day) --")
    ds = {s: daily_stats(candles[s]) for s in ["BTC", "ETH", "SOL"]}
    for d in sorted(ds["BTC"]):
        if datetime(2026, 5, 28).date() <= d <= datetime(2026, 6, 16).date():
            line = f"  {d}: "
            for s in ["BTC", "ETH", "SOL"]:
                st = ds[s].get(d)
                line += f"{s} {st['ret']:+5.2f}% rv{st['rv_daily_pct']:4.1f}  " if st else f"{s} --  "
            print(line)
    # cumulative moves
    for s in ["BTC", "ETH", "SOL"]:
        def px(mo, dy):
            d = datetime(2026, mo, dy).date()
            return ds[s][d]["close"] if d in ds[s] else None
        p0, p1, p2 = px(6, 1), px(6, 6), px(6, 16)
        if p0 and p1 and p2:
            print(f"  {s}: Jun1 close {p0:.2f} -> Jun6 {p1:.2f} ({(p1/p0-1)*100:+.1f}%) -> Jun16 {p2:.2f} ({(p2/p1-1)*100:+.1f}%)")

    # ---- passive-short beta baseline ----
    # bot equity Jun 1 ~ $4,812 pre-first-close ledger shows start ~5,000
    eq0 = 5000.0
    for s in ["BTC", "ETH", "SOL"]:
        d0, d1 = datetime(2026, 6, 1).date(), datetime(2026, 6, 6).date()
        if d0 in ds[s] and d1 in ds[s]:
            r = ds[s][d1]["close"]/ds[s][d0]["close"] - 1
            print(f"  passive SHORT {s} 2x, Jun1->Jun6 close-close, on ${eq0:.0f}: ${-r*2*eq0:+.2f}")

    # ---- luck analysis ----
    pnls = [r["pnl"] for r in era_a]
    wins = sum(1 for p in pnls if p > 0)
    # binomial P(>= wins | p=0.5)
    n = len(pnls)
    pbin = sum(math.comb(n, k) for k in range(wins, n + 1)) / 2**n
    print(f"\n-- luck: Jun1-6 n={n} wins={wins} P(>=w|p=.5)={pbin:.3f}")
    # sign-flip Monte Carlo on |pnl| magnitudes
    tgt = sum(pnls)
    hits = 0; TR = 200_000
    mags = [abs(p) for p in pnls]
    for _ in range(TR):
        s = sum(m if random.random() < 0.5 else -m for m in mags)
        if s >= tgt: hits += 1
    print(f"   sign-flip MC: P(sum >= {tgt:+.0f}) = {hits/TR:.4f}  ({hits}/{TR})")
    # fragility
    srt = sorted(pnls, reverse=True)
    print(f"   remove best 1: ${tgt - srt[0]:+.2f}; remove best 2: ${tgt - srt[0] - srt[1]:+.2f}; "
          f"remove best 3: ${tgt - sum(srt[:3]):+.2f}")
    # trade-shuffle era test: probability a random 13-trade contiguous window of the 92 has >= tgt
    allp = [r["pnl"] for r in rows]
    wins_windows = sum(1 for i in range(len(allp) - n + 1) if sum(allp[i:i+n]) >= tgt)
    print(f"   contiguous 13-trade windows >= +{tgt:.0f}: {wins_windows}/{len(allp)-n+1}")

    # ---- old-bot archive ----
    orows = list(csv.DictReader(open(OLD, encoding="utf-8")))
    op = [float(r["pnl"]) for r in orows]
    cum, best, bi, bj = 0.0, -1e9, 0, 0
    # max-subarray (Kadane) for best stretch
    cur, ci = 0.0, 0
    for i, v in enumerate(op):
        cur += v
        if cur > best: best, bi, bj = cur, ci, i
        if cur < 0: cur, ci = 0.0, i + 1
    print(f"\n-- old-bot archive (Mar25-May11): n={len(op)} total ${sum(op):+.2f}")
    print(f"   best contiguous stretch: rows {bi+1}-{bj+1} ${best:+.2f} "
          f"({orows[bi]['timestamp'][:10]} -> {orows[bj]['timestamp'][:10]})")
    seg = orows[bi:bj+1]
    sh = [r for r in seg if r["side"] == "SHORT"]
    print(f"   stretch sides: SHORT {len(sh)}/{len(seg)}, short pnl ${sum(float(r['pnl']) for r in sh):+.2f}")
    w = sum(1 for r in seg if float(r["pnl"]) > 0)
    print(f"   stretch WR {w}/{len(seg)}")
    # old-bot per-month
    bym = defaultdict(lambda: [0, 0.0])
    for r in orows:
        m = r["timestamp"][:7]; bym[m][0] += 1; bym[m][1] += float(r["pnl"])
    print("   by month:", {k: (v[0], round(v[1], 2)) for k, v in sorted(bym.items())})

if __name__ == "__main__":
    main()
