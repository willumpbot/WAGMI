"""Aggregate counterfactual blocks by GATE FAMILY, not by threshold.

skip_reason is logged as confidence_floor_65, _66, _67 ... which fragments one
gate into 26 tiny cells. Collapsing to the family gives usable n and lets us
test the server's two live findings on an earlier, independent period:

  server (2026-05-30 -> 10-05, live blocks):
    * trend-adjusted floor : -0.30% per blocked setup, CI excludes 0  (valuable)
    * confidence floor     : trimmed mean ~= 0                        (no value)

  here   (2026-03-23 -> 05-01, counterfactual resolutions)

Bootstrap CI is clustered on (symbol, UTC day) to respect repeated scans of the
same setup, matching the server's method.
"""
import json, collections, io, math, re, random

SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/llm/counterfactual_resolved.jsonl"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/"
random.seed(12345)  # fixed seed: Math.random/Date are unavailable to workflows; keep reproducible


def family(reason):
    r = (reason or "(none)").strip()
    m = re.match(r"^(confidence_floor|trend_adj_floor)_(\d+)$", r)
    if m:
        return m.group(1), int(m.group(2))
    if r.startswith("[MA]"):
        return "manager_advice", None
    return r[:40], None


def validate(d):
    side = (d.get("side") or "").upper()
    e, sl, tp1 = d.get("entry_price"), d.get("sl"), d.get("tp1")
    mf, ma = d.get("max_favorable_price"), d.get("max_adverse_price")
    pnl = d.get("hypothetical_pnl_pct")
    for v in (e, sl, tp1, mf, ma, pnl):
        if not isinstance(v, (int, float)) or (isinstance(v, float) and math.isnan(v)):
            return None
    if e <= 0 or sl <= 0 or tp1 <= 0 or abs(pnl) > 100:
        return None
    if side in ("BUY", "LONG"):
        if not (sl < e < tp1) or ma > e or mf < e:
            return None
        reached = mf >= tp1
    elif side in ("SELL", "SHORT"):
        if not (tp1 < e < sl) or ma < e or mf > e:
            return None
        reached = mf <= tp1
    else:
        return None
    if bool(d.get("would_hit_tp1")) != bool(reached):
        return None
    return side


rows = []
with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not d.get("resolved"):
            continue
        side = validate(d)
        if not side:
            continue
        fam, thr = family(d.get("skip_reason"))
        rows.append({
            "fam": fam, "thr": thr, "sym": d.get("symbol"), "side": side,
            "day": str(d.get("created_at", ""))[:10],
            "hour": str(d.get("created_at", ""))[:13],
            "pnl": float(d["hypothetical_pnl_pct"]),
            "tp1": bool(d.get("would_hit_tp1")), "sl": bool(d.get("would_hit_sl")),
            "conf": d.get("confidence"),
        })

# dedupe on (symbol, side, family, hour) — NOT threshold, so one gate isn't
# counted once per threshold value within the same hour
seen, ded = set(), []
for r in rows:
    k = (r["sym"], r["side"], r["fam"], r["hour"])
    if k in seen:
        continue
    seen.add(k)
    ded.append(r)

print(f"valid rows {len(rows)} -> deduped {len(ded)}")
print(f"span {min(r['day'] for r in ded)} -> {max(r['day'] for r in ded)}")


def boot_ci(sub, iters=4000):
    """Cluster bootstrap over (symbol, day)."""
    clusters = collections.defaultdict(list)
    for r in sub:
        clusters[(r["sym"], r["day"])].append(r["pnl"])
    keys = list(clusters)
    if len(keys) < 3:
        return None, None
    means = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(clusters[keys[random.randrange(len(keys))]])
        if pool:
            means.append(sum(pool) / len(pool))
    means.sort()
    return means[int(0.025 * len(means))], means[int(0.975 * len(means))]


print("\n" + "=" * 100)
print("GATE FAMILY SCORECARD — mean counterfactual PnL% of signals the gate BLOCKED")
print("  mean < 0 and CI excludes 0  => gate blocked losers  => gate EARNS ITS KEEP")
print("  mean > 0 and CI excludes 0  => gate blocked winners => gate COSTS MONEY")
print("=" * 100)
print(f"{'gate family':<22}{'n':>6}{'clusters':>9}{'mean%':>9}{'CI95':>20}{'tp1%':>7}{'sl%':>7}  verdict")
print("-" * 100)

byfam = collections.defaultdict(list)
for r in ded:
    byfam[r["fam"]].append(r)

out = {}
for fam, sub in sorted(byfam.items(), key=lambda x: -len(x[1])):
    n = len(sub)
    pnl = [r["pnl"] for r in sub]
    mean = sum(pnl) / n
    lo, hi = boot_ci(sub)
    ncl = len({(r["sym"], r["day"]) for r in sub})
    tp1r = 100 * sum(1 for r in sub if r["tp1"]) / n
    slr = 100 * sum(1 for r in sub if r["sl"]) / n
    if n < 13:
        verdict = "INSUFFICIENT (n<13)"
    elif lo is None:
        verdict = "too few clusters"
    elif hi < 0:
        verdict = "BLOCKS LOSERS (keeps value)"
    elif lo > 0:
        verdict = "BLOCKS WINNERS (costs money)"
    else:
        verdict = "no signal (CI spans 0)"
    ci = f"[{lo:+.3f},{hi:+.3f}]" if lo is not None else "n/a"
    print(f"{fam[:21]:<22}{n:>6}{ncl:>9}{mean:>9.3f}{ci:>20}{tp1r:>7.1f}{slr:>7.1f}  {verdict}")
    out[fam] = {"n": n, "clusters": ncl, "mean_pnl_pct": round(mean, 4),
                "ci95": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                "tp1_rate": round(tp1r, 1), "sl_rate": round(slr, 1),
                "verdict": verdict}

n = len(ded)
pnl = [r["pnl"] for r in ded]
mean = sum(pnl) / n
lo, hi = boot_ci(ded)
print("-" * 100)
print(f"{'ALL BLOCKED (null)':<22}{n:>6}{len({(r['sym'],r['day']) for r in ded}):>9}"
      f"{mean:>9.3f}{f'[{lo:+.3f},{hi:+.3f}]':>20}")
out["_null_all_blocked"] = {"n": n, "mean_pnl_pct": round(mean, 4),
                            "ci95": [round(lo, 4), round(hi, 4)]}

# threshold monotonicity for the confidence floor: if the gate had skill, higher
# thresholds should block progressively better trades
print("\n=== confidence_floor: does blocked-trade quality vary with threshold? ===")
cf = [r for r in ded if r["fam"] == "confidence_floor" and r["thr"]]
buckets = collections.defaultdict(list)
for r in cf:
    b = "<=65" if r["thr"] <= 65 else ("66-70" if r["thr"] <= 70 else ">70")
    buckets[b].append(r["pnl"])
for b in ("<=65", "66-70", ">70"):
    v = buckets.get(b, [])
    if v:
        flag = "  [n<13]" if len(v) < 13 else ""
        print(f"  thr {b:<6} n={len(v):>4}  mean={sum(v)/len(v):+.3f}%{flag}")

with io.open(OUT + "gate_families.json", "w", encoding="utf-8") as fh:
    json.dump({"source": SRC, "span": [min(r['day'] for r in ded), max(r['day'] for r in ded)],
               "deduped_rows": len(ded), "families": out}, fh, indent=1)
print("\nwrote gate_families.json")
