"""Runs PREREG_SKIPGATE_2026-10-12 (sealed 7f6ffc80, sha 3705561eb4265c1d). No re-specification.

Question: is the bot's confidence floor rejecting signals that were profitable net of cost?

Data: `counterfactual_resolved` -- 145,446 skipped signals, every one resolved, on disk, no API.

Two facts the prereg fixed before any statistic was computed:
  * `hypothetical_pnl_pct` is GROSS (1,128 of 1,131 stopped-out rows show exactly minus the stop
    distance), so 9 bps of round-trip cost is subtracted everywhere;
  * 145,446 rows is not the sample -- 83 DAYS is, at ~1,752 signals/day, so the day is the
    clustering unit and the equal-weighted day mean governs.
"""
import collections
import datetime
import json
import random
import sqlite3
import statistics
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
COST_PCT = 0.09          # 9 bps round trip, the figure the server specified for the live bot
Z_BAR = 2.39             # Bonferroni, 3 families, two-sided 0.05/3
MDE_FLOOR_BPS = 16.0     # pre-committed: above this, UNDERPOWERED regardless of the estimate


def family(reason):
    r = str(reason or "")
    if r.startswith("confidence_floor"):
        return "confidence_floor_*"
    if r.startswith("graduated_rule_veto"):
        return "graduated_rule_veto*"
    return "all other reasons"


def load():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    out = []
    for ts, body in c.execute("SELECT ts, body FROM bulk_rows "
                              "WHERE stream='counterfactual_resolved'"):
        d = json.loads(body)
        p = d.get("hypothetical_pnl_pct")
        if not isinstance(p, (int, float)) or ts is None:
            continue
        out.append({
            "day": datetime.datetime.fromtimestamp(ts, datetime.UTC).date(),
            "net": p - COST_PCT,
            "gross": p,
            "fam": family(d.get("skip_reason")),
            "reason": str(d.get("skip_reason") or ""),
            "conf": d.get("confidence"),
        })
    c.close()
    return out


def day_stats(rows, key="net", nrep=4000, seed=20261012):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["day"]].append(r[key])
    days = sorted(by)
    if len(days) < 3:
        return None
    eq = statistics.fmean([statistics.fmean(by[d]) for d in days])
    pooled = statistics.fmean([r[key] for r in rows])
    rng = random.Random(seed)
    boot = sorted(statistics.fmean([statistics.fmean(by[days[rng.randrange(len(days))]])
                                    for _ in days]) for _ in range(nrep))
    lo, hi = boot[int(.025 * nrep)], boot[int(.975 * nrep)]
    sd = statistics.pstdev(boot) or 1e-12
    return {"eq": eq, "pooled": pooled, "lo": lo, "hi": hi, "z": eq / sd,
            "ndays": len(days), "n": len(rows), "by": by, "days": days}


def mde_sim(by, days, nrep=600, seed=7):
    """Smallest true effect detected at 80% power with the prereg's constant, by simulation."""
    rng = random.Random(seed)
    dm = [statistics.fmean(by[d]) for d in days]
    centred = [x - statistics.fmean(dm) for x in dm]
    for eff_bps in range(1, 201):
        eff = eff_bps / 100.0
        hits = 0
        for _ in range(nrep):
            draw = [centred[rng.randrange(len(centred))] + eff for _ in centred]
            m = statistics.fmean(draw)
            se = statistics.pstdev(draw) / (len(draw) ** 0.5) or 1e-12
            if m / se > Z_BAR:
                hits += 1
        if hits / nrep >= 0.80:
            return eff_bps
    return None


