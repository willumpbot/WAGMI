"""Does a TRAILING exit convert this signal stream from negative to positive?

The owner's point, and he is right: ADX_GATE measured the signals at a FIXED bracket (stop, fixed
target, mark to close at 48h). That deliberately throws away the one thing a trailing stop captures
-- price running favourably and then coming back. So "the signals are negative-expectancy" is a
statement about a fixed bracket, NOT about the live bot, which has confidence floors, sizing and a
trailing exit on top.

AND THE GAP IS REAL, not hypothetical:
  exits.py:30     STOP_MULT = 8.0   "the geometry plateau; GEOMETRY.md"
  geometry_v3     x8 binds on only 14.3% of trades
  exits_v2.py     grep -c trail -> 0
So v1 tested trailing at a bracket that almost never fires, and v2 never tested trailing at all.
The trailing exit has NEVER been tested at a bracket that binds. This script fixes that.

ORDER OF WORK -- the cheap diagnostic decides whether the expensive test is worth running:

  STEP 1  FAVOURABLE EXCURSION. For each signal, how far did price go in our favour (in R) before
          the stop fired or 48h elapsed? A trailing exit can only harvest excursion that exists.
          If mean/median best-excursion is ~0, trailing cannot help and we stop here.
          Reported next to the FIXED-bracket outcome, so the gap between them is the prize.

  STEP 2  Only if step 1 shows harvestable excursion: trailing policies at brackets that BIND
          (x1 = the bot today, x2), swept over arm-at +0.25/+0.5/+1.0R and trail distance
          0.5/1.0/1.5R, against three references: fixed 1R target, mark-to-close, and stop-only.

  STEP 3  POWER, before any verdict. Lag placebo (shift each coin's signal times within that coin,
          preserving count and clustering). Report SIZE first; if size is not ~5% the comparison is
          labelled unmeasurable, per the standing rule that cost five retractions to learn.

Outcome in R, R = |entry - sl| from the bot's own signal, net 9 bps round trip, 48h horizon,
week-clustered CIs with the equal-weighted week mean beside every pooled figure.
"""
import json, io, os, gzip, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

from geometry_v2 import load_candles, first_after, FEE_BPS, HERE

HORIZON_H = 48
STOPS = (1.0, 2.0)                 # brackets that bind (geometry_v3: 86% and 79%)
ARM = (0.25, 0.5, 1.0)             # start trailing once +X R is reached
TRAIL = (0.5, 1.0, 1.5)            # trail this far below the running peak, in R
PLACEBO_SETS = 120
rng = np.random.default_rng(20261010)
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
        entry, base = c[i0][1], s["base"]
        if entry <= 0 or base <= 0:
            continue
        long_ = s["side"] == "LONG"
        end = s["t0"] + HORIZON_H * 3600
        bars = []
        k = i0 + 1
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if len(bars) < 2:
            continue
        rec = {"sym": sym, "day": s["day"], "week": s["week"],
               "conf": s.get("conf", 0.0), "agree": s.get("agree", 0.0)}
        for sm in STOPS:
            dist = sm * base
            sl = entry - dist if long_ else entry + dist
            feeR = 2 * (FEE_BPS / 1e4) * entry / dist
            # ---- step 1: favourable excursion + the fixed references, one walk ----
            peak = 0.0            # best favourable excursion in R, before the stop fires
            stop_at = None
            for j, (_, o, h, l, cl) in enumerate(bars):
                fav = ((h - entry) if long_ else (entry - l)) / dist
                adv = ((entry - l) if long_ else (h - entry)) / dist
                if adv >= 1.0:                      # the stop is 1R by construction
                    peak = max(peak, min(fav, 1e9))  # same-bar favourable still counted
                    stop_at = j
                    break
                peak = max(peak, fav)
            rec[f"exc|{sm}"] = peak
            rec[f"stopped|{sm}"] = stop_at is not None
            # fixed 1R target
            r_fix = None
            for (_, o, h, l, cl) in bars:
                hs = (l <= sl) if long_ else (h >= sl)
                tgt = entry + dist if long_ else entry - dist
                ht = (h >= tgt) if long_ else (l <= tgt)
                if hs:
                    r_fix = -1.0; break
                if ht:
                    r_fix = 1.0; break
            if r_fix is None:
                last = bars[-1][4]
                r_fix = ((last - entry) if long_ else (entry - last)) / dist
            rec[f"fix1R|{sm}"] = r_fix - feeR
            # mark to close, stop still active
            r_mtc = None
            for (_, o, h, l, cl) in bars:
                hs = (l <= sl) if long_ else (h >= sl)
                if hs:
                    r_mtc = -1.0; break
            if r_mtc is None:
                last = bars[-1][4]
                r_mtc = ((last - entry) if long_ else (entry - last)) / dist
            rec[f"mtc|{sm}"] = r_mtc - feeR
            # ---- step 2: trailing policies ----
            for a in ARM:
                for t in TRAIL:
                    armed = False
                    best = 0.0
                    r = None
                    for (_, o, h, l, cl) in bars:
                        fav = ((h - entry) if long_ else (entry - l)) / dist
                        adv = ((entry - l) if long_ else (h - entry)) / dist
                        if armed:
                            # trailing stop sits t below the running best, in R
                            trig = best - t
                            cur = ((cl - entry) if long_ else (entry - cl)) / dist
                            low = -adv
                            if low <= trig:
                                r = trig; break
                        if adv >= 1.0 and not armed:
                            r = -1.0; break
                        best = max(best, fav)
                        if not armed and best >= a:
                            armed = True
                    if r is None:
                        last = bars[-1][4]
                        r = ((last - entry) if long_ else (entry - last)) / dist
                    rec[f"tr|{sm}|{a}|{t}"] = r - feeR
        out.append(rec)
    return out


