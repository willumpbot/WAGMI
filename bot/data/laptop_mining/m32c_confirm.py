"""M32C fade-signal CONFIRM prep (per the prereg panel wf_fa2fe1d3). Compute the CLEAN (b05-EXCLUDED)
separations MYSELF on the DISCOVERY population to (1) resolve the judges' disagreement (surge-only clean
~0.071 vs ~0.043), (2) record the frozen thresholds S*/Vel*, (3) decide which classifier (surge-only vs
composite) clears the 0.05 substantive floor on the WIDER-CI LOWER BOUND with eqw-by-coin + sign>0.65,
(4) read the CORROBORATIVE confirmation subpopulation (descriptive, barred from go/no-go - the atlas saw
it too). Nothing is a live gate. b05-excluded surge: vs = V[b05-1]/mean(V[entry-72..entry-1]); drop b05==0.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, sidepaths, HOLD, HOR, SPACING, rng
from m13_build import daily, em_pit, atr_pit, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR", "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
MED_DAYKEY = 20693    # M28_SPLIT_SEAL recorded median daykey (2026-08-28); daykey = t_ms//86400000


def main():
    print("M32C confirm-prep: clean (b05-excl) separations on the discovery population.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M32C_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    LAB, VS, VEL, DISC, COIN, DAY = [], [], [], [], [], []
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
        Hs, Ls, Cs, Vs = b["h"][pidx], b["l"][pidx], b["c"][pidx], b["v"][pidx]
        vbase = np.array([b["v"][max(e - 72, 0):e].mean() if e > 72 else np.nan for e in ent])
        is_o17 = coin in ORIG17
        for side in (1.0, -1.0):
            fav, adv, close = sidepaths(entry, Hs, Ls, Cs, side)
            sfc = sf[:, None]
            b05 = first_true(fav >= 0.5 * sfc)
            cols = np.arange(HOLD)[None, :]
            markR = close / sfc
            b15 = first_true(fav >= 1.5 * sfc)
            fade_bar = first_true((markR <= 0) & (cols > b05[:, None]))
            run = (b15 < fade_bar) & (b15 < HOLD)
            fade = (fade_bar < HOLD) & (fade_bar <= b15)
            lab = np.where(run, 1, np.where(fade, 0, -1))
            # clean surge: volume at the bar BEFORE the +0.5R cross / trailing baseline (excludes b05)
            b05m1 = b05 - 1
            okm = (b05 < HOLD) & (lab >= 0) & (b05 >= 1) & np.isfinite(vbase)
            vprev = np.take_along_axis(Vs, np.clip(b05m1, 0, HOLD - 1)[:, None], 1)[:, 0]
            vs = vprev / np.maximum(vbase, 1e-9)
            tms = np.take_along_axis(b["t"][pidx], np.clip(b05, 0, HOR - 1)[:, None], 1)[:, 0]
            dk = (tms // 86400000).astype(np.int64)
            disc = np.full(len(ent), is_o17) | (dk < MED_DAYKEY)
            for arr, src in ((LAB, lab), (VS, vs), (VEL, b05.astype(float)), (DISC, disc.astype(float))):
                arr.append(src[okm])
            COIN.extend([coin] * int(okm.sum()))
            DAY.extend(list(dk[okm]))
    c.close()
    LAB = np.concatenate(LAB); VS = np.concatenate(VS); VEL = np.concatenate(VEL); DISC = np.concatenate(DISC)
    COIN = np.asarray(COIN); DAY = np.asarray(DAY, np.int64)
    isfade = (LAB == 0).astype(float)
    dmask = DISC > 0.5
    print("total scored %d | discovery %d | confirmation(corrob) %d" % (len(LAB), dmask.sum(), (~dmask).sum()))

    def sep_ci(fp_mask, pool_mask):
        """P(FADE|FADE_PRONE) - P(FADE|RUN_LIKELY) on pool_mask; wider of coin/day-block CI + eqw + sign-frac."""
        pm = pool_mask
        fp = fp_mask & pm; rl = (~fp_mask) & pm
        if fp.sum() < 50 or rl.sum() < 50:
            return None
        point = isfade[fp].mean() - isfade[rl].mean()
        # cluster bootstrap on the per-unit difference of means
        def boot(groups):
            u = np.unique(groups[pm])
            out = []
            gmap_fp = {x: isfade[fp & (groups == x)] for x in u}
            gmap_rl = {x: isfade[rl & (groups == x)] for x in u}
            for _ in range(2000):
                pick = u[rng.integers(0, len(u), len(u))]
                f = np.concatenate([gmap_fp[p] for p in pick if len(gmap_fp[p])])
                r = np.concatenate([gmap_rl[p] for p in pick if len(gmap_rl[p])])
                out.append(f.mean() - r.mean())
            return np.array(out)
        bc, bd = boot(COIN), boot(DAY)
        lo = min(np.percentile(bc, 2.5), np.percentile(bd, 2.5))
        hi = max(np.percentile(bc, 97.5), np.percentile(bd, 97.5))
        # eqw-by-coin + sign fraction
        us = np.unique(COIN[pm]); per = []
        for u in us:
            fm = fp & (COIN == u); rm = rl & (COIN == u)
            if fm.sum() >= 5 and rm.sum() >= 5:
                per.append(isfade[fm].mean() - isfade[rm].mean())
        per = np.array(per)
        return dict(point=float(point), lo=float(lo), hi=float(hi), eqw=float(per.mean()),
                    sign=float((per > 0).mean()), n_fp=int(fp.sum()), n_rl=int(rl.sum()), n_coins=int(len(per)))

    Sstar = float(np.median(VS[dmask])); Vstar = float(np.median(VEL[dmask]))
    print("frozen thresholds on DISCOVERY: S* (clean surge median) = %.4f | Vel* (median bars) = %.1f" % (Sstar, Vstar))
    surge_fp = VS <= Sstar
    comp_fp = (VS <= Sstar) & (VEL >= Vstar)
    print("\n=== DISCOVERY separations (clean, b05-excluded; wider coin/day CI; eqw; sign-frac) ===")
    out = {"Sstar": Sstar, "Vstar": Vstar, "discovery": {}, "corroborative": {}}
    for nm, fpm in (("surge_only", surge_fp), ("composite_AND", comp_fp)):
        r = sep_ci(fpm, dmask)
        out["discovery"][nm] = r
        if r:
            floor = " clears 0.05 floor on LOWER BOUND" if r["lo"] > 0.05 else " BELOW 0.05 floor (lower bound)"
            eqwok = "eqw>%0.05 OK" if r["eqw"] > 0.05 else "eqw<0.05"
            print("  %-13s sep %+.4f [%+.4f,%+.4f] | eqw %+.4f sign %.2f | n_fp=%d n_rl=%d coins=%d |%s %s"
                  % (nm, r["point"], r["lo"], r["hi"], r["eqw"], r["sign"], r["n_fp"], r["n_rl"], r["n_coins"], floor, eqwok))
    print("\n=== CORROBORATIVE confirmation subpop (DESCRIPTIVE - atlas saw it, barred from go/no-go) ===")
    for nm, fpm in (("surge_only", surge_fp), ("composite_AND", comp_fp)):
        r = sep_ci(fpm, ~dmask)
        out["corroborative"][nm] = r
        if r:
            print("  %-13s sep %+.4f [%+.4f,%+.4f] | eqw %+.4f sign %.2f" % (nm, r["point"], r["lo"], r["hi"], r["eqw"], r["sign"]))
    io.open(os.path.join(HERE, "m32c_confirm_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("\nwrote m32c_confirm_result.json -> decides the frozen classifier + whether it clears the floor.")


if __name__ == "__main__":
    main()
