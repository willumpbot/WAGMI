"""
Frontier-2 hypothesis tests, leak tests, and Tier-B model.
READ-ONLY research. Reads tools/research/intertwine/feature_store*.csv only.
"""
import os
import json
import numpy as np
import pandas as pd
from scipy import stats as sstats

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FS_PATH = os.path.join(OUT_DIR, "feature_store.csv")
FS_SHIFT_PATH = os.path.join(OUT_DIR, "feature_store_futureshift.csv")

RNG = np.random.default_rng(12345)
BLOCK_SECONDS = 24 * 3600


def trailing_pctile_per_symbol(df, col, min_hist=10):
    """Prior-only trailing percentile of col, per symbol, in record_ts order."""
    out = pd.Series(index=df.index, dtype=float)
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("record_ts")
        vals = grp[col].to_numpy()
        pcts = np.full(len(vals), np.nan)
        for i in range(len(vals)):
            hist = vals[:i]
            hist = hist[~np.isnan(hist)]
            if len(hist) < min_hist or np.isnan(vals[i]):
                continue
            pcts[i] = (hist < vals[i]).mean() * 100
        out.loc[grp.index] = pcts
    return out


def compute_btc_shock_flags(events, label_col_ts="record_ts"):
    """H8: for each event, was there a BTC imbalance_0_1pct |z|>2 shock (trailing,
    prior-only z-score of the 1-step change) within the preceding 30 minutes?
    Returns (fired_bool, shock_sign)."""
    import feature_store as fsmod
    depth = fsmod.load_depth()
    btc = depth[depth["symbol"] == "BTC"].sort_values("ts").reset_index(drop=True)
    chg = btc["imbalance_0_1pct"].diff()
    # trailing (prior-only) rolling std of the change, min_periods for stability
    trail_std = chg.expanding(min_periods=30).std().shift(1)
    z = chg / trail_std
    btc = btc.assign(z=z)
    shock_mask = btc["z"].abs() > 2
    shock_ts = btc.loc[shock_mask, "ts"].to_numpy()
    shock_sign = np.sign(btc.loc[shock_mask, "z"].to_numpy())

    fired = np.zeros(len(events), dtype=bool)
    sign_out = np.full(len(events), np.nan)
    ev_ts = events[label_col_ts].to_numpy()
    ev_sym = events["symbol"].to_numpy()
    for i in range(len(events)):
        if ev_sym[i] == "BTC":
            continue  # hypothesis is about ALT following BTC
        lo = ev_ts[i] - 1800
        hi = ev_ts[i]
        mask = (shock_ts >= lo) & (shock_ts <= hi)
        if mask.any():
            # most recent shock in window
            idxs = np.where(mask)[0]
            last = idxs[np.argmax(shock_ts[idxs])]
            fired[i] = True
            sign_out[i] = shock_sign[last]
    return fired, sign_out


