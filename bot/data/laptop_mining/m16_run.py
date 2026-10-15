"""M16 -- limit-entry plan vs market plan, same-moment ITT. BUILD + GATES + READ per M16_AMENDMENT_1.

Spec encoded (see the amendment):
  * Grid: 24-bar-spaced moments, MOMENT-level dedupe on [t, t+72] same-coin windows keeping BOTH sides.
  * Arms per moment-side: M = market plan filled at bar t+1 OPEN; L(d) = resting limit at
    close(t) -/+ d*ATR14(t), d in {0.25, 0.5, 0.75} (family) + 1.0 (descriptive); watch W=24h FROZEN;
    fill at the limit level (maker convention; open-through share reported); ITT: no fill -> 0.
    Runner engine from each fill with widths re-resolved at the FILL day; fill bar stop-first.
  * Common denominator: every outcome / sf0 = 1.65 x em(t) (own-em_f sensitivity printed).
  * Controls: K=8 + nullreal martingale continuations anchored at t (pool strictly before t), 72 bars,
    SAME M and L logic on each draw; control fills resolve em/ATR from the real calendar (stated limit).
  * Paired scalar per chain per d: mean over sides of [(L-M)_real - (L-M)_ctrlmean]; CI = widest of
    coin-eqw / chain / coin x week on that scalar. Family = 3 cells at z>=3.0.
  * Mandatory decomposition per cell: p, E[L-M | fill] (vs the identically fill-conditioned control
    contrast), (1-p)*(-E[M | no-fill]); fee*(1-p) line; fill rate real vs control.
  * Null gate then positive control (fill-weighted linearity + detection at 1.5 x own MDE) before the read.
"""
import io
import json
import os
import sqlite3

import numpy as np

import panel_snapshot
from m13_build import daily, em_pit, atr_pit, fund_series, rate_at, K_STOP
from m14_run import run_runner, synth_cont

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
SPACING = 24
W = 24
HOLD = 48
CONT = W + HOLD
K_CTRL = 8
DS = (0.25, 0.5, 0.75, 1.0)      # family = first three; 1.0 descriptive
Z_BAR = 3.0
rng = np.random.default_rng(20261018)


def limit_fill(lows, highs, level, side):
    """First watch bar (0..W-1) whose range reaches the limit. Returns index or None."""
    if side > 0:
        for j in range(min(W, len(lows))):
            if lows[j] <= level:
                return j
    else:
        for j in range(min(W, len(highs))):
            if highs[j] >= level:
                return j
    return None


def arms_on(O, H, L, C, side, sf0, px0, atr0, em_bar, atr_bar, rates):
    """All arms on one continuation (real or synthetic). Bars are absolute prices for CONT bars after
    the moment. em_bar/atr_bar: per-bar point-in-time widths aligned to the real calendar (len CONT).
    Returns dict: M, L{d} (ITT, / sf0), fill flags, open-through flag."""
    out = {"fills": {}, "openthru": 0}
    # M: fill at bar-0 open
    em_f, atr_f = em_bar[0], atr_bar[0]
    if np.isfinite(em_f) and np.isfinite(atr_f) and atr_f > 0:
        out["M"] = run_runner(O, H, L, C, O[0], K_STOP * em_f, atr_f, HOLD, side, rates) / sf0
    else:
        out["M"] = 0.0
    for d in DS:
        level = px0 * (1 - side * d * atr0)
        j = limit_fill(L, H, level, side)
        key = "L%.2f" % d
        if j is None:
            out[key] = 0.0
            out["fills"][d] = 0
            continue
        out["fills"][d] = 1
        if (side > 0 and O[j] < level) or (side < 0 and O[j] > level):
            out["openthru"] += 1          # open already through: maker fills at the limit anyway
        em_f, atr_f = em_bar[j], atr_bar[j]
        if not (np.isfinite(em_f) and np.isfinite(atr_f) and atr_f > 0):
            out[key] = 0.0
            out["fills"][d] = 0
            continue
        sub = slice(j, min(j + HOLD, len(C)))
        out[key] = run_runner(O[sub], H[sub], L[sub], C[sub], level, K_STOP * em_f, atr_f,
                              HOLD, side, rates[sub]) / sf0
    return out


