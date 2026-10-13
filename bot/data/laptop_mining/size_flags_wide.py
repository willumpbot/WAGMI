"""PREREG_FUNDING_WIDE (sha256 ecf331b4 = sealed 41805c5c + amendments 1-4) — the out-of-sample
replication.

Does `funding_hot` replicate on the 156 coins it was never tested on?

`SIZE_FLAGS` found funding_hot predicts a **+7.7% level** bigger next-day |move| than the HAR forecast
alone (+0.0740 is the week-mean LOG coefficient; I spent a session misquoting it as the percentage).
It is the only finding that has ever survived a red team here -- though on audit it is **"positive but
underpowered"**: significant at t 3.28 on 145 week-clusters, yet its effect sits under its own mde80.
The PC's knowledge registry carded it PROVEN and has since downgraded it to SUPPORTED.

It was discovered on 17 perps because 17 was all that was cached. The universe is 173. **The other
156 are a genuine held-out sample**, and this project has never run a real out-of-sample replication:
every prior "confirmation" was a re-cut of the discovery sample, which is how M2 survived six
readings.

GATE. Refuses to run below MIN_FUNDING_FILES of the qualifying perps. `load_funding` returns {} for a
missing file, which marks a coin silently and permanently UNFLAGGED and biases the comparison. A
missing source is never a zero.

THE DISCOVERY SAMPLE, recovered from the filesystem rather than from my own notes: `fetch_1d_wide.py`
skipped any `_1d.csv` with >365 rows, so the original 17 kept their pre-existing mtimes. Exactly 17
perp files are dated 2026-10-08 and all 161 new ones are dated 2026-10-12. That set matches what I had
recorded, independently.

POPULATIONS -- not interchangeable, per the prereg:
    (c)     NEW156  volume-filtered. HELD OUT. **THE NUMBER TO ACT ON.**
    (b)     ORIG17  volume-filtered. The discovery sample once fabricated rows are removed.
    (b_raw) ORIG17  UNFILTERED. **THE PIPELINE CANARY** -- must reproduce ~+0.0740 log / +7.7%
                    level, because SIZE_FLAGS itself ran on the contaminated panel. Rebuilds to
                    exactly 19,853 coin-days, matching what SIZE_FLAGS reported.
    (c_raw) NEW156  UNFILTERED. **SECONDARY sensitivity arm only** (amendment 3). Cannot change the
                    verdict; if it disagrees, the result is "filter-dependent" and the FILTERED arm
                    governs, because fabricated prices are not data.
    (a)     ALL173  completeness only. CONTAMINATED by (b); never quoted as the replication.

ARMS -- widening redefines the treatment, because funding_hot is a top-quintile RANK, not a
threshold. Top 20% of 17 coins is not top 20% of 173.
    PRIMARY   rank arm      quintile computed WITHIN the population tested (matches the live
                            scanner, which ranks across the coins it scans)
    SECONDARY frozen arm    quintile cutoff taken per-date from ORIG17 and applied to the subset
    Disagreement between arms is itself the result: reported as RANK-DEPENDENCE, neither promoted.

WHY `matched()` IS VECTORIZED HERE. The original loops over cells in Python. At 119 coins per date the
panel has ~6,900 date x em-quintile cells, and the power block needs PLACEBO permutations x 5 deltas x
6 population-arm combos -- tens of millions of cell operations, which does not finish. The vectorized
version computes identical quantities with bincount.

**Rewriting the core statistic is exactly where a silent bug would go**, and this project has already
shipped three ingester defects of mine. So `selftest()` asserts the vectorized and original
implementations agree to 1e-9 on RANDOM masks. Random, deliberately: it proves the rewrite is
equivalent without reading any real flag-vs-outcome quantity, which the prereg forbids before the
single gated run.

Report order is fixed by the prereg and enforced by the code: size at delta=0 -> MDE -> week counts ->
only then any effect. If size is outside SIZE_OK the run prints TEST BROKEN and issues no verdict.
"""
import collections
import csv
import datetime
import glob
import io
import json
import math
import os
import warnings

warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
EPS = 1e-8
START = "2023-01-01"          # frozen by the prereg; see the provenance note below
MAX_STALE = 0.02
PLACEBO = 400              # AMENDMENT 4(D): halves the Monte Carlo error on size and power
MIN_WEEKS = 8                 # matched() requires this many week clusters
MIN_FUNDING_FILES = 170       # the prereg's gate
SIZE_OK = (0.001, 0.09)       # AMENDMENT 4(D): the UPPER bound (over-rejection) is the real gate and is
                              # unchanged. The old lower bound of 0.02 treated a CONSERVATIVE test as
                              # broken -- but under-rejection makes a significant result stronger, not
                              # weaker, and 0.02 sat inside the Monte Carlo error of the size estimate
                              # itself. Now only a degenerate test that never rejects is caught.
CONSERVATIVE_BELOW = 0.03     # label, not a gate: significance achieved against a stricter-than-nominal bar
# AMENDMENT 1(B): finer grid. A grid of {0,.03,.05,.10,.20} can only ever return an MDE from that
# set, which is how SIZE_FLAGS' true effect of 0.074 ended up compared against a reported MDE of
# 0.10. MDE is now interpolated between the bracketing points at 80% power.
DELTAS = (0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.075, 0.10, 0.15, 0.20)
TARGET_POWER = 0.80


def mde_interp(power):
    """Linearly interpolated delta at TARGET_POWER. None if power never reaches it on the grid."""
    ds = [d for d in DELTAS if d > 0]
    for i, d in enumerate(ds):
        if power[d] >= TARGET_POWER:
            if i == 0:
                return d
            lo, hi = ds[i - 1], d
            plo, phi = power[lo], power[hi]
            if phi <= plo:
                return hi
            return lo + (TARGET_POWER - plo) * (hi - lo) / (phi - plo)
    return None
rng = np.random.default_rng(20261012)

# Recovered by mtime, not from notes. See the module docstring.
ORIG17 = ("ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC")

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]   # unchanged, unrefitted: out-of-sample by design


