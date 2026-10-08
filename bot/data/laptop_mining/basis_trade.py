"""Mission 14: is same-asset funding harvesting real on Hyperliquid?

Corrects my own error first. fetch_spot.py matched spot BASE names against the
perp universe and concluded BTC/ETH/SOL have no HL spot market. They do -- as
WRAPPED tokens (UBTC @142, UETH @151, USOL @156), so the names never matched.
With the mapping fixed there are 21 spot/perp pairs, and the majors have real
book depth ($419k/$631k within 0.5% on UBTC).

Trade, as mission 14 specifies it:
    enter  when trailing-24h funding >= 80th percentile (train-derived)
    exit   when trailing funding falls below its median, or after MAX_HOLD days
    legs   long wrapped spot, short perp, same asset, delta flat
    PnL    funding collected - change in basis - fees - slippage

Costs are real, not nominal:
    perp taker 4.5 bps, spot taker 7 bps, each in and out      = 23 bps / cycle
    slippage modelled from MEASURED book depth for the clip size, both legs
Capacity is the measured depth within 0.5%, which is the binding constraint.
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_BPS_CYCLE = 23.0        # perp 4.5 + spot 7, in and out
CLIPS = (1_000, 5_000, 25_000)
MAX_HOLD = 30
MAX_ABS_BASIS = 5.0
rng = np.random.default_rng(20261008)


def load(name, col="c"):
    p = os.path.join(HIST, f"{name}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=[col]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df[["day", col]]


def funding(sym):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if not os.path.exists(p) or os.path.getsize(p) < 500:
        return None
    f = pd.read_csv(p)
    f["rate"] = pd.to_numeric(f["rate"], errors="coerce")
    f = f.dropna(subset=["rate"])
    f["day"] = pd.to_datetime(f["t_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return f.groupby("day")["rate"].sum().mul(100)


pairs = {}
pj = os.path.join(HERE, "basis_pairs.json")
if os.path.exists(pj):
    for c in json.load(io.open(pj, encoding="utf-8")).get("pairs", []):
        if c.get("depth"):
            prev = pairs.get(c["perp"])
            if prev is None or (c["depth"].get("bid_0p5", 0) > prev["depth"].get("bid_0p5", 0)):
                pairs[c["perp"]] = c


def slippage_bps(clip, depth):
    """Linear-impact estimate: a clip equal to the 0.5% depth costs ~50 bps."""
    if not depth:
        return None
    d = min(depth.get("bid_0p5", 0), depth.get("ask_0p5", 0))
    if d <= 0:
        return None
    spread = depth.get("spread_bps", 0) or 0
    return spread / 2 + 50.0 * (clip / d)


syms = sorted({os.path.basename(p).split("_wspot_")[0]
               for p in glob.glob(os.path.join(HIST, "*_wspot_1d.csv"))})
print("=" * 110)
print("SCREEN — spot + perp + funding, basis sanity, measured depth")
print("=" * 110)
print(f"  {'coin':<10}{'days':>6}{'basis mean':>12}{'basis sd':>10}{'fund/day':>11}"
      f"{'cap 0.5%':>12}{'slip $5k':>10}  verdict")
print("-" * 110)
kept, screen = [], {}
for s in syms:
    sp, pp, fd = load(f"{s}_wspot_1d"), load(f"{s}_1d"), funding(s)
    if sp is None or pp is None or fd is None:
        screen[s] = {"verdict": "missing data"}
        print(f"  {s:<10}{'-':>6}{'-':>12}{'-':>10}{'-':>11}{'-':>12}{'-':>10}  "
              f"missing {'perp' if pp is None else ('spot' if sp is None else 'funding')}")
        continue
    d = pp.rename(columns={"c": "perp"}).merge(sp.rename(columns={"c": "spot"}), on="day")
    d = d.merge(fd.rename("fund_pct"), left_on="day", right_index=True)
    d = d[(d["spot"] > 0) & (d["perp"] > 0)].sort_values("day").reset_index(drop=True)
    if len(d) < 120:
        screen[s] = {"verdict": "too few days", "days": int(len(d))}
        print(f"  {s:<10}{len(d):>6}  too few overlapping days")
        continue
    d["basis_pct"] = (d["perp"] - d["spot"]) / d["spot"] * 100
    # Drop BAD PRINTS row-by-row rather than rejecting the coin. UBTC has 11 rows
    # in Feb 2025 printing spot at 6,969,696 / 7,979,573 -- placeholder quotes from
    # before the market had liquidity. Judging BTC on those threw away the best
    # asset in the set (deepest book, tightest real basis, 40x leverage).
    n_before = len(d)
    d = d[d["basis_pct"].abs() <= 2.0].reset_index(drop=True)
    n_dropped = n_before - len(d)
    if len(d) < 120:
        screen[s] = {"verdict": "too few clean days", "days": int(len(d)),
                     "dropped_bad_prints": int(n_dropped)}
        print(f"  {s:<10}{len(d):>6}  too few days after dropping {n_dropped} bad prints")
        continue
    bm, bs, fm = float(d["basis_pct"].mean()), float(d["basis_pct"].std()), float(d["fund_pct"].mean())
    dep = (pairs.get(s) or {}).get("depth")
    cap = min(dep.get("bid_0p5", 0), dep.get("ask_0p5", 0)) if dep else 0
    sl5 = slippage_bps(5000, dep)
    ok = abs(bm) < MAX_ABS_BASIS and bs < MAX_ABS_BASIS and cap >= 20_000
    print(f"  {s:<10}{len(d):>6}{bm:>+12.3f}{bs:>10.3f}{fm:>+11.4f}"
          f"${cap/1e3:>10.0f}k{(sl5 if sl5 else float('nan')):>10.1f}  "
          f"{'USE' if ok else ('reject: thin book' if cap < 20_000 else 'reject: basis scale')}")
    screen[s] = {"verdict": "use" if ok else "reject", "days": int(len(d)),
                 "basis_mean_pct": round(bm, 4), "basis_sd_pct": round(bs, 4),
                 "funding_mean_pct": round(fm, 5), "capacity_0p5_usd": round(cap),
                 "slip_bps_5k": round(sl5, 2) if sl5 else None,
                 "dropped_bad_prints": int(n_dropped)}
    if ok:
        d["sym"] = s
        d["cap"] = cap
        kept.append(d)

if not kept:
    raise SystemExit("\nNothing passes the screen.")

panel = pd.concat(kept, ignore_index=True)
panel["f_tr"] = panel.groupby("sym")["fund_pct"].shift(1)
days = sorted(panel["day"].unique())
cut = days[int(len(days) * 0.6)]
panel["half"] = np.where(panel["day"] < cut, "train", "test")
print(f"\nusable: {sorted(panel['sym'].unique())}   {len(panel)} coin-days   split {cut}")

tr = panel[panel["half"] == "train"]["f_tr"].dropna()
P80, MED = float(np.percentile(tr, 80)), float(np.median(tr))
print(f"train trailing funding: 80th pct {P80:.4f}%/day, median {MED:.4f}%/day")


def cycles(g, clip):
    """Walk one coin, entering/exiting by the funding rule. Returns completed cycles."""
    g = g.sort_values("day").reset_index(drop=True)
    dep = (pairs.get(g["sym"].iloc[0]) or {}).get("depth")
    sl = slippage_bps(clip, dep)
    if sl is None:
        return []
    cost = FEE_BPS_CYCLE / 100.0 + 2 * sl / 100.0     # both legs, in and out
    out, i = [], 0
    while i < len(g) - 1:
        if not (g["f_tr"].iloc[i] >= P80):
            i += 1
            continue
        start = i
        fund = 0.0
        j = i
        while j < len(g) - 1 and (j - start) < MAX_HOLD:
            fund += float(g["fund_pct"].iloc[j])
            j += 1
            if g["f_tr"].iloc[j] < MED:
                break
        db = float(g["basis_pct"].iloc[j] - g["basis_pct"].iloc[start])
        out.append({"sym": g["sym"].iloc[0], "day": g["day"].iloc[start],
                    "hold": j - start, "funding": fund, "dbasis": db,
                    "cost": cost, "net": fund - db - cost,
                    "half": g["half"].iloc[start], "clip": clip})
        i = j + 1
    return out


print("\n" + "=" * 110)
print("CYCLE BACKTEST — enter when trailing funding >= 80th pct, exit below median or after 30d")
print("=" * 110)
out = {"fee_bps_cycle": FEE_BPS_CYCLE, "entry_p80": round(P80, 5), "exit_median": round(MED, 5),
       "max_hold": MAX_HOLD, "split_day": cut, "screen": screen, "clips": {}, "coins": {}}
for clip in CLIPS:
    allc = []
    for s, g in panel.groupby("sym"):
        allc.extend(cycles(g, clip))
    if not allc:
        continue
    df = pd.DataFrame(allc)
    print(f"\n  clip ${clip:,}  ({len(df)} cycles, median hold {df['hold'].median():.0f}d)")
    print(f"    {'half':<7}{'n':>5}{'funding':>10}{'d basis':>10}{'cost':>8}"
          f"{'NET/cycle':>11}{'CI95':>22}{'ann. on 2x cap':>16}{'worst':>9}")
    for half in ("train", "test"):
        sub = df[df["half"] == half]
        if len(sub) < 5:
            continue
        v = sub["net"].values
        ms = np.empty(2000)
        for i in range(2000):
            ms[i] = v[rng.integers(0, len(v), len(v))].mean()
        ms.sort()
        lo, hi = float(ms[50]), float(ms[-50])
        m = float(v.mean())
        hold = float(sub["hold"].mean())
        ann = (m / 2.0) * (365.0 / max(hold, 1))
        sig = "*" if (lo > 0 or hi < 0) else " "
        print(f"    {half:<7}{len(sub):>5}{sub['funding'].mean():>10.4f}"
              f"{sub['dbasis'].mean():>10.4f}{sub['cost'].mean():>8.3f}{m:>10.4f}{sig}"
              f"[{lo:+.4f},{hi:+.4f}]".rjust(22) + f"{ann:>15.1f}%{v.min():>9.3f}")
        out["clips"][f"{clip}|{half}"] = {
            "n_cycles": int(len(sub)), "mean_hold_days": round(hold, 2),
            "funding_pct": round(float(sub["funding"].mean()), 5),
            "dbasis_pct": round(float(sub["dbasis"].mean()), 5),
            "cost_pct": round(float(sub["cost"].mean()), 5),
            "net_per_cycle_pct": round(m, 5), "ci": [round(lo, 5), round(hi, 5)],
            "annualised_on_2x_capital_pct": round(ann, 2),
            "worst_cycle_pct": round(float(v.min()), 4),
            "pct_cycles_negative": round(float((v < 0).mean() * 100), 1),
            "significant": bool(lo > 0 or hi < 0)}
    wipe = float((df["dbasis"] > df["funding"]).mean() * 100)
    print(f"    basis move wiped the cycle's funding in {wipe:.1f}% of cycles; "
          f"{float((df['net'] < 0).mean()*100):.1f}% of cycles net negative")
    out["clips"][f"{clip}|basis_wipe_pct"] = round(wipe, 1)

    if clip == 5000:
        print("\n    per coin (all cycles):")
        for s, g in df.groupby("sym"):
            print(f"      {s:<10} n={len(g):>3}  net/cycle {g['net'].mean():+.4f}%  "
                  f"hold {g['hold'].mean():>4.1f}d  worst {g['net'].min():+.3f}%  "
                  f"cap ${(pairs.get(s) or {}).get('depth',{}).get('bid_0p5',0)/1e3:.0f}k")
            out["coins"][s] = {
                "n_cycles": int(len(g)), "net_per_cycle_pct": round(float(g["net"].mean()), 5),
                "mean_hold_days": round(float(g["hold"].mean()), 2),
                "worst_cycle_pct": round(float(g["net"].min()), 4),
                "capacity_usd": round((pairs.get(s) or {}).get("depth", {}).get("bid_0p5", 0))}

with io.open(os.path.join(HERE, "basis_trade.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote basis_trade.json")
