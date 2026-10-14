"""M10 -- is the 48h plan time limit costing the owner? EXPLORATORY.

OWNER, verbatim: "why do we have the 48 hr time stop? it would've just timed us out at a rough time."
His ETH long passed 48h at -0.67R by the grader and he chose to hold. Every owner plan and Claude idea
carries max_hold_h=48, which is plans.py's DEFAULT -- a grading window, never tested.

THAT FRAMING DECIDES THE BAR. This is not a safeguard derived from evidence that I would need the
harshest possible risk measure to overturn; it is an arbitrary constant. The question is simply whether
a better default exists, and "no evidence either way" is a legitimate and likely answer.

THE TRAP THIS FILE EXISTS TO AVOID. With random-time both-sided entries there is no directional edge,
so raw expectancy is about -(fees) at EVERY horizon and a naive table would look flat and meaningless.
Different horizons are not equally priced under no edge either: a TIMEOUT samples the price
distribution at a fixed clock time, while stop and target are BARRIER exits. So the M1 v3 martingale
control (bootstrap of each coin's own bar shapes, multiplicative steps normalised to E[step] == 1) is
run per horizon and SUBTRACTED. Without that this study measures geometry, not the time limit.

AND THE AVERAGE IS NOT THE OWNER'S QUESTION. His complaint is conditional: a timeout that fires while
the position is UNDERWATER books a loss that might have recovered. So the headline table is followed by
the conditional that actually answers him -- among entries still open at 48h, what does holding to 7d
do, split by whether they were up or down at the 48h mark.

GEOMETRY, matching what the bot and the plans actually use:
  stop A  K = 1.65 x fitted exp_move   (the live stop multiple)
  stop B  fixed 1.70%                  (the bot's typical stop distance, per the server)
  target  2 x stop (2R) in both arms, so the R scale is comparable across horizons
  limits  24h / 48h / 72h / 7d / 30d, where 30d stands in for "none" (the planner's own mapping)
  exit    first of stop, target, or the time limit; same-bar stop/target ambiguity counted as the STOP

SPLITS. The owner asked about the MAJORS, and all six majors sit inside ORIG17 -- the discovery set --
so a majors-only answer cannot also be held out. Reported three ways and labelled: MAJORS (what he
asked), ORIG17 (discovery), NON-ORIG17 (held out). Agreement across them is the only thing that makes
this credible.

EXPLORATORY: no card above HYPOTHESIS. A recommendation for the default is the deliverable, and
"leave 48h alone" is an acceptable one.
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
FEE_FRAC = 0.0009                  # 9 bps round-trip taker, the project's unit
K_EM = 1.65                        # live stop multiple on exp_move
FIX_STOP = 0.0170                  # the bot's ~1.7% stop
TGT_R = 2.0                        # target at 2R in both geometries
LIMITS_H = (24, 48, 72, 168, 720)  # 720h = 30d stands for the planner's "none"
MAXH = max(LIMITS_H)
ENTRIES_PER_COIN = 150
BOOT = 4000
rng = np.random.default_rng(20261014)

MAJORS = ("BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR")
ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def daily_em(b):
    """Live fitted-HAR exp_move (fraction) per 1h bar, plus the UTC day index."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    if len(close) < 40:
        return None, None
    rets = np.concatenate(([0.0], (close[1:] / close[:-1] - 1.0) * 100.0))
    em = np.full(len(uniq), np.nan)
    for i in range(30, len(uniq)):
        rv1, rv5, rv22 = abs(rets[i]), sd(list(rets[i - 4:i + 1])), sd(list(rets[i - 21:i + 1]))
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[i] = v
    return em[np.searchsorted(uniq, day)] / 100.0, day


def paths(b, ent, synthetic):
    """Forward (high, low, close) matrices for each entry, real bars or the v3 martingale control."""
    entry = b["c"][ent]
    if not synthetic:
        pidx = ent[:, None] + np.arange(1, MAXH + 1)[None, :]
        return entry, b["h"][pidx], b["l"][pidx], b["c"][pidx]
    # M1 v3: bootstrap the coin's OWN bar shapes, then normalise the multiplicative steps so
    # E[step] == 1 exactly. v2 demeaned LOG returns, which by Jensen leaves +sig^2/2 arithmetic
    # drift per bar -- over 720 bars that would dwarf the effect being measured.
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
    lr, up, dn = lr[g], np.maximum(up[g], 0.0), np.maximum(dn[g], 0.0)
    if len(lr) < 200:
        return None, None, None, None
    draw = rng.integers(0, len(lr), size=(len(ent), MAXH))
    step = np.exp(lr[draw]) / float(np.mean(np.exp(lr)))
    C = entry[:, None] * np.cumprod(step, axis=1)
    prev = np.concatenate((entry[:, None], C[:, :-1]), axis=1)
    H = np.maximum(prev, C) * (1.0 + up[draw])
    L = np.minimum(prev, C) * (1.0 - dn[draw])
    return entry, H, L, C


