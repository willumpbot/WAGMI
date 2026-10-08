"""Does the best stop width depend on forecast volatility?

Joins the only two surviving findings:
  GEOMETRY.md    the bot's stop/target costs -0.431R; widening recovers it to ~0
  VOLATILITY.md  next-5d vol is forecastable OOS (corr 0.375, calibrated 2.1x spread)

If the optimal multiplier is the same in every volatility regime, a single global
number is correct and there is nothing to add. If it shifts, then an ADAPTIVE
stop -- wider when the forecast is hot, tighter when it is calm -- beats the
global one, and that is a new piece the hivemind can own.

Tested properly: the vol model is fitted on TRAIN days only and applied forward,
the geometry cell is chosen on TRAIN, and the comparison that counts is the
paired difference on TEST (same signals, different stop rule).
"""
import json, io, os, csv, gzip, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
HIST = os.path.join(HERE, "history")
FEE_BPS = 9.0
HORIZON_H = 48
CUTOFF = "2026-04-16"          # same split as sweep_oos.py
EPS = 1e-8
rng = np.random.default_rng(20261008)

STOP_MULTS = (1.0, 2.0, 4.0, 6.0, 8.0, 12.0)
TP_MULTS = (0.5, 1.0, 1.5)
DEFAULT = "1.0|1.5"


# ---------------------------------------------------------------- vol forecast
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
    return df


def vol_frame(sym):
    d = daily(sym)
    if d is None or len(d) < 80:
        return None
    ret = d["c"].pct_change() * 100
    f = pd.DataFrame({
        "day": pd.to_datetime(d["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"),
        "rv1": ret.abs(), "rv5": ret.rolling(5).std(), "rv22": ret.rolling(22).std(),
        "y5": ret.shift(-5).rolling(5).std()})
    f["sym"] = sym
    return f.dropna(subset=["rv1", "rv5", "rv22"])


syms_hist = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
vf = pd.concat([x for x in (vol_frame(s) for s in syms_hist) if x is not None], ignore_index=True)

# fit HAR on TRAIN days only, with the smearing correction from VOLATILITY.md
tr = vf[(vf["day"] < CUTOFF) & vf["y5"].notna()]
X = np.log(tr[["rv1", "rv5", "rv22"]] + EPS).values
y = np.log(tr["y5"] + EPS).values
A = np.column_stack([np.ones(len(X)), X])
beta, *_ = np.linalg.lstsq(A, y, rcond=None)
sm = float(np.mean(np.exp(y - A @ beta)))
Xa = np.log(vf[["rv1", "rv5", "rv22"]] + EPS).values
vf["volhat"] = np.exp(np.column_stack([np.ones(len(Xa)), Xa]) @ beta) * sm
print(f"vol model fitted on {len(tr)} train days, smearing {sm:.4f}")
volmap = {(r.sym, r.day): r.volhat for r in vf.itertuples()}

# volatility terciles, cut on TRAIN only so the buckets are not peeked
trv = vf[vf["day"] < CUTOFF]["volhat"].dropna()
q33, q67 = float(np.percentile(trv, 33)), float(np.percentile(trv, 67))
print(f"train vol terciles: calm < {q33:.3f} <= normal < {q67:.3f} <= hot")


# ---------------------------------------------------------------- simulate
def load_candles(sym):
    for d in (MERGED, HL):
        p = os.path.join(d, f"{sym}_1h.csv")
        if os.path.exists(p):
            out = []
            with io.open(p, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                                    float(r["l"]), float(r["c"])))
                    except (TypeError, ValueError):
                        continue
            out.sort()
            return out
    return None


