"""Mission 5: do the voices have value TOGETHER, even though none has it alone?

Panel: one row per (symbol, UTC day) from Hyperliquid daily candles, 2020-08 ->
2026-10, 10 symbols. Each voice is encoded -1 bear / 0 neutral / +1 bull so that
"agreement" is arithmetic rather than a judgement call.

Order of work, per the handoff:
  1 REDUNDANCY     correlation matrix -> collapse copies into independent families
  2 AGREEMENT      does forward return improve as k independent families agree?
  3 CONTRADICTION  when strong voices disagree, what follows? direction vs SIZE
  4 CONDITIONAL    does any voice work only inside a regime? (train/test gated)
  5 BOTTOM LINE    any combination with an OOS edge after 9 bps at 1-5 days?

House rules: train/test split, cluster-bootstrap CIs (clustered on DAY, since
all symbols move together), flag n<13, report the null, no lookahead.
"""
import json, io, os, glob, math, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_PCT = 0.09              # 9 bps round trip, in percent
CUTOFF = "2025-06-01"
rng = np.random.default_rng(20261008)

HORIZONS = (1, 3, 5)


# ---------------------------------------------------------------- panel build
def load_daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    df = df.rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c", "v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    # drop a still-forming final candle
    import time as _t
    if len(df) and df["t"].iloc[-1] + 86_400_000 > _t.time() * 1000:
        df = df.iloc[:-1]
    return df


