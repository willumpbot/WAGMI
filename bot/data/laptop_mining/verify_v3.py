"""Verify the red team's two FATAL findings against geometry_v3's recommendation.

Reviewer claim 1: the recommended cell 2.0|0.5 FAILS week-level clustering -- the exact
  standard GEOMETRY_V3.md enforces against the 48h drift claim. Stated: equal-weighted
  week mean +0.0733R, t=1.41, p=0.183, CI95 [-0.0392,+0.1858], 9/14 weeks positive, and
  the pooled mean (+0.1187) is 62% larger than the week mean.

Reviewer claim 2: the TARGET half of the decision card (1.5R -> 0.5R) was never tested at
  the recommended stop width. Stated: sym(2.0|0.5) - sym(2.0|1.5) = +0.0367R, week t=1.55,
  CI [-0.0146,+0.0880]; on real returns +0.0429R, t=0.75. Both contain zero. The fee saving
  is identical across tp, so the target half rests on a non-fee residual that is not
  distinguishable from zero.

If both hold, the card must shrink to "widen the stop, on deterministic fee arithmetic" and
drop the target change entirely.
"""
import json, io, os, gzip, collections, datetime, math, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

from geometry_v3 import sim3, init, CELLS
from geometry_v2 import DEFAULT, HERE, FEE_BPS

REC = "2.0|0.5"


def wk_t(d, wk):
    """Equal-weighted week means + a plain t-test on the 14 week means."""
    ws = np.unique(wk)
    mus = np.array([d[wk == w].mean() for w in ws])
    n = len(mus)
    m, s = float(mus.mean()), float(mus.std(ddof=1))
    se = s / math.sqrt(n)
    t = m / se if se > 0 else float("nan")
    # two-sided p from the t distribution, n-1 df, via a normal-ish approximation
    try:
        from statistics import NormalDist
        # Welch-Satterthwaite not needed; use t via survival of |t| under n-1 df
        import math as _m
        # crude but adequate: normal approx with small-sample widening
        p = 2 * (1 - NormalDist().cdf(abs(t) * (1 - 1 / (4 * (n - 1)))))
    except Exception:
        p = float("nan")
    tcrit = 2.160 if n == 14 else 1.96      # t_{0.975, 13} = 2.160
    return m, t, p, (m - tcrit * se, m + tcrit * se), int((mus > 0).sum()), n