def outcomes(entry, side, H, L, C, stop_frac):
    """bps of notional net of fees for every time limit, plus the 48h state. One stop geometry."""
    tgt_frac = TGT_R * stop_frac
    adv = np.where(side[:, None] > 0, (entry[:, None] - L) / entry[:, None],
                   (H - entry[:, None]) / entry[:, None])
    fav = np.where(side[:, None] > 0, (H - entry[:, None]) / entry[:, None],
                   (entry[:, None] - L) / entry[:, None])
    s_hit = adv >= stop_frac[:, None]
    t_hit = fav >= tgt_frac[:, None]
    sb = np.where(s_hit.any(axis=1), s_hit.argmax(axis=1), 10 ** 6)
    tb = np.where(t_hit.any(axis=1), t_hit.argmax(axis=1), 10 ** 6)
    mark = side * (C / entry[:, None] - 1.0) if False else None     # unused; kept explicit
    out = {}
    for h in LIMITS_H:
        last = h - 1
        stopped = (sb <= last) & (sb <= tb)                 # same bar => STOP (conservative)
        tgted = (~stopped) & (tb <= last)
        timed = (~stopped) & (~tgted)
        ret = np.where(stopped, -stop_frac,
                       np.where(tgted, tgt_frac, side * (C[:, last] / entry - 1.0)))
        out[h] = {"bps": (ret - FEE_FRAC) * 1e4,
                  "timeout_frac": float(np.mean(timed)),
                  "stop_frac_hit": float(np.mean(stopped)),
                  "tgt_frac_hit": float(np.mean(tgted))}
    # the owner's conditional: still open at 48h, and up or down at that moment
    l48 = 48 - 1
    open48 = (sb > l48) & (tb > l48)
    mark48 = side * (C[:, l48] / entry - 1.0)
    out["_open48"] = open48
    out["_down48"] = open48 & (mark48 < 0)
    out["_up48"] = open48 & (mark48 >= 0)
    return out


def run():
    print("M10 -- does the 48h plan time limit cost anything? EXPLORATORY, no card above HYPOTHESIS.")
    print("unit: bps of notional net of %0.0f bps fees. Martingale control SUBTRACTED per horizon."
          % (FEE_FRAC * 1e4))
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    snap = panel_snapshot.stamp(c)
    print("SOURCE SNAPSHOT: %s\n" % panel_snapshot.describe(snap))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]

    per = {}            # coin -> {geom -> {limit -> mean bps, net of control}}
    cond = {}           # coin -> conditional 48h arrays
    diag = {}
    for coin in coins:
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t",
                         (coin,)).fetchall()
        if len(rows) < MAXH + 400:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        em, _ = daily_em(b)
        if em is None:
            continue
        n = len(b["c"])
        ok = np.flatnonzero(np.isfinite(em[:n - MAXH - 1]))
        ok = ok[ok > 30]
        if len(ok) < 60:
            continue
        ent = rng.choice(ok, size=min(ENTRIES_PER_COIN, len(ok)), replace=False)
        side = np.where(rng.random(len(ent)) < 0.5, 1.0, -1.0)
        geoms = {"K1.65xem": K_EM * em[ent], "fixed1.7pct": np.full(len(ent), FIX_STOP)}
        res, c48 = {}, {}
        for gname, sfrac in geoms.items():
            e, H, L, Cl = paths(b, ent, False)
            real = outcomes(e, side, H, L, Cl, sfrac)
            e2, H2, L2, C2 = paths(b, ent, True)
            if e2 is None:
                res = None
                break
            ctrl = outcomes(e2, side, H2, L2, C2, sfrac)
            res[gname] = {h: float(np.mean(real[h]["bps"]) - np.mean(ctrl[h]["bps"]))
                          for h in LIMITS_H}
            res[gname + "_timeout"] = {h: real[h]["timeout_frac"] for h in LIMITS_H}
            if gname == "K1.65xem":
                # hold-to-7d minus close-at-48h, for entries still open at 48h
                o, d, u = real["_open48"], real["_down48"], real["_up48"]
                b48, b7d = real[48]["bps"], real[168]["bps"]
                c48 = {"n_open48": int(o.sum()),
                       "hold_minus_close_all": float(np.mean((b7d - b48)[o])) if o.any() else None,
                       "hold_minus_close_down": float(np.mean((b7d - b48)[d])) if d.any() else None,
                       "hold_minus_close_up": float(np.mean((b7d - b48)[u])) if u.any() else None,
                       "n_down48": int(d.sum()), "n_up48": int(u.sum())}
        if res is None:
            continue
        per[coin] = res
        cond[coin] = c48
        diag[coin] = len(ent)
    c.close()
    print("coins simulated: %d (entries/coin <= %d)\n" % (len(per), ENTRIES_PER_COIN))
    return snap, per, cond


