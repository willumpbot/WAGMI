"""Squeeze v2 — is `disagree` anything more than a relabeled overbought/oversold dummy?

RETRACTION.md:105 found the consensus feature is "84% a relabeled extremity dummy", and that
controlling for extremity collapses its coefficient from 0.268 to 0.0245. The "Squeeze L/S" column is
LIVE in the owner's terminal and is driven by this feature, so it needs settling.

THE MECHANISM, which makes the confound structural rather than incidental. squeeze.py:85 is

    disagree = sum((fam[x] != netdir) for x in fam.columns)

and two of the six families vote 0 unless they are extreme:

    "rsi":  +1 if rsi > 70, -1 if rsi < 30, else 0
    "boll": +1 if bb  > 0.8, -1 if bb  < -0.8, else 0

netdir is +-1, so a NEUTRAL rsi (0) always satisfies `!= netdir` and is counted as DISAGREEING.
Therefore high `disagree` literally means "rsi and bollinger are mid-range", and low `disagree` means
"overbought or oversold". The feature is an extremity indicator wearing a consensus label. Any
"agreement predicts squeezes" story told with it is really "extremes predict squeezes".

Two fixes tested here:
  1. CONTROL for extremity explicitly (|rsi-50|/50 and |bb|) and ask whether `disagree` still adds
     anything to out-of-sample AUC.
  2. Replace it with an HONEST dissent measure -- among families that actually VOTED (non-zero),
     how many disagree with the net? Neutrality is abstention, not dissent.

Plus a permutation null: shuffle the dissent feature within each day and confirm the AUC gain
disappears. If a shuffled feature produces the same gain, the gain was never about dissent.
"""
import json, io, os, glob, math, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8
THRESH_MULT = 2.0
rng = np.random.default_rng(20261008)


def load(sym, iv):
    p = os.path.join(HIST, f"{sym}_{iv}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    for col in ("o", "h", "l", "c"):
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["t_ms"] = pd.to_numeric(df["t_ms"], errors="coerce")
    df = df.dropna(subset=["t_ms", "c"]).sort_values("t_ms").reset_index(drop=True)
    df["day"] = pd.to_datetime(df["t_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df if len(df) else None


syms = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
rows = []
for s in syms:
    d = load(s, "1d")
    if d is None or len(d) < 150:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    ret = c.pct_change() * 100
    rv1, rv5, rv22 = ret.abs(), ret.rolling(5).std(), ret.rolling(22).std()
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

    # the ORIGINAL feature: neutral votes are miscounted as dissent
    disagree = sum((fam[x] != netdir).astype(int) for x in fam.columns)
    # the HONEST feature: only families that actually voted can dissent
    active = (fam != 0)
    n_active = active.sum(axis=1)
    dissent_active = sum(((fam[x] != netdir) & (fam[x] != 0)).astype(int) for x in fam.columns)
    # EXPLICIT extremity controls -- what `disagree` is secretly measuring
    ext_rsi = (rsi - 50).abs() / 50.0
    ext_bb = bb.abs()

    out = pd.DataFrame({
        "sym": s, "day": d["day"], "rv1": rv1, "rv5": rv5, "rv22": rv22,
        "disagree": disagree.values, "dissent_active": dissent_active.values,
        "n_active": n_active.values, "ext_rsi": ext_rsi.values, "ext_bb": ext_bb.values,
        "netdir": netdir.values})
    out["adv_long"] = ((c - l.shift(-1)) / c * 100).clip(lower=0)
    out["adv_short"] = ((h.shift(-1) - c) / c * 100).clip(lower=0)
    rows.append(out.dropna(subset=["rv22", "adv_long", "adv_short", "ext_rsi", "ext_bb"]))

panel = pd.concat(rows, ignore_index=True)
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
      f"{panel['day'].min()} -> {panel['day'].max()}")

F = ["rv1", "rv5", "rv22"]
tr0 = panel[panel["half"] == "train"].dropna(subset=F + ["adv_long"])
ytr = np.log(tr0["adv_long"].clip(lower=0.01) + EPS).values
A = np.column_stack([np.ones(len(tr0)), np.log(tr0[F] + EPS).values])
beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
sm = float(np.mean(np.exp(ytr - A @ beta)))
Xa = np.column_stack([np.ones(len(panel)), np.log(panel[F] + EPS).values])
panel["fcast"] = np.exp(Xa @ beta) * sm
panel["lfc"] = np.log(panel["fcast"] + EPS)
panel["thresh"] = THRESH_MULT * panel["fcast"]
panel["sq_long"] = (panel["adv_long"] > panel["thresh"]).astype(int)
panel["sq_short"] = (panel["adv_short"] > panel["thresh"]).astype(int)


def logistic(X, y, iters=300):
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (y - p) / len(y)
        hh = (X * (p * (1 - p))[:, None]).T @ X / len(y) + 1e-6 * np.eye(X.shape[1])
        try:
            w = w + np.linalg.solve(hh, g)
        except np.linalg.LinAlgError:
            break
    return w


def predict(w, X):
    X = np.column_stack([np.ones(len(X)), X])
    return 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))


def auc(y, p):
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), float)
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


out = {"rows": int(len(panel)), "coins": int(panel["sym"].nunique()),
       "cutoff": CUTOFF, "threshold_mult": THRESH_MULT}

