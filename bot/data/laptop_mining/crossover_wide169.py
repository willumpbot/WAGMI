"""The crossover grid on the widest panel available, with the panel chosen on POWER, not results.

WHY AGAIN. `horizon_wide.json` (42 coins, 208 days) resolved the short end: cross-sectional
REVERSAL at 1h clears Bonferroni (-3.0 bps, z -4.8), independently confirming the 5m result on a
different panel. It did NOT resolve the middle: a 24h lookback at a 24h horizon showed +17.3 bps
against a 26.8 bps detection floor.

That middle band is the one the live bot actually occupies -- median hold 3.0h, and
`ENTRY_TIMING.md` found its counter-trend entries win 17% vs 42%. So resolving it matters beyond
curiosity.

THE PANEL CHOICE IS A TRADEOFF AND IS MADE FIRST. Short-history small caps buy coins at the cost
of days. Power for a rank-weighted cross-sectional spread rises roughly with sqrt(n_coins) (finer
ranks, less idiosyncratic noise) and sqrt(n_days). So the script prints the whole tradeoff table,
picks the maximum of that projection, and only then runs the grid -- the panel is selected on a
formula declared in advance, never on which panel gave the nicer answer.

Listing bias is controlled the same way as before: a coin must cover the WHOLE chosen window.
"""
import csv
import glob
import io
import json
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261011)

LB = (1, 4, 12, 24, 72, 168)
HZ = (1, 4, 12, 24, 72, 168)
SHUFFLES = 12
ZBAR = 3.09
HOUR = 3_600_000
MDE_42 = {1: 1.56, 4: 5.93, 12: 16.05, 24: 26.77, 72: 60.55, 168: 106.83}