# ---------------------------------------------------------------- loaders (verbatim from size_flags)
def load_daily(sym):
    rows = []
    with io.open(os.path.join(HIST, "%s_1d.csv" % sym), encoding="utf-8",
                 errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"]), float(r.get("v") or 0)))
            except (TypeError, ValueError):
                continue
    rows.sort()
    return rows


def load_funding(sym):
    p = os.path.join(HIST, "%s_funding.csv" % sym)
    if not os.path.exists(p):
        return {}
    byday = collections.defaultdict(list)
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                t = int(r["t_ms"]) // 1000
                byday[datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d")
                      ].append(float(r["rate"]))
            except (TypeError, ValueError):
                continue
    return {d: float(np.mean(v)) for d, v in byday.items() if v}


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def universe():
    alls = sorted({os.path.basename(p).split("_1d")[0]
                   for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
    syms, drop = [], collections.Counter()
    for s in alls:
        if s.endswith("_spot") or s.endswith("_wspot"):
            drop["spot"] += 1
            continue
        d = load_daily(s)
        if len(d) < 200:
            drop["under_200_bars"] += 1
            continue
        if sum(1 for x in d if x[1] == x[2] == x[3] == x[4]) / len(d) > MAX_STALE:
            drop["stale_over_2pct"] += 1
            continue
        syms.append(s)
    return syms, drop


def build(syms, vol_filter=True):
    """Panel of coin-days with the HAR forecast `em`, next-day |move|, and raw funding.

    AMENDMENT 2: `vol_filter` removes Hyperliquid's own pre-listing backfill, which carries MOVING
    OHLC with v=0 and n=0 and is therefore invisible to the MAX_STALE check (o==h==l==c is false).
    11.9% of the analysis window is such rows, and they can never be flagged -- no funding exists
    before a coin trades -- so they sit entirely in the UNFLAGGED arm as fabricated price paths.

    Zero-volume runs are a clean PREFIX for 93 of 178 coins (83 have none), so truncating to the
    first v>0 bar removes every synthetic bar while keeping a contiguous daily grid for rv1/rv5/rv22.
    Only BANANA (8 bars) and VVV (1) have interior zeros; those coin-days are dropped individually.

    vol_filter=False reproduces SIZE_FLAGS' contaminated panel, needed for the (b_raw) canary.
    """
    rows = []
    removed = 0
    for s in syms:
        d = load_daily(s)
        if vol_filter:
            fz = next((i for i, x in enumerate(d) if x[5] > 0), None)
            if fz is None:
                continue                      # never traded: no real bars at all
            removed += fz
            d = d[fz:]
        fnd = load_funding(s)
        t = [x[0] for x in d]
        c = [x[4] for x in d]
        vol = [x[5] for x in d]
        day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") for x in t]
        rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
        for i in range(30, len(c) - 2):
            if day[i] < START:
                continue
            if vol_filter and (vol[i] == 0 or vol[i + 1] == 0):
                removed += 1                  # interior zero on the row or its outcome bar
                continue
            rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
            if rv22 <= 0 or rv5 <= 0:
                continue
            z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
                 + Y1B[3] * math.log(rv22 + EPS))
            em = math.exp(z) * Y1S
            if em <= 0:
                continue
            nxt = abs(rets[i + 1])
            if nxt <= 0:
                continue
            wk = datetime.date.fromisoformat(day[i]).isocalendar()
            rows.append({"sym": s, "day": day[i], "week": "%d-W%02d" % (wk[0], wk[1]),
                         "em": em, "move": nxt, "funding": fnd.get(day[i])})
    df = pd.DataFrame(rows)
    df["lr"] = np.log(df["move"] + EPS) - np.log(df["em"] + EPS)
    df.attrs["vol_removed"] = removed
    df.attrs["vol_filter"] = vol_filter
    return df


# ------------------------------------------------------------------------ the statistic, two ways
def cellify(sub):
    """Integer cell ids for date x em-quintile, and each cell's week.

    AMENDMENT 4 -- THE DEFECT THAT VOIDED THE FIRST RUN. `size_flags.py:148` buckets em GLOBALLY
    across the whole panel:

        df["emq"] = pd.qcut(df["em"], 5, labels=False, duplicates="drop")

    I had bucketed PER DATE, because the design docstring says "within the same date AND the same em
    quintile" and per-date quintiles are a defensible reading of that sentence. The CODE does global
    quintiles, and the code is what produced +7.7%. Per-date gave 2,944 matched cells and +5.64%;
    global gives 2,283 and +0.0740 log = +7.68%, matching every number SIZE_FLAGS reported.

    Third instance in one session of re-deriving a baseline from prose instead of reading the
    implementation. The canary existed to catch exactly this, and it did.
    """
    q = pd.qcut(sub["em"], 5, labels=False, duplicates="drop")
    key = sub["day"].astype(str) + "|" + pd.Series(q, index=sub.index).fillna(0).astype(int).astype(str)
    codes, uniq = pd.factorize(key)
    cweek = np.array([datetime.date.fromisoformat(k.split("|")[0]).isocalendar()[:2] for k in uniq])
    wkey = ["%d-W%02d" % (a, b) for a, b in cweek]
    wcodes, _ = pd.factorize(pd.Series(wkey))
    return codes.astype(np.int64), wcodes.astype(np.int64), len(uniq)


def matched_vec(f, lr, cell, cweek, ncell, nweek, inject=0.0):
    """Vectorized equivalent of size_flags.matched(): cell diff -> week mean -> mean over weeks."""
    nf = ~f
    s1 = np.bincount(cell[f], weights=lr[f], minlength=ncell)
    c1 = np.bincount(cell[f], minlength=ncell)
    s0 = np.bincount(cell[nf], weights=lr[nf], minlength=ncell)
    c0 = np.bincount(cell[nf], minlength=ncell)
    ok = (c1 > 0) & (c0 > 0)
    if not ok.any():
        return None
    diff = np.empty(ncell)
    diff[ok] = (s1[ok] / c1[ok] + inject) - (s0[ok] / c0[ok])
    w = cweek[ok]
    ws = np.bincount(w, weights=diff[ok], minlength=nweek)
    wc = np.bincount(w, minlength=nweek)
    have = wc > 0
    if have.sum() < MIN_WEEKS:
        return None
    mus = ws[have] / wc[have]
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return float(mus.mean()), se, int(have.sum()), int(ok.sum())


def matched_ref(f, lr, cellkeys, inject=0.0):
    """size_flags.matched() verbatim in shape -- the reference the vectorized version must match."""
    byw = collections.defaultdict(list)
    for k, idx in cellkeys.items():
        fl = f[idx]
        if fl.all() or not fl.any():
            continue
        a = lr[idx][fl] + inject
        b = lr[idx][~fl]
        ic = datetime.date.fromisoformat(k.split("|")[0]).isocalendar()
        byw["%d-W%02d" % (ic[0], ic[1])].append(a.mean() - b.mean())
    if len(byw) < MIN_WEEKS:
        return None
    mus = np.array([np.mean(v) for v in byw.values()])
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return float(mus.mean()), se, len(mus), sum(len(v) for v in byw.values())


def permute_in_cells(f, cell, ncell):
    """Permute f within each cell, vectorized: rank rows by a random key inside their cell."""
    n = len(f)
    u = rng.random(n)
    order = np.lexsort((u, cell))
    cs = np.bincount(cell, minlength=ncell)
    start = np.concatenate(([0], np.cumsum(cs)[:-1]))
    pos = np.arange(n) - start[cell[order]]
    k = np.bincount(cell[f], minlength=ncell)
    out = np.empty(n, dtype=bool)
    out[order] = pos < k[cell[order]]
    return out


def selftest(df):
    """Prove the rewrite is equivalent WITHOUT reading any real flag-vs-outcome quantity.

    Masks are random by design: equivalence is a property of the code, and checking it on the real
    funding_hot flag would be a read the prereg forbids before the single gated run.
    """
    sub = df[df["sym"].isin(ORIG17)].reset_index(drop=True)
    if sub.empty:
        return "skipped (no ORIG17 rows)"
    cell, cweek, ncell = cellify(sub)
    lr = sub["lr"].values
    keys = {}
    q = pd.Series(cell).astype(str)
    for k, g in sub.assign(_c=pd.Series(cell).map(lambda i: i)).groupby("_c"):
        keys[str(sub["day"].values[g.index[0]]) + "|" + str(k)] = g.index.values
    nweek = int(cweek.max()) + 1
    worst = 0.0
    for trial in range(5):
        f = rng.random(len(sub)) < 0.2
        a = matched_vec(f, lr, cell, cweek, ncell, nweek)
        b = matched_ref(f, lr, keys)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return "MISMATCH on trial %d: one returned None (%s vs %s)" % (trial, a, b)
        worst = max(worst, abs(a[0] - b[0]), abs(a[1] - b[1]))
        if a[2] != b[2]:
            return "MISMATCH week count on trial %d: %d vs %d" % (trial, a[2], b[2])
    return "OK (max abs diff %.2e over 5 random masks)" % worst


# ------------------------------------------------------------------------------------- flag arms
def flag_rank(sub):
    """PRIMARY: top funding quintile per date, computed within this population."""
    out = np.zeros(len(sub), dtype=bool)
    for _, g in sub.groupby("day"):
        f = g["funding"]
        if f.notna().sum() < 5:
            continue
        thr = f.quantile(0.80)
        if pd.isna(thr):
            continue
        out[g.index.values[(f >= thr).fillna(False).values]] = True
    return out


def flag_frozen(sub, cutoffs):
    """SECONDARY: per-date cutoff frozen from ORIG17, applied to this population."""
    out = np.zeros(len(sub), dtype=bool)
    for d, g in sub.groupby("day"):
        thr = cutoffs.get(d)
        if thr is None:
            continue
        f = g["funding"]
        out[g.index.values[(f >= thr).fillna(False).values]] = True
    return out


def orig17_cutoffs(df):
    cut = {}
    o = df[df["sym"].isin(ORIG17)]
    for d, g in o.groupby("day"):
        f = g["funding"]
        if f.notna().sum() >= 5:
            t = f.quantile(0.80)
            if not pd.isna(t):
                cut[d] = float(t)
    return cut


def analyse(name, sub, mask):
    """Power FIRST, then MDE, then weeks, then the effect. Order enforced by construction."""
    sub = sub.reset_index(drop=True)
    cell, cweek, ncell = cellify(sub)
    nweek = int(cweek.max()) + 1 if len(cweek) else 0
    lr = sub["lr"].values
    base = matched_vec(mask, lr, cell, cweek, ncell, nweek)
    if base is None:
        return {"population": name, "verdict": "INSUFFICIENT CELLS"}
    power = {}
    for d in DELTAS:
        hits = 0
        for _ in range(PLACEBO):
            p = permute_in_cells(mask, cell, ncell)
            r = matched_vec(p, lr, cell, cweek, ncell, nweek, inject=d)
            if r and (r[0] - 1.96 * r[1]) > 0:
                hits += 1
        power[d] = hits / PLACEBO
    size = power[0.0]
    mde_d = mde_interp(power)
    res = {"population": name, "coins": int(sub["sym"].nunique()), "rows": len(sub),
           "size_at_0": round(size, 3), "size_ok": SIZE_OK[0] <= size <= SIZE_OK[1],
           "power": {str(k): round(v, 3) for k, v in power.items()},
           "mde_log": mde_d, "mde_pct": (None if mde_d is None
                                         else round(100 * (math.exp(mde_d) - 1), 2)),
           "weeks": base[2], "cells": base[3],
           "week_mean_log": round(base[0], 4), "se": round(base[1], 4),
           "level_pct": round(100 * (math.exp(base[0]) - 1), 2),
           "ci_pct": [round(100 * (math.exp(base[0] - 1.96 * base[1]) - 1), 2),
                      round(100 * (math.exp(base[0] + 1.96 * base[1]) - 1), 2)],
           "flag_fired_pct": round(100 * float(mask.mean()), 2)}
    # AMENDMENT 1(A): the old rule said "effect below MDE => unmeasurable", which applied to the
    # discovery sample would have declared SIZE_FLAGS itself unmeasurable (+7.68% against an mde80
    # of +10.5%, at t 3.28). That conflates "could we have detected an effect of size X" with "did
    # we detect one". 80% power is a design target, not a detection threshold. Reported separately:
    eff, se = base[0], base[1]
    lo, hi = eff - 1.96 * se, eff + 1.96 * se
    excludes_zero = (lo > 0) or (hi < 0)
    powered = (mde_d is not None) and (abs(eff) >= mde_d)
    res["excludes_zero"] = bool(excludes_zero)
    res["powered"] = bool(powered)
    res["conservative"] = bool(size < CONSERVATIVE_BELOW)
    if not res["size_ok"]:
        res["verdict"] = "TEST BROKEN (size %.3f outside [%.3f, %.2f])" % (size, *SIZE_OK)
    elif excludes_zero and eff > 0:
        res["verdict"] = "replicates" if powered else "positive but underpowered"
    elif excludes_zero and eff < 0:
        res["verdict"] = ("contradicts: significant NEGATIVE" if powered
                          else "negative but underpowered")
    elif powered:
        res["verdict"] = "does not replicate"      # we could have seen it and did not
    else:
        res["verdict"] = "unmeasurable"
    return res


def main():
    syms, drop = universe()
    have_f = sum(1 for s in syms if os.path.exists(os.path.join(HIST, "%s_funding.csv" % s)))
    print("universe: %d qualifying perps (%s)" % (len(syms), dict(drop)))
    print("funding files for qualifying perps: %d / %d" % (have_f, len(syms)))
    if have_f < MIN_FUNDING_FILES:
        print("\nGATED: the prereg requires >= %d funding files. A missing source is never a zero --"
              % MIN_FUNDING_FILES)
        print("load_funding returns {} for a missing file, which would mark those coins silently and")
        print("permanently UNFLAGGED and bias the comparison. NOT RUNNING.")
        return
    df = build(syms)
    print("panel: %d coin-days, %d coins, %s..%s"
          % (len(df), df["sym"].nunique(), df["day"].min(), df["day"].max()))

    st = selftest(df)
    print("\nSELFTEST vectorized vs reference matched(): %s" % st)
    if not st.startswith("OK") and not st.startswith("skipped"):
        print("HALTING: the rewritten statistic does not match the original.")
        return

    # AMENDMENT 2(D): SIZE_FLAGS ran on the contaminated panel, so a volume-filtered ORIG17 cannot
    # serve as the pipeline canary. The unfiltered ORIG17 is the canary; it must reproduce +0.0740.
    raw17 = build(list(ORIG17), vol_filter=False)
    print("canary panel (ORIG17, NO volume filter): %d coin-days -- SIZE_FLAGS reported 19,853"
          % len(raw17))
    # AMENDMENT 3: the headline population is 12.1% synthetic, MORE than the discovery sample's
    # 10.7%, so the filter decision gets a sensitivity arm. SECONDARY ONLY -- it cannot change the
    # verdict. If the two disagree the result is "filter-dependent" and the FILTERED arm governs,
    # because fabricated prices are not data.
    rawnew = build([s for s in syms if s not in ORIG17], vol_filter=False)
    print("sensitivity panel (NEW156, NO volume filter): %d coin-days" % len(rawnew))
    cutoffs = orig17_cutoffs(df)
    pops = [("c_NEW156", df[~df["sym"].isin(ORIG17)]),
            ("b_ORIG17", df[df["sym"].isin(ORIG17)]),
            ("b_raw_ORIG17_NOFILTER", raw17),
            ("c_raw_NEW156_NOFILTER_sensitivity", rawnew),
            ("a_ALL173", df)]
    out = {"prereg": "PREREG_FUNDING_WIDE ecf331b4 (amendments 1-4)", "start": START,
           "universe": len(syms), "funding_files": have_f, "selftest": st,
           "vol_removed_rows": df.attrs.get("vol_removed"),
           "panel_rows_filtered": len(df), "panel_rows_canary": len(raw17), "results": []}
    for arm, fn in (("rank_PRIMARY", flag_rank), ("frozen_SECONDARY",
                                                  lambda s: flag_frozen(s, cutoffs))):
        for nm, sub in pops:
            if (nm.endswith("NOFILTER") or nm.endswith("sensitivity")) \
                    and arm != "rank_PRIMARY":
                continue    # unfiltered arms only mean anything under the original rank rule
            sub = sub.reset_index(drop=True)
            r = analyse("%s|%s" % (nm, arm), sub, fn(sub))
            r["arm"] = arm
            out["results"].append(r)
            print("\n--- %s | %s ---" % (nm, arm))
            if r.get("verdict") == "INSUFFICIENT CELLS":
                print("  INSUFFICIENT CELLS")
                continue
            print("  size@0 %.3f (%s) | power %s" % (r["size_at_0"],
                  "ok" if r["size_ok"] else "BROKEN", r["power"]))
            print("  MDE %s%% | weeks %d | cells %d | flag fired %.1f%%"
                  % (r["mde_pct"], r["weeks"], r["cells"], r["flag_fired_pct"]))
            print("  effect %+.2f%% CI [%+.2f, %+.2f] -> %s%s"
                  % (r["level_pct"], r["ci_pct"][0], r["ci_pct"][1], r["verdict"],
                     ("  [CONSERVATIVE test, size %.3f -- significance won against a stricter bar]"
                      % r["size_at_0"]) if r.get("conservative") else ""))
    io.open(os.path.join(HERE, "size_flags_wide.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote size_flags_wide.json")
    print("\nREMINDER: (c)_NEW156 is the replication. (a)_ALL173 contains the discovery sample and")
    print("must not be quoted as one. Disagreement between arms = rank-dependence, not an answer.")


if __name__ == "__main__":
    main()
