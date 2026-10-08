"""Mission 6: multi-timeframe base-rate maps for the swing desk.

Extends bot/tools/hivemind/basemap.py from daily-only to daily x 4h. Same state
vocabulary and the same output shape, so the server can load it unchanged:

  key = "STRUCT|STRETCH|RANGE|DRIVER|4hSTRUCT|4hSTRETCH|4hDRIVER"   (7 fields)
  out = {"built", "latest", "keys": {key: {"<hz>d": {"all": stats, "<SYM>": stats}}}}
  stats = {n, n_eff, up_pct, median_pct, p25_pct, p75_pct}   (+ vol stats here)

The daily half reuses basemap's definitions exactly (EMA20/50, close vs EMA20,
third of the 20-day range, +DI vs -DI). The 4h half adds structure / stretch /
driver on 4h candles, sampled at the last CLOSED 4h bar at or before the daily
close -- so no lookahead into the day being predicted.

Per the handoff, every state is scored on train (< 2025-06-01) and test
(>= 2025-06-01) separately, and only states whose distribution is stable across
both halves are flagged `stable: true`. Those are the only base rates the desk
should headline.
"""
import json, io, os, glob, time, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
HORIZONS = (1, 3, 5)
MIN_N = 30          # per-half minimum before a state can be called stable


