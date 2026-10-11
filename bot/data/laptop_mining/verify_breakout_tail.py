"""Independent verification of the red-team's central claim, written without reusing its code.

THE CLAIM. A red-team lens reported that `smallcap_momentum.py` found nothing because the
specification, not the data, was the binding constraint: graded by breakout STRENGTH, the strong
tail shows large negative excess returns -- a coin more than 4% above its 20-day high
underperforms its peers by ~6-10% over the following 72 hours, at |z| 5-7.

That is the opposite sign to the hypothesis and large enough to matter, so it does not get
accepted on an agent`s report. This re-derives it from the CSVs with an independently written
estimator, deliberately simpler than the original:

  - no sampling at all -- the benchmark is the FULL same-hour cross-section of eligible
    non-signal coins, so there is no draw noise and nothing to tune
  - equal-weighted BY DAY, which is what the prereg declared the clustering unit to be and what
    `smallcap_momentum.py` violated by pooling over events
  - day-block bootstrap on the daily series
  - and a PERMUTATION PLACEBO THAT CAN FAIL: re-draw the same number of signals per hour at
    random from that hour`s eligible coins. If the estimator were negative by construction, the
    placebo would be negative too.

If this reproduces, the finding is real and the write-up needs a substantial correction. If it
does not, the red-team overreached and I report that instead.
"""
import csv
import glob
import io
import json
import os

import numpy as np

rng = np.random.default_rng(31337)

WIN = 480
TOP_EXCLUDE = 15
HORIZONS = (1, 4, 12, 24, 72, 168)
BANDS = [(0.0, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.04), (0.04, 0.08), (0.08, 9.9)]
MIN_ELIG = 25


