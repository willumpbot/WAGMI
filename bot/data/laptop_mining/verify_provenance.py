"""Is the legacy trade_events.jsonl live trading, or simulation/backtest replay?

House rule: prove it, don't assert it. Tests:
  1. trades per calendar day  (live bot cannot close 1000+/day)
  2. TRADE_OPENED vs TRADE_CLOSED balance
  3. presence of any mode / paper / dry-run / backtest marker
  4. notional vs pnl scale sanity
"""
import json, collections, io

SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/trade_events.jsonl"

per_day = collections.Counter()
opened_day = collections.Counter()
keys = collections.Counter()
mode_vals = collections.Counter()
lev = collections.Counter()
sample = []

with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        e = d.get("event")
        day = str(d.get("timestamp", ""))[:10]
        if e == "TRADE_CLOSED":
            per_day[day] += 1
            for k in d:
                keys[k] += 1
            for mk in ("mode", "paper", "dry_run", "is_paper", "backtest", "simulated", "account"):
                if mk in d:
                    mode_vals[f"{mk}={d[mk]}"] += 1
            lev[d.get("leverage")] += 1
            if len(sample) < 3:
                sample.append(d)
        elif e == "TRADE_OPENED":
            opened_day[day] += 1

print("=== TRADE_CLOSED per day (top 12) ===")
for day, n in per_day.most_common(12):
    print(f"  {day}: {n:>5} closed   ({opened_day.get(day,0):>5} opened)")
print(f"\n  distinct days with closes: {len(per_day)}")
print(f"  total opened: {sum(opened_day.values())}   total closed: {sum(per_day.values())}")

print("\n=== keys present on TRADE_CLOSED rows ===")
for k, v in keys.most_common(30):
    print(f"  {v:>6}  {k}")

print("\n=== explicit mode/paper markers ===")
print("  ", dict(mode_vals) or "NONE FOUND")

print("\n=== leverage distribution ===")
for k, v in lev.most_common(10):
    print(f"  {v:>6}  lev={k}")

print("\n=== one full sample row ===")
if sample:
    print(json.dumps(sample[0], indent=2)[:1400])
