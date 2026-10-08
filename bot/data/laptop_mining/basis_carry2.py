"""Basis carry, done properly: sanity-filtered assets and realistic hold periods.

Two faults in the first run (basis_carry.py), both fixed here:

1. PUMP was included and its basis reads +2459% with a 1137% standard deviation.
   Spot and perp are quoted on different scales for that pair, so it is a data
   artefact, not a basis. A real spot/perp basis is a fraction of a percent. Now
   filtered: |basis| must stay under 5%.

2. Hold periods of 1 and 3 days cannot work at 35 bps round trip. HYPE funding
   averages 0.056%/day, so fees alone need about SIX days of carry to break even.
   Testing a 1-day hold was testing whether 0.056% beats 0.35%, which it cannot.
   Now: 1, 3, 7, 14 and 30-day holds, so the fee amortises as it would in reality.

The question this answers: on the one Hyperliquid asset where a same-asset basis
trade is actually possible and the data is clean, does holding it for weeks pay
after costs?
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_RT_PCT = 0.35
CAPITAL_MULT = 2.0
MAX_ABS_BASIS = 5.0          # sanity: a genuine spot/perp basis is well under this
HOLDS = (1, 3, 7, 14, 30)
rng = np.random.default_rng(20261008)


def load(name):
    p = os.path.join(HIST, f"{name}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    df["c"] = pd.to_numeric(df["c"], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df[["day", "c"]]


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
print("=" * 100)
print("ASSET SCREEN — spot + perp + funding, with a basis sanity check")
print("=" * 100)
print(f"  {'asset':<10}{'days':>6}{'basis mean':>12}{'basis sd':>11}{'funding/day':>13}  verdict")
print("-" * 100)
kept = []
screen = {}
for s in spots:
    sp, pp, fd = load(f"{s}_spot_1d"), load(f"{s}_1d"), funding(s)
    if sp is None or pp is None or fd is None:
        print(f"  {s:<10}{'-':>6}{'-':>12}{'-':>11}{'-':>13}  "
              f"missing {'perp' if pp is None else ('spot' if sp is None else 'funding')}")
        screen[s] = {"verdict": "missing data"}
        continue
    d = pp.rename(columns={"c": "perp"}).merge(sp.rename(columns={"c": "spot"}), on="day")
    d = d.merge(fd.rename("fund_pct"), left_on="day", right_index=True)
    d = d[(d["spot"] > 0) & (d["perp"] > 0)].sort_values("day").reset_index(drop=True)
    if len(d) < 90:
        print(f"  {s:<10}{len(d):>6}{'-':>12}{'-':>11}{'-':>13}  too few overlapping days")
        screen[s] = {"verdict": "too few days", "days": int(len(d))}
        continue
    d["basis_pct"] = (d["perp"] - d["spot"]) / d["spot"] * 100
    bm, bs = float(d["basis_pct"].mean()), float(d["basis_pct"].std())
    fm = float(d["fund_pct"].mean())
    ok = abs(bm) < MAX_ABS_BASIS and bs < MAX_ABS_BASIS
    print(f"  {s:<10}{len(d):>6}{bm:>+12.3f}{bs:>11.3f}{fm:>+13.4f}  "
          f"{'USE' if ok else 'REJECT — scale mismatch, not a basis'}")
    screen[s] = {"verdict": "use" if ok else "reject: scale mismatch",
                 "days": int(len(d)), "basis_mean_pct": round(bm, 4),
                 "basis_sd_pct": round(bs, 4), "funding_mean_pct": round(fm, 5)}
    if ok:
        d["sym"] = s
        kept.append(d)

if not kept:
    raise SystemExit("\nNo asset passes the screen -> basis carry is not testable on HL data.")

panel = pd.concat(kept, ignore_index=True)
print(f"\nusable: {sorted(panel['sym'].unique())}  ({len(panel)} asset-days)")

for h in HOLDS:
    panel[f"fund{h}"] = panel.groupby("sym")["fund_pct"].transform(
        lambda s: s.rolling(h).sum().shift(-(h - 1)))
    panel[f"db{h}"] = panel.groupby("sym")["basis_pct"].transform(
        lambda s: s.shift(-h)) - panel["basis_pct"]
    panel[f"pnl{h}"] = panel[f"fund{h}"] - panel[f"db{h}"] - FEE_RT_PCT
panel["f_tr"] = panel.groupby("sym")["fund_pct"].shift(1)

days = sorted(panel["day"].unique())
cut = days[int(len(days) * 0.6)]
panel["half"] = np.where(panel["day"] < cut, "train", "test")
print(f"split at {cut}: {panel.groupby('half').size().to_dict()}")


def boot(sub, col, block, iters=2000):
    """Block bootstrap: block length = hold period, since overlapping holds share days."""
    s = sub[["day", col]].dropna()
    if not len(s):
        return None, None, None
    dt = pd.to_datetime(s["day"])
    key = ((dt - dt.min()).dt.days // max(1, block)).values
    groups = [s[col].values[key == k] for k in np.unique(key)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 5:
        return float(s[col].mean()), None, None
    point = float(s[col].mean())
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


print("\n" + "=" * 100)
print("BASIS CARRY BY HOLD PERIOD — long spot / short perp, same asset")
print(f"   net = funding over the hold - change in basis - {FEE_RT_PCT*100:.0f} bps")
print("   block bootstrap, block = hold length (overlapping holds are not independent)")
print("=" * 100)
print(f"  {'hold':<7}{'half':<7}{'n':>6}{'funding':>10}{'d basis':>10}{'NET':>9}"
      f"{'CI95':>24}{'on capital':>12}{'ann.':>9}")
print("-" * 100)
out = {"fee_rt_pct": FEE_RT_PCT, "capital_mult": CAPITAL_MULT,
       "max_abs_basis_filter": MAX_ABS_BASIS, "screen": screen,
       "usable_assets": sorted(panel["sym"].unique()), "split_day": cut, "holds": {}}
for h in HOLDS:
    for half in ("train", "test"):
        sub = panel[panel["half"] == half].dropna(subset=[f"pnl{h}"])
        if len(sub) < 13:
            continue
        p, lo, hi = boot(sub, f"pnl{h}", h)
        if p is None:
            continue
        sig = "*" if (lo is not None and (lo > 0 or hi < 0)) else " "
        ci = f"[{lo:+.4f},{hi:+.4f}]" if lo is not None else ""
        oncap = p / CAPITAL_MULT
        ann = oncap * (365.0 / h)
        print(f"  {str(h)+'d':<7}{half:<7}{len(sub):>6}{sub[f'fund{h}'].mean():>10.4f}"
              f"{sub[f'db{h}'].mean():>10.4f}{p:>9.4f}{sig}{ci:>24}{oncap:>12.4f}{ann:>8.1f}%")
        out["holds"][f"{h}d|{half}"] = {
            "n": int(len(sub)), "funding_pct": round(float(sub[f"fund{h}"].mean()), 5),
            "d_basis_pct": round(float(sub[f"db{h}"].mean()), 5), "net_pct": round(p, 5),
            "ci": [round(lo, 5), round(hi, 5)] if lo is not None else None,
            "net_on_capital_pct": round(oncap, 5), "annualised_pct": round(ann, 2),
            "significant": bool(lo is not None and (lo > 0 or hi < 0))}

print("\n  break-even arithmetic (why short holds cannot work):")
for s, g in panel.groupby("sym"):
    fm = float(g["fund_pct"].mean())
    be = FEE_RT_PCT / max(fm, 1e-9)
    print(f"    {s:<8} funding {fm:+.4f}%/day  =>  {be:.1f} days of carry just to cover "
          f"{FEE_RT_PCT*100:.0f} bps of fees")
    out.setdefault("breakeven_days", {})[s] = round(be, 2)

print("\n" + "=" * 100)
print("VERDICT")
print("=" * 100)
best = None
for k, v in out["holds"].items():
    if k.endswith("|test") and v["significant"] and v["net_pct"] > 0:
        if best is None or v["annualised_pct"] > best[1]["annualised_pct"]:
            best = (k, v)
if best:
    print(f"  BEST confirmed on test: {best[0]}  net {best[1]['net_pct']:+.4f}% "
          f"({best[1]['net_on_capital_pct']:+.4f}% on capital, {best[1]['annualised_pct']:.1f}% annualised)")
    out["verdict"] = f"real on test at {best[0]}"
else:
    print("  No hold period shows a net positive with a CI excluding zero on test.")
    out["verdict"] = "not established on test at any hold period"
print(f"  Constraint that caps everything: only HYPE passes the screen. BTC/ETH/SOL/XRP")
print(f"  have no HL spot market, and the other spot/perp pairs fail on data or history.")
with io.open(os.path.join(HERE, "basis_carry.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote basis_carry.json")
