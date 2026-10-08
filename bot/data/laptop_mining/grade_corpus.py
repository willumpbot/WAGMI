"""Mission 3: forward-grade the laptop signal corpus against real Hyperliquid candles.

Method mirrors bot/data/agent_grades (SCORECARD.md "Method" section) so results
are comparable to the server's:
  * p0      = last close at or before the signal timestamp (NO lookahead)
  * p(t+h)  = first close at or after t+h, h in {1h, 4h, 12h}
  * e_h     = forward return in the PROPOSED direction, minus 9 bps fees
  * SL/TP1-first resolved from bar highs/lows strictly AFTER t0
  * CIs     = cluster bootstrap over (symbol, UTC day)
  * n<13 flagged insufficient; n_eff = distinct (symbol, day) clusters

Corpus is already de-duplicated on (symbol, side, strategy, entry, 1h bucket).
Candle coverage starts 2026-03-14 (Hyperliquid's public history limit), so
February signals are reported as ungradeable rather than silently dropped.
"""
import json, io, os, csv, math, collections, random, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "signal_corpus.jsonl.gz")
CANDLES = os.path.join(HERE, "candles")
FEE_BPS = 9.0
random.seed(20261008)

H = {"1h": 3600, "4h": 4 * 3600, "12h": 12 * 3600}


MERGED = os.path.join(HERE, "candles_merged")


def load_candles(sym):
    # Prefer the validated merged store (local cache verified against HL, or
    # verified by 1h->6h internal consistency; HL wins on overlap). Fall back to
    # the plain HL pull for symbols whose cache was REJECTED (HYPE, DOGE) or
    # absent -- HL itself is always trusted.
    p = os.path.join(MERGED, f"{sym}_1h.csv")
    if not os.path.exists(p):
        p = os.path.join(CANDLES, f"{sym}_1h.csv")
    if not os.path.exists(p):
        return None
    out = []
    with io.open(p, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                            float(r["l"]), float(r["c"])))
            except (TypeError, ValueError):
                continue
    out.sort()
    return out or None


