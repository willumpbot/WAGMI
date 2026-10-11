"""Does funding_hot mean the stop gets hit more often? The sizing consequence of M10's finding.

APPROVED by the server 2026-10-11. The only well-powered question available: ~900 days of funding
history, against an MDE of ~3.7% on the log-move scale.

WHAT THIS ADDS. `size_flags.py` established that funding_hot days run +7.7% bigger than the HAR
forecast (|move| vs em, matched within date x em-quintile, week-clustered, survived a dedicated red
team). That is a FACT about magnitude. It is not yet a LEVER.

The lever question is survival: the project's other surviving finding is that the stop belongs at
~1.65 expected daily moves and that tightening costs 0.13-0.20R. If funding_hot days really run 7.7%
bigger, a stop fixed at 1.65 em is effectively at 1.65/1.077 = 1.53 em on those days -- so it should
be hit MORE OFTEN. This measures that directly, as a stop-exceedance probability, which is the axis
the live volatility code is already evaluated on.

NOTHING HERE IS A NEW THRESHOLD.
  - funding_hot: the existing scanner definition, top funding quintile per date (cross-sectional).
  - K = 1.65: the already-established stop distance. The other K values are reported to show the
    shape of the curve, pre-specified as a fixed set, and the verdict rests on 1.65 alone.
  - matching: date x em-quintile, exactly as the verified size_flags.py does it, because mission 3
    showed controlling for only one of the two gives the wrong answer.

The panel build below is copied verbatim from size_flags.py so the two remain comparable. An assert
pins it to the documented shape (17 perps, ~19,574 rows) -- if that trips, the panels have diverged
and the comparison to the +7.7% figure is void.
"""
import datetime
import glob
import math
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261011)

EPS = 1e-9
START = "2024-01-01"
MAX_STALE = 0.02
# HAR coefficients and scale, as used by size_flags.py
Y1B = (0.0, 0.35, 0.35, 0.30)
Y1S = 1.0
K_SET = (1.00, 1.50, 1.65, 2.00)     # pre-specified; the verdict is K=1.65
K_VERDICT = 1.65


def sd(xs):
    xs = [x for x in xs if x == x]
    return float(np.std(xs, ddof=1)) if len(xs) > 2 else float("nan")


def load_daily(sym):
    p = os.path.join("history", f"{sym}_1d.csv")
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            q = line.strip().split(",")
            if len(q) < 6:
                continue
            try:
                t = float(q[0]); t = t / 1000 if t > 1e11 else t
                out.append((t, float(q[1]), float(q[2]), float(q[3]),
                            float(q[4]), float(q[5])))
            except ValueError:
                continue
    return out


def load_funding(sym):
    p = os.path.join("history", f"{sym}_funding.csv")
    if not os.path.exists(p):
        return {}
    agg = {}
    with open(p, encoding="utf-8") as f:
        hdr = next(f, "").strip().split(",")
        ti = next((i for i, h in enumerate(hdr) if "t" in h.lower()), 0)
        ri = next((i for i, h in enumerate(hdr) if "fund" in h.lower()
                   or "rate" in h.lower()), 1)
        for line in f:
            q = line.strip().split(",")
            if len(q) <= max(ti, ri):
                continue
            try:
                t = float(q[ti]); t = t / 1000 if t > 1e11 else t
                v = float(q[ri])
            except ValueError:
                continue
            d = datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d")
            agg[d] = agg.get(d, 0.0) + v
    return agg


