"""Mission 9: safe-leverage and adverse-excursion tables.

For each coin, bucket days by FORECAST volatility decile, then measure how far
price actually went AGAINST a position opened that day, over 1 / 3 / 5 days,
separately for longs and shorts, walking 4h bars so the path is intraday rather
than close-to-close.

Then invert it into leverage. On Hyperliquid a position is liquidated when the
margin fraction falls to the maintenance level, so for leverage L:

    adverse tolerance  =  1/L  -  mm         (as a fraction of entry)
    => max safe L      =  1 / (adverse/100 + mm)

with mm = 1/(2 * maxLeverage) per coin, Hyperliquid's documented maintenance
fraction (half the initial margin at max leverage). Funding and fees are ignored
in the liquidation distance, which makes the answer slightly optimistic -- noted
in the output rather than hidden.

Honesty check that decides whether the table is usable: build it on TRAIN days
and ask whether the stated 95th/99th percentile actually covers that share of
TEST days. A table that claims 99% and delivers 90% is worse than no table.
"""
import json, io, os, glob, time, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8
HORIZONS = (1, 3, 5)
N_BUCKETS = 5          # quintiles: deciles leave too few days per coin


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


meta = {}
p = os.path.join(HERE, "hl_meta.json")
if os.path.exists(p):
    meta = json.load(io.open(p, encoding="utf-8"))
LEV = meta.get("leverage", {})
VOLM = meta.get("day_notional_volume", {})

syms = sorted({os.path.basename(x).split("_")[0] for x in glob.glob(os.path.join(HIST, "*_4h.csv"))})
print(f"symbols with 4h path data: {syms}")

