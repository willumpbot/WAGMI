"""Mission 7: forecast move SIZE, since direction is not forecastable.

Established so far: no directional edge anywhere (three datasets), but
corr(today's ATR%, next-5d realised vol) = +0.341 full / +0.353 test, and
near-unanimity among voice families precedes a ~55% larger next-day move.

So build the smallest honest forecaster and check it against the only baseline
that matters: naive persistence (tomorrow's vol = today's vol). A forecaster
that cannot beat persistence is not worth shipping.

Model: HAR-RV in logs -- regress log(future vol) on log vol at 1 / 5 / 22-day
scales, the standard specification for realised volatility. Then test whether
the mission-5 consensus-disagreement count adds anything on top.

Reported out of sample: correlation, R^2, QLIKE, and a decile calibration table
(predicted vs actual), because a forecast that ranks well but is badly scaled is
useless for position sizing.
"""
import json, io, os, glob, time, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8


def load_daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c", "v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    return df


def build(sym, df, btc_vol):
    c, h, l = df["c"], df["h"], df["l"]
    ret = c.pct_change() * 100
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean() / c * 100

    # realised vol at three scales (past only)
    rv1 = ret.abs()
    rv5 = ret.rolling(5).std()
    rv22 = ret.rolling(22).std()
    rng_pct = (h - l) / c * 100

    out = pd.DataFrame({"t": df["t"], "sym": sym})
    out["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    out["atr_pct"] = atr14
    out["rv1"] = rv1
    out["rv5"] = rv5
    out["rv22"] = rv22
    out["rng_pct"] = rng_pct
    out["volume_z"] = (df["v"] / df["v"].rolling(20).mean()).replace([np.inf, -np.inf], np.nan)
    out["btc_rv5"] = out["day"].map(btc_vol)

    # ---- targets, strictly future ----
    out["y1"] = ret.shift(-1).abs()                      # next-day absolute move
    out["y5"] = ret.shift(-5).rolling(5).std()           # next-5-day realised vol
    # naive persistence benchmarks
    out["naive1"] = rv1
    out["naive5"] = rv5
    return out


syms = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
btc = load_daily("BTC")
bret = btc["c"].pct_change() * 100
btc_vol = pd.Series(bret.rolling(5).std().values,
                    index=pd.to_datetime(btc["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"))
btc_vol = btc_vol[~btc_vol.index.duplicated()]

frames = []
for s in syms:
    d = load_daily(s)
    if d is None or len(d) < 120:
        continue
    frames.append(build(s, d, btc_vol))
panel = pd.concat(frames, ignore_index=True)

# mission-5 consensus disagreement count, recomputed here so the two tie together
def add_consensus(panel):
    out = []
    for sym, g in panel.groupby("sym"):
        d = load_daily(sym)
        c, h, l = d["c"], d["h"], d["l"]
        e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        up, dn = h.diff(), -l.diff()
        pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index)
        mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
        atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
        pdi = pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        mdi = mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
        bb = (c - ma20) / (2 * sd20).replace(0, np.nan)
        dd = c.diff()
        gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        # one representative per independent family (voice_families.json)
        fam = pd.DataFrame({
            "structure": np.where(e20 > e50, 1, -1),
            "stretch": np.where(c > e20, 1, -1),              # fam_7 representative
            "rsi": np.where(rsi > 70, 1, np.where(rsi < 30, -1, 0)),
            "bollinger": np.where(bb > 0.8, 1, np.where(bb < -0.8, -1, 0)),
            "mom7": np.sign(c / c.shift(7) - 1).fillna(0),
            "mom30": np.sign(c / c.shift(30) - 1).fillna(0),
        })
        net = fam.sum(axis=1)
        netdir = np.sign(net)
        disagree = sum((fam[col] != netdir).astype(int) for col in fam.columns)
        tmp = pd.DataFrame({"day": pd.to_datetime(d["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"),
                            "sym": sym, "disagree": disagree.values})
        out.append(tmp)
    return pd.concat(out, ignore_index=True)


panel = panel.merge(add_consensus(panel), on=["day", "sym"], how="left")
panel = panel.dropna(subset=["y1", "y5", "rv22", "atr_pct", "naive5"])
panel = panel[(panel["y5"] > 0) & (panel["naive5"] > 0) & (panel["rv1"] >= 0)]
print(f"panel {len(panel)} rows  {panel['day'].min()} -> {panel['day'].max()}  "
      f"{panel['sym'].nunique()} symbols")

train = panel[panel["day"] < CUTOFF].copy()
test = panel[panel["day"] >= CUTOFF].copy()
print(f"train {len(train)}   test {len(test)}")

FEATS = ["rv1", "rv5", "rv22"]          # HAR-RV core


def fit_ols(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def predict(beta, X):
    return np.column_stack([np.ones(len(X)), X]) @ beta


def smearing(beta, X, y_log):
    """Duan's smearing factor for a log-linear model.

    Fitting log(y) and exponentiating returns a conditional MEDIAN, not a mean,
    so the level is biased low by Jensen's inequality -- badly so for |return|,
    which is strongly right-skewed. The factor is mean(exp(residual)) estimated
    on TRAIN only, then applied to test predictions. Without this the y1 forecast
    under-predicts every decile by 36-83%.
    """
    resid = y_log - predict(beta, X)
    return float(np.mean(np.exp(resid)))


def scores(actual, pred, label):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    m = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    a, p = a[m], p[m]
    if len(a) < 30:
        return None
    corr = float(np.corrcoef(a, p)[0, 1])
    ss = float(1 - ((a - p) ** 2).sum() / ((a - a.mean()) ** 2).sum())
    qlike = float(np.mean(a / p - np.log(a / p) - 1))     # lower is better
    bias = float(np.mean(p - a))
    return {"n": int(len(a)), "corr": round(corr, 4), "r2": round(ss, 4),
            "qlike": round(qlike, 4), "mean_bias": round(bias, 4), "label": label}


results = {}
print("\n" + "=" * 100)
print("MISSION 7 — volatility forecast vs naive persistence (out of sample)")
print("=" * 100)
print(f"  {'target / model':<34}{'n':>7}{'corr':>9}{'R2':>9}{'QLIKE':>9}{'bias':>9}")
print("-" * 100)

for tgt, naive in (("y1", "naive1"), ("y5", "naive5")):
    ltr = np.log(train[FEATS] + EPS).values
    lte = np.log(test[FEATS] + EPS).values
    ytr = np.log(train[tgt] + EPS).values
    beta = fit_ols(ltr, ytr)
    sm = smearing(beta, ltr, ytr)          # train-only Jensen correction
    pred_te = np.exp(predict(beta, lte)) * sm
    print(f"  [{tgt}] smearing factor = {sm:.4f}")

    s_naive = scores(test[tgt], test[naive], "naive persistence")
    s_har = scores(test[tgt], pred_te, "HAR-RV (log, 1/5/22d)")
    for s in (s_naive, s_har):
        if s:
            print(f"  {tgt} {s['label']:<30}{s['n']:>7}{s['corr']:>9.4f}{s['r2']:>9.4f}"
                  f"{s['qlike']:>9.4f}{s['mean_bias']:>+9.4f}")

    # + consensus disagreement
    extra = ["disagree"]
    tr2 = train.dropna(subset=extra)
    te2 = test.dropna(subset=extra)
    if len(tr2) > 500 and len(te2) > 200:
        Xtr = np.column_stack([np.log(tr2[FEATS] + EPS).values, tr2[extra].values])
        Xte = np.column_stack([np.log(te2[FEATS] + EPS).values, te2[extra].values])
        y2 = np.log(tr2[tgt] + EPS).values
        b2 = fit_ols(Xtr, y2)
        sm2 = smearing(b2, Xtr, y2)
        s_plus = scores(te2[tgt], np.exp(predict(b2, Xte)) * sm2, "HAR + consensus count")
        if s_plus:
            print(f"  {tgt} {s_plus['label']:<30}{s_plus['n']:>7}{s_plus['corr']:>9.4f}"
                  f"{s_plus['r2']:>9.4f}{s_plus['qlike']:>9.4f}{s_plus['mean_bias']:>+9.4f}")
            results[f"{tgt}_har_plus_consensus"] = s_plus
            print(f"      consensus coefficient: {b2[-1]:+.4f} "
                  f"(negative => more disagreement means smaller moves)")
            results[f"{tgt}_consensus_coef"] = round(float(b2[-1]), 4)

    results[f"{tgt}_naive"] = s_naive
    results[f"{tgt}_har"] = s_har
    results[f"{tgt}_beta"] = [round(float(x), 4) for x in beta]
    results[f"{tgt}_smearing"] = round(sm, 4)

    # ---- decile calibration on the test set ----
    te = test.dropna(subset=[tgt]).copy()
    te["pred"] = np.exp(predict(beta, np.log(te[FEATS] + EPS).values)) * sm
    te = te[(te["pred"] > 0) & np.isfinite(te["pred"])]
    te["dec"] = pd.qcut(te["pred"], 10, labels=False, duplicates="drop")
    print(f"\n  {tgt} decile calibration (test): predicted vs actual")
    print(f"    {'decile':<8}{'n':>7}{'pred':>9}{'actual':>9}{'ratio':>8}")
    cal = []
    for d, g in te.groupby("dec"):
        pm, am = float(g["pred"].mean()), float(g[tgt].mean())
        print(f"    {int(d)+1:<8}{len(g):>7}{pm:>9.3f}{am:>9.3f}{am/pm:>8.2f}")
        cal.append({"decile": int(d) + 1, "n": int(len(g)),
                    "pred": round(pm, 4), "actual": round(am, 4),
                    "ratio": round(am / pm, 3)})
    results[f"{tgt}_calibration_test"] = cal
    lo, hi = cal[0]["actual"], cal[-1]["actual"]
    print(f"    spread: decile 1 actual {lo:.3f}%  ->  decile 10 actual {hi:.3f}%  "
          f"({hi/lo:.1f}x)")
    results[f"{tgt}_decile_spread_x"] = round(hi / lo, 2)

verdict = []
for tgt in ("y1", "y5"):
    n, hh = results.get(f"{tgt}_naive"), results.get(f"{tgt}_har")
    if n and hh:
        better = hh["qlike"] < n["qlike"] and hh["corr"] > n["corr"]
        verdict.append(f"{tgt}: HAR {'BEATS' if better else 'does NOT beat'} naive persistence "
                       f"(QLIKE {hh['qlike']:.4f} vs {n['qlike']:.4f}, "
                       f"corr {hh['corr']:.3f} vs {n['corr']:.3f})")
print("\n" + "=" * 100)
print("VERDICT")
print("=" * 100)
for v in verdict:
    print("  " + v)
results["verdict"] = verdict

with io.open(os.path.join(HERE, "volatility_forecast.json"), "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=1)
print("\nwrote volatility_forecast.json")
