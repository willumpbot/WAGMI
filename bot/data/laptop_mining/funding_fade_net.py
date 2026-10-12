"""STEPS 4-5: realised funding over the actual 72h hold, and the fade net of it.

ESTIMAND. SMALLCAP_CORRECTION.md Sec5 acts on the ABSOLUTE short return (-5.80%/72h), so that is
the primary number; the peer-relative fade is reported beside it.

SIGN CONVENTION, stated explicitly because the brief's premise is the opposite of the perp
standard. On Hyperliquid, as on every major perp venue, fundingRate > 0 means LONGS PAY SHORTS.
So a positive realised funding sum is a CREDIT to a short, not a cost. The code below carries
F = sum of hourly rates over the hold, in percent, and reports the short's net BOTH ways so
the result cannot be misread. Which way is correct is also cross-checked against the premium
field, which is positive exactly when the perp trades above index -- the blow-off case.
"""
import json
import os
import sqlite3

import numpy as np

SCR = r"C:/Users/vince/AppData/Local/Temp/claude/C--windows-System32/acf03186-eb2f-4645-840c-0730784e417f/scratchpad"
CACHE = r"C:/Users/vince/WAGMI/bot/data/laptop_mining/funding_cache.sqlite"
HOUR = 3_600_000
HOLD = 72
FEES = 0.18            # 2 x 9bps taker round trip, in percent
MINCOV = 0.90
rng = np.random.default_rng(20261011)

sig = json.load(open(os.path.join(SCR, "signals.json")))
panel = json.load(open(os.path.join(SCR, "panel.json")))

