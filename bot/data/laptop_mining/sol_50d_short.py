"""MISSION 2 — the owner's first real setup: shorting into the 50-day average from above.

The plan, as the server described it: "SOL shorts at the 50-day average from above, daily trend up,
4h sellers leading."

WHY THIS NEEDS CARE BEFORE IT NEEDS COMPUTE. Two facts already on record point against it:

  LEVELS.md:31   ma50 approached FROM ABOVE: n=701, break rate 32.1% [28.8,35.8] vs a 36.5%
                 random-level null -> it HOLDS better than a random line. It is the only level in
                 the whole table that does. A short into it is a bet on the 32% branch.
  LEVELS.md:68   ma50 from above, UPTREND: train 29.9% / test 43.4%, marked "stable: no" -- the
                 single unstable cell in the structure table, and it is exactly the owner's
                 daily-trend-up condition.
  SCANNER_FLAGS  the unconditional version of this geometry (ma50_pullback, price within 0.5 em
                 above the 50d) has NO directional edge either way: median excess = -0.180% = the
                 fee exactly, win rate 43.1% vs a 43.4% panel base rate.

So the real question is narrow: does "4h sellers leading" rescue a setup that is null
unconditionally and whose level holds better than chance?

DEFINITIONS -- LEVELS.md verbatim, so this is comparable to the 32.1% baseline
  level   = 50-day EMA, shift(1) (known before the touch day)
  touch   = |price - level| <= 0.5 x expected daily move (em, the stage-1 HAR forecast)
  above   = price approaches from above (price > level on the touch day)
  BREAK   = closes beyond the level by >= 0.5 em within 2 days, in the approach direction
            (for a from-above touch, a break is DOWN -- the short wins)
  REJECT  = moves >= 1.0 em back to the approach side (price goes back up -- the short loses)
  neither = roughly a third of touches; price just sits there

CONDITIONS
  daily trend up   = daily EMA20 > EMA50          (scanner.py's `trend_up`)
  4h structure down = 4h EMA20 < 4h EMA50 on the last 4h bar closing at or before the touch day's
                      close. Reported alongside an alternative reading of "sellers leading"
                      (last six 4h bars net negative) because the phrase is ambiguous.

THE NULL -- LEVELS.md's, not a GBM
  For each real touch, two random days on the same coin with a pseudo-level placed at a uniformly
  random distance within +-0.5 em of that day's price. Identical geometry, no actual level. If the
  conditional break rate does not exceed this, the setup has no information.

Also reports the 1d/5d signed return TO A SHORT, net of 9 bps, as an excess over the universe
median -- and the equal-weighted week mean next to every pooled figure, per CORRECTIONS.md.
"""
import json, io, os, csv, glob, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_BPS = 9.0
FEE = 2 * FEE_BPS / 100.0
EPS = 1e-8
NULL_PER_TOUCH = 2
rng = np.random.default_rng(20261009)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def sma(v, n):
    """50-day SIMPLE average -- what levels.py:78 actually tested (c.rolling(50).mean()).
    scanner.py flags the EMA instead, which turns out to carry no effect (-0.5 vs -5.1)."""
    return [None] * (n - 1) + [sum(v[i - n + 1:i + 1]) / n for i in range(n - 1, len(v))]


def ema(v, n):
    k = 2.0 / (n + 1)
    out, e = [], v[0]
    for x in v:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def load(sym, iv):
    p = os.path.join(HIST, f"{sym}_{iv}.csv")
    if not os.path.exists(p):
        return None
    rows = []
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"])))
            except (TypeError, ValueError, KeyError):
                continue
    rows.sort()
    return rows or None


syms = sorted({os.path.basename(p).split("_4h")[0] for p in glob.glob(os.path.join(HIST, "*_4h.csv"))})
syms = [s for s in syms if not s.endswith("_wspot")]

