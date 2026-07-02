"""RQ17 — Fee drag map. READ-ONLY analysis of trade_ledger.csv + trades.csv.

Outputs: fee bps of notional per trade, fee drag vs gross PnL per symbol /
exit_type / hold bucket / size bucket / era, gross->net flip census, and the
per-symbol fee floor (minimum expected move to clear fees).
"""
import csv, json, math
from collections import defaultdict
from datetime import datetime, timezone

LEDGER = r"C:\Users\vince\WAGMI\bot\data\trade_ledger.csv"
TRADES = r"C:\Users\vince\WAGMI\bot\data\trades.csv"

rows = []
with open(LEDGER, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            ts = float(r["timestamp"])
            entry = float(r["entry_price"]); exitp = float(r["exit_price"])
            gross = float(r["gross_pnl"]); fees = float(r["fees"])
            funding = float(r["funding"] or 0); net = float(r["net_pnl"])
            hold = float(r["hold_hours"] or 0)
        except (ValueError, KeyError):
            continue
        side = r["side"].upper()
        d = 1 if side == "LONG" else -1
        move = (exitp - entry) / entry * d  # signed fractional move in trade's favor
        move_bps = move * 1e4
        # notional from gross pnl and move (gross = notional * move)
        notional = abs(gross / move) if abs(move) > 1e-9 else float("nan")
        fee_bps = fees / notional * 1e4 if notional == notional and notional > 0 else float("nan")
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        rows.append(dict(ts=ts, dt=dt, sym=r["symbol"], side=side, exit=r["exit_type"],
                         regime=r["regime_1h"] or "unknown", lev=float(r["leverage"] or 0),
                         hold=hold, entry=entry, exitp=exitp, gross=gross, fees=fees,
                         funding=funding, net=net, move_bps=move_bps, notional=notional,
                         fee_bps=fee_bps, agree=r.get("agreement_level", "")))

print(f"ledger rows parsed: {len(rows)}")
# integrity: gross - fees + funding ?= net
bad = [r for r in rows if abs(r["gross"] - r["fees"] + r["funding"] - r["net"]) > 0.02]
print(f"identity gross-fees+funding=net violations (> $0.02): {len(bad)}")
for r in bad[:5]:
    print("  ", r["dt"].date(), r["sym"], r["gross"], r["fees"], r["funding"], r["net"])

def era(dt):
    d = dt.date().isoformat()
    if d <= "2026-06-07": return "W1(Jun1-7)"
    if d <= "2026-06-23": return "MID(Jun8-23)"
    return "LATE(Jun24+)"

def med(xs):
    xs = sorted(x for x in xs if x == x)
    if not xs: return float("nan")
    n = len(xs)
    return xs[n//2] if n % 2 else (xs[n//2-1] + xs[n//2]) / 2

def hold_bucket(h):
    if h < 1: return "<1h"
    if h < 4: return "1-4h"
    if h < 12: return "4-12h"
    return ">=12h"

# size buckets by notional
nots = sorted(r["notional"] for r in rows if r["notional"] == r["notional"])
t1, t2 = nots[len(nots)//3], nots[2*len(nots)//3]
def size_bucket(n):
    if n != n: return "?"
    if n <= t1: return f"S(<=${t1:,.0f})"
    if n <= t2: return f"M(<=${t2:,.0f})"
    return f"L(>${t2:,.0f})"

def agg(keyfn, label):
    g = defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(r)
    print(f"\n== {label} ==")
    print(f"{'bucket':22s} {'n':>4s} {'sum_gross':>10s} {'sum_fees':>9s} {'sum_net':>9s} {'fee%|gross|':>11s} {'med_feebps':>10s} {'med_movebps':>11s} {'flips':>5s} {'gross+':>6s} {'net+':>5s}")
    out = {}
    for k in sorted(g, key=lambda x: str(x)):
        rs = g[k]
        sg = sum(r["gross"] for r in rs); sf = sum(r["fees"] for r in rs); sn = sum(r["net"] for r in rs)
        sag = sum(abs(r["gross"]) for r in rs)
        flips = sum(1 for r in rs if r["gross"] > 0 and r["net"] <= 0)
        gpos = sum(1 for r in rs if r["gross"] > 0); npos = sum(1 for r in rs if r["net"] > 0)
        mfb = med([r["fee_bps"] for r in rs]); mmb = med([abs(r["move_bps"]) for r in rs])
        print(f"{str(k):22s} {len(rs):4d} {sg:10.2f} {sf:9.2f} {sn:9.2f} {100*sf/sag if sag else 0:10.1f}% {mfb:10.1f} {mmb:11.1f} {flips:5d} {gpos:6d} {npos:5d}")
        out[k] = dict(n=len(rs), sum_gross=sg, sum_fees=sf, sum_net=sn, flips=flips)
    return out

agg(lambda r: r["sym"], "PER SYMBOL")
agg(lambda r: r["exit"], "PER EXIT TYPE")
agg(lambda r: hold_bucket(r["hold"]), "PER HOLD BUCKET")
agg(lambda r: size_bucket(r["notional"]), "PER SIZE BUCKET (notional)")
agg(lambda r: era(r["dt"]), "PER ERA")
agg(lambda r: (r["sym"], era(r["dt"])), "SYMBOL x ERA")
agg(lambda r: (r["sym"], hold_bucket(r["hold"])), "SYMBOL x HOLD")
agg(lambda r: r["regime"], "PER REGIME(1h)")
agg(lambda r: (r["exit"], era(r["dt"])), "EXIT x ERA")

# fee bps distribution per symbol + era (did fee rate change?)
print("\n== FEE BPS OF NOTIONAL (round trip) per symbol/era ==")
g = defaultdict(list)
for r in rows:
    g[(r["sym"], era(r["dt"]))].append(r["fee_bps"])
for k in sorted(g):
    xs = sorted(x for x in g[k] if x == x)
    if xs:
        print(f"  {str(k):28s} n={len(xs):3d} med={med(xs):6.2f} p10={xs[int(0.1*len(xs))]:6.2f} p90={xs[min(len(xs)-1,int(0.9*len(xs)))]:6.2f}")

# flip census: gross>0 net<=0
flips = [r for r in rows if r["gross"] > 0 and r["net"] <= 0]
print(f"\n== FLIPPED TRADES (gross>0, net<=0): {len(flips)} ==")
for r in flips:
    print(f"  {r['dt'].date()} {r['sym']:4s} {r['side']:5s} {r['exit']:14s} hold={r['hold']:5.1f}h move={r['move_bps']:+7.1f}bps gross={r['gross']:+8.2f} fees={r['fees']:6.2f} net={r['net']:+8.2f} feebps={r['fee_bps']:5.1f}")

# never-had-a-chance: |move| needed just to pay fees
print("\n== TRADES WHERE |realized move| < round-trip fee bps (couldn't clear fees even if direction right) ==")
nhc = [r for r in rows if abs(r["move_bps"]) < r["fee_bps"]]
print(f"count: {len(nhc)} / {len(rows)}")
g = defaultdict(int)
for r in nhc: g[(r["exit"], hold_bucket(r["hold"]))] += 1
for k, v in sorted(g.items(), key=lambda kv: -kv[1]):
    print(f"  {k}: {v}")

# join trades.csv for setup type (entry_type, num_agree)
setups = []
with open(TRADES, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            reasons = json.loads(r["entry_reasons"]) if r["entry_reasons"] else {}
        except json.JSONDecodeError:
            reasons = {}
        setups.append(dict(entry=float(r["entry"]), sym=r["symbol"], side=r["side"],
                           pnl=float(r["pnl"]), fees=float(r["fees"]),
                           entry_type=r["entry_type"], regime=r["regime"],
                           num_agree=reasons.get("num_agree"),
                           ts=r["timestamp"]))
# match ledger rows to trades.csv rows by sym+entry price+net pnl
matched = 0
for s in setups:
    for r in rows:
        if r["sym"] == s["sym"] and abs(r["entry"] - s["entry"]) < 1e-6 and abs(r["net"] - s["pnl"]) < 0.02:
            r["entry_type"] = s["entry_type"]; r["num_agree"] = s["num_agree"]
            matched += 1
            break
print(f"\ntrades.csv rows: {len(setups)}, matched to ledger: {matched}")
agg(lambda r: r.get("entry_type", "UNMATCHED") or "blank", "PER SETUP TYPE (entry_type)")
agg(lambda r: str(r.get("num_agree", "?")), "PER NUM_AGREE (strategies agreeing)")

# what fraction of trades' |move| cleared k x fee floor, per symbol (LATE era = current fee level)
print("\n== MOVE vs FEE FLOOR (LATE era only, current fee regime) ==")
late = [r for r in rows if era(r["dt"]) == "LATE(Jun24+)"]
for sym in sorted(set(r["sym"] for r in late)):
    rs = [r for r in late if r["sym"] == sym]
    fb = med([r["fee_bps"] for r in rs])
    moves = [abs(r["move_bps"]) for r in rs]
    c1 = sum(1 for m in moves if m >= fb); c2 = sum(1 for m in moves if m >= 2*fb); c4 = sum(1 for m in moves if m >= 4*fb)
    print(f"  {sym}: n={len(rs)} med_fee={fb:.1f}bps  |move|>=1x: {c1}/{len(rs)}  >=2x: {c2}/{len(rs)}  >=4x: {c4}/{len(rs)}  med|move|={med(moves):.0f}bps")

# fragility: LLM_EXIT_AGENT stats without wk1
print("\n== LLM_EXIT_AGENT ex-W1 ==")
rs = [r for r in rows if r["exit"] == "LLM_EXIT_AGENT" and era(r["dt"]) != "W1(Jun1-7)"]
print(f"n={len(rs)} sum_gross={sum(r['gross'] for r in rs):.2f} sum_fees={sum(r['fees'] for r in rs):.2f} sum_net={sum(r['net'] for r in rs):.2f} net+count={sum(1 for r in rs if r['net']>0)} med|move|={med([abs(r['move_bps']) for r in rs]):.1f}bps")

# fee floor table: per symbol, breakeven move = med fee bps; add p90 for safety
print("\n== FEE FLOOR TABLE ==")
g = defaultdict(list)
for r in rows: g[r["sym"]].append(r)
for sym in sorted(g):
    rs = g[sym]
    xs = sorted(r["fee_bps"] for r in rs if r["fee_bps"] == r["fee_bps"])
    # slippage proxy: SL exits overshoot — compare realized loss move vs typical; instead report exit-type med fee
    print(f"  {sym}: n={len(rs)} med_roundtrip_fee={med(xs):.1f}bps p90={xs[min(len(xs)-1,int(0.9*len(xs)))]:.1f}bps  -> min |move| to break even ~{med(xs):.0f}bps; for fees<=25%% of gross need ~{4*med(xs):.0f}bps")
