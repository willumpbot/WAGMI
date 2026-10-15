"""M13 stage 2 -- policy tree + grouped leave-coins-out + day-shift placebo + null gate. EXPLORATORY.

Reads m13_table.npz (stage 1). Design: M13_CONDITIONAL_EXIT_DESIGN.md Amendments 1-2.

Order of operations is the point:
  1. NULL GATE first: the identical pipeline runs on `nullreal` (an independent martingale draw, true
     gain 0 by construction). If the null headline CI excludes 0 or its placebo p < 0.10, the pipeline
     is broken and NOTHING below is read (the run HALTs).
  2. Real run: headline decomposed into (i) best-single-arm-in-fold vs runner_1.00atr and (ii) the
     tree's increment over (i). The conditional-structure claim and the placebo p attach to (ii) ONLY.
  3. Placebo: circular day-shift of the day-level feature tables (common k per rep, 4 <= k <= 208),
     entries/outcomes/controls fixed, FULL pipeline re-run per rep (deciles included), B = 200,
     p = (1 + #{null >= obs}) / (1 + B). The tested statistic uses day-level lookups (k = 0) so
     observed and null share one pipeline; the entry-level-feature gain is reported beside it.
  4. Shipped rules come from the full-sample tree on ENTRY-LEVEL features (what the live planner can
     compute), each annotated with out-of-fold agreement and out-of-fold gain; rules under 80%
     agreement are suppressed. IN-SAMPLE numbers are labelled as such.

R units govern the headline; bps secondary. Two uncertainty treatments: coin bootstrap and
coin x week two-way; act on the wider. UNDERPOWERED rule (pre-stated): CI covers 0 AND the bps
half-width > 9 bps (one fee) -> the verdict is UNDERPOWERED, never "no structure".
"""
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
T = np.load(os.path.join(HERE, "m13_table.npz"), allow_pickle=False)

ARMS = [str(a) for a in T["arms"]]
FEATS = [str(f) for f in T["featnames"]]
BASE = ARMS.index("runner_1.00atr")
NA = len(ARMS)
MIN_LEAF = 500
MIN_COINS = 30
MAX_COIN_SHARE = 0.20
MIN_IMPROVE_BPS = 2.0
COVER_FLOOR = 0.8
DEPTH = 3
NFOLD = 20
B_REAL = 200
B_NULL = 50
MIN_COIN_ENTRIES = 50
rng = np.random.default_rng(20261016)

coins_s = T["coins"]
ucoins, coin_idx = np.unique(coins_s, return_inverse=True)
C = len(ucoins)
daykey = T["daykey"]
side = T["side"]
sf = T["sf"]
week = daykey // 7
N = len(coin_idx)

# drop coins under the entry floor IDENTICALLY everywhere
cnt_by_coin = np.bincount(coin_idx, minlength=C)
keep_coin = cnt_by_coin >= MIN_COIN_ENTRIES
keep = keep_coin[coin_idx]
print("coins %d -> %d after n>=%d floor; entries %d -> %d"
      % (C, keep_coin.sum(), MIN_COIN_ENTRIES, N, keep.sum()))


def sub(a):
    return a[keep]


real = sub(T["real"] - T["ctrl"])
nullr = sub(T["nullreal"] - T["ctrl"])
feats_entry = sub(T["feats"])
coin_idx = sub(coin_idx)
# re-index coins compactly
ucoins = ucoins[keep_coin]
remap = -np.ones(C, dtype=np.int64)
remap[np.flatnonzero(keep_coin)] = np.arange(keep_coin.sum())
coin_idx = remap[coin_idx] if coin_idx.max() < len(remap) else coin_idx
coin_idx = coin_idx.astype(np.int64)
C = len(ucoins)
daykey, side, sf, week = sub(daykey), sub(side), sub(sf), sub(week)
N = len(coin_idx)
sf_col = sf[:, None]

ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
orig_mask_coin = np.asarray([c in ORIG17 for c in ucoins])

# ---- day-level tables for the placebo lookups ----
fd = T["fday"]                       # (M, 12) DAYF columns
fd_coin = T["fday_coin"]
fd_daykey = T["fday_daykey"]
DAYF = [str(x) for x in T["dayf"]]
hour_b = feats_entry[:, FEATS.index("hour_b")]
day_tab, day_keys = {}, {}
for ci, cname in enumerate(ucoins):
    m = fd_coin == cname
    order = np.argsort(fd_daykey[m])
    day_tab[ci] = fd[m][order]
    day_keys[ci] = fd_daykey[m][order]


