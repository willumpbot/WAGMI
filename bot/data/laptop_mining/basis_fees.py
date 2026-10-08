"""Fee sensitivity for the basis trade — does maker-only execution flip the answer?

BASIS_CARRY.md closed the lead at 35 bps taker round trip: only a 30-day hold
survived on test, at 2.3% annualised. I listed maker-only execution as one of
three things that could change that, so it should be tested rather than left as a
hypothesis.

Sweeps the round-trip cost from 0 to 50 bps and reports, per hold period, the
test-half net and whether its CI excludes zero. Break-even fee is reported
directly: the cost at which each hold stops paying.

HL fee reference used for the labels:
  taker perp 4.5 bps, taker spot 7 bps  -> 23 bps round trip both legs, + 12 bps
                                           slippage = 35 bps  (the base case)
  maker perp ~1.5 bps, maker spot ~4 bps -> ~11 bps round trip, + 4 bps = 15 bps
  maker rebate / zero-fee tier                                      -> 0-5 bps
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CAPITAL_MULT = 2.0
MAX_ABS_BASIS = 5.0
HOLDS = (3, 7, 14, 30)
FEES = (0.0, 0.05, 0.10, 0.15, 0.20, 0.26, 0.35, 0.50)
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


kept = []
for s in sorted({os.path.basename(p).split("_spot_")[0]
                 for p in glob.glob(os.path.join(HIST, "*_spot_1d.csv"))}):
    sp, pp, fd = load(f"{s}_spot_1d"), load(f"{s}_1d"), funding(s)
    if sp is None or pp is None or fd is None:
        continue
    d = pp.rename(columns={"c": "perp"}).merge(sp.rename(columns={"c": "spot"}), on="day")
    d = d.merge(fd.rename("fund_pct"), left_on="day", right_index=True)
    d = d[(d["spot"] > 0) & (d["perp"] > 0)].sort_values("day").reset_index(drop=True)
    if len(d) < 90:
        continue
    d["basis_pct"] = (d["perp"] - d["spot"]) / d["spot"] * 100
    if abs(d["basis_pct"].mean()) >= MAX_ABS_BASIS or d["basis_pct"].std() >= MAX_ABS_BASIS:
        continue
    d["sym"] = s
    kept.append(d)
if not kept:
    raise SystemExit("no usable asset")
panel = pd.concat(kept, ignore_index=True)
for h in HOLDS:
    panel[f"gross{h}"] = (panel.groupby("sym")["fund_pct"].transform(
        lambda s: s.rolling(h).sum().shift(-(h - 1)))
        - (panel.groupby("sym")["basis_pct"].transform(lambda s: s.shift(-h)) - panel["basis_pct"]))
days = sorted(panel["day"].unique())
cut = days[int(len(days) * 0.6)]
panel["half"] = np.where(panel["day"] < cut, "train", "test")
print(f"assets {sorted(panel['sym'].unique())}, {len(panel)} days, split {cut}")


def boot(vals, dys, block, iters=1500):
    s = pd.DataFrame({"d": dys, "v": vals}).dropna()
    if not len(s):
        return None, None, None
    dt = pd.to_datetime(s["d"])
    key = ((dt - dt.min()).dt.days // max(1, block)).values
    groups = [s["v"].values[key == k] for k in np.unique(key)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 5:
        return float(s["v"].mean()), None, None
    point = float(s["v"].mean())
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


LABELS = {0.0: "zero-fee", 0.05: "maker rebate", 0.15: "maker-only",
          0.26: "perp-taker only", 0.35: "taker base case", 0.50: "wide/slippy"}
print("\n" + "=" * 100)
print("FEE SENSITIVITY — TEST half net %, and annualised on 2x capital")
print("=" * 100)
header = f"  {'fee bps':<10}{'label':<18}" + "".join(f"{str(h)+'d':>18}" for h in HOLDS)
print(header)
print("-" * 100)
out = {"capital_mult": CAPITAL_MULT, "holds": list(HOLDS),
       "assets": sorted(panel["sym"].unique()), "split_day": cut, "grid": {}}
te = panel[panel["half"] == "test"]
for fee in FEES:
    line = f"  {fee*100:<10.0f}{LABELS.get(fee, ''):<18}"
    for h in HOLDS:
        v = (te[f"gross{h}"] - fee).values
        p, lo, hi = boot(v, te["day"].values, h)
        if p is None:
            line += f"{'n/a':>18}"
            continue
        ann = (p / CAPITAL_MULT) * (365.0 / h)
        star = "*" if (lo is not None and (lo > 0 or hi < 0)) else " "
        line += f"{p:>+9.3f}{star}{ann:>7.1f}%"
        out["grid"][f"fee{fee}|{h}d"] = {
            "net_pct": round(p, 5), "annualised_pct": round(ann, 2),
            "ci": [round(lo, 5), round(hi, 5)] if lo is not None else None,
            "significant": bool(lo is not None and (lo > 0 or hi < 0))}
    print(line)

print("\n  break-even fee per hold (TEST half): the cost at which the carry stops paying")
print(f"    {'hold':<8}{'mean gross %':>14}{'break-even bps':>16}{'ann. at 15bps maker':>22}")
for h in HOLDS:
    g = float(te[f"gross{h}"].mean())
    be = g * 100
    net15 = g - 0.15
    ann15 = (net15 / CAPITAL_MULT) * (365.0 / h)
    print(f"    {str(h)+'d':<8}{g:>14.4f}{be:>16.1f}{ann15:>21.1f}%")
    out.setdefault("breakeven", {})[f"{h}d"] = {
        "gross_pct": round(g, 5), "breakeven_bps": round(be, 2),
        "annualised_at_15bps": round(ann15, 2)}

print("\n" + "=" * 100)
print("VERDICT")
print("=" * 100)
best = None
for k, v in out["grid"].items():
    if v["significant"] and v["net_pct"] > 0:
        if best is None or v["annualised_pct"] > best[1]["annualised_pct"]:
            best = (k, v)
if best:
    print(f"  best significant cell on test: {best[0]}  "
          f"net {best[1]['net_pct']:+.3f}%  {best[1]['annualised_pct']:.1f}% annualised on capital")
    out["verdict"] = f"{best[0]} -> {best[1]['annualised_pct']}% annualised"
    if best[1]["annualised_pct"] < 5:
        print("  Still below anything worth the operational risk. Maker execution does NOT rescue it.")
        out["conclusion"] = "maker execution does not rescue the trade"
    else:
        print("  Maker execution materially changes the picture -- worth a forward test.")
        out["conclusion"] = "maker execution materially improves the trade"
else:
    print("  No fee level produces a significant positive on test.")
    out["conclusion"] = "no fee level works"
with io.open(os.path.join(HERE, "basis_fees.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote basis_fees.json")
