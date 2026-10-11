"""Intraday cross-sectional structure on the 5m archive — does the spread open gradually or in a gap?

WHY THIS, NOW. `CROSS_SECTIONAL_V2.md` found that the daily cross-sectional spread is real in the
data but lives on ~25 violent days out of 494, where close-to-close fills are fiction. The question
that leaves is *mechanical*: when the cross-section spreads 60% in a day, does it open gradually
(reachable) or in one jump (not)? Daily bars cannot answer that. 5m bars can.

This is the first use of the 5m archive the server started on 2026-10-09 after I found that
Hyperliquid deletes 5m history after ~17 days.

READ THIS BEFORE THE RESULTS — the economics are settled in advance:
  Fees are 4 x 9 bps = 36 bps per round trip. On a 5-minute hold that is a 36 bps hurdle per 5
  minutes, which no cross-sectional spread on six liquid coins will ever clear. **Nothing here can
  be tradeable, and I am not testing whether it is.** The question is whether intraday structure
  EXISTS, because that is what decides whether v2's daily effect was reachable or an artifact of
  measuring at the close.

DESIGN, fixed before running:
  - signal: trailing return over L bars, ranked across the 6 coins
  - outcome: forward return over H bars
  - estimator: rank-weighted, sum|w|=2 — the v2 estimator, which measured 1.5x more precisely
  - statistic: PAIRED real minus mean of 24 rank-shuffled baskets, so fees and the market move
    both cancel (the v2 fix for v1's fee-drag error)
  - clustering: HOURLY blocks of 12 bars. Justified from the data: 5m return autocorrelation is
    -0.025 at lag 1 and dead by lag 2-3, so 60 minutes is well beyond the dependence. This gives
    456 clusters where calendar days would give only 20.
  - multiplicity: 4 lookbacks x 4 horizons = 16 cells, Bonferroni |z| > 2.88
  - concentration is checked, not assumed. v2's lesson: a result that lives in a few observations
    is a statement about fill assumptions, not about the market.
"""
import glob
import io
import json
import math
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261011)

LOOKBACKS = (1, 3, 6, 12)      # 5, 15, 30, 60 min
HORIZONS = (1, 3, 6, 12)
BLOCK = 12                     # one hour, justified above
FEE_BPS_ROUND_TRIP = 36.0
SHUFFLES = 24


def load():
    rows = []
    for p in sorted(glob.glob(os.path.join("server_exports", "candles_5m", "*.jsonl"))):
        sym = os.path.basename(p).replace(".jsonl", "")
        for l in io.open(p, encoding="utf-8"):
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            rows.append({"sym": sym, "t": int(r["t"]), "c": float(r["c"])})
    df = pd.DataFrame(rows).drop_duplicates(["sym", "t"]).sort_values(["sym", "t"])
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["blk"] = df["dt"].dt.strftime("%Y-%m-%d %H")
    for L in LOOKBACKS:
        df[f"bak{L}"] = df.groupby("sym")["c"].pct_change(L) * 100
    for H in HORIZONS:
        df[f"fwd{H}"] = (df.groupby("sym")["c"].shift(-H) / df["c"] - 1) * 100
    return df


def legs_rank(v, f):
    r = np.argsort(np.argsort(v)).astype(float)
    w = r - r.mean()
    s = np.abs(w).sum()
    if s == 0:
        return np.nan
    return float(np.dot(2.0 * w / s, f))


def paired(df, sig, fwd, shuffles=SHUFFLES):
    """Per timestamp: real rank-weighted spread minus the mean shuffled spread."""
    out = []
    for t, g in df.groupby("t"):
        g = g.dropna(subset=[sig, fwd])
        if len(g) < 5:                      # need most of the 6 coins
            continue
        v = g[sig].values
        f = g[fwd].values
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
            out.append({"t": t, "blk": g["blk"].iloc[0], "r": real - float(np.mean(nl))})
    return pd.DataFrame(out)


def block_ci(s, iters=2000):
    """Block bootstrap on hourly blocks."""
    if not len(s):
        return (float("nan"),) * 3
    blocks = [g["r"].values for _, g in s.groupby("blk") if len(g)]
    if len(blocks) < 30:
        return (float("nan"),) * 3
    n = len(blocks)
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, n, n)
        ms[i] = np.concatenate([blocks[j] for j in pick]).mean()
    ms.sort()
    return float(s["r"].mean()), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


