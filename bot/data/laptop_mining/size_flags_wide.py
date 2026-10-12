"""PREREG_FUNDING_WIDE (sha256 41805c5c, commit b1144936) — the out-of-sample replication.

Does `funding_hot` replicate on the 156 coins it was never tested on?

`SIZE_FLAGS` found funding_hot predicts a +7.4% bigger next-day |move| than the HAR forecast alone --
the only finding that has ever survived a red team in this project. It was discovered on 17 perps
because 17 was all that was cached. The universe is 173. **The other 156 are a genuine held-out
sample**, and this project has never run a real out-of-sample replication: every prior
"confirmation" was a re-cut of the discovery sample, which is how M2 survived six readings.

GATE. Refuses to run below MIN_FUNDING_FILES of the qualifying perps. `load_funding` returns {} for a
missing file, which marks a coin silently and permanently UNFLAGGED and biases the comparison. A
missing source is never a zero.

THE DISCOVERY SAMPLE, recovered from the filesystem rather than from my own notes: `fetch_1d_wide.py`
skipped any `_1d.csv` with >365 rows, so the original 17 kept their pre-existing mtimes. Exactly 17
perp files are dated 2026-10-08 and all 161 new ones are dated 2026-10-12. That set matches what I had
recorded, independently.

POPULATIONS -- not interchangeable, per the prereg:
    (c) NEW156  held out. THE NUMBER TO ACT ON.
    (b) ORIG17  discovery sample. A PIPELINE CANARY, not evidence. Expected near +7.4%.
    (a) ALL173  reported for completeness. CONTAMINATED by (b); never quoted as the replication.

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
PLACEBO = 200
MIN_WEEKS = 8                 # matched() requires this many week clusters
MIN_FUNDING_FILES = 170       # the prereg's gate
SIZE_OK = (0.02, 0.09)        # delta=0 false-positive rate; outside this => TEST BROKEN
DELTAS = (0.0, 0.03, 0.05, 0.10, 0.20)
TARGET_POWER = 0.80
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


def build(syms):
    """Panel of coin-days with the HAR forecast `em`, next-day |move|, and raw funding."""
    rows = []
    for s in syms:
        d = load_daily(s)
        fnd = load_funding(s)
        t = [x[0] for x in d]
        c = [x[4] for x in d]
        day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") for x in t]
        rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
        for i in range(30, len(c) - 2):
            if day[i] < START:
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
    return df


# ------------------------------------------------------------------------ the statistic, two ways
def cellify(sub):
    """Integer cell ids for date x em-quintile WITHIN this population, and each cell's week."""
    q = sub.groupby("day")["em"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop") if s.notna().sum() >= 5 else 0)
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
    mde_d = next((d for d in DELTAS[1:] if power[d] >= TARGET_POWER), None)
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
    if not res["size_ok"]:
        res["verdict"] = "TEST BROKEN (size %.3f outside [%.2f, %.2f])" % (size, *SIZE_OK)
    elif mde_d is None or abs(res["level_pct"]) < (res["mde_pct"] or 1e9):
        res["verdict"] = "unmeasurable"
    elif base[0] - 1.96 * base[1] > 0:
        res["verdict"] = "replicates"
    else:
        res["verdict"] = "does not replicate"
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

    cutoffs = orig17_cutoffs(df)
    pops = [("c_NEW156", df[~df["sym"].isin(ORIG17)]),
            ("b_ORIG17", df[df["sym"].isin(ORIG17)]),
            ("a_ALL173", df)]
    out = {"prereg": "PREREG_FUNDING_WIDE 41805c5c", "start": START,
           "universe": len(syms), "funding_files": have_f, "selftest": st, "results": []}
    for arm, fn in (("rank_PRIMARY", flag_rank), ("frozen_SECONDARY",
                                                  lambda s: flag_frozen(s, cutoffs))):
        for nm, sub in pops:
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
            print("  effect %+.2f%% CI [%+.2f, %+.2f] -> %s"
                  % (r["level_pct"], r["ci_pct"][0], r["ci_pct"][1], r["verdict"]))
    io.open(os.path.join(HERE, "size_flags_wide.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote size_flags_wide.json")
    print("\nREMINDER: (c)_NEW156 is the replication. (a)_ALL173 contains the discovery sample and")
    print("must not be quoted as one. Disagreement between arms = rank-dependence, not an answer.")


if __name__ == "__main__":
    main()
