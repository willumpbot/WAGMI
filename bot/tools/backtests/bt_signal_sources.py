# bt_signal_sources.py — Lane: which entry SOURCE has edge?
# READ-ONLY on bot data. Outputs stats to stdout (parsed into coordination/BT_SIGNAL_SOURCES.md).
import csv, json, math, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = r"C:\Users\vince\WAGMI\bot\data"

def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

# ---------- 1. Load trades.csv ----------
trades = list(csv.DictReader(open(ROOT + r"\trades.csv", encoding="utf-8")))
for t in trades:
    t["pnl_f"] = float(t["pnl"])
    t["fees_f"] = float(t["fees"] or 0)
    er = t["entry_reasons"].strip()
    t["er"] = json.loads(er) if er else {}
    t["close_ts"] = parse_ts(t["timestamp"])

# ---------- 2. Match to TRADE_OPENED for entry timestamps ----------
opens = []
for line in open(ROOT + r"\trade_events.jsonl", encoding="utf-8"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("event") == "TRADE_OPENED":
        opens.append(d)
used = set()
for t in trades:
    t["entry_ts"] = None
    e = float(t["entry"])
    cands = [
        (i, o) for i, o in enumerate(opens)
        if i not in used and o["symbol"] == t["symbol"] and o["side"] == t["side"]
        and abs(o["entry"] - e) / e < 0.0005
        and parse_ts(o["timestamp"]) <= t["close_ts"]
    ]
    if cands:
        i, o = max(cands, key=lambda x: parse_ts(x[1]["timestamp"]))  # nearest before close
        used.add(i)
        t["entry_ts"] = parse_ts(o["timestamp"])
        t["open_entry_type"] = o.get("entry_type")

# ---------- 3. Classification ----------
def classify(t):
    er = t["er"]
    if not er:
        return "unknown_no_metadata", "low"
    if er.get("llm_action") == "no_llm":
        return "mechanical_ensemble", "high"
    lc = er.get("llm_confidence")
    conf = float(t["confidence"] or 0)
    thesis = (er.get("thesis") or "").strip()
    if lc is not None and float(lc) == 0.0:
        if thesis == "LLM pipeline failure":
            return "exploration_override_pipeline_fail", "high"
        return "exploration_override", "high"
    # echo bug: llm_confidence == ensemble conf/100 with empty thesis -> not a real LLM approval record
    if lc is not None and thesis == "" and abs(float(lc) - conf / 100.0) < 1e-9:
        return "suspect_echo", "medium"
    if lc is not None and float(lc) > 0:
        return "llm_approved", "med-high"
    return "unknown_no_metadata", "low"

for t in trades:
    t["source"], t["cls_conf"] = classify(t)

# ---------- 4. Per-source stats ----------
def stats(rows):
    n = len(rows)
    if n == 0:
        return None
    wins = [r["pnl_f"] for r in rows if r["pnl_f"] > 0]
    losses = [r["pnl_f"] for r in rows if r["pnl_f"] <= 0]
    tot = sum(r["pnl_f"] for r in rows)
    fees = sum(r["fees_f"] for r in rows)
    return dict(
        n=n, wr=len(wins) / n * 100, total_pnl=tot, fees=fees,
        avg_win=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        median_pnl=sorted(r["pnl_f"] for r in rows)[n // 2],
    )

def prow(label, s):
    if not s:
        print(f"{label:44s}  n=0")
        return
    print(f"{label:44s}  n={s['n']:3d}  WR={s['wr']:5.1f}%  totPnL={s['total_pnl']:+9.2f}  avgW={s['avg_win']:+8.2f}  avgL={s['avg_loss']:+8.2f}  medPnL={s['median_pnl']:+7.2f}  fees={s['fees']:7.2f}")

print("=== CLASSIFICATION COUNTS ===")
print(Counter(t["source"] for t in trades))
print()
print("=== PER-SOURCE (all 90 closes) ===")
srcs = ["llm_approved", "exploration_override", "exploration_override_pipeline_fail", "suspect_echo", "mechanical_ensemble", "unknown_no_metadata"]
for s in srcs:
    rows = [t for t in trades if t["source"] == s]
    prow(s, stats(rows))
    for side in ("LONG", "SHORT"):
        sub = [t for t in rows if t["side"] == side]
        if sub:
            prow(f"    {side}", stats(sub))
print()
print("=== ERA SPLIT (early era = close < 2026-06-07) ===")
cut = datetime(2026, 6, 7, tzinfo=timezone.utc)
for era, pred in [("early(Jun1-6)", lambda t: t["close_ts"] < cut), ("later(Jun7+)", lambda t: t["close_ts"] >= cut)]:
    rows = [t for t in trades if pred(t)]
    prow(era, stats(rows))
    for s in srcs:
        sub = [t for t in rows if t["source"] == s]
        if sub:
            prow(f"    {s}", stats(sub))
    for side in ("LONG", "SHORT"):
        sub = [t for t in rows if t["side"] == side]
        if sub:
            prow(f"    side={side}", stats(sub))
print()
print("=== EARLY-ERA SHORTS vs EVERYTHING ELSE ===")
es = [t for t in trades if t["close_ts"] < cut and t["side"] == "SHORT"]
rest = [t for t in trades if not (t["close_ts"] < cut and t["side"] == "SHORT")]
prow("early-era SHORTS", stats(es))
prow("everything else", stats(rest))
print()
print("=== LLM_APPROVED detail: by month-half ===")
la = [t for t in trades if t["source"] == "llm_approved"]
for lbl, pred in [("Jun1-9", lambda t: t["close_ts"] < datetime(2026, 6, 10, tzinfo=timezone.utc)),
                  ("Jun10-30+", lambda t: t["close_ts"] >= datetime(2026, 6, 10, tzinfo=timezone.utc))]:
    prow(f"  llm_approved {lbl}", stats([t for t in la if pred(t)]))
print()
print("=== unknown_no_metadata rows (list) ===")
for t in trades:
    if t["source"] == "unknown_no_metadata":
        print(f"  {t['timestamp'][:16]} {t['symbol']:4s} {t['side']:5s} pnl={t['pnl_f']:+9.2f} lev={t['leverage']} et={t['entry_type'] or '-'}")

# ---------- 5. Counterfactual ensemble-confidence backtest ----------
print()
print("=== COUNTERFACTUAL: ensemble confidence vs would-win ===")
recs = {}
bad = 0
unresolved = 0
for line in open(ROOT + r"\llm\counterfactual_resolved.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        bad += 1
        continue
    rid = d.get("record_id")
    recs[rid] = d  # last write wins (dedupe)
allr = list(recs.values())
res = [d for d in allr if d.get("resolved") and d.get("hypothetical_pnl_pct") is not None]
unresolved = len(allr) - len(res)
print(f"lines_parsed={len(allr)+bad+0} unique_records={len(allr)} resolved={len(res)} unresolved={unresolved} bad_lines={bad}")

def cf_stats(rows):
    n = len(rows)
    if n == 0:
        return "n=0"
    winp = sum(1 for r in rows if r["hypothetical_pnl_pct"] > 0) / n * 100
    tp1 = sum(1 for r in rows if r.get("would_hit_tp1")) / n * 100
    sl = sum(1 for r in rows if r.get("would_hit_sl")) / n * 100
    avg = sum(r["hypothetical_pnl_pct"] for r in rows) / n
    return f"n={n:6d}  pnl>0={winp:5.1f}%  TP1={tp1:5.1f}%  SL={sl:5.1f}%  avg_hyp_pnl={avg:+7.3f}%"

print("\n-- by confidence bucket (all resolved skips) --")
buckets = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
for lo, hi in buckets:
    rows = [r for r in res if lo <= (r.get("confidence") or 0) < hi]
    print(f"conf [{lo:3d},{hi:3d}): {cf_stats(rows)}")
hi80 = [r for r in res if (r.get("confidence") or 0) >= 80]
lo80 = [r for r in res if (r.get("confidence") or 0) < 80]
print(f"conf >=80 : {cf_stats(hi80)}")
print(f"conf < 80 : {cf_stats(lo80)}")

# significance: two-proportion z for pnl>0 rate
def ztest(a, b):
    pa = sum(1 for r in a if r["hypothetical_pnl_pct"] > 0) / len(a)
    pb = sum(1 for r in b if r["hypothetical_pnl_pct"] > 0) / len(b)
    p = (pa * len(a) + pb * len(b)) / (len(a) + len(b))
    se = math.sqrt(p * (1 - p) * (1 / len(a) + 1 / len(b)))
    return (pa - pb) / se if se else 0.0
print(f"two-prop z (>=80 vs <80, pnl>0): {ztest(hi80, lo80):+.2f}")

print("\n-- by side --")
for side in ("BUY", "SELL"):
    rows = [r for r in res if r.get("side") == side]
    print(f"side={side}: {cf_stats(rows)}")
    h = [r for r in rows if (r.get("confidence") or 0) >= 80]
    l = [r for r in rows if (r.get("confidence") or 0) < 80]
    print(f"   conf>=80: {cf_stats(h)}")
    print(f"   conf<80 : {cf_stats(l)}")
    if h and l:
        print(f"   z(>=80 vs <80): {ztest(h, l):+.2f}")

print("\n-- by month --")
for mon in ("2026-05", "2026-06", "2026-07"):
    rows = [r for r in res if (r.get("created_at") or "").startswith(mon)]
    print(f"{mon}: {cf_stats(rows)}")
    h = [r for r in rows if (r.get("confidence") or 0) >= 80]
    l = [r for r in rows if (r.get("confidence") or 0) < 80]
    if h:
        print(f"   conf>=80: {cf_stats(h)}")
        print(f"   conf<80 : {cf_stats(l)}")

print("\n-- confidence-decile spearman-ish check (bucket mean pnl monotonicity) --")
res_sorted = sorted(res, key=lambda r: r.get("confidence") or 0)
dec = len(res_sorted) // 10
for i in range(10):
    rows = res_sorted[i * dec:(i + 1) * dec] if i < 9 else res_sorted[9 * dec:]
    cmin = rows[0]["confidence"]; cmax = rows[-1]["confidence"]
    avg = sum(r["hypothetical_pnl_pct"] for r in rows) / len(rows)
    winp = sum(1 for r in rows if r["hypothetical_pnl_pct"] > 0) / len(rows) * 100
    print(f"decile {i}: conf[{cmin:5.1f},{cmax:5.1f}] n={len(rows):5d} pnl>0={winp:5.1f}% avg={avg:+7.3f}%")

print("\n-- by symbol, conf>=80 vs <80 --")
for sym in sorted(set(r.get("symbol") for r in res)):
    rows = [r for r in res if r.get("symbol") == sym]
    h = [r for r in rows if (r.get("confidence") or 0) >= 80]
    l = [r for r in rows if (r.get("confidence") or 0) < 80]
    print(f"{sym}: >=80 {cf_stats(h)} | <80 {cf_stats(l)}")

print("\n-- by skip_reason (top 8) --")
sr = Counter(r.get("skip_reason") for r in res)
for reason, cnt in sr.most_common(8):
    rows = [r for r in res if r.get("skip_reason") == reason]
    print(f"{str(reason)[:40]:40s} {cf_stats(rows)}")
