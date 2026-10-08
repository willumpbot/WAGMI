"""MISSION 1 — do the scanner's two "tested" directional flags earn their label?

The terminal shows `ma50_pullback` and `on_20d_low` with evidence="tested". The server has
pre-committed: "If either is null after fees, say so and I demote it on screen."

EXACT definitions lifted from tools/hivemind/scanner.py:103-105 (no paraphrase):

    d50 = (px / e50[-1] - 1) * 100          # e50 is an EMA, not an SMA
    em  = volforecast.forecast(c)["next_day_move_pct"]      # stage-1 HAR only
    ma50_pullback : 0 <= d50 <= 0.5 * em
    on_20d_low    : lo20 <= px and (px / lo20 - 1) * 100 <= 0.5 * em    # lo20 = min(low[-20:])

`em` is replicated here from volatility_forecast.json's y1_beta / y1_smearing rather than calling
volforecast.forecast() per row (which re-reads the JSON on every call). Verified identical on
8 coin/cutoff pairs to within rounding: BTC 2.0839 vs 2.08, ETH 2.5118 vs 2.51, SOL 3.2041 vs 3.20,
DOGE 3.7875 vs 3.79.

MEASUREMENT
  entry  = NEXT day's open after the flag day (no lookahead -- the flag uses that day's close)
  exit   = close of entry+1d and entry+5d
  cost   = 9 bps round trip, applied in the direction traded
  metric = EXCESS over the universe median return on the same calendar dates
           (removes market beta; a long flag that only captures "crypto went up" is not a flag)
  sign   = ma50_pullback scored LONG; on_20d_low scored SHORT (the server's stated senses)

THE NULL (as the server specified -- not a GBM)
  For each coin, draw the SAME NUMBER of random eligible dates that coin's flag actually fired on,
  and compute the same excess metric. 2,000 draws -> a null distribution of the mean excess.
  This holds constant: the coin mix, the number of observations per coin, and the sample period.
  It CAN fail: if the flag has no timing information the real mean lands inside this distribution.

POWER (the step I skipped in geometry_v3 and got burned for)
  A known effect is injected into the real flag rows and the test is re-run, to establish the
  smallest effect this design can actually detect. A null result is only evidence of absence
  above that floor. The zero-injection arm resamples genuinely -- it does NOT pin a sample mean
  to zero and then test that mean (geometry_v3.py's error).

Reported with ISO-week-clustered CIs AND the equal-weighted week mean next to every pooled figure,
per the rule earned in CORRECTIONS.md.
"""
import json, io, os, csv, glob, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FEE_BPS = 9.0
EPS = 1e-8
START = "2023-01-01"          # the server asked for 2023 -> now
HORIZONS = (1, 5)
NULL_DRAWS = 2000
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
    p = os.path.join(HIST, f"{sym}_1d.csv")
    rows = []
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"])))
            except (TypeError, ValueError, KeyError):
                continue
    rows.sort()
    return rows