def wk(v, w):
    byw = collections.defaultdict(list)
    for a, b in zip(v, w):
        byw[b].append(a)
    mus = np.array([np.mean(x) for x in byw.values()])
    if len(mus) < 4:
        return float("nan"), float("nan"), len(mus)
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return float(mus.mean()), se, len(mus)


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
                base = abs(float(d["entry"]) - float(d["sl"]))
            except Exception:
                continue
            if base <= 0:
                continue
            day = d["ts"][:10]
            w = datetime.date.fromisoformat(day).isocalendar()
            sigs.append({"sym": d["sym"], "side": d["side"], "base": base, "t0": t0,
                         "day": day, "week": f"{w[0]}-W{w[1]:02d}",
                         "conf": float(d.get("conf") or 0),
                         "agree": float(d.get("num_agree") or 0)})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    print(f"{len(sigs)} signals, {n} workers, stops x{STOPS}, horizon {HORIZON_H}h", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for o in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(o)
    df = pd.DataFrame(recs)
    CACHE = os.path.join(HERE, "trailing_exit_panel.csv.gz")
    df.to_csv(CACHE, index=False, compression="gzip")
    print("cached panel ->", os.path.basename(CACHE))
    print(f"simulated {len(df)}  weeks {df['week'].nunique()}\n")
    out = {"n": int(len(df)), "weeks": int(df["week"].nunique()), "horizon_h": HORIZON_H}

    # ================= STEP 1 =================
    print("=" * 100)
    print("STEP 1 — IS THERE FAVOURABLE EXCURSION TO HARVEST?")
    print("  excursion = best move in our favour (in R) before the stop fired or 48h elapsed")
    print("=" * 100)
    print(f"  {'stop':>6}{'mean exc':>11}{'median':>9}{'p75':>8}{'p90':>8}"
          f"{'% reaching +0.5R':>18}{'% +1.0R':>10}{'stopped%':>10}")
    print("-" * 100)
    for sm in STOPS:
        e = df[f"exc|{sm}"].values
        print(f"  x{sm:<5}{e.mean():>11.3f}{np.median(e):>9.3f}{np.percentile(e,75):>8.3f}"
              f"{np.percentile(e,90):>8.3f}{100*(e>=0.5).mean():>17.1f}%{100*(e>=1.0).mean():>9.1f}%"
              f"{100*df[f'stopped|{sm}'].mean():>9.1f}%")
        out.setdefault("excursion", {})[f"x{sm}"] = {
            "mean": round(float(e.mean()), 4), "median": round(float(np.median(e)), 4),
            "p75": round(float(np.percentile(e, 75)), 4),
            "p90": round(float(np.percentile(e, 90)), 4),
            "pct_reach_0.5R": round(100 * float((e >= 0.5).mean()), 2),
            "pct_reach_1.0R": round(100 * float((e >= 1.0).mean()), 2),
            "stopped_pct": round(100 * float(df[f"stopped|{sm}"].mean()), 2)}

    print(f"\n  {'stop':>6}{'fixed 1R':>12}{'mark-to-close':>16}{'best possible':>16}  (week means)")
    print("-" * 100)
    for sm in STOPS:
        f1, s1, _ = wk(df[f"fix1R|{sm}"].values, df["week"].values)
        mc, s2, _ = wk(df[f"mtc|{sm}"].values, df["week"].values)
        ex, s3, _ = wk(df[f"exc|{sm}"].values, df["week"].values)
        print(f"  x{sm:<5}{f1:>+12.4f}{mc:>+16.4f}{ex:>+16.4f}")
        out.setdefault("references", {})[f"x{sm}"] = {
            "fixed_1R_week": round(f1, 4), "mark_to_close_week": round(mc, 4),
            "excursion_week": round(ex, 4)}
    hv = max(out["excursion"][f"x{sm}"]["mean"] for sm in STOPS)
    print(f"\n  HEADROOM: mean excursion {hv:.3f}R vs the fixed-bracket outcome above.")
    if hv < 0.15:
        print("  => too little excursion to harvest; a trailing exit cannot help. STOPPING.")
        out["verdict"] = "no harvestable excursion"
        with io.open(os.path.join(HERE, "trailing_exit.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        return
    print("  => there IS excursion. Proceeding to the trailing sweep.")

    # ================= STEP 3 (power before verdict) =================
    print("\n" + "=" * 100)
    print("POWER — lag placebo, before any trailing verdict")
    print("=" * 100)
    bysym = collections.defaultdict(list)
    for r in recs:
        bysym[r["sym"]].append(r)
    best_key = f"tr|2.0|0.5|1.0"
    det = collections.Counter()
    for _ in range(PLACEBO_SETS):
        a_, b_ = [], []
        for s, rows in bysym.items():
            if len(rows) < 20:
                continue
            L = int(rng.integers(5, len(rows)))
            sh = rows[L:] + rows[:L]
            half = len(rows) // 2
            a_.extend(sh[:half]); b_.extend(rows[half:])
        for delta in (0.0, 0.05, 0.10, 0.20):
            m1, s1, _ = wk([x[best_key] + delta for x in a_], [x["week"] for x in a_])
            m0, s0, _ = wk([x[f"fix1R|2.0"] for x in b_], [x["week"] for x in b_])
            if not (np.isfinite(s1) and np.isfinite(s0)):
                continue
            se = math.sqrt(s1 ** 2 + s0 ** 2)
            if (m1 - m0) - 1.96 * se > 0:
                det[delta] += 1
    print(f"  {'injected R':>12}{'detection':>12}")
    for delta in (0.0, 0.05, 0.10, 0.20):
        rate = det[delta] / PLACEBO_SETS
        print(f"  {delta:>12.2f}{rate:>12.3f}{'   <- SIZE (want ~0.05)' if delta == 0 else ''}")
        out.setdefault("power", {})[str(delta)] = round(rate, 3)
    size = det[0.0] / PLACEBO_SETS
    mde = next((d for d in (0.05, 0.10, 0.20) if det[d] / PLACEBO_SETS >= 0.8), None)
    valid = 0.01 <= size <= 0.12
    print(f"\n  size {size:.3f} -> {'calibrated' if valid else 'MISCALIBRATED (label results unmeasurable)'}")
    print(f"  80%-power MDE: {str(mde)+'R' if mde else 'not reached within 0.20R'}")
    out["size"] = size
    out["mde80_R"] = mde
    out["design_valid"] = bool(valid)

    # ================= STEP 2 =================
    print("\n" + "=" * 100)
    print("STEP 2 — TRAILING POLICIES at brackets that BIND (week means, net 9bps)")
    print("=" * 100)
    for sm in STOPS:
        f1, sf, _ = wk(df[f"fix1R|{sm}"].values, df["week"].values)
        print(f"\n  stop x{sm}   reference: fixed 1R target = {f1:+.4f}R  (week mean)")
        print(f"    {'arm at':>8}{'trail':>8}{'mean R':>10}{'week mean':>12}{'week se':>10}"
              f"{'vs fixed':>11}{'week t':>9}  verdict")
        print("    " + "-" * 82)
        for a in ARM:
            for t in TRAIL:
                k = f"tr|{sm}|{a}|{t}"
                m, se, nw = wk(df[k].values, df["week"].values)
                d = m - f1
                sed = math.sqrt(se ** 2 + sf ** 2)
                sig = (d - 1.96 * sed) > 0
                v = ("BEATS fixed" if sig else
                     ("unmeasurable" if (mde is None or abs(d) < mde) else "no better"))
                print(f"    {a:>8.2f}{t:>8.1f}{df[k].mean():>+10.4f}{m:>+12.4f}{se:>10.4f}"
                      f"{d:>+11.4f}{(d/sed if sed else float('nan')):>9.2f}  {v}")
                out.setdefault("trailing", {})[k] = {
                    "mean_r": round(float(df[k].mean()), 4), "week_mean": round(m, 4),
                    "week_se": round(se, 4), "vs_fixed_1R": round(d, 4),
                    "week_t": round(d / sed, 2) if sed else None, "beats_fixed": bool(sig)}

    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    wins = [k for k, v in out.get("trailing", {}).items() if v["beats_fixed"]]
    best = max(out.get("trailing", {}).items(), key=lambda kv: kv[1]["week_mean"], default=(None, None))
    if not valid:
        out["verdict"] = "design void (placebo size miscalibrated)"
    elif wins:
        out["verdict"] = f"trailing beats a fixed target in {len(wins)} cells: {wins[:4]}"
    else:
        out["verdict"] = ("no trailing policy beats a fixed 1R target by more than this sample "
                          f"can detect ({mde}R)")
    print(f"  {out['verdict']}")
    if best[0]:
        print(f"  best cell by week mean: {best[0]} = {best[1]['week_mean']:+.4f}R "
              f"(vs fixed {out['references']['x2.0']['fixed_1R_week']:+.4f}R)")
    print(f"\n  POSITIVE IN ABSOLUTE TERMS? ", end="")
    pos = [k for k, v in out.get("trailing", {}).items() if v["week_mean"] > 0]
    print(f"{len(pos)} of {len(out.get('trailing', {}))} trailing cells have a POSITIVE week mean"
          f"{': ' + str(pos[:4]) if pos else ''}")
    out["positive_cells"] = pos
    with io.open(os.path.join(HERE, "trailing_exit.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote trailing_exit.json")


if __name__ == "__main__":
    main()
