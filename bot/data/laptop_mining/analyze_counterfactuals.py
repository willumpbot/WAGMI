"""Which gates blocked winners, and which blocked losers?

Source: WAGMI PROJECT/WAGMI/bot/data/llm/counterfactual_resolved.jsonl  (~112 MB)
Each row = a signal the bot SKIPPED, the gate that skipped it (skip_reason), and
the resolved counterfactual outcome (would_hit_tp1/tp2/sl, hypothetical_pnl_pct).

The server's own missed_trades_resolved.jsonl is corrupt (726/1407 impossible
prices), so every row here is validated before use:
  V1 geometry : BUY  -> sl < entry < tp1 ;  SELL -> tp1 < entry < sl
  V2 envelope : max_adverse must be on the adverse side of entry,
                max_favorable on the favorable side
  V3 coherence: would_hit_tp1 must agree with max_favorable reaching tp1
  V4 pnl sanity: |hypothetical_pnl_pct| <= 100
House rules: flag n<13, report the null, no lookahead (outcomes were resolved
forward of created_at by construction).
"""
import json, collections, io, math

SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/llm/counterfactual_resolved.jsonl"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/"

rows = []
bad = collections.Counter()
n_raw = 0


def validate(d):
    side = (d.get("side") or "").upper()
    e, sl, tp1 = d.get("entry_price"), d.get("sl"), d.get("tp1")
    mf, ma = d.get("max_favorable_price"), d.get("max_adverse_price")
    pnl = d.get("hypothetical_pnl_pct")
    for v in (e, sl, tp1, mf, ma, pnl):
        if not isinstance(v, (int, float)) or (isinstance(v, float) and math.isnan(v)):
            return "missing_numeric"
    if e <= 0 or sl <= 0 or tp1 <= 0:
        return "nonpositive_price"
    if side in ("BUY", "LONG"):
        if not (sl < e < tp1):
            return "V1_geometry"
        if ma > e:
            return "V2_adverse_wrong_side"
        if mf < e:
            return "V2_favorable_wrong_side"
        reached = mf >= tp1
    elif side in ("SELL", "SHORT"):
        if not (tp1 < e < sl):
            return "V1_geometry"
        if ma < e:
            return "V2_adverse_wrong_side"
        if mf > e:
            return "V2_favorable_wrong_side"
        reached = mf <= tp1
    else:
        return "unknown_side"
    if bool(d.get("would_hit_tp1")) != bool(reached):
        return "V3_tp1_incoherent"
    if abs(pnl) > 100:
        return "V4_pnl_insane"
    return None


with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        n_raw += 1
        try:
            d = json.loads(line)
        except Exception:
            bad["unparseable"] += 1
            continue
        if not d.get("resolved"):
            bad["unresolved"] += 1
            continue
        why = validate(d)
        if why:
            bad[why] += 1
            continue
        rows.append(d)

print(f"raw rows        : {n_raw}")
print(f"VALID rows      : {len(rows)}  ({100*len(rows)/max(n_raw,1):.1f}%)")
print(f"rejected        : {dict(bad)}")
if not rows:
    raise SystemExit("\nNo rows survived validation -> this file is unusable, same as the server's.")

ts = sorted(str(r.get("created_at", ""))[:19] for r in rows)
print(f"span            : {ts[0]} -> {ts[-1]}")

# dedupe: one row per (symbol, side, skip_reason, 1h bucket)
seen = set()
ded = []
for r in rows:
    key = (r.get("symbol"), r.get("side"), r.get("skip_reason"),
           str(r.get("created_at", ""))[:13])
    if key in seen:
        continue
    seen.add(key)
    ded.append(r)
print(f"after dedupe    : {len(ded)}")


def stats(sub):
    n = len(sub)
    pnl = [float(r["hypothetical_pnl_pct"]) for r in sub]
    tp1 = sum(1 for r in sub if r.get("would_hit_tp1"))
    slh = sum(1 for r in sub if r.get("would_hit_sl"))
    mean = sum(pnl) / n
    var = sum((x - mean) ** 2 for x in pnl) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n) if n else 0.0
    return n, mean, se, 100 * tp1 / n, 100 * slh / n, sorted(pnl)[n // 2]


print("\n" + "=" * 94)
print("GATE SCORECARD — mean counterfactual PnL% of the signals each gate BLOCKED")
print("  positive mean => the gate blocked trades that would have WON (gate costs money)")
print("  negative mean => the gate blocked losers (gate earns its keep)")
print("=" * 94)
byreason = collections.defaultdict(list)
for r in ded:
    byreason[r.get("skip_reason") or "(none)"].append(r)

print(f"{'skip_reason':<34}{'n':>6}{'mean%':>9}{'±se':>8}{'tp1%':>7}{'sl%':>7}{'med%':>8}  verdict")
print("-" * 94)
summary = {}
for reason, sub in sorted(byreason.items(), key=lambda x: -len(x[1])):
    n, mean, se, tp1r, slr, med = stats(sub)
    if n < 13:
        verdict = "INSUFFICIENT (n<13)"
    elif mean - 2 * se > 0:
        verdict = "GATE BLOCKS WINNERS"
    elif mean + 2 * se < 0:
        verdict = "gate blocks losers (good)"
    else:
        verdict = "no signal (CI spans 0)"
    print(f"{reason[:33]:<34}{n:>6}{mean:>9.2f}{se:>8.2f}{tp1r:>7.1f}{slr:>7.1f}{med:>8.2f}  {verdict}")
    summary[reason] = {"n": n, "mean_pnl_pct": round(mean, 3), "se": round(se, 3),
                       "tp1_rate": round(tp1r, 1), "sl_rate": round(slr, 1),
                       "median_pnl_pct": round(med, 3), "verdict": verdict}

n, mean, se, tp1r, slr, med = stats(ded)
print("-" * 94)
print(f"{'ALL BLOCKED (baseline/null)':<34}{n:>6}{mean:>9.2f}{se:>8.2f}{tp1r:>7.1f}{slr:>7.1f}{med:>8.2f}")

print("\n=== by symbol (all blocked) ===")
bysym = collections.defaultdict(list)
for r in ded:
    bysym[r.get("symbol")].append(r)
for s, sub in sorted(bysym.items(), key=lambda x: -len(x[1]))[:10]:
    n, mean, se, tp1r, slr, med = stats(sub)
    flag = "  [n<13]" if n < 13 else ""
    print(f"  {str(s):<7} n={n:>5} mean={mean:>7.2f}% ±{se:.2f}  tp1={tp1r:>5.1f}% sl={slr:>5.1f}%{flag}")

print("\n=== by side (all blocked) ===")
byside = collections.defaultdict(list)
for r in ded:
    byside[(r.get("side") or "?").upper()].append(r)
for s, sub in sorted(byside.items(), key=lambda x: -len(x[1])):
    n, mean, se, tp1r, slr, med = stats(sub)
    print(f"  {s:<7} n={n:>5} mean={mean:>7.2f}% ±{se:.2f}  tp1={tp1r:>5.1f}% sl={slr:>5.1f}%")

with io.open(OUT + "gate_scorecard.json", "w", encoding="utf-8") as fh:
    json.dump({"source": SRC, "raw_rows": n_raw, "valid_rows": len(rows),
               "deduped_rows": len(ded), "rejected": dict(bad),
               "span": [ts[0], ts[-1]], "by_skip_reason": summary}, fh, indent=1)
print("\nwrote gate_scorecard.json")
