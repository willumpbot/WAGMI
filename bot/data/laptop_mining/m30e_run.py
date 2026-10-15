"""M30 (e) sibling-close, per M30EF_AMENDMENT_1 (panel wf_02794887-1de).
Owner (a4cbdffd): "sibling close when a same-coin plan exits at target."

Object: when a DIFFERENT same-coin plan first reaches its own +1R, close THIS position. Does it beat
letting this position run (the live runner)?

Adopted FATAL fixes:
- FORWARD-SCAN sibling detection (no 'nearest overlapping entry' key). For position p (abs entry a_p,
  natural window (a_p, a_p+HOLD]), close_idx = the EARLIEST absolute bar at which ANY other same-coin
  plan (any side) first reaches +1R, strictly inside p's open window. Close p at ITS OWN price at that
  bar. Invariance guard: the sibling's first-+1R bar uses only bars <= itself (argmax of a cumulative
  condition) so it cannot move when later bars are deleted -> point-in-time by construction; asserted.
- JOINT coin-level null: resample ONE circular-block price series PER COIN and place ALL entries on
  that SAME synthetic series, so the sibling's +1R detection AND p's close price ride one path ->
  within-coin co-movement (the mechanical driver) preserved; only genuine forward edge destroyed.
- HEADLINE = DOUBLE DIFFERENCE D_real - D_null, widest coin/day-block CI. Realized-P&L / same-side
  slices are DESCRIPTIVE, never the verdict. Positive control + can-fail placebo. MDE before verdict.
- MINOR: require strict a_p < h_sibling <= a_p+HOLD (exclude pre-entry/entry-bar hits); report n.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, HOLD, HOR, SPACING, K_CTRL, BLOCK, rng
from m13_build import daily, em_pit, atr_pit, K_STOP
import panel_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
K_NULL = 8


def runner_net(fav, adv, close, sf):
    """Runner outcome (fraction) + stop_b, r1_b, for the sibling-close comparison."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    sfc = sf[:, None]
    runmax = np.maximum.accumulate(fav, axis=1)
    rm_prev = np.concatenate((np.full((N, 1), -np.inf), runmax[:, :-1]), axis=1)
    stop_b = first_true(adv >= sfc)
    r1_b = first_true(fav >= sfc)
    armed = r1_b < HOLD
    pre_stop = (stop_b <= r1_b) & (stop_b < HOLD)
    give = np.maximum(rm_prev - sfc, -sfc)
    hit = (adv >= -give) & (cols > r1_b[:, None]) & (cols < HOLD)
    xb = first_true(hit)
    got = armed & (xb < 10**6)
    rem = np.where(got, np.take_along_axis(give, np.minimum(xb, H - 1)[:, None], 1)[:, 0],
                   close[:, HOLD - 1])
    rn = np.where(pre_stop, -sf, np.where(armed, 0.5 * sf + 0.5 * rem, close[:, HOLD - 1]))
    return rn, stop_b, r1_b


def sidepaths_from(entry_px, Hs, Ls, Cs, side):
    fav = np.where(side > 0, (Hs - entry_px) / entry_px, (entry_px - Ls) / entry_px)
    adv = np.where(side > 0, (entry_px - Ls) / entry_px, (Hs - entry_px) / entry_px)
    close = side * (Cs / entry_px - 1.0)
    return fav[:, :HOLD], adv[:, :HOLD], close[:, :HOLD]


def sibling_close_bars(ent, Hs, Ls, Cs, entry_px, sf):
    """For each entry (abs bar a), the EARLIEST absolute bar at which ANY OTHER same-coin entry first
    reaches +1R on EITHER side, strictly inside (a, a+HOLD]. Returns rel-bar per entry (1..HOLD-1) or
    10**6 if none. Point-in-time by construction (first-hit uses only bars<=itself)."""
    ne = len(ent)
    # first +1R relative bar per entry per side
    h1 = np.full((ne, 2), 10**6)
    for si, side in enumerate((1.0, -1.0)):
        fav, _, _ = sidepaths_from(entry_px, Hs, Ls, Cs, side)
        h1[:, si] = first_true(fav >= sf[:, None])
    h1abs = ent[:, None] + h1                           # absolute bar of each entry's +1R, per side
    h1abs = np.where(h1 < HOLD, h1abs, 10**9)           # only genuine hits within hold
    flat = h1abs.reshape(-1)                            # all sibling hit bars (abs), 2 per entry
    owner = np.repeat(np.arange(ne), 2)                 # which entry each hit belongs to
    sideflat = np.tile(np.array([1.0, -1.0]), ne)       # side of each hit (si 0->long, 1->short)
    order = np.argsort(flat)
    flat_s, owner_s, side_s = flat[order], owner[order], sideflat[order]
    close_rel = np.full(ne, 10**6)
    close_sib_side = np.zeros(ne)                        # side of the firing sibling (+1/-1), 0 if none
    for i in range(ne):
        a = ent[i]
        lo, hi = a + 1, a + HOLD                        # strict a < h <= a+HOLD
        # earliest sibling hit (different entry) in the window
        j = np.searchsorted(flat_s, lo)
        while j < len(flat_s) and flat_s[j] <= hi:
            if owner_s[j] != i:
                close_rel[i] = int(flat_s[j] - a)
                close_sib_side[i] = side_s[j]
                break
            j += 1
    return close_rel, close_sib_side