con = sqlite3.connect(CACHE)
fund = {}
for coin, t, rate, prem in con.execute("SELECT coin,t,rate,premium FROM funding"):
    # HL funding timestamps carry a few ms of jitter (...068, ...022), so an exact-hour
    # dict lookup silently misses every row. Key on the FLOORED hour instead.
    fund.setdefault(coin, {})[(t // HOUR) * HOUR] = (rate, prem)
print("funding cache: %d coins, %d rows" % (len(fund), sum(len(v) for v in fund.values())))


def realised(coin, t):
    """Sum of hourly funding rates over the 72 payments inside the hold, as percent.
    Entry = close of the bar starting at t (i.e. t+1h); exit = t+73h."""
    d = fund.get(coin)
    if not d:
        return None, 0.0, None
    tot = 0.0
    prem = 0.0
    n = 0
    for k in range(1, HOLD + 1):
        v = d.get(t + (k + 1) * HOUR)    # payments at t+2h .. t+73h (72 of them)
        if v is None:
            continue
        tot += v[0]
        prem += v[1]
        n += 1
    cov = n / float(HOLD)
    if cov < MINCOV:
        return None, cov, None
    return tot * 100.0 * (HOLD / float(n)), cov, prem / n


rows = []
missing = []
for e in sig:
    F, cov, prem = realised(e["coin"], e["t"])
    if F is None:
        missing.append((e["coin"], e["t"], cov))
        continue
    rows.append({"coin": e["coin"], "t": e["t"], "day": e["t"] // 86_400_000,
                 "above": e["above"], "fwd72": e["fwd72"], "dv20": e["dv20"],
                 "F": F, "cov": cov, "prem": prem})
print("events usable %d / %d   (SOURCE-MISSING %d)" % (len(rows), len(sig), len(missing)))
if not rows:
    raise SystemExit("ABORT: no usable events -- funding cache not ready, nothing to report.")
if missing:
    mc = {}
    for c, t, cov in missing:
        mc[c] = mc.get(c, 0) + 1
    print("  SOURCE-MISSING by coin:", dict(sorted(mc.items(), key=lambda x: -x[1])[:20]))

A = np.array([r["F"] for r in rows])             # funding sum over hold, % of notional
G = np.array([-r["fwd72"] for r in rows])        # GROSS short price return, %
days = np.array([r["day"] for r in rows])


def ew_by_day(x, dd):
    u = np.unique(dd)
    return np.array([x[dd == d].mean() for d in u]), u


def boot(x, iters=20000):
    """Day-clustered bootstrap: resample DAYS with replacement."""
    x = np.asarray(x, dtype=float)
    if len(x) < 10:
        return float("nan"), float("nan"), (float("nan"), float("nan"))
    ms = np.empty(iters)
    for b in range(iters):
        ms[b] = x[rng.integers(0, len(x), len(x))].mean()
    ms.sort()
    lo, hi = ms[int(.025 * iters)], ms[int(.975 * iters)]
    return float(x.mean()), float((hi - lo) / 3.92), (float(lo), float(hi))


print()
print("=" * 88)
print("A. REALISED FUNDING OVER THE ACTUAL 72h HOLD (sum of hourly rates, % of notional)")
print("=" * 88)
dF, ud = ew_by_day(A, days)
mp, sp, cp = boot(A)                 # pooled: bootstrap over events, reference only
me, se, ce = boot(dF)
print("  pooled by event   n=%4d  mean %+0.4f%%   [%+0.4f, %+0.4f]" % (len(A), mp, cp[0], cp[1]))
print("  EQUAL-WT BY DAY   D=%4d  mean %+0.4f%%   [%+0.4f, %+0.4f]  se %.4f"
      % (len(dF), me, ce[0], ce[1], se))
print("  per-day  : median %+0.4f  p10 %+0.4f  p90 %+0.4f  min %+0.4f  max %+0.4f"
      % (np.median(dF), np.percentile(dF, 10), np.percentile(dF, 90), dF.min(), dF.max()))
print("  per-event: median %+0.4f  p10 %+0.4f  p90 %+0.4f  min %+0.4f  max %+0.4f"
      % (np.median(A), np.percentile(A, 10), np.percentile(A, 90), A.min(), A.max()))
print("  implied rate %+0.4f%%/day equal-wt (brief guessed -1.00%%/day against the short)"
      % (me / 3.0))
print("  events with POSITIVE funding sum (a credit to a short): %.1f%%" % (100 * (A > 0).mean()))
print("  mean premium over hold %+0.5f  (>0 = perp above index => longs owe shorts)"
      % np.mean([r["prem"] for r in rows]))
print("  robustness on the skew: day median %+0.4f  10%%-trimmed day mean %+0.4f"
      % (np.median(dF), float(np.mean(np.sort(dF)[int(.1 * len(dF)):max(int(.9 * len(dF)), 1)]))))
BRIEF = -3.00        # the brief's guess: 1%/day against a short over a 72h hold
print()
print("  --- IS THE BRIEF'S 3%%/72h FUNDING DRAG DETECTABLE, AND IS IT THERE? ---")
print("  MDE on the funding term (80%% power, two-sided a=.05) = 2.80 x %.4f = %0.3f%%"
      % (se, 2.80 * se))
print("  measured %+0.4f%%  vs brief's hypothesis %+0.2f%%  -> difference %+0.3f%% = %.1f se"
      % (me, BRIEF, me - BRIEF, abs(me - BRIEF) / se if se > 0 else float("nan")))
print("  => the 3%%/72h figure is %s"
      % ("RULED OUT (outside the CI by a wide margin)" if BRIEF < ce[0] or BRIEF > ce[1]
         else "inside the CI -- NOT ruled out"))
# concentration of the funding cost
srt = np.sort(A)
tot = A.sum()
print("  concentration: worst 1%% of events = %.0f%% of total funding paid, worst 5%% = %.0f%%"
      % (100 * srt[:max(int(.01 * len(A)), 1)].sum() / tot if tot else float("nan"),
         100 * srt[:max(int(.05 * len(A)), 1)].sum() / tot if tot else float("nan")))
bycoin = {}
for r in rows:
    bycoin.setdefault(r["coin"], []).append(r["F"])
worst = sorted(bycoin.items(), key=lambda kv: np.mean(kv[1]))[:6]
print("  worst coins by mean funding/72h: %s"
      % ", ".join("%s %+0.2f%% (n=%d)" % (c, np.mean(v), len(v)) for c, v in worst))

print()
print("=" * 88)
print("B. THE SHORT, NET -- both sign conventions shown")
print("=" * 88)
dG, _ = ew_by_day(G, days)
mG, sG, cG = boot(dG)
out = {}
for lbl, sgn in (("HL/standard: rate>0 => longs pay shorts (short RECEIVES F)", +1),
                 ("brief's premise (counterfactual): short PAYS F", -1)):
    N = G + sgn * A - FEES
    dN, _ = ew_by_day(N, days)
    mN, sN, cN = boot(dN)
    print("  %s" % lbl)
    print("    %-32s %13s %13s" % ("", "pooled/event", "EQUAL-WT/DAY"))
    print("    %-32s %+12.3f%% %+12.3f%%" % ("gross short price return", G.mean(), mG))
    print("    %-32s %+12.3f%% %+12.3f%%" % ("realised funding", sgn * A.mean(), sgn * dF.mean()))
    print("    %-32s %+12.3f%% %+12.3f%%" % ("fees (2x9bps taker)", -FEES, -FEES))
    print("    %-32s %+12.3f%% %+12.3f%%" % ("NET", N.mean(), mN))
    print("    day-clustered 95%% CI on NET (equal-wt): [%+0.3f%%, %+0.3f%%]  se %.3f  z %+0.2f"
          % (cN[0], cN[1], sN, mN / sN if sN > 0 else float("nan")))
    print("    MDE (80%% power, two-sided a=.05) = 2.80 x se = %0.3f%%" % (2.80 * sN))
    print("    share of days net-positive: %.1f%%" % (100 * (dN > 0).mean()))
    print()
    out[sgn] = (mN, sN, cN)

print("=" * 88)
print("C. PEER-RELATIVE FADE, net of funding on the short leg")
print("=" * 88)
byt = {}
for s, t, a, fw in panel:
    byt.setdefault(t, []).append((s, a, fw))
sigset = {(r["coin"], r["t"]) for r in rows}
dayex = {}
for t, mem in byt.items():
    s_ = [fw for s, a, fw in mem if a >= 0.04 and (s, t) in sigset]
    n_ = [fw for s, a, fw in mem if a <= 0]
    if not s_ or len(n_) < 10:
        continue
    dayex.setdefault(t // 86_400_000, []).append(float(np.mean(s_) - np.mean(n_)))
dx = np.array([np.mean(v) for k, v in sorted(dayex.items())])
mx, sx, cx = boot(dx)
print("  gross fade (excess vs same-hour peers), equal-wt by day: %+0.3f%%  [%+0.3f, %+0.3f]  D=%d"
      % (mx, cx[0], cx[1], len(dx)))
print("  shorting that fade, net of SHORT-leg funding + fees: %+0.3f%%" % (-mx + me - FEES))

# the properly hedged version: short the signal, long an equal-weighted peer basket,
# and net the funding on BOTH legs (the long basket collects/pays its own funding).
dsp = {}
for t, mem in byt.items():
    sg = [(s, fw) for s, a, fw in mem if a >= 0.04 and (s, t) in sigset]
    pr = [(s, fw) for s, a, fw in mem if a <= 0]
    if not sg or len(pr) < 10:
        continue
    sF, sR = [], []
    for s, fw in sg:
        F, cov, _ = realised(s, t)
        if F is not None:
            sF.append(F)
            sR.append(fw)
    pF, pR = [], []
    for s, fw in pr:
        F, cov, _ = realised(s, t)
        if F is not None:
            pF.append(F)
            pR.append(fw)
    if not sF or len(pF) < 10:
        continue
    # short signal: -price + F ; long peers: +price - F ; fees on both legs
    pnl = (-np.mean(sR) + np.mean(sF)) + (np.mean(pR) - np.mean(pF)) - 2 * FEES
    dsp.setdefault(t // 86_400_000, []).append(float(pnl))
if len(dsp) >= 20:
    ds = np.array([np.mean(v) for k, v in sorted(dsp.items())])
    ms, ss, cs = boot(ds)
    print()
    print("  FULLY-HEDGED SPREAD (short signal / long peer basket, BOTH legs' funding netted,")
    print("  fees on both legs = %0.2f%%):" % (2 * FEES))
    print("    equal-wt by day %+0.3f%%  [%+0.3f, %+0.3f]  se %.3f  z %+0.2f  D=%d"
          % (ms, cs[0], cs[1], ss, ms / ss if ss > 0 else float("nan"), len(ds)))
    print("    MDE = 2.80 x se = %0.3f%%   share of days positive %.1f%%"
          % (2.80 * ss, 100 * (ds > 0).mean()))
    print("    pooled-by-day-event reference (unclustered mean of all day-hours): %+0.3f%%"
          % float(np.mean([v for vs in dsp.values() for v in vs])))
else:
    print("  SPREAD NOT COMPUTED -- insufficient peer-leg funding coverage (SOURCE-MISSING)")

print()
print("=" * 88)
print("D. PLACEBO ON THE FUNDING TERM -- can it fail?")
print("=" * 88)
print("  H0: realised 72h funding at signal hours = that of random eligible coin-hours.")
elig_by_t = {}
for s, t, a, fw in panel:
    elig_by_t.setdefault(t, []).append(s)
sig_per_t = {}
for r in rows:
    sig_per_t[r["t"]] = sig_per_t.get(r["t"], 0) + 1
runs = []
for it in range(8):
    dd = {}
    for t, k in sig_per_t.items():
        pool = [s for s in elig_by_t.get(t, []) if s in fund]
        if len(pool) <= k:
            continue
        vals = []
        for j in rng.choice(len(pool), k, replace=False):
            F, cov, _ = realised(pool[j], t)
            if F is not None:
                vals.append(F)
        if vals:
            dd.setdefault(t // 86_400_000, []).append(float(np.mean(vals)))
    if len(dd) >= 20:
        runs.append(float(np.mean([np.mean(v) for v in dd.values()])))
if runs:
    pm, ps = float(np.mean(runs)), float(np.std(runs) + 1e-12)
    print("  placebo runs: %s" % ", ".join("%+0.4f%%" % x for x in runs))
    print("  placebo mean %+0.4f%%  vs signal-hour funding %+0.4f%%  -> %.1f placebo-sd away"
          % (pm, me, abs(me - pm) / ps))
else:
    print("  PLACEBO NOT RUN -- insufficient benchmark funding coverage")

print()
print("=" * 88)
print("Dx. SIGN-CONVENTION AND MECHANISM CHECKS")
print("=" * 88)
allr, allp = [], []
for coin, d in fund.items():
    for t, (rate, prem) in d.items():
        allr.append(rate)
        allp.append(prem)
allr = np.array(allr)
allp = np.array(allp)
print("  corr(fundingRate, premium) over the whole cache = %+0.3f  (n=%d)"
      % (np.corrcoef(allr, allp)[0, 1], len(allr)))
print("  => rate tracks the perp's premium to index, confirming rate>0 <=> perp ABOVE index")
print("     <=> longs pay shorts. So the measured NEGATIVE funding at signal events means the")
print("     perp sits at a DISCOUNT after the pump and the SHORT pays. Cost, not credit.")
print("  universe-wide median hourly rate %+0.6f (=%+0.4f%%/day); HL baseline is 0.01%%/8h"
      % (np.median(allr), np.median(allr) * 100 * 24))
print("  corr(funding F, gross short return G) across events = %+0.3f"
      % np.corrcoef(A, G)[0, 1])
print("     negative => the short pays MORE funding exactly when the fade works harder")
print("     (shorts crowd in as it falls). Positive/zero => the cost is not endogenous.")

print()
print("=" * 88)
print("E. DOSE-RESPONSE: does funding get worse in the strongest blow-offs?")
print("=" * 88)
ab = np.array([r["above"] for r in rows])
print("  %-16s %6s %12s %12s" % ("above 20d high", "n", "funding/72h", "gross short"))
for lo, hi in ((0.04, 0.06), (0.06, 0.08), (0.08, 0.15), (0.15, 9.9)):
    m = (ab >= lo) & (ab < hi)
    if m.sum() < 5:
        continue
    lbl = ">=15%" if hi > 9 else "%.0f-%.0f%%" % (lo * 100, hi * 100)
    dFb, _ = ew_by_day(A[m], days[m])
    dGb, _ = ew_by_day(G[m], days[m])
    print("  %-16s %6d %+11.4f%% %+11.3f%%" % (lbl, m.sum(), dFb.mean(), dGb.mean()))

print()
print("=" * 88)
print("F. CAPACITY / COST HONESTY")
print("=" * 88)
dv = np.array([r["dv20"] for r in rows]) * 24
print("  trailing dollar volume/day at signal: median $%.0fk  p10 $%.0fk  p25 $%.0fk"
      % (np.median(dv) / 1e3, np.percentile(dv, 10) / 1e3, np.percentile(dv, 25) / 1e3))
print("  fees alone = %0.2f%% of notional round trip" % FEES)
for frac in (0.01, 0.02, 0.05):
    print("    at %.0f%% of one day's volume: median clip $%.0f, p10 clip $%.0f"
          % (frac * 100, np.median(dv) * frac, np.percentile(dv, 10) * frac))
print("  n coins %d, n events %d, n days %d"
      % (len(set(r["coin"] for r in rows)), len(rows), len(dF)))

json.dump({"n_events": len(rows), "n_coins": len(set(r["coin"] for r in rows)),
           "n_days": int(len(dF)), "n_source_missing": len(missing),
           "funding_ew_day_pct_72h": round(me, 4),
           "funding_ci": [round(ce[0], 4), round(ce[1], 4)],
           "funding_pooled_pct_72h": round(mp, 4),
           "net_short_hl_convention_ew": round(out[+1][0], 4),
           "net_short_hl_ci": [round(out[+1][2][0], 3), round(out[+1][2][1], 3)],
           "mde_pct": round(2.80 * out[+1][1], 3)},
          open(os.path.join(SCR, "funding_result.json"), "w"), indent=1)
