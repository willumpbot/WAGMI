"""Geometry v3 — the direction-free estimator, done properly, on ALL 24 cells.

v2's null was algebraically (geometry) - (direction), so it read ~0 whenever the
two were the same size, which is what this data shows. Red team wj68xvlf8 caught
it; GEOMETRY_V3.md has the derivation. Verified identity over 23 cells:

    sym_adv + dir_adv == real_adv     (max err 5.6e-17)
    sym_adv - dir_adv == flip_adv     (max err 3.5e-17)   <- v2's "null"

where sym = (real+flip)/2 is the direction-free component and dir = (real-flip)/2
is the directional one. v2 computed neither.

This script fixes the four defects the red team found:

  D1  the null ran on 5 hand-picked cells while the write-up claimed 24.
      -> every estimator here runs on all 24, nothing hidden.
  D2  it had no power: flip CI half-width 0.3103R vs a true effect of 0.1745R.
      -> explicit power curve by injection, reported before any verdict.
  D3  the verdict tracked the directional edge, not the geometry.
      -> SYNTHETIC CONTROL: build an exact-zero-effect dataset, confirm the false
         positive rate, then inject known effects and confirm detection. A null
         that cannot detect a known-real effect is not evidence of absence.
  D4  "x32 is the optimum" was read off a saturated surface where the bracket
      never binds (spread across targets = 0.0000).
      -> measure the BINDING RATE per cell and only consider cells that bind.

The question: how much of the +0.3479R is direction-free, with honest week-block
CIs on every cell, and what is the best stop width among cells that still bind?
"""
import json, io, os, gzip, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

import geometry_v2 as G2
from geometry_v2 import (load_candles, first_after, week_boot, rng,
                         FEE_BPS, HORIZON_H, CUTOFF, STOPS, TPS, DEFAULT, HERE)

CELLS = [f"{s}|{t}" for s in STOPS for t in TPS]
BIND_FLOOR = 0.50          # D4: a cell must resolve at stop-or-target this often to count
CAND = {}


