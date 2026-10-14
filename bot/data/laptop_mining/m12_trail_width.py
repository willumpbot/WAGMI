"""M12 -- should the trail be scaled to the coin's OWN volatility instead of one exp_move? EXPLORATORY.

SERVER, 23:45Z: "trail width in units of the coin's OWN volatility for high-vol coins (the 1-exp-move
trail looks tight where ATR >> HAR exp_move) - exploratory, cross-section only." Prompted by their
replay of the owner's CASHCAT call: fixed +1.00R, partial+trail +1.37R with the 1-em trail cutting the
runner at ~31h, hold +2.32R.

THEIR PREMISE IS CORRECT AND MEASURED FIRST, because a study built on a false premise is wasted:
    ATR60 / HAR em      median 2.31   (p10 1.84, p90 2.96)
    low-vol third 2.09  high-vol third 2.85   corr(ATR, ratio) = +0.766
    CASHCAT 29.3% / 8.5% = 3.44
So one exp_move really is a tighter trail in ATR terms on high-vol coins, and CASHCAT is an extreme
case: a 1-em trail there is 0.29 of a typical daily true range, inside routine intraday noise.

🔴 BUT THERE IS A DIRECT TENSION WITH M10, AND RESOLVING IT IS THE POINT OF THIS FILE.
  * M10, 26,550 entries, cross-section: positions UP at 48h LOST money by being held (-32 bps majors,
    -16 held-out). That argues for cutting winners EARLIER -- a TIGHTER trail.
  * Their CASHCAT replay: hold +2.32R beat the trail's +1.37R. That argues for a WIDER trail.
  * The CASHCAT number is n=1 on the coin that was flagged BECAUSE it ran. It is the same
    outcome-selected anecdote M11 was built to neutralise.
So the cross-section decides, and the honest prior from M10 is that wider trails LOSE.

DESIGN. Stop is fixed at 1.65 x em in every arm so that ONLY the trail varies. The trail activates once
price reaches +1R, then rides at width W behind the best favourable excursion. Widths:
    incumbent   1.00 x em                  (what the bot does now)
    ATR-scaled  0.25 / 0.50 / 0.75 / 1.00 x ATR60
Because ATR/em averages 2.31, the incumbent 1-em trail sits near 0.43 ATR -- so the ATR arms bracket it
on both sides, and the comparison is not rigged toward "wider".

Reported BY VOLATILITY TERCILE, because the premise is an interaction claim: if ATR-scaling helps, it
must help MORE where ATR/em is large. A flat improvement across terciles would mean the win came from
width alone, not from scaling.

Unit bps of notional net of 9 bps fees. M1 v3 martingale control SUBTRACTED. Coin-clustered equal
weighted means. 72h horizon. EXPLORATORY, no card above HYPOTHESIS.
"""
import io
import json
import math
import os
import sqlite3

import numpy as np

import panel_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
FEE_FRAC = 0.0009
K_STOP = 1.65
TRAIL_ON_R = 1.0            # trail activates at +1R, as in M1's partial_1R family
HORIZON = 72
ATR_D = 60                  # daily ATR window, matching the premise measurement
ENTRIES = 250
BOOT = 4000
rng = np.random.default_rng(20261015)

ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]

ARMS = (("trail_1.00em", "em", 1.00),
        ("trail_0.25atr", "atr", 0.25),
        ("trail_0.50atr", "atr", 0.50),
        ("trail_0.75atr", "atr", 0.75),
        ("trail_1.00atr", "atr", 1.00))


