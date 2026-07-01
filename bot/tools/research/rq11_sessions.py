"""RQ11: Session structure — dollar performance by UTC session across trades + counterfactuals,
plus volatility/trend structure by session from exchange candles.
Ground truth: trade_ledger.csv (156 closed trades, superset of trades.csv), counterfactual_resolved.jsonl,
Binance 1h klines (Hyperliquid history too shallow for multi-month).
Output: printed tables consumed into coordination/RQ11_SESSIONS.md
"""
import csv, json, statistics, datetime, urllib.request, time
from collections import defaultdict

ROOT = r"C:\Users\vince\WAGMI\bot"
UTC = datetime.timezone.utc
SESSIONS = [("Asia_00-06", 0, 6), ("EU_06-12", 6, 12), ("US_12-18", 12, 18), ("Late_18-24", 18, 24)]

def sess(h):
    for name, a, b in SESSIONS:
        if a <= h < b:
            return name

# ---------- 1. REAL TRADES (trade_ledger.csv; timestamp=close, entry=close-hold) ----------
led = list(csv.DictReader(open(ROOT + r"\data\trade_ledger.csv", encoding="utf-8")))
trades = []
for r in led:
    try:
        close_ts = float(r["timestamp"]); hold = float(r["hold_hours"] or 0)
        pnl = float(r["net_pnl"]); entry = float(r["entry_price"]); ex = float(r["exit_price"])
    except Exception:
        continue
    ent_dt = datetime.datetime.fromtimestamp(close_ts - hold * 3600, UTC)
    move = abs(ex - entry) / entry if entry else 0
    gross = float(r["gross_pnl"]) if r["gross_pnl"] else 0.0
    notional = abs(gross) / move if move > 1e-6 else None
    trades.append(dict(dt=ent_dt, hour=ent_dt.hour, sess=sess(ent_dt.hour), pnl=pnl,
                       sym=r["symbol"], side=r["side"], notional=notional,
                       era="E1_Jun01-15" if ent_dt < datetime.datetime(2026, 6, 16, tzinfo=UTC) else "E2_Jun16-Jul01"))

nots = [t["notional"] for t in trades if t["notional"] and 50 < t["notional"] < 1e6]
MED_NOT = statistics.median(nots)
print(f"trades n={len(trades)} total=${sum(t['pnl'] for t in trades):.2f} median_notional=${MED_NOT:.0f}")

def table(rows, keyf, valf):
    agg = defaultdict(list)
    for r in rows:
        agg[keyf(r)].append(valf(r))
    out = {}
    for k, v in sorted(agg.items()):
        s = sorted(v)
        out[k] = dict(n=len(v), total=sum(v), mean=statistics.mean(v),
                      wr=sum(1 for x in v if x > 0) / len(v),
                      frag=sum(v) - max(v))  # remove single best observation
    return out

print("\n== REAL TRADES by session (dollars, net) ==")
for era in ["ALL", "E1_Jun01-15", "E2_Jun16-Jul01"]:
    sub = trades if era == "ALL" else [t for t in trades if t["era"] == era]
    t = table(sub, lambda r: r["sess"], lambda r: r["pnl"])
    for k, v in t.items():
        print(f"{era:14s} {k:11s} n={v['n']:3d} wr={v['wr']:.2f} total=${v['total']:8.2f} mean=${v['mean']:7.2f} frag(-best)=${v['frag']:8.2f}")

print("\n== REAL TRADES by 3h block (ALL) ==")
t = table(trades, lambda r: f"{(r['hour']//3)*3:02d}-{(r['hour']//3)*3+3:02d}", lambda r: r["pnl"])
for k, v in t.items():
    print(f"{k} n={v['n']:3d} wr={v['wr']:.2f} total=${v['total']:8.2f} frag=${v['frag']:8.2f}")

