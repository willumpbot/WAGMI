"""Mission 13: should the IC-muted strategies be flipped (traded inverted)?

Five strategies are muted at weight 0: confidence_scorer, multi_tier_quality,
bollinger_squeeze, regime_trend, mean_reversion. The gate currently drops ~99.8%
of signals, so the owner wants to know whether inverting them has an edge.

DATA LIMIT, stated up front: only ONE of the five appears as a label anywhere in
the laptop's data -- `multi_tier_quality` (4,315 rows in the legacy
signal_outcomes log). `confidence_scorer` and `mean_reversion` appear nowhere.
So this does two things:
  A. tests multi_tier_quality directly, as-is and inverted
  B. builds faithful PROXIES for bollinger_squeeze / regime_trend /
     mean_reversion from price alone and tests those inverted, since inverting a
     rule is just taking the opposite side of the same condition

Method: forward-grade on validated candles, 9 bps fees, block cluster bootstrap
on (symbol, day), train/test sign stability. Inverting is exactly the negation of
the signed return, so a flat original implies a flat inversion -- the test is
whether either direction clears fees.
"""
import json, io, os, csv, glob, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL, HIST = (os.path.join(HERE, d) for d in ("candles_merged", "candles", "history"))
LEGACY = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/logs/signal_outcomes_regime_backfilled.jsonl"
FEE_BPS = 9.0
rng = np.random.default_rng(20261008)


def load_candles(sym):
    for d in (MERGED, HL):
        p = os.path.join(d, f"{sym}_1h.csv")
        if os.path.exists(p):
            out = []
            with io.open(p, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                                    float(r["l"]), float(r["c"])))
                    except (TypeError, ValueError):
                        continue
            out.sort()
            return out
    return None