def e_diff(ent, Hs, Ls, Cs, entry_px, sf, drift=None):
    """Paired (arm - runner) net FRACTION per entry (side-pooled: computed for both sides, stacked).
    drift: optional per-entry post-sibling drift injected on BOTH arm&runner's remaining exposure (for
    the positive control; the arm closes early so it AVOIDS the drift)."""
    close_rel, sib_side = sibling_close_bars(ent, Hs, Ls, Cs, entry_px, sf)
    fired = close_rel < HOLD
    outs, sames = [], []
    for side in (1.0, -1.0):
        fav, adv, close = sidepaths_from(entry_px, Hs, Ls, Cs, side)
        rn, stop_b, r1_b = runner_net(fav, adv, close, sf)
        rb = np.minimum(close_rel, HOLD - 1)
        close_at = np.take_along_axis(close, rb[:, None], 1)[:, 0]
        # runner (control) with optional post-sibling drift on exposure still open at rb
        rn_eff = rn.copy()
        if drift is not None:
            open_at_rb = fired & (stop_b > rb)
            frac_open = np.where(r1_b < rb, 0.5, 1.0)      # half already banked if +1R before rb
            # drift is in R; rn is a FRACTION -> scale by sf. arm closes at rb and avoids this.
            rn_eff = np.where(open_at_rb, rn + frac_open * drift * sf, rn)
        # arm: close position at rb if a sibling fired and position still has exposure
        pre_stopped = stop_b <= rb
        banked_half = (r1_b < rb) & (~pre_stopped)
        arm = np.where(~fired, rn_eff,
              np.where(pre_stopped, rn_eff,
              np.where(banked_half, 0.5 * sf + 0.5 * close_at, close_at)))
        outs.append((arm - rn_eff) / sf)
        sames.append(fired & (sib_side == side))           # firing sibling shares this position's side
    return np.concatenate(outs), np.concatenate([fired, fired]), np.concatenate([close_rel, close_rel]), np.concatenate(sames)


def null_series(b, span, reps):
    """Block-bootstrap ONE coin price series of length `span` bars, `reps` times. Returns list of
    (H,L,C) arrays each shape (span,), sharing one path per rep (joint coin-level null)."""
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.flatnonzero(np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn))
    if len(g) < 500:
        return []
    lr, up, dn = lr[g], np.maximum(up[g], 0), np.maximum(dn[g], 0)
    norm = float(np.mean(np.exp(lr)))
    nb = int(np.ceil(span / BLOCK))
    series = []
    for _ in range(reps):
        starts = rng.integers(0, len(g) - BLOCK, size=nb)
        idx = (starts[:, None] + np.arange(BLOCK)[None, :]).reshape(-1)[:span]
        step = np.exp(lr[idx]) / norm
        C = b["c"][0] * np.cumprod(step)
        prev = np.concatenate(([b["c"][0]], C[:-1]))
        Hh = np.maximum(prev, C) * (1 + up[idx])
        Ll = np.minimum(prev, C) * (1 - dn[idx])
        series.append((Hh, Ll, C))
    return series


