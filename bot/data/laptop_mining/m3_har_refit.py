"""M3 — JOINT HAR REFIT. One fit, one matching smearing. The root fix for D3.

THE DEFECT THIS EXISTS TO FIX. The live forecast pairs betas from one fit with a smearing factor from
a DIFFERENT refit (volforecast.py:52,57 -- stage-2 smearing 1.7017, a constant -2.2 log-point bias).
A smearing factor is E[exp(residual)] for a SPECIFIC regression; pairing it with other betas is not a
tunable constant, it is a mismatch. I argued in reply 122 that the fix is one refit producing both
rather than a patch, and this is that refit.

SECOND THING IT SETTLES. risk_voice applies a 0.8 haircut to the top forecast quintile because the
CURRENT model over-predicts there (y1_calibration_test deciles 9/10 ratios 0.807/0.781, mean 0.794).
That haircut is a patch on a calibration defect. If a joint fit is well calibrated in the top decile,
THE HAIRCUT CAN BE RETIRED. If it is not, the haircut gets re-estimated from this fit instead of the
old one. Either way it stops being a magic number.

METHOD
  target     |next-day return| in percent, from daily closes
  inputs     log rv1, log rv5, log rv22 (1/5/22-day), CLOSED BARS ONLY -- no bar still forming
  fit        OLS of log(target) on [1, log rv1, log rv5, log rv22], pooled across coins, exactly the
             functional form the live model uses, so the comparison is like-for-like
  smearing   Duan: mean(exp(residual)) FROM THE SAME FIT. This is the whole point.
  validation WALK-FORWARD BY MONTH: fit on everything up to month M, score month M+1. No month is
             ever scored by a model that saw it.
  scoring    QLIKE = mean(a/p - log(a/p) - 1), the proper scoring rule for a magnitude forecast,
             against (a) the current live coefficients and (b) naive persistence (predict rv1)
  output     coefficients, smearing, out-of-sample QLIKE, and calibration deciles

EXPLORATORY until the walk-forward beats the incumbent out of sample; coefficients are not a claim.
"""
import collections
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
WARMUP = 30

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
CUR_B, CUR_S = np.asarray(CO["y1_beta"], float), float(CO["y1_smearing"])