def ib(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


def ia(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] >= t:
            best = m; hi = m - 1
        else:
            lo = m + 1
    return best


def boot(rows, col, iters=2500):
    cl = collections.defaultdict(list)
    for r in rows:
        v = r.get(col)
        if v is not None and np.isfinite(v):
            cl[(r["sym"], r["day"])].append(v)
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


report = {"fee_bps": FEE_BPS, "data_limit":
          "only multi_tier_quality has a real label in laptop data; "
          "confidence_scorer and mean_reversion appear nowhere; "
          "bollinger_squeeze / regime_trend / mean_reversion tested via price proxies",
          "strategies": {}}

# ============================== A. the one real label
print("=" * 104)
print("A. multi_tier_quality — the only muted strategy with a real label in laptop data")
print("=" * 104)
cache, rows = {}, []
H = {"1h": 3600, "4h": 14400, "12h": 43200}
with io.open(LEGACY, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("strat") != "multi_tier_quality":
            continue
        sym, side, ts = d.get("sym"), (d.get("side") or "").upper(), d.get("ts")
        if not sym or side not in ("BUY", "SELL", "LONG", "SHORT") or not isinstance(ts, (int, float)):
            continue
        if sym not in cache:
            cache[sym] = load_candles(sym)
        c = cache[sym]
        if not c:
            continue
        i0 = ib(c, ts)
        if i0 is None or ts - c[i0][0] > 7200:
            continue
        p0 = c[i0][4]
        if p0 <= 0:
            continue
        sgn = 1.0 if side in ("BUY", "LONG") else -1.0
        import datetime
        rec = {"sym": sym, "day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
               "passed": bool(d.get("passed"))}
        ok = False
        for nm, dt in H.items():
            j = ia(c, ts + dt)
            if j is None or c[j][0] - (ts + dt) > 3600:
                rec["e_" + nm] = None
                rec["inv_" + nm] = None
                continue
            e = 1e4 * sgn * (c[j][1] - p0) / p0 - FEE_BPS
            rec["e_" + nm] = e
            # inverting takes the opposite side: the raw return flips, fees stay
            rec["inv_" + nm] = -(e + FEE_BPS) - FEE_BPS
            ok = True
        if ok:
            rows.append(rec)

print(f"  graded rows: {len(rows)}")
if rows:
    days = sorted({r["day"] for r in rows})
    cut = days[int(len(days) * 0.6)]
    print(f"  span {days[0]} -> {days[-1]}, split {cut}")
    print(f"\n  {'slice':<26}{'n':>6}{'as-is 4h':>11}{'CI95':>22}{'inverted 4h':>13}{'CI95':>22}")
    print("-" * 104)
    res = {}
    for lab, sub in (("all", rows),
                     ("train", [r for r in rows if r["day"] < cut]),
                     ("test", [r for r in rows if r["day"] >= cut])):
        if len(sub) < 13:
            continue
        p, lo, hi = boot(sub, "e_4h")
        ip, ilo, ihi = boot(sub, "inv_4h")
        if p is None or ip is None:
            continue
        s1 = "*" if (lo > 0 or hi < 0) else " "
        s2 = "*" if (ilo > 0 or ihi < 0) else " "
        print(f"  multi_tier_quality {lab:<8}{len(sub):>6}{p:>10.1f}{s1}"
              f"[{lo:>7.1f},{hi:>7.1f}]".rjust(22) + f"{ip:>12.1f}{s2}"
              f"[{ilo:>7.1f},{ihi:>7.1f}]".rjust(22))
        res[lab] = {"n": int(len(sub)), "as_is_4h_bps": round(p, 2),
                    "as_is_ci": [round(lo, 2), round(hi, 2)],
                    "inverted_4h_bps": round(ip, 2),
                    "inverted_ci": [round(ilo, 2), round(ihi, 2)],
                    "as_is_sig": bool(lo > 0 or hi < 0),
                    "inverted_sig": bool(ilo > 0 or ihi < 0)}
    report["strategies"]["multi_tier_quality"] = {"source": "real label", "results": res}

# ============================== B. proxies from price
print("\n" + "=" * 104)
print("B. PROXIES for the muted strategies with no label, tested inverted")
print("   (inverting a condition = taking the opposite side of the same condition)")
print("=" * 104)


def daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df


# Restrict to coins with long, validated history. The first run swept in all 41
# symbols including newly-listed memes, which produced +309 bps/day cells -- an
# artefact of tiny illiquid names, not a strategy result.
MAJORS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]
prox = []
for s in MAJORS:
    d = daily(s)
    if d is None or len(d) < 150:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bb = (c - ma20) / (2 * sd20).replace(0, np.nan)
    bw = (2 * sd20) / ma20            # bandwidth; a "squeeze" is a low-bandwidth regime
    dd = c.diff()
    gain = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    r1 = (c.shift(-1) / c - 1) * 1e4
    out = pd.DataFrame({"sym": s, "day": d["day"], "r1_bps": r1})
    # regime_trend: long when EMA20>EMA50, short otherwise
    out["regime_trend"] = np.where(e20 > e50, 1, -1)
    # bollinger_squeeze: in the lowest-bandwidth tercile, trade the band break
    sq = bw < bw.rolling(100).quantile(0.33)
    out["bollinger_squeeze"] = np.where(sq & (bb > 0), 1, np.where(sq & (bb < 0), -1, 0))
    # mean_reversion: fade RSI extremes
    out["mean_reversion"] = np.where(rsi > 70, -1, np.where(rsi < 30, 1, 0))
    prox.append(out.iloc[60:])
pp = pd.concat(prox, ignore_index=True).dropna(subset=["r1_bps"])
days = sorted(pp["day"].unique())
cut = days[int(len(days) * 0.6)]
pp["half"] = np.where(pp["day"] < cut, "train", "test")
print(f"  proxy panel {len(pp)} coin-days, {pp['sym'].nunique()} coins, split {cut}")
print(f"\n  {'proxy / half':<34}{'n':>6}{'as-is':>10}{'CI95':>21}{'inverted':>11}{'CI95':>21}")
print("-" * 104)
for col in ("regime_trend", "bollinger_squeeze", "mean_reversion"):
    res = {}
    for half in ("train", "test"):
        sub = pp[(pp["half"] == half) & (pp[col] != 0)].copy()
        if len(sub) < 50:
            continue
        sub["e"] = sub[col] * sub["r1_bps"] - FEE_BPS
        sub["inv"] = -sub[col] * sub["r1_bps"] - FEE_BPS
        recs = sub.to_dict("records")
        p, lo, hi = boot(recs, "e")
        ip, ilo, ihi = boot(recs, "inv")
        if p is None:
            continue
        s1 = "*" if (lo > 0 or hi < 0) else " "
        s2 = "*" if (ilo > 0 or ihi < 0) else " "
        print(f"  {col + ' / ' + half:<34}{len(sub):>6}{p:>9.1f}{s1}"
              f"[{lo:>6.1f},{hi:>6.1f}]".rjust(21) + f"{ip:>10.1f}{s2}"
              f"[{ilo:>6.1f},{ihi:>6.1f}]".rjust(21))
        res[half] = {"n": int(len(sub)), "as_is_bps": round(p, 2),
                     "as_is_ci": [round(lo, 2), round(hi, 2)],
                     "inverted_bps": round(ip, 2),
                     "inverted_ci": [round(ilo, 2), round(ihi, 2)],
                     "as_is_sig": bool(lo > 0 or hi < 0),
                     "inverted_sig": bool(ilo > 0 or ihi < 0)}
    report["strategies"][col] = {"source": "price proxy", "results": res}

print("\n" + "=" * 104)
print("VERDICT")
print("=" * 104)
# A claim requires the inversion to be positive AND SIGN-STABLE across halves.
# An inversion that only works in the test half is the same instability that
# muted the strategy in the first place, not an edge.
any_sig = False
for name, v in report["strategies"].items():
    res = v.get("results") or {}
    tr, te = res.get("train"), res.get("test")
    if not tr or not te:
        print(f"  {name}: not testable (missing a half)")
        continue
    stable = (tr["inverted_bps"] > 0) == (te["inverted_bps"] > 0)
    if te.get("inverted_sig") and te["inverted_bps"] > 0 and stable:
        any_sig = True
        print(f"  {name}: INVERTED positive on test AND sign-stable "
              f"({tr['inverted_bps']:+.1f} -> {te['inverted_bps']:+.1f} bps) -> candidate to flip")
    elif te.get("inverted_sig") and te["inverted_bps"] > 0:
        print(f"  {name}: inverted looks positive on test ({te['inverted_bps']:+.1f}) but the sign "
              f"FLIPS across halves ({tr['inverted_bps']:+.1f} -> {te['inverted_bps']:+.1f}) -> reject")
    else:
        print(f"  {name}: no inversion edge (test {te['inverted_bps']:+.1f} bps {te['inverted_ci']})")
if not any_sig:
    print("\n  Nothing is both significantly positive on test AND sign-stable. KEEP THE GATE.")
report["verdict"] = ("flip at least one" if any_sig else
                     "keep the gate: no inversion is significantly positive out of sample")
report["note_confidence_scorer"] = ("no label and no faithful price proxy exists; untested")
with io.open(os.path.join(HERE, "muted_flip.json"), "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
print("\nwrote muted_flip.json")