def add_hypothesis_columns(events):
    ev = events.copy()

    # trailing pctile of vr (per symbol) for H2 "high vol"
    ev["vr_pctile"] = trailing_pctile_per_symbol(ev, "vr")

    # H1: crowded-side squeeze
    crowd_long = ev["funding_pctile"] > 90
    crowd_short = ev["funding_pctile"] < 10
    against_sign = np.where(crowd_long, -1, np.where(crowd_short, 1, np.nan))
    ev["h1_fire"] = (
        (crowd_long | crowd_short)
        & (ev["oi_delta_24h"] > 0)
        & (ev["side_sign"] == against_sign)
    )
    ev["h1_eligible"] = ev["funding_pctile"].notna() & ev["oi_delta_24h"].notna()

    # H2: liquidation-cascade continuation
    ev["h2_fire"] = (
        (ev["oi_delta_1h"] < -0.02)
        & (np.sign(ev["depth_imbalance_0_5pct"]) == ev["side_sign"])
        & (ev["vr_pctile"] > 75)
    )
    ev["h2_eligible"] = ev["oi_delta_1h"].notna() & ev["depth_imbalance_0_5pct"].notna() & ev["vr_pctile"].notna()

    # H3: absorption fade
    taker_sign = np.sign(ev["depth_buy_ratio"] - 0.5)
    book_sign = np.sign(ev["depth_imbalance_0_5pct"])
    ev["h3_fire"] = (book_sign != taker_sign) & (book_sign != 0) & (taker_sign != 0) & (ev["side_sign"] == -taker_sign)
    ev["h3_eligible"] = ev["depth_buy_ratio"].notna() & ev["depth_imbalance_0_5pct"].notna()

    # H4: consensus x regime
    regime_bias_sign = np.sign(ev["regime_drive_d1h"])
    ev["h4_fire"] = (ev["agree"] >= 2) & (ev["regime"] == "trend") & (ev["side_sign"] == regime_bias_sign)
    ev["h4_eligible"] = ev["regime_drive_d1h"].notna() & ev["regime"].notna()

    # H5: crowd-vs-book contrarian
    ev["h5_fire"] = (
        ((ev["ls_ratio_pctile"] > 85) & (ev["depth_imbalance_0_5pct"] < 0) & (ev["side_sign"] == -1))
        | ((ev["ls_ratio_pctile"] < 15) & (ev["depth_imbalance_0_5pct"] > 0) & (ev["side_sign"] == 1))
    )
    ev["h5_eligible"] = ev["ls_ratio_pctile"].notna() & ev["depth_imbalance_0_5pct"].notna()

    # H6: funding-premium divergence
    fund_sign = np.sign(ev["fo_funding_rate"])
    basis_sign = np.sign(ev["depth_basis_bps"])
    tight = ev["depth_spread_bps"] < ev["spread_bps_median_trail"]
    ev["h6_fire"] = (fund_sign != basis_sign) & (fund_sign != 0) & (basis_sign != 0) & tight & (ev["side_sign"] == basis_sign)
    ev["h6_eligible"] = ev["fo_funding_rate"].notna() & ev["depth_basis_bps"].notna() & ev["spread_bps_median_trail"].notna()

    # H7: stale-positioning chop veto (no side condition; negative hypothesis)
    ev["h7_fire"] = (ev["oi_vol_ratio_pctile"] > 75) & (ev["regime"] == "range")
    ev["h7_eligible"] = ev["oi_vol_ratio_pctile"].notna() & ev["regime"].notna()

    # H8: depth-shock lead-lag
    fired8, sign8 = compute_btc_shock_flags(ev)
    ev["h8_fire"] = fired8 & (ev["side_sign"] == sign8)
    ev["h8_eligible"] = ev["symbol"] != "BTC"  # any alt event is eligible for the test

    return ev


HYPOTHESES = {
    "H1_crowded_squeeze": ("h1_fire", "h1_eligible", "greater"),
    "H2_liq_cascade_cont": ("h2_fire", "h2_eligible", "greater"),
    "H3_absorption_fade": ("h3_fire", "h3_eligible", "greater"),
    "H4_consensus_regime": ("h4_fire", "h4_eligible", "greater"),
    "H5_crowd_book_contrarian": ("h5_fire", "h5_eligible", "greater"),
    "H6_funding_premium_div": ("h6_fire", "h6_eligible", "greater"),
    "H7_stale_pos_chop_veto": ("h7_fire", "h7_eligible", "less"),
    "H8_depth_shock_leadlag": ("h8_fire", "h8_eligible", "greater"),
}


