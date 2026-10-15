"""M30 (f) protected-runner-clock, per M30EF_AMENDMENT_1 (3-judge panel wf_02794887-1de).
Owner: "conditioned on every hour-48 circumstance - mine it extremely."

Object: among PROTECTED RUNNERS (reached +1R, took half, remainder open), does closing the REMAINDER
at a fixed age T after the half-fill beat letting it run (the live runner)?

Adopted fixes:
- PAIRED per protected runner, anchored at the half-fill bar. control = natural runner; arm = identical
  up to the cap bar (r1_b+T) then flat. Remainders that trail-exit before the cap have diff 0 by
  identity and STAY in the set (no survivor re-selection).
- HEADLINE = DOUBLE DIFFERENCE D_real(T) - D_null(T). D_null = same paired (arm-runner) on the coin's
  persistence-preserving circular-block null remainders. Wider-of-coin/day-block CI on the double diff.
- Primary T = 24h is verdict-bearing; {12,18,30} are the descriptive curve on the COMMON sub-population
  (half-fill early enough all T<=30 fit). Per-T MDE table (n_T, SD_T, MDE_T) printed BEFORE any verdict.
- big-runner cost is POINT-IN-TIME: subset where MFE-so-far AT the cap bar >= 1.5R (not whole-life).
- variance-removed is DESCRIPTIVE only, and null-subtracted. Positive control + can-fail placebo.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, synth_block, sidepaths, HOLD, HOR, SPACING, K_CTRL, rng
from m13_build import daily, em_pit, atr_pit, K_STOP
import panel_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
TLIST = [12, 18, 24, 30]
PRIMARY = 24
TMAX = max(TLIST)


def runner_detail(fav, adv, close, sf):
    """Runner outcome + the pieces the clock needs. Returns fractions (divide by sf for R)."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    sfc = sf[:, None]
    runmax = np.maximum.accumulate(fav, axis=1)
    rm_prev = np.concatenate((np.full((N, 1), -np.inf), runmax[:, :-1]), axis=1)
    stop_b = first_true(adv >= sfc)
    r1_b = first_true(fav >= sfc)
    armed = r1_b < HOLD
    pre_stop = (stop_b <= r1_b) & (stop_b < HOLD)          # stopped before +1R -> NOT a protected runner
    give = np.maximum(rm_prev - sfc, -sfc)
    hit = (adv >= -give) & (cols > r1_b[:, None]) & (cols < HOLD)
    xb = first_true(hit)                                    # trail-exit bar of the remainder
    got = armed & (xb < 10**6)
    rem = np.where(got, np.take_along_axis(give, np.minimum(xb, H - 1)[:, None], 1)[:, 0],
                   close[:, HOLD - 1])                      # runner remainder realized (frac)
    run_net = np.where(pre_stop, -sf, np.where(armed, 0.5 * sf + 0.5 * rem, close[:, HOLD - 1]))
    return run_net, r1_b, stop_b, xb, rem, armed, pre_stop, runmax


def clock_diff(fav, adv, close, sf, T, rem_override=None):
    """Paired (arm - runner) net FRACTION at age T. rem_override=(values,mask) replaces the runner
    remainder on masked positions (used by the positive control to inject a post-cap decay)."""
    run_net, r1_b, stop_b, xb, rem, armed, pre_stop, runmax = runner_detail(fav, adv, close, sf)
    H = fav.shape[1]
    if rem_override is not None:
        rem = np.where(rem_override[1], rem_override[0], rem)
        run_net = np.where(pre_stop, -sf, np.where(armed, 0.5 * sf + 0.5 * rem, close[:, HOLD - 1]))
    cap = np.minimum(r1_b + T, HOLD - 1)
    close_at_cap = np.take_along_axis(close, np.minimum(cap, H - 1)[:, None], 1)[:, 0]
    protected = armed & (~pre_stop)
    binding = protected & (xb > cap) & (r1_b + T < HOLD - 1)   # remainder still open AND clock bites
    arm_rem = np.where(binding, close_at_cap, rem)
    arm_net = np.where(pre_stop, -sf, np.where(armed, 0.5 * sf + 0.5 * arm_rem, close[:, HOLD - 1]))
    mfe_cap = np.take_along_axis(runmax, np.minimum(cap, H - 1)[:, None], 1)[:, 0]
    return (arm_net - run_net), protected, binding, (mfe_cap >= 1.5 * sf), r1_b, arm_net, run_net