def lookup_feats(k):
    """Entry features from the day tables shifted by k days (circular within each coin's list)."""
    X = np.full((N, len(FEATS)), np.nan)
    iL = {f: DAYF.index(f) for f in ("atr_em", "atr_pct", "stop_atr", "trend_raw", "room_long",
                                     "room_short", "fund_pctl", "fund_rate", "btc_beta", "btc_r2",
                                     "ret7_raw", "oi_chg")}
    for ci in range(C):
        m = coin_idx == ci
        dk = day_keys[ci]
        if not len(dk):
            continue
        pos = np.searchsorted(dk, daykey[m])
        pos = np.clip(pos, 0, len(dk) - 1)
        pos = (pos + k) % len(dk)
        F = day_tab[ci][pos]
        s = side[m]
        X[m, 0] = F[:, iL["atr_em"]]
        X[m, 1] = F[:, iL["atr_pct"]]
        X[m, 2] = F[:, iL["stop_atr"]]
        X[m, 3] = F[:, iL["trend_raw"]] * s
        X[m, 4] = np.where(s > 0, F[:, iL["room_long"]], F[:, iL["room_short"]])
        X[m, 5] = F[:, iL["fund_pctl"]]
        X[m, 6] = F[:, iL["fund_rate"]] * s
        X[m, 7] = F[:, iL["btc_beta"]]
        X[m, 8] = F[:, iL["btc_r2"]]
        X[m, 9] = hour_b[m]
        X[m, 10] = F[:, iL["ret7_raw"]] * s
        X[m, 11] = F[:, iL["oi_chg"]]
    return X


# ---- binned policy tree ----
def fit_tree(X, Yb, train_mask):
    """Greedy depth<=DEPTH policy tree on bps outcomes Yb (N,NA), equal-coin-weighted.
    Returns nested dict nodes. Split candidates at training-fold feature deciles."""
    edges = {}
    for f in range(X.shape[1]):
        v = X[train_mask, f]
        v = v[np.isfinite(v)]
        if len(v) < 100:
            edges[f] = None
            continue
        e = np.unique(np.percentile(v, np.arange(10, 100, 10)))
        edges[f] = e if len(e) else None

    def leaf_value(idx):
        """(best arm, equal-coin-weighted mean bps) on train entries idx."""
        ci = coin_idx[idx]
        cc = np.bincount(ci, minlength=C)
        cs = np.stack([np.bincount(ci, weights=Yb[idx, a], minlength=C) for a in range(NA)], axis=1)
        has = cc > 0
        pm = cs[has] / cc[has, None]
        mu = pm.mean(axis=0)
        a = int(np.argmax(mu))
        return a, float(mu[a]), has.sum()

    def build(idx, depth):
        a0, v0, _ = leaf_value(idx)
        node = {"arm": a0, "n": int(len(idx)), "value_bps": v0}
        if depth >= DEPTH or len(idx) < 2 * MIN_LEAF:
            return node
        best = None
        ci = coin_idx[idx]
        for f in range(X.shape[1]):
            e = edges[f]
            if e is None:
                continue
            x = X[idx, f]
            fin = np.isfinite(x)
            if fin.mean() < COVER_FLOOR:
                continue
            bins = np.searchsorted(e, x[fin])          # 0..len(e)
            nb = len(e) + 1
            flat = bins * C + ci[fin]
            cc = np.bincount(flat, minlength=nb * C).reshape(nb, C).astype(float)
            cs = np.stack([np.bincount(flat, weights=Yb[idx[fin], a], minlength=nb * C)
                           .reshape(nb, C) for a in range(NA)], axis=2)
            cumS = np.cumsum(cs, axis=0)
            cumC = np.cumsum(cc, axis=0)
            totS, totC = cumS[-1], cumC[-1]
            for th in range(nb - 1):
                lS, lC = cumS[th], cumC[th]
                rS, rC = totS - lS, totC - lC
                nL, nR = lC.sum(), rC.sum()
                if nL < MIN_LEAF or nR < MIN_LEAF:
                    continue
                hL, hR = lC > 0, rC > 0
                if hL.sum() < MIN_COINS or hR.sum() < MIN_COINS:
                    continue
                if lC.max() > MAX_COIN_SHARE * nL or rC.max() > MAX_COIN_SHARE * nR:
                    continue
                pmL = lS[hL] / lC[hL, None]
                pmR = rS[hR] / rC[hR, None]
                aL = int(np.argmax(pmL.mean(axis=0)))
                aR = int(np.argmax(pmR.mean(axis=0)))
                # node policy value under this split, equal-coin-weighted over node coins
                has = totC > 0
                picked = (lS[:, aL] + rS[:, aR])
                v = float((picked[has] / totC[has]).mean())
                if best is None or v > best[0]:
                    best = (v, f, float(e[th]), aL, aR)
        if best is None or best[0] - v0 < MIN_IMPROVE_BPS:
            return node
        _, f, thr, aL, aR = best
        x = X[idx, f]
        fin = np.isfinite(x)
        left = fin & (x <= thr)
        right = fin & (x > thr)
        nan = ~fin
        maj_left = left.sum() >= right.sum()
        if nan.any():
            (left if maj_left else right)[:] = (left if maj_left else right) | nan
        node.update({"feat": f, "thr": thr, "nan_left": bool(maj_left),
                     "L": build(idx[left], depth + 1), "R": build(idx[right], depth + 1)})
        return node

    return build(np.flatnonzero(train_mask), 0)


