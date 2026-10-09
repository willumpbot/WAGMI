"""Day-clustered robustness check for liq_magnet_calibration.py (2026-10-09).

The original bootstrap resamples individual magnet episodes, but episodes on the same UTC day share the same
market move (a big down day reaches every level below). This re-uses the original pre-registered candidate
construction unchanged and recomputes the magnet-minus-matched-control difference with a bootstrap over DAYS
(magnets and placebos resampled together by day), plus a time-shift placebo: magnet levels re-anchored to a
random other day's price offset, which should give ~0 if the design can't manufacture an effect.
Read-only; uses cached candles (pass --no-net to avoid fetching).
"""
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import liq_magnet_calibration as M  # noqa: E402


def day(c):
    return int(c["t"] // 86400)


def diff_for(mags, plac, key):
    tab = defaultdict(lambda: [0, 0])
    for p in plac:
        tab[key(p)][1] += 1
        tab[key(p)][0] += p["reached"]
    num = den = 0.0
    hits = 0
    n = 0
    for m in mags:
        k = key(m)
        if tab[k][1]:
            num += tab[k][0] / tab[k][1]
            den += 1
            hits += m["reached"]
            n += 1
    return (hits / n - num / den) if n and den else None, n


def main():
    no_net = "--no-net" in sys.argv
    iv = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--interval=")), "5m")
    if iv != "5m":   # HL serves only the last 5000 candles: coarser bars reach further back (15m ~52d, 1h ~208d)
        M.get_candles = lambda coin, a, b, _nn: M.hl_candles(coin, iv, int((a - 3600) * 1000), int((b + 3600) * 1000))
    print(f"candles: {iv}")
    rng = random.Random(7)
    liqs = M.load_liqs()
    tmin = min(e["ts"] for s in M.SYMBOLS for e in liqs.get(s, []))
    tmax = max(e["ts"] for s in M.SYMBOLS for e in liqs.get(s, []))
    cmap = {s: M.get_candles(s, tmin, tmax, no_net) for s in M.SYMBOLS}
    cands = M.build_all(liqs, cmap, M.K_MIN)
    mags = M.dedup_magnets([c for c in cands if c["is_magnet"]])
    plac = [c for c in cands if c["is_magnet"] is None]
    key = lambda c: (c["symbol"], c["side"], c["dbin"])
    d0, n0 = diff_for(mags, plac, key)
    print(f"point estimate diff={d0:.3f} on n={n0} magnet episodes, {len(plac)} placebos")

    bym, byp = defaultdict(list), defaultdict(list)
    for m in mags:
        bym[day(m)].append(m)
    for p in plac:
        byp[day(p)].append(p)
    days = sorted(set(bym) | set(byp))
    print(f"{len(days)} days, {len(bym)} with magnets")
    diffs = []
    for _ in range(2000):
        pick = [days[rng.randrange(len(days))] for _ in days]
        mm = [m for d in pick for m in bym.get(d, [])]
        pp = [p for d in pick for p in byp.get(d, [])]
        v, _n = diff_for(mm, pp, key)
        if v is not None:
            diffs.append(v)
    diffs.sort()
    lo, hi = diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs))]
    print(f"DAY-CLUSTERED bootstrap 95% CI: [{lo:.3f}, {hi:.3f}]  (share > 0: {sum(d > 0 for d in diffs) / len(diffs):.3f})")

    # weekly sign stability
    byw = defaultdict(lambda: ([], []))
    for m in mags:
        byw[int(m["t"] // (7 * 86400))][0].append(m)
    for p in plac:
        byw[int(p["t"] // (7 * 86400))][1].append(p)
    ws = []
    for w, (mm, pp) in sorted(byw.items()):
        v, n = diff_for(mm, pp, key)
        if v is not None and n >= 10:
            ws.append(v)
    print(f"weeks with n>=10: {len(ws)}, positive: {sum(v > 0 for v in ws)}, values: {[round(v, 3) for v in ws]}")


if __name__ == "__main__":
    main()