def init(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def sim3(args):
    """Same simulation as v2, plus the exit reason so binding can be measured."""
    sym, rows = args
    c = CAND.get(sym)
    if not c:
        return [], {}
    out, bind = [], collections.Counter()
    for s in rows:
        i0 = first_after(c, s["t0"])
        if i0 is None or c[i0][0] - s["t0"] > 3600:
            continue
        entry, base = c[i0][1], s["base"]
        if entry <= 0 or base <= 0:
            continue
        bars, k, end = [], i0, s["t0"] + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if len(bars) < 2:
            continue
        rec = {"sym": sym, "day": s["day"], "week": s["week"]}
        for flip in (False, True):
            long_ = (s["side"] == "LONG") != flip
            tag = "flip" if flip else "real"
            for sm in STOPS:
                dist = sm * base
                sl = entry - dist if long_ else entry + dist
                feeR = 2 * (FEE_BPS / 1e4) * entry / dist
                for tm in TPS:
                    tp = entry + tm * dist if long_ else entry - tm * dist
                    r, why = None, "horizon"
                    for (_, o, h, l, cl) in bars[1:]:
                        hit_sl = (l <= sl) if long_ else (h >= sl)
                        hit_tp = (h >= tp) if long_ else (l <= tp)
                        if hit_sl:
                            r, why = -1.0, "stop"; break
                        if hit_tp:
                            r, why = tm, "target"; break
                    if r is None:
                        last = bars[-1][4]
                        r = ((last - entry) if long_ else (entry - last)) / dist
                    rec[f"{tag}|{sm}|{tm}"] = r - feeR
                    if not flip:                       # binding measured on real side
                        bind[f"{sm}|{tm}|{'bound' if why != 'horizon' else 'horizon'}"] += 1
        out.append(rec)
    return out, bind


def boot_ci(d, wk, iters=4000):
    """Week-block bootstrap on an already-differenced vector."""
    groups = [d[wk == w] for w in np.unique(wk)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 4:
        return float(d.mean()), None, None
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return float(d.mean()), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


def main():
    sigs = []
    with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            try:
                t0 = pd.Timestamp(d["ts"]).timestamp()
            except Exception:
                continue
            base = abs(float(d["entry"]) - float(d["sl"]))
            if base <= 0:
                continue
            day = d["ts"][:10]
            wk = datetime.date.fromisoformat(day).isocalendar()
            sigs.append({"sym": d["sym"], "side": d["side"], "base": base, "t0": t0,
                         "day": day, "week": f"{wk[0]}-W{wk[1]:02d}"})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    print(f"{len(sigs)} signals, {n} workers", flush=True)
    recs, bind = [], collections.Counter()
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for o, b in pool.imap_unordered(sim3, [(s, by[s]) for s in syms]):
            recs.extend(o); bind.update(b)
    df = pd.DataFrame(recs)
    print(f"simulated {len(df)}  weeks {df['week'].nunique()}  days {df['day'].nunique()}")
    wk = df["week"].values

    # ---- build the two orthogonal components, per row, per cell ----
    for cell in CELLS:
        rk, fk = f"real|{cell}", f"flip|{cell}"
        if rk in df.columns:
            df[f"sym|{cell}"] = (df[rk] + df[fk]) / 2.0
            df[f"dir|{cell}"] = (df[rk] - df[fk]) / 2.0

    out = {"n": int(len(df)), "weeks": int(df["week"].nunique()),
           "default": DEFAULT, "bind_floor": BIND_FLOOR,
           "fixes": ["(real+flip)/2 direction-free estimator",
                     "ALL 24 cells, nothing hand-picked",
                     "binding rate measured per cell",
                     "synthetic control + power curve before any verdict"],
           "cells": {}}

    # ---------------- D3: SYNTHETIC CONTROL, run BEFORE any verdict ----------------
    print("\n" + "=" * 104)
    print("SYNTHETIC CONTROL — can this estimator detect a known direction-free effect?")
    print("  built by removing the measured effect (true effect := 0), then injecting known deltas")
    print("=" * 104)
    probe = "8.0|0.5"
    ds = (df[f"sym|{probe}"] - df[f"sym|{DEFAULT}"]).values
    ds = ds[np.isfinite(ds)]
    wk_p = wk[np.isfinite((df[f"sym|{probe}"] - df[f"sym|{DEFAULT}"]).values)]
    h0 = ds - ds.mean()                     # exact-zero-effect dataset
    print(f"  probe cell {probe}, n={len(h0)}, measured effect {ds.mean():+.4f}R")
    print(f"  {'injected delta':>16}{'detected?':>12}{'CI95':>26}")
    print("-" * 104)
    power = {}
    for delta in (0.0, 0.02, 0.05, 0.08, 0.1232, 0.15, 0.1745, 0.25):
        pt, lo, hi = boot_ci(h0 + delta, wk_p)
        det = lo is not None and lo > 0
        power[f"{delta}"] = {"point": round(pt, 4), "detected": bool(det),
                             "ci": [round(lo, 4), round(hi, 4)] if lo is not None else None}
        note = "  <- false positive!" if (delta == 0.0 and det) else (
               "  <- fee-drag prediction" if abs(delta - 0.1232) < 1e-9 else "")
        print(f"  {delta:>16.4f}{('YES' if det else 'no'):>12}"
              f"{f'[{lo:+.4f},{hi:+.4f}]':>26}{note}")
    out["synthetic_control"] = power
    fp = power["0.0"]["detected"]
    smallest = next((d for d in (0.02, 0.05, 0.08, 0.1232, 0.15, 0.1745, 0.25)
                     if power[f"{d}"]["detected"]), None)
    print(f"\n  false positive at true effect 0 : {'YES - ESTIMATOR UNUSABLE' if fp else 'no (good)'}")
    print(f"  smallest detectable effect      : {smallest if smallest else 'none in range'} R")
    if fp:
        print("  ABORT: the estimator reports an effect where none exists.")
        return
    out["smallest_detectable_R"] = smallest

    # ---------------- D1 + D4: all 24 cells, with binding ----------------
    print("\n" + "=" * 112)
    print("ALL 24 CELLS — direction-free (sym) and directional (dir) advantage vs the bot default")
    print(f"  sym = (real+flip)/2 ; dir = (real-flip)/2 ; sym+dir = real advantage")
    print(f"  'bound' = % of trades resolved by stop or target, not by the {HORIZON_H}h horizon")
    print("=" * 112)
    print(f"  {'cell':<11}{'bound':>7}{'sym adv':>10}{'sym CI95 (week)':>24}"
          f"{'dir adv':>10}{'real adv':>10}  verdict")
    print("-" * 112)
    for cell in CELLS:
        if f"sym|{cell}" not in df.columns:
            continue
        b = bind.get(f"{cell}|bound", 0)
        hz = bind.get(f"{cell}|horizon", 0)
        br = b / (b + hz) if (b + hz) else 0.0
        m = np.isfinite((df[f"sym|{cell}"] - df[f"sym|{DEFAULT}"]).values)
        sp, slo, shi = boot_ci((df[f"sym|{cell}"] - df[f"sym|{DEFAULT}"]).values[m], wk[m])
        dp, _, _ = boot_ci((df[f"dir|{cell}"] - df[f"dir|{DEFAULT}"]).values[m], wk[m], iters=1)
        real_adv = sp + dp
        sig = slo is not None and slo > 0
        worse = shi is not None and shi < 0          # excludes zero on the LOW side
        binds = br >= BIND_FLOOR
        verdict = ("real & binds" if (sig and binds) else
                   "real but NO BRACKET" if sig else
                   "SIGNIFICANTLY WORSE" if worse else
                   "not significant")
        if cell == DEFAULT:
            verdict = "<= DEFAULT"
        ci = f"[{slo:+.4f},{shi:+.4f}]" if slo is not None else ""
        print(f"  {cell:<11}{100*br:>6.1f}%{sp:>10.4f}{ci:>24}{dp:>10.4f}"
              f"{real_adv:>10.4f}  {verdict}")
        out["cells"][cell] = {
            "bound_pct": round(100 * br, 1), "sym_adv": round(sp, 4),
            "sym_ci": [round(slo, 4), round(shi, 4)] if slo is not None else None,
            "dir_adv": round(dp, 4), "real_adv": round(real_adv, 4),
            "sym_significant": bool(sig), "sym_sig_worse": bool(worse),
            "binds": bool(binds)}

    # ---------------- the actionable answer ----------------
    print("\n" + "=" * 104)
    print("THE DECISION — best stop width among cells where the bracket actually binds")
    print("=" * 104)
    cand = [(k, v) for k, v in out["cells"].items()
            if v["binds"] and v["sym_significant"] and k != DEFAULT]
    if not cand:
        print("  no cell both binds and shows a significant direction-free advantage.")
        out["recommendation"] = None
    else:
        cand.sort(key=lambda kv: -kv[1]["sym_adv"])
        for k, v in cand[:6]:
            print(f"  {k:<11} sym {v['sym_adv']:+.4f}R  CI {v['sym_ci']}  "
                  f"bound {v['bound_pct']}%  (dir {v['dir_adv']:+.4f} unvalidated)")
        bk, bv = cand[0]
        print(f"\n  RECOMMEND {bk}: {bv['sym_adv']:+.4f}R direction-free, CI {bv['sym_ci']},")
        print(f"            bracket still binds on {bv['bound_pct']}% of trades.")
        print(f"            Ignore the {bv['dir_adv']:+.4f}R directional half - it is unvalidated.")
        out["recommendation"] = {"cell": bk, **bv}
    sat = [k for k, v in out["cells"].items() if not v["binds"]]
    print(f"\n  SATURATED (bracket never binds, do NOT read an optimum here): {len(sat)} cells")
    print(f"    {', '.join(sat[:12])}")
    out["saturated_cells"] = sat

    with io.open(os.path.join(HERE, "geometry_v3.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote geometry_v3.json")


if __name__ == "__main__":
    main()
