"""M2 -- does small-cap perp momentum continue after costs?

Design is SEALED in PREREG_M2_SMALLCAP_2026-10-11.md
(SHA-256 91c39ce72023e2090cdc5a89ff83586fa8bcd168c4f4fcf75fa338e75d8c892b, committed 2d132ff7
BEFORE any small-cap result existed). Nothing below deviates from it; where the data forced a
choice, the prereg had already fixed it.

The owner claim, verbatim: "some of the smaller bigger momentum ones that we have been noticing
and having on lists couldve had some really good calls for us if we have chosen to dive into them
once we found some trend."

Why this cannot just look at those coins: they were noticed BECAUSE they ran. The remembered set is
selected on the outcome and cannot come out negative. So this applies a mechanical rule to every
qualifying coin in the panel, including every coin that trended and then died.

And the bias that survives even so, stated in the prereg before the run: Hyperliquid serves no
candles for DELISTED perps, so this universe is survivors only. Any positive number here is an
UPPER BOUND.
"""
import csv
import glob
import io
import json
import os

import numpy as np

rng = np.random.default_rng(20261011)

TOP_EXCLUDE = 15
WIN = 480            # 20 days of hours -- the trailing window for every baseline
HORIZONS = (1, 4, 24, 72)
NDRAW = 20           # matched draws per event, per null
MATCH_H = 336        # +/-14 days for the coin-matched null
FEES = (18.0, 40.0, 80.0)
HEADLINE_FEE = 40.0
ZBAR = 2.95          # Bonferroni over 16 cells
MIN_BARS = 600
MIN_ELIGIBLE = 10


def load():
    coins = {}
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
        if len(t) < MIN_BARS:
            continue
        o = np.argsort(np.asarray(t))
        coins[sym] = {"t": np.asarray(t)[o], "c": np.asarray(c)[o], "v": np.asarray(v)[o]}
    return coins


def roll_mean_prior(x, w):
    """Trailing mean over the w bars ENDING ONE BAR BEFORE i -- no same-bar leakage."""
    out = np.full(len(x), np.nan)
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])
    for i in range(w + 1, len(x)):
        out[i] = (cs[i] - cs[i - w]) / w
    return out


def roll_sum(x, w):
    out = np.full(len(x), np.nan)
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])
    for i in range(w - 1, len(x)):
        out[i] = cs[i + 1] - cs[i + 1 - w]
    return out


def roll_max_prior(x, w):
    """Max over the w bars STRICTLY BEFORE i."""
    out = np.full(len(x), np.nan)
    for i in range(w + 1, len(x)):
        out[i] = x[i - w:i].max()
    return out


def build(coins):
    """Per coin: signals, forward returns, trailing dollar volume. All point-in-time."""
    for sym, d in coins.items():
        c, v = d["c"], d["v"]
        dv = c * v
        d["dv20"] = roll_mean_prior(dv, WIN)       # ranking variable, prior bars only
        dv24 = roll_sum(dv, 24)
        d["dollar_vol_24h"] = dv24
        base24 = roll_mean_prior(dv24, WIN)
        hi = roll_max_prior(c, WIN)
        ret24 = np.full(len(c), np.nan)
        ret24[24:] = c[24:] / c[:-24] - 1.0
        expmove = roll_mean_prior(np.abs(ret24), WIN)
        bad = np.isnan(hi) | np.isnan(base24) | np.isnan(expmove) | np.isnan(dv24)
        with np.errstate(invalid="ignore"):
            s1 = c > hi
            s2 = dv24 > 2.0 * base24
            s4 = (ret24 > 1.5 * expmove) & (ret24 > 0)
        d["S1_breakout"] = np.where(bad, False, s1)
        d["S2_volsurge"] = np.where(bad, False, s2)
        d["S4_movesurge"] = np.where(bad, False, s4)
        d["S3_both"] = d["S1_breakout"] & d["S2_volsurge"]
        for h in HORIZONS:
            f = np.full(len(c), np.nan)
            f[:-h] = (c[h:] / c[:-h] - 1.0) * 100.0
            d[f"fwd{h}"] = f
        d["any"] = d["S1_breakout"] | d["S2_volsurge"] | d["S4_movesurge"]
    return coins


def eligibility(coins):
    """At each timestamp, rank by TRAILING dollar volume and drop the top 15.
    Current-day volume is never used for ranking -- that would leak the future."""
    idx = {}
    for sym, d in coins.items():
        for i, t in enumerate(d["t"]):
            idx.setdefault(int(t), []).append((sym, i))
    elig = {}
    for t, members in idx.items():
        vs = [(s, i, coins[s]["dv20"][i]) for s, i in members]
        vs = [x for x in vs if x[2] == x[2]]
        if len(vs) < MIN_ELIGIBLE + TOP_EXCLUDE:
            continue
        vs.sort(key=lambda x: -x[2])
        elig[t] = [(s, i) for s, i, _ in vs[TOP_EXCLUDE:]]
    return elig


