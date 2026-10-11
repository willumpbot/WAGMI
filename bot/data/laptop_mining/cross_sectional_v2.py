"""Cross-sectional v2 — a better ESTIMATOR on the same data, and no cherry-picking.

WHY. `CROSS_SECTIONAL.md` found nothing, but `NULLS_AUDIT.md` showed its MDE was 90-128%
annualised, so "nothing survived" meant "nothing enormous survived". Two cells were left
economically large and statistically unresolved: 5d `rsi` (+43%/yr) and 5d `stretch` (+32%/yr).

THE TRAP I AM AVOIDING. Those two were the best of 18 cells. Re-testing only them would be
selection on top of selection — the winner's curse with extra steps. **So this tests all 9
signals at 4 horizons (36 cells) with one correction, and reports the whole grid.** If rsi
survives a 36-test bar it means something; if it only survives alone, it does not.

WHAT IS ACTUALLY NEW (pre-specified before running):
  1. RANK-WEIGHTED portfolio instead of long-top-3 / short-bottom-3. The old basket threw
     away the middle 5 of 11 coins. Rank weighting uses every coin every day, which is a
     strictly lower-variance estimator of the same quantity. This is the real power gain.
  2. LONGER HOLDS: 10 and 20 day added. One round trip of fees per position, so a 20-day
     hold pays the same 36 bps as a 5-day one, spread over 4x the horizon.
  3. Both estimators are reported side by side, so the precision gain is visible rather
     than claimed.

WHAT IS NOT NEW, and I checked rather than assumed: the original ALREADY used overlapping
windows (it takes fwd{hz} on every day, not every hz-th day). I had listed that as an
improvement; it was already there.

UNCHANGED from v1 so the comparison is clean: the panel, the 9 signals, the 2025-06-01
train/test split, 4 x 9 bps of fees per round trip, the day-block bootstrap with the block
matched to the horizon, and the shuffled-rank null that keeps basket structure and destroys
the signal.
"""
import json
import math
import os
import time

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261011)

HIST = "history"
CUTOFF = "2025-06-01"
HOLDS = (1, 5, 10, 20)
K = 3                      # only used for the v1-style basket, for comparison
FEE_PCT = 0.09             # per leg per side; a round trip is 4 x this
SIGNALS = ["mom7", "mom30", "rev3", "stretch", "trend", "rsi", "bb", "rangepos", "vol22"]
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "LINK", "ARB", "UNI", "NEAR", "HYPE",
         "SUI", "ENA", "WLD", "ZEC", "PUMP", "VVV"]


def daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df


