"""Squeeze predictor: how likely is a violent move AGAINST the position?

The synthesis of everything that actually validated:
  VOLATILITY.md     next-day move size is forecastable (22/22 walk-forward folds)
  FUNDING_CARRY.md  funding is 99.3% persistent, and high funding precedes fatter
                    tails (p99 adverse 21.6% -> 29.0%)
  COOPERATION.md    near-unanimity precedes a ~55% larger move

None of those is directional. Together they should predict the TAIL -- the part a
leveraged trader actually gets hurt by. A liquidation is a tail event, so a
calibrated tail probability is worth more than a point forecast.

Target: P(adverse excursion > threshold within the next day), separately for
longs and shorts, with the threshold set per coin as a multiple of its own
forecast move so it means the same thing across coins.

Model: logistic regression, fitted on train only, validated out of sample on
(a) AUC, (b) calibration -- does a predicted 20% actually happen 20% of the time?
Baseline to beat: the unconditional base rate, and the vol forecast alone.
"""
import json, io, os, glob, time, math, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8
THRESH_MULT = 2.0      # "squeeze" = adverse move > 2x the forecast move
rng = np.random.default_rng(20261008)


def load(sym, iv):
    p = os.path.join(HIST, f"{sym}_{iv}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    bar = {"1d": 86_400_000, "4h": 14_400_000}[iv]
    if len(df) and df["t"].iloc[-1] + bar > time.time() * 1000:
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


syms = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
rows = []
for s in syms:
    d = load(s, "1d")
    if d is None or len(d) < 150:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    ret = c.pct_change() * 100
    rv1, rv5, rv22 = ret.abs(), ret.rolling(5).std(), ret.rolling(22).std()
    # consensus families (one representative each, per voice_families.json)
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bb = (c - ma20) / (2 * sd20).replace(0, np.nan)
    dd = c.diff()
    gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    fam = pd.DataFrame({
        "structure": np.where(e20 > e50, 1, -1),
        "stretch": np.where(c > e20, 1, -1),
        "rsi": np.where(rsi > 70, 1, np.where(rsi < 30, -1, 0)),
        "boll": np.where(bb > 0.8, 1, np.where(bb < -0.8, -1, 0)),
        "mom7": np.sign(c / c.shift(7) - 1).fillna(0),
        "mom30": np.sign(c / c.shift(30) - 1).fillna(0)})
    netdir = np.sign(fam.sum(axis=1))
    disagree = sum((fam[x] != netdir).astype(int) for x in fam.columns)

    fnd = funding(s)
    f_tr = d["day"].map(fnd).shift(1) if fnd is not None else pd.Series(np.nan, index=d.index)

    out = pd.DataFrame({"sym": s, "day": d["day"], "rv1": rv1, "rv5": rv5, "rv22": rv22,
                        "disagree": disagree.values, "f_tr": f_tr.values,
                        "netdir": netdir.values})
    # adverse excursion over the next day, from today's close
    out["adv_long"] = ((c - l.shift(-1)) / c * 100).clip(lower=0)
    out["adv_short"] = ((h.shift(-1) - c) / c * 100).clip(lower=0)
    rows.append(out.dropna(subset=["rv22", "adv_long", "adv_short"]))

panel = pd.concat(rows, ignore_index=True)
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
      f"{panel['day'].min()} -> {panel['day'].max()}")
print(f"funding present on {panel['f_tr'].notna().mean()*100:.1f}% of rows")

# ---- vol forecast, train-fitted (same spec as VOLATILITY.md) ----
F = ["rv1", "rv5", "rv22"]
tr = panel[panel["half"] == "train"].dropna(subset=F + ["adv_long"])
ytr = np.log(tr["adv_long"].clip(lower=0.01) + EPS).values
A = np.column_stack([np.ones(len(tr)), np.log(tr[F] + EPS).values])
beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
sm = float(np.mean(np.exp(ytr - A @ beta)))
Xa = np.column_stack([np.ones(len(panel)), np.log(panel[F] + EPS).values])
panel["fcast"] = np.exp(Xa @ beta) * sm
print(f"forecast fitted on {len(tr)} train rows, smearing {sm:.4f}")

panel["thresh"] = THRESH_MULT * panel["fcast"]
panel["sq_long"] = (panel["adv_long"] > panel["thresh"]).astype(int)
panel["sq_short"] = (panel["adv_short"] > panel["thresh"]).astype(int)
panel["f_tr_f"] = panel["f_tr"].fillna(0.0)
panel["has_f"] = panel["f_tr"].notna().astype(int)


def logistic(X, y, iters=300, lr=0.5):
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (y - p) / len(y)
        h = (X * (p * (1 - p))[:, None]).T @ X / len(y) + 1e-6 * np.eye(X.shape[1])
        try:
            w = w + np.linalg.solve(h, g)
        except np.linalg.LinAlgError:
            w = w + lr * g
    return w


