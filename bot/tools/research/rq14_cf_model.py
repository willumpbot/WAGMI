"""RQ14: Counterfactual skip model — does anything beat confidence floors OOS?

Data: bot/data/llm/counterfactual_resolved.jsonl (resolved skips, would_hit_tp1 labels).
Split BY TIME: train created_at < 2026-06-15, test >= 2026-06-15. No leakage.
Baseline: raw confidence as score (the floors are monotone in confidence, so
confidence-as-ranker IS the floor policy's ranking). Contenders: logistic
regression + HistGradientBoosting on skip-time features only.
Evidence only. No deployment.
"""
import json, re, sys
from datetime import datetime, timezone
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import pandas as pd

PATH = r"C:\Users\vince\WAGMI\bot\data\llm\counterfactual_resolved.jsonl"
SPLIT = "2026-06-15"

def reason_class(sr: str) -> str:
    sr = sr or ""
    if sr.startswith("confidence_floor"): return "confidence_floor"
    if sr.startswith("trend_adj_floor"): return "trend_adj_floor"
    if sr == "graduated_rule_veto": return "grad_veto"
    if sr == "graduated_rule_veto_overridden": return "grad_veto_overridden"
    if sr.startswith("[MA]"): return "ma_regime"
    return "other"

def floor_level(sr: str):
    m = re.search(r"floor_(\d+)", sr or "")
    return float(m.group(1)) if m else np.nan

rows = []
with open(PATH, encoding="utf-8") as f:
    for line in f:
        try: r = json.loads(line)
        except json.JSONDecodeError: continue
        if not r.get("resolved"): continue
        ca = r.get("created_at", "")
        if not ca: continue
        dt = datetime.fromisoformat(ca)
        sr = str(r.get("skip_reason") or "")
        entry, sl, tp1 = r.get("entry_price"), r.get("sl"), r.get("tp1")
        rr = np.nan
        try:
            risk = abs(entry - sl); rew = abs(tp1 - entry)
            rr = rew / risk if risk > 0 else np.nan
        except Exception: pass
        rows.append(dict(
            date=ca[:10], dt=dt,
            symbol=r.get("symbol") or "UNK",
            side=r.get("side") or "UNK",
            hour=dt.hour,
            confidence=float(r.get("confidence") or np.nan),
            reason=reason_class(sr),
            floor=floor_level(sr),
            regime=str(r.get("regime") or "unknown") or "unknown",
            strategy=str(r.get("strategy") or "unknown"),
            rr=rr,
            entry=entry,
            y=1 if r.get("would_hit_tp1") else 0,
            y_sl=1 if r.get("would_hit_sl") else 0,
        ))
df = pd.DataFrame(rows)
df["conf_minus_floor"] = df["confidence"] - df["floor"]
df["conf_minus_floor"] = df["conf_minus_floor"].fillna(0.0)
df["floor"] = df["floor"].fillna(df["floor"].median())
df["rr"] = df["rr"].fillna(df["rr"].median())
df["regime"] = df["regime"].replace("", "unknown")

train = df[df["date"] < SPLIT].copy()
test = df[df["date"] >= SPLIT].copy()
print(f"total={len(df)} train={len(train)} (<{SPLIT}) test={len(test)}")
print(f"base TP1: train={train.y.mean():.4f} test={test.y.mean():.4f}")
print(f"train dates {train.date.min()}..{train.date.max()}, test {test.date.min()}..{test.date.max()}")

cat = ["symbol", "side", "reason", "regime", "strategy"]
num = ["confidence", "hour", "floor", "conf_minus_floor", "rr"]

pre = ColumnTransformer([
    ("cat", OneHotEncoder(handle_unknown="ignore"), cat),
    ("num", StandardScaler(), num),
])
logit = Pipeline([("pre", pre), ("m", LogisticRegression(max_iter=2000, C=1.0))])
logit.fit(train[cat + num], train["y"])
p_logit = logit.predict_proba(test[cat + num])[:, 1]

# GBM on raw (ordinal-encode cats)
tr_g = train.copy(); te_g = test.copy()
cat_maps = {}
for c in cat:
    cats = sorted(train[c].astype(str).unique())
    m = {v: i for i, v in enumerate(cats)}
    cat_maps[c] = m
    tr_g[c] = train[c].astype(str).map(m)
    te_g[c] = test[c].astype(str).map(m).fillna(-1)
gbm = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                     max_leaf_nodes=31, random_state=0,
                                     categorical_features=list(range(len(cat))))
gbm.fit(tr_g[cat + num], tr_g["y"])
p_gbm = gbm.predict_proba(te_g[cat + num])[:, 1]

y = test["y"].values
conf = test["confidence"].values

def auc(s):
    return roc_auc_score(y, s)

