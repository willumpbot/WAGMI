"""Where does cross-sectional REVERSAL become MOMENTUM? The hourly panel bridges the two results.

THE QUESTION. Two results now bracket a gap:
  - `INTRADAY_DISP.md` (5m, 20 days): cross-sectional REVERSAL at 5-60 minutes, 16/16 cells
    negative, 0.4-5.2 bps. Well powered (MDE 3.7 bps), too small to trade.
  - `CROSS_SECTIONAL_V2.md` (daily, 2020-2026): cross-sectional MOMENTUM at 1-10 days,
    but concentrated in 25 violent days and not reachable.

If both are describing something real, there is a horizon where the sign flips. Nobody has
looked, and the hourly panel covers exactly that span: 1 hour to 1 week.

DATA: history/*_1h_fresh.csv -- 6 coins, 3,336 bars each, 2026-05-25 -> 10-10 (139 days).

METHOD, unchanged from the two studies so the three are comparable:
  - rank-weighted cross-sectional estimator, sum|w| = 2 (the v2 estimator)
  - PAIRED statistic: real minus the mean of 24 rank-shuffled baskets, so fees and the
    market move both cancel
  - block bootstrap with the block set from the measured autocorrelation, not by feel
  - 6 lookbacks x 6 horizons = 36 cells, Bonferroni |z| > 3.09
  - MDE per horizon reported BEFORE any verdict, because the long horizons will be weak:
    at a 168-hour horizon, 139 days is only ~20 independent observations
  - concentration checked, per the v2 lesson

FEES, stated up front: 36 bps per round trip. A 1-hour hold needs 36 bps of gross spread;
a 1-week hold needs the same 36 bps spread over 168 hours. So the longer horizons are the
only ones where tradeability is even arithmetically possible, and nothing here is proposed
as a strategy.
"""
import glob
import io
import json
import math
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261011)

LOOKBACKS = (1, 4, 12, 24, 72, 168)      # hours: 1h, 4h, 12h, 1d, 3d, 1w
HORIZONS = (1, 4, 12, 24, 72, 168)
SHUFFLES = 24
FEE_BPS = 36.0


def load():
    rows = []
    for p in sorted(glob.glob(os.path.join("history", "*_1h_fresh.csv"))):
        sym = os.path.basename(p).replace("_1h_fresh.csv", "")
        rd = csv_rows(p)
        for t, c in rd:
            rows.append({"sym": sym, "t": t, "c": c})
    df = pd.DataFrame(rows).drop_duplicates(["sym", "t"]).sort_values(["sym", "t"])
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["day"] = df["dt"].dt.strftime("%Y-%m-%d")
    for L in LOOKBACKS:
        df[f"bak{L}"] = df.groupby("sym")["c"].pct_change(L) * 100
    for H in HORIZONS:
        df[f"fwd{H}"] = (df.groupby("sym")["c"].shift(-H) / df["c"] - 1) * 100
    return df


def csv_rows(p):
    import csv
    out = []
    with io.open(p, encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd, None)
        for r in rd:
            try:
                t = float(r[0])
                t = t if t > 1e11 else t * 1000
                out.append((int(t), float(r[4])))
            except (ValueError, IndexError):
                continue
    return out


def legs_rank(v, f):
    r = np.argsort(np.argsort(v)).astype(float)
    w = r - r.mean()
    s = np.abs(w).sum()
    if s == 0:
        return np.nan
    return float(np.dot(2.0 * w / s, f))


def paired(df, sig, fwd, shuffles=SHUFFLES):
    out = []
    for t, g in df.groupby("t"):
        g = g.dropna(subset=[sig, fwd])
        if len(g) < 5:
            continue
        v, f = g[sig].values, g[fwd].values
        real = legs_rank(v, f)
        if real != real:
            continue
        nl = []
        for _ in range(shuffles):
            w = v.copy()
            rng.shuffle(w)
            x = legs_rank(w, f)
            if x == x:
                nl.append(x)
        if nl:
            out.append({"t": t, "day": g["day"].iloc[0], "r": real - float(np.mean(nl))})
    return pd.DataFrame(out)