def collect(coins, elig, sig, h):
    """One row per signal event: the real forward return and both matched nulls."""
    key = f"fwd{h}"
    pool = {}
    for t, mem in elig.items():
        pool[t] = [(s, i) for s, i in mem
                   if not coins[s]["any"][i] and coins[s][key][i] == coins[s][key][i]]
    ev = []
    for t, mem in elig.items():
        pl = pool.get(t, [])
        if len(pl) < 5:
            continue
        for s, i in mem:
            d = coins[s]
            if not d[sig][i] or d[key][i] != d[key][i]:
                continue
            lo = max(0, i - MATCH_H)
            hi2 = min(len(d["t"]), i + MATCH_H + 1)
            ok = (~d["any"][lo:hi2]) & (~np.isnan(d[key][lo:hi2]))
            cand = np.flatnonzero(ok) + lo
            if len(cand) < 5:
                continue
            n1 = float(np.mean(d[key][rng.choice(cand, min(NDRAW, len(cand)), replace=False)]))
            pick = rng.choice(len(pl), min(NDRAW, len(pl)), replace=False)
            n2 = float(np.mean([coins[pl[j][0]][key][pl[j][1]] for j in pick]))
            dvv = d["dollar_vol_24h"][i]
            ev.append({"t": int(t), "sym": s, "real": float(d[key][i]), "n1": n1, "n2": n2,
                       "dv": float(dvv) if dvv == dvv else 0.0})
    return ev