def to_epoch(ts):
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def px_at_or_before(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


def px_at_or_after(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] >= t:
            best = m; hi = m - 1
        else:
            lo = m + 1
    return best


import gzip
sig = []
with gzip.open(CORPUS, "rt", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if line:
            sig.append(json.loads(line))
print(f"corpus rows            : {len(sig)}")

cache, graded = {}, []
skip = collections.Counter()

for s in sig:
    sym = s["sym"]
    if sym not in cache:
        cache[sym] = load_candles(sym)
    c = cache[sym]
    if not c:
        skip["no_candles_for_symbol"] += 1
        continue
    t0 = to_epoch(s["ts"])
    if t0 is None:
        skip["bad_timestamp"] += 1
        continue
    i0 = px_at_or_before(c, t0)
    if i0 is None:
        skip["before_candle_history"] += 1
        continue
    if t0 - c[i0][0] > 2 * 3600:
        skip["stale_p0_gap"] += 1
        continue
    p0 = c[i0][4]
    if p0 <= 0:
        skip["bad_p0"] += 1
        continue
    sgn = 1.0 if s["side"] == "LONG" else -1.0
    rec = {"ts": s["ts"], "day": s["ts"][:10], "sym": sym, "side": s["side"],
           "conf": s["conf"], "num_agree": s["num_agree"],
           "regime_score": s.get("regime_score"), "trace_id": s.get("trace_id"),
           "rr1": s.get("rr1"), "stop_pct": s.get("stop_pct"), "p0": p0}
    ok = False
    for name, dt in H.items():
        j = px_at_or_after(c, t0 + dt)
        # Only 1h bars are available this far back (HL serves 15m from Aug 16,
        # 5m from Sep 20), so the server's <=30min staleness is unreachable here.
        # Use the OPEN of the first bar starting at or after t0+dt -- a tradeable
        # price at that boundary -- and allow one bar (3600s) of tolerance.
        if j is None or c[j][0] - (t0 + dt) > 3600:
            rec["e_" + name] = None
            continue
        ret = sgn * (c[j][1] - p0) / p0
        rec["e_" + name] = 1e4 * ret - FEE_BPS   # bps, net of fees
        ok = True
    if not ok:
        skip["no_horizon_resolvable"] += 1
        continue
    # SL / TP1 first, using bars strictly after t0, 24h window
    sl, tp1 = s["sl"], s["tp1"]
    first = None
    k = i0 + 1
    end = t0 + 24 * 3600
    while k < len(c) and c[k][0] <= end:
        hi, lo = c[k][2], c[k][3]
        if s["side"] == "LONG":
            hit_tp, hit_sl = hi >= tp1, lo <= sl
        else:
            hit_tp, hit_sl = lo <= tp1, hi >= sl
        if hit_tp and hit_sl:
            first = "both_same_bar"; break
        if hit_tp:
            first = "tp1"; break
        if hit_sl:
            first = "sl"; break
        k += 1
    rec["first_hit"] = first
    graded.append(rec)
    ok = True

print(f"graded                 : {len(graded)}")
print(f"skipped                : {dict(skip)}")
if not graded:
    raise SystemExit("nothing graded")

days = sorted({g["day"] for g in graded})
print(f"gradeable span         : {days[0]} -> {days[-1]} ({len(days)} days)")
ung = skip["before_candle_history"]
print(f"UNGRADEABLE (pre-candle-history): {ung} signals "
      f"({100*ung/len(sig):.1f}% of corpus) -- Hyperliquid public history starts 2026-03-14")


def boot(vals_by_cluster, iters=3000):
    keys = list(vals_by_cluster)
    if len(keys) < 3:
        return None, None
    ms = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(vals_by_cluster[keys[random.randrange(len(keys))]])
        if pool:
            ms.append(sum(pool) / len(pool))
    ms.sort()
    return ms[int(0.025 * len(ms))], ms[int(0.975 * len(ms))]


def cell(rows, h):
    v = [r["e_" + h] for r in rows if r.get("e_" + h) is not None]
    if not v:
        return None
    cl = collections.defaultdict(list)
    for r in rows:
        if r.get("e_" + h) is not None:
            cl[(r["sym"], r["day"])].append(r["e_" + h])
    lo, hi = boot(cl)
    mean = sum(v) / len(v)
    return {"n": len(v), "n_eff": len(cl), "mean_bps": round(mean, 2),
            "ci": [round(lo, 2), round(hi, 2)] if lo is not None else None,
            "hit": round(100 * sum(1 for x in v if x > 0) / len(v), 1)}


def show(label, rows, minn=13):
    parts = []
    for h in ("1h", "4h", "12h"):
        c = cell(rows, h)
        parts.append("    n/a    " if not c else
                     f"{c['mean_bps']:>8.1f}" + ("*" if c["ci"] and (c["ci"][1] < 0 or c["ci"][0] > 0) else " "))
    c4 = cell(rows, "4h")
    n = c4["n"] if c4 else 0
    ne = c4["n_eff"] if c4 else 0
    hit = f"{c4['hit']:>5.1f}" if c4 else "  -  "
    ci = f"[{c4['ci'][0]:>7.1f},{c4['ci'][1]:>7.1f}]" if c4 and c4["ci"] else " " * 17
    flag = "  n<13" if n < minn else ""
    print(f"  {label:<20}{n:>6}{ne:>7}{''.join(parts)}{hit}  {ci}{flag}")


print("\n" + "=" * 104)
print("FORWARD GRADE — laptop signal corpus, bps net of 9 bps fees  (* = 95% CI excludes 0)")
print("=" * 104)
print(f"  {'slice':<20}{'n':>6}{'n_eff':>7}{'1h':>9}{'4h':>9}{'12h':>9}{'hit4h':>6}  {'CI95 (4h)':^17}")
print("-" * 104)
show("ALL (null/baseline)", graded)

print("\n  -- by side --")
byside = collections.defaultdict(list)
for g in graded:
    byside[g["side"]].append(g)
for k in sorted(byside):
    show(k, byside[k])

print("\n  -- by symbol --")
bysym = collections.defaultdict(list)
for g in graded:
    bysym[g["sym"]].append(g)
for k, v in sorted(bysym.items(), key=lambda x: -len(x[1])):
    show(k, v)

print("\n  -- by num_agree --")
byag = collections.defaultdict(list)
for g in graded:
    a = int(g["num_agree"])
    byag[f"agree={a}" if a <= 2 else "agree>=3"].append(g)
for k in sorted(byag):
    show(k, byag[k])

print("\n  -- by confidence bucket --")
bycf = collections.defaultdict(list)
for g in graded:
    c = g["conf"]
    b = "<50" if c < 50 else ("50-59" if c < 60 else ("60-69" if c < 70 else
        ("70-79" if c < 80 else ">=80")))
    bycf[b].append(g)
for k in ("<50", "50-59", "60-69", "70-79", ">=80"):
    if k in bycf:
        show("conf " + k, bycf[k])

print("\n  -- by month --")
bymo = collections.defaultdict(list)
for g in graded:
    bymo[g["ts"][:7]].append(g)
for k in sorted(bymo):
    show(k, bymo[k])

print("\n=== SL/TP1-first within 24h ===")
fh_ = collections.Counter(g["first_hit"] for g in graded)
tot = sum(fh_.values())
for k, v in fh_.most_common():
    print(f"  {str(k):<16} {v:>6}  ({100*v/tot:>5.1f}%)")

# confidence informativeness: Spearman-ish rank correlation with 4h outcome
pairs = [(g["conf"], g["e_4h"]) for g in graded if g.get("e_4h") is not None]
if len(pairs) > 30:
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    a = ranks([p[0] for p in pairs]); b = ranks([p[1] for p in pairs])
    n = len(pairs)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((x - mb) ** 2 for x in b))
    print(f"\nconfidence -> 4h outcome rank corr: {num/den if den else 0:+.4f}  (n={n}; 0 = uninformative)")

out = {"corpus_rows": len(sig), "graded": len(graded), "skipped": dict(skip),
       "span": [days[0], days[-1]], "fee_bps": FEE_BPS,
       "all": {h: cell(graded, h) for h in ("1h", "4h", "12h")},
       "by_side": {k: cell(v, "4h") for k, v in byside.items()},
       "by_symbol": {k: cell(v, "4h") for k, v in bysym.items()},
       "by_num_agree": {k: cell(v, "4h") for k, v in byag.items()},
       "by_conf": {k: cell(v, "4h") for k, v in bycf.items()},
       "by_month": {k: cell(v, "4h") for k, v in bymo.items()},
       "first_hit": dict(fh_)}
with io.open(os.path.join(HERE, "regrade.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
with gzip.open(os.path.join(HERE, "graded_signals.jsonl.gz"), "wt", encoding="utf-8") as fh:
    for g in graded:
        fh.write(json.dumps(g) + "\n")
print("\nwrote regrade.json + graded_signals.jsonl.gz")
