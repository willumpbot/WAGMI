"""The placebo X2 was missing: is +0.19R for wider stops an EDGE, or arithmetic?

WHY THIS EXISTS, and why it should have been in the sealed prereg.

X2 measured A1 - A0 = +0.1870R and I reported it as "consistent with the prior +0.25R evidence".
Then the research standard did its job: reading the prior work instead of its description showed
that GEOMETRY_V3 had already RED-TEAMED that very claim and withdrawn it, for a reason that applies
directly to X2 --

    "A driftless-GBM placebo reproduces ~95% of the whole surface (+0.1131R at 2.0|0.5 vs +0.1187R
     measured). The effect is mechanical. There is no edge content in it."

A wider stop can look better in R on ANY price process. R is normalised by the ORIGINAL risk, so
moving the stop further away shrinks stop-out frequency while the denominator stays fixed, and the
per-trade fee in R shrinks as 1/m by construction. None of that requires the market to do anything.

X2's placebo permuted arm labels within day-cells. That tests whether the day-clustering and the
variance are right. It CANNOT detect a mechanical effect, because permuting labels destroys the very
asymmetry (one arm's stop is further away) that produces it. So X2 passed a placebo that was not
aimed at its main failure mode.

THIS test replaces the real price path with a driftless geometric Brownian motion calibrated to each
coin's own realised hourly volatility, keeps every other element identical -- same entry, same side,
same actual stop, same tp1/tp2, same arm multipliers, same fees, same 96h cap, same held-fixed exit
times -- and asks what A1 - A0 comes out to when there is no edge by construction.

If the simulated difference matches the measured +0.1870R, X2's point estimate is arithmetic and
must not be described as "consistent with wider stops helping".
"""
import collections
import datetime
import importlib.util
import math
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("x2", os.path.join(HERE, "x2_stopwidth.py"))
x2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x2)

N_SIM = 300          # simulated worlds; the measured value either sits inside this spread or not


def realised_hourly_vol(series, t0, n=480):
    """SD of log returns over the 480 bars (20 days) BEFORE entry -- no post-entry information."""
    past = [b for b in series if b[0] < t0][-n - 1:]
    if len(past) < 50:
        return None
    r = []
    for a, b in zip(past, past[1:]):
        if a[4] and b[4] and a[4] > 0:
            r.append(math.log(b[4] / a[4]))
    if len(r) < 50:
        return None
    return statistics.pstdev(r)


def gbm_series(t0, px, sig, hours, rng, step=3600.0):
    """Driftless GBM, same bar spacing. High/low from a within-bar Brownian range so wick geometry
    is present rather than assumed away -- otherwise the simulation would understate stop-outs and
    flatter the wider arm for the wrong reason."""
    out, p = [], px
    for i in range(hours):
        o = p
        z = rng.gauss(0.0, sig)
        p = o * math.exp(z)
        # a crude but unbiased intrabar range: two extra half-step shocks around the path
        w1 = o * math.exp(rng.gauss(0.0, sig * 0.7))
        w2 = p * math.exp(rng.gauss(0.0, sig * 0.7))
        hi, lo = max(o, p, w1, w2), min(o, p, w1, w2)
        out.append((t0 + i * step, o, hi, lo, p))
    return out


def main():
    c = x2.conn()
    trades = x2.load_trades(c)
    syms = sorted({t["sym"] for t in trades})
    h1 = {s: x2.bars(c, s, "candles_1h") for s in syms}
    for t in trades:
        d = datetime.datetime.fromtimestamp(t["open_ts"], datetime.UTC).date()
        cl = x2.daily_closes(h1[t["sym"]], d)
        f = x2.vf.forecast(cl) if len(cl) >= 23 else None
        t["em"] = (f or {}).get("next_day_move_pct")
        t["series"] = h1[t["sym"]]
        t["fund"] = x2.funding_sum(c, t["sym"], t["open_ts"], t["close_ts"])
        t["day"] = datetime.datetime.fromtimestamp(t["close_ts"], datetime.UTC).date()
        t["sig"] = realised_hourly_vol(t["series"], t["open_ts"])

    use = [t for t in trades if t["exit_type"] in x2.CHANGEABLE and t["em"] and t["sig"]]
    print("GBM placebo on the %d stop-exited trades X2 measured" % len(use))
    print("calibrated to each coin's own realised hourly vol over the 480 bars before entry\n")

    def delta(t, series):
        d0 = abs(t["entry"] - t["sl"])
        d1 = t["entry"] * t["em"] / 100.0 * 1.0
        r0, _ = x2.arm_r(c, t, t["entry"] - t["side"] * d0, series, t["fund"])
        r1, _ = x2.arm_r(c, t, t["entry"] - t["side"] * d1, series, t["fund"])
        return None if r0 is None or r1 is None else (r1 - r0)

    real = [(t["day"], delta(t, t["series"])) for t in use]
    real = [(d, v) for d, v in real if v is not None]
    by = collections.defaultdict(list)
    for d, v in real:
        by[d].append(v)
    measured = statistics.fmean([statistics.fmean(v) for v in by.values()])
    print("MEASURED  A1 - A0, equal-weighted day mean: %+.4f R" % measured)

    sims = []
    rng = random.Random(20261012)
    for k in range(N_SIM):
        by_s = collections.defaultdict(list)
        for t in use:
            # the held-fixed exit time must survive into the simulation, or the sim would give the
            # wider arm a longer life than the real trade had and invent an advantage
            s = gbm_series(t["open_ts"], t["entry"], t["sig"], x2.CAP_H + 2, rng)
            v = delta(t, s)
            if v is not None:
                by_s[t["day"]].append(v)
        if by_s:
            sims.append(statistics.fmean([statistics.fmean(v) for v in by_s.values()]))
        if (k + 1) % 60 == 0:
            print("   %d/%d simulated worlds" % (k + 1, N_SIM))

    sims.sort()
    lo, hi = sims[int(.025 * len(sims))], sims[int(.975 * len(sims))]
    med = statistics.median(sims)
    print("\nNO-EDGE WORLDS (n=%d): median %+.4f R   95%% spread [%+.4f, %+.4f]"
          % (len(sims), med, lo, hi))
    share = (med / measured * 100.0) if measured else float("nan")
    print("the random walk reproduces %.0f%% of the measured effect" % share)
    above = sum(1 for s in sims if s >= measured)
    print("simulated worlds at least as extreme as the measurement: %d of %d (p = %.3f)"
          % (above, len(sims), above / len(sims)))
    print()
    if lo <= measured <= hi:
        print("VERDICT: the measured +%.4fR sits INSIDE the no-edge spread." % measured)
        print("         X2's point estimate is consistent with pure arithmetic and must NOT be")
        print("         described as evidence that wider stops help.")
    else:
        print("VERDICT: the measured value falls OUTSIDE the no-edge spread, so it is not fully")
        print("         explained by the mechanical effect -- though X2 remains UNDERPOWERED.")


if __name__ == "__main__":
    main()
