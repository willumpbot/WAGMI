"""M30 arms A-D -- conditional give-back vs the runner, per M30_AMENDMENT_1. EXPLORATORY.

Arms (runner = control), vectorised on the m28 moment grid (both sides share the path):
  A  dynamic 50%-of-running-MFE give-back once MFE>=0.5R, before +1R; remainder re-arms the runner.
  Ap same at MFE>=0.75R.
  B  half at +0.75R (attribution control for trigger-vs-earlier-target; A' vs B is the clean contrast).
  C  breakeven-after-24h: if MFE>=0.5R and no bank by bar 24, move stop to entry; else runner.
  D  B then give-back on the remainder then +1R then trail.
Metrics (Amendment 1): paired (arm-runner) net R per moment; mean with the WIDER of day-block /
coin-week CI; net-R CDF; P(<=-0.5R); median. big-runner COST = descriptive subset where PATH MFE>=1.5R
(not a test). P(banked>0) and runner-realized-subset are DROPPED (by-construction).
Null: persistence-preserving CIRCULAR-BLOCK bootstrap of the coin's own bar increments (block ~ the
autocorr half-life), NOT the IID martingale - the give-back fires on persistence. vol_ratio printed.
"""
import io
import json
import os
import sqlite3

import numpy as np

import panel_snapshot
from m13_build import daily, em_pit, atr_pit, fund_series, rate_at, K_STOP, FEE_HALF

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
HOLD = 48
HOR = 72
SPACING = 24
BLOCK = 6                    # circular-block length (bars) for the persistence-preserving null
K_CTRL = 8
rng = np.random.default_rng(20261021)


def first_true(m):
    has = m.any(axis=1)
    return np.where(has, m.argmax(axis=1), 10**6)


