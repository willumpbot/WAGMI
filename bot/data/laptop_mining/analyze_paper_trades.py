"""Aggregate bot/paper_trades/*.csv — the cleanest dataset on the laptop.

2,836 session files, 2026-02-10 -> 2026-06-05, i.e. almost entirely BEFORE the
server's grading window opens (2026-05-30). Schema carries real fees and
outcome labels, so net-of-cost arithmetic is possible without trusting the
bot's warped aggregate PnL.

Validation: realistic price, non-zero qty, fee >= 0, |pnl| within a sane
multiple of notional. Flags n<13 per house rules.
"""
import csv, glob, io, collections, math

ROOT = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/paper_trades/"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/"

trades = []
bad = collections.Counter()
files = sorted(glob.glob(ROOT + "trades_*.csv"))

for path in files:
    try:
        with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    px = float(row["price"]); qty = float(row["qty"])
                    pnl = float(row["pnl"]); fee = float(row["fee"])
                    lev = float(row["leverage"] or 0)
                    hold = float(row["hold_time_s"] or 0)
                except (TypeError, ValueError, KeyError):
                    bad["unparseable_row"] += 1
                    continue
                if px <= 0 or qty <= 0:
                    bad["nonpositive"] += 1
                    continue
                if fee < 0:
                    bad["negative_fee"] += 1
                    continue
                notional = px * qty
                if notional <= 0 or abs(pnl) > notional:
                    bad["pnl_exceeds_notional"] += 1
                    continue
                trades.append({
                    "ts": row["timestamp"], "sym": row["symbol"],
                    "action": row["action"], "side": row["side"],
                    "pnl": pnl, "fee": fee, "net": pnl - fee,
                    "notional": notional, "lev": lev, "hold_s": hold,
                    "ret_pct": 100.0 * (pnl - fee) / notional,
                })
    except OSError:
        bad["unreadable_file"] += 1

print(f"session files       : {len(files)}")
print(f"valid trade rows    : {len(trades)}")
print(f"rejected            : {dict(bad) or 'none'}")
if not trades:
    raise SystemExit("nothing usable")

ts = sorted(t["ts"] for t in trades)
print(f"span                : {ts[0][:19]} -> {ts[-1][:19]}")
gross = sum(t["pnl"] for t in trades)
fees = sum(t["fee"] for t in trades)
print(f"gross pnl           : ${gross:,.2f}")
print(f"fees                : ${fees:,.2f}  ({100*fees/abs(gross) if gross else 0:.1f}% of |gross|)")
print(f"NET pnl             : ${gross-fees:,.2f}")
print(f"mean net return     : {sum(t['ret_pct'] for t in trades)/len(trades):+.3f}% of notional")


def blk(rows, label, minn=13):
    n = len(rows)
    if n == 0:
        return
    net = sum(r["net"] for r in rows)
    rp = [r["ret_pct"] for r in rows]
    mean = sum(rp) / n
    var = sum((x - mean) ** 2 for x in rp) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n) if n else 0.0
    w = sum(1 for r in rows if r["net"] > 0)
    flag = "  [n<13 INSUFFICIENT]" if n < minn else ""
    sig = ""
    if n >= minn:
        if mean - 2 * se > 0:
            sig = "  <= POSITIVE (CI excl 0)"
        elif mean + 2 * se < 0:
            sig = "  <= NEGATIVE (CI excl 0)"
    print(f"  {label:<14} n={n:>5}  net=${net:>11,.2f}  mean={mean:>+7.3f}% +/-{se:.3f}"
          f"  WR={100*w/n:>5.1f}%{flag}{sig}")


print("\n=== by action (exit type) ===")
byact = collections.defaultdict(list)
for t in trades:
    byact[t["action"]].append(t)
for k, v in sorted(byact.items(), key=lambda x: -len(x[1])):
    blk(v, k)

print("\n=== by side ===")
byside = collections.defaultdict(list)
for t in trades:
    byside[t["side"]].append(t)
for k, v in sorted(byside.items(), key=lambda x: -len(x[1])):
    blk(v, k)

print("\n=== by symbol (top 14) ===")
bysym = collections.defaultdict(list)
for t in trades:
    bysym[t["sym"]].append(t)
for k, v in sorted(bysym.items(), key=lambda x: -len(x[1]))[:14]:
    blk(v, k)

print("\n=== by month ===")
bymo = collections.defaultdict(list)
for t in trades:
    bymo[t["ts"][:7]].append(t)
for k in sorted(bymo):
    blk(bymo[k], k)

print("\n=== leverage buckets ===")
bylev = collections.defaultdict(list)
for t in trades:
    L = t["lev"]
    b = "0-2x" if L <= 2 else ("2-5x" if L <= 5 else ("5-10x" if L <= 10 else ">10x"))
    bylev[b].append(t)
for k in ("0-2x", "2-5x", "5-10x", ">10x"):
    if k in bylev:
        blk(bylev[k], k)

print("\n=== signals_*.csv companion files ===")
sfiles = sorted(glob.glob(ROOT + "signals_*.csv"))
print(f"  count: {len(sfiles)}")
if sfiles:
    big = max(sfiles, key=lambda p: __import__("os").path.getsize(p))
    with io.open(big, encoding="utf-8", errors="replace", newline="") as fh:
        rdr = csv.reader(fh)
        hdr = next(rdr, [])
        rows = sum(1 for _ in rdr)
    print(f"  largest: {big.split('/')[-1]} ({rows} rows)")
    print(f"  columns: {hdr}")

import json
with io.open(OUT + "paper_trades_summary.json", "w", encoding="utf-8") as fh:
    json.dump({
        "source": ROOT, "session_files": len(files), "valid_rows": len(trades),
        "rejected": dict(bad), "span": [ts[0], ts[-1]],
        "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "net_pnl": round(gross - fees, 2),
        "mean_net_ret_pct": round(sum(t["ret_pct"] for t in trades) / len(trades), 4),
        "by_action": {k: len(v) for k, v in byact.items()},
        "by_symbol": {k: len(v) for k, v in bysym.items()},
    }, fh, indent=1)
print("\nwrote paper_trades_summary.json")
