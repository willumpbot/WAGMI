"""What if chop_floor actually blocked instead of only warning?

From grade_gates.py: signals chop_floor flagged (warning/fail) returned -33.6 bps
at 4h (CI [-45.4,-16.5]), -37.4 at 12h, -13.7 at 1h, over n=12,725 and 84
symbol-day clusters -- significant at every horizon, the strongest effect found
anywhere in this investigation. But chop_floor is advisory: those signals passed
the stack and traded.

This quantifies the counterfactual properly:
  * flagged vs unflagged, with a bootstrap CI on the DIFFERENCE (the metric the
    rules manager actually scores), not just on each level
  * the surviving book if chop_floor hard-blocked
  * an honest train/test split, since one big in-sample cell proves little
  * the gate's own threshold/value distribution, to see whether the effect is
    monotone in how badly the floor was breached
"""
import json, io, os, csv, collections, random, datetime, math

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/logs/signal_outcomes_regime_backfilled.jsonl"
FEE_BPS = 9.0
CUTOFF = "2026-04-15"       # ~midpoint of the 03-29..04-28 span
random.seed(20261008)


def load_candles(sym):
    for d in (MERGED, HL):
        p = os.path.join(d, f"{sym}_1h.csv")
        if os.path.exists(p):
            out = []
            with io.open(p, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                                    float(r["l"]), float(r["c"])))
                    except (TypeError, ValueError):
                        continue
            out.sort()
            return out
    return None