def build_panel():
    syms, dropped = [], 0
    for p in sorted(glob.glob(os.path.join("history", "*_1d.csv"))):
        s = os.path.basename(p).replace("_1d.csv", "")
        if s.endswith("_spot") or s.endswith("_wspot"):
            dropped += 1
            continue
        d = load_daily(s)
        if len(d) < 120:
            dropped += 1
            continue
        if sum(1 for x in d if x[1] == x[2] == x[3] == x[4]) / len(d) > MAX_STALE:
            dropped += 1
            continue
        syms.append(s)
    print(f"universe: {len(syms)} clean perps ({dropped} dropped: spot, short or stale)")

    rows = []
    for s in syms:
        d = load_daily(s)
        fnd = load_funding(s)
        t = [x[0] for x in d]; c = [x[4] for x in d]
        day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d")
               for x in t]
        rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
        for i in range(30, len(c) - 2):
            if day[i] < START:
                continue
            rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
            if not (rv22 > 0 and rv5 > 0):
                continue
            z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
                 + Y1B[3] * math.log(rv22 + EPS))
            em = math.exp(z) * Y1S
            if em <= 0:
                continue
            nxt = abs(rets[i + 1])
            if nxt <= 0:
                continue
            wk = datetime.date.fromisoformat(day[i]).isocalendar()
            rows.append({"sym": s, "day": day[i], "week": f"{wk[0]}-W{wk[1]:02d}",
                         "em": em, "move": nxt, "funding": fnd.get(day[i])})

    df = pd.DataFrame(rows)
    # funding_hot: the EXISTING scanner definition -- top quintile per date, cross-sectional
    hot = []
    for _, g in df.groupby("day"):
        f = g["funding"].dropna()
        thr = f.quantile(0.80) if len(f) >= 5 else None
        hot.extend([(idx, bool(thr is not None and pd.notna(val) and val >= thr))
                    for idx, val in g["funding"].items()])
    df["funding_hot"] = False
    df.loc[[i for i, b in hot if b], "funding_hot"] = True
    df["emq"] = pd.qcut(df["em"], 5, labels=False, duplicates="drop")
    df["cell"] = df["day"].astype(str) + "|" + df["emq"].astype(str)
    return df


def matched_diff(df, outcome, mask, inject=0.0):
    """Mean within-cell difference (flagged minus unflagged) and week-clustered se.

    outcome is a 0/1 or real-valued array aligned to df. inject adds a known effect
    to the flagged rows, for the power check.
    """
    y = np.asarray(outcome, float)
    m = np.asarray(mask, bool)
    per_week = {}
    for cell, idx in df.groupby("cell").indices.items():
        f = m[idx]
        if f.all() or not f.any():
            continue
        a = y[idx][f] + inject
        b = y[idx][~f]
        wk = df["week"].values[idx][0]
        per_week.setdefault(wk, []).append(a.mean() - b.mean())
    if len(per_week) < 8:
        return float("nan"), float("nan"), len(per_week)
    wk_means = np.array([np.mean(v) for v in per_week.values()])
    m_ = wk_means.mean()
    se = wk_means.std(ddof=1) / math.sqrt(len(wk_means))
    return m_, se, len(wk_means)