def block_bootstrap_diff(fired_df, base_df, label_col, n_boot=10000):
    """Day-block bootstrap of mean(fired) - mean(base). Returns (lo90, hi90)."""
    if len(fired_df) == 0 or len(base_df) == 0:
        return (np.nan, np.nan)
    f_blocks = (fired_df["record_ts"] // BLOCK_SECONDS).astype(int).to_numpy()
    b_blocks = (base_df["record_ts"] // BLOCK_SECONDS).astype(int).to_numpy()
    f_vals = fired_df[label_col].to_numpy()
    b_vals = base_df[label_col].to_numpy()
    f_unique_blocks = np.unique(f_blocks)
    b_unique_blocks = np.unique(b_blocks)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        fb_sample = RNG.choice(f_unique_blocks, size=len(f_unique_blocks), replace=True)
        bb_sample = RNG.choice(b_unique_blocks, size=len(b_unique_blocks), replace=True)
        fmask = np.isin(f_blocks, fb_sample)
        bmask = np.isin(b_blocks, bb_sample)
        fv = f_vals[fmask] if fmask.any() else f_vals
        bv = b_vals[bmask] if bmask.any() else b_vals
        diffs[i] = np.nanmean(fv) - np.nanmean(bv)
    lo, hi = np.nanpercentile(diffs, [5, 95])
    return (lo, hi)


def run_all_hypotheses(ev, label_col="net_ret_2h", n_boot=10000, verbose=True):
    results = []
    for name, (fire_col, elig_col, alt) in HYPOTHESES.items():
        pool = ev[ev[elig_col]].copy()
        fired = pool[pool[fire_col]]
        base = pool[~pool[fire_col]]
        n_fired = len(fired)
        n_base = len(base)
        if n_fired == 0:
            results.append(dict(hypothesis=name, n_fired=0, n_eligible=len(pool),
                                 wr_fired=np.nan, wr_base=np.nan,
                                 mean_fired=np.nan, mean_base=np.nan,
                                 diff=np.nan, p_value=np.nan, ci90=(np.nan, np.nan),
                                 direction_correct=False, weak_n=True))
            continue
        wr_fired = (fired[label_col] > 0).mean()
        wr_base = (base[label_col] > 0).mean() if n_base else np.nan
        mean_fired = fired[label_col].mean()
        mean_base = base[label_col].mean() if n_base else np.nan

        tstat, p_two = sstats.ttest_ind(fired[label_col], base[label_col], equal_var=False, nan_policy="omit")
        if alt == "greater":
            direction_correct = mean_fired > mean_base
            p_one = p_two / 2 if tstat > 0 else 1 - p_two / 2
        else:
            direction_correct = mean_fired < mean_base
            p_one = p_two / 2 if tstat < 0 else 1 - p_two / 2

        ci = block_bootstrap_diff(fired, base, label_col, n_boot=n_boot)

        results.append(dict(
            hypothesis=name, n_fired=n_fired, n_eligible=len(pool),
            wr_fired=wr_fired, wr_base=wr_base,
            mean_fired=mean_fired, mean_base=mean_base,
            diff=mean_fired - mean_base, p_value=p_one, ci90=ci,
            direction_correct=direction_correct, weak_n=n_fired < 30,
        ))
    return pd.DataFrame(results)


def holm_bonferroni(pvals, alpha=0.10):
    """Return boolean array of which hypotheses survive Holm-Bonferroni at family alpha."""
    m = len(pvals)
    order = np.argsort(pvals)
    survives = np.zeros(m, dtype=bool)
    for rank, idx in enumerate(order):
        p = pvals[idx]
        if np.isnan(p):
            continue
        thresh = alpha / (m - rank)
        if p <= thresh:
            survives[idx] = True
        else:
            break  # Holm stops at first failure
    return survives


def leak_test_shuffle(ev, n_reps=20, label_col="net_ret_2h"):
    """Shuffle labels across events, rerun all 8 tests, count how many still
    'survive' direction+nominal p<0.10 (should be ~ at chance rate, not
    systematically the same hypotheses every time)."""
    survive_counts = {name: 0 for name in HYPOTHESES}
    rng = np.random.default_rng(999)
    for rep in range(n_reps):
        shuffled = ev.copy()
        perm = rng.permutation(len(shuffled))
        shuffled[label_col] = shuffled[label_col].to_numpy()[perm]
        res = run_all_hypotheses(shuffled, label_col=label_col, n_boot=200)
        for _, row in res.iterrows():
            if row["direction_correct"] and not np.isnan(row["p_value"]) and row["p_value"] < 0.10:
                survive_counts[row["hypothesis"]] += 1
    return survive_counts, n_reps


TIER_B_FEATURES = [
    "funding_pctile", "oi_vol_ratio_pctile", "ls_ratio_pctile", "oi_delta_1h", "oi_delta_24h",
    "depth_spread_bps", "depth_imbalance_0_1pct", "depth_imbalance_0_5pct", "depth_imbalance_1pct",
    "depth_buy_ratio", "depth_basis_bps", "depth_long_short_account_ratio", "depth_taker_buy_sell_ratio",
    "fo_funding_rate", "fo_premium", "vr_pctile", "agree", "dissent", "avg_conf",
    "spread_bps_median_trail", "side_sign",
]


def tier_b_model(ev, label_col="net_ret_2h", n_folds=5):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    ev = ev.sort_values("record_ts").reset_index(drop=True)
    y = (ev[label_col] > 0).astype(int).to_numpy()
    X_raw = ev[TIER_B_FEATURES].copy()
    # missing-indicator columns (computed per-row, no leak)
    miss = X_raw.isna().astype(int)
    miss.columns = [c + "_missing" for c in miss.columns]

    n = len(ev)
    fold_bounds = np.linspace(0, n, n_folds + 1).astype(int)
    oos_pred, oos_true = [], []
    fold_aucs = []
    for k in range(1, n_folds):
        train_idx = np.arange(0, fold_bounds[k])
        test_idx = np.arange(fold_bounds[k], fold_bounds[k + 1])
        if len(test_idx) == 0 or len(train_idx) < 30:
            continue
        Xtr_raw = X_raw.iloc[train_idx]
        Xte_raw = X_raw.iloc[test_idx]
        med = Xtr_raw.median()  # train-only imputation stats, no leak
        Xtr = Xtr_raw.fillna(med).fillna(0.0)
        Xte = Xte_raw.fillna(med).fillna(0.0)
        mu, sd = Xtr.mean(), Xtr.std().replace(0, 1).fillna(1.0)
        Xtr = ((Xtr - mu) / sd).fillna(0.0)
        Xte = ((Xte - mu) / sd).fillna(0.0)
        Xtr = pd.concat([Xtr, miss.iloc[train_idx]], axis=1)
        Xte = pd.concat([Xte, miss.iloc[test_idx]], axis=1)
        ytr, yte = y[train_idx], y[test_idx]
        if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
            continue
        clf = LogisticRegression(penalty="l1", solver="liblinear", C=0.5, max_iter=2000)
        clf.fit(Xtr, ytr)
        proba = clf.predict_proba(Xte)[:, 1]
        fold_auc = roc_auc_score(yte, proba)
        fold_aucs.append(fold_auc)
        oos_pred.extend(proba.tolist())
        oos_true.extend(yte.tolist())

    overall_auc = roc_auc_score(oos_true, oos_pred) if len(set(oos_true)) > 1 else float("nan")
    return overall_auc, fold_aucs, len(oos_true)


def main():
    ev = pd.read_csv(FS_PATH)
    ev = add_hypothesis_columns(ev)

    print("=" * 100)
    print("LEAK TEST 1: as-of integrity (already verified in feature_store: max(src_ts - event_ts) < 0)")
    fo_ok = (ev["fo_src_ts"] <= ev["record_ts"]).where(ev["fo_src_ts"].notna(), True).all()
    depth_ok = (ev["depth_src_ts"] <= ev["record_ts"]).where(ev["depth_src_ts"].notna(), True).all()
    print(f"  funding/OI as-of integrity: {'PASS' if fo_ok else 'FAIL'}")
    print(f"  depth as-of integrity:      {'PASS' if depth_ok else 'FAIL'}")

    print("=" * 100)
    print("PRIMARY RESULTS (label = net_ret_2h, 2h horizon)")
    res2h = run_all_hypotheses(ev, label_col="net_ret_2h")
    pvals = res2h["p_value"].to_numpy()
    survives = holm_bonferroni(pvals, alpha=0.10)
    res2h["survives_holm"] = survives
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(res2h.to_string(index=False))
    res2h.to_csv(os.path.join(OUT_DIR, "results_2h.csv"), index=False)

    print("=" * 100)
    print("ROBUSTNESS: 6h horizon")
    res6h = run_all_hypotheses(ev, label_col="net_ret_6h")
    pvals6 = res6h["p_value"].to_numpy()
    res6h["survives_holm"] = holm_bonferroni(pvals6, alpha=0.10)
    print(res6h.to_string(index=False))
    res6h.to_csv(os.path.join(OUT_DIR, "results_6h.csv"), index=False)

    print("=" * 100)
    print("LEAK TEST 2: label shuffle (20 reps) -- survival counts should be near chance, not")
    print("systematically reproducing the same 'significant' hypotheses")
    shuf_counts, n_reps = leak_test_shuffle(ev, n_reps=20)
    for name, cnt in shuf_counts.items():
        print(f"  {name:30s} survived {cnt}/{n_reps} shuffles at nominal p<0.10 (direction-correct)")

    print("=" * 100)
    print("LEAK TEST 3: future-shift canary")
    ev_shift = pd.read_csv(FS_SHIFT_PATH)
    ev_shift = add_hypothesis_columns(ev_shift)
    res_shift = run_all_hypotheses(ev_shift, label_col="net_ret_2h")
    res_shift["survives_holm"] = holm_bonferroni(res_shift["p_value"].to_numpy(), alpha=0.10)
    print(res_shift.to_string(index=False))
    res_shift.to_csv(os.path.join(OUT_DIR, "results_futureshift.csv"), index=False)

    print("=" * 100)
    print("TIER-B: L1-logistic, forward-chaining CV, OOS fee-adjusted AUC (net_ret_2h > 0)")
    overall_auc, fold_aucs, n_oos = tier_b_model(ev, label_col="net_ret_2h")
    print(f"  overall OOS AUC: {overall_auc:.4f} over n_oos={n_oos}, fold AUCs: {[round(a,4) for a in fold_aucs]}")

    print("=" * 100)
    print("Data coverage honesty")
    print(f"  total deduped events: {len(ev)}")
    for name, (fire_col, elig_col, alt) in HYPOTHESES.items():
        n_elig = ev[elig_col].sum()
        print(f"  {name:30s} eligible (non-NaN inputs): {n_elig}/{len(ev)} ({100*n_elig/len(ev):.1f}%)")


if __name__ == "__main__":
    main()
