"""Mission 5 - "plan N trades before judging yourself." The owner's most important number.

How many plans must the owner log before his plan-picking edge (mean realized R per plan) is
distinguishable from zero at +0.1 / +0.2 / +0.3 R, two-sided 5%, 80% power?

Method: simulate the owner's OWN plan geometry on the real coin universe to get the per-plan R
dispersion (sigma), then N = (z_.975 + z_.80)^2 * sigma^2 / Delta^2 = 7.849 * sigma^2 / Delta^2.
Geometry (from server_exports/plans.json): LIMIT entry offset ~0.52 ATR, 24h fill window, stop = 1 ATR
(="1 expected move"; swept 1 and 1.2 ATR), target = 1.0R (owner median), 48h max hold, 9 bps round-trip.
Two readings: FILL-CONDITIONED (his selection edge GIVEN a fill) and ITT (all plans, unfilled = 0R).
Plans logged days apart -> treat as ~independent; a clustering design-effect note is included.
"""
import io, json, os, sqlite3
import numpy as np
from m13_build import daily, em_pit, atr_pit, FEE_HALF
from m30_run import first_true, HOLD, HOR, SPACING, rng

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
FILLW = 24                       # hours to fill the limit
HOLDP = 48                       # max hold after fill
LIMIT_ATR = 0.52                 # limit offset in ATR = median 2.36% / 4.5% ATR (26 owner plans)
TARGET_R = 1.0                   # target:stop ratio, median 1.0R across the 26 owner plans
RT_FEE = 2 * FEE_HALF            # round-trip fee as price fraction (~9 bps)
Zc = 1.959964 + 0.841621         # two-sided 5%, 80% power
DELTAS = [0.1, 0.2, 0.3]


def resolve_plan(px, H, L, C, atr, side, stop_mult):
    """Vectorised limit-fill then stop/target/timeout resolve. Returns (R_filled_or_nan, filled_bool).
    side +1 long, -1 short. px shape (N,), H/L/C shape (N,HOR) for bars 1..HOR after the plan bar."""
    N = px.shape[0]
    cols = np.arange(H.shape[1])[None, :]
    stop_frac = stop_mult * atr                       # 1R distance as price fraction
    tgt_frac = TARGET_R * stop_frac                   # target distance = 0.5R
    lim_frac = LIMIT_ATR * atr
    if side > 0:                                      # long: limit BELOW, fill if low <= limit
        limit = px * (1 - lim_frac)
        fillable = (L <= limit[:, None]) & (cols < FILLW)
        fb = first_true(fillable)
        filled = fb < 10**6
        stop = limit * (1 - stop_frac)                # stop below fill
        tgt = limit * (1 + tgt_frac)                  # target above fill
        inwin = (cols > fb[:, None]) & (cols <= (fb + HOLDP)[:, None])
        stop_b = first_true((L <= stop[:, None]) & inwin)
        tgt_b = first_true((H >= tgt[:, None]) & inwin)
    else:                                             # short: limit ABOVE, fill if high >= limit
        limit = px * (1 + lim_frac)
        fillable = (H >= limit[:, None]) & (cols < FILLW)
        fb = first_true(fillable)
        filled = fb < 10**6
        stop = limit * (1 + stop_frac)
        tgt = limit * (1 - tgt_frac)
        inwin = (cols > fb[:, None]) & (cols <= (fb + HOLDP)[:, None])
        stop_b = first_true((H >= stop[:, None]) & inwin)
        tgt_b = first_true((L <= tgt[:, None]) & inwin)
    # timeout close bar = min(fb+HOLDP, last)
    tob = np.minimum(fb + HOLDP, H.shape[1] - 1)
    close_px = np.take_along_axis(C, np.clip(tob, 0, H.shape[1] - 1)[:, None], 1)[:, 0]
    # R: stop-first within a bar (conservative). 1R = stop_frac in price.
    hit_stop = stop_b <= tgt_b                          # includes same-bar -> stop first
    r_stop = -1.0
    r_tgt = +TARGET_R
    # timeout realized move in R
    move_frac = np.where(side > 0, (close_px - limit) / limit, (limit - close_px) / limit)
    r_to = move_frac / stop_frac
    got_stop = filled & (stop_b < 10**6) & hit_stop
    got_tgt = filled & (tgt_b < 10**6) & (~hit_stop)
    R = np.where(got_stop, r_stop, np.where(got_tgt, r_tgt, r_to))
    R = R - RT_FEE / stop_frac                          # fees in R
    R = np.where(filled, R, np.nan)
    return R, filled


