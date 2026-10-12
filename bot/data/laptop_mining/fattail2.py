"""Fat-tail, done right: 24h / 7d / 14d on the SAME calls, horizon stated in every header.

WHY A SECOND SCRIPT. The first pass computed one horizon and I labelled it wrong: `peak_m` is a
1,441-point MINUTE grid (24 hours) and I read `len/24 = 60` as sixty DAYS. The arithmetic was fine;
the unit was not. So "holding loses 42%" was a one-day claim wearing a two-month label, and the
owner's actual question -- about coins that run for weeks -- was never tested. The call that exposed
the token-side bug settles the point: 1.30x in its first 24 hours, 58.69x by day 14.

The server's instruction after that correction: report 7d AND 14d, same corrected calls, horizon in
every table header.

SAME-CALL-SET CONSTRUCTION, which is the whole reason this is careful:

    analysis set = calls with BOTH grids  +  calls that are dead
    EXCLUDED     = calls with a minute grid but no hourly grid yet

That last line matters. 320 rows currently have 24h data and no 14d data purely because the upgrade
pass has not reached them. They are not a property of the data, they are a property of the clock, and
counting them would make the 24h column a different (larger) sample than the 14d column -- which is
exactly the cross-sample contamination the server warned about when the dead-pool rate rises with
horizon.

DEAD IS -100%, NOT DROPPED. A call whose pool never existed or never priced is a total loss, and
dropping it is the survivorship error this project has now found in four separate forms. Dead is
horizon-independent here: the hourly request covers all 14 days in one call, so a dead row is dead
at every horizon equally.

BUT THE DEAD COUNT MUST BE A RATE, NOT A TALLY -- caught by this script's own self-check.

Taking the raw dead rows alongside the complete rows gave 72 dead against 73 complete: a 50% death
rate, against the ~16-20% measured on a full cohort. The two groups are not the same population.
The complete rows come from the UPGRADE cohort, every member of which was already successfully
priced, so it contains no dead calls by construction; the dead rows accumulate from the NEW batch
being fetched alongside it. Pooling them imports the new batch's failures onto the upgrade cohort's
successes and pushes every mean down by tens of points.

So the death rate is measured across everything fetched -- dead / (dead + priced-at-all) -- and
applied as a WEIGHT:

    mean = (1 - d) * mean(priced) + d * (-1.0)

which is what the raw count would have given if the two groups were one population. The rate and its
denominator are printed, because a weight taken on trust is how the first pool rule hid a 30% death
rate behind a 12% one.
"""
import collections
import io
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
PATHS = os.path.join(HERE, "megacalls_paths.jsonl")
MIN_COMPLETE = 200          # the n I committed to before reporting any horizon comparison

HORIZONS = [("24h", "m", 1440), ("7d", "h", 168), ("14d", "h", 336)]
TARGETS = [1.5, 2.0, 3.0, 5.0, None]