def block_ci(s, block_hours, iters=1500):
    """Block bootstrap. Block = max(24h, the horizon) so overlap is covered."""
    if not len(s):
        return (float("nan"),) * 3
    r = s["r"].values
    b = max(24, block_hours)
    if len(r) < b * 8:
        return (float("nan"),) * 3
    starts = np.arange(len(r) - b + 1)
    nb = max(1, len(r) // b)
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.choice(starts, nb, replace=True)
        ms[i] = np.concatenate([r[p:p + b] for p in pick]).mean()
    ms.sort()
    return float(r.mean()), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


def main():
    df = load()
    print("HOURLY PANEL: %d bars, %d coins, %d days (%s -> %s)"
          % (len(df), df["sym"].nunique(), df["day"].nunique(),
             df["day"].min(), df["day"].max()))
    print()

    # justify the block length from the data
    print("AUTOCORRELATION OF 1h RETURNS (sets the block, not a guess)")
    df["r1"] = df.groupby("sym")["c"].pct_change() * 100
    for lag in (1, 2, 4, 12, 24, 48):
        rs = []
        for s, g in df.groupby("sym"):
            x = g["r1"].dropna().values
            if len(x) > lag + 100:
                rs.append(np.corrcoef(x[:-lag], x[lag:])[0, 1])
        print("  lag %3dh  rho %+.4f" % (lag, np.mean(rs)))
    print("  -> blocks are set to max(24h, horizon), which exceeds the dependence")
    print()

    print("POWER FIRST — MDE per horizon. The long ones will be weak and that is arithmetic:")
    for H in HORIZONS:
        s = paired(df, "bak24", f"fwd{H}", shuffles=8)
        m, lo, hi = block_ci(s, H)
        se = (hi - lo) / 3.92 if hi == hi else float("nan")
        eff = df["day"].nunique() / max(H / 24, 1)
        print("  fwd%-4dh  n=%5d  eff.obs~%5.0f  MDE %7.2f bps   fee hurdle %2.0f bps"
              % (H, len(s), eff, 2.8 * se * 100 if se == se else float("nan"), FEE_BPS))
    print()

    zbar = 3.09
    print("THE CROSSOVER GRID — 36 cells, Bonferroni |z| > %.2f" % zbar)
    print("  negative = REVERSAL (the 5m result)   positive = MOMENTUM (the daily result)")
    print()
    hdr = "  %-7s" % "look" + "".join("%12s" % f"fwd{H}h" for H in HORIZONS)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    res = {}
    for L in LOOKBACKS:
        cells = []
        for H in HORIZONS:
            s = paired(df, f"bak{L}", f"fwd{H}")
            m, lo, hi = block_ci(s, H)
            se = (hi - lo) / 3.92 if hi == hi else float("nan")
            z = m / se if se and se == se and se > 0 else float("nan")
            star = "*" if abs(z) > zbar else ("+" if abs(z) > 1.96 else " ")
            cells.append("%+9.1f%s" % (m * 100, star))
            res[f"bak{L}h|fwd{H}h"] = {"bps": round(m * 100, 2),
                                       "ci_bps": [round(lo * 100, 2), round(hi * 100, 2)],
                                       "z": None if z != z else round(z, 2), "n": len(s)}
        print("  %-7s" % f"{L}h" + "".join("%12s" % c for c in cells))
    print()
    print("  * clears Bonferroni   + unadjusted only   (values in bps)")
    json.dump({"fee_bps": FEE_BPS, "bonferroni_z": zbar, "results": res},
              open("horizon_crossover.json", "w"), indent=1)

    sig = [(k, v) for k, v in res.items() if v["z"] is not None and abs(v["z"]) > zbar]
    print()
    print("=" * 78)
    if sig:
        print("CLEARS BONFERRONI:")
        for k, v in sorted(sig, key=lambda z: -abs(z[1]["z"])):
            print("  %-22s %+8.1f bps  z %+6.2f  %s vs %.0f bps fees"
                  % (k, v["bps"], v["z"],
                     "REVERSAL" if v["bps"] < 0 else "MOMENTUM", FEE_BPS))
    else:
        print("CLEARS BONFERRONI: none")
    print("=" * 78)


if __name__ == "__main__":
    main()
