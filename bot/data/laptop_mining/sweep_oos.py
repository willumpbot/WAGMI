"""The test that killed everything else, applied to the geometry finding.

chop_floor looked like the strongest effect in the investigation until the
in-minus-out metric and a train/test split were applied, at which point the sign
flipped between halves. The geometry result has not yet faced that test, so it
gets it here before anyone acts on it.

Three checks:
  1. TRAIN/TEST  -- fit the grid on 2026-02-11..04-15, re-score on 04-16..06-05.
                    Does the cell chosen in train still beat the bot default in test?
  2. PER-SYMBOL  -- does the ranking hold on BTC, ETH, HYPE and SOL separately,
                    or is it one symbol carrying it?
  3. MONOTONICITY -- Spearman rank correlation of mean_R against stop_mult.
                    Monotone-in-both-axes is the actual evidence here; a single
                    best cell is not.

Deliberately NOT re-picking the best cell on the full sample.
"""
import json, io, os, gzip, csv, collections, random, math
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
FEE_BPS = 9.0
HORIZON_H = 48
CUTOFF = "2026-04-16"
random.seed(20261008)

STOP_MULTS = (1.0, 2.0, 4.0, 6.0, 8.0, 12.0)
TP_MULTS = (0.5, 1.0, 1.5)
DEFAULT = (1.0, 1.5)


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


def to_epoch(ts):
    import datetime
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
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


CAND = {}


def init_worker(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def run_symbol(args):
    sym, sigs = args
    c = CAND.get(sym)
    if not c:
        return sym, []
    out = []
    for s in sigs:
        t0 = s["t0"]
        i0 = ib(c, t0)
        if i0 is None or t0 - c[i0][0] > 7200:
            continue
        entry = c[i0][4]
        base = abs(entry - s["sl"])
        if entry <= 0 or base <= 0:
            continue
        long_ = s["side"] == "LONG"
        bars = []
        k = i0 + 1
        end = t0 + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if not bars:
            continue
        cells = {}
        for sm in STOP_MULTS:
            dist = sm * base
            sl = entry - dist if long_ else entry + dist
            feeR = 2 * (FEE_BPS / 1e4) * entry / dist
            for tm in TP_MULTS:
                tp = entry + tm * dist if long_ else entry - tm * dist
                r = None
                for (_, o, h, l, cl) in bars:
                    if long_:
                        hit_sl, hit_tp = l <= sl, h >= tp
                    else:
                        hit_sl, hit_tp = h >= sl, l <= tp
                    if hit_sl:
                        r = -1.0; break
                    if hit_tp:
                        r = tm; break
                if r is None:
                    last = bars[-1][4]
                    r = ((last - entry) if long_ else (entry - last)) / dist
                cells[f"{sm}|{tm}"] = r - feeR
        out.append({"sym": sym, "day": s["day"], "cells": cells})
    return sym, out


def mean_of(recs, key):
    v = [r["cells"][key] for r in recs if key in r["cells"]]
    return (sum(v) / len(v)) if v else None


def boot_diff(recs, key_a, key_b, iters=2500):
    cl = collections.defaultdict(list)
    for r in recs:
        if key_a in r["cells"] and key_b in r["cells"]:
            cl[(r["sym"], r["day"])].append(r["cells"][key_a] - r["cells"][key_b])
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    allv = [x for k in keys for x in cl[k]]
    point = sum(allv) / len(allv)
    ds = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(cl[keys[random.randrange(len(keys))]])
        if pool:
            ds.append(sum(pool) / len(pool))
    ds.sort()
    return point, ds[int(.025 * len(ds))], ds[int(.975 * len(ds))]


def spearman(xs, ys):
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for p, i in enumerate(o):
            r[i] = p
        return r
    a, b = rk(xs), rk(ys)
    n = len(xs)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((x - mb) ** 2 for x in b))
    return num / den if den else 0.0


