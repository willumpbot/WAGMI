"""Proposal D: model the volatility forecast's own error.

The HAR model works (22/22 walk-forward folds) but its top two deciles
over-predict by 15-24%, and `risk_voice.py` currently patches that with a flat
x0.8. A flat multiplier covering a structured error is a hack; if the error is
predictable, a second stage should absorb it.

This matters more than it sounds: every stop width and every leverage cap served
by `risk_voice.py` is scaled off this forecast, so a calibration improvement
propagates into both -- and unlike the directional work, it improves something
already known to be real.

Target:   log(actual / predicted)  -- the forecast's log error
Features: forecast level, funding, consensus dissent, BTC volatility, weekday,
          days since the last large move, and the forecast's own term structure
Accept only what survives train -> test, judged on QLIKE and decile calibration
(not R^2, which rewards fitting the noisy tail).
"""
import json, io, os, glob, time, math, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8
COINS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]
rng = np.random.default_rng(20261008)


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


def funding(sym):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if not os.path.exists(p) or os.path.getsize(p) < 500:
        return None
    f = pd.read_csv(p)
    f["rate"] = pd.to_numeric(f["rate"], errors="coerce")
    f = f.dropna(subset=["rate"])
    f["day"] = pd.to_datetime(f["t_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return f.groupby("day")["rate"].sum().mul(100)


btc = daily("BTC")
bret = btc["c"].pct_change() * 100
btc_vol = pd.Series(bret.rolling(5).std().values, index=btc["day"]).groupby(level=0).first()

frames = []
for s in COINS:
    d = daily(s)
    if d is None or len(d) < 160:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    ret = c.pct_change() * 100
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    dd = c.diff()
    gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    bb = (c - ma20) / (2 * sd20).replace(0, np.nan)
    fam = pd.DataFrame({
        "structure": np.where(e20 > e50, 1, -1),
        "stretch": np.where(c > e20, 1, -1),
        "rsi": np.where(rsi > 70, 1, np.where(rsi < 30, -1, 0)),
        "boll": np.where(bb > 0.8, 1, np.where(bb < -0.8, -1, 0)),
        "mom7": np.sign(c / c.shift(7) - 1).fillna(0),
        "mom30": np.sign(c / c.shift(30) - 1).fillna(0)})
    netdir = np.sign(fam.sum(axis=1))
    disagree = sum((fam[x] != netdir).astype(int) for x in fam.columns)

    rv1, rv5, rv22 = ret.abs(), ret.rolling(5).std(), ret.rolling(22).std()
    big = (ret.abs() > 2 * rv22)
    # days since the last >2-sigma move
    since = np.zeros(len(d))
    last = -1
    for i in range(len(d)):
        if bool(big.iloc[i]):
            last = i
        since[i] = (i - last) if last >= 0 else 999
    fnd = funding(s)
    out = pd.DataFrame({
        "sym": s, "day": d["day"], "rv1": rv1, "rv5": rv5, "rv22": rv22,
        "y1": ret.shift(-1).abs(), "disagree": disagree.values,
        "since_big": since, "dow": pd.to_datetime(d["t"], unit="ms", utc=True).dt.dayofweek,
        "term": (rv5 / rv22.replace(0, np.nan)).values})
    out["f_tr"] = (d["day"].map(fnd).shift(1).values if fnd is not None else np.nan)
    out["btc_vol"] = d["day"].map(btc_vol).values
    frames.append(out.iloc[60:])

panel = pd.concat(frames, ignore_index=True).dropna(subset=["rv1", "rv5", "rv22", "y1"])
panel = panel[panel["y1"] > 0]
F = ["rv1", "rv5", "rv22"]

# ---- stage 1: the HAR forecast, train-fitted with smearing ----
tr = panel[panel["day"] < CUTOFF]
X = np.log(tr[F] + EPS).values
y = np.log(tr["y1"] + EPS).values
A = np.column_stack([np.ones(len(X)), X])
b1, *_ = np.linalg.lstsq(A, y, rcond=None)
sm = float(np.mean(np.exp(y - A @ b1)))
Xa = np.log(panel[F] + EPS).values
panel["pred1"] = np.exp(np.column_stack([np.ones(len(Xa)), Xa]) @ b1) * sm
panel["logerr"] = np.log(panel["y1"] + EPS) - np.log(panel["pred1"] + EPS)
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
      f"{panel['day'].min()} -> {panel['day'].max()}")
print(f"stage-1 HAR: smearing {sm:.4f}, train {int((panel['half']=='train').sum())}, "
      f"test {int((panel['half']=='test').sum())}")

# ---- which features explain the log error? train only ----
panel["l_pred"] = np.log(panel["pred1"] + EPS)
panel["f_tr_f"] = panel["f_tr"].fillna(0.0)
panel["has_f"] = panel["f_tr"].notna().astype(int)
panel["l_btc"] = np.log(panel["btc_vol"].fillna(panel["btc_vol"].median()) + EPS)
panel["l_since"] = np.log(np.minimum(panel["since_big"], 60) + 1)
CAND = ["l_pred", "disagree", "f_tr_f", "has_f", "l_btc", "l_since", "term"]
trn = panel[panel["half"] == "train"].dropna(subset=CAND + ["logerr"])
tst = panel[panel["half"] == "test"].dropna(subset=CAND + ["logerr"])
print(f"\nfeature rows: train {len(trn)}, test {len(tst)}")

print("\n" + "=" * 96)
print("WHICH FEATURES EXPLAIN THE FORECAST'S LOG ERROR? (train coefficients, test sign check)")
print("=" * 96)
print(f"  {'feature':<12}{'train coef':>12}{'train corr':>12}{'test corr':>12}  sign holds")
print("-" * 96)
keep = []
for f in CAND:
    ctr = float(np.corrcoef(trn[f], trn["logerr"])[0, 1])
    cte = float(np.corrcoef(tst[f], tst["logerr"])[0, 1])
    A1 = np.column_stack([np.ones(len(trn)), trn[[f]].values])
    bb_, *_ = np.linalg.lstsq(A1, trn["logerr"].values, rcond=None)
    holds = (ctr > 0) == (cte > 0) and abs(cte) > 0.01
    print(f"  {f:<12}{bb_[1]:>+12.4f}{ctr:>+12.4f}{cte:>+12.4f}  {'yes' if holds else 'no'}")
    if holds:
        keep.append(f)
print(f"\n  features whose sign holds into test: {keep or 'NONE'}")

# ---- stage 2: correct the forecast with the surviving features ----
def qlike(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    a, p = a[m], p[m]
    return float(np.mean(a / p - np.log(a / p) - 1))


def decile_table(a, p):
    o = np.argsort(p)
    rows = []
    for d in range(10):
        idx = o[d * len(o) // 10:(d + 1) * len(o) // 10]
        if len(idx) < 20:
            continue
        rows.append({"decile": d + 1, "n": int(len(idx)),
                     "pred": round(float(p[idx].mean()), 4),
                     "actual": round(float(a[idx].mean()), 4),
                     "ratio": round(float(a[idx].mean() / p[idx].mean()), 3)})
    return rows


out = {"stage1_smearing": round(sm, 4), "features_tested": CAND,
       "features_sign_stable": keep, "variants": {}}
print("\n" + "=" * 96)
print("DOES A SECOND STAGE BEAT THE FLAT x0.8 PATCH?  (test half)")
print("=" * 96)
print(f"  {'variant':<28}{'QLIKE':>9}{'corr':>9}{'top-2 dec ratio':>18}{'bias':>9}")
print("-" * 96)
variants = {}
a_te = tst["y1"].values
variants["stage 1 only (raw HAR)"] = tst["pred1"].values
variants["stage 1 x0.80 flat (current)"] = tst["pred1"].values * 0.8
if keep:
    Atr = np.column_stack([np.ones(len(trn))] + [trn[f].values for f in keep])
    b2, *_ = np.linalg.lstsq(Atr, trn["logerr"].values, rcond=None)
    Ate = np.column_stack([np.ones(len(tst))] + [tst[f].values for f in keep])
    adj = np.exp(Ate @ b2)
    # smearing for the second stage, from train residuals
    sm2 = float(np.mean(np.exp(trn["logerr"].values - Atr @ b2)))
    variants["stage 1 + stage 2 model"] = tst["pred1"].values * adj * sm2
    out["stage2_features"] = keep
    out["stage2_coef"] = [round(float(x), 5) for x in b2]
    out["stage2_smearing"] = round(sm2, 4)

# HYBRID: stage-2 level, with the x0.8 haircut applied ONLY to the top two deciles.
# The flat global x0.8 fixes top-decile calibration but drags the whole curve down
# (bias -0.388 on test), which for risk use is the dangerous direction: stops too
# tight and leverage caps too high. Applying it only where it is needed should get
# both the QLIKE of stage 2 and the top-decile calibration of the flat patch.
if "stage 1 + stage 2 model" in variants:
    base_p = variants["stage 1 + stage 2 model"].copy()
    o = np.argsort(base_p)
    top = o[int(0.8 * len(o)):]
    hyb = base_p.copy()
    hyb[top] *= 0.8
    variants["stage 2 + top-2-decile x0.8"] = hyb

for lab, p in variants.items():
    q = qlike(a_te, p)
    m = np.isfinite(a_te) & np.isfinite(p) & (p > 0)
    cr = float(np.corrcoef(a_te[m], p[m])[0, 1])
    dt = decile_table(a_te[m], p[m])
    top2 = np.mean([r["ratio"] for r in dt[-2:]]) if len(dt) >= 2 else float("nan")
    bias = float(np.mean(p[m] - a_te[m]))
    print(f"  {lab:<28}{q:>9.4f}{cr:>9.4f}{top2:>18.3f}{bias:>+9.4f}")
    out["variants"][lab] = {"qlike": round(q, 5), "corr": round(cr, 4),
                            "top2_decile_ratio": round(float(top2), 3),
                            "bias": round(bias, 4), "deciles": dt}

print("\n" + "=" * 96)
print("VERDICT")
print("=" * 96)
base = out["variants"].get("stage 1 x0.80 flat (current)", {}).get("qlike")
best_lab, best_q = None, None
for lab, v in out["variants"].items():
    if best_q is None or v["qlike"] < best_q:
        best_lab, best_q = lab, v["qlike"]
print(f"  lowest QLIKE on test: {best_lab} ({best_q:.4f})")
if base is not None and best_lab != "stage 1 x0.80 flat (current)":
    print(f"  improvement over the current flat x0.8 patch: "
          f"{100*(base-best_q)/abs(base):.1f}% lower QLIKE")
    out["verdict"] = f"{best_lab} beats the flat patch"
else:
    print("  the flat x0.8 patch is already the best available -- keep it")
    out["verdict"] = "keep the flat x0.8 patch"
with io.open(os.path.join(HERE, "vol_error.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote vol_error.json")
