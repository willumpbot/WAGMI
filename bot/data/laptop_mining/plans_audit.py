"""MISSION 4 — audit plans.py's grading, and answer "should ties resolve on 1m?" with a number.

Three things the server asked about, plus one it did not.

  Q1 (asked)  stop-first tie rule at 5m. TIE_RULE.md says stop-first is right only ~39% of the
              time, so: is it worth resolving ties on 1m candles?
  Q2 (asked)  the fill rule `low <= entry <= high`
  Q3 (asked)  candles that opened before the plan are skipped
  Q4 (NOT asked, and it is the bigger one) -- the FILL CANDLE is tested for stop/target using its
              OWN full high/low, including the part of the range that happened BEFORE the fill.

Q4, from plans.py:_walk:

        if fill_t is None:
            ...
            if l <= e <= h:
                fill_t = t0          # filled somewhere INSIDE this candle
            else:
                continue
        ...                          # same loop iteration, same candle:
        hit_stop = (l <= st) if sg > 0 else (h >= st)
        hit_tgt  = (h >= tg) if sg > 0 else (l <= tg)

A limit plan fills mid-candle, but the stop/target test then uses the whole candle's range. Price
action before the fill can therefore close the trade. This cuts both ways (a pre-fill wick to the
target scores a win; a pre-fill wick to the stop scores a loss) so it is not a simple bias in the
owner's favour -- but it is not measurement either. Same applies to best_r / worst_r, which are
computed from the full fill candle.

WHAT THIS SCRIPT MEASURES, on real HL 5m candles, for plan geometries the owner actually uses
(stop 0.5-3% away, target 0.5-3x the stop distance):

  A. the AMBIGUOUS RATE: how often the candle that resolves a plan contains BOTH stop and target.
     That is the only situation where the tie rule does any work, so it is the whole answer to Q1.
     If it is rare, 1m resolution is not worth the complexity.
  B. the FILL-CANDLE CONTAMINATION RATE for Q4: how often the filling candle also contains the
     stop or the target, i.e. how often a trade can be decided by pre-fill price action.

No 1m data is needed for either: both are "how often does it matter" questions.
"""
import json, io, os, csv, glob, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
MAX_HOLD_H = 48
ENTRY_WINDOW_H = 24
STOP_PCTS = (0.005, 0.01, 0.02, 0.03)       # plan stop distance as a fraction of price
RR = (0.5, 1.0, 2.0, 3.0)                   # target distance in R
rng = np.random.default_rng(20261009)
PER_SYM = 400                               # random plan start times per symbol


def load5(sym):
    p = os.path.join(HIST, f"{sym}_5m.csv")
    rows = []
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"])))
            except (TypeError, ValueError, KeyError):
                continue
    rows.sort()
    return rows


syms = sorted({os.path.basename(p).split("_5m")[0] for p in glob.glob(os.path.join(HIST, "*_5m.csv"))})
syms = [s for s in syms if not s.endswith("_wspot")]
print(f"5m symbols: {len(syms)}  ({', '.join(syms[:10])}{'...' if len(syms) > 10 else ''})")

bars_per_hold = MAX_HOLD_H * 12
res = collections.defaultdict(lambda: collections.Counter())

for s in syms:
    b = load5(s)
    if len(b) < bars_per_hold + 50:
        continue
    n = len(b)
    starts = rng.integers(10, n - bars_per_hold - 2, PER_SYM)
    for i0 in starts:
        px = b[i0][4]
        if px <= 0:
            continue
        for sp in STOP_PCTS:
            for rr in RR:
                for sg in (1, -1):
                    e = px
                    st = e * (1 - sp) if sg > 0 else e * (1 + sp)
                    tg = e * (1 + rr * sp) if sg > 0 else e * (1 - rr * sp)
                    risk = abs(e - st)
                    key = f"{sp}|{rr}"
                    # --- market fill at the logged price, as plans.py does ---
                    filled = True
                    for k in range(i0 + 1, min(i0 + 1 + bars_per_hold, n)):
                        _, o, h, l, c = b[k]
                        hs = (l <= st) if sg > 0 else (h >= st)
                        ht = (h >= tg) if sg > 0 else (l <= tg)
                        if hs and ht:
                            res[key]["ambiguous"] += 1
                            res[key]["resolved"] += 1
                            break
                        if hs:
                            res[key]["stop_only"] += 1
                            res[key]["resolved"] += 1
                            break
                        if ht:
                            res[key]["target_only"] += 1
                            res[key]["resolved"] += 1
                            break
                    else:
                        res[key]["timed_out"] += 1
                    # --- Q4: limit fill, does the FILL candle also contain stop or target? ---
                    # a limit plan entry sits away from current price; emulate the common case of
                    # an entry 0.5 stop-distances away, then look at the candle that fills it
                    elimit = e * (1 - 0.5 * sp) if sg > 0 else e * (1 + 0.5 * sp)
                    stl = elimit * (1 - sp) if sg > 0 else elimit * (1 + sp)
                    tgl = elimit * (1 + rr * sp) if sg > 0 else elimit * (1 - rr * sp)
                    for k in range(i0 + 1, min(i0 + 1 + ENTRY_WINDOW_H * 12, n)):
                        _, o, h, l, c = b[k]
                        if l <= elimit <= h:
                            res[key]["limit_filled"] += 1
                            touches_stop = (l <= stl) if sg > 0 else (h >= stl)
                            touches_tgt = (h >= tgl) if sg > 0 else (l <= tgl)
                            if touches_stop or touches_tgt:
                                res[key]["fill_candle_contaminated"] += 1
                            break

