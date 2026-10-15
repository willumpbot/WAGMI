"""Mission 7 (interpretation B, target 1.0R) - how much is a LIMIT-entry plan's GRADE inflated by the
fill/path optimism of grading only from the moment price reaches the level? Two clean components:
  SELECTION credit = mean(LIMIT-filled R) - mean(MARKET-at-plan-time R) on the SAME plans: a limit only
    fills when price comes TO it (a selected local extreme), so the graded entry is mechanically better
    than a market entry - the grader must not credit that to the plan's direction skill.
  FILL-TIMING optimism = mean(LIMIT@level R) - mean(LIMIT@fill-bar-close R): grading a fill at the exact
    wicked level vs the realistic close of the bar that tagged it (latency / maker-miss).
The contamination the grader should SUBTRACT as an anchor = these gaps (in R). m5 geometry:
limit 0.52 ATR, stop 1 ATR (1R), target 1.0R, 24h fill window, 48h hold, 9bps. EXPLORATORY; panels grid.
"""
import io, json, os, sqlite3
import numpy as np
from m30_run import first_true, sidepaths, HOLD, HOR, SPACING, rng
from m13_build import daily, em_pit, atr_pit, FEE_HALF, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
FILLW, HOLDP, LIMIT_ATR, TARGET_R, RT_FEE = 24, 48, 0.52, 1.0, 2 * FEE_HALF


def resolve_from(entry_px, H, L, C, atr, side, start_bar):
    """Resolve stop(1 ATR)/target(1R)/timeout in R from a fill at entry_px, starting the walk at
    start_bar (inclusive+1). Vectorised. side +1 long / -1 short."""
    N, HH = H.shape
    cols = np.arange(HH)[None, :]
    stop_frac = atr                      # 1R = 1 ATR
    tgt_frac = TARGET_R * stop_frac
    if side > 0:
        stop = entry_px * (1 - stop_frac); tgt = entry_px * (1 + tgt_frac)
        inwin = (cols > start_bar[:, None]) & (cols <= (start_bar + HOLDP)[:, None])
        sb = first_true((L <= stop[:, None]) & inwin); tb = first_true((H >= tgt[:, None]) & inwin)
    else:
        stop = entry_px * (1 + stop_frac); tgt = entry_px * (1 - tgt_frac)
        inwin = (cols > start_bar[:, None]) & (cols <= (start_bar + HOLDP)[:, None])
        sb = first_true((H >= stop[:, None]) & inwin); tb = first_true((L <= tgt[:, None]) & inwin)
    tob = np.minimum(start_bar + HOLDP, HH - 1)
    cpx = np.take_along_axis(C, np.clip(tob, 0, HH - 1)[:, None], 1)[:, 0]
    move = np.where(side > 0, (cpx - entry_px) / entry_px, (entry_px - cpx) / entry_px)
    r_to = move / stop_frac
    hit_stop = sb <= tb
    R = np.where((sb < 10**6) & hit_stop, -1.0, np.where((tb < 10**6) & (~hit_stop), TARGET_R, r_to))
    return R - RT_FEE / stop_frac