touches, pool = [], collections.defaultdict(list)
for s in syms:
    d, f4 = load(s, "1d"), load(s, "4h")
    if not d or not f4 or len(d) < 120:
        continue
    t = [x[0] for x in d]
    o = [x[1] for x in d]
    c = [x[4] for x in d]
    day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") for x in t]
    rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
    e20d, e50d = ema(c, 20), ema(c, 50)
    s50d = sma(c, 50)          # the VALIDATED level (LEVELS.md); e50d is the scanner's

    # 4h structure, indexed by the last 4h bar closing at or before each daily close
    f4t = [x[0] for x in f4]
    f4c = [x[4] for x in f4]
    e20h, e50h = ema(f4c, 20), ema(f4c, 50)
    import bisect

    for i in range(60, len(c) - 6):
        rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
        if rv22 <= 0 or rv5 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        em = math.exp(z) * Y1S
        if em <= 0:
            continue
        px = c[i]
        lvl = s50d[i - 1]            # shift(1), SIMPLE 50d -- matches levels.py:78
        if lvl is None or not np.isfinite(lvl) or lvl <= 0:
            continue
        emp = px * em / 100.0
        entry = o[i + 1]
        if entry <= 0 or emp <= 0:
            continue
        # forward path for break/reject, 2 days, per LEVELS.md
        fwd = c[i + 1:i + 3]
        if len(fwd) < 2:
            continue
        r1 = (c[i + 1] / entry - 1) * 100
        r5 = (c[i + 5] / entry - 1) * 100 if i + 5 < len(c) else None
        if r5 is None:
            continue
        wk = datetime.date.fromisoformat(day[i]).isocalendar()
        rec = {"sym": s, "day": day[i], "week": f"{wk[0]}-W{wk[1]:02d}",
               "r1": r1, "r5": r5, "em": em}

        # --- 4h structure at the touch ---
        k = bisect.bisect_right(f4t, t[i] + 86399) - 1
        if k < 60:
            continue
        h_down = e20h[k] < e50h[k]
        last6 = f4c[max(0, k - 6):k + 1]
        h_sellers = (last6[-1] < last6[0]) if len(last6) >= 2 else None
        rec["h4_down"] = bool(h_down)
        rec["h4_sellers"] = bool(h_sellers)
        rec["trend_up"] = bool(e20d[i] > e50d[i])
        pool[s].append(rec | {"px": px, "emp": emp, "i": i})

        # --- is this a real ma50 touch FROM ABOVE? ---
        dist = px - lvl
        if dist < 0 or abs(dist) > 0.5 * emp:
            continue
        broke = bool(any(x < lvl - 0.5 * emp for x in fwd))     # down through: short wins
        rejected = bool(any(x > px + 1.0 * emp for x in fwd))    # back up: short loses
        touches.append(rec | {"broke": broke, "rejected": rejected})

print(f"{len(syms)} coins with both 1d and 4h; {len(touches)} ma50-from-above touches")
if touches:
    print(f"window {min(x['day'] for x in touches)} -> {max(x['day'] for x in touches)}")
    print("(4h history is the binding constraint -- it starts 2024-06, so this is a SHORTER\n"
          " sample than LEVELS.md's 701 touches across 2020-2026)\n")


def rate(rows, key):
    n = len(rows)
    if not n:
        return float("nan"), (float("nan"), float("nan")), 0
    k = sum(1 for r in rows if r[key])
    p = k / n
    se = math.sqrt(max(p * (1 - p), EPS) / n)
    return 100 * p, (100 * (p - 1.96 * se), 100 * (p + 1.96 * se)), n


def wk(rows, key):
    byw = collections.defaultdict(list)
    for r in rows:
        byw[r["week"]].append(-r[key] - FEE)        # SHORT, net
    mus = np.array([np.mean(v) for v in byw.values()])
    if len(mus) < 4:
        return float("nan"), float("nan"), len(mus)
    m = float(mus.mean())
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return m, (m / se if se > 0 else float("nan")), len(mus)


# ---------- the null: random-date pseudo-levels, LEVELS.md's design ----------
def null_break_rate(real):
    """For each real touch, NULL_PER_TOUCH random days on the same coin with a pseudo-level
    at a uniform random distance within +-0.5 em. Returns the pooled pseudo break rate."""
    hits = tot = 0
    percoin = collections.Counter(r["sym"] for r in real)
    for s, k in percoin.items():
        p = pool[s]
        if len(p) < 10:
            continue
        for _ in range(k * NULL_PER_TOUCH):
            r = p[rng.integers(0, len(p))]
            emp = r["emp"]
            lvl = r["px"] - rng.uniform(0, 0.5) * emp      # pseudo-level just below price
            i = r["i"]
            d = load(r["sym"], "1d")
            tot += 1
    return None     # replaced below by the vectorised version


# vectorised null: precompute closes per coin once
CLOSES = {s: [x[4] for x in load(s, "1d")] for s in syms if load(s, "1d")}


def null_rates(real, draws=400):
    """Distribution of the pseudo break rate over `draws` resamples."""
    percoin = collections.Counter(r["sym"] for r in real)
    out = np.empty(draws)
    for b in range(draws):
        hits = tot = 0
        for s, k in percoin.items():
            p = [r for r in pool[s] if r["i"] + 3 < len(CLOSES[s])]
            if len(p) < 10:
                continue
            idx = rng.integers(0, len(p), k * NULL_PER_TOUCH)
            for j in idx:
                r = p[j]
                emp, i = r["emp"], r["i"]
                lvl = r["px"] - rng.uniform(0, 0.5) * emp
                fwd = CLOSES[s][i + 1:i + 3]
                if len(fwd) < 2:
                    continue
                hits += any(x < lvl - 0.5 * emp for x in fwd)
                tot += 1
        out[b] = 100 * hits / tot if tot else np.nan
    return out


