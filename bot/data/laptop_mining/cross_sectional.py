"""Proposal B: does cross-sectional ranking work where time-series direction failed?

Every directional test in this project asked "will this coin go up?" and the
answer was no, roughly 80 times. This asks a genuinely different question:
**"will this coin go up MORE than the others today?"**

It is not a reframing. A long-short basket is market-neutral by construction, so
beta and the market's own drift cancel. That matters here because:
  * `always-long` was NOT significant over this period (+0.135%, CI [-0.043,+0.313])
  * the 2025 carry result turned out to be day-selection, not skill -- a
    cross-sectional test is immune to that failure mode by design

Method: each day, rank every coin by a voice, go long the top k and short the
bottom k in equal weight, hold 1 or 5 days, charge 9 bps per leg per side.
Train/test split, block bootstrap on day with the block matched to the horizon,
and a shuffled-rank null that keeps the basket structure but destroys the signal.
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
FEE_PCT = 0.09          # per leg, per side
K = 3                   # long top 3, short bottom 3
HOLDS = (1, 5)
EPS = 1e-8
rng = np.random.default_rng(20261008)
COINS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]


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


frames = []
for s in COINS:
    d = daily(s)
    if d is None or len(d) < 150:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    ret = c.pct_change() * 100
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    dd = c.diff()
    gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out = pd.DataFrame({"sym": s, "day": d["day"]})
    # ---- cross-sectional signals: each is a CONTINUOUS score, ranked across coins ----
    out["mom7"] = (c / c.shift(7) - 1) * 100
    out["mom30"] = (c / c.shift(30) - 1) * 100
    out["rev3"] = -(c / c.shift(3) - 1) * 100            # short-term reversal
    out["stretch"] = (c / e20 - 1) * 100
    out["trend"] = (e20 / e50 - 1) * 100
    out["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    out["bb"] = (c - ma20) / (2 * sd20).replace(0, np.nan)
    out["rangepos"] = (c - lo20) / (hi20 - lo20).replace(0, np.nan)
    out["vol22"] = -ret.rolling(22).std()                # low-vol preference
    for hz in HOLDS:
        out[f"fwd{hz}"] = (c.shift(-hz) / c - 1) * 100
    frames.append(out.iloc[60:])

panel = pd.concat(frames, ignore_index=True)
SIGNALS = ["mom7", "mom30", "rev3", "stretch", "trend", "rsi", "bb", "rangepos", "vol22"]
panel = panel.dropna(subset=["fwd1"])
# require a reasonable cross-section each day
counts = panel.groupby("day")["sym"].count()
good_days = set(counts[counts >= 2 * K + 1].index)
panel = panel[panel["day"].isin(good_days)]
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
      f"{panel['day'].nunique()} days with >= {2*K+1} coins")
print(f"span {panel['day'].min()} -> {panel['day'].max()}   "
      f"train {int((panel['half']=='train').sum())} / test {int((panel['half']=='test').sum())}")


def basket(df, sig, hz, shuffle=False):
    """Daily long-top-k / short-bottom-k return, net of fees. One row per day."""
    rows = []
    for day, g in df.groupby("day"):
        g = g.dropna(subset=[sig, f"fwd{hz}"])
        if len(g) < 2 * K + 1:
            continue
        v = g[sig].values.copy()
        if shuffle:
            rng.shuffle(v)
        order = np.argsort(v)
        f = g[f"fwd{hz}"].values
        shortm = f[order[:K]].mean()
        longm = f[order[-K:]].mean()
        # long + short legs, each in and out
        rows.append({"day": day, "r": (longm - shortm) - 4 * FEE_PCT})
    return pd.DataFrame(rows)


def boot(df, block, iters=2000):
    if not len(df):
        return None, None, None
    dt = pd.to_datetime(df["day"])
    key = ((dt - dt.min()).dt.days // max(1, block)).values
    groups = [df["r"].values[key == k] for k in np.unique(key)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 5:
        return float(df["r"].mean()), None, None
    point = float(df["r"].mean())
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


out = {"k": K, "fee_pct_per_leg_side": FEE_PCT, "cutoff": CUTOFF,
       "coins": sorted(panel["sym"].unique()), "signals": SIGNALS, "results": {}}
print("\n" + "=" * 104)
print(f"CROSS-SECTIONAL LONG-SHORT — long top {K}, short bottom {K}, net of 4 x {FEE_PCT}% fees")
print("=" * 104)
for hz in HOLDS:
    print(f"\n  hold {hz}d")
    print(f"    {'signal':<12}{'train %':>10}{'CI95':>20}{'test %':>10}{'CI95':>20}"
          f"{'null %':>9}{'verdict':>22}")
    print("    " + "-" * 98)
    for sig in SIGNALS:
        tr = basket(panel[panel["half"] == "train"], sig, hz)
        te = basket(panel[panel["half"] == "test"], sig, hz)
        if len(tr) < 20 or len(te) < 20:
            continue
        ptr, ltr, htr = boot(tr, hz)
        pte, lte, hte = boot(te, hz)
        if ptr is None or pte is None:
            continue
        nulls = [boot(basket(panel[panel["half"] == "test"], sig, hz, shuffle=True), hz)[0]
                 for _ in range(5)]
        nmean = float(np.mean([x for x in nulls if x is not None])) if nulls else float("nan")
        stable = (ptr > 0) == (pte > 0)
        sig_te = lte is not None and (lte > 0 or hte < 0)
        if sig_te and pte > 0 and stable:
            verdict = "EDGE: sig + stable"
        elif sig_te and pte > 0:
            verdict = "sig but sign flips"
        elif sig_te and pte < 0:
            verdict = "significantly NEGATIVE"
        else:
            verdict = "no edge"
        cit = f"[{ltr:+.3f},{htr:+.3f}]" if ltr is not None else ""
        cie = f"[{lte:+.3f},{hte:+.3f}]" if lte is not None else ""
        print(f"    {sig:<12}{ptr:>+10.3f}{cit:>20}{pte:>+10.3f}{cie:>20}"
              f"{nmean:>+9.3f}{verdict:>22}")
        out["results"][f"{sig}|{hz}d"] = {
            "train_pct": round(ptr, 4), "train_ci": [round(ltr, 4), round(htr, 4)] if ltr else None,
            "test_pct": round(pte, 4), "test_ci": [round(lte, 4), round(hte, 4)] if lte else None,
            "shuffled_null_pct": round(nmean, 4) if np.isfinite(nmean) else None,
            "sign_stable": bool(stable), "test_significant": bool(sig_te),
            "verdict": verdict}

winners = [k for k, v in out["results"].items() if v["verdict"] == "EDGE: sig + stable"]
print("\n" + "=" * 104)
print("VERDICT")
print("=" * 104)
if winners:
    for w in winners:
        v = out["results"][w]
        print(f"  {w}: train {v['train_pct']:+.3f}%  test {v['test_pct']:+.3f}% {v['test_ci']}  "
              f"null {v['shuffled_null_pct']:+.3f}%")
    out["verdict"] = f"{len(winners)} signal-horizon cell(s) significant and sign-stable"
else:
    print("  No cross-sectional signal is both significantly positive on test and sign-stable.")
    print("  Cross-sectional ranking fails the same way time-series direction did.")
    out["verdict"] = "no cross-sectional edge"
print(f"\n  cells tested: {len(out['results'])}  (expect ~{0.05*len(out['results']):.1f} "
      f"false positives at p<0.05)")
with io.open(os.path.join(HERE, "cross_sectional.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote cross_sectional.json")