# ---------------- 1. show the confound directly ----------------
print("\n" + "=" * 100)
print("THE CONFOUND — what is `disagree` actually made of?")
print("=" * 100)
cc = panel[["disagree", "dissent_active", "n_active", "ext_rsi", "ext_bb"]].corr()
print(cc.round(3).to_string())
r_na = float(cc.loc["disagree", "n_active"])
print(f"\n  corr(disagree, n_active)      = {r_na:+.3f}   <- how many families bothered to vote")
print(f"  corr(disagree, ext_rsi)       = {float(cc.loc['disagree','ext_rsi']):+.3f}")
print(f"  corr(disagree, ext_bb)        = {float(cc.loc['disagree','ext_bb']):+.3f}")
print(f"  corr(disagree, dissent_active)= {float(cc.loc['disagree','dissent_active']):+.3f}"
      f"   <- it IS related to real dissent too; the AUC test below is what decides")
print(f"\n  R^2 of disagree on [n_active, ext_rsi, ext_bb]:", end=" ")
Xc = np.column_stack([np.ones(len(panel)), panel[["n_active", "ext_rsi", "ext_bb"]].values])
bc, *_ = np.linalg.lstsq(Xc, panel["disagree"].values, rcond=None)
res = panel["disagree"].values - Xc @ bc
r2 = 1 - res.var() / panel["disagree"].values.var()
print(f"{r2:.4f}")
out["confound"] = {"corr_disagree_n_active": round(r_na, 4),
                   "corr_disagree_dissent_active": round(float(cc.loc['disagree','dissent_active']), 4),
                   "r2_disagree_on_extremity_and_activity": round(float(r2), 4)}
print(f"  => {100*r2:.1f}% of `disagree` is explained by vote-activity and extremity alone.")

# ---------------- 2. does it add anything once extremity is controlled? ----------------
SETS = {
    "forecast only":                 ["lfc"],
    "+ disagree (ORIGINAL)":         ["lfc", "disagree"],
    "+ extremity":                   ["lfc", "ext_rsi", "ext_bb", "n_active"],
    "+ extremity + disagree":        ["lfc", "ext_rsi", "ext_bb", "n_active", "disagree"],
    "+ extremity + TRUE dissent":    ["lfc", "ext_rsi", "ext_bb", "n_active", "dissent_active"],
}
out["sides"] = {}
for side in ("long", "short"):
    tgt = f"sq_{side}"
    tr = panel[panel["half"] == "train"].dropna(subset=["lfc", tgt])
    te = panel[panel["half"] == "test"].dropna(subset=["lfc", tgt])
    print("\n" + "=" * 100)
    print(f"{side.upper()} — P(adverse move > {THRESH_MULT}x forecast in 1 day), "
          f"train {len(tr)} / test {len(te)}")
    print(f"  base rate: train {tr[tgt].mean()*100:.1f}%  test {te[tgt].mean()*100:.1f}%")
    print("=" * 100)
    print(f"  {'features':<30}{'test AUC':>10}{'vs forecast-only':>19}{'vs +extremity':>16}")
    print("-" * 100)
    aucs = {}
    for name, feats in SETS.items():
        w = logistic(tr[feats].values, tr[tgt].values)
        a = auc(te[tgt].values, predict(w, te[feats].values))
        aucs[name] = a
        d0 = a - aucs["forecast only"]
        de = (a - aucs["+ extremity"]) if "+ extremity" in aucs else float("nan")
        print(f"  {name:<30}{a:>10.4f}{d0:>+19.4f}"
              f"{(f'{de:+.4f}' if not math.isnan(de) else ''):>16}")
    out["sides"][side] = {k: round(v, 4) for k, v in aucs.items()}
    gain = aucs["+ extremity + disagree"] - aucs["+ extremity"]
    out["sides"][side]["disagree_gain_over_extremity"] = round(gain, 4)

    # ---------------- 3. permutation null on the dissent feature ----------------
    feats = ["lfc", "ext_rsi", "ext_bb", "n_active", "disagree"]
    null = []
    for _ in range(200):
        trs, tes = tr.copy(), te.copy()
        trs["disagree"] = rng.permutation(trs["disagree"].values)
        tes["disagree"] = rng.permutation(tes["disagree"].values)
        w = logistic(trs[feats].values, trs[tgt].values)
        null.append(auc(tes[tgt].values, predict(w, tes[feats].values)) - aucs["+ extremity"])
    null = np.array(null)
    p = float((null >= gain).mean())
    print(f"\n  PERMUTATION NULL (200 shuffles of `disagree`, extremity kept):")
    print(f"    real gain over +extremity : {gain:+.4f}")
    print(f"    shuffled gain, mean       : {null.mean():+.4f}  "
          f"[{np.percentile(null,2.5):+.4f},{np.percentile(null,97.5):+.4f}]")
    print(f"    p(shuffled >= real)       : {p:.3f}   "
          f"{'=> ADDS NOTHING' if p > 0.05 else '=> survives'}")
    out["sides"][side]["perm_p"] = round(p, 4)
    out["sides"][side]["perm_null_mean"] = round(float(null.mean()), 4)

print("\n" + "=" * 100)
print("VERDICT")
print("=" * 100)
surv = [s for s in ("long", "short") if out["sides"][s]["perm_p"] <= 0.05]
for s in ("long", "short"):
    d = out["sides"][s]
    print(f"  {s:<6} disagree gain over extremity {d['disagree_gain_over_extremity']:+.4f}, "
          f"permutation p {d['perm_p']:.3f}")
if not surv:
    print("\n  `disagree` adds NOTHING to the squeeze model once extremity and vote-activity are")
    print("  controlled, on either side. The 'Squeeze L/S' column should drop the consensus term")
    print("  or be relabelled as what it is: an overbought/oversold indicator.")
    out["verdict"] = "disagree adds nothing once extremity is controlled"
else:
    print(f"\n  survives on: {surv}")
    out["verdict"] = f"survives on {surv}"
with io.open(os.path.join(HERE, "squeeze_v2.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote squeeze_v2.json")