def load():
    """DEDUPE BY CA, LAST WINS -- the file legitimately holds more than one row per call.

    The horizon upgrade appends a NEW complete row (24h grid carried forward + the new 14d grid)
    and leaves the original minute-only row in place, because the fetch only ever appends. So an
    upgraded call appears TWICE. Counting rows instead of calls put the same call in both the
    "complete" and the "pending" bucket, which inflated the death-rate denominator and therefore
    UNDERSTATED the death rate applied to every mean.

    Last-wins is correct here and not arbitrary: the upgrade row is written later and is a strict
    superset of the row it supersedes. That is exactly why the upgrade was built to carry the
    minute grid forward -- see the note in megacalls_fetch.load_calls.
    """
    by_ca = {}
    for line in io.open(PATHS, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("ca"):
            by_ca[d["ca"]] = d
    both, dead, pending = [], 0, 0
    for d in by_ca.values():
        m = d.get("peak_m") if isinstance(d.get("peak_m"), list) else None
        h = d.get("peak_h") if isinstance(d.get("peak_h"), list) else None
        if m and h:
            both.append(d)
        elif d.get("dead"):
            dead += 1
        else:
            pending += 1          # minute-only: awaiting the hourly upgrade, NOT dead
    return both, dead, pending


def outcome(rec, grid, idx, target):
    """Return the fraction return of one call under one target at one horizon."""
    peak = rec["peak_m"] if grid == "m" else rec["peak_h"]
    close = rec["close_m"] if grid == "m" else rec["close_h"]
    n = min(idx, len(peak) - 1)
    if n < 1:
        return None
    if target is None:
        return close[n] - 1.0
    return (target - 1.0) if peak[n] >= target else close[n] - 1.0


def day_block_ci(by_day, dead_rate, nrep=4000, seed=20261012):
    """CI on the EQUAL-WEIGHTED call-day mean, resampling whole DAYS with replacement.

    Days are the clustering unit because these calls arrive in bursts -- 183 calls sat on 44
    call-days at the time this was written -- so resampling calls would treat a single busy day as
    many independent observations and shrink the interval to a fiction.

    The dead-rate weight is applied INSIDE each bootstrap draw rather than to the final point, so
    the interval reflects the same quantity the point estimate reports.
    """
    import random
    days = sorted(by_day)
    if len(days) < 3:
        return None, None, None
    rng = random.Random(seed)
    def eq(ds):
        return (1.0 - dead_rate) * statistics.fmean(
            [statistics.fmean(by_day[d]) for d in ds]) + dead_rate * (-1.0)
    point = eq(days)
    boot = sorted(eq([days[rng.randrange(len(days))] for _ in days]) for _ in range(nrep))
    return point, boot[int(.025 * nrep)], boot[int(.975 * nrep)]


def main():
    global DEAD_RATE, DEAD_DENOM
    both, dead, pending = load()
    DEAD_DENOM = len(both) + pending + dead
    DEAD_RATE = dead / DEAD_DENOM if DEAD_DENOM else 0.0
    print("complete rows (both grids): %d | dead: %d | minute-only, awaiting upgrade: %d"
          % (len(both), dead, pending))
    print("death rate = %d / %d = %.1f%% (applied as a weight, not a tally)"
          % (dead, DEAD_DENOM, 100 * DEAD_RATE))
    print("analysis set = complete + dead = %d; the %d pending are EXCLUDED because they are a "
          "property of\n  the upgrade clock, not of the data -- including them would make the 24h "
          "column a bigger sample\n  than the 14d column." % (len(both) + dead, pending))

    if len(both) < MIN_COMPLETE:
        print("\nn=%d complete, below the %d I committed to before reporting a horizon comparison."
              % (len(both), MIN_COMPLETE))
        print("Running the instrument anyway as a SELF-CHECK only -- no conclusions below.\n")
        report(both, dead, check_only=True)
        return
    report(both, dead, check_only=False)


DEAD_RATE = 0.0
DEAD_DENOM = 0


def report(both, dead, check_only):
    tag = "  [SELF-CHECK, n too small for a conclusion]" if check_only else ""
    print("=" * 78)
    print("IF YOU BOUGHT EVERY CALL EQUALLY -- mean return by exit rule and HORIZON%s" % tag)
    print("death rate %.1f%% applied as a WEIGHT (%d dead of %d priced-at-all, measured across "
          "the whole fetch, not the raw dead/complete ratio -- see the module docstring)"
          % (100 * DEAD_RATE, dead, DEAD_DENOM))
    print("=" * 78)
    hdr = "%-20s" % "exit rule"
    for name, _g, _i in HORIZONS:
        hdr += "%14s" % ("within %s" % name)
    print(hdr)
    rows = {}
    for target in TARGETS:
        lbl = "hold to the end" if target is None else "sell all at %.1fx" % target
        line = "%-20s" % lbl
        for name, grid, idx in HORIZONS:
            vals = [outcome(r, grid, idx, target) for r in both]
            vals = [v for v in vals if v is not None]
            if not vals:
                rows[(lbl, name)] = float("nan")
                line += "%13s" % "-"
                continue
            m = (1.0 - DEAD_RATE) * statistics.fmean(vals) + DEAD_RATE * (-1.0)
            rows[(lbl, name)] = m
            line += "%13.1f%%" % (100 * m)
        print(line)

    print("\n%-20s" % "best rule, per horizon", end="")
    for name, _g, _i in HORIZONS:
        best = max(((v, k[0]) for k, v in rows.items() if k[1] == name))
        print("%14s" % best[1].replace("sell all at ", "").replace("hold to the end", "hold"),
              end="")
    print()

    print("\nPEAK MULTIPLE REACHED, by horizon (priced calls only, n=%d)" % len(both))
    print("%-14s" % "", end="")
    for name, _g, _i in HORIZONS:
        print("%12s" % name, end="")
    print()
    for lbl, p in (("median", .5), ("p90", .9), ("p99", .99)):
        print("%-14s" % lbl, end="")
        for name, grid, idx in HORIZONS:
            v = sorted(max(r["peak_m" if grid == "m" else "peak_h"][:idx + 1]) for r in both)
            print("%11.2fx" % v[min(int(p * len(v)), len(v) - 1)], end="")
        print()
    for thr in (2, 5, 10):
        print("%-14s" % (">=%dx" % thr), end="")
        for name, grid, idx in HORIZONS:
            v = [max(r["peak_m" if grid == "m" else "peak_h"][:idx + 1]) for r in both]
            k = sum(1 for x in v if x >= thr)
            print("%10.1f%%" % (100.0 * k / len(v)), end="")
        print()
    print("%-14s" % "max", end="")
    for name, grid, idx in HORIZONS:
        v = [max(r["peak_m" if grid == "m" else "peak_h"][:idx + 1]) for r in both]
        print("%11.2fx" % max(v), end="")
    print()

    # ---------------------------------------------------------------- robustness
    # Written BEFORE the result it judges was visible (n=114 of the 200 committed), deliberately:
    # a near-breakeven mean carried by one 35x call is an outlier, not a strategy, and the moment to
    # fix how that gets tested is before there is a number worth protecting.
    print("")
    print("ROBUSTNESS of the best rule at each horizon")
    print("%-24s %10s %10s %10s %10s" % ("", "pooled", "drop best", "eq-weight", "top-1 share"))
    for name, grid, idx_h in HORIZONS:
        best_lbl, best_t = None, None
        for target in TARGETS:
            lbl = "hold to the end" if target is None else "sell all at %.1fx" % target
            if best_lbl is None or rows[(lbl, name)] > rows[(best_lbl, name)]:
                best_lbl, best_t = lbl, target
        vals, days = [], {}
        for r in both:
            v = outcome(r, grid, idx_h, best_t)
            if v is None:
                continue
            vals.append(v)
            d = int(float(r["call_ts"]) // 86400)
            days.setdefault(d, []).append(v)
        if not vals:
            continue

        def wt(xs):
            return (1.0 - DEAD_RATE) * statistics.fmean(xs) + DEAD_RATE * (-1.0)

        pooled = wt(vals)
        drop = wt(sorted(vals)[:-1]) if len(vals) > 1 else float("nan")
        eqday = (1.0 - DEAD_RATE) * statistics.fmean(
            [statistics.fmean(v) for v in days.values()]) + DEAD_RATE * (-1.0)
        pos = [x for x in vals if x > 0]
        share = (max(vals) / sum(pos) * 100.0) if pos and sum(pos) > 0 else float("nan")
        print("%-24s %9.1f%% %9.1f%% %9.1f%% %9.0f%%"
              % ("%s @ %s" % (best_lbl.replace("sell all at ", ""), name),
                 100 * pooled, 100 * drop, 100 * eqday, share))
        pt, lo, hi = day_block_ci(days, DEAD_RATE)
        if pt is not None:
            print("%-24s   %d calls over %d call-days | eq-weight CI95 [%+.1f%%, %+.1f%%]%s"
                  % ("", len(vals), len(days), 100 * lo, 100 * hi,
                     "  <- includes zero" if lo <= 0 <= hi else ""))
        else:
            print("%-24s   %d calls over %d call-days" % ("", len(vals), len(days)))
    print("   EQ-WEIGHT GOVERNS on disagreement with pooled -- clustering the CI while pooling the")
    print("   estimate is what turned an M2 result from +0.09% into -3.93%.")
    print("   TOP-1 SHARE: fraction of all positive return carried by the single best call.")
    print("   DROP BEST: the same rule with that call removed entirely.")

    print("\nWHERE THE PEAK HAPPENS -- the question the 24h study could not see")
    later = sum(1 for r in both
                if max(r["peak_h"][:337]) > max(r["peak_m"]) * 1.02)
    print("   calls whose 14d peak EXCEEDS their 24h peak: %d of %d (%.0f%%)"
          % (later, len(both), 100.0 * later / len(both)))
    ratio = sorted(max(r["peak_h"][:337]) / max(r["peak_m"]) for r in both)
    print("   14d peak / 24h peak: median x%.2f  p90 x%.2f  max x%.2f"
          % (ratio[len(ratio) // 2], ratio[int(.9 * len(ratio))], ratio[-1]))


if __name__ == "__main__":
    main()
