"""M3 -- sell it all, or keep a moonbag?

Design SEALED in PREREG_M3_MOONBAG_2026-10-11.md, SHA-256
03818a91afab0656d434afa30af26f60111412456ce602cd2a24a23147c19134, committed 55b09d22 BEFORE any
exit rule was evaluated on these paths.

Owner, via the server: "holding some could be an option, sometimes there are bigger runners."

The prereg fixes 6 primary rules, one primary cell (0-minute delay, 6% round trip), the
day-weighted mean as the governing statistic, Bonferroni |z| > 2.64 over the 6, and a paired
moonbag-vs-twin comparison. It also states, in advance, that this is expected to be UNDERPOWERED:
~6 calls/day means the clustered n is ~30, not 182, on an extremely right-skewed distribution.

caller_hash and starred are absent from the input by construction -- when to sell does not require
knowing who called it.
"""
import io
import json
import os

import numpy as np

rng = np.random.default_rng(20261011)

SRC = "syndicate_paths.jsonl"
COST = 0.06                       # primary: 6% round trip
COSTS = (0.03, 0.06, 0.10)
DELAYS = (0, 1, 5, 15, 30)        # minutes; sensitivity only
ZBAR = 2.64                       # Bonferroni 0.05/6, two-sided
DAY_S = 86_400


def load():
    rows, skipped = [], []
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("skip"):
            skipped.append(d)
            continue
        m1 = d.get("m1") or []
        h1 = d.get("h1") or []
        if len(m1) < 60 or len(h1) < 24:
            skipped.append(dict(d, skip="short_path"))
            continue
        rows.append(d)
    return rows, skipped


def path_of(d, delay_min=0):
    """Minute resolution for the first 24h, hourly thereafter, rebased to the entry.

    Closes only -- the archive stores closes, so an intrabar wick that would have triggered a
    target or a trailing stop is NOT seen. That biases target-hit rules DOWN and trailing-stop
    rules UP, and it is stated rather than corrected because the data cannot support correcting it.
    """
    m1, h1 = d["m1"], d["h1"]
    if delay_min >= len(m1):
        return None
    base = m1[delay_min]
    if not base or base <= 0:
        return None
    fine = [v / base for v in m1[delay_min:]]
    coarse = [v / base for v in h1[25:]] if len(h1) > 25 else []
    return fine + coarse


def realise(path, rule):
    """Gross multiple realised by `rule` on `path` (path[0] == 1.0 by construction)."""
    if not path:
        return None
    end = path[-1]
    h24 = path[min(1440, len(path) - 1)]
    peak = 1.0
    if rule == "R1_hold24":
        return h24
    if rule == "R2_hold7d":
        return end
    if rule == "R3_tp2x":
        for v in path:
            if v >= 2.0:
                return 2.0
        return end
    if rule == "R4_trail40":
        for v in path:
            peak = max(peak, v)
            if v <= peak * 0.60 and peak > 1.0:
                return peak * 0.60
        return end
    if rule == "R5_moon_50at2x":
        for i, v in enumerate(path):
            if v >= 2.0:
                return 0.5 * 2.0 + 0.5 * path[-1]
        return end
    if rule == "R6_moon_75at15":
        for i, v in enumerate(path):
            if v >= 1.5:
                return 0.75 * 1.5 + 0.25 * path[-1]
        return end
    raise ValueError(rule)


RULES = ["R1_hold24", "R2_hold7d", "R3_tp2x", "R4_trail40",
         "R5_moon_50at2x", "R6_moon_75at15"]
TWINS = [("R5_moon_50at2x", "R3_tp2x"), ("R6_moon_75at15", "R3_tp2x"),
         ("R5_moon_50at2x", "R2_hold7d"), ("R6_moon_75at15", "R2_hold7d")]