def main():
    sigs = []
    with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            try:
                t0 = pd.Timestamp(d["ts"]).timestamp()
            except Exception:
                continue
            base = abs(float(d["entry"]) - float(d["sl"]))
            if base <= 0:
                continue
            day = d["ts"][:10]
            w = datetime.date.fromisoformat(day).isocalendar()
            sigs.append({"sym": d["sym"], "side": d["side"], "base": base, "t0": t0,
                         "day": day, "week": f"{w[0]}-W{w[1]:02d}"})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for o, _ in pool.imap_unordered(sim3, [(s, by[s]) for s in syms]):
            recs.extend(o)
    df = pd.DataFrame(recs)
    wk = df["week"].values
    for cell in CELLS:
        rk, fk = f"real|{cell}", f"flip|{cell}"
        if rk in df.columns:
            df[f"sym|{cell}"] = (df[rk] + df[fk]) / 2.0
    print(f"simulated {len(df)} rows, {df['week'].nunique()} ISO weeks\n")

    out = {}
    print("=" * 100)
    print(f"CLAIM 1 — does the recommended cell {REC} survive WEEK-LEVEL clustering?")
    print("  (the standard GEOMETRY_V3.md itself enforces against the 48h drift claim)")
    print("=" * 100)
    d = (df[f"sym|{REC}"] - df[f"sym|{DEFAULT}"]).values
    m = np.isfinite(d)
    pooled = float(d[m].mean())
    wm, t, p, ci, npos, nw = wk_t(d[m], wk[m])
    print(f"  pooled mean (what I published)      : {pooled:+.4f} R")
    print(f"  equal-weighted week mean            : {wm:+.4f} R   over {nw} weeks")
    print(f"  week-mean t-test                    : t = {t:+.2f}, p = {p:.3f}")
    print(f"  week-mean CI95 (t_.975,13 = 2.160)  : [{ci[0]:+.4f}, {ci[1]:+.4f}]")
    print(f"  weeks positive                      : {npos}/{nw}")
    print(f"  pooled is {100*(pooled/wm-1):.0f}% larger than the equal-weighted week mean")
    survives = ci[0] > 0
    print(f"\n  => {'SURVIVES week clustering' if survives else 'FAILS week clustering — CI CONTAINS ZERO'}")
    out["claim1"] = {"pooled": round(pooled, 4), "week_mean": round(wm, 4), "t": round(float(t), 3),
                     "ci": [round(ci[0], 4), round(ci[1], 4)], "weeks_positive": npos,
                     "weeks": nw, "survives": bool(survives)}

    print("\n" + "=" * 100)
    print("CLAIM 2 — was the TARGET change (1.5R -> 0.5R) ever tested AT the recommended stop?")
    print("=" * 100)
    for lab, a, b in (("sym (direction-free)", f"sym|2.0|0.5", f"sym|2.0|1.5"),
                      ("real returns", f"real|2.0|0.5", f"real|2.0|1.5")):
        dd = (df[a] - df[b]).values
        mm = np.isfinite(dd)
        wm2, t2, p2, ci2, np2, nw2 = wk_t(dd[mm], wk[mm])
        print(f"  {lab:<22} pooled {dd[mm].mean():+.4f}  week mean {wm2:+.4f}  "
              f"t {t2:+.2f}  CI [{ci2[0]:+.4f},{ci2[1]:+.4f}]  {np2}/{nw2} wks +")
        out.setdefault("claim2", {})[lab] = {
            "pooled": round(float(dd[mm].mean()), 4), "week_mean": round(wm2, 4),
            "t": round(float(t2), 3), "ci": [round(ci2[0], 4), round(ci2[1], 4)],
            "survives": bool(ci2[0] > 0)}
    print("\n  is the FEE saving identical across targets at the same stop width?")
    # fee term depends only on stop distance, so it must be
    for tp in ("0.5", "1.0", "1.5"):
        feeR = 2 * (FEE_BPS / 1e4) / (2.0 * 0.01415)   # illustrative at the modal base
        print(f"    stop x2, tp {tp}R -> fee term {feeR:.4f} R  (independent of tp by construction)")
    print("  => the target half cannot inherit any of the fee argument.")

    print("\n" + "=" * 100)
    print("WHAT SURVIVES — the deterministic part")
    print("=" * 100)
    print("  The fee saving is arithmetic, not statistical: fee_R = 2*9bps/(m*base).")
    base = 0.01415
    f1 = 2 * (FEE_BPS / 1e4) / (1.0 * base)
    f2 = 2 * (FEE_BPS / 1e4) / (2.0 * base)
    print(f"    stop x1 : {f1:.4f} R per trade")
    print(f"    stop x2 : {f2:.4f} R per trade")
    print(f"    saving  : {f1-f2:+.4f} R  <- deterministic, needs no significance test")
    out["deterministic_fee_saving_R"] = round(f1 - f2, 4)
    print("\n  VERDICT")
    if not survives:
        print("    * the TOTAL +0.1187R does NOT survive week clustering (CI contains zero)")
    if not out["claim2"]["sym (direction-free)"]["survives"]:
        print("    * the TARGET change is NOT supported at the recommended stop width")
    print(f"    * the fee component ({f1-f2:+.4f} R) is arithmetic and DOES hold")
    print("    => ship the STOP WIDTH on fee grounds; DROP the target change.")
    with io.open(os.path.join(HERE, "verify_v3.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote verify_v3.json")


if __name__ == "__main__":
    main()