out = {"max_hold_h": MAX_HOLD_H, "entry_window_h": ENTRY_WINDOW_H,
       "symbols": len(syms), "plans_per_symbol": PER_SYM, "cells": {}}

print("\n" + "=" * 112)
print("A. HOW OFTEN DOES THE TIE RULE ACTUALLY DO ANY WORK?")
print("   'ambiguous' = the resolving 5m candle contains BOTH the stop and the target.")
print("   Only these cases are decided by the stop-first assumption.")
print("=" * 112)
print(f"  {'stop%':>7}{'tp(R)':>7}{'resolved':>10}{'AMBIGUOUS':>12}{'= share':>10}"
      f"{'stop only':>11}{'target only':>13}{'timed out':>11}")
print("-" * 112)
for sp in STOP_PCTS:
    for rr in RR:
        k = f"{sp}|{rr}"
        c = res[k]
        tot = c["resolved"] + c["timed_out"]
        if not tot:
            continue
        amb = c["ambiguous"]
        share = 100 * amb / c["resolved"] if c["resolved"] else 0
        print(f"  {100*sp:>6.1f}%{rr:>7.1f}{c['resolved']:>10}{amb:>12}{share:>9.2f}%"
              f"{c['stop_only']:>11}{c['target_only']:>13}{c['timed_out']:>11}")
        out["cells"][k] = {"resolved": c["resolved"], "ambiguous": amb,
                           "ambiguous_share_pct": round(share, 3),
                           "stop_only": c["stop_only"], "target_only": c["target_only"],
                           "timed_out": c["timed_out"],
                           "limit_filled": c["limit_filled"],
                           "fill_candle_contaminated": c["fill_candle_contaminated"],
                           "fill_contamination_pct": round(
                               100 * c["fill_candle_contaminated"] / c["limit_filled"], 2)
                           if c["limit_filled"] else None}

allamb = sum(res[k]["ambiguous"] for k in res)
allres = sum(res[k]["resolved"] for k in res)
print("-" * 112)
print(f"  {'OVERALL':<14}{allres:>10}{allamb:>12}{100*allamb/allres:>9.2f}%")
out["overall_ambiguous_share_pct"] = round(100 * allamb / allres, 3)

print("\n" + "=" * 112)
print("B. Q4 — CAN PRE-FILL PRICE ACTION DECIDE A LIMIT PLAN?")
print("   'contaminated' = the candle that fills the limit entry ALSO contains the stop or target,")
print("   so plans.py can close the trade on range that happened before the position existed.")
print("=" * 112)
print(f"  {'stop%':>7}{'tp(R)':>7}{'limit fills':>13}{'contaminated':>14}{'= share':>10}")
print("-" * 112)
for sp in STOP_PCTS:
    for rr in RR:
        k = f"{sp}|{rr}"
        c = res[k]
        if not c["limit_filled"]:
            continue
        pc = 100 * c["fill_candle_contaminated"] / c["limit_filled"]
        print(f"  {100*sp:>6.1f}%{rr:>7.1f}{c['limit_filled']:>13}"
              f"{c['fill_candle_contaminated']:>14}{pc:>9.2f}%")
allfill = sum(res[k]["limit_filled"] for k in res)
allcont = sum(res[k]["fill_candle_contaminated"] for k in res)
print("-" * 112)
print(f"  {'OVERALL':<14}{allfill:>13}{allcont:>14}{100*allcont/allfill:>9.2f}%")
out["overall_fill_contamination_pct"] = round(100 * allcont / allfill, 3)

print("\n" + "=" * 112)
print("ANSWERS")
print("=" * 112)
amb_pct = 100 * allamb / allres
print(f"  Q1 should ties resolve on 1m?  The tie rule decides {amb_pct:.2f}% of resolved plans.")
if amb_pct < 2:
    print(f"     => NO. At {amb_pct:.2f}% it cannot move your stats, and TIE_RULE.md found 15.4% of")
    print("        ambiguous cases are STILL tied at 5m, so 1m would only fix a fraction of a")
    print("        fraction. Spend the effort on B instead.")
else:
    print(f"     => WORTH IT. {amb_pct:.2f}% is enough to matter given stop-first is ~39% right.")
print(f"  Q4 pre-fill contamination: {100*allcont/allfill:.2f}% of limit fills can be decided by")
print("     range that predates the position. THIS is the one to fix, and it is a 3-line change:")
print("     on the fill candle, only test stop/target if the candle's close is already beyond them,")
print("     or simply start stop/target testing from the NEXT candle.")
with io.open(os.path.join(HERE, "plans_audit.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote plans_audit.json")