def load():
    out = {}
    for p in sorted(glob.glob(os.path.join("history1h", "*_1h.csv"))):
        sym = os.path.basename(p).replace("_1h.csv", "")
        t, c, v = [], [], []
        with io.open(p, encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    t.append(int(r[0]))
                    c.append(float(r[4]))
                    v.append(float(r[5]))
                except (ValueError, IndexError):
                    continue
        if len(t) < 600:
            continue
        o = np.argsort(np.asarray(t))
        out[sym] = {"t": np.asarray(t)[o], "c": np.asarray(c)[o], "v": np.asarray(v)[o]}
    return out


def prep(d):
    c, v = d["c"], d["v"]
    n = len(c)
    dv = c * v
    # trailing mean dollar volume over the PRIOR WIN bars, for point-in-time ranking
    cs = np.concatenate([[0.0], np.cumsum(dv)])
    dv20 = np.full(n, np.nan)
    if n > WIN + 1:
        idx = np.arange(WIN + 1, n)
        dv20[idx] = (cs[idx] - cs[idx - WIN]) / WIN
    # max close over the WIN bars STRICTLY before i
    hi = np.full(n, np.nan)
    for i in range(WIN + 1, n):
        hi[i] = c[i - WIN:i].max()
    d["dv20"] = dv20
    d["hi"] = hi
    with np.errstate(invalid="ignore"):
        d["above"] = c / hi - 1.0          # how far above the 20-day high, as a fraction
    for h in HORIZONS:
        f = np.full(n, np.nan)
        f[:-h] = (c[h:] / c[:-h] - 1.0) * 100.0
        d["fwd%d" % h] = f
    return d


def main():
    coins = {k: prep(v) for k, v in load().items()}
    print("INDEPENDENT VERIFICATION -- breakout strength vs forward excess return")
    print("  %d coins loaded" % len(coins))

    # index by timestamp
    at = {}
    for s, d in coins.items():
        for i, t in enumerate(d["t"]):
            at.setdefault(int(t), []).append((s, i))

    # eligible = not in the top 15 by trailing dollar volume at that hour
    elig = {}
    for t, mem in at.items():
        vs = [(s, i, coins[s]["dv20"][i]) for s, i in mem]
        vs = [x for x in vs if x[2] == x[2]]
        if len(vs) < MIN_ELIG + TOP_EXCLUDE:
            continue
        vs.sort(key=lambda x: -x[2])
        elig[t] = [(s, i) for s, i, _ in vs[TOP_EXCLUDE:]]
    print("  %d hours with >= %d eligible coins" % (len(elig), MIN_ELIG))
    print()
    print("  Benchmark = the FULL same-hour cross-section of eligible non-breakout coins.")
    print("  No sampling, so no draw noise. Equal-weighted BY DAY, per the prereg.")
    print()

    def excess_by_day(h, lo, hi_b, placebo=False):
        """Per day: mean(signal fwd) - mean(non-signal fwd), averaged over the day`s hours."""
        key = "fwd%d" % h
        days = {}
        for t, mem in elig.items():
            sig, non = [], []
            for s, i in mem:
                d = coins[s]
                a, f = d["above"][i], d[key][i]
                if f != f or a != a:
                    continue
                if a <= 0:
                    non.append(f)              # benchmark: not above its 20-day high
                elif lo <= a < hi_b:
                    sig.append(f)              # a breakout, in this strength band
                # a breakout in a DIFFERENT band belongs to neither arm, so it is dropped
                # from both rather than polluting the benchmark with other breakouts
            if placebo:
                # same count, drawn at random from the non-signal pool -- a null that CAN fail
                k = len(sig)
                if k and len(non) > k:
                    pick = rng.choice(len(non), k, replace=False)
                    sig = [non[j] for j in pick]
            if not sig or len(non) < 10:
                continue
            days.setdefault(int(t // 86_400_000), []).append(
                float(np.mean(sig)) - float(np.mean(non)))
        return {d: float(np.mean(v)) for d, v in days.items()}

    def boot(days, iters=3000):
        if len(days) < 20:
            return (float("nan"),) * 3
        x = np.asarray(list(days.values()))
        ms = np.empty(iters)
        for b in range(iters):
            ms[b] = x[rng.integers(0, len(x), len(x))].mean()
        ms.sort()
        se = (ms[int(.975 * iters)] - ms[int(.025 * iters)]) / 3.92
        return float(x.mean()), float(se), float(x.mean() / se) if se > 0 else float("nan")

    print("  DOSE-RESPONSE at 72h. Monotonicity is the protection against fishing:")
    print("  %-22s %7s %10s %9s %8s" % ("close above 20d high", "days", "excess", "se", "z"))
    grad = []
    for lo, hi_b in BANDS:
        dd = excess_by_day(72, lo, hi_b)
        m, se, z = boot(dd)
        lbl = ">= 8%" if hi_b > 9 else "%.1f-%.0f%%" % (lo * 100, hi_b * 100)
        print("  %-22s %7d %+9.2f%% %8.2f %+8.2f" % (lbl, len(dd), m, se, z))
        grad.append((lbl, m, z, len(dd)))
    print()

    print("  TERM STRUCTURE of the >=4%% tail. A bad print cannot grow smoothly with horizon:")
    print("  %-8s %7s %10s %8s" % ("horizon", "days", "excess", "z"))
    term = {}
    for h in HORIZONS:
        dd = excess_by_day(h, 0.04, 9.9)
        m, se, z = boot(dd)
        term[h] = (m, z)
        print("  %-8s %7d %+9.2f%% %+8.2f" % ("%dh" % h, len(dd), m, z))
    print()

    print("  PERMUTATION PLACEBO at 72h, >=4%% tail -- same counts, random coins.")
    print("  If the estimator were negative by construction this would be negative too:")
    pl = []
    for _ in range(5):
        dd = excess_by_day(72, 0.04, 9.9, placebo=True)
        m, _se, _z = boot(dd)
        pl.append(m)
    real = term[72][0]
    pm, ps = float(np.mean(pl)), float(np.std(pl) + 1e-9)
    print("    placebo runs: %s" % ", ".join("%+.3f%%" % x for x in pl))
    print("    placebo mean %+.3f%%  vs real %+.2f%%  -> real is %.1f placebo-sd away"
          % (pm, real, abs(real - pm) / ps))
    print()

    mono = all(grad[i][1] >= grad[i + 1][1] - 1e-9 for i in range(len(grad) - 1))
    print("=" * 78)
    print("MONOTONE DECREASING ACROSS ALL %d STRENGTH BANDS: %s" % (len(grad), mono))
    print("STRONG TAIL (>=8%%) AT 72h: %+.2f%%  z %+.2f" % (grad[-1][1], grad[-1][2]))
    print("VERDICT: %s" % ("red-team claim REPRODUCES on independently written code"
                           if mono and grad[-1][2] < -3.55 else
                           "does NOT reproduce -- red-team overreached"))
    print("=" * 78)
    json.dump({"gradient": [{"band": a, "excess_pct": round(b, 4),
                             "z": None if c != c else round(c, 2), "days": d}
                            for a, b, c, d in grad],
               "term_structure": {str(k): [round(v[0], 4),
                                           None if v[1] != v[1] else round(v[1], 2)]
                                  for k, v in term.items()},
               "placebo_mean_pct": round(pm, 4), "monotone": bool(mono)},
              open("verify_breakout_tail.json", "w"), indent=1)


if __name__ == "__main__":
    main()