def main():
    print("Mission 7: plan-grader fill/path optimism (B, 1.0R). m5 geometry, panels grid.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M7_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    SEL, FILLT, coin_k, day_k = [], [], [], []
    mkt_all, lim_all = [], []
    done = 0
    for coin in coins:
        rows = c.execute("SELECT t,o,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}
        day, uq, dh, dl, dc = daily(b)
        atr_d = atr_pit(dh, dl, dc); dix = np.searchsorted(uq, day); atr_h = atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - HOR - 2)]
        if len(elig) < 40:
            continue
        off = int(rng.integers(0, SPACING)); ent, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                ent.append(e); last = e
        ent = np.asarray(ent); atr = atr_h[ent]; px = b["c"][ent]
        pidx = ent[:, None] + np.arange(1, HOR + 1)[None, :]
        H, L, C, O = b["h"][pidx], b["l"][pidx], b["c"][pidx], b["o"][pidx]
        for side in (1.0, -1.0):
            lim_frac = LIMIT_ATR * atr
            limit = px * (1 + lim_frac) if side < 0 else px * (1 - lim_frac)
            cols = np.arange(HOR)[None, :]
            if side < 0:
                fb = first_true((H >= limit[:, None]) & (cols < FILLW))
            else:
                fb = first_true((L <= limit[:, None]) & (cols < FILLW))
            filled = fb < 10**6
            fbc = np.clip(fb, 0, HOR - 1)
            # OPTIMISTIC: fill AT the limit level, resolve from the fill bar
            r_opt = resolve_from(limit, H, L, C, atr, side, fbc)
            # REALISTIC fill: fill at the fill BAR'S CLOSE (latency/maker-miss proxy)
            fill_close = np.take_along_axis(C, fbc[:, None], 1)[:, 0]
            r_real = resolve_from(fill_close, H, L, C, atr, side, fbc)
            # MARKET at plan-time: enter at px now (bar 0), resolve from bar 0
            r_mkt = resolve_from(px, H, L, C, atr, side, np.zeros(len(ent), int))
            m = filled
            SEL.append((r_opt - r_mkt)[m])          # selection credit (limit vs market, filled)
            FILLT.append((r_opt - r_real)[m])        # fill-at-level vs fill-at-close
            lim_all.append(r_opt[m]); mkt_all.append(r_mkt[m])
            coin_k.extend([coin] * int(m.sum())); day_k.extend([int(uq[dix[e]]) for e, mm in zip(ent, m) if mm])
        done += 1
    c.close()
    SEL = np.concatenate(SEL); FILLT = np.concatenate(FILLT)
    lim_all = np.concatenate(lim_all); mkt_all = np.concatenate(mkt_all)
    carr = np.asarray(coin_k); dayk = np.asarray(day_k, np.int64)

    def ci(v):
        u = np.unique(carr); gc = {x: v[carr == x] for x in u}
        b1 = np.array([np.concatenate([gc[p] for p in u[rng.integers(0, len(u), len(u))]]).mean() for _ in range(2000)])
        ud = np.unique(dayk); gd = {x: v[dayk == x] for x in ud}
        b2 = np.array([np.concatenate([gd[p] for p in ud[rng.integers(0, len(ud), len(ud))]]).mean() for _ in range(2000)])
        lo = min(np.percentile(b1, 2.5), np.percentile(b2, 2.5)); hi = max(np.percentile(b1, 97.5), np.percentile(b2, 97.5))
        return float(v.mean()), float(lo), float(hi)

    print("filled limit plans: %d (coins %d)" % (len(SEL), done))
    s_m, s_lo, s_hi = ci(SEL); f_m, f_lo, f_hi = ci(FILLT)
    print("\n=== M7 contamination the grader should SUBTRACT (R per filled plan; wider coin/day CI) ===")
    print("  SELECTION credit (limit-filled R - market-at-plan R) = %+.3f R [%+.3f,%+.3f]" % (s_m, s_lo, s_hi))
    print("     -> graded limit entries start %+.3f R better than a market entry PURELY because a limit only" % s_m)
    print("        fills at a selected local extreme; the grader must not read this as direction skill.")
    print("  FILL-TIMING (fill@level - fill@bar-close) = %+.3f R [%+.3f,%+.3f]  (A, the cheap one)" % (f_m, f_lo, f_hi))
    print("     -> grading the exact wicked level vs the realistic close of the tagging bar.")
    print("  TOTAL optimism anchor to subtract ~= %+.3f R per filled plan." % (s_m + f_m))
    print("  (context: graded limit mean %+.3f R vs market mean %+.3f R)" % (float(lim_all.mean()), float(mkt_all.mean())))
    out = {"n_filled": len(SEL), "coins": done,
           "selection_credit": {"mean": s_m, "lo": s_lo, "hi": s_hi},
           "fill_timing": {"mean": f_m, "lo": f_lo, "hi": f_hi},
           "total_anchor": s_m + f_m, "graded_limit_mean": float(lim_all.mean()), "market_mean": float(mkt_all.mean())}
    io.open(os.path.join(HERE, "m7_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("\nwrote m7_result.json")


if __name__ == "__main__":
    main()