def predict(w, X):
    X = np.column_stack([np.ones(len(X)), X])
    return 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))


def auc(y, p):
    y = np.asarray(y); p = np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), float)
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


FEATSETS = {
    "forecast only": ["lfc"],
    "+ funding": ["lfc", "f_tr_f", "has_f"],
    "+ consensus": ["lfc", "disagree"],
    "all three": ["lfc", "f_tr_f", "has_f", "disagree"],
}
panel["lfc"] = np.log(panel["fcast"] + EPS)

print("\n" + "=" * 100)
print(f"SQUEEZE PREDICTOR — P(adverse move > {THRESH_MULT}x forecast within 1 day)")
print("=" * 100)
report = {"threshold_mult": THRESH_MULT, "rows": int(len(panel)),
          "coins": int(panel["sym"].nunique()), "cutoff": CUTOFF, "sides": {}}

for side in ("long", "short"):
    tgt = f"sq_{side}"
    tr = panel[panel["half"] == "train"].dropna(subset=["lfc", tgt])
    te = panel[panel["half"] == "test"].dropna(subset=["lfc", tgt])
    base_tr = float(tr[tgt].mean() * 100)
    base_te = float(te[tgt].mean() * 100)
    print(f"\n  {side.upper()} side — base rate: train {base_tr:.1f}%  test {base_te:.1f}%")
    print(f"    {'features':<18}{'test AUC':>10}{'lift top decile':>18}{'calib slope':>13}")
    print("    " + "-" * 66)
    report["sides"][side] = {"base_rate_train": round(base_tr, 2),
                             "base_rate_test": round(base_te, 2), "models": {}}
    for lab, feats in FEATSETS.items():
        w = logistic(tr[feats].values, tr[tgt].values)
        p = predict(w, te[feats].values)
        a = auc(te[tgt].values, p)
        t = te.copy(); t["p"] = p
        try:
            t["d"] = pd.qcut(t["p"], 10, labels=False, duplicates="drop")
            top = t[t["d"] == t["d"].max()]
            lift = float(top[tgt].mean() * 100)
            # calibration slope: actual vs predicted across deciles
            cal = t.groupby("d").agg(pred=("p", "mean"), act=(tgt, "mean"))
            slope = float(np.polyfit(cal["pred"], cal["act"], 1)[0])
        except Exception:
            lift, slope = float("nan"), float("nan")
        print(f"    {lab:<18}{a:>10.4f}{lift:>17.1f}%{slope:>13.2f}")
        report["sides"][side]["models"][lab] = {
            "test_auc": round(a, 4), "top_decile_rate_pct": round(lift, 2),
            "calibration_slope": round(slope, 3),
            "coef": [round(float(x), 4) for x in w], "features": feats}

    # calibration table for the best model
    best_lab = max(report["sides"][side]["models"],
                   key=lambda k: report["sides"][side]["models"][k]["test_auc"])
    feats = FEATSETS[best_lab]
    w = logistic(tr[feats].values, tr[tgt].values)
    t = te.copy(); t["p"] = predict(w, te[feats].values)
    t["d"] = pd.qcut(t["p"], 10, labels=False, duplicates="drop")
    print(f"\n    calibration of '{best_lab}' on test:")
    print(f"      {'decile':<8}{'n':>7}{'predicted':>11}{'actual':>9}")
    cal = []
    for dd, g in t.groupby("d"):
        print(f"      {int(dd)+1:<8}{len(g):>7}{g['p'].mean()*100:>10.1f}%{g[tgt].mean()*100:>8.1f}%")
        cal.append({"decile": int(dd) + 1, "n": int(len(g)),
                    "pred_pct": round(float(g["p"].mean() * 100), 2),
                    "actual_pct": round(float(g[tgt].mean() * 100), 2)})
    report["sides"][side]["best_model"] = best_lab
    report["sides"][side]["calibration_test"] = cal

print("\n" + "=" * 100)
print("WHAT THE FEATURES SAY (sign of the coefficient on the 'all three' model)")
print("=" * 100)
for side in ("long", "short"):
    m = report["sides"][side]["models"]["all three"]
    names = ["intercept"] + m["features"]
    print(f"  {side:<6} " + "  ".join(f"{n}={c:+.3f}" for n, c in zip(names, m["coef"])))
print("\n  positive on f_tr_f  => higher funding raises squeeze risk")
print("  negative on disagree => MORE agreement raises squeeze risk (matches COOPERATION.md)")

with io.open(os.path.join(HERE, "squeeze.json"), "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
print("\nwrote squeeze.json")
