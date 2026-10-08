"""Build the one genuinely clean asset on this laptop: the signal corpus.

Every other series here (trade_events PnL, counterfactual envelopes, paper-trade
PnL) is warped by simulator bugs or fixture flooding. The signals_*.csv files
are different: they record what the bot PROPOSED, with a trace_id, before any
simulated fill touched them. They can be graded against real Hyperliquid candles
later, so no broken arithmetic propagates.

Output: signal_corpus.jsonl (one row per de-duplicated proposal) + a profile.
Validation: geometry (sl/tp on correct sides of entry), positive prices,
confidence in range. Dedupe on (symbol, side, strategy, entry, 1h bucket).
"""
import csv, glob, io, json, collections, os

ROOT = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/paper_trades/"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/"

files = sorted(glob.glob(ROOT + "signals_*.csv"))
rows, bad = [], collections.Counter()

for path in files:
    try:
        with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    e = float(r["entry"]); sl = float(r["sl"])
                    tp1 = float(r["tp1"]); tp2 = float(r["tp2"] or 0)
                    conf = float(r["confidence"])
                    na = float(r["num_agree"] or 0)
                    tot = float(r["total_strategies"] or 0)
                    rs = r.get("regime_score")
                    rs = float(rs) if rs not in (None, "") else None
                except (TypeError, ValueError, KeyError):
                    bad["unparseable"] += 1
                    continue
                side = (r.get("side") or "").upper()
                if e <= 0 or sl <= 0 or tp1 <= 0:
                    bad["nonpositive"] += 1
                    continue
                if not (0 <= conf <= 100):
                    bad["conf_range"] += 1
                    continue
                if side in ("BUY", "LONG"):
                    if not (sl < e < tp1):
                        bad["geometry"] += 1
                        continue
                elif side in ("SELL", "SHORT"):
                    if not (tp1 < e < sl):
                        bad["geometry"] += 1
                        continue
                else:
                    bad["unknown_side"] += 1
                    continue
                risk = abs(e - sl) / e
                if not (0.0005 <= risk <= 0.25):
                    bad["implausible_stop"] += 1
                    continue
                rows.append({
                    "ts": r["timestamp"], "trace_id": r.get("trace_id"),
                    "sym": r["symbol"], "strategy": r.get("strategy"),
                    "side": "LONG" if side in ("BUY", "LONG") else "SHORT",
                    "conf": conf, "entry": e, "sl": sl, "tp1": tp1, "tp2": tp2,
                    "atr": r.get("atr"), "regime_score": rs,
                    "num_agree": na, "total_strategies": tot,
                    "rr1": abs(tp1 - e) / abs(e - sl) if e != sl else None,
                    "stop_pct": round(100 * risk, 4),
                    "src": os.path.basename(path),
                })
    except OSError:
        bad["unreadable"] += 1

seen, ded = set(), []
for r in sorted(rows, key=lambda x: x["ts"]):
    k = (r["sym"], r["side"], r["strategy"], round(r["entry"], 8), r["ts"][:13])
    if k in seen:
        continue
    seen.add(k)
    ded.append(r)

print(f"signal files      : {len(files)}")
print(f"raw rows          : {len(rows) + sum(bad.values())}")
print(f"valid rows        : {len(rows)}")
print(f"rejected          : {dict(bad) or 'none'}")
print(f"after dedupe      : {len(ded)}")
if not ded:
    raise SystemExit("empty corpus")

ts = [r["ts"] for r in ded]
print(f"span              : {min(ts)[:19]} -> {max(ts)[:19]}")
days = sorted({r['ts'][:10] for r in ded})
print(f"distinct days     : {len(days)}  ({days[0]} .. {days[-1]})")
print(f"trace_id present  : {sum(1 for r in ded if r['trace_id'])}/{len(ded)}")

print("\n=== by month ===")
bymo = collections.Counter(r["ts"][:7] for r in ded)
for k in sorted(bymo):
    print(f"  {k}: {bymo[k]:>6}")

print("\n=== by symbol (top 14) ===")
for k, v in collections.Counter(r["sym"] for r in ded).most_common(14):
    print(f"  {k:<10} {v:>6}")

print("\n=== by side / strategy ===")
for k, v in collections.Counter(r["side"] for r in ded).most_common():
    print(f"  {k:<10} {v:>6}")
for k, v in collections.Counter(r["strategy"] for r in ded).most_common(8):
    print(f"  {str(k):<18} {v:>6}")

print("\n=== confidence distribution ===")
cb = collections.Counter()
for r in ded:
    c = r["conf"]
    cb[f"{int(c//10)*10}-{int(c//10)*10+9}"] += 1
for k in sorted(cb, key=lambda x: int(x.split('-')[0])):
    print(f"  conf {k:<8} {cb[k]:>6}")

print("\n=== num_agree distribution ===")
for k, v in sorted(collections.Counter(int(r["num_agree"]) for r in ded).items()):
    print(f"  agree={k}  {v:>6}")

rr = [r["rr1"] for r in ded if r["rr1"]]
sp = [r["stop_pct"] for r in ded]
rr.sort(); sp.sort()
print(f"\nR:R to tp1  median {rr[len(rr)//2]:.2f}  (p10 {rr[len(rr)//10]:.2f}, p90 {rr[9*len(rr)//10]:.2f})")
print(f"stop width %  median {sp[len(sp)//2]:.3f}  (p10 {sp[len(sp)//10]:.3f}, p90 {sp[9*len(sp)//10]:.3f})")

with io.open(OUT + "signal_corpus.jsonl", "w", encoding="utf-8") as fh:
    for r in ded:
        fh.write(json.dumps(r) + "\n")
sz = os.path.getsize(OUT + "signal_corpus.jsonl") / 1048576
print(f"\nwrote signal_corpus.jsonl ({len(ded)} rows, {sz:.1f} MB)")