def ib(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


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
        day = d["ts"][:10]
        vh = volmap.get((d["sym"], day))
        if vh is None or not np.isfinite(vh):
            continue
        sigs.append({"sym": d["sym"], "side": d["side"], "sl": d["sl"],
                     "t0": t0, "day": day, "volhat": float(vh)})
print(f"signals with a vol forecast: {len(sigs)}")

cache = {}
recs = []
for s in sigs:
    if s["sym"] not in cache:
        cache[s["sym"]] = load_candles(s["sym"])
    c = cache[s["sym"]]
    if not c:
        continue
    i0 = ib(c, s["t0"])
    if i0 is None or s["t0"] - c[i0][0] > 7200:
        continue
    entry = c[i0][4]
    base = abs(entry - s["sl"])
    if entry <= 0 or base <= 0:
        continue
    long_ = s["side"] == "LONG"
    bars = []
    k, end = i0 + 1, s["t0"] + HORIZON_H * 3600
    while k < len(c) and c[k][0] <= end:
        bars.append(c[k]); k += 1
    if not bars:
        continue
    cells = {}
    for smult in STOP_MULTS:
        dist = smult * base
        sl = entry - dist if long_ else entry + dist
        feeR = 2 * (FEE_BPS / 1e4) * entry / dist
        for tm in TP_MULTS:
            tp = entry + tm * dist if long_ else entry - tm * dist
            r = None
            for (_, o, h, l, cl) in bars:
                hit_sl = (l <= sl) if long_ else (h >= sl)
                hit_tp = (h >= tp) if long_ else (l <= tp)
                if hit_sl:
                    r = -1.0; break
                if hit_tp:
                    r = tm; break
            if r is None:
                last = bars[-1][4]
                r = ((last - entry) if long_ else (entry - last)) / dist
            cells[f"{smult}|{tm}"] = r - feeR
    bucket = "calm" if s["volhat"] < q33 else ("normal" if s["volhat"] < q67 else "hot")
    recs.append({"sym": s["sym"], "day": s["day"], "bucket": bucket,
                 "volhat": s["volhat"], "cells": cells})

print(f"simulated {len(recs)} signals")
df = pd.DataFrame(recs)
df["half"] = np.where(df["day"] < CUTOFF, "train", "test")
print(df.groupby(["bucket", "half"]).size().unstack(fill_value=0))

CELLS = [f"{s}|{t}" for s in STOP_MULTS for t in TP_MULTS]


def mean_cell(sub, key):
    v = [r[key] for r in sub["cells"] if key in r]
    return float(np.mean(v)) if v else None


def boot_pair(sub, a, b, iters=2500):
    cl = collections.defaultdict(list)
    for _, row in sub.iterrows():
        cc = row["cells"]
        if a in cc and b in cc:
            cl[(row["sym"], row["day"])].append(cc[a] - cc[b])
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    allv = [x for k in keys for x in cl[k]]
    point = float(np.mean(allv))
    ds = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        ds[i] = np.mean([x for j in pick for x in cl[keys[j]]])
    ds.sort()
    return point, float(ds[int(.025 * iters)]), float(ds[int(.975 * iters)])


print("\n" + "=" * 100)
print("1. BEST GEOMETRY PER VOLATILITY BUCKET (chosen on TRAIN only)")
print("=" * 100)
print(f"  {'bucket':<10}{'n train':>9}{'best cell':>14}{'train R':>10}{'default R':>11}")
print("-" * 100)
picks = {}
for b in ("calm", "normal", "hot"):
    sub = df[(df["bucket"] == b) & (df["half"] == "train")]
    if len(sub) < 100:
        print(f"  {b:<10}{len(sub):>9}  too few train rows")
        continue
    scored = [(mean_cell(sub, c), c) for c in CELLS]
    scored = [(v, c) for v, c in scored if v is not None]
    scored.sort(reverse=True)
    picks[b] = scored[0][1]
    print(f"  {b:<10}{len(sub):>9}{scored[0][1]:>14}{scored[0][0]:>10.4f}"
          f"{mean_cell(sub, DEFAULT):>11.4f}")

glob_sub = df[df["half"] == "train"]
gscored = sorted(((mean_cell(glob_sub, c), c) for c in CELLS), reverse=True)
gpick = gscored[0][1]
print(f"\n  global best on train (no conditioning): {gpick}  ({gscored[0][0]:+.4f}R)")

print("\n" + "=" * 100)
print("2. ON TEST — does conditioning on volatility beat one global stop rule?")
print("=" * 100)
te = df[df["half"] == "test"].copy()
te["adaptive"] = [r["cells"].get(picks.get(b, gpick)) for r, b in zip(te["cells"], te["bucket"])]
te["globalr"] = [r["cells"].get(gpick) for r in te["cells"]]
te["defaultr"] = [r["cells"].get(DEFAULT) for r in te["cells"]]
sub = te.dropna(subset=["adaptive", "globalr", "defaultr"])
print(f"  test n = {len(sub)}")
for lab, col in (("bot default", "defaultr"), ("global best", "globalr"), ("adaptive", "adaptive")):
    print(f"    {lab:<14} mean {sub[col].mean():+.4f}R")


def boot_col_diff(sub, a, b, iters=2500):
    cl = collections.defaultdict(list)
    for _, r in sub.iterrows():
        cl[(r["sym"], r["day"])].append(r[a] - r[b])
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    point = float(np.mean([x for k in keys for x in cl[k]]))
    ds = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        ds[i] = np.mean([x for j in pick for x in cl[keys[j]]])
    ds.sort()
    return point, float(ds[int(.025 * iters)]), float(ds[int(.975 * iters)])


print("\n  paired differences on test:")
out = {"picks_per_bucket": picks, "global_pick": gpick, "test_n": int(len(sub)),
       "terciles": {"q33": round(q33, 4), "q67": round(q67, 4)},
       "test_means": {k: round(float(sub[c].mean()), 4) for k, c in
                      (("default", "defaultr"), ("global", "globalr"), ("adaptive", "adaptive"))}}
for a, b, lab in (("adaptive", "defaultr", "adaptive - bot default"),
                  ("globalr", "defaultr", "global best - bot default"),
                  ("adaptive", "globalr", "adaptive - global best")):
    p, lo, hi = boot_col_diff(sub, a, b)
    if p is None:
        continue
    verdict = "CI excludes 0" if (lo > 0 or hi < 0) else "CI spans 0"
    print(f"    {lab:<28}{p:+.4f}R  [{lo:+.4f},{hi:+.4f}]  {verdict}")
    out[lab.replace(" ", "_")] = {"diff_R": round(p, 4), "ci": [round(lo, 4), round(hi, 4)],
                                  "significant": bool(lo > 0 or hi < 0)}

print("\n" + "=" * 100)
print("3. HOW THE SURFACE SHIFTS WITH VOLATILITY (full sample, tp fixed at 1.0R)")
print("=" * 100)
print(f"  {'bucket':<10}" + "".join(f"{'x'+str(s):>10}" for s in STOP_MULTS))
print("-" * 100)
for b in ("calm", "normal", "hot"):
    sub2 = df[df["bucket"] == b]
    if not len(sub2):
        continue
    row = f"  {b:<10}"
    for s in STOP_MULTS:
        v = mean_cell(sub2, f"{s}|1.0")
        row += f"{v:>10.4f}" if v is not None else f"{'n/a':>10}"
    print(row)
out["surface_by_bucket"] = {b: {f"{s}|1.0": (round(mean_cell(df[df['bucket'] == b], f"{s}|1.0"), 4)
                                             if mean_cell(df[df['bucket'] == b], f"{s}|1.0") is not None else None)
                                for s in STOP_MULTS} for b in ("calm", "normal", "hot")}

with io.open(os.path.join(HERE, "adaptive_geometry.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote adaptive_geometry.json")
