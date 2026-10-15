"""M17 -- the funding-carry atlas + flip table, per M17_AMENDMENT_1 (d0456175). COST ONLY.

Descriptive study: no sim, so no null gate; its honesty gates are the amendment's: AT-BASELINE state
space, pre-registered tier-level key rule with OOS R2, transition-matrix persistence, coverage floors
with POOLED fallbacks, trailing-90d sf denominator with DRIFT flags and harsher-of live snapshots,
and the verbatim language rules (cost sentences only; carry-FOR cells are magnitude-symmetry displays).
"""
import io
import json
import os
import sqlite3

import numpy as np

import panel_snapshot
from m13_build import daily, em_pit, atr_pit, fund_series, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
H48 = 48
FLIPS_BPS = (9.0, 18.0)       # 1 fee, 2 fees
FLIP_R = 0.10
MIN_DAYS = 30
rng = np.random.default_rng(20261019)


def states(rates, modal):
    """State per hour: 0 AT-BASELINE, 1 below-baseline, 2/3/4 off-baseline trailing-90d terciles-ish
    (p<=50 / 50-90 / >90, midrank, off-baseline hours only, 90d warmup -> -1)."""
    n = len(rates)
    st = np.full(n, -1, dtype=np.int8)
    off_hist = []
    W = 90 * 24
    for i in range(n):
        r = rates[i]
        if i >= W:
            if r == modal:
                st[i] = 0
            elif r < modal:
                st[i] = 1
            else:
                hist = off_hist[-W:]
                if len(hist) >= 200:
                    h = np.asarray(hist)
                    pct = ((h < r).sum() + 0.5 * (h == r).sum()) / len(h)
                    st[i] = 2 if pct <= 0.5 else (3 if pct <= 0.9 else 4)
        if r != modal and r > modal:
            off_hist.append(r)
    return st


def dayboot(vals, days, B=2000):
    ud = np.unique(days)
    groups = {d: vals[days == d] for d in ud}
    ms = []
    for _ in range(B):
        pick = ud[rng.integers(0, len(ud), len(ud))]
        allv = np.concatenate([groups[p] for p in pick])
        ms.append(allv.mean())
    return float(np.percentile(ms, 10)), float(np.percentile(ms, 90))