def boot(vals):
    a = np.asarray([v for v in vals if v is not None and np.isfinite(v)], float)
    if len(a) < 3:
        return float("nan"), float("nan"), float("nan"), float("nan")
    idx = rng.integers(0, len(a), size=(BOOT, len(a)))
    ms = a[idx].mean(axis=1)
    m, se = float(a.mean()), float(np.std(ms, ddof=1))
    return m, float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5)), se


def report(per, cond, snap):
    groups = (("MAJORS (asked; inside DISCOVERY)", [k for k in per if k in MAJORS]),
              ("ORIG17 discovery", [k for k in per if k in ORIG17]),
              ("NON-ORIG17 held-out", [k for k in per if k not in ORIG17]))
    out = {"source_snapshot": snap, "unit": "bps_of_notional_net_of_fees",
           "control": "M1 v3 martingale, subtracted per horizon", "groups": {}}
    for gname, ks in groups:
        if len(ks) < 3:
            print("--- %s: only %d coins, skipped ---" % (gname, len(ks)))
            continue
        print("--- %s (%d coins) --- bps net of fees, control subtracted, eq-weighted by coin" %
              (gname, len(ks)))
        print("  %-14s %9s %19s %7s %9s" % ("stop", "limit", "95% CI", "z", "timeout%"))
        g = {}
        for geom in ("K1.65xem", "fixed1.7pct"):
            for h in LIMITS_H:
                m, lo, hi, se = boot([per[k][geom][h] for k in ks])
                to = float(np.mean([per[k][geom + "_timeout"][h] for k in ks])) * 100
                z = m / se if se and np.isfinite(se) and se > 0 else float("nan")
                lbl = "none(30d)" if h == 720 else ("7d" if h == 168 else "%dh" % h)
                print("  %-14s %9s [%+7.1f,%+7.1f] %7.2f %8.1f%%   %+.1f bps"
                      % (geom if h == LIMITS_H[0] else "", lbl, lo, hi, z, to, m))
                g["%s|%s" % (geom, lbl)] = {"mean_bps": m, "ci": [lo, hi], "z": z,
                                            "timeout_pct": to}
        out["groups"][gname] = g
        print()
    print("--- THE OWNER'S ACTUAL QUESTION: still open at 48h, hold to 7d vs close at 48h ---")
    print("    (K=1.65xem geometry; positive = holding beat the timeout, in bps net of fees)")
    for gname, ks in groups:
        ks = [k for k in ks if cond.get(k)]
        if len(ks) < 3:
            continue
        a_m, a_lo, a_hi, a_se = boot([cond[k]["hold_minus_close_all"] for k in ks])
        d_m, d_lo, d_hi, d_se = boot([cond[k]["hold_minus_close_down"] for k in ks])
        u_m, u_lo, u_hi, u_se = boot([cond[k]["hold_minus_close_up"] for k in ks])
        nopen = int(np.sum([cond[k]["n_open48"] for k in ks]))
        ndown = int(np.sum([cond[k]["n_down48"] for k in ks]))
        print("  %-34s open@48h %5d (down %5d)" % (gname, nopen, ndown))
        for lbl, (m, lo, hi, se) in (("all still open", (a_m, a_lo, a_hi, a_se)),
                                     ("DOWN at 48h", (d_m, d_lo, d_hi, d_se)),
                                     ("up at 48h", (u_m, u_lo, u_hi, u_se))):
            z = m / se if se and np.isfinite(se) and se > 0 else float("nan")
            print("      %-16s %+8.1f bps  [%+8.1f,%+8.1f]  z %6.2f" % (lbl, m, lo, hi, z))
        out.setdefault("conditional_48h", {})[gname] = {
            "n_open48": nopen, "n_down48": ndown,
            "all": {"mean_bps": a_m, "ci": [a_lo, a_hi]},
            "down": {"mean_bps": d_m, "ci": [d_lo, d_hi]},
            "up": {"mean_bps": u_m, "ci": [u_lo, u_hi]}}
    io.open(os.path.join(HERE, "m10_time_limit.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m10_time_limit.json")


if __name__ == "__main__":
    s, p, cd = run()
    if len(p) < 3:
        raise SystemExit("HALT: only %d coins simulated -- too few to report anything." % len(p))
    report(p, cd, s)