def load(sym, iv):
    p = os.path.join(HIST, f"{sym}_{iv}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c", "v"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    bar_ms = {"1d": 86_400_000, "4h": 14_400_000}[iv]
    if len(df) and df["t"].iloc[-1] + bar_ms > time.time() * 1000:
        df = df.iloc[:-1]          # drop the still-forming bar
    return df


def di(h, l, c):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    return (pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr,
            mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr, tr)


def daily_states(df):
    c, h, l = df["c"], df["h"], df["l"]
    ema20, ema50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    pdi, mdi, tr = di(h, l, c)
    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    pos = (c - lo20) / (hi20 - lo20).replace(0, np.nan)
    out = pd.DataFrame({
        "t": df["t"],
        "structure": np.where(ema20 > ema50, "UP", "DOWN"),
        "stretch": np.where(c > ema20, "ABOVE", "BELOW"),
        "range": np.where(pos < 1 / 3, "LOW", np.where(pos > 2 / 3, "HIGH", "MID")),
        "driver": np.where(pdi > mdi, "BUYERS", "SELLERS"),
        "atr_pct": tr.rolling(14).mean() / c * 100,
    })
    ret1 = c.pct_change() * 100
    for hz in HORIZONS:
        out[f"r{hz}"] = (c.shift(-hz) / c - 1) * 100
        out[f"vol{hz}"] = ret1.shift(-hz).rolling(hz).std() if hz > 1 else ret1.shift(-1).abs()
    out["valid"] = np.arange(len(df)) >= 50
    out["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return out


def h4_states(df):
    c, h, l = df["c"], df["h"], df["l"]
    ema20, ema50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    pdi, mdi, _ = di(h, l, c)
    out = pd.DataFrame({
        "t": df["t"],
        "h4_structure": np.where(ema20 > ema50, "UP", "DOWN"),
        "h4_stretch": np.where(c > ema20, "ABOVE", "BELOW"),
        "h4_driver": np.where(pdi > mdi, "BUYERS", "SELLERS"),
    })
    out["valid4"] = np.arange(len(df)) >= 50
    return out[out["valid4"]].drop(columns="valid4").reset_index(drop=True)


def stats(vals, volvals=None):
    v = np.asarray([x for x in vals if x == x], dtype=float)
    if len(v) == 0:
        return {"n": 0}
    d = {"n": int(len(v)), "n_eff": int(len(v) // 5),
         "up_pct": round(float((v > 0).mean() * 100), 1),
         "median_pct": round(float(np.median(v)), 2),
         "p25_pct": round(float(np.percentile(v, 25)), 2),
         "p75_pct": round(float(np.percentile(v, 75)), 2)}
    if volvals is not None:
        w = np.asarray([x for x in volvals if x == x], dtype=float)
        if len(w):
            d["vol_median_pct"] = round(float(np.median(w)), 2)
            d["vol_p75_pct"] = round(float(np.percentile(w, 75)), 2)
    return d


syms = sorted({os.path.basename(p).split("_")[0]
               for p in glob.glob(os.path.join(HIST, "*_4h.csv"))})
print(f"symbols: {syms}")

rows, latest = [], {}
for sym in syms:
    d1, d4 = load(sym, "1d"), load(sym, "4h")
    if d1 is None or d4 is None or len(d1) < 80 or len(d4) < 80:
        continue
    ds = daily_states(d1)
    ds = ds[ds["valid"]].copy()
    hs = h4_states(d4)
    # sample the last CLOSED 4h bar at or before each daily close (no lookahead)
    ds = ds.sort_values("t")
    hs = hs.sort_values("t")
    merged = pd.merge_asof(ds, hs, on="t", direction="backward")
    merged = merged.dropna(subset=["h4_structure"])
    merged["sym"] = sym
    rows.append(merged)
    if len(merged):
        last = merged.iloc[-1]
        latest[sym] = {k: str(last[k]) for k in
                       ("structure", "stretch", "range", "driver",
                        "h4_structure", "h4_stretch", "h4_driver")}
        latest[sym]["atr_pct"] = (round(float(last["atr_pct"]), 2)
                                  if last["atr_pct"] == last["atr_pct"] else None)
        latest[sym]["since"] = str(merged.iloc[0]["day"])

panel = pd.concat(rows, ignore_index=True)
print(f"panel rows: {len(panel)}   span {panel['day'].min()} -> {panel['day'].max()}")


def key_of(r):
    return "|".join([r["structure"], r["stretch"], r["range"], r["driver"],
                     r["h4_structure"], r["h4_stretch"], r["h4_driver"]])


panel["key"] = panel.apply(key_of, axis=1)
panel["half"] = np.where(panel["day"] < CUTOFF, "train", "test")
print(f"distinct MTF states observed: {panel['key'].nunique()} "
      f"(of {2*2*3*2*2*2*2} possible)")
print(f"train rows {int((panel['half']=='train').sum())}  "
      f"test rows {int((panel['half']=='test').sum())}")

out = {"built": time.time(), "schema": "basemap_mtf_v1",
       "key_fields": ["structure", "stretch", "range", "driver",
                      "h4_structure", "h4_stretch", "h4_driver"],
       "cutoff": CUTOFF, "horizons": [f"{h}d" for h in HORIZONS],
       "latest": latest, "keys": {}, "stability": {}}

for key, g in panel.groupby("key"):
    rec = {}
    for hz in HORIZONS:
        per = {"all": stats(g[f"r{hz}"], g[f"vol{hz}"])}
        for sym, gs in g.groupby("sym"):
            s = stats(gs[f"r{hz}"], gs[f"vol{hz}"])
            if s.get("n"):
                per[sym] = s
        rec[f"{hz}d"] = per
    out["keys"][key] = rec

    tr, te = g[g["half"] == "train"], g[g["half"] == "test"]
    st = {}
    for hz in HORIZONS:
        a, b = stats(tr[f"r{hz}"]), stats(te[f"r{hz}"])
        ok = (a.get("n", 0) >= MIN_N and b.get("n", 0) >= MIN_N
              and np.sign(a.get("median_pct", 0)) == np.sign(b.get("median_pct", 0))
              and abs(a.get("up_pct", 50) - b.get("up_pct", 50)) <= 15)
        st[f"{hz}d"] = {"train": a, "test": b, "stable": bool(ok)}
    out["stability"][key] = st

stable_any = {hz: [k for k, v in out["stability"].items() if v[f"{hz}d"]["stable"]]
              for hz in HORIZONS}
print("\n=== states STABLE across both halves (n>=30 each, same median sign, up% within 15pts) ===")
for hz in HORIZONS:
    print(f"  {hz}d: {len(stable_any[hz])} of {len(out['keys'])} states")

print("\n=== the stable 1d states, ranked by |median| ===")
rank = []
for k in stable_any[1]:
    a = out["stability"][k]["1d"]["train"]
    b = out["stability"][k]["1d"]["test"]
    allst = out["keys"][k]["1d"]["all"]
    rank.append((abs(allst["median_pct"]), k, allst, a, b))
rank.sort(reverse=True)
print(f"  {'state':<48}{'n':>6}{'up%':>7}{'med%':>8}{'trn med':>9}{'tst med':>9}{'volmed':>8}")
print("-" * 104)
for _, k, allst, a, b in rank[:18]:
    print(f"  {k:<48}{allst['n']:>6}{allst['up_pct']:>7.1f}{allst['median_pct']:>8.2f}"
          f"{a['median_pct']:>9.2f}{b['median_pct']:>9.2f}"
          f"{allst.get('vol_median_pct', float('nan')):>8.2f}")

# does adding the 4h view sharpen the daily-only base rate?
print("\n=== does the 4h overlay add anything over daily alone? (1d horizon) ===")
panel["dkey"] = panel.apply(lambda r: "|".join(
    [r["structure"], r["stretch"], r["range"], r["driver"]]), axis=1)
dsp, msp = [], []
for dk, g in panel.groupby("dkey"):
    if len(g) < 100:
        continue
    base_up = (g["r1"] > 0).mean() * 100
    sub = [( (gg["r1"] > 0).mean() * 100, len(gg)) for _, gg in g.groupby("key") if len(gg) >= MIN_N]
    if len(sub) < 2:
        continue
    spread = max(s[0] for s in sub) - min(s[0] for s in sub)
    dsp.append(base_up)
    msp.append(spread)
    print(f"  daily {dk:<32} n={len(g):>5} up%={base_up:>5.1f}  "
          f"4h sub-states={len(sub):>2}  up% spread={spread:>5.1f}pts")
if msp:
    print(f"\n  mean up% spread the 4h overlay opens inside a daily state: "
          f"{np.mean(msp):.1f} points")
    out["h4_adds_up_pct_spread_mean"] = round(float(np.mean(msp)), 2)

with io.open(os.path.join(HERE, "basemap_mtf.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print(f"\nwrote basemap_mtf.json ({len(out['keys'])} states, "
      f"{os.path.getsize(os.path.join(HERE, 'basemap_mtf.json'))/1048576:.2f} MB)")