def load_funding(sym):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if not os.path.exists(p):
        return None
    f = pd.read_csv(p)
    if not len(f):
        return None
    f["day"] = pd.to_datetime(f["t_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return f.groupby("day")["rate"].mean()


def voices_for(sym, df, btc_struct):
    c, h, l = df["c"], df["h"], df["l"]
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_safe = atr.replace(0, np.nan)
    pdi = pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr_safe
    mdi = mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr_safe
    dx = ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()

    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    pos = (c - lo20) / (hi20 - lo20).replace(0, np.nan)

    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bb = (c - ma20) / (2 * sd20).replace(0, np.nan)      # +1 = at upper band

    atr_pct = atr / c * 100
    vol_exp = atr_pct / atr_pct.rolling(50).mean().replace(0, np.nan)

    out = pd.DataFrame({"t": df["t"], "c": c})
    out["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    out["sym"] = sym

    # ---- voices, each in {-1, 0, +1} ----
    out["v_structure"] = np.where(ema20 > ema50, 1, -1)
    out["v_stretch"] = np.where(c > ema20, 1, -1)
    out["v_range20"] = np.where(pos > 2 / 3, 1, np.where(pos < 1 / 3, -1, 0))
    out["v_driver"] = np.where(pdi > mdi, 1, -1)
    out["v_rsi"] = np.where(rsi > 70, 1, np.where(rsi < 30, -1, 0))
    out["v_bollinger"] = np.where(bb > 0.8, 1, np.where(bb < -0.8, -1, 0))
    out["v_mom7"] = np.sign(c / c.shift(7) - 1).fillna(0)
    out["v_mom30"] = np.sign(c / c.shift(30) - 1).fillna(0)
    out["v_btc"] = out["day"].map(btc_struct).fillna(0)

    # ---- conditioners (not directional) ----
    out["adx"] = adx
    out["vol_exp"] = vol_exp
    out["atr_pct"] = atr_pct
    out["weekday"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.dayofweek

    # ---- outcomes (no lookahead: shift(-hz) is strictly future) ----
    for hz in HORIZONS:
        out[f"r{hz}"] = (c.shift(-hz) / c - 1) * 100
    ret1 = c.pct_change() * 100
    out["fwd_vol5"] = ret1.shift(-5).rolling(5).std()      # std of the NEXT 5 daily returns
    out["fwd_absr1"] = out["r1"].abs()

    out["valid"] = np.arange(len(df)) >= 60                # EMA50 + rolling(50) warm-up
    return out


syms = sorted({os.path.basename(p).split("_")[0]
               for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
print(f"symbols: {syms}")

btc = load_daily("BTC")
bs = btc["c"].ewm(span=20, adjust=False).mean() > btc["c"].ewm(span=50, adjust=False).mean()
btc_struct = pd.Series(np.where(bs, 1, -1),
                       index=pd.to_datetime(btc["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"))
btc_struct = btc_struct[~btc_struct.index.duplicated()]

frames = []
for s in syms:
    df = load_daily(s)
    if df is None or len(df) < 120:
        continue
    v = voices_for(s, df, btc_struct)
    fund = load_funding(s)
    v["v_funding"] = (-np.sign(v["day"].map(fund)).fillna(0)
                      if fund is not None else 0.0)        # crowded long = bearish prior
    frames.append(v)

panel = pd.concat(frames, ignore_index=True)
panel = panel[panel["valid"]].copy()
panel = panel.dropna(subset=["r1"])
VOICES = [c for c in panel.columns if c.startswith("v_")]
print(f"panel rows: {len(panel)}  span {panel['day'].min()} -> {panel['day'].max()}")
print(f"voices ({len(VOICES)}): {[v[2:] for v in VOICES]}")
print(f"funding coverage: {(panel['v_funding'] != 0).mean()*100:.1f}% of rows")

train = panel[panel["day"] < CUTOFF].copy()
test = panel[panel["day"] >= CUTOFF].copy()
print(f"train {len(train)} (<{CUTOFF})   test {len(test)} (>={CUTOFF})")

report = {"panel_rows": int(len(panel)), "span": [panel["day"].min(), panel["day"].max()],
          "symbols": syms, "voices": [v[2:] for v in VOICES], "cutoff": CUTOFF,
          "fee_pct": FEE_PCT, "train_rows": int(len(train)), "test_rows": int(len(test))}


# ------------------------------------------------- cluster bootstrap on DAY
def boot_mean(df, col, iters=2000, block=1):
    """Bootstrap the mean of `col` with a BLOCK cluster bootstrap.

    Clusters are contiguous `block`-day calendar blocks, so two dependencies are
    handled at once: all symbols move together on a given day (cross-sectional),
    and an h-day forward window overlaps the next h-1 days (serial). For a
    horizon of h days, pass block=h -- otherwise the CI is far too narrow. The
    first version of this script used block=1 for every horizon, which inflated
    the significance of every 3d and 5d cell.
    """
    sub = df[["day", col]].dropna()
    if not len(sub):
        return None, None, None
    d = pd.to_datetime(sub["day"])
    origin = d.min()
    key = ((d - origin).dt.days // max(1, block)).values
    groups = [sub[col].values[key == k] for k in np.unique(key)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 5:
        return float(sub[col].mean()), None, None
    point = float(sub[col].mean())
    idx = rng.integers(0, len(groups), size=(iters, len(groups)))
    means = np.empty(iters)
    for i in range(iters):
        means[i] = np.concatenate([groups[j] for j in idx[i]]).mean()
    means.sort()
    return point, float(means[int(.025 * iters)]), float(means[int(.975 * iters)])


# ============================================================ 1. REDUNDANCY
print("\n" + "=" * 104)
print("1. REDUNDANCY — correlation between voices (Pearson on the -1/0/+1 encoding)")
print("=" * 104)
corr = panel[VOICES].astype(float).corr()
names = [v[2:] for v in VOICES]
print("      " + "".join(f"{n[:7]:>9}" for n in names))
for i, v in enumerate(VOICES):
    print(f"  {names[i][:9]:<10}" + "".join(
        f"{corr.iloc[i, j]:>9.2f}" if i != j else f"{'-':>9}" for j in range(len(VOICES))))

THRESH = 0.70
parent = {v: v for v in VOICES}


def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


for i, a in enumerate(VOICES):
    for b in VOICES[i + 1:]:
        if abs(corr.loc[a, b]) >= THRESH:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
fams = collections.defaultdict(list)
for v in VOICES:
    fams[find(v)].append(v)
families = {f"fam_{i+1}": sorted(m) for i, (_, m) in enumerate(sorted(fams.items()))}
print(f"\n  families at |r| >= {THRESH}:")
for fam, members in families.items():
    print(f"    {fam}: {[m[2:] for m in members]}")
print(f"  => {len(VOICES)} voices collapse to {len(families)} independent families")

# independence weight: 1/family size, so copies cannot double-count
weights = {}
for fam, members in families.items():
    for m in members:
        weights[m[2:]] = round(1.0 / len(members), 4)
report["redundancy"] = {
    "threshold": THRESH,
    "families": {k: [m[2:] for m in v] for k, v in families.items()},
    "n_families": len(families),
    "corr": {names[i]: {names[j]: round(float(corr.iloc[i, j]), 3)
                        for j in range(len(names))} for i in range(len(names))},
}

# family representative = the member most correlated with the others in its family
reps = {}
for fam, members in families.items():
    if len(members) == 1:
        reps[fam] = members[0]
    else:
        sub = corr.loc[members, members].abs().sum(axis=1)
        reps[fam] = str(sub.idxmax())
print(f"  representatives: {[(f, reps[f][2:]) for f in families]}")


# ============================================================ 2. AGREEMENT
print("\n" + "=" * 104)
print("2. AGREEMENT — does forward return improve as independent families agree?")
print("   net = sum of one representative per family, each in {-1,0,+1}")
print("=" * 104)
repcols = [reps[f] for f in families]
for d in (panel, train, test):
    d["net"] = d[repcols].astype(float).sum(axis=1)
    d["netdir"] = np.sign(d["net"])
    d["k"] = d["net"].abs()

# directional return: return in the direction the panel points, minus fees
for d in (panel, train, test):
    for hz in HORIZONS:
        d[f"e{hz}"] = d["netdir"] * d[f"r{hz}"] - FEE_PCT

print(f"  {'k (|net|)':<12}{'n':>7}{'n_days':>8}{'e1 %':>9}{'CI95 e1':>20}{'e5 %':>9}{'CI95 e5':>20}")
print("-" * 104)
agree_rows = {}
maxk = int(panel["k"].max())
for k in range(1, maxk + 1):   # k=0 => netdir 0 => no trade, not a fee loss
    sub = panel[panel["k"] == k]
    if len(sub) < 13:
        if len(sub):
            print(f"  {k:<12}{len(sub):>7}{sub['day'].nunique():>8}   n<13 insufficient")
        continue
    p1, l1, h1 = boot_mean(sub, "e1", block=1)
    p5, l5, h5 = boot_mean(sub, "e5", block=5)
    c1 = f"[{l1:>7.3f},{h1:>7.3f}]" if l1 is not None else ""
    c5 = f"[{l5:>7.3f},{h5:>7.3f}]" if l5 is not None else ""
    s1 = "*" if (l1 is not None and (h1 < 0 or l1 > 0)) else " "
    s5 = "*" if (l5 is not None and (h5 < 0 or l5 > 0)) else " "
    print(f"  {k:<12}{len(sub):>7}{sub['day'].nunique():>8}{p1:>8.3f}{s1}{c1:>20}{p5:>8.3f}{s5}{c5:>20}")
    agree_rows[k] = {"n": int(len(sub)), "n_days": int(sub["day"].nunique()),
                     "e1": round(p1, 4), "e1_ci": [round(l1, 4), round(h1, 4)] if l1 is not None else None,
                     "e5": round(p5, 4), "e5_ci": [round(l5, 4), round(h5, 4)] if l5 is not None else None}

ks = sorted(agree_rows)
if len(ks) >= 3:
    e1s = [agree_rows[k]["e1"] for k in ks]
    rho = float(pd.Series(ks).corr(pd.Series(e1s), method="spearman"))
    shape = "MONOTONIC (more agreement helps)" if rho > 0.6 else \
            ("INVERTED (more agreement hurts)" if rho < -0.6 else "FLAT / no relationship")
    print(f"\n  rho(k, e1) = {rho:+.3f}  =>  {shape}")
    report["agreement"] = {"by_k": agree_rows, "rho_k_vs_e1": round(rho, 4), "shape": shape}

# train/test on the strongest-agreement bucket
hi_k = max(ks) if ks else 0
if hi_k:
    tr_sub, te_sub = train[train["k"] >= hi_k - 1], test[test["k"] >= hi_k - 1]
    print(f"\n  high agreement (k>={hi_k-1}) train/test:")
    for lab, sub in (("train", tr_sub), ("test", te_sub)):
        if len(sub) >= 13:
            for hz, blk in ((1, 1), (5, 5)):
                p, lo, hi = boot_mean(sub, f"e{hz}", block=blk)
                ci = f"[{lo:+.3f},{hi:+.3f}]" if lo is not None else ""
                sg = "*" if (lo is not None and (hi < 0 or lo > 0)) else " "
                print(f"    {lab:<6} n={len(sub):>6}  e{hz} {p:+.3f}%{sg} {ci}")


# ======================================================== 3. CONTRADICTION
print("\n" + "=" * 104)
print("3. CONTRADICTION — when strong voices disagree: direction vs SIZE of move")
print("=" * 104)
panel["contra"] = (panel["v_structure"] != panel["v_driver"]).astype(int)
print(f"  {'slice':<24}{'n':>7}{'e1 %':>9}{'|r1| %':>9}{'CI95 |r1|':>20}{'fwd_vol5':>10}")
print("-" * 104)
contra = {}
for lab, sub in (("structure == driver", panel[panel["contra"] == 0]),
                 ("structure != driver", panel[panel["contra"] == 1])):
    pe, _, _ = boot_mean(sub, "e1")
    pa, la, ha = boot_mean(sub, "fwd_absr1", block=1)
    pv, _, _ = boot_mean(sub, "fwd_vol5", block=5)
    ca = f"[{la:>7.3f},{ha:>7.3f}]" if la is not None else ""
    print(f"  {lab:<24}{len(sub):>7}{pe:>9.3f}{pa:>9.3f}{ca:>20}{pv:>10.3f}")
    contra[lab] = {"n": int(len(sub)), "e1": round(pe, 4),
                   "abs_r1": round(pa, 4), "fwd_vol5": round(pv, 4)}
# also: does disagreement COUNT predict size?
panel["disagree_n"] = sum((panel[c] != panel["netdir"]).astype(int) for c in repcols)
print("\n  by number of families disagreeing with the net direction:")
for dn in sorted(panel["disagree_n"].unique()):
    sub = panel[panel["disagree_n"] == dn]
    if len(sub) < 13:
        continue
    pa, la, ha = boot_mean(sub, "fwd_absr1")
    pe, _, _ = boot_mean(sub, "e1")
    print(f"    disagree={dn}  n={len(sub):>6}  |r1| {pa:>6.3f}%  "
          f"[{la:>6.3f},{ha:>6.3f}]   e1 {pe:+.3f}%")
report["contradiction"] = contra


# ====================================================== 4. CONDITIONAL TRUST
print("\n" + "=" * 104)
print("4. CONDITIONAL TRUST — does a voice work only inside a regime? (train must hold in test)")
print("=" * 104)
print(f"  {'voice x regime':<34}{'train e1':>10}{'test e1':>10}{'test CI95':>22}  verdict")
print("-" * 104)
cond = {}
REGIMES = {
    "adx>25": lambda d: d["adx"] > 25,
    "adx<=25": lambda d: d["adx"] <= 25,
    "vol_expanding": lambda d: d["vol_exp"] > 1.1,
    "vol_quiet": lambda d: d["vol_exp"] < 0.9,
}
for v in VOICES:
    for rname, rfn in REGIMES.items():
        for d in (train, test):
            d["_e"] = d[v].astype(float).replace(0, np.nan) * 0
        tr = train[rfn(train) & (train[v] != 0)].copy()
        te = test[rfn(test) & (test[v] != 0)].copy()
        if len(tr) < 100 or len(te) < 100:
            continue
        tr["ev"] = np.sign(tr[v]) * tr["r1"] - FEE_PCT
        te["ev"] = np.sign(te[v]) * te["r1"] - FEE_PCT
        ptr, _, _ = boot_mean(tr, "ev")
        pte, lte, hte = boot_mean(te, "ev")
        if ptr is None or pte is None:
            continue
        holds = (lte is not None and ((lte > 0 and ptr > 0) or (hte < 0 and ptr < 0)))
        if abs(ptr) < 0.05 and not holds:
            continue
        ci = f"[{lte:+.3f},{hte:+.3f}]" if lte is not None else ""
        verdict = "HOLDS (OOS CI excludes 0, same sign)" if holds else \
                  ("sign flips" if ptr * pte < 0 else "not confirmed")
        print(f"  {v[2:]+' x '+rname:<34}{ptr:>+10.3f}{pte:>+10.3f}{ci:>22}  {verdict}")
        cond[f"{v[2:]}|{rname}"] = {"train_e1": round(ptr, 4), "test_e1": round(pte, 4),
                                    "test_ci": [round(lte, 4), round(hte, 4)] if lte is not None else None,
                                    "holds": bool(holds), "n_train": int(len(tr)), "n_test": int(len(te))}
survivors = [k for k, v in cond.items() if v["holds"]]
print(f"\n  survived train AND test: {survivors or 'NONE'}")
report["conditional"] = cond
report["conditional_survivors"] = survivors


# ========================================================== 5. BOTTOM LINE
print("\n" + "=" * 104)
print("5. BOTTOM LINE — is there any out-of-sample edge after fees?")
print("=" * 104)
bl = {}
for lab, sub in (("always-long (null)", panel), ("panel net direction", panel)):
    pass
nullp, nulll, nullh = boot_mean(panel.assign(x=panel["r1"] - FEE_PCT), "x")
print(f"  always-long null        e1 {nullp:+.4f}%  [{nulll:+.4f},{nullh:+.4f}]")
for hz in HORIZONS:
    p, lo, hi = boot_mean(test, f"e{hz}", block=hz)
    if p is None:
        continue
    sig = "*" if (lo is not None and (hi < 0 or lo > 0)) else " "
    print(f"  TEST net-direction e{hz}  {p:+.4f}%{sig} [{lo:+.4f},{hi:+.4f}]  n={test[f'e{hz}'].notna().sum()}")
    bl[f"test_e{hz}"] = {"mean": round(p, 4), "ci": [round(lo, 4), round(hi, 4)],
                         "significant": bool(hi < 0 or lo > 0)}
# what IS predictable: vol persistence
pv = panel[["atr_pct", "fwd_vol5"]].dropna()
if len(pv) > 100:
    r = float(pv["atr_pct"].corr(pv["fwd_vol5"]))
    pvt = test[["atr_pct", "fwd_vol5"]].dropna()
    rt = float(pvt["atr_pct"].corr(pvt["fwd_vol5"])) if len(pvt) > 100 else float("nan")
    print(f"\n  predictability of SIZE, not direction:")
    print(f"    corr(today ATR%, next-5d realised vol) = {r:+.3f} full, {rt:+.3f} on test")
    bl["vol_persistence_corr_full"] = round(r, 4)
    bl["vol_persistence_corr_test"] = round(rt, 4)
    dcorr = float(panel[["v_structure", "r1"]].dropna().corr().iloc[0, 1])
    print(f"    corr(structure voice, next-1d return)  = {dcorr:+.3f}  <- direction, for contrast")
    bl["direction_corr"] = round(dcorr, 4)
report["bottom_line"] = bl

with io.open(os.path.join(HERE, "cooperation.json"), "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
with io.open(os.path.join(HERE, "voice_families.json"), "w", encoding="utf-8") as fh:
    json.dump({"threshold": THRESH, "n_voices": len(VOICES), "n_families": len(families),
               "families": {k: [m[2:] for m in v] for k, v in families.items()},
               "representatives": {k: reps[k][2:] for k in families},
               "independence_weight": weights,
               "note": "weight = 1/family size; multiply a voice's vote by this so "
                       "correlated copies cannot double-count in a consensus score."},
              fh, indent=1)
print("\nwrote cooperation.json + voice_families.json")