# ---------- 2. COUNTERFACTUALS (dedup raw scans -> episodes) ----------
recs = []
with open(ROOT + r"\data\llm\counterfactual_resolved.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("resolved") or r.get("hypothetical_pnl_pct") is None:
            continue
        dt = datetime.datetime.fromisoformat(r["created_at"])
        recs.append((r["symbol"], r["side"], dt, float(r["hypothetical_pnl_pct"]), r.get("skip_reason", "")))
recs.sort(key=lambda x: (x[0], x[1], x[2]))
episodes = []
last = {}
GAP = 2 * 3600
for sym, side, dt, pnl, reason in recs:
    k = (sym, side)
    if k not in last or (dt - last[k]).total_seconds() > GAP:
        episodes.append(dict(sym=sym, side=side, dt=dt, hour=dt.hour, sess=sess(dt.hour), pnl_pct=pnl,
                             usd=pnl / 100 * MED_NOT, reason=reason))
    last[k] = dt

def cf_era(dt):
    if dt < datetime.datetime(2026, 6, 11, tzinfo=UTC): return "CF1_May30-Jun10"
    if dt < datetime.datetime(2026, 6, 26, tzinfo=UTC): return "CF2_Jun16-25"
    return "CF3_Jun26-Jul01"

for e in episodes:
    e["era"] = cf_era(e["dt"])
print(f"\ncounterfactual episodes n={len(episodes)} (from {len(recs)} raw resolved records, 2h dedup gap)")

print("\n== COUNTERFACTUAL EPISODES by session (dollarized @ median notional) ==")
for era in ["ALL", "CF1_May30-Jun10", "CF2_Jun16-25", "CF3_Jun26-Jul01"]:
    sub = episodes if era == "ALL" else [e for e in episodes if e["era"] == era]
    t = table(sub, lambda r: r["sess"], lambda r: r["usd"])
    for k, v in t.items():
        print(f"{era:16s} {k:11s} n={v['n']:4d} wr={v['wr']:.2f} total=${v['total']:9.0f} mean=${v['mean']:7.2f} frag=${v['frag']:9.0f}")

# ---------- 3. NIGHT BLOCK (00-06) dollar verdict ----------
print("\n== NIGHT 00-06: actual trades that DID fire at night ==")
for era in ["E1_Jun01-15", "E2_Jun16-Jul01"]:
    sub = [t for t in trades if t["sess"] == "Asia_00-06" and t["era"] == era]
    if sub:
        print(f"{era}: n={len(sub)} total=${sum(t['pnl'] for t in sub):.2f} wr={sum(1 for t in sub if t['pnl']>0)/len(sub):.2f} frag=${sum(t['pnl'] for t in sub)-max(t['pnl'] for t in sub):.2f}")

print("\n== NIGHT 00-06 CF episodes: what blocked/skipped night signals would have done ==")
night = [e for e in episodes if e["sess"] == "Asia_00-06"]
for era in ["CF1_May30-Jun10", "CF2_Jun16-25", "CF3_Jun26-Jul01"]:
    sub = [e for e in night if e["era"] == era]
    if sub:
        print(f"{era}: n={len(sub)} total=${sum(e['usd'] for e in sub):.0f} wr={sum(1 for e in sub if e['usd']>0)/len(sub):.2f}")

# ---------- 4. CANDLE STRUCTURE by session (Binance 1h, Mar-Jul 2026) ----------
def klines(coin, start_ms, end_ms):
    """Hyperliquid candleSnapshot, paginated (Binance geo-blocked 451)."""
    out, cur, seen = [], start_ms, set()
    while cur < end_ms:
        body = json.dumps({"type": "candleSnapshot",
                           "req": {"coin": coin, "interval": "1h", "startTime": cur, "endTime": end_ms}}).encode()
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        batch = [b for b in batch if b["t"] not in seen]
        if not batch:
            break
        out += batch
        seen.update(b["t"] for b in batch)
        cur = batch[-1]["t"] + 3600_000
        time.sleep(0.2)
    return out

start = int(datetime.datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000)
end = int(datetime.datetime(2026, 7, 1, tzinfo=UTC).timestamp() * 1000)
print("\n== CANDLE STRUCTURE (Hyperliquid 1h) ==")
for symbol in ["BTC", "ETH", "SOL"]:
    ks = klines(symbol, start, end)
    rows = []
    for k in ks:
        o, h, l, c = float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"])
        dt = datetime.datetime.fromtimestamp(k["t"] / 1000, UTC)
        rows.append(dict(dt=dt, mon=dt.strftime("%Y-%m"), sess=sess(dt.hour),
                         absret=abs(c / o - 1) * 100, rng=(h - l) / o * 100, ret=(c / o - 1) * 100))
    print(f"\n{symbol} n={len(rows)} bars {rows[0]['dt']:%m-%d}..{rows[-1]['dt']:%m-%d}")
    # per session: mean abs 1h ret, mean range, trend efficiency per session-day
    eff = defaultdict(list)
    byday = defaultdict(list)
    for r in rows:
        byday[(r["dt"].date(), r["sess"])].append(r["ret"])
    for (d, s), rets in byday.items():
        tot = sum(abs(x) for x in rets)
        if tot > 0:
            eff[s].append(abs(sum(rets)) / tot)
    for era_mon in ["ALL", "2026-03", "2026-04", "2026-05", "2026-06"]:
        sub = rows if era_mon == "ALL" else [r for r in rows if r["mon"] == era_mon]
        if not sub:
            continue
        for sname, _, _ in SESSIONS:
            ss = [r for r in sub if r["sess"] == sname]
            e = statistics.mean(eff[sname]) if era_mon == "ALL" else None
            estr = f" trend_eff={e:.3f}" if e is not None else ""
            print(f"  {era_mon:7s} {sname:11s} mean|ret|={statistics.mean(r['absret'] for r in ss):.3f}% "
                  f"mean_range={statistics.mean(r['rng'] for r in ss):.3f}%{estr}")
