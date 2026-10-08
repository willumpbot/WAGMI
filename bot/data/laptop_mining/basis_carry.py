"""The decisive test of this project's one promising lead: spot/perp basis carry.

FUNDING_CARRY.md: funding is 99.3% persistent and pays ~0.28%/day at the top, but
a cross-asset hedge has 25-38x more noise than signal. A SAME-ASSET hedge removes
that drift by construction -- long spot, short perp, delta flat.

fetch_spot.py established the hard constraint: only 8 Hyperliquid assets have both
a USDC spot market and a perp, and BTC/ETH/SOL/XRP are NOT among them. HYPE is the
only one the owner actually holds.

Mechanics (exact, not approximated):
    position   long 1 unit spot, short 1 unit perp
    basis      b = (perp - spot) / spot
    price PnL  = -(b_exit - b_entry)          <- the two legs cancel except via basis
    total      = funding collected - d(basis) - fees
    capital    = 2x notional (spot bought outright + perp margin), so the return on
                 capital is HALF the headline percentage

Fees charged: perp taker 4.5 bps and spot taker 7 bps, each in and out = 23 bps
round trip. Slippage 3 bps per leg per side = 12 bps. Total 35 bps.
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_RT_PCT = 0.35          # 35 bps round trip, both legs
CAPITAL_MULT = 2.0         # spot + perp margin
rng = np.random.default_rng(20261008)


def load(path_sym, kind):
    p = os.path.join(HIST, f"{path_sym}_{kind}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
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


spots = sorted({os.path.basename(p).split("_spot_")[0]
                for p in glob.glob(os.path.join(HIST, "*_spot_1d.csv"))})
print(f"assets with HL spot candles: {spots}")

rows = []
for s in spots:
    sp = load(f"{s}_spot", "1d")
    pp = load(s, "1d")
    fd = funding(s)
    if sp is None or pp is None:
        print(f"  {s}: missing {'spot' if sp is None else 'perp'} candles -- skipped")
        continue
    if fd is None:
        print(f"  {s}: no funding history -- skipped")
        continue
    d = pp[["day", "c"]].rename(columns={"c": "perp"}).merge(
        sp[["day", "c"]].rename(columns={"c": "spot"}), on="day", how="inner")
    d = d.merge(fd.rename("fund_pct"), left_on="day", right_index=True, how="inner")
    d = d[(d["spot"] > 0) & (d["perp"] > 0)].sort_values("day").reset_index(drop=True)
    if len(d) < 90:
        print(f"  {s}: only {len(d)} overlapping days -- skipped")
        continue
    d["sym"] = s
    d["basis_pct"] = (d["perp"] - d["spot"]) / d["spot"] * 100
    d["f_tr"] = d["fund_pct"].shift(1)
    # hold 1 day: collect today's funding, suffer today's basis change
    d["dbasis1"] = d["basis_pct"].shift(-1) - d["basis_pct"]
    d["pnl1"] = d["fund_pct"] - d["dbasis1"] - FEE_RT_PCT
    # hold 3 days
    d["fund3"] = d["fund_pct"].rolling(3).sum().shift(-2)
    d["dbasis3"] = d["basis_pct"].shift(-3) - d["basis_pct"]
    d["pnl3"] = d["fund3"] - d["dbasis3"] - FEE_RT_PCT
    rows.append(d)
    print(f"  {s:<8} {len(d):>4} days  {d['day'].min()} -> {d['day'].max()}   "
          f"basis mean {d['basis_pct'].mean():+.3f}%  sd {d['basis_pct'].std():.3f}%   "
          f"funding mean {d['fund_pct'].mean():+.4f}%/day")

if not rows:
    raise SystemExit("\nNo asset has spot + perp + funding overlap -> basis carry untestable here.")

panel = pd.concat(rows, ignore_index=True).dropna(subset=["pnl1", "f_tr"])
CUT = panel["day"].quantile(0.6) if False else None
days = sorted(panel["day"].unique())
cut_day = days[int(len(days) * 0.6)]
panel["half"] = np.where(panel["day"] < cut_day, "train", "test")
print(f"\npanel {len(panel)} asset-days, {panel['sym'].nunique()} assets, split at {cut_day}")
print(panel.groupby("half").size().to_dict())


def boot(v, days_, iters=2000):
    cl = collections.defaultdict(list)
    for x, dd in zip(v, days_):
        if np.isfinite(x):
            cl[dd].append(x)
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


print("\n" + "=" * 104)
print("BASIS CARRY — long spot / short perp, same asset, delta flat")
print(f"   net = funding collected - change in basis - {FEE_RT_PCT*100:.0f} bps")
print("=" * 104)
q70 = float(np.percentile(panel[panel["half"] == "train"]["f_tr"].dropna(), 70))
print(f"  train 70th pct of trailing funding = {q70:.4f}%/day")
print(f"\n  {'bucket / half':<28}{'n':>6}{'funding':>10}{'d basis':>10}"
       f"{'NET 1d':>9}{'CI95':>22}{'on capital':>12}")
print("-" * 104)
out = {"fee_rt_pct": FEE_RT_PCT, "capital_mult": CAPITAL_MULT,
       "assets": sorted(panel["sym"].unique()), "rows": int(len(panel)),
       "split_day": cut_day, "trailing_funding_p70": round(q70, 5), "buckets": {}}
for lab, mask in (("all days", panel["f_tr"].notna()),
                  ("trailing funding > 0", panel["f_tr"] > 0),
                  ("trailing >= 70th pct", panel["f_tr"] >= q70)):
    for half in ("train", "test"):
        sub = panel[mask & (panel["half"] == half)].dropna(subset=["pnl1"])
        if len(sub) < 13:
            continue
        p, lo, hi = boot(sub["pnl1"].values, sub["day"].values)
        if p is None:
            continue
        sig = "*" if (lo > 0 or hi < 0) else " "
        print(f"  {lab + ' / ' + half:<28}{len(sub):>6}{sub['fund_pct'].mean():>10.4f}"
              f"{sub['dbasis1'].mean():>10.4f}{p:>9.4f}{sig}"
              f"[{lo:+.4f},{hi:+.4f}]".rjust(22) + f"{p/CAPITAL_MULT:>12.4f}")
        out["buckets"][f"{lab}|{half}"] = {
            "n": int(len(sub)), "funding_pct": round(float(sub["fund_pct"].mean()), 5),
            "d_basis_pct": round(float(sub["dbasis1"].mean()), 5),
            "net_pct": round(p, 5), "ci": [round(lo, 5), round(hi, 5)],
            "net_on_capital_pct": round(p / CAPITAL_MULT, 5),
            "significant": bool(lo > 0 or hi < 0)}

print("\n  basis volatility vs the funding it must not swamp:")
for s, g in panel.groupby("sym"):
    sd = float(g["dbasis1"].std())
    fm = float(g["fund_pct"].mean())
    print(f"    {s:<8} d(basis) sd {sd:.4f}%   funding/day {fm:+.4f}%   "
          f"noise/signal {sd/max(abs(fm),1e-9):>6.1f}x")
    out.setdefault("per_asset", {})[s] = {
        "dbasis_sd_pct": round(sd, 5), "funding_mean_pct": round(fm, 5),
        "noise_over_signal": round(sd / max(abs(fm), 1e-9), 2),
        "n": int(len(g))}

print("\n  3-day hold, trailing funding >= 70th pct:")
for half in ("train", "test"):
    sub = panel[(panel["f_tr"] >= q70) & (panel["half"] == half)].dropna(subset=["pnl3"])
    if len(sub) < 13:
        continue
    p, lo, hi = boot(sub["pnl3"].values, sub["day"].values)
    if p is None:
        continue
    print(f"    {half:<6} n={len(sub):>5}  funding {sub['fund3'].mean():+.4f}%  "
          f"d(basis) {sub['dbasis3'].mean():+.4f}%  net {p:+.4f}% [{lo:+.4f},{hi:+.4f}]  "
          f"on capital {p/CAPITAL_MULT:+.4f}%")
    out["buckets"][f"3d trailing>=p70|{half}"] = {
        "n": int(len(sub)), "net_pct": round(p, 5),
        "ci": [round(lo, 5), round(hi, 5)],
        "net_on_capital_pct": round(p / CAPITAL_MULT, 5),
        "significant": bool(lo > 0 or hi < 0)}

print("\n" + "=" * 104)
print("VERDICT")
print("=" * 104)
te = out["buckets"].get("trailing >= 70th pct|test")
if te:
    good = te["significant"] and te["net_pct"] > 0
    print(f"  high-funding, 1-day hold, TEST: net {te['net_pct']:+.4f}% "
          f"{te['ci']}  ({te['net_on_capital_pct']:+.4f}% on capital)")
    print(f"  => {'REAL after costs' if good else 'NOT established after costs'}")
    out["verdict"] = ("real after costs" if good else "not established after costs")
print(f"\n  HARD CONSTRAINT: only {len(spots)} HL assets have both spot and perp, and "
      f"BTC/ETH/SOL/XRP are not among them.")
out["hard_constraint"] = ("only 8 HL assets have both a USDC spot market and a perp; "
                          "BTC/ETH/SOL/XRP do not")
with io.open(os.path.join(HERE, "basis_carry.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote basis_carry.json")
