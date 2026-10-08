"""CORRECTED geometry analysis. Supersedes sweep_geometry / sweep_oos / geometry_walkforward.

RETRACTION.md records why the original was refuted. Every fix the reviewer named is
implemented here, and the result is whatever it is:

FIX 1 (fatal) -- entry lookahead. The original took `entry = close of the bar
  CONTAINING the signal` (up to 2h after it) while keeping the signal's ORIGINAL
  stop price, so when price drifted toward the stop in those minutes the simulated
  stop distance collapsed: 2.69% of signals got a stop under 0.3% of price vs 0.06%
  in the real signals. Since fees-in-R scale as 1/distance, that inflated a term
  worth 44% of the headline. Here: entry = OPEN of the first bar strictly AFTER the
  signal, and the stop distance is the bot's OWN |entry_sig - sl_sig|, never
  re-derived from a later price.

FIX 2 (fatal) -- no null. The side-flip null keeps the geometry, fees, bars, tie
  rule and horizon, and removes only the directional content. If the "geometry"
  advantage survives on side-flipped signals it is geometry; if it vanishes, the
  effect was the signals being directionally wrong and a tight stop levering that
  loss. Reported for every cell.

FIX 3 (fatal) -- hidden cells. The original printed "-" for tp 0.5R at stops 0.5,
  1.0 and 2.0 while the code computed them. ALL cells are printed here, and the
  cheap alternative (keep the stop, change only the target) is reported explicitly.

FIX 4 (major) -- bootstrap blocks. (symbol, day) is too fine on both axes: symbols
  move together (BTC/HYPE daily-mean corr +0.358) and a 48h trade spans two days.
  Blocks here are ISO weeks, resampled whole.

FIX 5 (major) -- fold slicing. The original sliced distinct SIGNAL-days, so its
  last "14-day fold" was 4 data-days straddling a 23-day hole. Folds here are
  CALENDAR windows.

FIX 6 (major) -- degrees of freedom. The surface is monotone in stop width, so
  argmax over a grid whose widest stop is its boundary is predetermined. The grid
  is extended well past the plateau so the argmax can be interior, and the
  selection is reported either way.
"""
import json, io, os, csv, gzip, collections, warnings, datetime
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL = os.path.join(HERE, "candles_merged"), os.path.join(HERE, "candles")
FEE_BPS = 9.0
HORIZON_H = 48
CUTOFF = "2026-04-16"
rng = np.random.default_rng(20261008)
STOPS = (0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 32.0)   # extended past the plateau
TPS = (0.5, 1.0, 1.5)
DEFAULT = "1.0|1.5"


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


def first_after(c, t):
    """Index of the first bar starting STRICTLY after t. No lookahead."""
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] > t:
            best = m; hi = m - 1
        else:
            lo = m + 1
    return best


CAND = {}