def main():
    df = load()
    print("5m panel: %d bars, %d coins, %d hourly blocks, %s -> %s"
          % (len(df), df["sym"].nunique(), df["blk"].nunique(),
             df["dt"].min().strftime("%m-%d %H:%M"), df["dt"].max().strftime("%m-%d %H:%M")))
    print()
    print("THE FEE HURDLE, stated first so no result here reads as tradeable:")
    for H in HORIZONS:
        print("    %2d-bar hold (%2d min): must clear %.0f bps GROSS just to break even"
              % (H, H * 5, FEE_BPS_ROUND_TRIP))
    print("  No cross-sectional spread on 6 liquid coins clears 36 bps in 5-60 minutes.")
    print("  This measures whether STRUCTURE exists, not whether money can be made.")
    print()

    ncells = len(LOOKBACKS) * len(HORIZONS)
    zbar = 2.88
    print("POWER FIRST (hourly blocks, %d of them)" % df["blk"].nunique())
    s = paired(df, "bak6", "fwd6", shuffles=8)
    m, lo, hi = block_ci(s)
    se = (hi - lo) / 3.92
    print("  reference cell bak6->fwd6: n=%d, se=%.4f%%, 80%%-power MDE=%.4f%% (%.1f bps)"
          % (len(s), se, 2.8 * se, 2.8 * se * 100))
    print("  so the smallest detectable spread is ~%.0f bps -- well under the 36 bps fee hurdle,"
          % (2.8 * se * 100))
    print("  which is exactly why this can detect structure it could never trade.")
    print()

    print("CROSS-SECTIONAL 5m STRUCTURE — all %d cells, Bonferroni |z| > %.2f" % (ncells, zbar))
    print("  positive = the recent WINNER keeps winning (momentum)")
    print("  negative = the recent winner gives it back (reversal)")
    print()
    print("  %-8s %-8s %10s %20s %7s %9s  %s"
          % ("lookback", "horizon", "spread", "CI95", "z", "bps", "verdict"))
    print("  " + "-" * 82)
    res = {}
    for L in LOOKBACKS:
        for H in HORIZONS:
            s = paired(df, f"bak{L}", f"fwd{H}")
            m, lo, hi = block_ci(s)
            se = (hi - lo) / 3.92 if hi == hi else float("nan")
            z = m / se if se and se == se and se > 0 else float("nan")
            v = ("MOMENTUM" if z > zbar else "REVERSAL" if z < -zbar else
                 "weak" if abs(z) > 1.96 else "nothing")
            print("  %-8s %-8s %+9.4f%% [%+8.4f,%+8.4f]%7.2f%+9.1f  %s"
                  % (f"{L*5}min", f"{H*5}min", m, lo, hi, z, m * 100, v))
            res[f"bak{L}|fwd{H}"] = {"spread_pct": round(m, 5),
                                     "ci": [round(lo, 5), round(hi, 5)],
                                     "z": None if z != z else round(z, 2),
                                     "bps": round(m * 100, 2), "n": len(s)}
        print()
    json.dump({"fee_bps_round_trip": FEE_BPS_ROUND_TRIP, "block_bars": BLOCK,
               "bonferroni_z": zbar, "n_cells": ncells, "results": res},
              open("intraday_disp.json", "w"), indent=1)

    # concentration, per the v2 lesson
    print("CONCENTRATION CHECK (the v2 lesson: where does the return live?)")
    for key in ("bak1|fwd1", "bak6|fwd6", "bak12|fwd12"):
        L, H = (int(key.split("|")[0][3:]), int(key.split("|")[1][3:]))
        s = paired(df, f"bak{L}", f"fwd{H}", shuffles=12)
        if not len(s):
            continue
        x = np.sort(s["r"].values)
        tot = x.sum()
        top1 = x[-max(1, len(x) // 100):].sum()
        print("  %-14s top 1%% of bars = %5.0f%% of the total | %.0f%% of bars positive"
              % (key, 100 * top1 / tot if tot else 0, 100 * np.mean(s["r"].values > 0)))
    print()
    cl = [k for k, v in res.items() if v["z"] is not None and abs(v["z"]) > zbar]
    print("=" * 82)
    print("CLEARS BONFERRONI: %s" % (cl or "none"))
    print("=" * 82)


if __name__ == "__main__":
    main()
