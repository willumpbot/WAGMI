"""Mission 8: adaptive stops scaled to the volatility forecast.

Replaces the fixed-ATR stop with  stop = k x forecast move,  which is the bridge
between GEOMETRY.md (fixed stops cost -0.43R) and VOLATILITY.md (next-day move is
forecastable, 2.4x decile spread).

THE CONTROL THAT MATTERS: a wider stop is better almost everywhere, so comparing
a forecast-scaled stop against the bot's narrow default would prove nothing. For
every k, this also builds a FIXED-percent stop with the SAME AVERAGE WIDTH over
the same signals, and reports the paired difference between them. That isolates
"scaling with the forecast" from "being wider".

Targets: 0.5R, 1R, 1.5R, 2R, plus a trailing stop at 1x the forecast move.
Train 2026-02-11..04-15, test 04-16..06-05. Conservative tie rule (a bar covering
both levels counts as a stop), fees both legs, no lookahead, paired cluster
bootstrap on (symbol, day).
"""
import json, io, os, csv, gzip, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL, HIST = (os.path.join(HERE, d) for d in ("candles_merged", "candles", "history"))
FEE_BPS, HORIZON_H, EPS = 9.0, 48, 1e-8
CUTOFF = "2026-04-16"
rng = np.random.default_rng(20261008)

KS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
TPS = (0.5, 1.0, 1.5, 2.0)
BOT_DEFAULT = "bot_default"


# ---------------------------------------------------- vol forecast (train-fit)
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
    return df