def sd(xs):
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def prep(c, coin):
    rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
    if len(rows) < HORIZON + 900:
        return None
    a = np.asarray(rows, float)
    b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
    day = (b["t"] // 86400000).astype(np.int64)
    uq, fi = np.unique(day, return_index=True)
    ends = np.append(fi[1:], len(b["c"]))
    dh = np.array([b["h"][i:j].max() for i, j in zip(fi, ends)])
    dl = np.array([b["l"][i:j].min() for i, j in zip(fi, ends)])
    dc = np.array([b["c"][j - 1] for j in ends])
    if len(dc) < 40:
        return None
    tr = np.maximum(dh[1:] - dl[1:], np.maximum(np.abs(dh[1:] - dc[:-1]),
                                                np.abs(dl[1:] - dc[:-1])))
    atr_frac = float(np.mean(tr[-ATR_D:]) / dc[-1]) if len(tr) >= ATR_D else None
    rets = np.concatenate(([0.0], (dc[1:] / dc[:-1] - 1.0) * 100.0))
    em = np.full(len(uq), np.nan)
    for i in range(30, len(dc)):
        rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[i] = v / 100.0
    if atr_frac is None or not np.isfinite(em[30:]).any():
        return None
    b["em"] = em[np.searchsorted(uq, day)]
    b["atr"] = atr_frac
    return b


def simulate(b, ent, side, synthetic):
    """Walk each path once and resolve every trail arm. Returns {arm: bps array}."""
    entry = b["c"][ent]
    if synthetic:
        prevc = b["c"][:-1]
        lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
        up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
        dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
        g = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
        lr, up, dn = lr[g], np.maximum(up[g], 0.0), np.maximum(dn[g], 0.0)
        if len(lr) < 200:
            return None
        draw = rng.integers(0, len(lr), size=(len(ent), HORIZON))
        step = np.exp(lr[draw]) / float(np.mean(np.exp(lr)))
        C = entry[:, None] * np.cumprod(step, axis=1)
        prev = np.concatenate((entry[:, None], C[:, :-1]), axis=1)
        H = np.maximum(prev, C) * (1.0 + up[draw])
        L = np.minimum(prev, C) * (1.0 - dn[draw])
    else:
        pidx = ent[:, None] + np.arange(1, HORIZON + 1)[None, :]
        H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
    stop_frac = K_STOP * b["em"][ent]
    # favourable and adverse excursion per bar, side-adjusted
    fav = np.where(side[:, None] > 0, (H - entry[:, None]) / entry[:, None],
                   (entry[:, None] - L) / entry[:, None])
    adv = np.where(side[:, None] > 0, (entry[:, None] - L) / entry[:, None],
                   (H - entry[:, None]) / entry[:, None])
    close_ret = side[:, None] * (C / entry[:, None] - 1.0)
    runmax = np.maximum.accumulate(fav, axis=1)
    out = {}
    for name, kind, mult in ARMS:
        w = (mult * b["em"][ent]) if kind == "em" else np.full(len(ent), mult * b["atr"])
        n = len(ent)
        ret = np.empty(n)
        for i in range(n):
            sf, wi = stop_frac[i], w[i]
            armed = False
            res = None
            for j in range(HORIZON):
                if not armed:
                    # the original stop still governs until the trail arms
                    if adv[i, j] >= sf:
                        res = -sf
                        break
                    if runmax[i, j] >= TRAIL_ON_R * sf:
                        armed = True
                if armed:
                    # trail sits wi behind the best excursion so far; conservative within-bar
                    if adv[i, j] >= sf and runmax[i, j] <= TRAIL_ON_R * sf:
                        res = -sf
                        break
                    give = runmax[i, j] - wi
                    if fav[i, j] <= give and give > -sf:
                        res = give
                        break
                    if adv[i, j] >= sf:
                        res = -sf
                        break
            if res is None:
                res = close_ret[i, HORIZON - 1]
            ret[i] = res
        out[name] = (ret - FEE_FRAC) * 1e4
    return out


def main():
    print("M12 -- trail width in the coin's OWN volatility vs one exp_move. EXPLORATORY.")
    print("premise verified: ATR60/em median 2.31, low third 2.09 -> high third 2.85, corr +0.766.")
    print("M10's prior says WIDER trails should LOSE (positions up at 48h lost by being held).\n")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    snap = panel_snapshot.stamp(c)
    print("SOURCE SNAPSHOT: %s\n" % panel_snapshot.describe(snap))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    per, vol = {}, {}
    for coin in coins:
        b = prep(c, coin)
        if b is None:
            continue
        n = len(b["c"])
        ok = np.flatnonzero(np.isfinite(b["em"][:n - HORIZON - 1]))
        ok = ok[ok > 40]
        if len(ok) < 80:
            continue
        ent = rng.choice(ok, size=min(ENTRIES, len(ok)), replace=False)
        side = np.where(rng.random(len(ent)) < 0.5, 1.0, -1.0)
        real = simulate(b, ent, side, False)
        ctrl = simulate(b, ent, side, True)
        if real is None or ctrl is None:
            continue
        per[coin] = {k: float(np.mean(real[k]) - np.mean(ctrl[k])) for k in real}
        vol[coin] = b["atr"]
    c.close()
    if len(per) < 10:
        raise SystemExit("HALT: only %d coins simulated." % len(per))
    print("coins simulated: %d\n" % len(per))

    ks = sorted(per, key=lambda k: vol[k])
    t = len(ks) // 3
    groups = (("ALL", ks), ("low-vol third", ks[:t]), ("mid-vol third", ks[t:2 * t]),
              ("HIGH-vol third", ks[2 * t:]),
              ("ORIG17", [k for k in ks if k in ORIG17]),
              ("non-ORIG17", [k for k in ks if k not in ORIG17]))
    out = {"source_snapshot": snap, "premise": {"atr_em_median": 2.31, "corr_atr_ratio": 0.766},
           "unit": "bps_net_of_fees", "groups": {}}
    for gname, gk in groups:
        if len(gk) < 5:
            continue
        print("--- %s (%d coins, mean ATR %.1f%%/day) ---" %
              (gname, len(gk), 100 * float(np.mean([vol[k] for k in gk]))))
        base = None
        for name, _, _ in ARMS:
            a = np.asarray([per[k][name] for k in gk], float)
            a = a[np.isfinite(a)]
            idx = rng.integers(0, len(a), size=(BOOT, len(a)))
            ms = a[idx].mean(axis=1)
            m, se = float(a.mean()), float(np.std(ms, ddof=1))
            lo, hi = float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))
            if base is None:
                base = m
            d = m - base
            print("  %-14s %+8.2f bps [%+8.2f,%+8.2f]   vs incumbent %+8.2f"
                  % (name, m, lo, hi, d))
            out["groups"].setdefault(gname, {})[name] = {
                "mean_bps": m, "ci": [lo, hi], "vs_incumbent": d, "coins": int(len(a))}
        print()
    io.open(os.path.join(HERE, "m12_trail_width.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("wrote m12_trail_width.json")
    print("INTERACTION TEST: ATR-scaling is only vindicated if it beats the incumbent MORE in the")
    print("HIGH-vol third than in the low. A flat gain would mean width alone, not scaling.")


if __name__ == "__main__":
    main()