def ib(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


def ia(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] >= t:
            best = m; hi = m - 1
        else:
            lo = m + 1
    return best


H = {"1h": 3600, "4h": 14400, "12h": 43200}
cache, rows = {}, []

with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        sym, side, ts = d.get("sym"), (d.get("side") or "").upper(), d.get("ts")
        if not sym or side not in ("BUY", "SELL", "LONG", "SHORT") or not isinstance(ts, (int, float)):
            continue
        if sym not in cache:
            cache[sym] = load_candles(sym)
        c = cache[sym]
        if not c:
            continue
        i0 = ib(c, ts)
        if i0 is None or ts - c[i0][0] > 7200:
            continue
        p0 = c[i0][4]
        if p0 <= 0:
            continue
        sgn = 1.0 if side in ("BUY", "LONG") else -1.0
        chop = None
        for a in (d.get("annotations") or []):
            if isinstance(a, dict) and a.get("gate") == "chop_floor":
                chop = a
                break
        rec = {"day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
               "sym": sym, "side": "LONG" if sgn > 0 else "SHORT",
               "passed": bool(d.get("passed")),
               "flagged": bool(chop and chop.get("severity") in ("warning", "fail")),
               "chop_sev": (chop or {}).get("severity"),
               "chop_val": (chop or {}).get("value"),
               "chop_thr": (chop or {}).get("threshold")}
        ok = False
        for name, dt in H.items():
            j = ia(c, ts + dt)
            if j is None or c[j][0] - (ts + dt) > 3600:
                rec["e_" + name] = None
                continue
            rec["e_" + name] = 1e4 * sgn * (c[j][1] - p0) / p0 - FEE_BPS
            ok = True
        if ok:
            rows.append(rec)

print(f"graded rows        : {len(rows)}")
print(f"chop_floor flagged : {sum(1 for r in rows if r['flagged'])}")
print(f"of which PASSED    : {sum(1 for r in rows if r['flagged'] and r['passed'])}"
      f"   <- these traded despite the warning")
days = sorted({r["day"] for r in rows})
print(f"span               : {days[0]} -> {days[-1]}")


def diff_boot(sub, key, pred, iters=3000):
    """Bootstrap the IN-minus-OUT difference over (symbol, day) clusters."""
    cl = collections.defaultdict(lambda: ([], []))
    for r in sub:
        v = r.get(key)
        if v is None:
            continue
        b = cl[(r["sym"], r["day"])]
        (b[0] if pred(r) else b[1]).append(v)
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    ins = [x for k in keys for x in cl[k][0]]
    out = [x for k in keys for x in cl[k][1]]
    if not ins or not out:
        return None, None, None
    point = sum(ins) / len(ins) - sum(out) / len(out)
    ds = []
    for _ in range(iters):
        a, b = [], []
        for _ in range(len(keys)):
            k = keys[random.randrange(len(keys))]
            a.extend(cl[k][0]); b.extend(cl[k][1])
        if a and b:
            ds.append(sum(a) / len(a) - sum(b) / len(b))
    ds.sort()
    return point, ds[int(.025 * len(ds))], ds[int(.975 * len(ds))]


print("\n" + "=" * 100)
print("chop_floor FLAGGED minus UNFLAGGED  (the metric the rules manager scores)")
print("=" * 100)
print(f"  {'window':<22}{'n_flag':>8}{'n_clean':>9}{'horizon':>9}{'diff bps':>10}  CI95")
print("-" * 100)
res = {}
for label, sub in (("full span", rows),
                   (f"train <{CUTOFF}", [r for r in rows if r["day"] < CUTOFF]),
                   (f"test >={CUTOFF}", [r for r in rows if r["day"] >= CUTOFF])):
    nf = sum(1 for r in sub if r["flagged"])
    nc = len(sub) - nf
    for h in ("1h", "4h", "12h"):
        p, lo, hi = diff_boot(sub, "e_" + h, lambda r: r["flagged"])
        if p is None:
            continue
        sig = "*" if (hi < 0 or lo > 0) else " "
        print(f"  {label:<22}{nf:>8}{nc:>9}{h:>9}{p:>9.1f}{sig} [{lo:>7.1f},{hi:>7.1f}]")
        res[f"{label}|{h}"] = {"diff": round(p, 2), "ci": [round(lo, 2), round(hi, 2)],
                               "n_flagged": nf, "n_clean": nc,
                               "significant": bool(hi < 0 or lo > 0)}
    print("-" * 100)

# ---- the surviving book if chop_floor hard-blocked ----
print("\n=== the book, if chop_floor hard-blocked ===")
traded = [r for r in rows if r["passed"]]
kept = [r for r in traded if not r["flagged"]]
dropped = [r for r in traded if r["flagged"]]


def mean_ci(sub, key):
    cl = collections.defaultdict(list)
    for r in sub:
        if r.get(key) is not None:
            cl[(r["sym"], r["day"])].append(r[key])
    keys = list(cl)
    v = [x for k in keys for x in cl[k]]
    if not v or len(keys) < 3:
        return (sum(v) / len(v) if v else None), None, None, len(v)
    ms = []
    for _ in range(2500):
        pool = []
        for _ in range(len(keys)):
            pool.extend(cl[keys[random.randrange(len(keys))]])
        if pool:
            ms.append(sum(pool) / len(pool))
    ms.sort()
    return sum(v) / len(v), ms[int(.025 * len(ms))], ms[int(.975 * len(ms))], len(v)


for lab, sub in (("as traded (all passed)", traded),
                 ("kept (chop_floor clean)", kept),
                 ("would be dropped", dropped)):
    m, lo, hi, n = mean_ci(sub, "e_4h")
    ci = f"[{lo:>7.1f},{hi:>7.1f}]" if lo is not None else ""
    print(f"  {lab:<26} n={n:>6}  4h mean {m:>8.1f} bps  {ci}")

mt, _, _, nt = mean_ci(traded, "e_4h")
mk, _, _, nk = mean_ci(kept, "e_4h")
if mt is not None and mk is not None:
    print(f"\n  improvement from blocking: {mk - mt:+.1f} bps per traded signal")
    print(f"  volume cost: {100*(nt-nk)/nt:.1f}% of the traded book removed")

# ---- is the effect monotone in how badly the floor was breached? ----
print("\n=== monotone in the breach size? (flagged rows only) ===")
fl = [r for r in rows if r["flagged"] and isinstance(r.get("chop_val"), (int, float))
      and isinstance(r.get("chop_thr"), (int, float)) and r["chop_thr"]]
if fl:
    for r in fl:
        r["gap"] = (r["chop_thr"] - r["chop_val"]) / r["chop_thr"]
    fl.sort(key=lambda r: r["gap"])
    q = len(fl) // 4 or 1
    for i, lab in enumerate(("Q1 smallest breach", "Q2", "Q3", "Q4 largest breach")):
        sub = fl[i * q:(i + 1) * q] if i < 3 else fl[3 * q:]
        m, lo, hi, n = mean_ci(sub, "e_4h")
        ci = f"[{lo:>7.1f},{hi:>7.1f}]" if lo is not None else ""
        gaps = [r["gap"] for r in sub]
        print(f"  {lab:<20} n={n:>5}  gap {min(gaps):.2f}-{max(gaps):.2f}  "
              f"4h {m:>8.1f} bps {ci}")
else:
    print("  no numeric value/threshold pairs available")

with io.open(os.path.join(HERE, "chop_floor.json"), "w", encoding="utf-8") as fh:
    json.dump({"source": SRC, "graded": len(rows), "span": [days[0], days[-1]],
               "cutoff": CUTOFF, "flagged_minus_unflagged": res,
               "book_as_traded_4h": round(mt, 2) if mt is not None else None,
               "book_if_blocked_4h": round(mk, 2) if mk is not None else None,
               "improvement_bps": round(mk - mt, 2)
               if (mt is not None and mk is not None) else None,
               "volume_removed_pct": round(100 * (nt - nk) / nt, 1) if nt else None},
              fh, indent=1)
print("\nwrote chop_floor.json")