def predict(node, X, idx):
    out = np.empty(len(idx), dtype=np.int64)

    def walk(nd, ii):
        if "feat" not in nd:
            out[np.searchsorted(idx, ii)] = nd["arm"]
            return
        x = X[ii, nd["feat"]]
        fin = np.isfinite(x)
        left = fin & (x <= nd["thr"])
        nan = ~fin
        if nd["nan_left"]:
            left = left | nan
        walk(nd["L"], ii[left])
        walk(nd["R"], ii[~left])

    walk(node, idx)
    return out


FOLD = coin_idx % NFOLD                   # deterministic coin->fold (coins sorted by name upstream)


def run_pipeline(X, Y):
    """Grouped 20-fold leave-coins-out. Y: (N,NA) net fractions (control-subtracted).
    Returns per-coin arrays: gain1_r, inc_r (tree increment), gain_r, same in bps, chosen frac."""
    Yb = Y * 1e4
    Yr = Y / sf_col
    g1r = np.full(C, np.nan)
    gtr = np.full(C, np.nan)
    g1b = np.full(C, np.nan)
    gtb = np.full(C, np.nan)
    dev = np.full(C, np.nan)
    fold_tree = {}
    for fo in range(NFOLD):
        te = FOLD == fo
        tr = ~te
        tree = fit_tree(X, Yb, tr)
        fold_tree[fo] = tree
        # best single arm on training, equal-coin-weighted
        ci = coin_idx[tr]
        cc = np.bincount(ci, minlength=C).astype(float)
        cs = np.stack([np.bincount(ci, weights=Yb[tr, a], minlength=C) for a in range(NA)], axis=1)
        has = cc > 0
        arm1 = int(np.argmax((cs[has] / cc[has, None]).mean(axis=0)))
        idx = np.flatnonzero(te)
        ch = predict(tree, X, idx)
        for c in np.unique(coin_idx[idx]):
            m = idx[coin_idx[idx] == c]
            chm = ch[np.isin(idx, m)]
            g1r[c] = Yr[m, arm1].mean() - Yr[m, BASE].mean()
            g1b[c] = Yb[m, arm1].mean() - Yb[m, BASE].mean()
            gtr[c] = Yr[m, chm].mean() - Yr[m, BASE].mean()
            gtb[c] = Yb[m, chm].mean() - Yb[m, BASE].mean()
            dev[c] = float((chm != BASE).mean())
    return {"g1r": g1r, "g1b": g1b, "gtr": gtr, "gtb": gtb, "dev": dev, "fold_tree": fold_tree}


def coin_ci(vals, nboot=4000):
    v = vals[np.isfinite(vals)]
    idx = rng.integers(0, len(v), size=(nboot, len(v)))
    ms = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))


def twoway_ci(per_entry_gain, nboot=2000):
    """coin x week two-way bootstrap on per-(coin,week) cell means."""
    cw = coin_idx * 100000 + week
    ucw, inv = np.unique(cw, return_inverse=True)
    cell_sum = np.bincount(inv, weights=per_entry_gain)
    cell_n = np.bincount(inv)
    cell_mu = cell_sum / cell_n
    cell_coin = ucw // 100000
    cell_week = ucw % 100000
    uw = np.unique(cell_week)
    ms = []
    for _ in range(nboot):
        cs = rng.integers(0, C, C)
        ws = uw[rng.integers(0, len(uw), len(uw))]
        cmask = np.isin(cell_coin, cs)
        wmask = np.isin(cell_week, ws)
        sel = cell_mu[cmask & wmask]
        if len(sel):
            ms.append(sel.mean())
    return float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))