def main():
    print("M16 (Amendment 1). Paired MDE expected 0.011-0.015 R -- NOT a screen.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    moments = []
    for coin in coins:
        rows = c.execute("SELECT t,o,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        fr = fund_series(c, coin)
        t_s = np.where(b["t"] > 1e12, b["t"] / 1000.0, b["t"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - CONT - 2)]
        if len(elig) < 40:
            continue
        off = int(rng.integers(0, SPACING))
        kept, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= CONT:     # moment-level dedupe: windows [t, t+72] disjoint
                kept.append(e)
                last = e
        for e in kept:
            sf0 = K_STOP * em_h[e]
            px0 = b["c"][e]
            bars = slice(e + 1, e + 1 + CONT)
            O, H, L, C = b["o"][bars], b["h"][bars], b["l"][bars], b["c"][bars]
            em_bar = em_h[e + 1:e + 1 + CONT]
            atr_bar = atr_h[e + 1:e + 1 + CONT]
            rates = rate_at(fr, t_s[e + 1:e + 1 + CONT][None, :])[0] if len(fr) else np.zeros(CONT)
            sp = synth_cont(b, e, K_CTRL + 1, CONT)
            if sp is None:
                continue
            mo = {"coin": coin, "daykey": int(uq[dix[e]]), "sides": {}}
            okm = True
            for side in (1.0, -1.0):
                real = arms_on(O, H, L, C, side, sf0, px0, atr_h[e], em_bar, atr_bar, rates)
                ctr = []
                for ki in range(K_CTRL):
                    ctr.append(arms_on(sp[0][ki], sp[1][ki], sp[2][ki], sp[3][ki], side, sf0, px0,
                                       atr_h[e], em_bar, atr_bar, rates))
                nul = arms_on(sp[0][K_CTRL], sp[1][K_CTRL], sp[2][K_CTRL], sp[3][K_CTRL], side, sf0,
                              px0, atr_h[e], em_bar, atr_bar, rates)
                mo["sides"][side] = {"real": real, "ctrl": ctr, "null": nul}
            moments.append(mo)
        if len(moments) % 1000 < 2 and len(moments) > 100:
            print("  %d moments..." % len(moments))
    c.close()
    if len(moments) < 2000:
        raise SystemExit("HALT: only %d moments." % len(moments))
    print("moments kept: %d (both sides each)" % len(moments))

    coins_u = sorted(set(m["coin"] for m in moments))
    cidx = {k: i for i, k in enumerate(coins_u)}
    carr = np.array([cidx[m["coin"]] for m in moments])
    week = np.array([m["daykey"] // 7 for m in moments])

    def scalars(src, d):
        key = "L%.2f" % d
        out = np.zeros(len(moments))
        for i, m in enumerate(moments):
            v = 0.0
            for side in (1.0, -1.0):
                s_ = m["sides"][side]
                r_ = s_[src] if src != "real" else s_["real"]
                cl = np.mean([ct[key] - ct["M"] for ct in s_["ctrl"]])
                v += (r_[key] - r_["M"]) - cl
            out[i] = v / 2.0
        return out

    def cell(v, idx=None):
        ca = carr if idx is None else carr[idx]
        wk = week if idx is None else week[idx]
        cm = np.zeros(len(coins_u)); cc = np.zeros(len(coins_u))
        np.add.at(cm, ca, v); np.add.at(cc, ca, 1)
        has = cc > 0
        per = cm[has] / cc[has]
        b1 = [per[rng.integers(0, len(per), len(per))].mean() for _ in range(3000)]
        b2 = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(3000)]
        # coin x week
        cw = ca * 100000 + wk
        ucw, inv = np.unique(cw, return_inverse=True)
        cmu = np.bincount(inv, weights=v) / np.bincount(inv)
        ccn = ucw // 100000; cwk = ucw % 100000
        uc2, uw2 = np.unique(ccn), np.unique(cwk)
        b3 = []
        for _ in range(1500):
            cs_ = uc2[rng.integers(0, len(uc2), len(uc2))]
            ws_ = uw2[rng.integers(0, len(uw2), len(uw2))]
            sel = cmu[np.isin(ccn, cs_) & np.isin(cwk, ws_)]
            if len(sel): b3.append(sel.mean())
        los = [np.percentile(x, 2.5) for x in (b1, b2, b3)]
        his = [np.percentile(x, 97.5) for x in (b1, b2, b3)]
        w_ = int(np.argmax([h - l for l, h in zip(los, his)]))
        lo, hi = los[w_], his[w_]
        se = (hi - lo) / 3.92
        return {"mean": float(v.mean()), "eqw_coin": float(per.mean()), "lo": float(lo), "hi": float(hi),
                "se": float(se), "z": float(v.mean() / se if se > 0 else 0), "n": len(v)}

    print("=== NULL GATE (nullreal - ctrl, 3 family cells) ===")
    ng = {}
    for d in DS[:3]:
        ng[d] = cell(scalars("null", d))
        print("  [NULL d=%.2f] %+0.4f [%+0.4f,%+0.4f] z %+0.2f" % (d, ng[d]["mean"], ng[d]["lo"], ng[d]["hi"], ng[d]["z"]))
    if max(abs(r["z"]) for r in ng.values()) >= Z_BAR:
        raise SystemExit("HALT: NULL GATE FAILED.")
    mde = {d: 2.8 * ng[d]["se"] for d in ng}
    print("NULL GATE PASSED. per-cell MDE:", {("%.2f" % d): round(v, 4) for d, v in mde.items()})

    print("=== POSITIVE CONTROL (d=0.50: fill-weighted linearity + detection at 1.5 x own MDE) ===")
    d0 = 0.5
    key = "L%.2f" % d0
    base = ng[d0]["mean"]
    pf_null = np.mean([np.mean([m["sides"][s]["null"]["fills"][d0] for s in (1.0, -1.0)]) for m in moments])
    for shift in (0.10, None):
        eff = shift if shift else 1.5 * mde[d0] / max(pf_null, 1e-9)
        v = scalars("null", d0).copy()
        add = np.array([np.mean([m["sides"][s]["null"]["fills"][d0] * eff for s in (1.0, -1.0)]) for m in moments])
        r_ = cell(v + add)
        rec = r_["mean"] - base
        expect = pf_null * eff
        lin = abs(rec - expect) <= 0.1 * expect + 1e-9
        det = abs((r_["mean"] - base) / ng[d0]["se"]) >= 2.8 if shift is None else True
        print("  inject %.4f/fill (p_null=%.2f) -> recovered %+0.4f vs expected %+0.4f (lin %s, det %s)"
              % (eff, pf_null, rec, expect, lin, det))
        if not (lin and det):
            raise SystemExit("HALT: POSITIVE CONTROL FAILED.")
    print("POSITIVE CONTROL PASSED.")

    print("=== THE READ (3 pooled-side paired cells, z>=%.1f; d=1.00 descriptive) ===" % Z_BAR)
    res = {}
    for d in DS:
        v = scalars("real", d)
        r_ = cell(v)
        res[d] = r_
        key = "L%.2f" % d
        # decomposition on real
        fills, lmf, mnf, p_ct = [], [], [], []
        for m in moments:
            for s in (1.0, -1.0):
                sd = m["sides"][s]
                f = sd["real"]["fills"][d]
                fills.append(f)
                p_ct.append(np.mean([ct["fills"][d] for ct in sd["ctrl"]]))
                if f:
                    lmf.append(sd["real"][key] - sd["real"]["M"])
                else:
                    mnf.append(sd["real"]["M"])
        p = float(np.mean(fills))
        term_fill = p * float(np.mean(lmf)) if lmf else 0.0
        term_miss = (1 - p) * -float(np.mean(mnf)) if mnf else 0.0
        tag = "FAMILY" if d < 1.0 else "descriptive"
        print("  [d=%.2f %s] ITT %+0.4f [%+0.4f,%+0.4f] z %+0.2f | p=%.2f (ctrl %.2f) | "
              "fill-term %+0.4f  miss-term %+0.4f | fee*(1-p)=%+0.4f"
              % (d, tag, r_["mean"], r_["lo"], r_["hi"], r_["z"], p, float(np.mean(p_ct)),
                 term_fill, term_miss, 0.017 * (1 - p)))
    io.open(os.path.join(HERE, "m16_result.json"), "w", encoding="utf-8").write(json.dumps(
        {"moments": len(moments), "null": {str(k): v for k, v in ng.items()},
         "mde": {str(k): v for k, v in mde.items()},
         "read": {str(k): v for k, v in res.items()}}, indent=1, default=float))
    print("wrote m16_result.json")


if __name__ == "__main__":
    main()
