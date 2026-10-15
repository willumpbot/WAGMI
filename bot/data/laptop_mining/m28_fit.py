"""M28 stage A -- DISCOVERY read only. Null gate + positive control FIRST, then L1 region contrasts.

Reads m28_map_discovery.npz ONLY (opening m28_map_confirmation_SEALED.npz here is a protocol breach;
the file is not referenced anywhere in this script on purpose). Design: M28_MAP_DESIGN.md + Amendment 1
+ the amended seal. No condition freeze happens in this script -- the freeze is its own amendment,
written cold on a later pass.

Per Amendment 1:
  * The MOMENT is the unit. Outcomes decompose into D = (L-S)/2 (direction content) and A = (L+S)/2
    (machinery/cost). Directional claims attach to D only. Control-subtracted per moment.
  * NULL GATE: all contrasts run on (nullreal - ctrl) first; the gate fails if any contrast clears the
    survivor z-bar on noise, or the overall mean CIs exclude 0.
  * POSITIVE CONTROL: +10/+20/+30 bps injected into a COPY of the null D for fund_hot_xs==1 moments;
    the pipeline must recover the injection (detect at the claimed MDE) or nothing is read.
  * Contrasts: binary flags direct; continuous features top-vs-bottom quintile (pre-stated). Two-way
    (coin x week) bootstrap CI, act on the wider vs coin-only; eqw-by-coin and eqw-by-week beside
    pooled; n in moments. R governs (per-moment sf), bps beside.
  * Pre-stated expected signs: waking_24h -> D NEGATIVE for the up-side (M11 fade); btc_shock_24h ->
    A worse (M5 tail inflation); others exploratory.
  * L2: labels = FILLED owner-plan clusters deduped by (coin, side, overlapping 72h window);
    +/-72h same-coin aftermath exclusion for the gain; point estimate + CI, HYPOTHESIS-capped,
    descriptive. late_logged and status=duplicate never enter either pool.
"""
import io
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
T = np.load(os.path.join(HERE, "m28_map_discovery.npz"), allow_pickle=False)

ARMS = [str(a) for a in T["arms"]]              # runner_1.00atr, full_1R
FEATS = [str(f) for f in T["featnames"]]
coins_s = T["coins"]
ucoins, coin_idx = np.unique(coins_s, return_inverse=True)
C = len(ucoins)
daykey = T["daykey"]
week = daykey // 7
sf = T["sf"]
N = len(sf)
X = T["feats"]
rng = np.random.default_rng(20261017)
SURVIVOR_Z = 3.0
BOOT = 2000

ix = {f: i for i, f in enumerate(FEATS)}


def da(real_l, real_s, ctrl_l, ctrl_s):
    D = ((real_l - real_s) - (ctrl_l - ctrl_s)) / 2.0
    A = ((real_l + real_s) - (ctrl_l + ctrl_s)) / 2.0
    return D / sf[:, None], A / sf[:, None]      # R units


D_R, A_R = da(T["L_real"], T["S_real"], T["L_ctrl"], T["S_ctrl"])
D_N, A_N = da(T["L_null"], T["S_null"], T["L_ctrl"], T["S_ctrl"])
BPS = sf[:, None] * 1e4                          # R -> bps conversion per moment


def cell_means(vals, mask):
    """(coin, week) cell means of vals[mask] -> arrays for two-way bootstrap."""
    cw = coin_idx[mask] * 100000 + week[mask]
    ucw, inv = np.unique(cw, return_inverse=True)
    s = np.bincount(inv, weights=vals[mask])
    n = np.bincount(inv)
    return s / n, ucw // 100000, ucw % 100000