def daily_panel():
    """Per coin-day: rv1, rv5, rv22 from CLOSED daily bars, and the next day's |return|."""
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    rows = c.execute("SELECT coin, t, c FROM candles_1h ORDER BY coin, t").fetchall()
    c.close()
    bycoin = collections.defaultdict(list)
    for coin, t, cl in rows:
        bycoin[coin].append((int(t), float(cl)))
    out = []
    for coin, seq in bycoin.items():
        day = {}
        for t, cl in seq:
            day[t // 86400000] = (t, cl)          # last bar of each day wins => closed daily bar
        ds = sorted(day)
        if len(ds) < WARMUP + 5:
            continue
        close = np.array([day[d][1] for d in ds], float)
        ret = np.concatenate(([0.0], (close[1:] / close[:-1] - 1.0) * 100.0))
        for i in range(WARMUP, len(ds) - 1):
            rv1 = abs(ret[i])
            rv5 = float(np.std(ret[i - 4:i + 1], ddof=1))
            rv22 = float(np.std(ret[i - 21:i + 1], ddof=1))
            nxt = abs(ret[i + 1])
            if rv1 <= 0 or rv5 <= 0 or rv22 <= 0 or nxt <= 0:
                continue
            out.append({"coin": coin, "day": int(ds[i]),
                        "month": int(ds[i] // 30), "x1": math.log(rv1 + EPS),
                        "x5": math.log(rv5 + EPS), "x22": math.log(rv22 + EPS),
                        "y": math.log(nxt + EPS), "actual": nxt, "rv1": rv1})
    return out


def fit(rows):
    """OLS + Duan smearing from the SAME residuals. Returns (beta, smearing)."""
    X = np.column_stack([np.ones(len(rows)),
                         [r["x1"] for r in rows],
                         [r["x5"] for r in rows],
                         [r["x22"] for r in rows]])
    y = np.asarray([r["y"] for r in rows], float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, float(np.mean(np.exp(resid)))


def predict(rows, beta, smear):
    X = np.column_stack([np.ones(len(rows)),
                         [r["x1"] for r in rows],
                         [r["x5"] for r in rows],
                         [r["x22"] for r in rows]])
    return np.exp(X @ beta) * smear


def qlike(actual, pred):
    a = np.asarray(actual, float)
    p = np.maximum(np.asarray(pred, float), 1e-9)
    r = a / p
    return float(np.mean(r - np.log(r) - 1.0))


def deciles(actual, pred, label):
    o = np.argsort(pred)
    a, p = np.asarray(actual)[o], np.asarray(pred)[o]
    n = len(a) // 10
    print("  %s" % label)
    print("    %-8s %9s %9s %7s" % ("decile", "pred", "actual", "ratio"))
    rows = []
    for d in range(10):
        s = slice(d * n, (d + 1) * n if d < 9 else len(a))
        mp, ma = float(np.mean(p[s])), float(np.mean(a[s]))
        rows.append({"decile": d + 1, "pred": mp, "actual": ma, "ratio": ma / mp if mp else 0})
        flag = "  <-- top two" if d >= 8 else ""
        print("    %-8d %9.3f %9.3f %7.3f%s" % (d + 1, mp, ma, ma / mp if mp else 0, flag))
    top2 = [r for r in rows if r["decile"] >= 9]
    m = float(np.mean([r["ratio"] for r in top2]))
    print("    top-two mean ratio %.3f  ->  implied haircut %.3f" % (m, m))
    return rows, m


def main():
    rows = daily_panel()
    print("M3 joint HAR refit -- one fit, one matching smearing. Root fix for D3.")
    print("panel: %d coin-days, %d coins, %d month-blocks\n"
          % (len(rows), len({r["coin"] for r in rows}), len({r["month"] for r in rows})))

    months = sorted({r["month"] for r in rows})
    oos = {"joint": [], "current": [], "naive": []}
    oos_a = []
    for mi in range(3, len(months)):
        tr = [r for r in rows if r["month"] < months[mi]]
        te = [r for r in rows if r["month"] == months[mi]]
        if len(tr) < 2000 or len(te) < 200:
            continue
        b, s = fit(tr)
        a = [r["actual"] for r in te]
        oos_a.extend(a)
        oos["joint"].extend(predict(te, b, s))
        oos["current"].extend(predict(te, CUR_B, CUR_S))
        oos["naive"].extend([r["rv1"] for r in te])
    print("--- WALK-FORWARD OUT-OF-SAMPLE QLIKE (lower is better), %d scored coin-days ---"
          % len(oos_a))
    res = {}
    for k in ("joint", "current", "naive"):
        res[k] = qlike(oos_a, oos[k])
        print("  %-9s QLIKE %.4f" % (k, res[k]))
    best = min(res, key=res.get)
    print("  winner: %s" % best.upper())
    if res["joint"] < res["current"]:
        print("  joint beats the incumbent by %.1f%%"
              % (100 * (res["current"] - res["joint"]) / res["current"]))
    else:
        print("  joint does NOT beat the incumbent -- report that, do not tune")

    print("\n--- FULL-SAMPLE COEFFICIENTS (for the canonical model) ---")
    b, s = fit(rows)
    print("  joint   beta %s  smearing %.4f" % (np.round(b, 4).tolist(), s))
    print("  current beta %s  smearing %.4f" % (np.round(CUR_B, 4).tolist(), CUR_S))
    print("  NOTE: the joint smearing comes from THESE residuals. That is the D3 fix.")

    print("\n--- CALIBRATION: can the 0.8 haircut be retired? ---")
    pj = predict(rows, b, s)
    pc = predict(rows, CUR_B, CUR_S)
    dj, mj = deciles([r["actual"] for r in rows], pj, "JOINT refit")
    dc, mc = deciles([r["actual"] for r in rows], pc, "CURRENT live model")
    print("\n  current top-two ratio %.3f (the 0.8 haircut's justification)" % mc)
    print("  joint   top-two ratio %.3f" % mj)
    if 0.93 <= mj <= 1.07:
        print("  -> the joint fit is CALIBRATED in the top decile: the 0.8 haircut can be RETIRED")
    else:
        print("  -> still miscalibrated: the haircut should be RE-ESTIMATED at %.3f, not 0.8" % mj)

    io.open(os.path.join(HERE, "m3_har_refit.json"), "w", encoding="utf-8").write(json.dumps({
        "panel_coin_days": len(rows), "oos_scored": len(oos_a), "qlike": res,
        "joint_beta": b.tolist(), "joint_smearing": s,
        "current_beta": CUR_B.tolist(), "current_smearing": CUR_S,
        "joint_top2_ratio": mj, "current_top2_ratio": mc,
        "joint_deciles": dj, "current_deciles": dc}, indent=1))
    print("\nwrote m3_har_refit.json")
    print("STAGE 2 (funding + live dissent) NOT run: the dissent series is not on this disk.")


if __name__ == "__main__":
    main()
