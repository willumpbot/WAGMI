"""M32 ladder atlas = Project X parts 1-2. Multi-step scale-out vs the runner on the m28 grid.
EXPLORATORY. Convergence note stands for MEAN R; the deliverable here is the DISTRIBUTION per style
(P(loss), P(<=-1R), give-back, variance, drawdown) + the big-runner cost, with a persistence-preserving
null on the mean so a "win" that is mechanical is flagged. Per-leg fees (more tranches = more legs).
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, synth_block, sidepaths, HOLD, HOR, SPACING, K_CTRL, rng
from m13_build import daily, em_pit, atr_pit, K_STOP, FEE_HALF

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")

# STYLES: ordered tranches (level_in_R, fraction) + implicit trailing remainder = 1 - sum(frac).
STYLES = {
    "runner":   [(1.0, 0.5)],                              # 50% @ +1R, 50% trail (the control)
    "quarters": [(0.5, 0.25), (0.75, 0.25), (1.0, 0.25)],  # +trail 25%  (owner's new default)
    "thirds":   [(0.5, 1/3), (1.0, 1/3)],                  # +trail 34%
    "q25_25":   [(0.5, 0.25), (1.0, 0.25)],                # 25%@.5, 25%@1, 50% trail
    "aggr":     [(0.5, 1/3), (0.75, 1/3), (1.0, 1/3 - 1e-9)],  # trail ~0 (fully scale out)
}


def trail_only(fav, adv, close, sf):
    """Trailing-stop realised FRACTION for a remainder that rides from entry (1R trail, floor -1R)."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    sfc = sf[:, None]
    rm = np.maximum.accumulate(fav, axis=1)
    rm_prev = np.concatenate((np.full((N, 1), -np.inf), rm[:, :-1]), axis=1)
    give = np.maximum(rm_prev - sfc, -sfc)
    hit = (adv >= -give) & (cols < HOLD)
    xb = first_true(hit)
    got = xb < 10**6
    return np.where(got, np.take_along_axis(give, np.minimum(xb, H - 1)[:, None], 1)[:, 0], close[:, HOLD - 1])


def resolve_style(fav, adv, close, sf, tranches):
    """Realised net R per moment for a scale-out style. Also returns peak R (for give-back) and n_legs."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    sfc = sf[:, None]
    stop_b = first_true(adv >= sfc)
    closeR = close[:, HOLD - 1] / sf
    peakR = np.maximum.accumulate(fav, axis=1)[:, HOLD - 1] / sf
    tr_frac = 1.0 - sum(f for _, f in tranches)
    total = np.zeros(N)
    n_filled = np.zeros(N)
    for L, frac in tranches:
        hit = first_true(fav >= L * sfc)
        fills = (hit < stop_b) & (hit < HOLD)
        stopped_first = (stop_b < HOLD) & (stop_b <= hit)
        contrib = np.where(fills, L, np.where(stopped_first, -1.0, closeR))   # per unit fraction, in R
        total += frac * contrib
        n_filled += fills.astype(float)
    if tr_frac > 1e-6:
        total += tr_frac * (trail_only(fav, adv, close, sf) / sf)
    legs = 1.0 + n_filled + (1.0 if tr_frac > 1e-6 else 0.0)   # entry + filled tranches + remainder close
    fee_R = FEE_HALF * legs / sf
    return total - fee_R, peakR


def main():
    print("M32 ladder atlas (Project X parts 1-2): styles vs runner; distribution + null.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M32_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    R = {s: [] for s in STYLES}
    PEAK = []
    NUL = {s: [] for s in STYLES}
    carr, dayk = [], []
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
        Hs, Ls, Cs = b["h"][pidx], b["l"][pidx], b["c"][pidx]
        sp = synth_block(b, ent, K_CTRL, HOR)
        for side in (1.0, -1.0):
            fav, adv, close = sidepaths(entry, Hs, Ls, Cs, side)
            res = {s: resolve_style(fav, adv, close, sf, t)[0] for s, t in STYLES.items()}
            _, peak = resolve_style(fav, adv, close, sf, STYLES["runner"])
            for s in STYLES:
                R[s].append(res[s])
            PEAK.append(peak)
            carr.extend([coin] * len(ent)); dayk.extend([int(uq[dix[e]]) for e in ent])
            if sp is not None:
                sfr = np.repeat(sf, K_CTRL)
                fa = np.where(side > 0, (sp[1] - sp[0]) / sp[0], (sp[0] - sp[2]) / sp[0])[:, :HOLD]
                ad = np.where(side > 0, (sp[0] - sp[2]) / sp[0], (sp[1] - sp[0]) / sp[0])[:, :HOLD]
                cl = (side * (sp[3] / sp[0] - 1.0))[:, :HOLD]
                nres = {s: resolve_style(fa, ad, cl, sfr, t)[0] for s, t in STYLES.items()}
                for s in STYLES:
                    NUL[s].append((nres[s] - nres["runner"]).reshape(len(ent), K_CTRL).mean(axis=1))
        done += 1
    c.close()
    for s in STYLES:
        R[s] = np.concatenate(R[s]); NUL[s] = np.concatenate(NUL[s])
    PEAK = np.concatenate(PEAK)
    carr = np.asarray(carr); dayk = np.asarray(dayk, np.int64)
    run = R["runner"]
    bigm = PEAK >= 1.5
    print("moments: %d (coins %d) | big-runner(peak>=1.5R) subset %d" % (len(run), done, int(bigm.sum())))

    def ci(v, mask=None):
        vv = v if mask is None else v[mask]
        cc = carr if mask is None else carr[mask]
        if len(vv) < 20:
            return float("nan"), float("nan"), float("nan")
        u = np.unique(cc); grp = {x: vv[cc == x] for x in u}
        bo = np.array([np.concatenate([grp[p] for p in u[rng.integers(0, len(u), len(u))]]).mean() for _ in range(2000)])
        return float(vv.mean()), float(np.percentile(bo, 2.5)), float(np.percentile(bo, 97.5))

    print("\n=== STYLE SURFACE (vs runner; mean is control-subtracted vs the persistence-preserving null) ===")
    print("  style     | dMean(real) | dMean(null) | NET(real-null) | P(loss) | P(<=-1R) | giveback | SD   | bigcost")
    out = {"moments": int(len(run)), "coins": done, "styles": {}}
    for s in STYLES:
        d = R[s] - run
        mr, lo, hi = ci(d)
        mn = float(NUL[s].mean())
        net = mr - mn
        ploss = float(np.mean(R[s] < 0)); p1 = float(np.mean(R[s] <= -1.0 + 1e-9))
        giveback = float(np.mean(np.maximum(PEAK, 0) - R[s]))      # peak R not kept
        sd = float(R[s].std())
        bc, _, _ = ci(d, bigm)
        print("  %-9s | %+.4f    | %+.4f    | %+.4f       | %.3f   | %.3f    | %+.3f   | %.3f| %+.3f"
              % (s, mr, mn, net, ploss, p1, giveback, sd, bc))
        out["styles"][s] = {"dmean_real": mr, "dmean_lo": lo, "dmean_hi": hi, "dmean_null": mn,
                            "net": net, "p_loss": ploss, "p_le_-1R": p1, "giveback": giveback,
                            "sd": sd, "big_runner_cost": bc, "abs_mean": float(R[s].mean())}
    io.open(os.path.join(HERE, "m32_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("\nNET ~ 0 for every style confirms the convergence (mean is a wash). Read the DISTRIBUTION")
    print("columns: that is where ladders differ. wrote m32_result.json")


if __name__ == "__main__":
    main()