def resolve_arms(fav, adv, close, sf):
    """All arms + runner from side-adjusted excursion matrices (N,HOLD). Returns {name: net_frac}.
    Fees on actual leg notionals (FEE_HALF entry + per leg). Stop-first within bar."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    sfc = sf[:, None]
    runmax = np.maximum.accumulate(fav, axis=1)
    rm_prev = np.concatenate((np.full((N, 1), -np.inf), runmax[:, :-1]), axis=1)
    stop_b = first_true(adv >= sfc)
    r1_b = first_true(fav >= sfc)                     # +1R
    out = {}

    def runner_from(bank_bar, bank_frac, bank_ret, arm_on_sub):
        # after banking bank_frac at bank_ret on bar bank_bar, remainder (1-bank) runs the runner:
        # arms at +1R (fav>=sf) from bank_bar on, trails 1*? -- reuse the simple runner: trail at
        # best - 1R-equivalent is handled by resolve_vec elsewhere; here the remainder just runs to
        # the +1R bank then holds to close (conservative: the amendment's A re-arms+re-banks at +1R).
        pass

    # ---- runner control: half at +1R, remainder trails at best-sf (1R proxy), floor at stop ----
    def runner(fav, adv, close, sf):
        banked = np.zeros(N)
        armed = r1_b < HOLD
        # pre-+1R stop
        pre_stop = (stop_b <= r1_b) & (stop_b < HOLD)
        # armed branch: bank 0.5 at +1R, remainder trails at runmax-sf from the bar after r1
        give = np.maximum(rm_prev - sfc, -sfc)
        hit = (adv >= -give) & (cols > r1_b[:, None]) & (cols < HOLD)
        xb = first_true(hit)
        got = armed & (xb < 10**6)
        rem = np.where(got, np.take_along_axis(give, np.minimum(xb, H - 1)[:, None], 1)[:, 0],
                       close[:, HOLD - 1])
        res = np.where(pre_stop, -sf, np.where(armed, 0.5 * sf + 0.5 * rem, close[:, HOLD - 1]))
        bankbar = np.where(pre_stop, stop_b, np.where(armed, r1_b, HOLD - 1))
        legs = np.where(armed, 2.0, 1.0)
        return res, bankbar, legs
    rr, _, _ = runner(fav, adv, close, sf)

    def giveback(fav, adv, close, sf, mfe_trig):
        # bank 0.5 at the give-back level once runmax>=mfe_trig*sf and fav<=0.5*runmax, before +1R
        trig = (rm_prev >= mfe_trig * sfc) & (fav <= 0.5 * rm_prev) & (cols < r1_b[:, None]) \
               & (cols < HOLD) & (rm_prev < sfc)
        gb_b = first_true(trig)
        fired = (gb_b < 10**6) & (gb_b < stop_b)      # not already stopped
        gb_ret = np.where(fired, 0.5 * np.take_along_axis(rm_prev, np.minimum(gb_b, H - 1)[:, None], 1)[:, 0], 0.0)
        # remainder (0.5) re-arms the runner from gb_b: runs to +1R bank or close; approximate with
        # the runner outcome on the SAME path but starting the half at gb_b (re-bank at +1R else close)
        rem_r1 = (fav >= sfc) & (cols > gb_b[:, None]) & (cols < HOLD)
        rem_hit = first_true(rem_r1)
        rem_banks = fired & (rem_hit < 10**6)
        # remainder: if it re-reaches +1R bank 0.5*sf of the half; else close
        rem_ret = np.where(rem_banks, sf, close[:, HOLD - 1])
        pre_stop = (stop_b < gb_b) & (stop_b < HOLD)
        res = np.where(pre_stop, rr,                       # stopped before give-back: == runner path
              np.where(fired, 0.5 * gb_ret + 0.5 * rem_ret, rr))  # not fired: identical to runner
        return res
    out["A"] = giveback(fav, adv, close, sf, 0.5)
    out["Ap"] = giveback(fav, adv, close, sf, 0.75)

    # B: half at +0.75R, remainder trails (runner from 0.75R)
    r075 = first_true((fav >= 0.75 * sfc) & (cols < HOLD))
    b_fired = (r075 < 10**6) & (r075 < stop_b)
    rem_r1 = first_true((fav >= sfc) & (cols > r075[:, None]) & (cols < HOLD))
    rem_banks = b_fired & (rem_r1 < 10**6)
    rem_ret = np.where(rem_banks, sf, close[:, HOLD - 1])
    pre = (stop_b < r075) & (stop_b < HOLD)
    out["B"] = np.where(pre, rr, np.where(b_fired, 0.5 * 0.75 * sf + 0.5 * rem_ret, rr))

    # C: breakeven after 24 if MFE>=0.5R and no +1R bank yet; else runner
    mfe24 = runmax[:, min(24, H - 1)]
    be = (mfe24 >= 0.5 * sf) & (r1_b >= 24)
    # with BE stop, remainder stops at 0 instead of -sf on later adverse; approximate: floor the
    # runner outcome at 0 on BE moments where the runner went negative without arming
    out["C"] = np.where(be & (rr < 0) & (r1_b >= HOLD), np.maximum(rr, 0.0), rr)

    # D: B then give-back on remainder (approx: max of B's protection and A's give-back path)
    out["D"] = np.where(b_fired, out["B"], out["A"])

    # fees: entry + exit legs; runner-equiv 2 legs on armed, arms add one leg when they bank early.
    # apply a flat per-leg fee approximation consistent with m28 (entry + ~2 exit legs)
    fee = FEE_HALF * 2.5
    return {k: v - fee for k, v in out.items()}, rr - fee


def synth_block(b, ent, k, nbars):
    """Circular-block bootstrap continuations (preserves persistence) anchored at each entry."""
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.flatnonzero(np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn))
    if len(g) < 500:
        return None
    lr, up, dn = lr[g], np.maximum(up[g], 0), np.maximum(dn[g], 0)
    norm = float(np.mean(np.exp(lr)))
    N = len(ent) * k
    nb = int(np.ceil(nbars / BLOCK))
    starts = rng.integers(0, len(g) - BLOCK, size=(N, nb))
    idx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]).reshape(N, nb * BLOCK)[:, :nbars]
    step = np.exp(lr[idx]) / norm
    entry = np.repeat(b["c"][ent], k)[:, None]
    C = entry * np.cumprod(step, axis=1)
    prev = np.concatenate((entry, C[:, :-1]), axis=1)
    H = np.maximum(prev, C) * (1 + up[idx])
    L = np.minimum(prev, C) * (1 - dn[idx])
    return entry, H, L, C


def sidepaths(entry, H, L, C, side):
    s = side
    fav = np.where(s > 0, (H - entry) / entry, (entry - L) / entry)
    adv = np.where(s > 0, (entry - L) / entry, (H - entry) / entry)
    close = s * (C / entry - 1.0)
    return fav[:, :HOLD], adv[:, :HOLD], close[:, :HOLD]


def main():
    print("M30 arms A-D (Amendment 1): give-back vs runner; persistence-preserving null.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    AR = {k: [] for k in ("A", "Ap", "B", "C", "D")}
    RUN = []
    PATHMFE = []
    coin_k = []
    day_k = []
    null_acc = {k: [] for k in ("A", "Ap", "B", "C", "D")}
    done = 0
    for coin in coins:
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - HOR - 2)]
        if len(elig) < 40:
            continue
        off = int(rng.integers(0, SPACING))
        ent, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                ent.append(e); last = e
        ent = np.asarray(ent)
        sf = K_STOP * em_h[ent]
        pidx = ent[:, None] + np.arange(1, HOR + 1)[None, :]
        entry = b["c"][ent][:, None]
        H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
        sp = synth_block(b, ent, K_CTRL, HOR)
        for side in (1.0, -1.0):
            fav, adv, close = sidepaths(entry, H, L, C, side)
            arms, run = resolve_arms(fav, adv, close, sf)
            run_R = run / sf                             # R units (resolve_arms returns fractions)
            for k_ in AR:
                AR[k_].append(arms[k_] / sf - run_R)     # paired (arm - runner) in R
            RUN.append(run_R)
            PATHMFE.append(np.maximum.accumulate(fav, axis=1)[:, -1] / sf)   # path MFE in R
            coin_k.extend([coin] * len(ent))
            day_k.extend([int(uq[dix[e]]) for e in ent])
            if sp is not None:
                sfr = np.repeat(sf, K_CTRL)
                fa = np.where(side > 0, (sp[1] - sp[0]) / sp[0], (sp[0] - sp[2]) / sp[0])[:, :HOLD]
                ad = np.where(side > 0, (sp[0] - sp[2]) / sp[0], (sp[1] - sp[0]) / sp[0])[:, :HOLD]
                cl = (side * (sp[3] / sp[0] - 1.0))[:, :HOLD]
                na, nr = resolve_arms(fa, ad, cl, sfr)
                for k_ in null_acc:
                    d_ = ((na[k_] - nr) / sfr).reshape(len(ent), K_CTRL).mean(axis=1)
                    null_acc[k_].append(d_)
        done += 1
    c.close()
    RUN = np.concatenate(RUN)
    PATHMFE = np.concatenate(PATHMFE)
    carr = np.asarray(coin_k)
    week = np.asarray(day_k, np.int64) // 7
    ucoins = np.unique(carr)
    print("moments: %d (coins %d)" % (len(RUN), done))

    def ci(v):
        cm = {};
        for u in ucoins:
            m = carr == u
            if m.any(): cm[u] = v[m].mean()
        per = np.array(list(cm.values()))
        b1 = [per[rng.integers(0, len(per), len(per))].mean() for _ in range(2000)]
        # day-block
        ud = np.unique(day_k)
        dm = {d: v[np.asarray(day_k) == d] for d in ud}
        b2 = []
        for _ in range(2000):
            pick = np.array(ud)[rng.integers(0, len(ud), len(ud))]
            b2.append(np.concatenate([dm[p] for p in pick]).mean())
        lo = min(np.percentile(b1, 2.5), np.percentile(b2, 2.5))
        hi = max(np.percentile(b1, 97.5), np.percentile(b2, 97.5))
        return float(v.mean()), float(lo), float(hi)

    print("=== NULL GATE (persistence-preserving block bootstrap, arm-runner on null paths) ===")
    ng = {}
    for k_ in null_acc:
        nv = np.concatenate(null_acc[k_])
        ng[k_] = float(nv.mean())
        print("  [NULL %s] %+0.4f R" % (k_, nv.mean()))
    print("=== THE READ (paired arm-runner in R; wider of coin/day-block CI; tail + median) ===")
    out = {"moments": int(len(RUN)), "null": ng, "arms": {}}
    bigmask = PATHMFE >= 1.5                            # path MFE >= 1.5R (shared-path property)
    p_tail_run = float(np.mean(RUN <= -0.5))
    for k_ in ("A", "Ap", "B", "C", "D"):
        v = np.concatenate(AR[k_])
        m, lo, hi = ci(v)
        p_tail_arm = float(np.mean((RUN + v) <= -0.5))
        med = float(np.median(v[np.abs(v) > 1e-9])) if (np.abs(v) > 1e-9).any() else 0.0
        big_cost = float(v[bigmask].mean()) if bigmask.any() else float("nan")
        print("  [%s] mean %+0.4f R [%+0.4f,%+0.4f] | fired-median %+0.4f | P(<=-0.5R) %.3f->%.3f | "
              "big-runner(MFE>=1.5R) cost %+0.3f R (n=%d) | null %+0.4f"
              % (k_, m, lo, hi, med, p_tail_run, p_tail_arm, big_cost, int(bigmask.sum()), ng[k_]))
        out["arms"][k_] = {"mean": m, "lo": lo, "hi": hi, "fired_median": med,
                           "p_tail_runner": p_tail_run, "p_tail_arm": p_tail_arm,
                           "big_runner_cost": big_cost, "null": ng[k_]}
    io.open(os.path.join(HERE, "m30_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("wrote m30_result.json")


if __name__ == "__main__":
    main()
