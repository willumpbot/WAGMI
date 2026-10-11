"""Mission E: does a confidence floor improve the real ledger? Era-aware.

THE TRAP THIS SCRIPT EXISTS TO AVOID: sweeping a threshold and reporting the best
one is guaranteed to show an improvement, because the best cut of any noisy series
looks good in-sample. That is the "test that cannot fail" pattern that has refuted
most of this project's findings.

So the headline statistic is NOT "the best floor". It is:

    how does the best in-sample improvement compare to the best in-sample
    improvement obtained after SHUFFLING confidence within the same era?

If a floor on shuffled confidence buys you just as much, the floor is worthless and
the apparent gain is threshold mining. Shuffling within era preserves the era
composition, so the placebo cannot win just by reweighting June against July.
"""
import csv, io, datetime, sys
import numpy as np

rng = np.random.default_rng(20261011)
CONF_FIELD = "confidence_score"


def load():
    r = list(csv.DictReader(io.open("server_exports/trade_ledger.csv",
                                    encoding="utf-8", errors="replace")))
    out = []
    for x in r:
        try:
            pnl = float(x["net_pnl"]); conf = float(x[CONF_FIELD])
        except (KeyError, TypeError, ValueError):
            continue
        d = datetime.datetime.fromtimestamp(float(x["timestamp"]), datetime.UTC)
        out.append({"pnl": pnl, "conf": conf, "mo": d.strftime("%Y-%m"),
                    "wk": d.isocalendar()[:2],
                    "era": ("1 pre-Jul15"
                            if d < datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
                            else "2 Jul15-Sep"
                            if d < datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
                            else "3 Oct")})
    return out


def curve(rows, floors):
    """mean P&L per trade kept, and count kept, at each floor"""
    out = []
    for f in floors:
        keep = [x["pnl"] for x in rows if x["conf"] >= f]
        out.append((f, len(keep), np.mean(keep) if keep else np.nan,
                    np.sum(keep) if keep else 0.0))
    return out


def best_gain(rows, floors, min_keep):
    """best in-sample improvement in MEAN P&L over taking everything.
    min_keep guards against a floor that keeps 3 lucky trades."""
    base = np.mean([x["pnl"] for x in rows])
    best = 0.0
    for f in floors:
        keep = [x["pnl"] for x in rows if x["conf"] >= f]
        if len(keep) >= min_keep:
            best = max(best, np.mean(keep) - base)
    return best


def main():
    rows = load()
    confs = np.array([x["conf"] for x in rows])
    print("Mission E -- confidence floor on the real ledger")
    print("  %d closes carry both %s and net_pnl" % (len(rows), CONF_FIELD))
    print("  confidence: min %.1f  p25 %.1f  median %.1f  p75 %.1f  max %.1f"
          % (confs.min(), np.percentile(confs, 25), np.median(confs),
             np.percentile(confs, 75), confs.max()))
    base = np.mean([x["pnl"] for x in rows])
    print("  baseline: take everything -> mean $%+.2f/trade, total $%+.2f"
          % (base, sum(x["pnl"] for x in rows)))
    print()

    floors = np.percentile(confs, np.arange(0, 95, 5))
    MIN_KEEP = max(30, len(rows) // 6)

    print("THE FLOOR CURVE (reported whole, because the best point is not evidence)")
    print("  %8s %6s %10s %11s" % ("floor", "kept", "mean $", "total $"))
    for f, n, m, t in curve(rows, floors):
        flag = "" if n >= MIN_KEEP else "  (below min-keep)"
        print("  %8.1f %6d %+10.2f %+11.2f%s" % (f, n, m, t, flag))
    print()

    obs = best_gain(rows, floors, MIN_KEEP)
    print("BEST in-sample gain over baseline (min %d kept): $%+.2f/trade" % (MIN_KEEP, obs))
    print()

    print("PLACEBO -- the same search on SHUFFLED confidence, within era")
    print("  (if this matches the observed gain, the floor is threshold mining)")
    null = []
    byera = {}
    for x in rows:
        byera.setdefault(x["era"], []).append(x)
    for _ in range(2000):
        sh = []
        for e, g in byera.items():
            cs = rng.permutation([y["conf"] for y in g])
            for y, c in zip(g, cs):
                sh.append({"pnl": y["pnl"], "conf": c, "era": e})
        null.append(best_gain(sh, floors, MIN_KEEP))
    null = np.array(null)
    p = float(np.mean(null >= obs))
    print("  shuffled best gain: mean $%+.2f, median $%+.2f, 95th pct $%+.2f, max $%+.2f"
          % (null.mean(), np.median(null), np.percentile(null, 95), null.max()))
    print("  observed $%+.2f  ->  p = %.3f  (%s)"
          % (obs, p, "BEATS the placebo" if p < 0.05 else "INDISTINGUISHABLE from threshold mining"))
    print()

    print("ERA-AWARE: the same question inside each era")
    print("  %-13s %5s %10s %10s %10s" % ("era", "n", "base $", "best gain", "placebo p"))
    for e in sorted(byera):
        g = byera[e]
        if len(g) < 40:
            print("  %-13s %5d   -- too few --" % (e, len(g)))
            continue
        gc = np.array([y["conf"] for y in g])
        fl = np.percentile(gc, np.arange(0, 95, 5))
        mk = max(20, len(g) // 6)
        o = best_gain(g, fl, mk)
        nl = []
        for _ in range(800):
            cs = rng.permutation(gc)
            sh = [{"pnl": y["pnl"], "conf": c} for y, c in zip(g, cs)]
            nl.append(best_gain(sh, fl, mk))
        pp = float(np.mean(np.array(nl) >= o))
        print("  %-13s %5d %+10.2f %+10.2f %10.3f" % (e, len(g),
              np.mean([y["pnl"] for y in g]), o, pp))
    print()

    print("DIRECTION CHECK -- does confidence correlate with outcome at all?")
    pn = np.array([x["pnl"] for x in rows])
    cf = np.array([x["conf"] for x in rows])
    rho = np.corrcoef(cf, pn)[0, 1]
    wks = sorted({x["wk"] for x in rows})
    per = []
    for w in wks:
        g = [x for x in rows if x["wk"] == w]
        if len(g) > 5:
            a = np.array([y["conf"] for y in g]); b = np.array([y["pnl"] for y in g])
            if a.std() > 0 and b.std() > 0:
                per.append(np.corrcoef(a, b)[0, 1])
    print("  pooled correlation(confidence, net P&L) = %+.3f" % rho)
    print("  equal-weighted by week                  = %+.3f  (%d weeks)"
          % (np.mean(per), len(per)))
    print("  weeks positive: %d of %d" % (sum(v > 0 for v in per), len(per)))
    mde = 2.8 / np.sqrt(len(rows) - 3)
    print("  80%%-power MDE on a correlation at n=%d is about %.3f -> %s"
          % (len(rows), mde, "detectable" if abs(rho) > mde else "BELOW the floor"))


if __name__ == "__main__":
    main()