def main():
    sigs = []
    with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            t0 = to_epoch(d["ts"])
            if t0 is not None:
                sigs.append({"sym": d["sym"], "side": d["side"], "sl": d["sl"],
                             "t0": t0, "day": d["ts"][:10]})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    nproc = max(1, min(cpu_count() - 2, len(syms)))
    print(f"signals {len(sigs)}, workers {nproc}/{cpu_count()}", flush=True)

    recs = []
    with Pool(nproc, initializer=init_worker, initargs=(syms,)) as pool:
        for sym, out in pool.imap_unordered(run_symbol, [(s, by[s]) for s in syms]):
            recs.extend(out)
    print(f"simulated {len(recs)} signals", flush=True)

    dk = f"{DEFAULT[0]}|{DEFAULT[1]}"
    train = [r for r in recs if r["day"] < CUTOFF]
    test = [r for r in recs if r["day"] >= CUTOFF]
    print(f"train {len(train)} ({min(r['day'] for r in train)}..{max(r['day'] for r in train)})  "
          f"test {len(test)} ({min(r['day'] for r in test)}..{max(r['day'] for r in test)})")

    # ---- 1. train/test ----
    cells = [f"{sm}|{tm}" for sm in STOP_MULTS for tm in TP_MULTS]
    tr = sorted(((mean_of(train, c), c) for c in cells), key=lambda x: -(x[0] or -9))
    picked = tr[0][1]
    print("\n" + "=" * 96)
    print("1. TRAIN/TEST — cell chosen on train only, then scored on test")
    print("=" * 96)
    print(f"  picked on train : stop x{picked.split('|')[0]} tp {picked.split('|')[1]}R "
          f"-> train mean {tr[0][0]:+.4f}R")
    print(f"  bot default     : train mean {mean_of(train, dk):+.4f}R")
    pt, pte = mean_of(test, picked), mean_of(test, dk)
    print(f"\n  ON TEST  picked {pt:+.4f}R   default {pte:+.4f}R   "
          f"advantage {pt - pte:+.4f}R")
    p, lo, hi = boot_diff(test, picked, dk)
    if p is not None:
        sig = "CI EXCLUDES 0 — holds out of sample" if lo > 0 else "CI spans 0 — not confirmed"
        print(f"  paired diff on test: {p:+.4f}R  CI95 [{lo:+.4f}, {hi:+.4f}]  <= {sig}")

    # ---- 2. per symbol ----
    print("\n" + "=" * 96)
    print("2. PER-SYMBOL — is one symbol carrying it? (full span, picked vs default)")
    print("=" * 96)
    persym = {}
    for sym in sorted({r["sym"] for r in recs}):
        sub = [r for r in recs if r["sym"] == sym]
        if len(sub) < 200:
            continue
        a, b = mean_of(sub, picked), mean_of(sub, dk)
        p2, lo2, hi2 = boot_diff(sub, picked, dk)
        ci = f"[{lo2:+.4f},{hi2:+.4f}]" if p2 is not None else ""
        star = "*" if (p2 is not None and lo2 > 0) else " "
        print(f"  {sym:<6} n={len(sub):>5}  picked {a:+.4f}R  default {b:+.4f}R  "
              f"diff {a-b:+.4f}R{star} {ci}")
        persym[sym] = {"n": len(sub), "picked_R": round(a, 4), "default_R": round(b, 4),
                       "diff_R": round(a - b, 4),
                       "ci": [round(lo2, 4), round(hi2, 4)] if p2 is not None else None}

    # ---- 3. monotonicity ----
    print("\n" + "=" * 96)
    print("3. MONOTONICITY in stop_mult (the real evidence), per half")
    print("=" * 96)
    mono = {}
    for lab, sub in (("train", train), ("test", test), ("full", recs)):
        xs, ys = [], []
        for sm in STOP_MULTS:
            m = mean_of(sub, f"{sm}|1.0")
            if m is not None:
                xs.append(sm); ys.append(m)
        rho = spearman(xs, ys)
        mono[lab] = round(rho, 4)
        print(f"  {lab:<6} rho(stop_mult, mean_R) = {rho:+.4f}   "
              + "  ".join(f"x{x:g}:{y:+.3f}" for x, y in zip(xs, ys)))

    with io.open(os.path.join(HERE, "sweep_oos.json"), "w", encoding="utf-8") as fh:
        json.dump({"cutoff": CUTOFF, "horizon_h": HORIZON_H,
                   "picked_on_train": picked, "default": dk,
                   "train_n": len(train), "test_n": len(test),
                   "test_picked_R": round(pt, 4) if pt is not None else None,
                   "test_default_R": round(pte, 4) if pte is not None else None,
                   "test_paired_diff_R": round(p, 4) if p is not None else None,
                   "test_paired_ci": [round(lo, 4), round(hi, 4)] if p is not None else None,
                   "per_symbol": persym, "monotonicity_rho": mono}, fh, indent=1)
    print("\nwrote sweep_oos.json")


if __name__ == "__main__":
    main()