def headline(X, Y, label):
    r = run_pipeline(X, Y)
    inc_r = r["gtr"] - r["g1r"]
    inc_b = r["gtb"] - r["g1b"]
    m1, lo1, hi1 = coin_ci(r["g1r"])
    mi, loi, hii = coin_ci(inc_r)
    mib, loib, hiib = coin_ci(inc_b)
    mt, lot, hit = coin_ci(r["gtr"])
    print("[%s] (i) best-single-arm vs runner_1.00atr: %+.4f R [%+.4f,%+.4f]" % (label, m1, lo1, hi1))
    print("[%s] (ii) TREE INCREMENT over (i):          %+.4f R [%+.4f,%+.4f]  (bps %+0.2f [%+0.2f,%+0.2f])"
          % (label, mi, loi, hii, mib, loib, hiib))
    print("[%s] total policy vs baseline:             %+.4f R [%+.4f,%+.4f]; deviation frac %.2f"
          % (label, mt, lot, hit, float(np.nanmean(r["dev"]))))
    return r, {"g1_r": [m1, lo1, hi1], "inc_r": [mi, loi, hii], "inc_bps": [mib, loib, hiib],
               "total_r": [mt, lot, hit], "dev_frac": float(np.nanmean(r["dev"]))}


def placebo(Y, obs_inc_b, B):
    nulls = []
    ks = rng.choice(np.arange(4, 209), size=B, replace=False) if B <= 200 else rng.integers(4, 209, B)
    for i, k in enumerate(ks):
        Xk = lookup_feats(int(k))
        r = run_pipeline(Xk, Y)
        nulls.append(float(np.nanmean(r["gtb"] - r["g1b"])))
        if (i + 1) % 25 == 0:
            print("  placebo %d/%d  null inc mean so far %+0.2f bps" % (i + 1, B, np.mean(nulls)))
    nulls = np.asarray(nulls)
    p = (1 + int((nulls >= obs_inc_b).sum())) / (1 + len(nulls))
    return nulls, p