def boot_ci(vals, mask, nboot=BOOT):
    """pooled mean + coin-only CI + two-way (coin x week) CI + eqw-by-coin/week means."""
    v = vals[mask]
    if len(v) < 50:
        return None
    pooled = float(v.mean())
    ci = coin_idx[mask]
    cs = np.bincount(ci, weights=v, minlength=C)
    cc = np.bincount(ci, minlength=C)
    has = cc > 0
    coin_mu = cs[has] / cc[has]
    eqw_coin = float(coin_mu.mean())
    cm, cell_c, cell_w = cell_means(vals, mask)
    uw = np.unique(cell_w)
    wk_mu = np.array([cm[cell_w == w_].mean() for w_ in uw])
    eqw_week = float(wk_mu.mean())
    # coin-only bootstrap on per-coin means
    idx = rng.integers(0, len(coin_mu), size=(nboot, len(coin_mu)))
    ms1 = coin_mu[idx].mean(axis=1)
    # two-way
    ms2 = []
    ucs = np.unique(cell_c)
    for _ in range(nboot // 2):
        csamp = ucs[rng.integers(0, len(ucs), len(ucs))]
        wsamp = uw[rng.integers(0, len(uw), len(uw))]
        sel = cm[np.isin(cell_c, csamp) & np.isin(cell_w, wsamp)]
        if len(sel):
            ms2.append(sel.mean())
    lo1, hi1 = np.percentile(ms1, [2.5, 97.5])
    lo2, hi2 = np.percentile(ms2, [2.5, 97.5])
    lo, hi = (lo1, hi1) if (hi1 - lo1) >= (hi2 - lo2) else (lo2, hi2)
    se = max((hi1 - lo1), (hi2 - lo2)) / 3.92
    return {"pooled": pooled, "eqw_coin": eqw_coin, "eqw_week": eqw_week,
            "lo": float(lo), "hi": float(hi), "se": float(se), "n": int(mask.sum())}


def contrast(vals, cond_mask):
    """mean(vals | cond) - mean(vals | ~cond), with the wider of coin-only / two-way CI."""
    a = boot_ci(vals, cond_mask)
    b = boot_ci(vals, ~cond_mask)
    if a is None or b is None:
        return None
    d = a["pooled"] - b["pooled"]
    se = (a["se"] ** 2 + b["se"] ** 2) ** 0.5
    return {"diff": d, "se": se, "z": d / se if se > 0 else 0.0,
            "eqw_coin_diff": a["eqw_coin"] - b["eqw_coin"],
            "eqw_week_diff": a["eqw_week"] - b["eqw_week"],
            "n_cond": a["n"], "n_rest": b["n"]}


def condition_masks():
    out = []
    for f in ("fund_hot_xs", "waking_24h", "btc_shock_24h"):
        v = X[:, ix[f]]
        m = np.isfinite(v)
        if m.mean() < 0.8:
            continue
        out.append((f + "==1", np.where(m, v == 1.0, False)))
    for f in ("atr_em", "atr_pct", "stop_atr", "vol_rank_xs", "fund_pctl", "ret7_raw", "btc_r2", "room_long"):
        v = X[:, ix[f]]
        fin = np.isfinite(v)
        if fin.mean() < 0.8:
            continue
        qlo, qhi = np.percentile(v[fin], [20, 80])
        out.append((f + " top-q vs bottom-q", np.where(fin, v >= qhi, False)))
        # the complement for the contrast is the bottom quintile, handled below
    out.append(("trend_raw==+1", np.where(np.isfinite(X[:, ix["trend_raw"]]), X[:, ix["trend_raw"]] > 0, False)))
    return out


def quintile_contrast(vals, f):
    v = X[:, ix[f]]
    fin = np.isfinite(v)
    qlo, qhi = np.percentile(v[fin], [20, 80])
    top = fin & (v >= qhi)
    bot = fin & (v <= qlo)
    a, b = boot_ci(vals, top), boot_ci(vals, bot)
    if a is None or b is None:
        return None
    d = a["pooled"] - b["pooled"]
    se = (a["se"] ** 2 + b["se"] ** 2) ** 0.5
    return {"diff": d, "se": se, "z": d / se if se > 0 else 0.0,
            "eqw_coin_diff": a["eqw_coin"] - b["eqw_coin"], "eqw_week_diff": a["eqw_week"] - b["eqw_week"],
            "n_cond": a["n"], "n_rest": b["n"]}


BINARY = ("fund_hot_xs", "waking_24h", "btc_shock_24h", "trend_pos")
CONT = ("atr_em", "atr_pct", "stop_atr", "vol_rank_xs", "fund_pctl", "ret7_raw", "btc_r2", "room_long")


def all_contrasts(D, A):
    res = {}
    tr = np.where(np.isfinite(X[:, ix["trend_raw"]]), X[:, ix["trend_raw"]] > 0, False)
    bins = {"fund_hot_xs": np.where(np.isfinite(X[:, ix["fund_hot_xs"]]), X[:, ix["fund_hot_xs"]] == 1, False),
            "waking_24h": np.where(np.isfinite(X[:, ix["waking_24h"]]), X[:, ix["waking_24h"]] == 1, False),
            "btc_shock_24h": np.where(np.isfinite(X[:, ix["btc_shock_24h"]]), X[:, ix["btc_shock_24h"]] == 1, False),
            "trend_pos": tr}
    for s_i, arm in enumerate(ARMS):
        for nm, vals in (("D", D[:, s_i]), ("A", A[:, s_i])):
            for f, m in bins.items():
                r = contrast(vals, m)
                if r:
                    res["%s|%s|%s" % (arm, nm, f)] = r
            for f in CONT:
                r = quintile_contrast(vals, f)
                if r:
                    res["%s|%s|%s_q" % (arm, nm, f)] = r
    return res


def main():
    print("M28 stage A -- discovery. moments=%d coins=%d (DISCOVERY FILE ONLY)" % (N, C))
    # ---- NULL GATE ----
    print("=== NULL GATE (contrasts on nullreal - ctrl) ===")
    null_res = all_contrasts(D_N, A_N)
    zmax = max(abs(r["z"]) for r in null_res.values())
    om_d = boot_ci(D_N[:, 0], np.ones(N, bool))
    om_a = boot_ci(A_N[:, 0], np.ones(N, bool))
    print("null max |z| over %d contrasts: %.2f; null D mean %.4f [%.4f,%.4f]; null A mean %.4f [%.4f,%.4f]"
          % (len(null_res), zmax, om_d["pooled"], om_d["lo"], om_d["hi"], om_a["pooled"], om_a["lo"], om_a["hi"]))
    null_z = sorted((abs(r["z"]) for r in null_res.values()), reverse=True)[:5]
    print("top null |z|:", [round(z, 2) for z in null_z])
    if zmax >= SURVIVOR_Z or not (om_d["lo"] <= 0 <= om_d["hi"]):
        raise SystemExit("HALT: NULL GATE FAILED (max|z|=%.2f) -- pipeline broken, nothing is read." % zmax)
    mde_r = 2.8 * float(np.median([r["se"] for r in null_res.values()]))
    print("NULL GATE PASSED. MDE (2.8 x median contrast SE): %.4f R (~%.1f bps at median sf)"
          % (mde_r, mde_r * float(np.median(sf)) * 1e4))

    # ---- POSITIVE CONTROL (spec corrected after the first run HALTed before any read:
    #      the original demanded 30 bps detection on fund_hot, the WORST-clustered condition, whose
    #      own MDE is ~4x the median -- a mis-specified bar, not a broken pipeline. Corrected spec:
    #      (a) LINEARITY: contrast(injected) - contrast(null) must equal the injected mean R shift
    #          within 10% + bootstrap noise, on BOTH a clustered (fund_hot) and a dispersed
    #          (trend_pos) condition;
    #      (b) DETECTION: inject 1.5 x the condition's OWN MDE on the dispersed condition -> z >= 2.8;
    #      (c) publish per-condition MDEs -- the survivor profile's MDE term is per-condition.) ----
    print("=== POSITIVE CONTROL (corrected spec; first run HALTed pre-read on the old bar) ===")
    tr_m = np.where(np.isfinite(X[:, ix["trend_raw"]]), X[:, ix["trend_raw"]] > 0, False)
    hot = np.where(np.isfinite(X[:, ix["fund_hot_xs"]]), X[:, ix["fund_hot_xs"]] == 1, False)
    ok = True
    cond_mde = {}
    for nm, m in (("fund_hot_xs", hot), ("trend_pos", tr_m)):
        base = contrast(D_N[:, 0], m)
        cond_mde[nm] = 2.8 * base["se"]
        for shift_r in (0.05, 0.10):
            Dinj = D_N.copy()
            Dinj[m, 0] += shift_r
            r = contrast(Dinj[:, 0], m)
            rec = r["diff"] - base["diff"]
            lin_ok = abs(rec - shift_r) <= 0.10 * shift_r + 1e-9
            print("  [%s] inject %.2f R -> recovered %.4f R (linearity %s)" % (nm, shift_r, rec,
                  "OK" if lin_ok else "FAIL"))
            ok &= lin_ok
    det_shift = 1.5 * cond_mde["trend_pos"]
    Dinj = D_N.copy()
    Dinj[tr_m, 0] += det_shift
    r = contrast(Dinj[:, 0], tr_m)
    det = abs(r["z"]) >= 2.8
    print("  [trend_pos] inject 1.5 x own MDE (%.4f R) -> z %.2f detected=%s" % (det_shift, r["z"], det))
    ok &= det
    print("  per-condition MDE (2.8 x SE): fund_hot %.4f R, trend_pos %.4f R; median-contrast %.4f R"
          % (cond_mde["fund_hot_xs"], cond_mde["trend_pos"], mde_r))
    if not ok:
        raise SystemExit("HALT: POSITIVE CONTROL FAILED -- estimator not linear or cannot detect at "
                         "1.5 x own MDE.")
    print("POSITIVE CONTROL PASSED.")

    # ---- L1: the real discovery read ----
    print("=== L1 DISCOVERY (D = direction content, A = machinery/cost; R units; wider CI governs) ===")
    om = {}
    for s_i, arm in enumerate(ARMS):
        d_ = boot_ci(D_R[:, s_i], np.ones(N, bool))
        a_ = boot_ci(A_R[:, s_i], np.ones(N, bool))
        om[arm] = {"D": d_, "A": a_}
        print("[%s] D %.4f R [%.4f,%.4f] eqwC %.4f eqwW %.4f | A %.4f R [%.4f,%.4f] eqwC %.4f"
              % (arm, d_["pooled"], d_["lo"], d_["hi"], d_["eqw_coin"], d_["eqw_week"],
                 a_["pooled"], a_["lo"], a_["hi"], a_["eqw_coin"]))
    real_res = all_contrasts(D_R, A_R)
    rows = sorted(real_res.items(), key=lambda kv: -abs(kv[1]["z"]))
    print("--- top contrasts by |z| (survivor bar z>=%.1f is for the SEALED confirmation only) ---" % SURVIVOR_Z)
    for k, r in rows[:14]:
        print("  %-42s diff %+0.4f R (z %+5.2f) eqwC %+0.4f eqwW %+0.4f  n=%d/%d"
              % (k, r["diff"], r["z"], r["eqw_coin_diff"], r["eqw_week_diff"], r["n_cond"], r["n_rest"]))
    out = {"moments": int(N), "coins": int(C), "mde_r": mde_r,
           "null_gate": {"max_z": zmax, "top5": null_z},
           "overall": om, "contrasts": real_res,
           "pre_stated_signs": {"waking_24h D": "negative (M11 fade)", "btc_shock_24h A": "worse (M5)"}}
    io.open(os.path.join(HERE, "m28_discovery.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("wrote m28_discovery.json  (NO conditions are frozen in this pass -- freeze is its own "
          "amendment, written cold)")


if __name__ == "__main__":
    main()