print("\n=== AUC (test, would_hit_tp1) ===")
print(f"confidence-only baseline: {auc(conf):.4f}")
print(f"logistic (all features):  {auc(p_logit):.4f}")
print(f"GBM (all features):       {auc(p_gbm):.4f}")

# logistic on confidence alone (calibration check, same AUC as raw)
lc = LogisticRegression(max_iter=1000).fit(train[["confidence"]], train["y"])
p_conf = lc.predict_proba(test[["confidence"]])[:, 1]
print(f"Brier: conf-logit={brier_score_loss(y, p_conf):.4f} logit={brier_score_loss(y, p_logit):.4f} gbm={brier_score_loss(y, p_gbm):.4f} base={brier_score_loss(y, np.full_like(p_conf, train.y.mean())):.4f}")

print("\n=== Precision at matched volume (test) — top-k by score ===")
for frac in (0.01, 0.02, 0.05, 0.10, 0.20):
    k = max(1, int(len(y) * frac))
    out = [f"k={k} ({frac:.0%}):"]
    for name, s in (("conf", conf), ("logit", p_logit), ("gbm", p_gbm)):
        idx = np.argsort(-s)[:k]
        out.append(f"{name}={y[idx].mean():.3f}")
    out.append(f"base={y.mean():.3f}")
    print(" ".join(out))

# what would the existing floor policy pass? all records here were skipped, so
# floor policy passes 0 of them. The comparable question: rank by confidence.
print("\n=== Per-era AUC stability (test split by week) ===")
test = test.assign(week=test["dt"].dt.strftime("%G-W%V"))
te_g = te_g.assign(week=test["week"].values)
for wk, g in test.groupby("week"):
    if len(g) < 200 or g.y.sum() < 10:
        print(f"{wk}: n={len(g)} tp1={g.y.sum()} (too small, skipped)"); continue
    m = test["week"] == wk
    print(f"{wk}: n={len(g)} base={g.y.mean():.3f} conf_auc={roc_auc_score(g.y, conf[m.values]):.3f} "
          f"gbm_auc={roc_auc_score(g.y, p_gbm[m.values]):.3f} logit_auc={roc_auc_score(g.y, p_logit[m.values]):.3f}")

# Adversarial: dedupe near-identical clustered signals (same symbol/side/hour bucket/entry ~0.2%)
test2 = test.copy()
test2["hb"] = test2["dt"].dt.strftime("%Y-%m-%d %H")
test2["eb"] = (np.log(test2["entry"].astype(float)) * 500).round()  # ~0.2% buckets
dd = test2.drop_duplicates(subset=["symbol", "side", "hb", "eb"])
mask = test2.index.isin(dd.index)
print(f"\n=== Deduped test (1 per symbol/side/hour/~0.2% entry bucket): n={mask.sum()} of {len(test2)} ===")
print(f"base={y[mask].mean():.3f} conf_auc={roc_auc_score(y[mask], conf[mask]):.4f} "
      f"logit_auc={roc_auc_score(y[mask], p_logit[mask]):.4f} gbm_auc={roc_auc_score(y[mask], p_gbm[mask]):.4f}")
for frac in (0.02, 0.05, 0.10):
    k = max(1, int(mask.sum() * frac))
    ysub, cs, gs = y[mask], conf[mask], p_gbm[mask]
    print(f"dedup top {frac:.0%} (k={k}): conf={ysub[np.argsort(-cs)[:k]].mean():.3f} gbm={ysub[np.argsort(-gs)[:k]].mean():.3f} base={ysub.mean():.3f}")

# Fragility: drop the best symbol for GBM in test
print("\n=== Fragility: per-symbol test AUC ===")
for s in sorted(test["symbol"].unique()):
    m = (test["symbol"] == s).values
    if y[m].sum() < 10: print(f"{s}: n={m.sum()} tp1={y[m].sum()} skipped"); continue
    print(f"{s}: n={m.sum()} base={y[m].mean():.3f} conf={roc_auc_score(y[m], conf[m]):.3f} gbm={roc_auc_score(y[m], p_gbm[m]):.3f}")

# GBM feature importance via permutation on a sample
from sklearn.inspection import permutation_importance
samp = te_g.sample(min(6000, len(te_g)), random_state=0)
r = permutation_importance(gbm, samp[cat + num], test.loc[samp.index, "y"],
                           n_repeats=5, random_state=0, scoring="roc_auc")
print("\n=== GBM permutation importance (AUC drop) ===")
for name, imp in sorted(zip(cat + num, r.importances_mean), key=lambda t: -t[1]):
    print(f"{name}: {imp:+.4f}")

# Confidence decile calibration on test
print("\n=== Test TP1 rate by confidence decile ===")
test["cq"] = pd.qcut(test["confidence"], 10, duplicates="drop")
print(test.groupby("cq", observed=True)["y"].agg(["count", "mean"]).to_string())