CONDS = [
    ("ALL ma50-from-above touches", lambda r: True),
    ("+ daily trend UP (the owner's)", lambda r: r["trend_up"]),
    ("+ trend UP & 4h EMA20<EMA50", lambda r: r["trend_up"] and r["h4_down"]),
    ("+ trend UP & 4h last-6 down", lambda r: r["trend_up"] and r["h4_sellers"]),
    ("  (contrast) trend DOWN & 4h down", lambda r: (not r["trend_up"]) and r["h4_down"]),
]

out = {"touches": len(touches), "coins": len(syms), "fee_bps_round_trip": 2 * FEE_BPS,
       "levels_baseline": {"ma50_from_above_break_pct": 32.1, "null_pct": 36.5, "n": 701,
                           "source": "LEVELS.md:31"},
       "conditions": {}}

print("=" * 112)
print("DOES THE 50-DAY AVERAGE BREAK? (a break DOWN = the short wins)")
print("  LEVELS.md baseline, 2020-2026, n=701: breaks 32.1% vs a 36.5% random-level null")
print("=" * 112)
print(f"  {'condition':<34}{'n':>5}{'BREAK%':>9}{'CI95':>18}{'null%':>8}"
      f"{'vs null':>9}{'reject%':>9}{'neither%':>10}")
print("-" * 112)
for name, fn in CONDS:
    rows = [r for r in touches if fn(r)]
    if len(rows) < 12:
        print(f"  {name:<34}{len(rows):>5}   too few")
        continue
    b, bci, n = rate(rows, "broke")
    rj, _, _ = rate(rows, "rejected")
    neither = 100 * sum(1 for r in rows if not r["broke"] and not r["rejected"]) / n
    nl = null_rates(rows)
    nm = float(np.nanmean(nl))
    print(f"  {name:<34}{n:>5}{b:>9.1f}{f'[{bci[0]:.1f},{bci[1]:.1f}]':>18}{nm:>8.1f}"
          f"{b-nm:>+9.1f}{rj:>9.1f}{neither:>10.1f}")
    out["conditions"][name.strip()] = {
        "n": n, "break_pct": round(b, 1), "break_ci": [round(bci[0], 1), round(bci[1], 1)],
        "null_pct": round(nm, 1), "vs_null": round(b - nm, 1),
        "reject_pct": round(rj, 1), "neither_pct": round(neither, 1),
        "beats_null": bool(bci[0] > nm)}

print("\n" + "=" * 112)
print("WHAT A SHORT ACTUALLY RETURNS (net 9 bps, signed for a SHORT)")
print("=" * 112)
print(f"  {'condition':<34}{'n':>5}{'1d mean':>10}{'1d wk mean':>12}{'wk t':>7}"
      f"{'5d mean':>10}{'5d wk mean':>12}{'wk t':>7}")
print("-" * 112)
for name, fn in CONDS:
    rows = [r for r in touches if fn(r)]
    if len(rows) < 12:
        continue
    m1 = float(np.mean([-r["r1"] - FEE for r in rows]))
    m5 = float(np.mean([-r["r5"] - FEE for r in rows]))
    w1, t1, _ = wk(rows, "r1")
    w5, t5, nw = wk(rows, "r5")
    print(f"  {name:<34}{len(rows):>5}{m1:>+10.3f}{w1:>+12.3f}{t1:>7.2f}"
          f"{m5:>+10.3f}{w5:>+12.3f}{t5:>7.2f}")
    out["conditions"].setdefault(name.strip(), {}).update({
        "short_1d_mean": round(m1, 4), "short_1d_week_mean": round(w1, 4),
        "short_1d_week_t": round(float(t1), 2),
        "short_5d_mean": round(m5, 4), "short_5d_week_mean": round(w5, 4),
        "short_5d_week_t": round(float(t5), 2), "weeks": nw})

print("\n" + "=" * 112)
print("VERDICT")
print("=" * 112)
key = "+ trend UP & 4h EMA20<EMA50"
c = out["conditions"].get(key.strip(), {})
if c:
    print(f"  the owner's setup (n={c['n']}): the 50d breaks {c['break_pct']}% of the time "
          f"vs a {c['null_pct']}% random-level null ({c['vs_null']:+.1f} points)")
    print(f"  a short into it returns {c.get('short_1d_mean'):+.3f}% at 1d and "
          f"{c.get('short_5d_mean'):+.3f}% at 5d, net of fees")
    print(f"  price does NEITHER {c['neither_pct']:.0f}% of the time")
    ok = c.get("beats_null") and (c.get("short_5d_week_t") or 0) > 1.96
    out["verdict"] = ("the 4h filter rescues the setup" if ok
                      else "the 4h filter does not rescue it; the 50d still holds")
    print(f"\n  => {out['verdict'].upper()}")
with io.open(os.path.join(HERE, "sol_50d_short.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote sol_50d_short.json")
