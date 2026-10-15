"""Project X part 3 - the fade-vs-run atlas (THE PRIZE). For every m28 moment that reaches +0.5R, is
what's knowable AT the +0.5R bar (strictly pre-peak, no look-ahead) predictive of whether it FADES
(gives it all back) or RUNS (reaches +1.5R)? If yes -> a conditional signal for WHICH trades to ladder
harder (not an exit dial). EXPLORATORY. By-construction guard: the FADE/RUN label is defined on the
post-+0.5R path; EVERY circumstance uses only bars <= the +0.5R bar.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, sidepaths, HOLD, HOR, SPACING, rng
from m13_build import daily, em_pit, atr_pit, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")


def main():
    print("Project X part 3: fade-vs-run atlas. Circumstances strictly at/<= the +0.5R bar.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M32C_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    # BTC reference path (for co-move), aligned by timestamp
    btc = np.asarray(c.execute("SELECT t,c FROM candles_1h WHERE coin='BTC' ORDER BY t").fetchall(), float)
    btc_t, btc_c = btc[:, 0], btc[:, 1]

    LAB, VEL, TOD, VOLT, TRW, BTCW, RNG, VSRG, BTCUP = ([] for _ in range(9))
    coin_k, day_k = [], []
    done = 0
    for coin in coins:
        rows = c.execute("SELECT t,o,h,l,c,v FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5]}
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
        Hs, Ls, Cs, Vs, Ts = b["h"][pidx], b["l"][pidx], b["c"][pidx], b["v"][pidx], b["t"][pidx]
        # trailing-20d close and volume baseline (point-in-time, at entry)
        c20 = b["c"][np.maximum(ent - 480, 0)]
        vbase = np.array([b["v"][max(e - 72, 0):e].mean() if e > 72 else np.nan for e in ent])
        for side in (1.0, -1.0):
            fav, adv, close = sidepaths(entry, Hs, Ls, Cs, side)
            sfc = sf[:, None]
            b05 = first_true(fav >= 0.5 * sfc)
            ok = b05 < HOLD
            if ok.sum() < 10:
                continue
            cols = np.arange(HOLD)[None, :]
            markR = close / sfc
            b15 = first_true(fav >= 1.5 * sfc)
            fade_cond = (markR <= 0) & (cols > b05[:, None])
            fade_bar = first_true(fade_cond)
            run = (b15 < fade_bar) & (b15 < HOLD)                 # reached +1.5R before fading
            fade = (fade_bar < HOLD) & (fade_bar <= b15)          # faded to 0 before +1.5R
            lab = np.where(run, 1, np.where(fade, 0, -1))         # 1=RUN 0=FADE -1=OTHER
            # circumstances AT b05 (<= b05 only)
            bi = np.minimum(b05, HOLD - 1)
            vel = b05.astype(float)
            t05 = np.take_along_axis(Ts, bi[:, None], 1)[:, 0]
            tod = ((t05 // 3600000) % 24).astype(float)
            volt = atr_h[ent]
            trend_sign = np.sign(entry[:, 0] - c20)
            trw = (trend_sign == side).astype(float)              # position WITH the 20d trend
            bidx = np.searchsorted(btc_t, t05)
            bidx = np.clip(bidx, 25, len(btc_c) - 1)
            btc_ret = btc_c[bidx] / btc_c[bidx - 24] - 1.0
            btcw = (np.sign(btc_ret) == side).astype(float)       # BTC moving WITH the position
            rng_bar = (Hs - Ls) / np.maximum(Cs, 1e-12)
            rmax = np.array([rng_bar[i, :max(int(bi[i]) + 1, 1)].max() for i in range(len(ent))])
            vatb = np.take_along_axis(Vs, bi[:, None], 1)[:, 0]
            vsrg = vatb / np.maximum(vbase, 1e-9)
            m = ok & (lab >= 0)                                   # scored moments (RUN or FADE)
            for arr, src in ((LAB, lab), (VEL, vel), (TOD, tod), (VOLT, volt), (TRW, trw),
                             (BTCW, btcw), (RNG, rmax), (VSRG, vsrg), (BTCUP, (btc_ret > 0).astype(float))):
                arr.append(src[m])
            coin_k.extend([coin] * int(m.sum()))
            day_k.extend([int(uq[dix[e]]) for e, mm in zip(ent, m) if mm])
        done += 1
    c.close()
    LAB = np.concatenate(LAB); VEL = np.concatenate(VEL); TOD = np.concatenate(TOD)
    VOLT = np.concatenate(VOLT); TRW = np.concatenate(TRW); BTCW = np.concatenate(BTCW)
    RNG = np.concatenate(RNG); VSRG = np.concatenate(VSRG); BTCUP = np.concatenate(BTCUP)
    carr = np.asarray(coin_k); dayk = np.asarray(day_k, np.int64)
    isfade = (LAB == 0).astype(float)
    base = float(isfade.mean())
    print("scored (+0.5R reachers that RAN or FADED): %d (coins %d) | base P(FADE) = %.3f (RUN %.3f)"
          % (len(LAB), done, base, 1 - base))

    def ci(mask):
        v = isfade[mask]; cc = carr[mask]
        if len(v) < 30:
            return float("nan"), float("nan"), float("nan"), int(len(v))
        u = np.unique(cc); grp = {x: v[cc == x] for x in u}
        bo = np.array([np.concatenate([grp[p] for p in u[rng.integers(0, len(u), len(u))]]).mean() for _ in range(2000)])
        return float(v.mean()), float(np.percentile(bo, 2.5)), float(np.percentile(bo, 97.5)), int(len(v))

    def report(name, arr, buckets):
        print("\n[%s]  P(FADE) by bucket (base %.3f); CI clustered by coin:" % (name, base))
        out = []
        for blab, mask in buckets(arr):
            m, lo, hi, nn = ci(mask)
            sig = "" if not np.isfinite(lo) else (" <== higher FADE" if lo > base else " <== lower FADE (runs)" if hi < base else "")
            print("   %-16s n=%6d  P(FADE)=%.3f [%.3f,%.3f]%s" % (blab, nn, m, lo, hi, sig))
            out.append({"bucket": blab, "n": nn, "p_fade": m, "lo": lo, "hi": hi})
        return out

    def quart(arr):
        qs = np.nanpercentile(arr, [25, 50, 75])
        return [("Q1 (low)", arr <= qs[0]), ("Q2", (arr > qs[0]) & (arr <= qs[1])),
                ("Q3", (arr > qs[1]) & (arr <= qs[2])), ("Q4 (high)", arr > qs[2])]
    def binary(arr, lab0, lab1):
        return [(lab0, arr < 0.5), (lab1, arr >= 0.5)]
    def todb(arr):
        return [("Asia 0-7h", (arr >= 0) & (arr < 8)), ("EU 8-15h", (arr >= 8) & (arr < 16)), ("US 16-23h", arr >= 16)]

    res = {"base_p_fade": base, "n": int(len(LAB)), "coins": done, "circ": {}}
    res["circ"]["velocity_bars_to_0.5R"] = report("velocity (bars to +0.5R)", VEL, quart)
    res["circ"]["vol_tier_atr"] = report("vol tier (ATR at entry)", VOLT, quart)
    res["circ"]["range_into_peak"] = report("max bar-range into +0.5R", RNG, quart)
    res["circ"]["vol_surge"] = report("volume surge at +0.5R bar", VSRG, quart)
    res["circ"]["trend_with"] = report("position vs 20d trend", TRW, lambda a: binary(a, "AGAINST trend", "WITH trend"))
    res["circ"]["btc_with"] = report("BTC co-move (24h)", BTCW, lambda a: binary(a, "BTC AGAINST", "BTC WITH"))
    res["circ"]["time_of_day"] = report("time-of-day (UTC) of +0.5R", TOD, todb)
    # ---- ADVERSARIAL CONTROLS: kill the confounds before any tell is called real ----
    print("\n==================  CONTROLS (confound checks)  ==================")
    # 1. VELOCITY vs REMAINING-WINDOW: a slow +0.5R leaves fewer bars to reach +1.5R -> mechanically
    #    biases toward not-RUN. Re-test velocity ONLY where b05<=12 (>=36 bars remain for every moment).
    capped = VEL <= 12
    print("\n[CONTROL 1] velocity WITHIN a fixed window (b05<=12h, >=36 bars remain for all); base here %.3f:"
          % (isfade[capped].mean() if capped.sum() else float("nan")))
    bbase = float(isfade[capped].mean()) if capped.sum() else float("nan")
    qs = np.nanpercentile(VEL[capped], [50]) if capped.sum() else [6]
    for blab, mk in [("fast (<=median)", capped & (VEL <= qs[0])), ("slow (>median, still<=12)", capped & (VEL > qs[0]))]:
        m, lo, hi, nn = ci(mk)
        print("   %-22s n=%6d P(FADE)=%.3f [%.3f,%.3f] %s" % (blab, nn, m, lo, hi,
              "(still separates)" if (np.isfinite(hi) and (hi < bbase or lo > bbase)) else "-> velocity tell DISSOLVES once window is held fixed" if np.isfinite(hi) else ""))
    # 2. TIME-OF-DAY vs REGIME: does US-fades hold within BOTH btc-up and btc-down moments?
    print("\n[CONTROL 2] US-session fade within BTC-up vs BTC-down (is it regime, not clock?):")
    for reg, rmask in [("BTC-up", BTCUP > 0.5), ("BTC-down", BTCUP <= 0.5)]:
        us = rmask & (TOD >= 16); asia = rmask & (TOD < 8)
        mu, lou, hiu, nu = ci(us); ma, loa, hia, na = ci(asia)
        print("   %-9s: US n=%5d P(FADE)=%.3f [%.3f,%.3f] | Asia n=%5d P(FADE)=%.3f [%.3f,%.3f]%s"
              % (reg, nu, mu, lou, hiu, na, ma, loa, hia,
                 "  US>Asia holds" if (np.isfinite(lou) and np.isfinite(hia) and lou > hia) else "  (gap not clean here)"))
    # 3. MOVE-QUALITY collinearity: does volume-surge still separate WITHIN each vol-tier half?
    print("\n[CONTROL 3] volume-surge (low Q1 vs high Q4) WITHIN low-ATR and high-ATR halves:")
    vmed = np.nanmedian(VOLT); vq = np.nanpercentile(VSRG, [25, 75])
    for tlab, tmask in [("low-ATR", VOLT <= vmed), ("high-ATR", VOLT > vmed)]:
        lo_s = tmask & (VSRG <= vq[0]); hi_s = tmask & (VSRG >= vq[1])
        ml, ll, hl_, nl = ci(lo_s); mh, lh, hh, nh = ci(hi_s)
        print("   %-9s: low-surge n=%5d P(FADE)=%.3f [%.3f,%.3f] | high-surge n=%5d P(FADE)=%.3f [%.3f,%.3f]%s"
              % (tlab, nl, ml, ll, hl_, nh, mh, lh, hh,
                 "  surge tell SURVIVES" if (np.isfinite(hh) and np.isfinite(ll) and hh < ll) else "  (not clean within tier)"))
    res["controls"] = "see log: velocity capped-window, ToD-by-regime, surge-within-ATR-tier"
    io.open(os.path.join(HERE, "m32c_result.json"), "w", encoding="utf-8").write(json.dumps(res, indent=1, default=float))
    print("\nA bucket whose CI is clear of the base rate is a PRE-PEAK tell of fade vs run -> candidate")
    print("conditional signal (ladder harder when fade-prone). Exploratory; survivors -> sealed study.")
    print("wrote m32c_result.json")


if __name__ == "__main__":
    main()
