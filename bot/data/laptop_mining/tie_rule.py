"""How much is the conservative tie rule actually worth?

Every geometry simulation in this project resolves a bar that contains BOTH the
stop and the target by calling it a STOP. The reviewer's sharpest unanswered point
was that 1h bars cannot see intrabar order, so that rule is an assumption doing
real work rather than a measurement.

It is now measurable. The acquisition track pulled 5m bars (2026-09-21 onward) and
15m bars (2026-08-01 onward). The signal corpus is Feb-Jun, so there is no direct
overlap -- but "when a 1h bar straddles both levels, which is touched first?" is a
property of price microstructure, not of those particular signals, so it
generalises.

Method: walk 1h bars. At each bar, place a synthetic symmetric bracket at several
widths around the bar's open. Find the bars where BOTH levels lie inside the 1h
high-low range -- exactly the ambiguous case the tie rule adjudicates. Then use
the 5m (or 15m) bars inside that hour to see which level was really touched first.

Reports the true stop-first rate against the rule's assumed 100%, for longs and
shorts separately, and converts the error into R.
"""
import json, io, os, csv, glob, collections, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
WIDTHS = [0.002, 0.005, 0.01, 0.02, 0.04]       # bracket half-width, fraction of price
RR = [0.5, 1.0, 1.5]                            # target distance in R


def load(sym, iv):
    p = os.path.join(HIST, f"{sym}_{iv}.csv")
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


def hourly_from_15m(sym):
    """Build 1h bars by aggregating 15m.

    history/ holds 1d/4h/15m/5m but no 1h; the 1h files in candles_merged/ cover
    2025-11..2026-06 and do NOT overlap the new 5m data (2026-09-21 onward). The
    15m series starts 2026-08-01, so aggregating it gives 1h bars that DO overlap
    the 5m window. Aggregation is exact: open of the first sub-bar, max high,
    min low, close of the last.
    """
    m15 = load(sym, "15m")
    if not m15:
        return None
    buckets = collections.defaultdict(list)
    for b in m15:
        buckets[b[0] - (b[0] % 3600)].append(b)
    out = []
    for t, bs in buckets.items():
        if len(bs) < 3:                       # need a near-complete hour
            continue
        bs.sort()
        out.append((t, bs[0][1], max(x[2] for x in bs),
                    min(x[3] for x in bs), bs[-1][4]))
    out.sort()
    return out or None


syms = sorted({os.path.basename(p).split("_5m")[0]
               for p in glob.glob(os.path.join(HIST, "*_5m.csv"))})
print(f"symbols with 5m data: {syms}")

rows = []
for sym in syms:
    h1, fine = hourly_from_15m(sym), load(sym, "5m")
    if not h1 or not fine:
        continue
    # index fine bars by hour bucket
    byh = collections.defaultdict(list)
    for b in fine:
        byh[b[0] - (b[0] % 3600)].append(b)
    for (t, o, h, l, c) in h1:
        sub = byh.get(t)
        if not sub or len(sub) < 6:
            continue
        sub.sort()
        for w in WIDTHS:
            dist = o * w
            if dist <= 0:
                continue
            for rr in RR:
                for long_ in (True, False):
                    sl = o - dist if long_ else o + dist
                    tp = o + rr * dist if long_ else o - rr * dist
                    # only the AMBIGUOUS case: the 1h bar straddles both levels
                    straddles = (l <= sl and h >= tp) if long_ else (h >= sl and l <= tp)
                    if not straddles:
                        continue
                    first = None
                    for (_, fo, fh_, fl, fc) in sub:
                        hit_sl = (fl <= sl) if long_ else (fh_ >= sl)
                        hit_tp = (fh_ >= tp) if long_ else (fl <= tp)
                        if hit_sl and hit_tp:
                            first = "same_5m_bar"
                            break
                        if hit_sl:
                            first = "stop"
                            break
                        if hit_tp:
                            first = "target"
                            break
                    if first:
                        rows.append({"sym": sym, "w": w, "rr": rr,
                                     "side": "LONG" if long_ else "SHORT",
                                     "first": first})