def coverage():
    cov = {}
    for p in sorted(glob.glob(os.path.join("history1h", "*_1h.csv"))):
        sym = os.path.basename(p).replace("_1h.csv", "")
        t = []
        with io.open(p, encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    t.append(int(r[0]))
                except (ValueError, IndexError):
                    continue
        if len(t) > 400:
            t = np.asarray(sorted(t))
            cov[sym] = (int(t[0]), int(t[-1]), len(t))
    return cov


def choose_panel(cov):
    end = min(v[1] for v in cov.values())
    print("COVERAGE TRADEOFF -- more coins vs more days. Printed BEFORE any result.")
    print("  %d coins with >400 bars of 1h history" % len(cov))
    print()
    print("  %-8s %7s %7s %11s %12s" % ("window", "coins", "days", "coin-days", "proj. power"))
    best = None
    for days in (45, 60, 90, 120, 150, 180, 208):
        start = end - days * 24 * HOUR
        keep = [s for s, (a, b, _n) in cov.items() if a <= start + HOUR and b >= end - HOUR]
        if len(keep) < 12:
            continue
        pw = np.sqrt(max(len(keep) - 1, 1)) * np.sqrt(days)
        print("  %-8s %7d %7d %11d %12.1f" % ("%dd" % days, len(keep), days,
                                              len(keep) * days, pw))
        if best is None or pw > best[0]:
            best = (pw, days, keep, start)
    print()
    print("  CHOSEN: %dd window, %d coins -- the maximum of the projection above, which was"
          % (best[1], len(best[2])))
    print("  fixed before the grid ran. Every coin covers the whole window (no listing bias).")
    return best


def load(keep, start):
    rows = []
    for s in keep:
        with io.open(os.path.join("history1h", "%s_1h.csv" % s), encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    t = int(r[0])
                    if t >= start:
                        rows.append((s, t, float(r[4])))
                except (ValueError, IndexError):
                    continue
    df = pd.DataFrame(rows, columns=["sym", "t", "c"])
    return df.drop_duplicates(["sym", "t"]).sort_values(["sym", "t"])


def legs(v, f):
    r = np.argsort(np.argsort(v)).astype(float)
    w = r - r.mean()
    s = np.abs(w).sum()
    return float(np.dot(2.0 * w / s, f)) if s else np.nan


def paired(df, nk, sig, fwd, sh=SHUFFLES):
    out = []
    for _t, g in df.groupby("t"):
        g = g.dropna(subset=[sig, fwd])
        if len(g) < nk * 0.8:
            continue
        v, f = g[sig].values, g[fwd].values
        real = legs(v, f)
        if real != real:
            continue
        nl = []
        for _ in range(sh):
            w = v.copy()
            rng.shuffle(w)
            x = legs(w, f)
            if x == x:
                nl.append(x)
        if nl:
            out.append(real - float(np.mean(nl)))
    return np.asarray(out)


def ci(r, block, iters=1200):
    b = max(24, block)
    if len(r) < b * 8:
        return float("nan"), float("nan")
    st = np.arange(len(r) - b + 1)
    n = max(1, len(r) // b)
    ms = np.empty(iters)
    for i in range(iters):
        pk = rng.choice(st, n, replace=True)
        ms[i] = np.concatenate([r[p:p + b] for p in pk]).mean()
    ms.sort()
    return float(r.mean()), float(ms[int(.975 * iters)] - ms[int(.025 * iters)]) / 3.92


def main():
    cov = coverage()
    _pw, days, keep, start = choose_panel(cov)
    df = load(keep, start)
    nk = df["sym"].nunique()
    print()
    print("  panel: %d bars, %d coins, %d hourly timestamps"
          % (len(df), nk, df["t"].nunique()))
    for L in LB:
        df["bak%d" % L] = df.groupby("sym")["c"].pct_change(L) * 100
    for H in HZ:
        df["fwd%d" % H] = (df.groupby("sym")["c"].shift(-H) / df["c"] - 1) * 100

    print()
    print("POWER FIRST -- MDE per horizon against the 42-coin panel")
    mdes = {}
    for H in HZ:
        m, se = ci(paired(df, nk, "bak24", "fwd%d" % H), H)
        mde = 2.8 * se * 100
        mdes[H] = mde
        gain = (MDE_42[H] / mde) if mde == mde and mde > 0 else float("nan")
        print("  fwd%-5dh   42-coin %7.2f bps   this panel %7.2f bps   %s"
              % (H, MDE_42[H], mde,
                 "%.2fx better" % gain if gain == gain and gain > 1 else
                 ("%.2fx WORSE" % (1 / gain) if gain == gain else "")))

    print()
    print("THE CROSSOVER GRID -- 36 cells, Bonferroni |z| > %.2f, values in bps" % ZBAR)
    print("  negative = REVERSAL   positive = MOMENTUM")
    print()
    print("  %-7s" % "look" + "".join("%12s" % ("fwd%dh" % H) for H in HZ))
    res, sig = {}, []
    for L in LB:
        cells = []
        for H in HZ:
            m, se = ci(paired(df, nk, "bak%d" % L, "fwd%d" % H), H)
            z = m / se if se and se == se and se > 0 else float("nan")
            star = "*" if abs(z) > ZBAR else ("+" if abs(z) > 1.96 else " ")
            cells.append("%+9.1f%s" % (m * 100, star))
            res["bak%dh|fwd%dh" % (L, H)] = {
                "bps": round(m * 100, 2), "z": None if z != z else round(z, 2),
                "mde_bps": round(2.8 * se * 100, 1) if se == se else None}
            if abs(z) > ZBAR:
                sig.append(("bak%dh|fwd%dh" % (L, H), m * 100, z))
        print("  %-7s" % ("%dh" % L) + "".join("%12s" % c for c in cells))

    json.dump({"window_days": days, "coins": sorted(keep), "n_coins": nk,
               "bonferroni_z": ZBAR, "mde_bps": {str(k): round(v, 2) for k, v in mdes.items()},
               "results": res}, open("crossover_wide169.json", "w"), indent=1)
    print()
    print("CLEARS BONFERRONI: %s"
          % (", ".join("%s %+.0fbps z%+.1f" % s
                       for s in sorted(sig, key=lambda x: -abs(x[2]))) or "none"))
    print()
    mid = res.get("bak24h|fwd24h", {})
    print("THE BAND THAT MATTERS (24h lookback -> 24h horizon, where the live bot sits):")
    print("  %s bps, z %s, MDE %s bps" % (mid.get("bps"), mid.get("z"), mid.get("mde_bps")))
    if mid.get("z") is not None and abs(mid["z"]) <= ZBAR:
        print("  Still inside the detection floor. The effect is not resolved, and saying")
        print("  otherwise would be reading a number smaller than the instrument.")


if __name__ == "__main__":
    main()
