"""Walk-forward validation of the volatility forecaster.

VOLATILITY.md flagged its own weakness: a single train/test split at 2025-06-01.
A single split can be lucky. This refits the HAR model on an expanding window and
predicts the next block, repeatedly, across the whole history -- which is how the
model would actually have been used.

Also answers two questions left open there:
  * per-symbol coefficients vs one pooled fit
  * does the model degrade as the regime changes, or hold up?

Reported per fold: correlation, out-of-sample R^2, QLIKE, and the calibration
ratio of the top decile (the one that misbehaved in the single-split test).
"""
import json, io, os, glob, time, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
EPS = 1e-8
MIN_TRAIN = 1500          # rows before the first fold
FOLD_DAYS = 90            # predict 90 days forward, then refit


def load_daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    return df


def frame(sym):
    d = load_daily(sym)
    if d is None or len(d) < 120:
        return None
    ret = d["c"].pct_change() * 100
    f = pd.DataFrame({
        "day": pd.to_datetime(d["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"),
        "sym": sym,
        "rv1": ret.abs(), "rv5": ret.rolling(5).std(), "rv22": ret.rolling(22).std(),
        "y1": ret.shift(-1).abs(), "y5": ret.shift(-5).rolling(5).std(),
        "naive5": ret.rolling(5).std()})
    return f.dropna(subset=["rv1", "rv5", "rv22", "y5"])


syms = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
panel = pd.concat([x for x in (frame(s) for s in syms) if x is not None], ignore_index=True)
panel = panel[(panel["y5"] > 0) & (panel["naive5"] > 0)].sort_values("day").reset_index(drop=True)
print(f"panel {len(panel)} rows, {panel['sym'].nunique()} symbols, "
      f"{panel['day'].min()} -> {panel['day'].max()}")

F = ["rv1", "rv5", "rv22"]


def fit(sub, tgt):
    X = np.log(sub[F] + EPS).values
    y = np.log(sub[tgt] + EPS).values
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    sm = float(np.mean(np.exp(y - A @ b)))
    return b, sm


def pred(b, sm, sub):
    X = np.log(sub[F] + EPS).values
    return np.exp(np.column_stack([np.ones(len(X)), X]) @ b) * sm


def score(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    a, p = a[m], p[m]
    if len(a) < 50:
        return None
    return {"n": int(len(a)),
            "corr": round(float(np.corrcoef(a, p)[0, 1]), 4),
            "r2": round(float(1 - ((a - p) ** 2).sum() / ((a - a.mean()) ** 2).sum()), 4),
            "qlike": round(float(np.mean(a / p - np.log(a / p) - 1)), 4)}


days = sorted(panel["day"].unique())
start_i = max(MIN_TRAIN // max(panel["sym"].nunique(), 1), 120)
folds = []
i = start_i
while i + 1 < len(days):
    tr_days = set(days[:i])
    te_days = set(days[i:i + FOLD_DAYS])
    if len(te_days) < 20:
        break
    tr = panel[panel["day"].isin(tr_days)]
    te = panel[panel["day"].isin(te_days)]
    if len(tr) >= MIN_TRAIN and len(te) >= 100:
        folds.append((days[i], days[min(i + FOLD_DAYS, len(days)) - 1], tr, te))
    i += FOLD_DAYS

print(f"folds: {len(folds)}  (expanding train, {FOLD_DAYS}-day test blocks)")
print("\n" + "=" * 104)
print("WALK-FORWARD — y5 (next-5-day realised vol), model refit before each block")
print("=" * 104)
print(f"  {'test block':<26}{'n':>7}{'HAR corr':>10}{'HAR R2':>9}{'HAR QL':>9}"
      f"{'naive R2':>10}{'naive QL':>10}{'top-dec ratio':>14}")
print("-" * 104)

rows, wins = [], 0
for a, b_, tr, te in folds:
    beta, sm = fit(tr, "y5")
    p = pred(beta, sm, te)
    s_h = score(te["y5"], p)
    s_n = score(te["y5"], te["naive5"])
    if not s_h or not s_n:
        continue
    t = te.copy()
    t["pred"] = p
    t = t[(t["pred"] > 0) & np.isfinite(t["pred"])]
    try:
        t["dec"] = pd.qcut(t["pred"], 10, labels=False, duplicates="drop")
        top = t[t["dec"] == t["dec"].max()]
        ratio = float(top["y5"].mean() / top["pred"].mean())
    except Exception:
        ratio = float("nan")
    better = s_h["qlike"] < s_n["qlike"]
    wins += int(better)
    mark = "*" if better else " "
    print(f"  {a} -> {b_}{mark}{s_h['n']:>6}{s_h['corr']:>10.4f}{s_h['r2']:>9.4f}"
          f"{s_h['qlike']:>9.4f}{s_n['r2']:>10.4f}{s_n['qlike']:>10.4f}{ratio:>14.2f}")
    rows.append({"block": [a, b_], "har": s_h, "naive": s_n,
                 "top_decile_ratio": None if ratio != ratio else round(ratio, 3),
                 "har_beats_naive": bool(better)})

print("-" * 104)
if rows:
    hq = np.mean([r["har"]["qlike"] for r in rows])
    nq = np.mean([r["naive"]["qlike"] for r in rows])
    hr = np.mean([r["har"]["r2"] for r in rows])
    nr = np.mean([r["naive"]["r2"] for r in rows])
    hc = np.mean([r["har"]["corr"] for r in rows])
    print(f"  mean over {len(rows)} folds:  HAR QLIKE {hq:.4f} vs naive {nq:.4f}   "
          f"HAR R2 {hr:+.4f} vs naive {nr:+.4f}   HAR corr {hc:.4f}")
    print(f"  HAR beat naive in {wins}/{len(rows)} folds "
          f"({100*wins/len(rows):.0f}%)")
    pos = sum(1 for r in rows if r["har"]["r2"] > 0)
    print(f"  folds with positive HAR out-of-sample R2: {pos}/{len(rows)}")

# ---- pooled vs per-symbol coefficients, on the last fold ----
print("\n" + "=" * 104)
print("POOLED vs PER-SYMBOL coefficients (last fold)")
print("=" * 104)
per = {}
if folds:
    a, b_, tr, te = folds[-1]
    beta, sm = fit(tr, "y5")
    s_pool = score(te["y5"], pred(beta, sm, te))
    print(f"  pooled              n={s_pool['n']:>6}  corr {s_pool['corr']:.4f}  "
          f"R2 {s_pool['r2']:+.4f}  QLIKE {s_pool['qlike']:.4f}")
    preds, acts = [], []
    for sym in sorted(te["sym"].unique()):
        trs, tes = tr[tr["sym"] == sym], te[te["sym"] == sym]
        if len(trs) < 300 or len(tes) < 40:
            continue
        bb, ss = fit(trs, "y5")
        pp = pred(bb, ss, tes)
        s = score(tes["y5"], pp)
        if s:
            per[sym] = s
            preds.extend(pp); acts.extend(tes["y5"].values)
    if acts:
        s_per = score(acts, preds)
        print(f"  per-symbol pooled   n={s_per['n']:>6}  corr {s_per['corr']:.4f}  "
              f"R2 {s_per['r2']:+.4f}  QLIKE {s_per['qlike']:.4f}")
        verdict = ("per-symbol WINS" if s_per["qlike"] < s_pool["qlike"]
                   else "pooled WINS -- keep one set of coefficients")
        print(f"  => {verdict}")

out = {"folds": rows, "fold_days": FOLD_DAYS, "min_train": MIN_TRAIN,
       "n_folds": len(rows),
       "mean_har_qlike": round(float(np.mean([r["har"]["qlike"] for r in rows])), 4) if rows else None,
       "mean_naive_qlike": round(float(np.mean([r["naive"]["qlike"] for r in rows])), 4) if rows else None,
       "mean_har_r2": round(float(np.mean([r["har"]["r2"] for r in rows])), 4) if rows else None,
       "har_beats_naive_folds": f"{wins}/{len(rows)}" if rows else None,
       "per_symbol_last_fold": per}
with io.open(os.path.join(HERE, "walkforward_vol.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote walkforward_vol.json")
