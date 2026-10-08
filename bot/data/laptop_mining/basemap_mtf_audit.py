"""Audit of basemap_mtf.json: is "6 of 144 stable" better than chance, and is
VOLATILITY more stable across halves than RETURN?

Mission 5 concluded that size is predictable and direction is not. If that holds
here, the per-state volatility distribution should repeat across halves far more
often than the per-state return distribution. That decides what the desk should
headline.

Checks:
  1. the testable denominator -- how many states even have n>=30 in BOTH halves
  2. return stability vs a shuffled-label null (same states, labels permuted
     within symbol, so the state loses meaning but the sample shape is kept)
  3. volatility stability on the same footing
"""
import json, io, os, glob, time, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
MIN_N = 30
rng = np.random.default_rng(20261008)

import importlib.util
spec = importlib.util.spec_from_file_location("bm", os.path.join(HERE, "basemap_mtf.py"))

# rebuild the panel locally (cheaper than importing the whole script)
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
    return df


def di(h, l, c):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    return (pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr,
            mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr, tr)


rows = []
for sym in sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_4h.csv"))}):
    d1, d4 = load(sym, "1d"), load(sym, "4h")
    if d1 is None or d4 is None:
        continue
    c, h, l = d1["c"], d1["h"], d1["l"]
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    pdi, mdi, tr = di(h, l, c)
    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    pos = (c - lo20) / (hi20 - lo20).replace(0, np.nan)
    ds = pd.DataFrame({"t": d1["t"],
                       "structure": np.where(e20 > e50, "UP", "DOWN"),
                       "stretch": np.where(c > e20, "ABOVE", "BELOW"),
                       "range": np.where(pos < 1/3, "LOW", np.where(pos > 2/3, "HIGH", "MID")),
                       "driver": np.where(pdi > mdi, "BUYERS", "SELLERS")})
    ret1 = c.pct_change() * 100
    ds["r1"] = (c.shift(-1) / c - 1) * 100
    ds["vol5"] = ret1.shift(-5).rolling(5).std()
    ds = ds.iloc[50:].copy()
    c4, h4, l4 = d4["c"], d4["h"], d4["l"]
    f20, f50 = c4.ewm(span=20, adjust=False).mean(), c4.ewm(span=50, adjust=False).mean()
    p4, m4, _ = di(h4, l4, c4)
    hs = pd.DataFrame({"t": d4["t"],
                       "h4_structure": np.where(f20 > f50, "UP", "DOWN"),
                       "h4_stretch": np.where(c4 > f20, "ABOVE", "BELOW"),
                       "h4_driver": np.where(p4 > m4, "BUYERS", "SELLERS")}).iloc[50:]
    m = pd.merge_asof(ds.sort_values("t"), hs.sort_values("t"), on="t", direction="backward")
    m = m.dropna(subset=["h4_structure", "r1"])
    m["sym"] = sym
    m["day"] = pd.to_datetime(m["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    rows.append(m)

panel = pd.concat(rows, ignore_index=True)
KF = ["structure", "stretch", "range", "driver", "h4_structure", "h4_stretch", "h4_driver"]
panel["key"] = panel[KF].agg("|".join, axis=1)
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel {len(panel)} rows, {panel['key'].nunique()} states, "
      f"span {panel['day'].min()} -> {panel['day'].max()}")


def stability(df, col, sign_based=True, tol=15):
    """Count states testable in both halves and how many repeat."""
    testable = repeat = 0
    for key, g in df.groupby("key"):
        a, b = g[g["half"] == "train"][col].dropna(), g[g["half"] == "test"][col].dropna()
        if len(a) < MIN_N or len(b) < MIN_N:
            continue
        testable += 1
        if sign_based:
            ua, ub = (a > 0).mean() * 100, (b > 0).mean() * 100
            if np.sign(np.median(a)) == np.sign(np.median(b)) and abs(ua - ub) <= tol:
                repeat += 1
        else:
            # volatility: medians within 25% of each other (relative)
            ma, mb = np.median(a), np.median(b)
            if ma > 0 and mb > 0 and abs(ma - mb) / ((ma + mb) / 2) <= 0.25:
                repeat += 1
    return testable, repeat


print("\n" + "=" * 92)
print("1. TESTABLE DENOMINATOR and 2/3. STABILITY vs a SHUFFLED-LABEL NULL")
print("=" * 92)
t_r, s_r = stability(panel, "r1", sign_based=True)
t_v, s_v = stability(panel, "vol5", sign_based=False)
print(f"  states with n>=30 in BOTH halves : {t_r}  (of {panel['key'].nunique()} observed)")
print(f"  RETURN  direction repeats        : {s_r}/{t_r} = {100*s_r/max(t_r,1):.1f}%")
print(f"  VOLATILITY level repeats (+-25%) : {s_v}/{t_v} = {100*s_v/max(t_v,1):.1f}%")

# shuffled-label null: permute the state label within each symbol
NULL_ITERS = 40
nr, nv = [], []
for i in range(NULL_ITERS):
    sh = panel.copy()
    sh["key"] = sh.groupby("sym")["key"].transform(lambda s: rng.permutation(s.values))
    a, b = stability(sh, "r1", sign_based=True)
    nr.append(100 * b / max(a, 1))
    a2, b2 = stability(sh, "vol5", sign_based=False)
    nv.append(100 * b2 / max(a2, 1))
nr, nv = np.array(nr), np.array(nv)
print(f"\n  shuffled-label null, RETURN      : {nr.mean():.1f}%  "
      f"[{np.percentile(nr,2.5):.1f}, {np.percentile(nr,97.5):.1f}]")
print(f"  shuffled-label null, VOLATILITY  : {nv.mean():.1f}%  "
      f"[{np.percentile(nv,2.5):.1f}, {np.percentile(nv,97.5):.1f}]")

rv = 100 * s_r / max(t_r, 1)
vv = 100 * s_v / max(t_v, 1)
print("\n  VERDICT")
print(f"    return stability   {rv:.1f}% vs null {nr.mean():.1f}%  -> "
      + ("BEATS the null" if rv > np.percentile(nr, 97.5) else "INDISTINGUISHABLE from chance"))
print(f"    volatility stability {vv:.1f}% vs null {nv.mean():.1f}%  -> "
      + ("BEATS the null" if vv > np.percentile(nv, 97.5) else "INDISTINGUISHABLE from chance"))

out = {"panel_rows": int(len(panel)), "states_observed": int(panel["key"].nunique()),
       "states_testable_both_halves": int(t_r), "min_n_per_half": MIN_N,
       "return_repeat_pct": round(rv, 1), "vol_repeat_pct": round(vv, 1),
       "null_return_pct": {"mean": round(float(nr.mean()), 1),
                           "ci": [round(float(np.percentile(nr, 2.5)), 1),
                                  round(float(np.percentile(nr, 97.5)), 1)]},
       "null_vol_pct": {"mean": round(float(nv.mean()), 1),
                        "ci": [round(float(np.percentile(nv, 2.5)), 1),
                               round(float(np.percentile(nv, 97.5)), 1)]},
       "return_beats_null": bool(rv > np.percentile(nr, 97.5)),
       "vol_beats_null": bool(vv > np.percentile(nv, 97.5))}

# ---- 4. does the 4h overlay HELP or FRAGMENT? compare key granularities ----
print("\n" + "=" * 92)
print("4. GRANULARITY — does adding the 4h view help, or just fragment the sample?")
print("=" * 92)
GRAN = {
    "daily only (4 fields)": ["structure", "stretch", "range", "driver"],
    "daily + 4h structure (5)": ["structure", "stretch", "range", "driver", "h4_structure"],
    "daily + full 4h (7)": KF,
    "structure+driver only (2)": ["structure", "driver"],
}
print(f"  {'key':<28}{'states':>8}{'testable':>10}{'ret rep%':>10}{'null%':>8}{'vol rep%':>10}{'null%':>8}  verdict")
print("-" * 104)
gran_out = {}
for lab, fields in GRAN.items():
    d = panel.copy()
    d["key"] = d[fields].agg("|".join, axis=1)
    tr_, sr_ = stability(d, "r1", sign_based=True)
    tv_, sv_ = stability(d, "vol5", sign_based=False)
    rr = 100 * sr_ / max(tr_, 1); vr = 100 * sv_ / max(tv_, 1)
    nrs, nvs = [], []
    for _ in range(30):
        sh = d.copy()
        sh["key"] = sh.groupby("sym")["key"].transform(lambda x: rng.permutation(x.values))
        a, b = stability(sh, "r1", sign_based=True); nrs.append(100 * b / max(a, 1))
        a2, b2 = stability(sh, "vol5", sign_based=False); nvs.append(100 * b2 / max(a2, 1))
    nrs, nvs = np.array(nrs), np.array(nvs)
    beats = (rr > np.percentile(nrs, 97.5)) or (vr > np.percentile(nvs, 97.5))
    print(f"  {lab:<28}{d['key'].nunique():>8}{tr_:>10}{rr:>10.1f}{nrs.mean():>8.1f}"
          f"{vr:>10.1f}{nvs.mean():>8.1f}  {'BEATS null' if beats else 'chance'}")
    gran_out[lab] = {"states": int(d["key"].nunique()), "testable": int(tr_),
                     "ret_repeat_pct": round(rr, 1), "null_ret_pct": round(float(nrs.mean()), 1),
                     "vol_repeat_pct": round(vr, 1), "null_vol_pct": round(float(nvs.mean()), 1),
                     "beats_null": bool(beats)}
out["granularity"] = gran_out

# continuous check for contrast: ATR -> next-5d vol, per half
pv = panel[["atr_pct", "vol5", "half"]].dropna() if "atr_pct" in panel else None
print("\n  CONTRAST — the same information used CONTINUOUSLY instead of bucketed:")
if pv is not None and len(pv) > 200:
    for hh in ("train", "test"):
        g = pv[pv["half"] == hh]
        print(f"    corr(ATR%, next-5d vol) {hh}: {g['atr_pct'].corr(g['vol5']):+.3f}  n={len(g)}")
else:
    print("    (atr_pct not carried into this panel; see cooperation.json: +0.341 full / +0.353 test)")

with io.open(os.path.join(HERE, "basemap_mtf_audit.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote basemap_mtf_audit.json")