def init(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def sim(args):
    sym, rows = args
    c = CAND.get(sym)
    if not c:
        return []
    out = []
    for s in rows:
        i0 = first_after(c, s["t0"])
        if i0 is None or c[i0][0] - s["t0"] > 3600:
            continue
        entry = c[i0][1]                      # FIX 1: open of the next bar
        base = s["base"]                      # FIX 1: the bot's own stop distance
        if entry <= 0 or base <= 0:
            continue
        bars, k, end = [], i0, s["t0"] + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if len(bars) < 2:
            continue
        rec = {"sym": sym, "day": s["day"], "week": s["week"]}
        for flip in (False, True):            # FIX 2: side-flip null
            long_ = (s["side"] == "LONG") != flip
            tag = "flip" if flip else "real"
            for sm in STOPS:
                dist = sm * base
                sl = entry - dist if long_ else entry + dist
                feeR = 2 * (FEE_BPS / 1e4) * entry / dist
                for tm in TPS:
                    tp = entry + tm * dist if long_ else entry - tm * dist
                    r = None
                    for (_, o, h, l, cl) in bars[1:]:
                        hit_sl = (l <= sl) if long_ else (h >= sl)
                        hit_tp = (h >= tp) if long_ else (l <= tp)
                        if hit_sl:
                            r = -1.0; break
                        if hit_tp:
                            r = tm; break
                    if r is None:
                        last = bars[-1][4]
                        r = ((last - entry) if long_ else (entry - last)) / dist
                    rec[f"{tag}|{sm}|{tm}"] = r - feeR
        out.append(rec)
    return out


def week_boot(df, a, b, iters=2000):
    """FIX 4: paired difference, resampling whole ISO weeks."""
    sub = df[["week", a, b]].dropna()
    if not len(sub):
        return None, None, None
    d = (sub[a] - sub[b]).values
    wk = sub["week"].values
    groups = [d[wk == w] for w in np.unique(wk)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 4:
        return float(d.mean()), None, None
    point = float(d.mean())
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


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
            base = abs(float(d["entry"]) - float(d["sl"]))   # the bot's own distance
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
    print(f"{len(sigs)} signals, {n} workers, entry = open of next bar, "
          f"stop = bot's own distance", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for out in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(out)
    df = pd.DataFrame(recs)
    print(f"simulated {len(df)}  weeks {df['week'].nunique()}  days {df['day'].nunique()}")
    df["half"] = np.where(df["day"] < CUTOFF, "train", "test")

    CELLS = [f"{s}|{t}" for s in STOPS for t in TPS]
    out = {"fixes": ["entry=open of next bar", "stop=bot's own distance",
                     "side-flip null", "all cells printed", "ISO-week blocks",
                     "calendar folds", "grid extended past the plateau"],
           "n": int(len(df)), "cells": {}}

    print("\n" + "=" * 104)
    print("FULL SURFACE (nothing hidden) — mean R, real signals vs side-flipped null")
    print("=" * 104)
    print(f"  {'cell':<12}{'real R':>10}{'flip R':>10}{'real-flip':>11}"
          f"{'vs default':>12}{'CI95 (week blocks)':>24}")
    print("-" * 104)
    for cell in CELLS:
        rk, fk = f"real|{cell}", f"flip|{cell}"
        if rk not in df.columns:
            continue
        rm, fm = float(df[rk].mean()), float(df[fk].mean())
        p, lo, hi = week_boot(df, rk, f"real|{DEFAULT}")
        ci = f"[{lo:+.4f},{hi:+.4f}]" if lo is not None else ""
        star = "*" if (lo is not None and (lo > 0 or hi < 0)) else " "
        mark = "  <= DEFAULT" if cell == DEFAULT else ""
        print(f"  {cell:<12}{rm:>10.4f}{fm:>10.4f}{rm-fm:>11.4f}"
              f"{p:>11.4f}{star}{ci:>24}{mark}")
        out["cells"][cell] = {"real_R": round(rm, 4), "flip_R": round(fm, 4),
                              "real_minus_flip": round(rm - fm, 4),
                              "vs_default_R": round(p, 4),
                              "ci": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                              "significant": bool(lo is not None and (lo > 0 or hi < 0))}

    print("\n" + "=" * 104)
    print("THE DECISIVE TEST — does the advantage survive on SIDE-FLIPPED signals?")
    print("  if yes it is geometry; if no it was directional loss levered by a tight stop")
    print("=" * 104)
    for cell in ("8.0|0.5", "12.0|0.5", "12.0|1.0", "20.0|0.5", "32.0|0.5"):
        if f"real|{cell}" not in df.columns:
            continue
        pr, lr, hr = week_boot(df, f"real|{cell}", f"real|{DEFAULT}")
        pf, lf, hf = week_boot(df, f"flip|{cell}", f"flip|{DEFAULT}")
        cr = f"[{lr:+.4f},{hr:+.4f}]" if lr is not None else ""
        cf = f"[{lf:+.4f},{hf:+.4f}]" if lf is not None else ""
        verdict = ("GEOMETRY survives" if (lf is not None and lf > 0)
                   else "advantage is DIRECTIONAL, not geometric")
        print(f"  {cell:<10} real {pr:+.4f} {cr:<22} flip {pf:+.4f} {cf:<22} {verdict}")
        out["cells"].setdefault(cell, {}).update({
            "null_vs_default_R": round(pf, 4),
            "null_ci": [round(lf, 4), round(hf, 4)] if lf is not None else None,
            "geometry_survives_null": bool(lf is not None and lf > 0)})

    print("\n" + "=" * 104)
    print("FIX 3 — THE CHEAP ALTERNATIVE the original hid: keep the stop, change the target")
    print("=" * 104)
    for cell in ("1.0|0.5", "1.0|1.0", "1.0|1.5"):
        if f"real|{cell}" not in df.columns:
            continue
        p, lo, hi = week_boot(df, f"real|{cell}", f"real|{DEFAULT}")
        ci = f"[{lo:+.4f},{hi:+.4f}]" if lo is not None else ""
        print(f"  stop x1.0, tp {cell.split('|')[1]}R:  R {float(df[f'real|{cell}'].mean()):+.4f}"
              f"   vs default {p:+.4f} {ci}")
    out["cheap_alternative"] = {
        c: {"R": round(float(df[f"real|{c}"].mean()), 4),
            "vs_default": round(week_boot(df, f"real|{c}", f"real|{DEFAULT}")[0], 4)}
        for c in ("1.0|0.5", "1.0|1.0") if f"real|{c}" in df.columns}

    print("\n" + "=" * 104)
    print("FIX 5/6 — CALENDAR-day walk-forward, interior argmax allowed")
    print("=" * 104)
    days = sorted(df["day"].unique())
    d0 = datetime.date.fromisoformat(days[0])
    dN = datetime.date.fromisoformat(days[-1])
    folds, cur = [], d0 + datetime.timedelta(days=35)
    while cur < dN:
        nxt = cur + datetime.timedelta(days=21)
        tr = df[df["day"] < cur.isoformat()]
        te = df[(df["day"] >= cur.isoformat()) & (df["day"] < nxt.isoformat())]
        if len(tr) > 500 and len(te) > 200 and te["week"].nunique() >= 3:
            folds.append((cur, nxt, tr, te))
        cur = nxt
    print(f"  {'fold (calendar)':<28}{'n':>6}{'wks':>5}{'picked':>11}"
          f"{'real adv':>11}{'null adv':>11}  verdict")
    print("-" * 104)
    fout = []
    for a, b, tr, te in folds:
        means = [(float(tr[f"real|{c}"].mean()), c) for c in CELLS if f"real|{c}" in tr.columns]
        means.sort(reverse=True)
        pick = means[0][1]
        pr = week_boot(te, f"real|{pick}", f"real|{DEFAULT}")[0]
        pf = week_boot(te, f"flip|{pick}", f"flip|{DEFAULT}")[0]
        boundary = pick.split("|")[0] == str(max(STOPS))
        print(f"  {a.isoformat()}..{b.isoformat():<14}{len(te):>6}{te['week'].nunique():>5}"
              f"{pick:>11}{pr:>11.4f}{pf:>11.4f}"
              f"  {'argmax AT grid edge' if boundary else 'interior argmax'}")
        fout.append({"from": a.isoformat(), "to": b.isoformat(), "n": int(len(te)),
                     "weeks": int(te["week"].nunique()), "picked": pick,
                     "real_adv": round(pr, 4), "null_adv": round(pf, 4),
                     "argmax_at_grid_edge": bool(boundary)})
    out["folds"] = fout

    survives = any(v.get("geometry_survives_null") for v in out["cells"].values())
    print("\n" + "=" * 104)
    print("VERDICT")
    print("=" * 104)
    print("  geometry survives the side-flip null: " + ("YES" if survives else "NO"))
    if not survives:
        print("  => the wide-stop advantage is de-levering a losing signal stream,")
        print("     not a stop/target geometry effect. RETRACTION.md stands.")
    out["verdict"] = ("geometry survives the null" if survives
                      else "advantage is directional de-levering, not geometry")
    with io.open(os.path.join(HERE, "geometry_v2.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote geometry_v2.json")


if __name__ == "__main__":
    main()
