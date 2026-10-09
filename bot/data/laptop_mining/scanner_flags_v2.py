"""MISSION 1 v2 — rebuilt after red team wkqz8m3br found three fatal defects in v1.

WHAT WAS WRONG IN v1 (all three verified by me before accepting):

 F1  DATA CONTAMINATION. The filter was `not s.endswith("_wspot")`, which excluded the wrapped-spot
     duplicates but let the IDENTICAL `*_spot` series through. 7 of the claimed "24 HL perps" were
     spot: AZTEC, BERA, HYPE, MON, PUMP, STABLE, TRUMP. They carry up to 70.5% STALE bars
     (o==h==l==c, i.e. no trading): BERA_spot 70.5%, TRUMP_spot 68.0%, MON_spot 65.3%, PUMP 40.0%.
     A stale run makes px == min(low[-20:]) exactly, so `on_20d_low` fires EVERY day of it: 63% of
     all on_20d_low firings came from those 7 series, and all 13 "top 1%" rows were spot
     denomination jumps (MON 0.000543 -> 0.0069 -> 0.000565), not meme explosions.
     FIX: exclude `_spot` and `_wspot`, and drop any series with >2% stale bars.

 F2  THE POWER TABLE WAS AN IDENTITY. v1 "injected" an effect by adding a scalar to every row. That
     shifts each week mean by delta and leaves mus.std(ddof=1) EXACTLY unchanged, so
     DETECTED <=> delta > 1.96*se - mean <=> delta > -ci_low. Verified: ma50 -ci_low=0.0435 ->
     "MDE 0.1"; on_20d_low -ci_low=1.2700 -> "MDE 2.0". The grid points were the first values above
     the CI bound. Worse, the "zero-injection arm (must NOT detect)" is the statement ci_low < 0,
     which IS the headline null verdict -- so it could not fail when the headline said null. v1's
     docstring claimed it "resamples genuinely"; it touches no RNG at all.
     FIX: a LAG PLACEBO. Shift each coin's firing indices by L positions (wrapping within the coin),
     which preserves per-coin firing counts AND within-coin clustering while destroying any real
     timing. Inject a known effect into the placebo firings and run the FULL decision criterion.
     Detection rate at delta=0 is the test's SIZE (should land near 5%); at delta>0 it is POWER.
     This can fail, and if size comes back far from 5% the whole design is void.

 F3  THE MEDIAN WAS A CONSTRUCTION ARTIFACT. "median excess = -0.180% = exactly the fee, at every
     flag and horizon" is forced: net = x - 0.18 and subtracting the per-date cross-sectional median
     makes median(x) == 0 identically (748 rows are exactly zero -- the median coin on odd-count
     dates). It is true of the FULL PANEL too, so it says nothing about the flags.
     FIX: report it as an identity where it belongs, and lean on win rate and the null instead.

v1's arithmetic reproduced exactly under review; it was the inference on top that failed.
"""
import json, io, os, csv, glob, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_BPS = 9.0
FEE = 2 * FEE_BPS / 100.0
EPS = 1e-8
START = "2023-01-01"
HORIZONS = (1, 5)
NULL_DRAWS = 2000
MAX_STALE = 0.02          # F1: drop any series with >2% o==h==l==c bars
PLACEBO_SETS = 120        # F2: lag-placebo firing sets per (flag, horizon)
rng = np.random.default_rng(20261009)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def ema(v, n):
    k = 2.0 / (n + 1)
    out, e = [], v[0]
    for x in v:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def load(sym):
    rows = []
    with io.open(os.path.join(HIST, f"{sym}_1d.csv"), encoding="utf-8",
                 errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"])))
            except (TypeError, ValueError, KeyError):
                continue
    rows.sort()
    return rows


# ---------- F1: build a clean universe ----------
allsyms = sorted({os.path.basename(p).split("_1d")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
dropped = {}
syms = []
for s in allsyms:
    if s.endswith("_spot") or s.endswith("_wspot"):
        dropped[s] = "spot series (not a perp)"
        continue
    d = load(s)
    if len(d) < 120:
        dropped[s] = f"only {len(d)} bars"
        continue
    stale = sum(1 for (_, o, h, l, c) in d if o == h == l == c) / len(d)
    if stale > MAX_STALE:
        dropped[s] = f"{100*stale:.1f}% stale bars"
        continue
    syms.append(s)
print(f"universe: {len(syms)} perps kept, {len(dropped)} dropped")
for k, v in list(dropped.items())[:10]:
    print(f"    dropped {k:<16} {v}")
if len(dropped) > 10:
    print(f"    ... and {len(dropped)-10} more")

obs = []
firing_idx = collections.defaultdict(lambda: collections.defaultdict(list))  # flag -> sym -> row pos
percoin_rows = collections.defaultdict(list)

for s in syms:
    d = load(s)
    t = [x[0] for x in d]
    o = [x[1] for x in d]
    l = [x[3] for x in d]
    c = [x[4] for x in d]
    day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") for x in t]
    rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
    e50 = ema(c, 50)
    for i in range(60, len(c) - max(HORIZONS) - 1):
        if day[i] < START:
            continue
        rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
        if rv22 <= 0 or rv5 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        em = math.exp(z) * Y1S
        if em <= 0:
            continue
        px = c[i]
        lo20 = min(l[i - 19:i + 1])
        entry = o[i + 1]
        if entry <= 0:
            continue
        fwd = {}
        for hz in HORIZONS:
            if i + hz >= len(c):
                fwd = None
                break
            fwd[hz] = (c[i + hz] / entry - 1) * 100
        if fwd is None:
            continue
        wk = datetime.date.fromisoformat(day[i]).isocalendar()
        rec = {"sym": s, "day": day[i], "week": f"{wk[0]}-W{wk[1]:02d}",
               "ma50_pullback": (0 <= (px / e50[i] - 1) * 100 <= 0.5 * em),
               "on_20d_low": (lo20 <= px and (px / lo20 - 1) * 100 <= 0.5 * em),
               "r1": fwd[1], "r5": fwd[5]}
        pos = len(percoin_rows[s])
        percoin_rows[s].append(rec)
        obs.append(rec)
        for f in ("ma50_pullback", "on_20d_low"):
            if rec[f]:
                firing_idx[f][s].append(pos)

print(f"\npanel: {len(obs)} coin-days, {len({r['sym'] for r in obs})} perps, "
      f"{min(r['day'] for r in obs)} -> {max(r['day'] for r in obs)}")

bydate = collections.defaultdict(list)
for r in obs:
    bydate[r["day"]].append(r)
keep = []
for dy, rs in bydate.items():
    if len(rs) < 5:
        continue
    for hz in HORIZONS:
        med = float(np.median([r[f"r{hz}"] for r in rs]))
        for r in rs:
            r[f"x{hz}"] = r[f"r{hz}"] - med
    keep.extend(rs)
obs = keep
print(f"after requiring >=5 coins per date: {len(obs)} rows")
# stale check on the surviving panel
flat = sum(1 for r in obs if r["r1"] == 0.0 and r["r5"] == 0.0)
print(f"rows with zero 1d AND 5d return (stale proxy): {flat} ({100*flat/len(obs):.2f}%)\n")


def net(r, hz, side):
    return (r[f"x{hz}"] if side == "long" else -r[f"x{hz}"]) - FEE


def week_stats(rows, hz, side, shift=0.0):
    byw = collections.defaultdict(list)
    for r in rows:
        byw[r["week"]].append(net(r, hz, side) + shift)
    mus = np.array([np.mean(v) for v in byw.values()])
    n = len(mus)
    if n < 4:
        return float("nan"), float("nan"), (float("nan"), float("nan")), n
    m = float(mus.mean())
    se = float(mus.std(ddof=1)) / math.sqrt(n)
    return m, (m / se if se > 0 else float("nan")), (m - 1.96 * se, m + 1.96 * se), n


def null_p(fired, hz, side, shift=0.0, draws=NULL_DRAWS):
    """Same coins, same counts, random dates. One-sided: is the real mean above random dates?"""
    real = float(np.mean([net(r, hz, side) + shift for r in fired]))
    percoin = collections.Counter(r["sym"] for r in fired)
    nulls = np.empty(draws)
    for b in range(draws):
        vals = []
        for sym, k in percoin.items():
            p = percoin_rows[sym]
            idx = rng.integers(0, len(p), k)
            vals.extend(net(p[j], hz, side) for j in idx if f"x{hz}" in p[j])
        nulls[b] = np.mean(vals) if vals else np.nan
    return real, float(np.nanmean(nulls)), float(np.nanmean(nulls >= real))


def lag_placebo_sets(flag, k=PLACEBO_SETS):
    """F2: shift each coin's firing positions by L (wrapping), preserving count AND clustering."""
    sets = []
    for _ in range(k):
        rows = []
        for sym, idxs in firing_idx[flag].items():
            p = percoin_rows[sym]
            if len(p) < 50 or not idxs:
                continue
            L = int(rng.integers(30, max(31, len(p) - 1)))
            for i in idxs:
                r = p[(i + L) % len(p)]
                if f"x1" in r:
                    rows.append(r)
        if rows:
            sets.append(rows)
    return sets


FLAGS = [("ma50_pullback", "long"), ("on_20d_low", "short")]
out = {"panel_rows": len(obs), "perps": len({r["sym"] for r in obs}),
       "universe_kept": syms, "universe_dropped": dropped,
       "max_stale_allowed": MAX_STALE,
       "start": min(r["day"] for r in obs), "end": max(r["day"] for r in obs),
       "fee_bps_round_trip": 2 * FEE_BPS, "flags": {}}

for flag, side in FLAGS:
    fired = [r for r in obs if r[flag]]
    print("=" * 108)
    print(f"{flag}  scored {side.upper()}   {len(fired)} firings "
          f"({100*len(fired)/len(obs):.1f}% of panel), {len({r['sym'] for r in fired})} coins")
    print("=" * 108)
    out["flags"][flag] = {"side": side, "n_fired": len(fired),
                          "pct_of_panel": round(100 * len(fired) / len(obs), 2),
                          "horizons": {}}
    print(f"  {'hz':>3}{'mean excess':>13}{'week mean':>11}{'week t':>8}{'week CI95':>22}"
          f"{'null mean':>11}{'null p':>8}{'win%':>7}{'panel win%':>12}  verdict")
    print("-" * 108)
    for hz in HORIZONS:
        real, nm, p1 = null_p(fired, hz, side)
        wm, t, ci, nw = week_stats(fired, hz, side)
        v = np.array([net(r, hz, side) for r in fired])
        av = np.array([net(r, hz, side) for r in obs])
        earned = (p1 < 0.05) and (ci[0] > 0)
        verdict = "EARNED" if earned else ("beats random, CI covers 0" if p1 < 0.05
                                           else "null (no timing edge)")
        print(f"  {hz:>3}{real:>+13.4f}{wm:>+11.4f}{t:>8.2f}  [{ci[0]:+.4f},{ci[1]:+.4f}]"
              f"{nm:>+11.4f}{p1:>8.3f}{100*(v>0).mean():>6.1f}%{100*(av>0).mean():>11.1f}%  {verdict}")
        out["flags"][flag]["horizons"][f"{hz}d"] = {
            "mean_excess": round(real, 4), "week_mean": round(wm, 4),
            "week_t": round(float(t), 2), "week_ci": [round(ci[0], 4), round(ci[1], 4)],
            "weeks": nw, "null_mean": round(nm, 4), "null_p": round(p1, 4),
            "win_rate_pct": round(100 * float((v > 0).mean()), 2),
            "panel_win_rate_pct": round(100 * float((av > 0).mean()), 2),
            "earned": bool(earned)}

    # ---------- F2: honest power via lag placebo ----------
    print(f"\n  HONEST POWER (lag placebo: shift firing dates within each coin, keep count AND")
    print(f"  clustering, then inject a known effect and run the FULL criterion)")
    print(f"  {'injected':>10}{'1d size/power':>16}{'5d size/power':>16}")
    print("  " + "-" * 44)
    sets = lag_placebo_sets(flag)
    pw = {}
    for delta in (0.0, 0.25, 0.5, 1.0, 2.0):
        line = {}
        for hz in HORIZONS:
            det = 0
            for rows in sets:
                _, _, pp = null_p(rows, hz, side, shift=delta, draws=200)
                _, _, cci, nn = week_stats(rows, hz, side, shift=delta)
                if nn >= 4 and pp < 0.05 and cci[0] > 0:
                    det += 1
            line[hz] = det / len(sets) if sets else float("nan")
        pw[str(delta)] = {f"{h}d": round(line[h], 3) for h in HORIZONS}
        tag = "   <- SIZE (want ~0.05)" if delta == 0 else ""
        print(f"  {delta:>10.2f}{line[1]:>16.3f}{line[5]:>16.3f}{tag}")
    out["flags"][flag]["power"] = pw
    size1 = pw["0.0"]["1d"]
    mde = next((d for d in (0.25, 0.5, 1.0, 2.0) if pw[str(d)]["1d"] >= 0.8), None)
    print(f"  size at delta=0: {size1:.3f}  "
          f"{'OK' if 0.01 <= size1 <= 0.12 else 'MISCALIBRATED - design void'}")
    print(f"  80%-power MDE at 1d: {str(mde)+'% per trade' if mde else 'not reached within 2%'}")
    out["flags"][flag]["size_1d"] = size1
    out["flags"][flag]["mde80_1d_pct"] = mde
    print()

print("=" * 108)
print("THE MEDIAN CLAIM FROM v1 — it was an identity, recorded here so it is not re-used")
print("=" * 108)
for hz in HORIZONS:
    allx = np.array([r[f"x{hz}"] for r in obs])
    print(f"  hz={hz}: median of the raw excess x = {np.median(allx):+.6f} "
          f"(exactly 0 by construction: the per-date cross-sectional median is subtracted)")
    print(f"         so median(net) == -fee == {-FEE:+.3f} for ANY subset, flags included.")
out["median_is_identity"] = True

print("\n" + "=" * 108)
print("VERDICT")
print("=" * 108)
for flag, side in FLAGS:
    f = out["flags"][flag]
    e = [k for k, v in f["horizons"].items() if v["earned"]]
    print(f"  {flag:<16} ({side:<5}) earned: {e if e else 'NO HORIZON'}   "
          f"size {f['size_1d']:.3f}, 80%-power MDE {f['mde80_1d_pct']}%")
any_e = any(v["earned"] for f in out["flags"].values() for v in f["horizons"].values())
out["verdict"] = ("a flag earned its label" if any_e
                  else "neither flag beats random dates in the same coin after fees, on clean perps")
print(f"\n  => {out['verdict']}")
with io.open(os.path.join(HERE, "scanner_flags_v2.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote scanner_flags_v2.json")