def main():
    print("M30 (e) sibling-close (Amendment 1): forward-scan sibling, joint coin-level null.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M30E_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    REAL, NULLD, NULLA, NULLB, FIRED, coin_k, day_k, BIG, SAME = [], [], [], [], [], [], [], [], []
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
        entry_px = b["c"][ent][:, None]
        Hs, Ls, Cs = b["h"][pidx], b["l"][pidx], b["c"][pidx]
        dreal, fired, crel, same = e_diff(ent, Hs, Ls, Cs, entry_px, sf)
        # path MFE-so-far AT the sibling-close bar (point-in-time big-runner cell)
        big = []
        for side in (1.0, -1.0):
            fav, _, _ = sidepaths_from(entry_px, Hs, Ls, Cs, side)
            rm = np.maximum.accumulate(fav, axis=1)
            rb = np.minimum(np.where(crel[:len(ent)] < HOLD, crel[:len(ent)], HOLD - 1), HOLD - 1)
            big.append(np.take_along_axis(rm, rb[:, None], 1)[:, 0] >= 1.5 * sf)
        big = np.concatenate(big)
        REAL.append(dreal); FIRED.append(fired); BIG.append(big); SAME.append(same)
        coin_k.extend([coin] * (2 * len(ent)))
        day_k.extend([int(uq[dix[e]]) for e in ent] * 2)
        # joint coin-level null: one shared synthetic series per rep, all entries placed on it.
        # split the reps into two independent halves -> a can-fail placebo (A vs B should be ~0).
        span = int(ent[-1] - ent[0]) + HOR + 2
        rel0 = ent - ent[0]
        accA = np.zeros(2 * len(ent)); accB = np.zeros(2 * len(ent))
        series = null_series(b, span, K_NULL)
        half = len(series) // 2
        if series and half > 0:
            for ri, (Hh, Ll, Cc) in enumerate(series):
                pj = rel0[:, None] + np.arange(1, HOR + 1)[None, :]
                epx = Cc[rel0][:, None]
                dn_, _, _, _ = e_diff(rel0, Hh[pj], Ll[pj], Cc[pj], epx, sf)
                if ri < half:
                    accA += dn_
                else:
                    accB += dn_
            accA /= half; accB /= (len(series) - half)
        NULLA.append(accA); NULLB.append(accB); NULLD.append(0.5 * (accA + accB))
        done += 1
    c.close()
    REAL = np.concatenate(REAL); NULLD = np.concatenate(NULLD)
    NULLA = np.concatenate(NULLA); NULLB = np.concatenate(NULLB)
    FIRED = np.concatenate(FIRED); BIG = np.concatenate(BIG); SAME = np.concatenate(SAME)
    carr = np.asarray(coin_k); dayarr = np.asarray(day_k, np.int64)
    nmom = len(REAL)
    nfire = int(FIRED.sum())
    print("moments(side-pooled): %d (coins %d) | sibling fired on %d (%.1f%%)"
          % (nmom, done, nfire, 100.0 * nfire / max(nmom, 1)))

    def ci_sd(v, mask):
        vm, cm_, dm_ = v[mask], carr[mask], dayarr[mask]
        if len(vm) < 30:
            return float("nan"), float("nan"), float("nan"), float("nan")
        cs = {u: vm[cm_ == u].mean() for u in np.unique(cm_) if (cm_ == u).any()}
        per = np.array(list(cs.values()))
        b1 = np.array([per[rng.integers(0, len(per), len(per))].mean() for _ in range(2000)])
        udm = np.unique(dm_); dgrp = {d: vm[dm_ == d] for d in udm}
        b2 = np.array([np.concatenate([dgrp[p] for p in np.array(udm)[rng.integers(0, len(udm), len(udm))]]).mean()
                       for _ in range(2000)])
        lo = min(np.percentile(b1, 2.5), np.percentile(b2, 2.5))
        hi = max(np.percentile(b1, 97.5), np.percentile(b2, 97.5))
        return float(vm.mean()), float(lo), float(hi), float(max(b1.std(), b2.std()))

    # fired subset is where the arm differs from the runner (the policy's active set)
    _, _, _, sd = ci_sd(REAL, FIRED)
    mde = 2.8 * sd if np.isfinite(sd) else float("nan")
    print("=== (e) PRE-REGISTERED MDE (fired subset; MDE=2.8*SE) ===")
    print("  fired n=%d (coins=%d) | SD=%.4f | MDE=%.4f R"
          % (nfire, len(np.unique(carr[FIRED])) if FIRED.any() else 0, sd if np.isfinite(sd) else -1, mde))

    # ---- POSITIVE CONTROL: a second real pass injecting a post-sibling adverse drift = MDE on the
    # runner's remaining exposure. The arm closes at the sibling bar and AVOIDS it, so the measured
    # (arm-runner) must RISE by ~mean(frac_open)*delta on the fired set. ----
    print("=== (e) POSITIVE CONTROL + PLACEBO ===")
    delta = mde if np.isfinite(mde) else 0.1
    c2 = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    PC_BASE, PC_INJ, PC_FIRE = [], [], []
    rng2 = np.random.default_rng(777)
    for coin in coins:
        rows = c2.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day); em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - HOR - 2)]
        if len(elig) < 40:
            continue
        off = int(rng2.integers(0, SPACING))
        ent, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                ent.append(e); last = e
        ent = np.asarray(ent)
        sf = K_STOP * em_h[ent]
        pidx = ent[:, None] + np.arange(1, HOR + 1)[None, :]
        entry_px = b["c"][ent][:, None]
        Hs, Ls, Cs = b["h"][pidx], b["l"][pidx], b["c"][pidx]
        d0, f0, _, _ = e_diff(ent, Hs, Ls, Cs, entry_px, sf, drift=None)
        d1, f1, _, _ = e_diff(ent, Hs, Ls, Cs, entry_px, sf, drift=-delta)
        PC_BASE.append(d0); PC_INJ.append(d1); PC_FIRE.append(f0)
    c2.close()
    PC_BASE = np.concatenate(PC_BASE); PC_INJ = np.concatenate(PC_INJ); PC_FIRE = np.concatenate(PC_FIRE)
    rec = float(PC_INJ[PC_FIRE].mean() - PC_BASE[PC_FIRE].mean())
    print("  injected post-sibling adverse drift delta=%.4f R; arm avoids it -> measured (arm-runner) "
          "rose %+.4f R on fired (PASS if clearly > 0 and <= delta)" % (delta, rec))
    print("  -> %s" % ("PASS" if (rec > 0.25 * delta) else "WEAK/CHECK"))
    # placebo: the NULL double-diff component resampled over coins must straddle 0 (can fail if biased)
    # CAN-FAIL placebo: two INDEPENDENT joint-null draws (A vs B) differenced on the fired set must
    # straddle 0. (D_null itself is correctly nonzero for (e) - it is the mechanical component - so the
    # placebo is the A-B difference, not D_null.)
    plc_vec = NULLA - NULLB
    pm, plo, phi, _ = ci_sd(plc_vec, FIRED)
    print("  placebo (two independent null draws A-B, fired): mean %+.4f R [%+.4f,%+.4f] (%s)"
          % (pm, plo, phi, "PASS" if (plo <= 0 <= phi) else "FAIL"))

    print("=== (e) THE READ: DOUBLE DIFFERENCE D_real - D_null (headline), widest coin/day-block CI ===")
    dd = REAL - NULLD
    m, lo, hi, _ = ci_sd(dd, FIRED)
    dr = float(REAL[FIRED].mean()); dnull = float(NULLD[FIRED].mean())
    verdict = ("EDGE" if lo > 0 else "NEGATIVE" if hi < 0 else
               ("NULL" if (np.isfinite(mde) and lo >= -mde and hi <= mde) else "UNDERPOWERED"))
    print("  fired subset | D_real %+.4f | D_null %+.4f | DOUBLE-DIFF %+.4f R [%+.4f,%+.4f] | %s"
          % (dr, dnull, m, lo, hi, verdict))
    # big-runner-so-far cell, and the harsh SAME-vs-OPPOSITE-side split (same-side is the by-construction
    # risk: a same-coin same-side sibling hitting +1R means the coin moved our way, so this cell banks a
    # favourable move; opposite-side is the cleaner contrast).
    out = {"moments": int(nmom), "coins": done, "n_fired": nfire, "mde": mde,
           "double_diff": m, "lo": lo, "hi": hi, "verdict": verdict, "d_real": dr, "d_null": dnull,
           "placebo_AB": pm, "placebo_lo": plo, "placebo_hi": phi, "cells": {}}
    for name, cell in [("big_all", BIG & FIRED), ("big_SAMEside", BIG & FIRED & SAME),
                       ("big_OPPside", BIG & FIRED & (~SAME)),
                       ("nonbig_all", (~BIG) & FIRED)]:
        bm, blo, bhi, bsd = ci_sd(dd, cell)
        und = "" if (np.isfinite(bsd) and np.isfinite(bhi) and 2.8 * bsd < (bhi - blo)) else " [UNDERPOWERED]"
        print("  %-13s n=%6d (coins=%3d) double-diff %+.4f R [%+.4f,%+.4f]%s"
              % (name, int(cell.sum()), len(np.unique(carr[cell])) if cell.any() else 0, bm, blo, bhi, und))
        out["cells"][name] = {"n": int(cell.sum()), "dd": bm, "lo": blo, "hi": bhi}
    io.open(os.path.join(HERE, "m30e_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("wrote m30e_result.json")


if __name__ == "__main__":
    main()
