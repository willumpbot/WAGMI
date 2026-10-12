"""Robustness on the funding term: is it an artifact of a few coins, and is SKR real?"""
import json
import os
import sqlite3

import numpy as np

SCR = r"C:/Users/vince/AppData/Local/Temp/claude/C--windows-System32/acf03186-eb2f-4645-840c-0730784e417f/scratchpad"
CACHE = r"C:/Users/vince/WAGMI/bot/data/laptop_mining/funding_cache.sqlite"
HOUR = 3_600_000
HOLD = 72
FEES = 0.18
rng = np.random.default_rng(7)

sig = json.load(open(os.path.join(SCR, "signals.json")))
con = sqlite3.connect(CACHE)
fund = {}
for coin, t, rate, prem in con.execute("SELECT coin,t,rate,premium FROM funding"):
    fund.setdefault(coin, {})[(t // HOUR) * HOUR] = (rate, prem)


def realised(coin, t):
    d = fund.get(coin)
    if not d:
        return None
    tot = 0.0
    n = 0
    for k in range(1, HOLD + 1):
        v = d.get(t + (k + 1) * HOUR)
        if v is None:
            continue
        tot += v[0]
        n += 1
    if n / float(HOLD) < 0.90:
        return None
    return tot * 100.0 * (HOLD / float(n))


rows = []
for e in sig:
    F = realised(e["coin"], e["t"])
    if F is None:
        continue
    rows.append((e["coin"], e["t"] // 86_400_000, F, -e["fwd72"]))

A = np.array([r[2] for r in rows])
G = np.array([r[3] for r in rows])
days = np.array([r[1] for r in rows])
coin = np.array([r[0] for r in rows])


def ewd(x, dd):
    u = np.unique(dd)
    return np.array([x[dd == d].mean() for d in u])


def boot(x, iters=20000):
    x = np.asarray(x, float)
    ms = np.empty(iters)
    for b in range(iters):
        ms[b] = x[rng.integers(0, len(x), len(x))].mean()
    ms.sort()
    return float(x.mean()), float((ms[int(.975 * iters)] - ms[int(.025 * iters)]) / 3.92), \
        (float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)]))


print("=" * 86)
print("R1. LEAVE-ONE-COIN-OUT on the funding term (equal-wt by day)")
print("=" * 86)
base = ewd(A, days).mean()
print("  all coins: %+0.4f%%" % base)
res = []
for c in set(coin):
    m = coin != c
    res.append((c, ewd(A[m], days[m]).mean()))
res.sort(key=lambda kv: kv[1])
print("  most influential (dropping it moves funding most TOWARD zero):")
for c, v in sorted(res, key=lambda kv: -kv[1])[:5]:
    print("    drop %-9s -> %+0.4f%%  (moves %+0.4f)" % (c, v, v - base))
print("  range across all 140 leave-one-out fits: %+0.4f%% .. %+0.4f%%"
      % (res[0][1], res[-1][1]))

print()
print("=" * 86)
print("R2. WINSORISED / TRIMMED funding term -- how much is the thin tail?")
print("=" * 86)
for p in (0, 1, 5, 10):
    lo, hi = np.percentile(A, p), np.percentile(A, 100 - p)
    Aw = np.clip(A, lo, hi)
    m, s, c = boot(ewd(Aw, days))
    print("  winsorise at %2d%%/%2d%%: funding %+0.4f%%  [%+0.4f, %+0.4f]" % (p, 100 - p, m, c[0], c[1]))
print("  median-of-days (fully rank-based): %+0.4f%%" % np.median(ewd(A, days)))

print()
print("=" * 86)
print("R3. IS SKR REAL? raw hourly rates around its signal hours")
print("=" * 86)
sk = [r for r in rows if r[0] == "SKR"]
print("  SKR signal events: %d, mean funding/72h %+0.3f%%" % (len(sk), np.mean([r[2] for r in sk])))
d = fund["SKR"]
ts = sorted(d)
rr = np.array([d[t][0] for t in ts])
pp = np.array([d[t][1] for t in ts])
print("  SKR hourly rate over %d hours: median %+0.6f  p1 %+0.6f  min %+0.6f  max %+0.6f"
      % (len(rr), np.median(rr), np.percentile(rr, 1), rr.min(), rr.max()))
print("  SKR hourly premium: median %+0.6f  min %+0.6f  (negative = perp BELOW index)"
      % (np.median(pp), pp.min()))
print("  frac of SKR hours with rate < -0.0005 (-0.05%%/h): %.1f%%" % (100 * (rr < -0.0005).mean()))
print("  HL caps funding at +/-4%%/h; SKR min %+0.4f%%/h is %swithin that cap"
      % (rr.min() * 100, "" if abs(rr.min()) < 0.04 else "NOT "))

print()
print("=" * 86)
print("R4. NET SHORT excluding the 3 worst-funding coins (SKR, SOPH, ACE)")
print("=" * 86)
for drop in ([], ["SKR"], ["SKR", "SOPH", "ACE"]):
    m = ~np.isin(coin, drop)
    N = G[m] + A[m] - FEES
    mN, sN, cN = boot(ewd(N, days[m]))
    mF, sF, cF = boot(ewd(A[m], days[m]))
    lbl = "all" if not drop else "drop " + ",".join(drop)
    print("  %-22s n=%3d  funding %+0.3f%%  NET %+0.3f%% [%+0.3f, %+0.3f] z %+0.2f"
          % (lbl, m.sum(), mF, mN, cN[0], cN[1], mN / sN))

print()
print("=" * 86)
print("R5. COULD THE NET HAVE COME OUT NEGATIVE? break-even funding")
print("=" * 86)
dG = ewd(G, days)
mG, sG, cG = boot(dG)
print("  equal-wt gross short %+0.3f%%; fees %0.2f%%" % (mG, FEES))
print("  funding would have to be %+0.3f%%/72h (= %+0.3f%%/day) to wipe the edge out"
      % (-(mG - FEES), -(mG - FEES) / 3.0))
print("  measured %+0.3f%%/72h -- i.e. %.1fx smaller than break-even, and the worst single"
      % (base, abs((mG - FEES) / base)))
print("  coin in the sample (SKR, %+0.2f%%/72h) is itself past break-even, so a universe"
      % np.mean([r[2] for r in sk]))
print("  dominated by SKR-like coins WOULD have killed it. The result was not forced.")
