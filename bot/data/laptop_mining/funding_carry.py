"""Mission 10: is funding carry on Hyperliquid a real edge after costs?

Positive funding means longs pay shorts, so the carry trade is: short the perp
when trailing funding is high, hedge the price risk with a long in a correlated
major, and collect the funding.

Three questions, answered in order:
  1 PERSISTENCE   if funding was high over the last 24h, does it stay high?
  2 PnL           what would the trade have earned net of fees, slippage and
                  HEDGE DRIFT -- the residual price move between the two legs,
                  which is the part that usually eats this strategy
  3 TAIL          what happens during squeezes in high-funding regimes

Costs are charged explicitly, not assumed away:
  taker fee 4.5 bps per side, 2 legs, in and out  =  18 bps round trip
  slippage  2.0 bps per side, 2 legs, in and out  =   8 bps round trip
  total                                              26 bps per round trip
Hedge drift is measured from actual prices, never modelled.

House rules: train/test split, cluster bootstrap on day, flag n<13, report the
null, say plainly if there is no edge.
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
FEE_BPS_RT = 26.0          # both legs, in and out, incl. slippage
HEDGE = "BTC"
rng = np.random.default_rng(20261008)


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
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df


def load_funding(sym):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if not os.path.exists(p) or os.path.getsize(p) < 500:
        return None
    f = pd.read_csv(p)
    if not len(f):
        return None
    f["rate"] = pd.to_numeric(f["rate"], errors="coerce")
    f = f.dropna(subset=["rate"])
    f["day"] = pd.to_datetime(f["t_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    # hourly rates -> daily funding in PERCENT
    g = f.groupby("day")["rate"].sum().mul(100).rename("fund_pct")
    return g


syms = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(HIST, "*_funding.csv"))})
print(f"coins with funding history: {len(syms)}")

hedge_px = load_daily(HEDGE)
if hedge_px is None:
    raise SystemExit("no hedge price data")
hmap = hedge_px.set_index("day")["c"].to_dict()

rows = []
for s in syms:
    fd = load_funding(s)
    px = load_daily(s)
    if fd is None or px is None or len(px) < 120:
        continue
    d = px[["day", "c", "h", "l"]].merge(fd, left_on="day", right_index=True, how="inner")
    if len(d) < 120:
        continue
    d = d.sort_values("day").reset_index(drop=True)
    d["sym"] = s
    # trailing funding (yesterday and the 3 days before), strictly past
    d["f_tr1"] = d["fund_pct"].shift(1)
    d["f_tr3"] = d["fund_pct"].shift(1).rolling(3).sum()
    # forward funding a short would COLLECT (positive funding = longs pay shorts)
    d["f_fwd1"] = d["fund_pct"]
    d["f_fwd3"] = d["fund_pct"].rolling(3).sum().shift(-2)
    # price legs
    d["ret1"] = d["c"].pct_change().shift(-1) * 100
    d["ret3"] = (d["c"].shift(-3) / d["c"] - 1) * 100
    d["hedge"] = d["day"].map(hmap)
    d["hret1"] = (d["day"].map(hmap).shift(-1) / d["day"].map(hmap) - 1) * 100
    d["hret3"] = (d["day"].map(hmap).shift(-3) / d["day"].map(hmap) - 1) * 100
    # worst upside excursion while short, next 1 and 3 days (squeeze risk)
    d["sq1"] = (d["h"].shift(-1) / d["c"] - 1) * 100
    d["sq3"] = (pd.concat([d["h"].shift(-i) for i in (1, 2, 3)], axis=1).max(axis=1) / d["c"] - 1) * 100
    rows.append(d)

panel = pd.concat(rows, ignore_index=True).dropna(subset=["f_tr1", "fund_pct"])
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"panel: {len(panel)} coin-days, {panel['sym'].nunique()} coins, "
      f"{panel['day'].min()} -> {panel['day'].max()}")
print(panel.groupby("half").size().to_dict())

report = {"coins": int(panel["sym"].nunique()), "rows": int(len(panel)),
          "span": [panel["day"].min(), panel["day"].max()],
          "fee_bps_round_trip": FEE_BPS_RT, "hedge": HEDGE, "cutoff": CUTOFF}


def boot(v, days, iters=2000):
    cl = collections.defaultdict(list)
    for x, d in zip(v, days):
        if np.isfinite(x):
            cl[d].append(x)
    keys = list(cl)
    if len(keys) < 5:
        return None, None, None
    point = float(np.mean([x for k in keys for x in cl[k]]))
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        ms[i] = np.mean([x for j in pick for x in cl[keys[j]]])
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


# =============================================== 1. PERSISTENCE
print("\n" + "=" * 104)
print("1. PERSISTENCE — if funding was high yesterday, does it stay high?")
print("=" * 104)
tr = panel[panel["half"] == "train"]
q80 = float(np.percentile(tr["f_tr1"].dropna(), 80))
q95 = float(np.percentile(tr["f_tr1"].dropna(), 95))
print(f"  train thresholds: 80th pct of trailing-1d funding = {q80:.4f}%/day, "
      f"95th = {q95:.4f}%/day")
base_pos = float((panel["f_fwd1"] > 0).mean() * 100)
print(f"  unconditional P(next-day funding > 0) = {base_pos:.1f}%   <= the null")
print(f"\n  {'condition':<28}{'n':>7}{'P(fwd1>0)':>11}{'P(fwd3>0)':>11}"
      f"{'mean fwd1 %':>13}{'mean fwd3 %':>13}")
print("-" * 104)
pers = {}
for lab, mask in (("trailing > 0", panel["f_tr1"] > 0),
                  ("trailing >= 80th pct", panel["f_tr1"] >= q80),
                  ("trailing >= 95th pct", panel["f_tr1"] >= q95),
                  ("trailing < 0", panel["f_tr1"] < 0)):
    sub = panel[mask]
    if len(sub) < 13:
        continue
    p1 = float((sub["f_fwd1"] > 0).mean() * 100)
    p3 = float((sub["f_fwd3"] > 0).mean() * 100)
    m1 = float(sub["f_fwd1"].mean())
    m3 = float(sub["f_fwd3"].mean())
    print(f"  {lab:<28}{len(sub):>7}{p1:>10.1f}%{p3:>10.1f}%{m1:>13.4f}{m3:>13.4f}")
    pers[lab] = {"n": int(len(sub)), "p_fwd1_pos": round(p1, 1), "p_fwd3_pos": round(p3, 1),
                 "mean_fwd1_pct": round(m1, 5), "mean_fwd3_pct": round(m3, 5)}
report["persistence"] = {"thresholds": {"p80": round(q80, 5), "p95": round(q95, 5)},
                         "unconditional_p_pos": round(base_pos, 1), "by_condition": pers}

# =============================================== 2. CARRY PnL
print("\n" + "=" * 104)
print("2. CARRY PnL — short the high-funding perp, hedge long BTC, hold 1 or 3 days")
print(f"   net = funding collected  -  (perp price move)  +  (hedge move)  -  {FEE_BPS_RT} bps")
print("=" * 104)
panel["drift1"] = -panel["ret1"] + panel["hret1"]      # short perp + long hedge
panel["drift3"] = -panel["ret3"] + panel["hret3"]
panel["pnl1"] = panel["f_fwd1"] + panel["drift1"] - FEE_BPS_RT / 100.0
panel["pnl3"] = panel["f_fwd3"] + panel["drift3"] - FEE_BPS_RT / 100.0
panel["pnl1_nohedge"] = panel["f_fwd1"] - panel["ret1"] - (FEE_BPS_RT / 2) / 100.0

print(f"  {'bucket / half':<30}{'n':>7}{'funding':>10}{'hedge drift':>13}"
      f"{'NET 1d %':>11}{'CI95':>22}")
print("-" * 104)
carry = {}
for lab, mask in (("trailing >= 80th pct", panel["f_tr1"] >= q80),
                  ("trailing >= 95th pct", panel["f_tr1"] >= q95)):
    for half in ("train", "test"):
        sub = panel[mask & (panel["half"] == half)].dropna(subset=["pnl1"])
        if len(sub) < 13:
            continue
        p, lo, hi = boot(sub["pnl1"].values, sub["day"].values)
        ci = f"[{lo:+.4f},{hi:+.4f}]" if p is not None else ""
        sig = "*" if (lo is not None and (lo > 0 or hi < 0)) else " "
        print(f"  {lab + ' / ' + half:<30}{len(sub):>7}{sub['f_fwd1'].mean():>10.4f}"
              f"{sub['drift1'].mean():>13.4f}{p:>10.4f}{sig}{ci:>22}")
        carry[f"{lab}|{half}"] = {"n": int(len(sub)),
                                  "funding_pct": round(float(sub["f_fwd1"].mean()), 5),
                                  "hedge_drift_pct": round(float(sub["drift1"].mean()), 5),
                                  "net_pct": round(p, 5),
                                  "ci": [round(lo, 5), round(hi, 5)] if p is not None else None,
                                  "significant": bool(lo is not None and (lo > 0 or hi < 0))}
print("\n  how big is hedge drift relative to the funding it is meant to protect?")
for lab, mask in (("trailing >= 80th pct", panel["f_tr1"] >= q80),
                  ("trailing >= 95th pct", panel["f_tr1"] >= q95)):
    sub = panel[mask].dropna(subset=["drift1", "f_fwd1"])
    if len(sub) < 13:
        continue
    print(f"    {lab:<24} funding {sub['f_fwd1'].mean():+.4f}%  "
          f"drift mean {sub['drift1'].mean():+.4f}%  drift sd {sub['drift1'].std():.4f}%  "
          f"=> noise/signal {sub['drift1'].std()/max(abs(sub['f_fwd1'].mean()),1e-9):.0f}x")
report["carry"] = carry

# =============================================== 3. TAIL / SQUEEZE
print("\n" + "=" * 104)
print("3. TAIL RISK — upside excursion against the short, in high-funding regimes")
print("=" * 104)
print(f"  {'bucket':<28}{'n':>7}{'median sq1':>12}{'p95 sq1':>10}{'p99 sq1':>10}{'p99 sq3':>10}{'worst':>9}")
print("-" * 104)
tail = {}
for lab, mask in (("all days", panel["f_tr1"].notna()),
                  ("trailing >= 80th pct", panel["f_tr1"] >= q80),
                  ("trailing >= 95th pct", panel["f_tr1"] >= q95)):
    sub = panel[mask].dropna(subset=["sq1"])
    if len(sub) < 13:
        continue
    print(f"  {lab:<28}{len(sub):>7}{np.median(sub['sq1']):>12.2f}"
          f"{np.percentile(sub['sq1'],95):>10.2f}{np.percentile(sub['sq1'],99):>10.2f}"
          f"{np.percentile(sub['sq3'].dropna(),99):>10.2f}{sub['sq1'].max():>9.2f}")
    tail[lab] = {"n": int(len(sub)), "median_sq1": round(float(np.median(sub["sq1"])), 3),
                 "p95_sq1": round(float(np.percentile(sub["sq1"], 95)), 3),
                 "p99_sq1": round(float(np.percentile(sub["sq1"], 99)), 3),
                 "p99_sq3": round(float(np.percentile(sub["sq3"].dropna(), 99)), 3),
                 "worst_sq1": round(float(sub["sq1"].max()), 3)}
report["tail"] = tail

# =============================================== VERDICT
print("\n" + "=" * 104)
print("VERDICT")
print("=" * 104)
te95 = carry.get("trailing >= 95th pct|test")
te80 = carry.get("trailing >= 80th pct|test")
lines = []
for k, v in (("top 5%", te95), ("top 20%", te80)):
    if not v:
        continue
    lines.append(f"{k} funding, hedged, 1-day hold, on TEST: net {v['net_pct']:+.4f}% "
                 f"{v['ci']} -> {'REAL after costs' if v['significant'] and v['net_pct'] > 0 else 'NOT an edge after costs'}")
for l in lines:
    print("  " + l)
report["verdict"] = lines
with io.open(os.path.join(HERE, "funding_carry.json"), "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
print("\nwrote funding_carry.json")
