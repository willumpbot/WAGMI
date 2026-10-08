"""Separate plausibly-real closed trades from synthetic/backtest rows.

A row is treated as synthetic if ANY of:
  - strategy == ""            (live rows always carry a strategy name)
  - confidence == 0           (live rows carry the ensemble confidence)
  - regime == ""              (live rows carry a regime label)
  - entry_price is a suspiciously round number (exact multiple of 50 or 100)
  - entry_price in the known canned set
Also profiles the manual/ sniper files, which the handoff flags as the owner's
own discretionary trades.
"""
import json, collections, io

TE = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/trade_events.jsonl"
SNIPE = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/manual/sniper_signals.jsonl"

CANNED = {100.0, 50000.0, 3000.0, 84.63, 40.0}


def synth_reasons(d):
    r = []
    if not d.get("strategy"):
        r.append("no_strategy")
    if not d.get("confidence"):
        r.append("conf_zero")
    if not d.get("regime"):
        r.append("no_regime")
    e = d.get("entry_price")
    if isinstance(e, (int, float)):
        if e in CANNED:
            r.append("canned_entry")
        elif e > 1 and (e % 50 == 0 or e % 100 == 0):
            r.append("round_entry")
    return r


real, synth = [], []
reasons = collections.Counter()

with io.open(TE, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event") != "TRADE_CLOSED":
            continue
        if not isinstance(d.get("pnl"), (int, float)):
            continue
        r = synth_reasons(d)
        if r:
            for x in r:
                reasons[x] += 1
            synth.append(d)
        else:
            real.append(d)

print("=== TRADE_CLOSED split ===")
print(f"  synthetic/suspect : {len(synth)}")
print(f"  plausibly real    : {len(real)}")
print("  synthetic reasons :", dict(reasons))


def summarise(rows, label):
    if not rows:
        print(f"\n  {label}: EMPTY")
        return
    ts = sorted(str(r.get("timestamp", ""))[:19] for r in rows)
    pnl = [float(r["pnl"]) for r in rows]
    w = sum(1 for x in pnl if x > 0)
    print(f"\n=== {label} (n={len(rows)}) ===")
    print(f"  span   : {ts[0]} -> {ts[-1]}")
    print(f"  net    : ${sum(pnl):,.2f}   WR {100*w/len(rows):.1f}%")
    print(f"  median : ${sorted(pnl)[len(pnl)//2]:,.2f}   mean ${sum(pnl)/len(pnl):,.2f}")
    days = collections.Counter(str(r.get("timestamp", ""))[:10] for r in rows)
    print(f"  days   : {len(days)}  max/day {max(days.values())}")
    bysym = collections.defaultdict(list)
    for r in rows:
        bysym[r.get("symbol")].append(float(r["pnl"]))
    print("  by symbol:")
    for s, v in sorted(bysym.items(), key=lambda x: -len(x[1]))[:8]:
        wv = sum(1 for x in v if x > 0)
        flag = "  [n<13 INSUFFICIENT]" if len(v) < 13 else ""
        print(f"    {str(s):<7} n={len(v):>4} net=${sum(v):>10,.2f} WR={100*wv/len(v):>5.1f}%{flag}")


summarise(real, "PLAUSIBLY REAL closed trades")

with io.open("C:/Users/vince/WAGMI/bot/data/laptop_mining/legacy_real_trades.json", "w",
             encoding="utf-8") as fh:
    json.dump(real, fh, indent=0)

# --- manual sniper file (owner's discretionary system) ---
print("\n\n=== manual/sniper_signals.jsonl ===")
sn = []
with io.open(SNIPE, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            sn.append(json.loads(line))
        except Exception:
            pass
print(f"  rows: {len(sn)}")
if sn:
    print(f"  keys: {sorted(sn[0].keys())}")
    has_outcome = sum(1 for d in sn if any(k in d for k in ("outcome", "result", "pnl_actual", "closed")))
    print(f"  rows with a realised outcome field: {has_outcome}")
    tiers = collections.Counter(d.get("tier") for d in sn)
    print(f"  tiers: {dict(tiers)}")
    tss = [str(d.get("timestamp") or d.get("ts") or "") for d in sn]
    tss = [t for t in tss if t]
    print(f"  timestamp field present on {len(tss)}/{len(sn)} rows")
    if tss:
        print(f"  span: {min(tss)[:19]} -> {max(tss)[:19]}")