def main():
    rows = load()
    print("loaded %d resolved skipped signals over %d days"
          % (len(rows), len({r["day"] for r in rows})))
    print("cost applied: %.2f%% round trip (gross figures shown alongside)\n" % COST_PCT)

    fams = collections.Counter(r["fam"] for r in rows)
    print("%-24s %8s %7s %10s %10s %22s %7s"
          % ("family", "n", "days", "pooled", "EQ-DAY", "CI95 (eq, net)", "z"))
    results = {}
    for fam in ("confidence_floor_*", "graduated_rule_veto*", "all other reasons"):
        sub = [r for r in rows if r["fam"] == fam]
        if not sub:
            continue
        s = day_stats(sub)
        g = day_stats(sub, key="gross")
        results[fam] = s
        print("%-24s %8d %7d %9.3f%% %9.3f%% [%+8.3f%%, %+8.3f%%] %+7.2f"
              % (fam, s["n"], s["ndays"], s["pooled"], s["eq"], s["lo"], s["hi"], s["z"]))
        print("%-24s %8s %7s %9.3f%% %9.3f%%   (gross, before the %.2f%% cost)"
              % ("", "", "", g["pooled"], g["eq"], COST_PCT))

    print("\n--- PRIMARY: confidence_floor_* , net of cost ---")
    s = results.get("confidence_floor_*")
    if not s:
        print("  family absent"); return
    print("  equal-weighted day mean %+.3f%% (%.1f bps)   CI95 [%+.3f%%, %+.3f%%]   z %+.2f"
          % (s["eq"], s["eq"] * 100, s["lo"], s["hi"], s["z"]))
    print("  pooled per-signal       %+.3f%%   -> signs %s"
          % (s["pooled"], "AGREE" if (s["pooled"] > 0) == (s["eq"] > 0) else "DISAGREE"))
    print("  bar to clear: |z| > %.2f (Bonferroni, 3 families)" % Z_BAR)
    print("  CI excludes zero: %s" % ("YES" if (s["lo"] > 0 or s["hi"] < 0) else "NO"))

    mid = s["days"][len(s["days"]) // 2]
    h1 = [r for r in rows if r["fam"] == "confidence_floor_*" and r["day"] < mid]
    h2 = [r for r in rows if r["fam"] == "confidence_floor_*" and r["day"] >= mid]
    a, b = day_stats(h1), day_stats(h2)
    if a and b:
        print("  walk-forward halves: %+.3f%% / %+.3f%%  -> %s"
              % (a["eq"], b["eq"], "SIGN-STABLE" if (a["eq"] > 0) == (b["eq"] > 0) else "FLIPS"))

    m = mde_sim(s["by"], s["days"])
    print("\n  MDE (simulated, 80%% power at z %.2f): %s bps" % (Z_BAR, m if m else ">200"))
    print("  pre-committed floor: %.0f bps. Effect to beat is the gross aggregate less cost."
          % MDE_FLOOR_BPS)
    under = (m is None) or (m > MDE_FLOOR_BPS)
    print("  -> %s" % ("UNDERPOWERED by the pre-commitment" if under
                       else "powered enough to resolve the stated effect"))

    print("\n--- PLACEBO 1: day-label shuffle (size must be ~5%) ---")
    rng = random.Random(99)
    cf = [r for r in rows if r["fam"] == "confidence_floor_*"]
    dm = [statistics.fmean(v) for v in s["by"].values()]
    centred = [x - statistics.fmean(dm) for x in dm]
    rej = 0
    N = 2000
    for _ in range(N):
        draw = [centred[rng.randrange(len(centred))] for _ in centred]
        mm = statistics.fmean(draw)
        se = statistics.pstdev(draw) / (len(draw) ** 0.5) or 1e-12
        if abs(mm / se) > Z_BAR:
            rej += 1
    print("  rejection rate %.1f%% -> %s"
          % (100.0 * rej / N, "size OK" if 0.01 <= rej / N <= 0.12
             else "SIZE WRONG: result is unmeasurable, not null"))

    print("\n--- PLACEBO 3: shuffled reason within day (must be null) ---")
    byday = collections.defaultdict(list)
    for r in rows:
        byday[r["day"]].append(r)
    rng2 = random.Random(5)
    sh = []
    for d, grp in byday.items():
        fl = [r["fam"] for r in grp]
        rng2.shuffle(fl)
        for r, f in zip(grp, fl):
            sh.append({"day": d, "net": r["net"], "fam": f})
    ss = day_stats([r for r in sh if r["fam"] == "confidence_floor_*"])
    print("  shuffled confidence_floor_* eq-day mean %+.3f%%  z %+.2f  -> %s"
          % (ss["eq"], ss["z"], "null as required" if abs(ss["z"]) < Z_BAR
             else "NOT NULL: families differ by day composition, not by reason"))

    print("\n--- SECONDARY (descriptive only, multiplicity NOT corrected) ---")
    byfloor = collections.defaultdict(list)
    for r in cf:
        f = r["reason"].replace("confidence_floor_", "")
        if f.isdigit():
            byfloor[int(f)].append(r)
    print("  %-8s %8s %7s %11s" % ("floor", "n", "days", "eq-day net"))
    for f in sorted(byfloor):
        sub = byfloor[f]
        if len(sub) < 200:
            continue
        st = day_stats(sub, nrep=400)
        if st:
            print("  %-8d %8d %7d %10.3f%%" % (f, st["n"], st["ndays"], st["eq"]))
    print("  ^ shape only. The prereg forbids this becoming the headline.")


if __name__ == "__main__":
    main()