def returns(rows, rule, cost=COST, delay=0, zeros=()):
    """Per-call net % return, with its day, for one rule."""
    out = []
    for d in rows:
        p = path_of(d, delay)
        g = realise(p, rule) if p else None
        if g is None:
            continue
        net = ((g * (1.0 - cost)) - 1.0) * 100.0
        out.append((net, int(d["call_ts"]) // DAY_S))
    for z in zeros:
        # a rugged call scored as a total loss, per prereg section 2
        out.append((-100.0, int(z["call_ts"]) // DAY_S))
    return out


def day_stats(pairs, iters=4000):
    """Pooled mean, equal-weighted DAY mean (which governs), and the day-block interval."""
    if not pairs:
        return {}
    vals = np.asarray([v for v, _d in pairs], dtype=float)
    days = {}
    for v, d in pairs:
        days.setdefault(d, []).append(v)
    keys = list(days)
    dmeans = np.asarray([float(np.mean(days[k])) for k in keys])
    counts = np.asarray([len(days[k]) for k in keys], dtype=float)
    boots = np.empty(iters)
    for b in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        boots[b] = dmeans[pick].mean()
    boots.sort()
    lo, hi = float(boots[int(.025 * iters)]), float(boots[int(.975 * iters)])
    se = (hi - lo) / 3.92 if hi > lo else float("nan")
    corr = float(np.corrcoef(np.log(counts), dmeans)[0, 1]) if len(keys) > 2 else float("nan")
    return {"n_calls": len(vals), "n_days": len(keys),
            "pooled": float(vals.mean()), "day_ew": float(dmeans.mean()),
            "median_call": float(np.median(vals)),
            "ci": [lo, hi], "se": se,
            "z": float(dmeans.mean() / se) if se == se and se > 0 else float("nan"),
            "mde": 2.8 * se if se == se else float("nan"),
            "corr_count_mean": corr,
            "pct_positive": 100.0 * float(np.mean(vals > 0))}


def paired(rows, a, b, cost=COST):
    """Paired per-call difference: same entry, same path, different exit."""
    diffs = []
    for d in rows:
        p = path_of(d, 0)
        if not p:
            continue
        ga, gb = realise(p, a), realise(p, b)
        if ga is None or gb is None:
            continue
        va = (ga * (1 - cost) - 1) * 100
        vb = (gb * (1 - cost) - 1) * 100
        diffs.append((va - vb, int(d["call_ts"]) // DAY_S))
    return day_stats(diffs)


def main():
    rows, skipped = load()
    print("M3 MOONBAG -- prereg 03818a91, sealed before any rule touched these paths")
    print("  %d calls with usable paths, %d excluded" % (len(rows), len(skipped)))
    import collections
    print("  exclusion reasons: %s"
          % dict(collections.Counter(s.get("skip", "?") for s in skipped)))
    days = sorted({int(d["call_ts"]) // DAY_S for d in rows})
    print("  %d distinct call days -- so the CLUSTERED n is ~%d, not %d"
          % (len(days), len(days), len(rows)))
    print()
    print("  POWER FIRST, as the prereg demands. Closes only: an intrabar wick that would have")
    print("  hit a target or a trailing stop is not seen, which biases target rules DOWN and")
    print("  trailing rules UP. Stated, not corrected -- the data cannot support correcting it.")
    print()

    print("PRIMARY CELL -- 0 min delay, %.0f%% round trip, day-weighted mean GOVERNS" % (COST * 100))
    print("  %-16s %7s %6s %10s %10s %10s %9s %8s %7s"
          % ("rule", "calls", "days", "pooled", "DAY-EW", "median", "MDE", "z", "pos%"))
    print("  " + "-" * 96)
    res = {}
    for r in RULES:
        s = day_stats(returns(rows, r))
        res[r] = s
        print("  %-16s %7d %6d %+9.1f%% %+9.1f%% %+9.1f%% %8.1f%% %+8.2f %6.0f%%"
              % (r, s["n_calls"], s["n_days"], s["pooled"], s["day_ew"], s["median_call"],
                 s["mde"], s["z"], s["pct_positive"]))
    print()
    cc = [s["corr_count_mean"] for s in res.values() if s["corr_count_mean"] == s["corr_count_mean"]]
    print("  corr(log calls per day, day mean) = %+.3f median across rules" % float(np.median(cc)))
    print("  -> if that is far from zero the POOLED column is the wrong number, not just noisier.")
    print()

    print("THE MOONBAG QUESTION -- paired, same call, same path, different exit")
    print("  %-34s %10s %10s %9s %8s" % ("moonbag minus its twin", "DAY-EW", "CI95", "MDE", "z"))
    print("  " + "-" * 76)
    pr = {}
    for a, b in TWINS:
        s = paired(rows, a, b)
        pr["%s-%s" % (a, b)] = s
        print("  %-34s %+9.1f%% [%+6.1f,%+6.1f] %8.1f%% %+8.2f"
              % ("%s vs %s" % (a.split("_", 1)[1], b.split("_", 1)[1]),
                 s["day_ew"], s["ci"][0], s["ci"][1], s["mde"], s["z"]))
    print()

    print("THE DANGEROUS EXCLUSION -- prereg section 2: the 18 may be the ones that RUGGED")
    best = max(RULES, key=lambda r: res[r]["day_ew"])
    with_zeros = day_stats(returns(rows, best, zeros=skipped))
    print("  best day-weighted rule is %s at %+.1f%%" % (best, res[best]["day_ew"]))
    print("  same rule, scoring all %d excluded calls as TOTAL LOSSES: %+.1f%% (z %+.2f)"
          % (len(skipped), with_zeros["day_ew"], with_zeros["z"]))
    flip = (res[best]["day_ew"] > 0) != (with_zeros["day_ew"] > 0)
    print("  sign flips when they are counted as zeros: %s" % flip)
    print()

    print("SENSITIVITY -- reported, never promoted to a finding")
    print("  %-16s" % "rule" + "".join("%11s" % ("%dm" % d) for d in DELAYS))
    for r in RULES:
        cells = []
        for dl in DELAYS:
            s = day_stats(returns(rows, r, delay=dl))
            cells.append("%+9.1f%%" % s["day_ew"] if s else "        —")
        print("  %-16s" % r + "".join("%11s" % c for c in cells))
    print()
    print("  %-16s" % "rule" + "".join("%11s" % ("%.0f%%" % (c * 100)) for c in COSTS))
    for r in RULES:
        cells = ["%+9.1f%%" % day_stats(returns(rows, r, cost=c))["day_ew"] for c in COSTS]
        print("  %-16s" % r + "".join("%11s" % c for c in cells))
    ncells = len(RULES) * (len(DELAYS) + len(COSTS))
    print()
    print("  %d sensitivity cells examined, so the multiplicity is visible." % ncells)
    print()

    print("WALK-FORWARD -- first 15 days vs last 15, per the prereg's redefined split")
    mid = days[len(days) // 2]
    first = [d for d in rows if int(d["call_ts"]) // DAY_S < mid]
    second = [d for d in rows if int(d["call_ts"]) // DAY_S >= mid]
    print("  %-16s %12s %12s   same sign?" % ("rule", "first half", "second half"))
    for r in RULES:
        a = day_stats(returns(first, r))
        b = day_stats(returns(second, r))
        ok = (a.get("day_ew", 0) > 0) == (b.get("day_ew", 0) > 0)
        print("  %-16s %+11.1f%% %+11.1f%%   %s"
              % (r, a.get("day_ew", float("nan")), b.get("day_ew", float("nan")), ok))
    print()

    json.dump({"prereg_sha256":
               "03818a91afab0656d434afa30af26f60111412456ce602cd2a24a23147c19134",
               "n_calls": len(rows), "n_excluded": len(skipped), "n_days": len(days),
               "cost_primary": COST, "zbar": ZBAR,
               "primary": res, "paired": pr,
               "best_rule_with_zeros": with_zeros, "sensitivity_cells": ncells},
              open("syndicate_moonbag.json", "w"), indent=1)

    print("=" * 96)
    cleared = [k for k, s in pr.items() if abs(s["z"]) > ZBAR]
    under = [k for k, s in pr.items() if abs(s["day_ew"]) < s["mde"]]
    print("PAIRED MOONBAG COMPARISONS CLEARING |z| > %.2f: %s" % (ZBAR, cleared or "none"))
    print("COMPARISONS WHERE THE EFFECT IS SMALLER THAN THE DETECTION FLOOR: %d of %d"
          % (len(under), len(pr)))
    if not cleared:
        print("So: UNDERPOWERED for the moonbag question, exactly as the prereg predicted.")
        print("That is NOT evidence against moonbags. It is an absence of evidence either way.")
    print("=" * 96)


if __name__ == "__main__":
    main()