# ---- vol forecast, fitted on TRAIN only (same HAR spec as VOLATILITY.md) ----
F = ["rv1", "rv5", "rv22"]
frames = []
for s in syms:
    d = load(s, "1d")
    if d is None or len(d) < 80:
        continue
    r = d["c"].pct_change() * 100
    f = pd.DataFrame({"day": pd.to_datetime(d["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"),
                      "sym": s, "rv1": r.abs(), "rv5": r.rolling(5).std(),
                      "rv22": r.rolling(22).std(), "y1": r.shift(-1).abs()})
    frames.append(f.dropna(subset=F))
vf = pd.concat(frames, ignore_index=True)
tr = vf[(vf["day"] < CUTOFF) & vf["y1"].notna()]
X = np.log(tr[F] + EPS).values
y = np.log(tr["y1"] + EPS).values
A = np.column_stack([np.ones(len(X)), X])
beta, *_ = np.linalg.lstsq(A, y, rcond=None)
sm = float(np.mean(np.exp(y - A @ beta)))
Xa = np.log(vf[F] + EPS).values
vf["fcast"] = np.exp(np.column_stack([np.ones(len(Xa)), Xa]) @ beta) * sm
print(f"vol model: {len(tr)} train rows, smearing {sm:.4f}")


def adverse_paths(sym):
    """Max adverse excursion % from each day's open, over 1/3/5 days, on 4h bars."""
    d4 = load(sym, "4h")
    d1 = load(sym, "1d")
    if d4 is None or d1 is None or len(d4) < 100:
        return None
    d4 = d4.copy()
    d4["day"] = pd.to_datetime(d4["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    days = sorted(d4["day"].unique())
    idx = {dd: i for i, dd in enumerate(days)}
    g = {dd: sub for dd, sub in d4.groupby("day")}
    rows = []
    for i, dd in enumerate(days):
        sub = g[dd]
        entry = float(sub.iloc[0]["o"])
        if entry <= 0:
            continue
        rec = {"sym": sym, "day": dd}
        ok = True
        for hz in HORIZONS:
            win = days[i:i + hz]
            if len(win) < hz:
                ok = False
                break
            chunk = pd.concat([g[w] for w in win])
            lo, hi = float(chunk["l"].min()), float(chunk["h"].max())
            # a long suffers on the way down, a short on the way up
            rec[f"adv_long_{hz}"] = max(0.0, (entry - lo) / entry * 100)
            rec[f"adv_short_{hz}"] = max(0.0, (hi - entry) / entry * 100)
        if ok:
            rows.append(rec)
    return pd.DataFrame(rows) if rows else None


parts = [x for x in (adverse_paths(s) for s in syms) if x is not None]
adv = pd.concat(parts, ignore_index=True)
adv = adv.merge(vf[["sym", "day", "fcast"]], on=["sym", "day"], how="inner").dropna(subset=["fcast"])
adv["half"] = np.where(adv["day"] < CUTOFF, "train", "test")
print(f"adverse-excursion rows: {len(adv)}  "
      f"({adv['sym'].nunique()} coins, {adv['day'].min()} -> {adv['day'].max()})")
print(adv.groupby("half").size().to_dict())

table, coverage = {}, []
print("\n" + "=" * 112)
print("SAFE LEVERAGE — adverse excursion by forecast-volatility quintile, and the leverage it allows")
print("  max L = 1 / (adverse%/100 + mm),  mm = 1/(2 x coin maxLeverage)   [funding and fees excluded]")
print("=" * 112)

for sym, g in adv.groupby("sym"):
    gtr = g[g["half"] == "train"]
    if len(gtr) < 150:
        continue
    maxlev = (LEV.get(sym) or {}).get("maxLeverage") or 0
    if not maxlev:
        continue
    mm = 1.0 / (2.0 * maxlev)
    edges = np.percentile(gtr["fcast"], np.linspace(0, 100, N_BUCKETS + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    g = g.copy()
    g["b"] = pd.cut(g["fcast"], bins=np.unique(edges), labels=False, include_lowest=True)
    print(f"\n  {sym}   maxLeverage {maxlev}x   mm {mm*100:.2f}%   "
          f"24h vol ${VOLM.get(sym, 0)/1e6:.0f}M   n={len(g)}")
    print(f"    {'quintile':<10}{'fcast%':>8}{'n tr':>6}{'n te':>6}"
          + "".join(f"{'p95_'+str(h)+'d':>10}{'p99_'+str(h)+'d':>10}" for h in HORIZONS)
          + f"{'maxL_long':>11}{'maxL_short':>11}")
    table[sym] = {"max_leverage": maxlev, "mm_fraction": round(mm, 5), "quintiles": {}}
    for b, gb in g.groupby("b"):
        btr, bte = gb[gb["half"] == "train"], gb[gb["half"] == "test"]
        if len(btr) < 25:
            continue
        rec = {"n_train": int(len(btr)), "n_test": int(len(bte)),
               "fcast_median": round(float(gb["fcast"].median()), 3), "horizons": {}}
        line = f"    Q{int(b)+1:<9}{gb['fcast'].median():>8.2f}{len(btr):>6}{len(bte):>6}"
        worst99 = 0.0
        for hz in HORIZONS:
            for side in ("long", "short"):
                col = f"adv_{side}_{hz}"
                p95 = float(np.percentile(btr[col], 95))
                p99 = float(np.percentile(btr[col], 99))
                rec["horizons"].setdefault(f"{hz}d", {})[side] = {
                    "p95": round(p95, 3), "p99": round(p99, 3)}
                if side == "long":
                    l95, l99 = p95, p99
                else:
                    s95, s99 = p95, p99
                worst99 = max(worst99, p99)
                # out-of-sample coverage of the train-built p95/p99
                if len(bte) >= 25:
                    coverage.append({"sym": sym, "q": int(b) + 1, "hz": hz, "side": side,
                                     "cov95": float((bte[col] <= p95).mean() * 100),
                                     "cov99": float((bte[col] <= p99).mean() * 100),
                                     "n_test": int(len(bte))})
            line += f"{(l95+s95)/2:>10.2f}{(l99+s99)/2:>10.2f}"
        # leverage sized to survive the 1-day 99th percentile
        a_long = rec["horizons"]["1d"]["long"]["p99"]
        a_short = rec["horizons"]["1d"]["short"]["p99"]
        maxL_long = 1.0 / (a_long / 100.0 + mm)
        maxL_short = 1.0 / (a_short / 100.0 + mm)
        rec["max_lev_long_1d_p99"] = round(min(maxL_long, maxlev), 2)
        rec["max_lev_short_1d_p99"] = round(min(maxL_short, maxlev), 2)
        line += f"{min(maxL_long, maxlev):>11.1f}{min(maxL_short, maxlev):>11.1f}"
        print(line)
        table[sym]["quintiles"][f"Q{int(b)+1}"] = rec

cov = pd.DataFrame(coverage)
print("\n" + "=" * 112)
print("OUT-OF-SAMPLE COVERAGE — does a table built on train actually hold on test?")
print("=" * 112)
if len(cov):
    print(f"  {'horizon':<10}{'side':<8}{'claimed':>10}{'actual p95 cov':>17}{'actual p99 cov':>17}{'cells':>8}")
    print("-" * 112)
    for (hz, side), gg in cov.groupby(["hz", "side"]):
        print(f"  {str(hz)+'d':<10}{side:<8}{'95 / 99':>10}"
              f"{gg['cov95'].mean():>16.1f}%{gg['cov99'].mean():>16.1f}%{len(gg):>8}")
    print(f"\n  overall: p95 covers {cov['cov95'].mean():.1f}% of test days "
          f"(claimed 95), p99 covers {cov['cov99'].mean():.1f}% (claimed 99)")
    under95 = (cov["cov95"] < 90).mean() * 100
    under99 = (cov["cov99"] < 95).mean() * 100
    print(f"  cells where the p95 bound held <90%% of the time: {under95:.0f}%")
    print(f"  cells where the p99 bound held <95%% of the time: {under99:.0f}%")
    verdict = ("USABLE — the bounds roughly hold out of sample"
               if cov["cov99"].mean() >= 96 and cov["cov95"].mean() >= 90
               else "NOT USABLE AS STATED — the bounds are optimistic out of sample")
    print(f"\n  VERDICT: {verdict}")
else:
    verdict = "no test cells"

out = {"built": time.time(), "schema": "safe_leverage_v1", "cutoff": CUTOFF,
       "n_buckets": N_BUCKETS, "horizons": [f"{h}d" for h in HORIZONS],
       "mm_rule": "mm = 1/(2*maxLeverage); funding and fees excluded from the liquidation distance",
       "leverage_rule": "max_lev = 1/(adverse_p99_1d/100 + mm), capped at the coin maxLeverage",
       "rows": int(len(adv)), "coins": list(table),
       "oos_coverage": {"p95_mean": round(float(cov["cov95"].mean()), 2) if len(cov) else None,
                        "p99_mean": round(float(cov["cov99"].mean()), 2) if len(cov) else None,
                        "verdict": verdict},
       "table": table}
with io.open(os.path.join(HERE, "safe_leverage.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote safe_leverage.json")