def day_blocks(ev, field):
    days = {}
    for e in ev:
        days.setdefault(int(e["t"] // 86_400_000), []).append(e["real"] - e[field])
    return days


def boot(days, iters=2000):
    """Day-clustered bootstrap. The clustering unit is the signal DAY, because many small caps
    fire together -- that design effect is what broke earlier work in this project."""
    keys = list(days)
    if len(keys) < 12:
        return (float("nan"),) * 4
    flat = np.concatenate([np.asarray(days[k]) for k in keys])
    n = len(keys)
    ms = np.empty(iters)
    for b in range(iters):
        pick = rng.integers(0, n, n)
        ms[b] = np.concatenate([days[keys[j]] for j in pick]).mean()
    ms.sort()
    lo = float(ms[int(.025 * iters)])
    hi = float(ms[int(.975 * iters)])
    return float(flat.mean()), lo, hi, (hi - lo) / 3.92


def design_effect(days):
    """1+(m-1)rho from the measured within-day correlation of event returns."""
    vals = [np.asarray(v, dtype=float) for v in days.values()]
    gs = [g for g in vals if len(g) > 1]
    allv = np.concatenate(vals)
    gm, gv = allv.mean(), allv.var()
    if not gs or gv <= 0:
        return 1.0, 0.0, float(np.mean([len(v) for v in vals]))
    num = np.mean([(((g - gm).sum() ** 2) - ((g - gm) ** 2).sum()) / (len(g) * (len(g) - 1))
                   for g in gs])
    rho = max(0.0, min(1.0, num / gv))
    m = float(np.mean([len(v) for v in vals]))
    return 1 + (m - 1) * rho, rho, m


def concentration(ev, field):
    r = np.sort(np.asarray([e["real"] - e[field] for e in ev]))
    tot = r.sum()
    k = max(1, len(r) // 20)
    return (100.0 * r[-k:].sum() / tot) if tot else float("nan"), 100.0 * float(np.mean(r > 0))


def halves(ev, field):
    ts = sorted(e["t"] for e in ev)
    mid = ts[len(ts) // 2]
    a = [e for e in ev if e["t"] < mid]
    b = [e for e in ev if e["t"] >= mid]
    f = lambda z: float(np.mean([e["real"] - e[field] for e in z])) if len(z) > 20 else float("nan")
    return f(a), f(b)


def main():
    coins = build(load())
    print("M2 SMALL-CAP MOMENTUM -- prereg 91c39ce7, sealed and committed before this ran")
    print("  panel: %d coins with >= %d bars of 1h history" % (len(coins), MIN_BARS))
    elig = eligibility(coins)
    nel = np.mean([len(v) for v in elig.values()]) if elig else 0
    print("  %d timestamps with >= %d eligible coins after dropping the top %d by TRAILING volume"
          % (len(elig), MIN_ELIGIBLE, TOP_EXCLUDE))
    print("  mean eligible coins per timestamp: %.0f" % nel)
    print()
    print("  SURVIVORSHIP, from the prereg: HL serves no candles for delisted perps, so this")
    print("  universe is survivors only. Delisted small caps mostly went to zero, and a")
    print("  momentum-long rule would have bought some of them. Every positive number below")
    print("  is an UPPER BOUND.")
    print()

    sigs = ["S1_breakout", "S2_volsurge", "S3_both", "S4_movesurge"]
    out = {}
    print("%-14s %3s %7s %6s %10s %10s %7s %10s %7s %8s %6s"
          % ("signal", "hz", "events", "days", "realgross", "vs N1", "z(N1)", "vs N2", "z(N2)",
             "MDE", "deff"))
    print("-" * 110)
    for sig in sigs:
        for h in HORIZONS:
            ev = collect(coins, elig, sig, h)
            if len(ev) < 40:
                print("%-14s %3d %7d   too few events" % (sig, h, len(ev)))
                out[f"{sig}|{h}h"] = {"events": len(ev)}
                continue
            raw = float(np.mean([e["real"] for e in ev]))
            d1 = day_blocks(ev, "n1")
            d2 = day_blocks(ev, "n2")
            m1, l1, h1, se1 = boot(d1)
            m2, l2, h2, se2 = boot(d2)
            z1 = m1 / se1 if se1 == se1 and se1 > 0 else float("nan")
            z2 = m2 / se2 if se2 == se2 and se2 > 0 else float("nan")
            deff, rho, mbar = design_effect(d1)
            mde = 2.8 * max(se1, se2) * 100 if se1 == se1 and se2 == se2 else float("nan")
            print("%-14s %3d %7d %6d %+9.2f%% %+9.2f%% %7.2f %+9.2f%% %7.2f %6.0fbp %6.1f"
                  % (sig, h, len(ev), len(d1), raw, m1, z1, m2, z2, mde, deff))
            c5, pos = concentration(ev, "n1")
            ha, hb = halves(ev, "n1")
            out[f"{sig}|{h}h"] = {
                "events": len(ev), "days": len(d1), "real_gross_pct": round(raw, 4),
                "vs_n1_pct": round(m1, 4), "ci_n1": [round(l1, 4), round(h1, 4)],
                "z_n1": None if z1 != z1 else round(z1, 2),
                "vs_n2_pct": round(m2, 4), "ci_n2": [round(l2, 4), round(h2, 4)],
                "z_n2": None if z2 != z2 else round(z2, 2),
                "mde_bps": None if mde != mde else round(mde, 1),
                "design_effect": round(deff, 2), "rho_within_day": round(rho, 4),
                "mean_events_per_day": round(mbar, 1),
                "top5pct_share_of_return": None if c5 != c5 else round(c5, 1),
                "pct_events_positive": round(pos, 1),
                "half1_pct": None if ha != ha else round(ha, 4),
                "half2_pct": None if hb != hb else round(hb, 4),
                "net_bps": {str(int(f)): round(min(m1, m2) * 100 - f, 1) for f in FEES},
            }
        print()

    print("GATE CHECK -- the five prereg conditions, applied without discretion")
    print("  (1) |z| > %.2f on BOTH nulls   (2) net of %.0f bps positive" % (ZBAR, HEADLINE_FEE))
    print("  (3) top 5%% of events < 50%% of return   (4) sign repeats in both halves")
    print("  (5) survivorship bound restated")
    print()
    passed = []
    shown = 0
    for k, v in out.items():
        if v.get("z_n1") is None or v.get("z_n2") is None:
            continue
        g1 = abs(v["z_n1"]) > ZBAR and abs(v["z_n2"]) > ZBAR
        g2 = v["net_bps"][str(int(HEADLINE_FEE))] > 0
        g3 = v["top5pct_share_of_return"] is not None and v["top5pct_share_of_return"] < 50
        g4 = (v["half1_pct"] is not None and v["half2_pct"] is not None
              and v["half1_pct"] * v["half2_pct"] > 0)
        if g1 and g2 and g3 and g4:
            passed.append(k)
        if g1 or g2:
            print("  %-20s z %+.2f / %+.2f   net@%.0fbps %+.0f bps   top5%% %s%%   halves %s / %s"
                  % (k, v["z_n1"], v["z_n2"], HEADLINE_FEE, v["net_bps"][str(int(HEADLINE_FEE))],
                     v["top5pct_share_of_return"], v["half1_pct"], v["half2_pct"]))
            print("  %-20s gates: stat=%s  cost=%s  concentration=%s  walkforward=%s"
                  % ("", g1, g2, g3, g4))
            shown += 1
    if not shown:
        print("  no cell cleared either the statistical gate or the cost gate")
    json.dump({"prereg_sha256":
               "91c39ce72023e2090cdc5a89ff83586fa8bcd168c4f4fcf75fa338e75d8c892b",
               "top_exclude": TOP_EXCLUDE, "fees_bps": list(FEES),
               "headline_fee_bps": HEADLINE_FEE, "bonferroni_z": ZBAR,
               "n_coins": len(coins), "results": out, "all_gates_passed": passed},
              open("smallcap_momentum.json", "w"), indent=1)
    print()
    print("=" * 110)
    print("PASSES ALL FOUR TESTABLE GATES: %s" % (passed or "none"))
    print("=" * 110)


if __name__ == "__main__":
    main()