def main():
    print("Mission 5: plan-N-to-judge-yourself. Owner plan geometry on the real universe.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    for stop_mult in (1.0, 1.2):
        Rf, allR, fill_flags, coin_k = [], [], [], []
        done = 0
        for coin in coins:
            rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
            if len(rows) < 1000:
                continue
            a = np.asarray(rows, float)
            b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
            day, uq, dh, dl, dc = daily(b)
            atr_d = atr_pit(dh, dl, dc)
            dix = np.searchsorted(uq, day)
            atr_h = atr_d[dix]
            n = len(b["c"])
            elig = np.flatnonzero(np.isfinite(atr_h) & (atr_h > 0))
            elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - HOR - 2)]
            if len(elig) < 40:
                continue
            off = int(rng.integers(0, SPACING))
            ent, last = [], -10**9
            for e in elig:
                if e >= off and e - last >= SPACING:
                    ent.append(e); last = e
            ent = np.asarray(ent)
            atr = atr_h[ent]
            px = b["c"][ent]
            pidx = ent[:, None] + np.arange(1, HOR + 1)[None, :]
            H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
            for side in (1.0, -1.0):
                R, filled = resolve_plan(px, H, L, C, atr, side, stop_mult)
                Rf.append(R[filled]); fill_flags.append(filled)
                allR.append(np.where(filled, R, 0.0))      # ITT: unfilled = 0R
                coin_k.extend([coin] * len(ent))
            done += 1
        Rf = np.concatenate(Rf); allR = np.concatenate(allR); fill_flags = np.concatenate(fill_flags)
        p_fill = float(fill_flags.mean())
        mu_f, sd_f = float(np.nanmean(Rf)), float(np.nanstd(Rf))
        mu_i, sd_i = float(allR.mean()), float(allR.std())
        win = float(np.mean(Rf > 0))                    # fraction of filled plans closing green
        print("\n=== STOP = %g ATR (1R); target +%.1fR; limit %.1f ATR; %d coins; %d filled plans ==="
              % (stop_mult, TARGET_R, LIMIT_ATR, done, int(fill_flags.sum())))
        print("  fill rate %.1f%% | filled-plan R: mean %+.3f SD %.3f (%.1f%% close green) | "
              "ITT(all plans) R: mean %+.3f SD %.3f" % (100 * p_fill, mu_f, sd_f, 100 * win, mu_i, sd_i))
        print("  N to detect +Delta R/plan at 80%% power, two-sided 5%%  (N = %.3f * sigma^2 / Delta^2):" % (Zc ** 2))
        for D in DELTAS:
            n_fill = Zc ** 2 * sd_f ** 2 / D ** 2
            n_tot_fill = n_fill / max(p_fill, 1e-9)       # plans to LOG to get n_fill fills
            n_itt = Zc ** 2 * sd_i ** 2 / D ** 2          # judged on all plans (unfilled=0)
            print("    Delta=+%.1fR | FILLED-edge: %4d filled (= log ~%4d plans at this fill rate) | "
                  "ITT all-plans: %4d plans" % (D, int(np.ceil(n_fill)), int(np.ceil(n_tot_fill)), int(np.ceil(n_itt))))
        if stop_mult == 1.0:
            out = {"stop_atr": stop_mult, "p_fill": p_fill, "filled_mean": mu_f, "filled_sd": sd_f,
                   "itt_sd": sd_i, "win_at_target": win,
                   "N": {str(D): {"filled": int(np.ceil(Zc ** 2 * sd_f ** 2 / D ** 2)),
                                  "log_plans": int(np.ceil(Zc ** 2 * sd_f ** 2 / D ** 2 / max(p_fill, 1e-9))),
                                  "itt": int(np.ceil(Zc ** 2 * sd_i ** 2 / D ** 2))} for D in DELTAS}}
            io.open(os.path.join(HERE, "m5_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    c.close()
    print("\nNOTE: plans logged days apart -> treated as independent. If several plans share one")
    print("regime/day, inflate N by the design effect 1+(m-1)*rho (m plans/cluster, rho intra-corr).")
    print("wrote m5_result.json")


if __name__ == "__main__":
    main()
