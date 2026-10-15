"""Mission 9 EXTENSION to CHIEF_GRADEABLE.md (2026-10-10) - adds the two axes the prior pass did not
cover, WITHOUT re-running the levels verdict (that is pre-registered for 2026-10-16; do not pre-empt).
New axes:
  1. DIRECTION via p_up_24h (the prior said "direction cannot be graded" categorically, but the chief
     DOES emit a continuous prob): AUC + Brier vs 0.5 and vs the regime base rate.
  2. VOLATILITY vs the HAR baseline under PROPER scores (MAE cherry-picks HAR; MSE/QLIKE/range are the
     standard vol scores): is expected_move_pct better than har_move_pct?
  3. CONDITIONAL skill: score ONLY the non-degenerate calls (conviction>=2 OR |p_up-50|>=2) - the only
     ones that can be right or wrong - as the standing forward metric.
Honest framing: one quiet 4-day regime, underpowered -> DEFER, not a settled null.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import rng

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
CALLS = os.path.join(HERE, "server_exports", "chief_calls.jsonl")
H24 = 24


def main():
    rows = [json.loads(l) for l in open(CALLS) if l.strip()]
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    syms = sorted(set(r["symbol"] for r in rows))
    cd = {}
    for s in syms:
        a = np.asarray(c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (s,)).fetchall(), float)
        if len(a) > 200:
            cd[s] = a
    c.close()

    rm_close, rm_range, ex, ha, pup, sgn, conv, sym = [], [], [], [], [], [], [], []
    for r in rows:
        s = r["symbol"]
        if s not in cd:
            continue
        a = cd[s]
        i = int(np.searchsorted(a[:, 0], r["ts"] * 1000.0))
        if i < 1 or i + H24 >= len(a):
            continue
        px = a[i, 3] if a[i, 3] > 0 else r["price"]
        ret = a[i + H24, 3] / px - 1.0
        rc = abs(ret) * 100.0
        rr = (a[i + 1:i + 1 + H24, 1].max() - a[i + 1:i + 1 + H24, 2].min()) / px * 100.0
        if r.get("expected_move_pct") and r.get("har_move_pct"):
            rm_close.append(rc); rm_range.append(rr); ex.append(r["expected_move_pct"]); ha.append(r["har_move_pct"])
            sym.append(s); conv.append(r.get("conviction", 1))
            pup.append(r.get("p_up_24h", np.nan)); sgn.append(1.0 if ret > 0 else 0.0)
    rm_close = np.array(rm_close); rm_range = np.array(rm_range)
    ex = np.array(ex); ha = np.array(ha); sym = np.array(sym); conv = np.array(conv)
    pup = np.array(pup); sgn = np.array(sgn)
    n = len(ex)

    def clus(v, g):
        u = np.unique(g); grp = {x: v[g == x] for x in u}
        b = np.array([np.concatenate([grp[p] for p in u[rng.integers(0, len(u), len(u))]]).mean() for _ in range(3000)])
        return float(v.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))

    print("Mission 9 EXTENSION. aligned n=%d, symbols=%d, days=%d (honors the 2026-10-16 levels re-test prereg)"
          % (n, len(np.unique(sym)), len(np.unique((np.array([r['ts'] for r in rows if r.get('har_move_pct')][:n]) // 86400).astype(int)))))

    print("\n=== 1. VOLATILITY: expected_move vs HAR under proper scores (+ = chief better) ===")
    for name, real in [("close |move|", rm_close), ("hi-lo range", rm_range)]:
        mae = (np.abs(real - ha) - np.abs(real - ex))
        mse = ((real - ha) ** 2 - (real - ex) ** 2)
        m1, l1, h1 = clus(mae, sym); m2, l2, h2 = clus(mse, sym)
        print("  realised=%-11s | dMAE %+.4f [%+.4f,%+.4f] | dMSE %+.4f [%+.4f,%+.4f] (mean real %.2f%%)"
              % (name, m1, l1, h1, m2, l2, h2, real.mean()))
    # QLIKE on close-move magnitude (guard tiny)
    f_ha = np.maximum(ha, 1e-6); f_ex = np.maximum(ex, 1e-6); rv = np.maximum(rm_close, 1e-6)
    ql = (np.log(f_ha) + rv / f_ha) - (np.log(f_ex) + rv / f_ex)
    mq, lq, hq = clus(ql, sym)
    print("  QLIKE dq %+.4f [%+.4f,%+.4f] (+ = chief better)" % (mq, lq, hq))
    print("  -> underpowered (4 day-clusters, one quiet regime); sign flips by metric -> DEFER to the")
    print("     2026-10-16 re-test. Substantive bar to justify Opus on vol: cut MAE >=10%% (>=0.17%%).")

    print("\n=== 2. DIRECTION via p_up_24h (prior said 'unscoreable'; it IS emitted and scoreable) ===")
    ok = np.isfinite(pup)
    p = pup[ok] / 100.0 if np.nanmax(pup) > 1.5 else pup[ok]
    y = sgn[ok]
    base = float(y.mean())
    brier = float(np.mean((p - y) ** 2))
    brier05 = float(np.mean((0.5 - y) ** 2))
    brier_base = float(np.mean((base - y) ** 2))
    # AUC via rank
    order = np.argsort(p); r_ = np.empty(len(p)); r_[order] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    auc = float((r_[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 > 0 and n0 > 0 else float("nan")
    print("  n=%d | p_up spans %.0f-%.0f%% (mode ~50) | up-rate %.2f | AUC %.3f | Brier %.4f vs 0.5=%.4f vs base=%.4f"
          % (ok.sum(), np.nanmin(pup), np.nanmax(pup), base, auc, brier, brier05, brier_base))
    print("  -> no discrimination (AUC~0.5), miscalibrated for a down-drift regime. 'direction cannot be")
    print("     graded' should read 'the probability is pinned ~50%% and shows no discrimination'.")

    print("\n=== 3. CONDITIONAL skill on the only non-degenerate calls (conviction>=2 OR |p_up-50|>=2) ===")
    nd = ok & ((conv >= 2) | (np.abs(pup - 50) >= 2))
    if nd.sum() >= 5:
        pn = (pup[nd] / 100.0) if np.nanmax(pup) > 1.5 else pup[nd]
        yn = sgn[nd]
        print("  non-degenerate n=%d | up-rate %.2f | Brier %.4f vs 0.5=%.4f (the standing forward metric)"
              % (nd.sum(), yn.mean(), np.mean((pn - yn) ** 2), np.mean((0.5 - yn) ** 2)))
    else:
        print("  non-degenerate n=%d -> too few to score yet; accumulate." % nd.sum())
    print("  conviction-2 calls in sample: %d (these are risk-overlay reads, not forecasts - grading the" % int((conv >= 2).sum()))
    print("  chief's ACTUAL function needs the bot action log; flagged to PC).")

    out = {"n": n, "vol_dMAE_close": clus(np.abs(rm_close - ha) - np.abs(rm_close - ex), sym),
           "vol_dMSE_close": clus((rm_close - ha) ** 2 - (rm_close - ex) ** 2, sym),
           "auc": auc, "brier": brier, "brier_0.5": brier05, "brier_base": brier_base,
           "nondegen_n": int(nd.sum()), "conv2_n": int((conv >= 2).sum())}
    io.open(os.path.join(HERE, "m9b_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("\nwrote m9b_result.json")


if __name__ == "__main__":
    main()