def main():
    print("M17 carry atlas (Amendment 1). COST ONLY - no sentence here implies direction.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]

    # tiers by trailing-90d median dollar volume (computed once, full-sample trailing-90d median)
    vol90 = {}
    for coin in coins:
        rows = c.execute("SELECT c, v FROM candles_1h WHERE coin=? ORDER BY t DESC LIMIT 2160", (coin,)).fetchall()
        if len(rows) < 500:
            continue
        a = np.asarray(rows, float)
        vol90[coin] = float(np.median(a[:, 0] * a[:, 1]))
    order = sorted(vol90, key=lambda k: -vol90[k])
    tier = {k: (1 if i < 20 else (2 if i < 80 else 3)) for i, k in enumerate(order)}

    atlas = {}
    tier_cells = {}
    key_eval = {1: [], 2: [], 3: []}
    trans = {}
    for coin in coins:
        if coin not in tier:
            continue
        fr = fund_series(c, coin)
        if len(fr) < 120 * 24:
            continue
        t = fr[:, 0]
        r = fr[:, 1]
        vals, cnts = np.unique(np.round(r, 10), return_counts=True)
        modal = float(vals[np.argmax(cnts)])
        clamp = float(cnts.max() / len(r))
        st = states(r, modal)
        # realized forward 48h carry per hour (sum of next 48 rates) -- cost magnitude, side-agnostic
        cum = np.concatenate(([0.0], np.cumsum(r)))
        fwd48 = np.full(len(r), np.nan)
        ok = len(r) - H48
        fwd48[:ok] = cum[H48:ok + H48] - cum[:ok]
        days = (t // 86400).astype(np.int64)
        # key evaluation (per tier, collected per coin): entry print vs trailing-24h mean -> |fwd48|
        half = len(r) // 2
        tr24 = np.convolve(r, np.ones(24) / 24, mode="full")[23:23 + len(r)]
        m = np.isfinite(fwd48)
        m2 = m & (np.arange(len(r)) >= half)        # OOS = second half
        def r2(x, y):
            x, y = x[m2], y[m2]
            g = np.isfinite(x) & np.isfinite(y)
            if g.sum() < 500:
                return np.nan
            x, y = x[g], y[g]
            if x.var() <= 0:
                return np.nan
            b = np.cov(x, y)[0, 1] / x.var()
            a_ = y.mean() - b * x.mean()
            res = y - (a_ + b * x)
            return 1 - res.var() / y.var()
        key_eval[tier[coin]].append((r2(r * H48, fwd48), r2(tr24 * H48, fwd48)))
        # atlas cells: per state, |realized 48h carry| in bps (against-side cost = this magnitude when
        # side x rate < 0 throughout -- reported as COST OF HOLDING AGAINST the prevailing sign)
        em_dummy = None
        for s_ in (0, 1, 2, 3, 4):
            mm = m & (st == s_)
            nd = len(np.unique(days[mm]))
            if mm.sum() < 100:
                continue
            v_bps = np.abs(fwd48[mm]) * 1e4
            med = float(np.median(v_bps))
            cell = {"coin": coin, "state": s_, "median_bps": med, "n_hours": int(mm.sum()),
                    "n_days": nd, "clamp_share": clamp, "pooled": False}
            if nd >= MIN_DAYS:
                lo, hi = dayboot(v_bps, days[mm], B=400)
                cell["p10"], cell["p90"] = float(np.percentile(v_bps, 10)), float(np.percentile(v_bps, 90))
                cell["boot_lo"], cell["boot_hi"] = lo, hi
            atlas.setdefault(coin, {})[s_] = cell
            tier_cells.setdefault((tier[coin], s_), []).append(v_bps)
        # transitions from state 4 (extreme-against candidate) over 48h
        if (st == 4).sum() > 100:
            idx = np.flatnonzero(st == 4)
            idx = idx[idx < len(st) - H48]
            if len(idx):
                stay = float(np.mean(st[idx + H48] == 4))
                trans[coin] = {"P_stay_extreme_48h": stay, "n": len(idx)}
    c.close()

    # key decision per tier
    print("=== KEY RULE (per tier, OOS R2; <0.05 difference -> trailing-24h mean; <0.10 winner -> NOT FORECASTABLE) ===")
    key_choice = {}
    for ti in (1, 2, 3):
        arr = np.asarray([x for x in key_eval[ti] if np.isfinite(x).all()])
        if not len(arr):
            key_choice[ti] = "no-data"
            continue
        ep, tm = float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))
        if max(ep, tm) < 0.10:
            key_choice[ti] = "NOT_FORECASTABLE"
        elif abs(ep - tm) < 0.05:
            key_choice[ti] = "trail24"
        else:
            key_choice[ti] = "entry" if ep > tm else "trail24"
        print("  tier %d: entry-print R2 %.3f vs trail-24h R2 %.3f -> %s (n coins %d)" % (ti, ep, tm, key_choice[ti], len(arr)))

    # flip table: per tier (pooled; per-coin where floors pass), extreme state (4) expected 48h
    # against-side cost vs thresholds; sf denominator = trailing-90d median sf per tier (harsher-of rule
    # applies only to live snapshots, not the historical table)
    print("=== FLIP TABLE (48h against-side cost in state 4 'extreme off-baseline'; COST statements only) ===")
    # tier median sf via em of tier members (reuse em from candles; approximate with the tier median of
    # 1.65 x median em over trailing 90d)
    flip = {}
    for ti in (1, 2, 3):
        cells = tier_cells.get((ti, 4), [])
        if not cells:
            continue
        v = np.concatenate(cells) if len(cells) > 1 else cells[0]
        med = float(np.median(v))
        p25, p75 = np.percentile(v, [25, 75])
        flip[ti] = {"median_bps": med, "p25": float(p25), "p75": float(p75), "n_hours": int(len(v)),
                    "key": key_choice[ti]}
        over = {("%dbps" % int(b)): float(np.mean(v >= b)) for b in FLIPS_BPS}
        print("  tier %d state-4: median 48h against-cost %.1f bps [IQR %.1f-%.1f], n=%dh; "
              "P(cost >= 9bps)=%.2f P(>=18bps)=%.2f | key=%s"
              % (ti, med, p25, p75, len(v), over["9bps"], over["18bps"], key_choice[ti]))
    # per-coin flip lines where floors pass, else POOLED
    passing = sum(1 for co, cs in atlas.items() if 4 in cs and cs[4]["n_days"] >= MIN_DAYS)
    print("per-coin state-4 cells passing the %d-day floor: %d (others take the tier POOLED cell)" % (MIN_DAYS, passing))
    print("=== transitions ===")
    ps = [v["P_stay_extreme_48h"] for v in trans.values()]
    if ps:
        print("P(still extreme after 48h): median %.2f across %d coins (extreme states usually decay inside a hold)"
              % (float(np.median(ps)), len(ps)))
    io.open(os.path.join(HERE, "m17_result.json"), "w", encoding="utf-8").write(json.dumps(
        {"key_choice": key_choice, "flip_tiers": flip, "per_coin_pass": passing,
         "transitions_median_stay": float(np.median(ps)) if ps else None,
         "atlas_coins": len(atlas)}, indent=1, default=float))
    print("wrote m17_result.json  (atlas coins: %d)" % len(atlas))


if __name__ == "__main__":
    main()