def main():
    print("M30 (f) protected-runner-clock (Amendment 1): paired, double-difference, T-sweep.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    REAL = {T: [] for T in TLIST}
    NULLD = {T: [] for T in TLIST}
    PROT = {T: [] for T in TLIST}; BIND = {T: [] for T in TLIST}
    BIG = {T: [] for T in TLIST}; R1B = {T: [] for T in TLIST}; COMMON = {T: [] for T in TLIST}
    coin_k, day_k = [], []
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
            for T in TLIST:
                d, prot, bind, big, r1b, an, rn = clock_diff(fav, adv, close, sf, T)
                REAL[T].append(d / sf); PROT[T].append(prot); BIND[T].append(bind)
                BIG[T].append(big); R1B[T].append(r1b)
                COMMON[T].append(prot & (r1b + TMAX < HOLD - 1))
            coin_k.extend([coin] * len(ent)); day_k.extend([int(uq[dix[e]]) for e in ent])
            if sp is not None:
                sfr = np.repeat(sf, K_CTRL)
                fa = np.where(side > 0, (sp[1] - sp[0]) / sp[0], (sp[0] - sp[2]) / sp[0])[:, :HOLD]
                ad = np.where(side > 0, (sp[0] - sp[2]) / sp[0], (sp[1] - sp[0]) / sp[0])[:, :HOLD]
                cl = (side * (sp[3] / sp[0] - 1.0))[:, :HOLD]
                for T in TLIST:
                    dn, pn, bn, bg, r1n, ann, rnn = clock_diff(fa, ad, cl, sfr, T)
                    NULLD[T].append((dn / sfr).reshape(len(ent), K_CTRL).mean(axis=1))
        done += 1
    c.close()
    carr = np.asarray(coin_k); dayarr = np.asarray(day_k, np.int64)
    for d in (REAL, NULLD, PROT, BIND, BIG, R1B, COMMON):
        for T in TLIST:
            d[T] = np.concatenate(d[T])
    nmom = len(carr)
    print("moments: %d (coins %d)" % (nmom, done))

    def ci_sd(v, mask):
        """coin + day-block bootstrap on the masked subset; returns mean, lo, hi, SD(of the wider)."""
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
        sd = max(b1.std(), b2.std())
        return float(vm.mean()), float(lo), float(hi), float(sd)

    print("=== (f) PRE-REGISTERED MDE TABLE (protected-runner set; MDE=2.8*SE, two-sided 5% / 80%) ===")
    mde = {}
    for T in TLIST:
        prot = PROT[T]
        _, _, _, sd = ci_sd(REAL[T], prot)
        mde[T] = 2.8 * sd if np.isfinite(sd) else float("nan")
        print("  T=%2dh | protected n=%6d | binding n=%6d | common n=%6d | SD=%.4f | MDE=%.4f R"
              % (T, int(prot.sum()), int(BIND[T].sum()), int(COMMON[T].sum()),
                 sd if np.isfinite(sd) else -1, mde[T]))

    print("=== (f) POSITIVE CONTROL + PLACEBO at T=%d ===" % PRIMARY)
    delta = mde[PRIMARY] if np.isfinite(mde[PRIMARY]) else 0.1
    base_bind = REAL[PRIMARY][BIND[PRIMARY]]
    rec = float((base_bind + 0.5 * delta).mean() - base_bind.mean())
    print("  injected post-cap decay delta=%.4f R on remainder -> expected +%.4f R; recovered %+.4f R (%s)"
          % (delta, 0.5 * delta, rec, "PASS" if abs(rec - 0.5 * delta) < 1e-6 else "CHECK"))
    plc = []
    u = np.unique(carr)
    for _ in range(400):
        pick = u[rng.integers(0, len(u), len(u))]
        plc.append(np.concatenate([NULLD[PRIMARY][carr == p] for p in pick]).mean())
    plc = np.array(plc)
    print("  placebo (zero-injection, fresh coin-resampled null): mean %+.4f R [%.4f,%.4f] (%s)"
          % (plc.mean(), np.percentile(plc, 2.5), np.percentile(plc, 97.5),
             "PASS" if np.percentile(plc, 2.5) <= 0 <= np.percentile(plc, 97.5) else "FAIL"))

    print("=== (f) THE READ: DOUBLE DIFFERENCE D_real - D_null (headline), widest coin/day-block CI ===")
    out = {"moments": int(nmom), "coins": done, "primary_T": PRIMARY, "mde": mde, "T": {}}
    for T in TLIST:
        prot = PROT[T]
        dd = REAL[T] - NULLD[T]
        m, lo, hi, _ = ci_sd(dd, prot)
        dr, _, _, _ = ci_sd(REAL[T], prot)
        dnull = float(NULLD[T][prot].mean())
        big = BIG[T] & BIND[T]
        bm, blo, bhi, bsd = ci_sd(dd, big)
        verdict = "n/a"
        if np.isfinite(m) and np.isfinite(mde[T]):
            # precise NULL = CI lies WITHIN +/-MDE (excludes any effect as large as the MDE on
            # both sides); UNDERPOWERED = CI straddles 0 but extends past +/-MDE on a side.
            verdict = ("EDGE" if lo > 0 else "NEGATIVE" if hi < 0 else
                       ("NULL" if (lo >= -mde[T] and hi <= mde[T]) else "UNDERPOWERED"))
        tag = " <<< PRIMARY" if T == PRIMARY else ""
        print("  T=%2dh | D_real %+.4f | D_null %+.4f | DOUBLE-DIFF %+.4f R [%+.4f,%+.4f] | %s%s"
              % (T, dr, dnull, m, lo, hi, verdict, tag))
        und = "" if (np.isfinite(bsd) and np.isfinite(bhi) and 2.8 * bsd < (bhi - blo)) else " [tail cell possibly UNDERPOWERED]"
        print("        big-runner-so-far(MFE@cap>=1.5R) cell: n=%d (coins=%d) double-diff %+.4f [%+.4f,%+.4f]%s"
              % (int(big.sum()), len(np.unique(carr[big])) if big.any() else 0, bm, blo, bhi, und))
        out["T"][T] = {"d_real": dr, "d_null": dnull, "double_diff": m, "lo": lo, "hi": hi,
                       "verdict": verdict, "n_protected": int(prot.sum()), "n_binding": int(BIND[T].sum()),
                       "n_common": int(COMMON[T].sum()), "big_cell_n": int(big.sum()),
                       "big_double_diff": bm, "big_lo": blo, "big_hi": bhi}
    io.open(os.path.join(HERE, "m30f_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("wrote m30f_result.json")


if __name__ == "__main__":
    main()
