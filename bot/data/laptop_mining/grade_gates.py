"""Does the gate stack add value? Grade passed vs rejected signals directly.

Source: WAGMI PROJECT/WAGMI/bot/data/logs/signal_outcomes_regime_backfilled.jsonl
83,432 rows, 2026-03-29 -> 2026-04-28, each carrying the gate decision
(`passed`, `hard_rej`, `rej_reason`) plus per-gate `annotations` with
severity/value/threshold. The counterfactual file only held BLOCKED signals;
this one holds both sides, so for the first time passed and rejected can be
compared on the same forward-return metric.

A gate stack earns its keep if passed signals beat rejected ones. Graded against
validated candles, cluster-bootstrapped over (symbol, UTC day), fees deducted.
"""
import json, io, os, csv, gzip, collections, random, datetime, math

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/logs/signal_outcomes_regime_backfilled.jsonl"
FEE_BPS = 9.0
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


rows = []
skip = collections.Counter()
cache = {}
H = {"1h": 3600, "4h": 14400, "12h": 43200}

with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            skip["unparseable"] += 1
            continue
        sym = d.get("sym")
        side = (d.get("side") or "").upper()
        ts = d.get("ts")
        if not sym or side not in ("BUY", "SELL", "LONG", "SHORT") or not isinstance(ts, (int, float)):
            skip["bad_fields"] += 1
            continue
        if sym not in cache:
            cache[sym] = load_candles(sym)
        c = cache[sym]
        if not c:
            skip["no_candles"] += 1
            continue
        i0 = ib(c, ts)
        if i0 is None or ts - c[i0][0] > 7200:
            skip["no_p0"] += 1
            continue
        p0 = c[i0][4]
        if p0 <= 0:
            skip["bad_p0"] += 1
            continue
        sgn = 1.0 if side in ("BUY", "LONG") else -1.0
        rec = {"day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
               "sym": sym, "side": "LONG" if sgn > 0 else "SHORT",
               "passed": bool(d.get("passed")), "hard_rej": bool(d.get("hard_rej")),
               "rej_reason": (d.get("rej_reason") or "")[:48],
               "conf": d.get("conf"), "n_agree": d.get("n_agree"),
               "regime": d.get("regime"),
               "gates": [a.get("gate") for a in (d.get("annotations") or [])
                         if isinstance(a, dict) and a.get("severity") in ("warning", "fail")]}
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
        else:
            skip["no_horizon"] += 1

print(f"rows graded : {len(rows)}")
print(f"skipped     : {dict(skip)}")
if not rows:
    raise SystemExit("nothing graded")
days = sorted({r["day"] for r in rows})
print(f"span        : {days[0]} -> {days[-1]} ({len(days)} days)")


def boot(sub, key, iters=2500):
    cl = collections.defaultdict(list)
    for r in sub:
        if r.get(key) is not None:
            cl[(r["sym"], r["day"])].append(r[key])
    keys = list(cl)
    if len(keys) < 3:
        return None, None
    ms = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(cl[keys[random.randrange(len(keys))]])
        if pool:
            ms.append(sum(pool) / len(pool))
    ms.sort()
    return ms[int(.025 * len(ms))], ms[int(.975 * len(ms))]


def show(label, sub, minn=13):
    v4 = [r["e_4h"] for r in sub if r.get("e_4h") is not None]
    if not v4:
        print(f"  {label:<28} n/a")
        return None
    out = [f"  {label:<28}{len(v4):>7}"]
    for key in ("e_1h", "e_4h", "e_12h"):
        v = [r[key] for r in sub if r.get(key) is not None]
        if not v:
            out.append(f"{'n/a':>10}")
            continue
        lo, hi = boot(sub, key)
        m = sum(v) / len(v)
        out.append(f"{m:>9.1f}" + ("*" if lo is not None and (hi < 0 or lo > 0) else " "))
    lo, hi = boot(sub, "e_4h")
    ci = f"[{lo:>7.1f},{hi:>7.1f}]" if lo is not None else ""
    ne = len({(r["sym"], r["day"]) for r in sub})
    flag = "  n<13" if len(v4) < minn else ""
    print("".join(out) + f"{ne:>6}  {ci}{flag}")
    return sum(v4) / len(v4)


print("\n" + "=" * 104)
print("GATE STACK VALUE — forward return in proposed direction, bps net of 9 bps (* CI excludes 0)")
print("=" * 104)
print(f"  {'slice':<28}{'n':>7}{'1h':>10}{'4h':>10}{'12h':>10}{'nEff':>6}  CI95 (4h)")
print("-" * 104)
allm = show("ALL (null)", rows)
pas = [r for r in rows if r["passed"]]
rej = [r for r in rows if not r["passed"]]
mp = show("PASSED the gate stack", pas)
mr = show("REJECTED by the stack", rej)
hard = [r for r in rows if r["hard_rej"]]
if hard:
    show("hard-rejected", hard)

if mp is not None and mr is not None:
    print("-" * 104)
    print(f"  PASSED minus REJECTED at 4h: {mp - mr:+.1f} bps")
    print("    positive => the stack selected better signals; negative => it selected worse")

print("\n  -- by rejection reason (rejected rows only) --")
byr = collections.defaultdict(list)
for r in rej:
    byr[r["rej_reason"] or "(none)"].append(r)
for k, v in sorted(byr.items(), key=lambda x: -len(x[1]))[:12]:
    show(k[:27], v)

print("\n  -- by gate that flagged warning/fail --")
byg = collections.defaultdict(list)
for r in rows:
    for g in set(r["gates"]):
        byg[g].append(r)
for k, v in sorted(byg.items(), key=lambda x: -len(x[1]))[:14]:
    show(str(k)[:27], v)

print("\n  -- by n_agree --")
bya = collections.defaultdict(list)
for r in rows:
    try:
        a = int(r["n_agree"] or 0)
    except (TypeError, ValueError):
        continue
    bya[f"agree={a}" if a <= 2 else "agree>=3"].append(r)
for k in sorted(bya):
    show(k, bya[k])

with io.open(os.path.join(HERE, "gate_value.json"), "w", encoding="utf-8") as fh:
    json.dump({"source": SRC, "graded": len(rows), "skipped": dict(skip),
               "span": [days[0], days[-1]],
               "all_4h": round(allm, 2) if allm is not None else None,
               "passed_4h": round(mp, 2) if mp is not None else None,
               "rejected_4h": round(mr, 2) if mr is not None else None,
               "passed_minus_rejected_4h": round(mp - mr, 2)
               if (mp is not None and mr is not None) else None,
               "n_passed": len(pas), "n_rejected": len(rej)}, fh, indent=1)
print("\nwrote gate_value.json")