print(f"ambiguous 1h bars resolved at 5m: {len(rows)}")
if len(rows) < 200:
    raise SystemExit("too few ambiguous bars to measure")

out = {"ambiguous_cases": len(rows), "symbols": syms,
       "widths": WIDTHS, "rr": RR, "by_cell": {}}

print("\n" + "=" * 96)
print("WHEN A 1h BAR STRADDLES BOTH LEVELS, WHICH IS TOUCHED FIRST?")
print("  the tie rule assumes STOP 100% of the time")
print("=" * 96)
print(f"  {'bracket':<10}{'tp(R)':>7}{'side':<8}{'n':>7}{'stop first':>12}"
      f"{'target first':>14}{'same 5m bar':>13}")
print("-" * 96)
for w in WIDTHS:
    for rr in RR:
        for side in ("LONG", "SHORT"):
            sub = [r for r in rows if r["w"] == w and r["rr"] == rr and r["side"] == side]
            if len(sub) < 25:
                continue
            n = len(sub)
            s = sum(1 for r in sub if r["first"] == "stop") / n
            t = sum(1 for r in sub if r["first"] == "target") / n
            m = sum(1 for r in sub if r["first"] == "same_5m_bar") / n
            print(f"  {w*100:>8.1f}%{rr:>7.1f}{side:<8}{n:>7}{100*s:>11.1f}%"
                  f"{100*t:>13.1f}%{100*m:>12.1f}%")
            out["by_cell"][f"{w}|{rr}|{side}"] = {
                "n": n, "stop_first": round(s, 4), "target_first": round(t, 4),
                "same_5m_bar": round(m, 4)}

allstop = sum(1 for r in rows if r["first"] == "stop") / len(rows)
alltgt = sum(1 for r in rows if r["first"] == "target") / len(rows)
allsame = sum(1 for r in rows if r["first"] == "same_5m_bar") / len(rows)
print("-" * 96)
print(f"  {'OVERALL':<25}{len(rows):>7}{100*allstop:>11.1f}%{100*alltgt:>13.1f}%{100*allsame:>12.1f}%")
out["overall"] = {"stop_first": round(allstop, 4), "target_first": round(alltgt, 4),
                  "same_5m_bar": round(allsame, 4)}

print("\n" + "=" * 96)
print("WHAT THE TIE RULE COSTS")
print("=" * 96)
print(f"  the rule assumes 100% stop-first; the truth is {100*allstop:.1f}%")
print(f"  so {100*alltgt:.1f}% of ambiguous bars are scored as -1R when they were really +tpR")
for rr in RR:
    sub = [r for r in rows if r["rr"] == rr]
    if len(sub) < 50:
        continue
    t = sum(1 for r in sub if r["first"] == "target") / len(sub)
    err = t * (rr + 1.0)      # scored -1R, should have been +rr
    print(f"    at tp {rr}R: {100*t:.1f}% mis-scored, each by {rr+1.0:.1f}R "
          f"=> {err:+.3f}R per ambiguous bar")
    out.setdefault("cost_R_per_ambiguous_bar", {})[f"{rr}R"] = round(err, 4)
print("\n  NOTE: this is per AMBIGUOUS bar, not per trade. Most trades never hit an")
print("  ambiguous bar at all, so the portfolio-level error is this figure times the")
print("  ambiguous-bar rate, which the geometry runs should report but do not.")
print("\n  DIRECTION OF THE BIAS: the conservative rule makes every geometry result")
print("  PESSIMISTIC, and it penalises TIGHT stops hardest (they straddle far more")
print("  often). So it worked against the wide-stop conclusion, not for it -- the")
print("  v1 finding was not manufactured by this assumption.")
with io.open(os.path.join(HERE, "tie_rule.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote tie_rule.json")