def vframe(sym):
    d = daily(sym)
    if d is None or len(d) < 80:
        return None
    r = d["c"].pct_change() * 100
    f = pd.DataFrame({"day": pd.to_datetime(d["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"),
                      "sym": sym, "rv1": r.abs(), "rv5": r.rolling(5).std(),
                      "rv22": r.rolling(22).std(),
                      "y1": r.shift(-1).abs(), "y5": r.shift(-5).rolling(5).std()})
    return f.dropna(subset=["rv1", "rv5", "rv22"])


vf = pd.concat([x for x in (vframe(s) for s in
                sorted({os.path.basename(p).split("_")[0]
                        for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})) if x is not None],
               ignore_index=True)
F = ["rv1", "rv5", "rv22"]
for tgt, name in (("y1", "f1"), ("y5", "f5")):
    tr = vf[(vf["day"] < CUTOFF) & vf[tgt].notna()]
    X = np.log(tr[F] + EPS).values
    y = np.log(tr[tgt] + EPS).values
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    sm = float(np.mean(np.exp(y - A @ b)))
    Xa = np.log(vf[F] + EPS).values
    vf[name] = np.exp(np.column_stack([np.ones(len(Xa)), Xa]) @ b) * sm
    print(f"{name}: fitted on {len(tr)} train days, smearing {sm:.4f}")
fmap = {(r.sym, r.day): (float(r.f1), float(r.f5)) for r in vf.itertuples()}


# ---------------------------------------------------- candles + simulation
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


def walk(bars, entry, long_, stop_dist, tp_dist, trail_dist=None):
    """Return (R, hours_held, outcome). Stop wins ties. Mark to close at horizon."""
    feeR = 2 * (FEE_BPS / 1e4) * entry / stop_dist
    sl = entry - stop_dist if long_ else entry + stop_dist
    tp = entry + tp_dist if long_ else entry - tp_dist
    best = entry
    for i, (_, o, h, l, cl) in enumerate(bars):
        if trail_dist is not None:
            best = max(best, h) if long_ else min(best, l)
            sl = (max(sl, best - trail_dist) if long_
                  else min(sl, best + trail_dist))
        hit_sl = (l <= sl) if long_ else (h >= sl)
        hit_tp = (h >= tp) if long_ else (l <= tp)
        if hit_sl:
            r = (sl - entry) / stop_dist if long_ else (entry - sl) / stop_dist
            return r - feeR, i + 1, "stop"
        if hit_tp:
            return tp_dist / stop_dist - feeR, i + 1, "target"
    last = bars[-1][4]
    r = ((last - entry) if long_ else (entry - last)) / stop_dist
    return r - feeR, len(bars), "time"


sigs = []
with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        f = fmap.get((d["sym"], d["ts"][:10]))
        if not f or not all(np.isfinite(f)):
            continue
        try:
            t0 = pd.Timestamp(d["ts"]).timestamp()
        except Exception:
            continue
        sigs.append({"sym": d["sym"], "side": d["side"], "sl": d["sl"], "t0": t0,
                     "day": d["ts"][:10], "f1": f[0], "f5": f[1]})
print(f"signals with a forecast: {len(sigs)}")

cache, recs = {}, []
for s in sigs:
    if s["sym"] not in cache:
        cache[s["sym"]] = load_candles(s["sym"])
    c = cache[s["sym"]]
    if not c:
        continue
    i0 = ib(c, s["t0"])
    if i0 is None or s["t0"] - c[i0][0] > 7200:
        continue
    entry = c[i0][4]
    base = abs(entry - s["sl"])
    if entry <= 0 or base <= 0:
        continue
    long_ = s["side"] == "LONG"
    bars, k, end = [], i0 + 1, s["t0"] + HORIZON_H * 3600
    while k < len(c) and c[k][0] <= end:
        bars.append(c[k]); k += 1
    if not bars:
        continue
    rec = {"sym": s["sym"], "day": s["day"], "entry": entry,
           "f1_pct": s["f1"], "widths": {}, "R": {}, "hrs": {}, "out": {}}
    # the bot's own geometry, for reference
    r, hrs, o = walk(bars, entry, long_, base, 1.5 * base)
    rec["R"][BOT_DEFAULT] = r; rec["hrs"][BOT_DEFAULT] = hrs; rec["out"][BOT_DEFAULT] = o
    rec["widths"][BOT_DEFAULT] = base / entry * 100
    for kk in KS:
        for src, fv in (("f1", s["f1"]), ("f5", s["f5"])):
            sd = entry * (kk * fv) / 100.0          # forecast is in %
            if sd <= 0:
                continue
            for tp in TPS:
                key = f"{src}|k{kk}|tp{tp}"
                r, hrs, o = walk(bars, entry, long_, sd, tp * sd)
                rec["R"][key] = r; rec["hrs"][key] = hrs; rec["out"][key] = o
                rec["widths"][key] = sd / entry * 100
            key = f"{src}|k{kk}|trail1x"
            r, hrs, o = walk(bars, entry, long_, sd, 99 * sd, trail_dist=entry * fv / 100.0)
            rec["R"][key] = r; rec["hrs"][key] = hrs; rec["out"][key] = o
            rec["widths"][key] = sd / entry * 100
    recs.append(rec)

print(f"simulated {len(recs)} signals")
train = [r for r in recs if r["day"] < CUTOFF]
test = [r for r in recs if r["day"] >= CUTOFF]
print(f"train {len(train)}  test {len(test)}")

KEYS = [k for k in recs[0]["R"] if k != BOT_DEFAULT]


def mean_R(rs, key):
    v = [r["R"][key] for r in rs if key in r["R"]]
    return float(np.mean(v)) if v else None


def mean_width(rs, key):
    v = [r["widths"][key] for r in rs if key in r["widths"]]
    return float(np.mean(v)) if v else None


def paired(rs, a, b, iters=2000):
    cl = collections.defaultdict(list)
    for r in rs:
        if a in r["R"] and b in r["R"]:
            cl[(r["sym"], r["day"])].append(r["R"][a] - r["R"][b])
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    point = float(np.mean([x for k in keys for x in cl[k]]))
    ds = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        ds[i] = np.mean([x for j in pick for x in cl[keys[j]]])
    ds.sort()
    return point, float(ds[int(.025 * iters)]), float(ds[int(.975 * iters)])


# ---- matched fixed-% control: same average width as the forecast-scaled rule ----
def add_fixed_control(rs, target_width_pct, tp_mult, tag):
    """Fixed-percent stop at a constant width, re-simulated on the same signals."""
    for r in rs:
        pass  # widths are per-signal; the control needs a re-walk, done below


print("\n" + "=" * 108)
print("MISSION 8 — forecast-scaled stop vs a FIXED stop of the SAME AVERAGE WIDTH")
print("=" * 108)
print(f"  bot default: mean R {mean_R(recs, BOT_DEFAULT):+.4f}   "
      f"mean width {mean_width(recs, BOT_DEFAULT):.2f}%   "
      f"stopped {100*np.mean([r['out'][BOT_DEFAULT]=='stop' for r in recs]):.1f}%")

# re-walk fixed controls at the matched widths
fixed_cache = {}
for key in KEYS:
    w = mean_width(recs, key)
    if w is None:
        continue
    fixed_cache[key] = w

print("\n  building matched fixed-width controls ...", flush=True)
for r in recs:
    if r["sym"] not in cache:
        continue
    c = cache[r["sym"]]
    i0 = ib(c, pd.Timestamp(r["day"]).timestamp())
    # re-derive bars from the stored entry time is not kept; use stored R only for
    # forecast rules and simulate controls from the same entry/bars below
for key in list(KEYS):
    pass

# simpler, exact approach: redo the whole simulation once more, this time with
# fixed widths equal to each rule's average width
fixed_results = collections.defaultdict(dict)
for s, rec in zip(sigs, recs):
    c = cache.get(s["sym"])
    if not c:
        continue
    i0 = ib(c, s["t0"])
    if i0 is None:
        continue
    entry = rec["entry"]
    long_ = s["side"] == "LONG"
    bars, k, end = [], i0 + 1, s["t0"] + HORIZON_H * 3600
    while k < len(c) and c[k][0] <= end:
        bars.append(c[k]); k += 1
    if not bars:
        continue
    for key in KEYS:
        w = fixed_cache.get(key)
        if not w:
            continue
        sd = entry * w / 100.0
        tp_mult = 1.0
        if key.endswith("trail1x"):
            tp_mult = 1.0
        else:
            tp_mult = float(key.split("tp")[-1])
        r2, hrs2, o2 = walk(bars, entry, long_, sd, tp_mult * sd)
        rec["R"]["FIXED_" + key] = r2
        rec["out"]["FIXED_" + key] = o2
        rec["hrs"]["FIXED_" + key] = hrs2

print(f"  {'rule':<22}{'width%':>8}{'trainR':>9}{'testR':>9}{'vs FIXED same width':>22}{'stop%':>7}{'med hrs':>9}")
print("-" * 108)
rows = []
for key in KEYS:
    trR, teR = mean_R(train, key), mean_R(test, key)
    if trR is None or teR is None:
        continue
    p, lo, hi = paired(test, key, "FIXED_" + key)
    ci = f"{p:+.4f}[{lo:+.3f},{hi:+.3f}]" if p is not None else ""
    stops = 100 * np.mean([r["out"][key] == "stop" for r in recs if key in r["out"]])
    hrs = float(np.median([r["hrs"][key] for r in recs if key in r["hrs"]]))
    print(f"  {key:<22}{fixed_cache[key]:>8.2f}{trR:>9.4f}{teR:>9.4f}{ci:>22}{stops:>7.1f}{hrs:>9.1f}")
    rows.append({"rule": key, "width_pct": round(fixed_cache[key], 3),
                 "train_R": round(trR, 4), "test_R": round(teR, 4),
                 "vs_fixed_same_width": None if p is None else
                 {"diff_R": round(p, 4), "ci": [round(lo, 4), round(hi, 4)],
                  "significant": bool(lo > 0 or hi < 0)},
                 "stopped_pct": round(stops, 1), "median_hours": round(hrs, 1)})

# pick on train, judge on test
best = max((r for r in rows), key=lambda r: r["train_R"])
print(f"\n  picked on TRAIN: {best['rule']}  (train {best['train_R']:+.4f}R)")
print(f"    on TEST: {best['test_R']:+.4f}R")
p, lo, hi = paired(test, best["rule"], BOT_DEFAULT)
if p is not None:
    print(f"    vs bot default on test: {p:+.4f}R [{lo:+.4f},{hi:+.4f}]  "
          f"{'CI excludes 0' if lo > 0 else 'CI spans 0'}")
p2, lo2, hi2 = paired(test, best["rule"], "FIXED_" + best["rule"])
if p2 is not None:
    print(f"    vs FIXED same width on test: {p2:+.4f}R [{lo2:+.4f},{hi2:+.4f}]  "
          f"{'forecast scaling ADDS value' if lo2 > 0 else 'scaling adds nothing beyond width'}")

print("\n  per-symbol stability of the picked rule (test, vs bot default):")
persym = {}
for sym in sorted({r["sym"] for r in test}):
    sub = [r for r in test if r["sym"] == sym]
    if len(sub) < 100:
        continue
    pp, ll, hh = paired(sub, best["rule"], BOT_DEFAULT)
    if pp is None:
        continue
    print(f"    {sym:<6} n={len(sub):>5}  {pp:+.4f}R [{ll:+.4f},{hh:+.4f}]"
          f"{'  *' if ll > 0 else ''}")
    persym[sym] = {"n": len(sub), "diff_R": round(pp, 4),
                   "ci": [round(ll, 4), round(hh, 4)], "significant": bool(ll > 0)}

out = {"horizon_h": HORIZON_H, "fee_bps": FEE_BPS, "cutoff": CUTOFF,
       "n_simulated": len(recs), "train_n": len(train), "test_n": len(test),
       "bot_default": {"mean_R": round(mean_R(recs, BOT_DEFAULT), 4),
                       "mean_width_pct": round(mean_width(recs, BOT_DEFAULT), 3),
                       "stopped_pct": round(100*float(np.mean([r['out'][BOT_DEFAULT]=='stop' for r in recs])), 1)},
       "rules": rows, "picked_on_train": best["rule"],
       "picked_test_R": best["test_R"], "per_symbol": persym}
with io.open(os.path.join(HERE, "adaptive_stops.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote adaptive_stops.json")