def main():
    mode_null = "--skip-null" not in sys.argv
    X0 = lookup_feats(0)

    if mode_null:
        print("=== NULL GATE: pipeline on nullreal (true gain 0 by construction) ===")
        rn, hn = headline(X0, nullr, "NULL")
        inc_b_null = hn["inc_bps"][0]
        nulls, p_null = placebo(nullr, inc_b_null, B_NULL)
        print("NULL placebo p = %.3f" % p_null)
        ci = hn["inc_r"]
        if not (ci[1] <= 0.0 <= ci[2]) or p_null < 0.10:
            raise SystemExit("HALT: NULL GATE FAILED (inc CI [%+.4f,%+.4f] R, p=%.3f) -- "
                             "pipeline is broken; the real table must not be read." % (ci[1], ci[2], p_null))
        print("NULL GATE PASSED.\n")

    print("=== REAL RUN (day-level k=0 lookups; the placebo-comparable statistic) ===")
    r0, h0 = headline(X0, real, "REAL/day-lookup")
    print("\n=== REAL RUN (entry-level features; reported beside, same pipeline) ===")
    re_, he = headline(feats_entry, real, "REAL/entry-level")

    # two-way (coin x week) CI on the TOTAL policy gain per entry (chosen vs baseline, R units),
    # from each entry's own fold tree -- act on the wider of this and the coin-only CI above
    Yb = real * 1e4
    Yr = real / sf_col
    chosen = np.empty(N, dtype=np.int64)
    for fo in range(NFOLD):
        idx = np.flatnonzero(FOLD == fo)
        chosen[idx] = predict(r0["fold_tree"][fo], X0, idx)
    pe_gain = Yr[np.arange(N), chosen] - Yr[:, BASE]
    lo2, hi2 = twoway_ci(pe_gain)
    print("two-way (coin x week) CI, total policy gain: [%+.4f, %+.4f] R  (coin-only above; act on wider)"
          % (lo2, hi2))
    dmask = chosen != BASE
    if dmask.any():
        dv = pe_gain[dmask]
        dci = coin_idx[dmask]
        cc = np.bincount(dci, minlength=C).astype(float)
        cs = np.bincount(dci, weights=dv, minlength=C)
        has = cc > 0
        per_coin_dev = cs[has] / cc[has]
        print("per-DEVIATED-entry gain: %+.4f R equal-coin (n=%d entries, %d coins, f=%.2f)"
              % (per_coin_dev.mean(), int(dmask.sum()), int(has.sum()), float(dmask.mean())))

    print("\n=== placebo (B=%d) on the day-lookup increment ===" % B_REAL)
    nulls, p = placebo(real, h0["inc_bps"][0], B_REAL)
    se = float(nulls.std(ddof=1))
    print("PLACEBO p = %.4f   null mean %+0.2f bps  sd %.2f  -> MDE(2.8*SE) %.1f bps"
          % (p, float(nulls.mean()), se, 2.8 * se))

    # time-split robustness
    med = np.median(daykey)
    for nm, trm in (("early->late", daykey <= med), ("late->early", daykey > med)):
        tree = fit_tree(feats_entry, Yb, trm)
        idx = np.flatnonzero(~trm)
        ch = predict(tree, feats_entry, idx)
        g = np.full(C, np.nan)
        for c in np.unique(coin_idx[idx]):
            m = idx[coin_idx[idx] == c]
            g[c] = (real[m, ch[np.isin(idx, m)]] / sf[m]).mean() - (real[m, BASE] / sf[m]).mean()
        mm, lo, hi = coin_ci(g)
        print("time-split %s: policy vs base %+.4f R [%+.4f,%+.4f]" % (nm, mm, lo, hi))

    # ORIG17 split (descriptive)
    r = re_
    for nm, msk in (("ORIG17", orig_mask_coin), ("non-ORIG17", ~orig_mask_coin)):
        v = (r["gtr"] - r["g1r"])[msk]
        v = v[np.isfinite(v)]
        if len(v) >= 5:
            print("%s increment (descriptive): %+.4f R (n=%d coins)" % (nm, v.mean(), len(v)))

    # ---- shipped rules: full-sample tree on entry-level features, out-of-fold annotation ----
    full_tree = fit_tree(feats_entry, Yb, np.ones(N, bool))

    def paths(nd, cond):
        if "feat" not in nd:
            return [(cond, nd)]
        f, t = FEATS[nd["feat"]], nd["thr"]
        return (paths(nd["L"], cond + [(f, "<=", t)]) + paths(nd["R"], cond + [(f, ">", t)]))

    rules = []
    fold_tr = r0["fold_tree"]
    for cond, leaf in paths(full_tree, []):
        # entries in this leaf
        m = np.ones(N, bool)
        for f, op, t in cond:
            x = feats_entry[:, FEATS.index(f)]
            ok = np.isfinite(x)
            m &= np.where(ok, (x <= t) if op == "<=" else (x > t), False)
        idx = np.flatnonzero(m)
        if not len(idx):
            continue
        # out-of-fold: each entry's own fold tree choice
        agree = np.zeros(len(idx), bool)
        for fo in range(NFOLD):
            fm = FOLD[idx] == fo
            if fm.any():
                ch = predict(fold_tr[fo], feats_entry, idx[fm])
                agree[fm] = ch == leaf["arm"]
        oof_gain = None
        if agree.any():
            mm = idx[agree]
            per_coin = {}
            for c in np.unique(coin_idx[mm]):
                e = mm[coin_idx[mm] == c]
                per_coin[c] = float((real[e, leaf["arm"]] / sf[e]).mean() - (real[e, BASE] / sf[e]).mean())
            vals = np.asarray(list(per_coin.values()))
            oof_gain = [float(vals.mean()), int(len(vals))]
        rules.append({
            "if": [{"feat": f, "op": op, "thr": round(t, 6)} for f, op, t in cond],
            "arm": ARMS[leaf["arm"]], "n": int(len(idx)),
            "in_sample_value_bps_LABELLED_IN_SAMPLE": round(leaf["value_bps"], 2),
            "oof_agreement": round(float(agree.mean()), 3),
            "oof_gain_r_equal_coin": oof_gain,
            "ships": bool(agree.mean() >= 0.8)})
    out = {"default": ARMS[BASE], "rules": rules,
           "headline": {"day_lookup": h0, "entry_level": he},
           "placebo": {"p": p, "B": B_REAL, "null_mean_bps": float(nulls.mean()),
                       "null_sd_bps": se, "mde_bps": 2.8 * se},
           "underpowered_rule": "CI covers 0 AND bps half-width > 9 -> UNDERPOWERED",
           "coins": int(C), "entries": int(N)}
    io.open(os.path.join(HERE, "m13_style_hint.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m13_style_hint.json  (%d leaf rules, %d ship at >=80%% agreement)"
          % (len(rules), sum(1 for r_ in rules if r_["ships"])))


if __name__ == "__main__":
    main()