def build():
    frames = []
    for s in COINS:
        d = daily(s)
        if d is None or len(d) < 150:
            continue
        c, h, l = d["c"], d["h"], d["l"]
        ret = c.pct_change() * 100
        e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
        ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
        hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
        dd = c.diff()
        gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        out = pd.DataFrame({"sym": s, "day": d["day"]})
        out["mom7"] = (c / c.shift(7) - 1) * 100
        out["mom30"] = (c / c.shift(30) - 1) * 100
        out["rev3"] = -(c / c.shift(3) - 1) * 100
        out["stretch"] = (c / e20 - 1) * 100
        out["trend"] = (e20 / e50 - 1) * 100
        out["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        out["bb"] = (c - ma20) / (2 * sd20).replace(0, np.nan)
        out["rangepos"] = (c - lo20) / (hi20 - lo20).replace(0, np.nan)
        out["vol22"] = -ret.rolling(22).std()
        for hz in HOLDS:
            out[f"fwd{hz}"] = (c.shift(-hz) / c - 1) * 100
        frames.append(out.iloc[60:])
    panel = pd.concat(frames, ignore_index=True).dropna(subset=["fwd1"])
    counts = panel.groupby("day")["sym"].count()
    panel = panel[panel["day"].isin(set(counts[counts >= 2 * K + 1].index))]
    panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
    return panel


def legs_topk(v, f):
    """v1 estimator: long the top K, short the bottom K, equal weight."""
    order = np.argsort(v)
    return f[order[-K:]].mean() - f[order[:K]].mean()


def legs_rank(v, f):
    """v2 estimator: rank-weighted, every coin used, normalised to sum|w| = 2
    so it is directly comparable to one long leg plus one short leg."""
    n = len(v)
    r = np.argsort(np.argsort(v)).astype(float)      # 0..n-1
    w = r - r.mean()
    s = np.abs(w).sum()
    if s == 0:
        return np.nan
    w = 2.0 * w / s
    return float(np.dot(w, f))


SHUFFLES = 24


def series(df, sig, hz, estimator, shuffle=False):
    """One net return per day. Overlapping by construction (every day starts a position)."""
    rows = []
    for day, g in df.groupby("day"):
        g = g.dropna(subset=[sig, f"fwd{hz}"])
        if len(g) < 2 * K + 1:
            continue
        v = g[sig].values.copy()
        if shuffle:
            rng.shuffle(v)
        gross = estimator(v, g[f"fwd{hz}"].values)
        if gross == gross:
            rows.append({"day": day, "r": gross - 4 * FEE_PCT})
    return pd.DataFrame(rows)


def paired(df, sig, hz, estimator, shuffles=SHUFFLES):
    """PAIRED statistic: per day, real minus the mean of `shuffles` rank-shuffled baskets.

    v1 found that its 'significantly negative' cells were just the 36 bps round trip
    showing through -- the shuffled null lands at -0.32 to -0.43%/day. Testing the net
    return against ZERO therefore scores the fee drag as signal. The null already carries
    the fees AND the basket structure, so the honest statistic is the difference, paired
    within day so market-wide moves cancel too.
    """
    rows = []
    for day, g in df.groupby("day"):
        g = g.dropna(subset=[sig, f"fwd{hz}"])
        if len(g) < 2 * K + 1:
            continue
        v = g[sig].values
        f = g[f"fwd{hz}"].values
        real = estimator(v, f)
        if real != real:
            continue
        nulls = []
        for _ in range(shuffles):
            w = v.copy()
            rng.shuffle(w)
            x = estimator(w, f)
            if x == x:
                nulls.append(x)
        if not nulls:
            continue
        # fees are identical in both arms, so they cancel in the difference
        rows.append({"day": day, "r": real - float(np.mean(nulls))})
    return pd.DataFrame(rows)


def boot_ci(s, block, iters=2000):
    """Day-block bootstrap, block matched to the horizon."""
    if len(s) < block * 5:
        return float("nan"), float("nan"), float("nan")
    r = s["r"].values
    nb = max(1, len(r) // block)
    starts = np.arange(len(r) - block + 1)
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.choice(starts, nb, replace=True)
        ms[i] = np.concatenate([r[p:p + block] for p in pick]).mean()
    ms.sort()
    return float(r.mean()), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


def main():
    panel = build()
    print(f"panel {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
          f"{panel['day'].nunique()} days, {panel['day'].min()} -> {panel['day'].max()}")
    te = panel[panel["half"] == "test"]
    print(f"test half: {len(te)} coin-days, {te['day'].nunique()} days")
    print()

    # --- POWER FIRST: what can each estimator even see, on the test half? ---
    print("POWER FIRST — MDE on the TEST half, both estimators, before any verdict")
    print(f"  {'horizon':>8}{'v1 topk MDE':>14}{'v2 paired MDE':>16}{'gain':>8}")
    mdes = {}
    for hz in HOLDS:
        s1 = series(te, "mom7", hz, legs_topk)
        s2 = paired(te, "mom7", hz, legs_rank, shuffles=8)
        m1 = 2.8 * s1["r"].std(ddof=1) / math.sqrt(max(len(s1) / hz, 1))
        m2 = 2.8 * s2["r"].std(ddof=1) / math.sqrt(max(len(s2) / hz, 1))
        mdes[hz] = (m1, m2)
        print(f"  {str(hz)+'d':>8}{m1:>13.3f}%{m2:>13.3f}%{m1/m2 if m2 else float('nan'):>7.2f}x")
    print("  (effective n = days/horizon, since overlapping positions are not independent)")
    print()

    nblocks = len(SIGNALS) * len(HOLDS)
    zbar = 3.09   # Bonferroni, 0.05 two-sided over 36 tests
    print(f"THE FULL GRID — all {len(SIGNALS)} signals x {len(HOLDS)} horizons = {nblocks} cells")
    print(f"  Bonferroni bar for {nblocks} tests: |z| > {zbar:.2f}. Unadjusted bar: 1.96.")
    print()
    print(f"  {'signal':<10}{'hz':>4}{'net ret':>10}{'vs null':>10}{'CI95 on diff':>22}"
          f"{'z':>7}{'null':>8}  verdict")
    print("  " + "-" * 92)
    res = {}
    for sig in SIGNALS:
        for hz in HOLDS:
            s2 = series(te, sig, hz, legs_rank)
            m1 = s2["r"].mean() if len(s2) else float("nan")   # net return, fees included
            sp = paired(te, sig, hz, legs_rank)                # real - null, fees cancel
            m2, lo, hi = boot_ci(sp, hz)
            se = (hi - lo) / 3.92 if hi == hi else float("nan")
            z = m2 / se if se and se == se and se > 0 else float("nan")
            nullm = (m1 - m2) if (m1 == m1 and m2 == m2) else float("nan")
            v = ("CLEARS BONFERRONI" if abs(z) > zbar else
                 "unadjusted only" if abs(z) > 1.96 else "no")
            print(f"  {sig:<10}{str(hz)+'d':>4}{m1:>+10.3f}{m2:>+10.3f}"
                  f"  [{lo:>+7.3f},{hi:>+7.3f}]{z:>7.2f}{nullm:>+8.3f}  {v}")
            res[f"{sig}|{hz}d"] = {"v1": round(m1, 4), "v2": round(m2, 4),
                                   "ci": [round(lo, 4), round(hi, 4)],
                                   "z": None if z != z else round(z, 2),
                                   "null": round(nullm, 4), "n_days": len(s2)}
        print()
    json.dump({"estimator": "rank-weighted, sum|w|=2", "holds": list(HOLDS),
               "fee_pct_per_leg_side": FEE_PCT, "cutoff": CUTOFF,
               "bonferroni_z": zbar, "n_tests": nblocks, "mde_test_half": {str(k): v for k, v in mdes.items()},
               "results": res},
              open("cross_sectional_v2.json", "w"), indent=1)
    cl = [k for k, v in res.items() if v["z"] is not None and abs(v["z"]) > zbar]
    un = [k for k, v in res.items() if v["z"] is not None and 1.96 < abs(v["z"]) <= zbar]
    print("=" * 92)
    print(f"CLEARS BONFERRONI ({nblocks} tests): {cl or 'none'}")
    print(f"UNADJUSTED ONLY (expect ~{nblocks*0.05:.1f} by chance): {un or 'none'}")
    print("=" * 92)


if __name__ == "__main__":
    main()