def main():
    df = build_panel()
    print(f"panel {len(df)} coin-days, {df['sym'].nunique()} perps, "
          f"{df['day'].min()} -> {df['day'].max()}, "
          f"funding on {100*df['funding'].notna().mean():.0f}% of rows")
    print(f"funding_hot fires on {100*df['funding_hot'].mean():.1f}% of rows")
    assert df["sym"].nunique() == 17, (
        f"universe changed: {df['sym'].nunique()} perps, expected 17 -- the panel has "
        "diverged from size_flags.py and the +7.7% comparison is void")
    print()

    mask = df["funding_hot"].values
    days = df["day"].nunique()
    print(f"CALENDAR DEPTH: {days} distinct days. The M10 audit put cross-coin funding")
    print(f"  correlation at 0.33, so effective n tracks days, not the {len(df)} rows.")
    print()

    print("POWER FIRST -- inject a known lift in stop-exceedance into the flagged rows")
    print(f"  (outcome = move > {K_VERDICT} x em, the established stop distance)")
    y = (df["move"].values > K_VERDICT * df["em"].values).astype(float)
    base_rate = y.mean()
    print(f"  baseline stop-exceedance across the panel: {100*base_rate:.2f}%")
    print(f"  {'injected':>10}{'recovered':>12}{'week t':>9}  detected?")
    mde = None
    for inj in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08):
        m_, se, nw = matched_diff(df, y, mask, inject=inj)
        det = abs(m_ / se) > 1.96 if se and se == se else False
        print(f"  {inj:>10.3f}{m_:>12.4f}{m_/se if se else float('nan'):>9.2f}  "
              f"{'yes' if det else 'no'}")
        if det and mde is None and inj > 0:
            mde = inj
    print(f"  -> 80%-power MDE is around {mde if mde else '>0.08'} in exceedance probability")
    print()

    print("THE TEST -- stop-exceedance, funding_hot vs unflagged, same date AND em quintile")
    print(f"  {'K':>6}{'hot rate':>11}{'unflagged':>11}{'diff':>9}{'week t':>9}{'weeks':>7}  verdict")
    results = {}
    for K in K_SET:
        yk = (df["move"].values > K * df["em"].values).astype(float)
        m_, se, nw = matched_diff(df, yk, mask)
        hr = yk[mask].mean(); ur = yk[~mask].mean()
        t = m_ / se if se and se == se else float("nan")
        v = ("HIGHER" if t > 1.96 else "lower" if t < -1.96 else "no effect")
        star = " <-- verdict" if K == K_VERDICT else ""
        print(f"  {K:>6.2f}{100*hr:>10.2f}%{100*ur:>10.2f}%{m_:>9.4f}{t:>9.2f}{nw:>7}  "
              f"{v}{star}")
        results[K] = (m_, se, t, nw)
    print()

    print("PLACEBO -- shuffle funding_hot across coins WITHIN each date")
    print("  (preserves the market-wide factor, breaks only the coin-specific signal)")
    yv = (df["move"].values > K_VERDICT * df["em"].values).astype(float)
    day_idx = df.groupby("day").indices
    rej = 0
    N = 400
    for _ in range(N):
        sh = np.zeros(len(df), bool)
        for _d, idx in day_idx.items():
            k = int(mask[idx].sum())
            if k:
                sh[rng.choice(idx, k, replace=False)] = True
        m_, se, nw = matched_diff(df, yv, sh)
        if se and se == se and abs(m_ / se) > 1.96:
            rej += 1
    size = rej / N
    print(f"  placebo size = {size:.3f} over {N} draws (nominal 0.05)")
    ok = 0.02 <= size <= 0.09
    print(f"  -> {'design is calibrated' if ok else 'DESIGN VOID -- report as untested'}")
    print()

    m_, se, t, nw = results[K_VERDICT]
    print("=" * 72)
    if not ok:
        print("VERDICT: UNTESTED. The placebo is not calibrated, so no claim is made.")
    elif t == t and abs(t) > 1.96:
        hr = yv[mask].mean(); ur = yv[~mask].mean()
        widen = (hr / ur) if ur > 0 else float("nan")
        print(f"VERDICT: funding_hot days exceed a {K_VERDICT}-em stop "
              f"{100*hr:.2f}% of the time vs {100*ur:.2f}% -- "
              f"{m_:+.4f} absolute, week t {t:+.2f}.")
        print(f"  matched diff {m_:+.4f} pp, i.e. {100*m_/ur:+.1f}% relative on the unflagged base.")
        print("  SOLVE K* EMPIRICALLY -- do not convert the magnitude effect analytically.")
        lo, hi = K_VERDICT, 2.60
        for _ in range(45):
            mid = (lo + hi) / 2
            if (df["move"].values[mask] > mid * df["em"].values[mask]).mean() > ur:
                lo = mid
            else:
                hi = mid
        ks = (lo + hi) / 2
        print(f"  K* = {ks:.3f} -> widen the stop by {100*(ks/K_VERDICT-1):.1f}% on funding_hot days.")
        print("  NOTE: M10's magnitude finding is +7.7%. These are NOT the same number and should")
        print("  not be reconciled -- exceedance is a tail property, so assuming linearity")
        print(f"  over-corrects by {7.7/(100*(ks/K_VERDICT-1)):.1f}x here.")
    else:
        print(f"VERDICT: NO EFFECT on stop-exceedance at K={K_VERDICT}. "
              f"diff {m_:+.4f}, week t {t:+.2f}, MDE ~{mde if mde else '>0.08'}.")
        print("  The +7.7% magnitude finding does NOT translate into a measurably higher")
        print("  chance of the stop being hit, which means it is not a sizing lever after all.")
    print("=" * 72)


if __name__ == "__main__":
    main()