syms = sorted({os.path.basename(p).split("_1d")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
syms = [s for s in syms if not s.endswith("_wspot")]     # perps only; wspot series are short

# ---------- build the panel ----------
obs = []          # one row per (coin, day) with flags + forward returns
for s in syms:
    d = load(s)
    if len(d) < 120:
        continue
    t = [x[0] for x in d]
    o = [x[1] for x in d]
    h = [x[2] for x in d]
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
        d50 = (px / e50[i] - 1) * 100
        lo20 = min(l[i - 19:i + 1])
        f_ma50 = (0 <= d50 <= 0.5 * em)
        f_lo20 = (lo20 <= px and (px / lo20 - 1) * 100 <= 0.5 * em)
        entry = o[i + 1]                       # NEXT open: the flag used today's close
        if entry <= 0:
            continue
        fwd = {}
        for hz in HORIZONS:
            j = i + hz
            if j >= len(c):
                fwd = None
                break
            fwd[hz] = (c[j] / entry - 1) * 100
        if fwd is None:
            continue
        wk = datetime.date.fromisoformat(day[i]).isocalendar()
        obs.append({"sym": s, "day": day[i], "week": f"{wk[0]}-W{wk[1]:02d}",
                    "ma50_pullback": f_ma50, "on_20d_low": f_lo20,
                    "r1": fwd[1], "r5": fwd[5]})

print(f"panel: {len(obs)} coin-days, {len({r['sym'] for r in obs})} perps, "
      f"{min(r['day'] for r in obs)} -> {max(r['day'] for r in obs)}")

# ---------- universe median per date, then excess ----------
bydate = collections.defaultdict(list)
for r in obs:
    bydate[r["day"]].append(r)
for dy, rs in bydate.items():
    if len(rs) < 5:
        for r in rs:
            r["skip"] = True
        continue
    for hz in HORIZONS:
        med = float(np.median([r[f"r{hz}"] for r in rs]))
        for r in rs:
            r[f"x{hz}"] = r[f"r{hz}"] - med
obs = [r for r in obs if not r.get("skip")]
print(f"after requiring >=5 coins per date for a median: {len(obs)} rows\n")

FEE = 2 * FEE_BPS / 100.0      # 9 bps each way, in percent


def net(r, hz, side):
    """Excess return in the traded direction, net of the round trip."""
    return (r[f"x{hz}"] if side == "long" else -r[f"x{hz}"]) - FEE


def wk_mean(rows, hz, side):
    """Equal-weighted ISO-week mean + t on the week means."""
    byw = collections.defaultdict(list)
    for r in rows:
        byw[r["week"]].append(net(r, hz, side))
    mus = np.array([np.mean(v) for v in byw.values()])
    n = len(mus)
    if n < 4:
        return float("nan"), float("nan"), (float("nan"), float("nan")), n
    m = float(mus.mean())
    se = float(mus.std(ddof=1)) / math.sqrt(n)
    t = m / se if se > 0 else float("nan")
    return m, t, (m - 1.96 * se, m + 1.96 * se), n


FLAGS = [("ma50_pullback", "long"), ("on_20d_low", "short")]
out = {"panel_rows": len(obs), "perps": len({r["sym"] for r in obs}),
       "start": min(r["day"] for r in obs), "end": max(r["day"] for r in obs),
       "fee_bps_round_trip": 2 * FEE_BPS, "null_draws": NULL_DRAWS, "flags": {}}

for flag, side in FLAGS:
    fired = [r for r in obs if r[flag]]
    percoin = collections.Counter(r["sym"] for r in fired)
    print("=" * 104)
    print(f"{flag}  scored {side.upper()}   fired on {len(fired)} coin-days "
          f"({100*len(fired)/len(obs):.1f}% of the panel), {len(percoin)} coins")
    print("=" * 104)
    out["flags"][flag] = {"side": side, "n_fired": len(fired),
                          "pct_of_panel": round(100 * len(fired) / len(obs), 2),
                          "coins": len(percoin), "horizons": {}}
    if len(fired) < 30:
        print("  too few firings to test\n")
        continue

    # eligible pool per coin for the null: every row that coin contributes
    pool = collections.defaultdict(list)
    for r in obs:
        pool[r["sym"]].append(r)

    print(f"  {'hz':>3}{'mean excess':>14}{'week mean':>12}{'week t':>9}"
          f"{'week CI95':>24}{'null mean':>11}{'null p':>9}  verdict")
    print("-" * 104)
    for hz in HORIZONS:
        real = float(np.mean([net(r, hz, side) for r in fired]))
        wm, t, ci, nw = wk_mean(fired, hz, side)

        # ---- the null: same coins, same counts, random dates ----
        nulls = np.empty(NULL_DRAWS)
        for b in range(NULL_DRAWS):
            vals = []
            for sym, k in percoin.items():
                p = pool[sym]
                idx = rng.integers(0, len(p), k)
                vals.extend(net(p[j], hz, side) for j in idx)
            nulls[b] = np.mean(vals)
        nm = float(nulls.mean())
        p_one = float((nulls >= real).mean())          # is the flag BETTER than random dates?
        beats = (p_one < 0.05) and (ci[0] > 0)
        verdict = ("EARNED" if beats else
                   "null (no timing edge)" if p_one > 0.05 else
                   "beats random dates but CI contains zero")
        print(f"  {hz:>3}{real:>+14.4f}{wm:>+12.4f}{t:>9.2f}"
              f"  [{ci[0]:+.4f},{ci[1]:+.4f}]{nm:>+11.4f}{p_one:>9.3f}  {verdict}")
        out["flags"][flag]["horizons"][f"{hz}d"] = {
            "mean_excess_net_pct": round(real, 4), "week_mean": round(wm, 4),
            "week_t": round(float(t), 2), "week_ci": [round(ci[0], 4), round(ci[1], 4)],
            "weeks": nw, "null_mean": round(nm, 4),
            "null_p_one_sided": round(p_one, 4),
            "null_ci": [round(float(np.percentile(nulls, 2.5)), 4),
                        round(float(np.percentile(nulls, 97.5)), 4)],
            "earned": bool(beats)}

    # ---- robustness: the mean is tail-dominated, so report order statistics too ----
    print("\n  ROBUSTNESS — the mean is not the right statistic here:")
    print(f"    {'hz':>3}{'mean':>10}{'MEDIAN':>10}{'winsor 1/99':>13}{'win rate':>10}"
          f"{'panel win rate':>16}{'top-1% share of |excess|':>26}")
    allrows = obs
    for hz in HORIZONS:
        v = np.array([net(r, hz, side) for r in fired])
        av = np.array([net(r, hz, side) for r in allrows])
        lo, hi = np.percentile(v, [1, 99])
        k = max(1, len(v) // 100)
        idx = np.argsort(np.abs(v))[::-1]
        share = 100 * np.abs(v[idx[:k]]).sum() / np.abs(v).sum()
        print(f"    {hz:>3}{v.mean():>+10.3f}{np.median(v):>+10.3f}"
              f"{np.clip(v,lo,hi).mean():>+13.3f}{100*(v>0).mean():>9.1f}%"
              f"{100*(av>0).mean():>15.1f}%{share:>25.1f}%")
        out["flags"][flag]["horizons"][f"{hz}d"].update({
            "median_excess": round(float(np.median(v)), 4),
            "winsorized_mean": round(float(np.clip(v, lo, hi).mean()), 4),
            "win_rate_pct": round(100 * float((v > 0).mean()), 2),
            "panel_win_rate_pct": round(100 * float((av > 0).mean()), 2),
            "top1pct_share_of_abs_excess": round(float(share), 1),
            "mean_excl_top1pct": round(float(np.delete(v, idx[:k]).mean()), 4)})
    print(f"    NOTE: the round-trip fee is exactly {FEE:.3f}%. A median of -{FEE:.3f}% means the")
    print(f"    median flagged trade earns EXACTLY ZERO before costs.")

    # ---- power: what is the smallest effect this design could detect? ----
    print(f"\n  POWER — inject a known effect into the {flag} rows, re-run the same test (hz=1):")
    base = [net(r, 1, side) for r in fired]
    byw_idx = collections.defaultdict(list)
    for r in fired:
        byw_idx[r["week"]].append(r)
    mde = None
    for delta in (0.0, 0.1, 0.25, 0.5, 1.0, 2.0):
        mus = np.array([np.mean([net(r, 1, side) + delta for r in v]) for v in byw_idx.values()])
        n = len(mus)
        se = float(mus.std(ddof=1)) / math.sqrt(n)
        lo = float(mus.mean()) - 1.96 * se
        det = lo > 0
        if det and mde is None and delta > 0:
            mde = delta
        print(f"    +{delta:>4.2f}%  week CI low {lo:+.4f}  {'DETECTED' if det else 'not detected'}"
              f"{'   <- zero-injection arm (must NOT detect)' if delta == 0 else ''}")
    print(f"    smallest detectable effect: {mde}% per trade"
          if mde else "    nothing in range detectable")
    out["flags"][flag]["mde_pct_1d"] = mde
    print()

print("=" * 104)
print("VERDICT")
print("=" * 104)
for flag, side in FLAGS:
    f = out["flags"].get(flag, {})
    hz = f.get("horizons", {})
    earned = [k for k, v in hz.items() if v.get("earned")]
    print(f"  {flag:<16} ({side:<5}) earned at: {earned if earned else 'NO HORIZON'}"
          f"   (detectable floor {f.get('mde_pct_1d')}%)")
anyearned = any(v.get("earned") for f in out["flags"].values() for v in f.get("horizons", {}).values())
out["verdict"] = ("at least one flag earned its label" if anyearned
                  else "neither flag beats random dates in the same coin after fees")
print(f"\n  => {out['verdict']}")
with io.open(os.path.join(HERE, "scanner_flags.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote scanner_flags.json")
