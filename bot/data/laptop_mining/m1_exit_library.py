"""M1 — EXIT-POLICY LIBRARY on perps. EXPLORATORY sweep; nothing here reaches a card above HYPOTHESIS.

Owner (2026-10-13, via the server): "intensive candle data mining for our leverage/perp trading ...
extremely long, hard, challenging data processes to obtain and understand information we may not have
fully pathed through yet." Mission text: MISSIONS_PERP_CANDLES_2026-10-13.md.

THE QUESTION: "who manages the exit" -- answered mechanically. Direction is null in this project (~98
direction tests, 8,340 graded rounds, all no), so entries are RANDOM-TIME and BOTH SIDES. That is the
point, not a limitation: with direction stripped out, any difference between exit rules is the
mechanical cost/benefit of the rule itself rather than a dressed-up directional edge.

ENGINE
  bars      candles_1h, 178 perps, 2026-03-17..2026-10-13 (~5,050 bars/coin, 884k rows)
  stop      K x exp_move, K in {1.0, 1.5, 2.0, 2.5, 3.0}; R == the stop distance
  exp_move  the FITTED HAR from volatility_forecast.json (y1_beta + y1_smearing) on daily closes --
            the same quantity the bot sizes from, NOT funding_stop.py's unfitted variant
  horizon   72 one-hour bars
  fees      9 bps round trip taker; a partial exit pays its own leg (so partial rules pay 1.5x)
  unit      BPS OF NOTIONAL NET OF FEES, never dollars, never R alone (ground rule)

EVERY RULE IS EVALUATED AGAINST THE SAME FORWARD PATH, so rule-vs-rule differences cannot come from
different price action. Rules compared:
  stop_only            stop, else close at 72h
  tgt_{0.5,1,1.5,2,3}R  first touch of target or stop, else 72h
  time_{4,12,24,48}h   close at the horizon with the stop still live
  be_at_1R             once +1R trades, stop moves to entry (REFUTED once as breakeven_ratchet --
                       re-tested here on perps WITH fees, per the mission text)
  partial_1R_har       50% off at +1R, remainder trails 1.0 x exp_move below the running extreme
  partial_1R_atr       same, trailing 2.0 x ATR(14, 1h)
  partial_1R_chand     same, chandelier at 3.0 x ATR from the running extreme

CONSERVATIVE CONVENTIONS, declared because they move the answer:
  * if a bar's high reaches the target AND its low reaches the stop, the STOP is taken. 1h bars
    cannot order two touches inside one bar, and earlier tonight that exact ambiguity produced a 22%
    referee disagreement against 5m on a 1.66% stop. Assuming the bad fill is the only honest default.
  * a trail only moves on a CLOSED bar, never intrabar.
  * entries need 72 forward bars and a valid exp_move, so the last 72 bars of each coin are unused.

WHAT THIS CANNOT SETTLE: 1h bars are a coarse referee for tight stops. 5m exists for 72 coins over
~21 days and is held back deliberately as a REFEREE (phase 2), to measure the 1h disagreement rate per
rule and per K rather than assume it. No rule ranking from this file should be believed at K=1.0 until
that check runs.

OUTPUT: per (K, rule) expectancy in bps net, win rate, P(stop hit), max adverse excursion in R, fee
drag, mean bars held -- reported for ALL coins and split ORIG17 vs NEW156 so the built-in replication
is visible. Clustered by DAY and by COIN, because the mission's ground rules require both and because
pooling has produced a sign flip in this project more often than any other defect.

Resumable: per-coin checkpoints in m1_checkpoints/; progress to crunch/STATUS for server liveness.
"""
import io
import json
import math
import os
import sqlite3
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
CKPT = os.path.join(HERE, "m1_checkpoints")
STATUS = os.path.join(HERE, "crunch", "STATUS")
EPS = 1e-8
HORIZON = 72
FEE_BPS = 9.0
PARTIAL_FEE_BPS = FEE_BPS * 1.5
K_SET = (1.0, 1.5, 2.0, 2.5, 3.0)
ENTRIES_PER_COIN = 400
ATR_N = 14
rng = np.random.default_rng(20261013)

ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]

RULES = (["stop_only"]
         + ["tgt_%gR" % r for r in (0.5, 1.0, 1.5, 2.0, 3.0)]
         + ["time_%dh" % h for h in (4, 12, 24, 48)]
         + ["be_at_1R", "partial_1R_har", "partial_1R_atr", "partial_1R_chand"])


def log(msg):
    line = "%s  M1  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with io.open(STATUS, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def coins():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    out = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    c.close()
    return out


def bars_1h(coin):
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    rows = c.execute("SELECT t,o,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
    c.close()
    if not rows:
        return None
    a = np.asarray(rows, float)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}


def daily_em(b):
    """exp_move per DAY from the fitted HAR on daily closes, mapped onto each 1h bar."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    if len(close) < 40:
        return None, None
    rets = np.concatenate(([0.0], (close[1:] / close[:-1] - 1.0) * 100.0))
    em = np.full(len(uniq), np.nan)
    for i in range(30, len(uniq)):
        rv1 = abs(rets[i])
        rv5 = sd(list(rets[i - 4:i + 1]))
        rv22 = sd(list(rets[i - 21:i + 1]))
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[i] = v
    idx = np.searchsorted(uniq, day)
    return em[idx], uniq


def atr(b, n=ATR_N):
    tr = np.maximum(b["h"][1:] - b["l"][1:],
                    np.maximum(np.abs(b["h"][1:] - b["c"][:-1]),
                               np.abs(b["l"][1:] - b["c"][:-1])))
    out = np.full(len(b["c"]), np.nan)
    if len(tr) >= n:
        cs = np.cumsum(np.insert(tr, 0, 0.0))
        out[n:] = (cs[n:] - cs[:-n]) / n
    return out


def first_true(mat):
    """First column index where mat is True, else HORIZON (meaning never)."""
    any_ = mat.any(axis=1)
    idx = mat.argmax(axis=1)
    return np.where(any_, idx, HORIZON)


def simulate(coin, b, em_bar, atr_bar, synthetic=False):
    """All rules x all K for one coin, on shared random entry paths. Returns a list of dicts."""
    n = len(b["c"])
    ok = np.where(~np.isnan(em_bar[:n - HORIZON - 1]) & ~np.isnan(atr_bar[:n - HORIZON - 1]))[0]
    ok = ok[ok > ATR_N + 1]
    if len(ok) < 50:
        return []
    take = min(ENTRIES_PER_COIN, len(ok))
    ent = rng.choice(ok, size=take, replace=False)
    sides = np.where(rng.random(take) < 0.5, 1.0, -1.0)      # +1 long, -1 short

    # forward path matrices, shared by every rule
    off = np.arange(1, HORIZON + 1)
    pidx = ent[:, None] + off[None, :]
    entry = b["c"][ent]
    if synthetic:
        # NO-EDGE CONTROL, v2. The v1 control was a driftless GBM with wicks drawn as |N(0,sig)| in
        # each direction, and sanity-checking it exposed the flaw: on WIF it produced -66 bps on
        # stop_only where real bars give -3.7, an 18x gap that scaled with volatility, because
        # independent wicks invent far more stop-outs than real bars contain. A control that is wrong
        # in a volatility-dependent way is worse than none -- it would have made high-vol coins look
        # like the best performers.
        #
        # v2 BOOTSTRAPS THE COIN'S OWN BAR SHAPES: each synthetic bar draws a real bar at random and
        # replays its proportional (prev->close) move and its (prev->high, prev->low) wick offsets.
        # That keeps the true intrabar geometry, range distribution and fat tails by construction,
        # and removes only the SEQUENCE -- which is exactly what "no edge" has to mean here. The log
        # returns are DEMEANED so the control is exactly driftless, since the real period had drift
        # and a drifting control is not a no-edge control.
        prevc = b["c"][:-1]
        lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
        up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
        dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
        good = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
        lr, up, dn = lr[good], np.maximum(up[good], 0.0), np.maximum(dn[good], 0.0)
        if len(lr) < 100:
            return []
        # DRIFT REMOVAL, v3. v2 subtracted the mean LOG return, which is the wrong unit: by Jensen
        # that leaves a POSITIVE arithmetic drift of about sig^2/2 per bar, compounding over 72 bars
        # into +66 bps on WIF where a no-edge control must sit at -(fee). Same class of error as the
        # rest of tonight -- correcting in the convenient unit rather than the one that matters.
        # The price path must be a MARTINGALE, so normalise the multiplicative steps to mean 1.
        draw = rng.integers(0, len(lr), size=(len(ent), HORIZON))
        step = np.exp(lr[draw])
        step = step / float(np.mean(np.exp(lr)))              # E[step] == 1 exactly
        C = entry[:, None] * np.cumprod(step, axis=1)
        prev = np.concatenate((entry[:, None], C[:, :-1]), axis=1)
        H = np.maximum(prev, C) * (1.0 + up[draw])
        L = np.minimum(prev, C) * (1.0 - dn[draw])
    else:
        H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
    emv = em_bar[ent] / 100.0 * entry                        # exp_move in price
    atrv = atr_bar[ent]
    day = (b["t"][ent] // 86400000).astype(np.int64)

    out = []
    for K in K_SET:
        Rpx = K * emv                                        # stop distance in price
        with np.errstate(invalid="ignore"):
            # signed favourable / adverse excursions in R, per bar
            fav = (np.where(sides[:, None] > 0, H - entry[:, None], entry[:, None] - L)
                   / Rpx[:, None])
            adv = (np.where(sides[:, None] > 0, entry[:, None] - L, H - entry[:, None])
                   / Rpx[:, None])
        stop_bar = first_true(adv >= 1.0)
        mae = np.nanmax(np.where(np.arange(HORIZON)[None, :] <=
                                 np.minimum(stop_bar, HORIZON - 1)[:, None], adv, np.nan), axis=1)

        for rule in RULES:
            gross = np.zeros(take)
            held = np.full(take, HORIZON, dtype=int)
            fee = np.full(take, FEE_BPS)
            stopped = np.zeros(take, bool)

            if rule == "stop_only":
                ex = stop_bar
                gross = np.where(ex < HORIZON, -1.0,
                                 (C[:, -1] - entry) * sides / Rpx)
                held = np.minimum(ex, HORIZON - 1) + 1
                stopped = ex < HORIZON

            elif rule.startswith("tgt_"):
                tR = float(rule[4:-1])
                tgt_bar = first_true(fav >= tR)
                # same-bar ambiguity resolves to the STOP (declared convention)
                ex = np.minimum(stop_bar, tgt_bar)
                won = (tgt_bar < stop_bar)
                gross = np.where(won, tR, np.where(stop_bar < HORIZON, -1.0,
                                                   (C[:, -1] - entry) * sides / Rpx))
                held = np.minimum(ex, HORIZON - 1) + 1
                stopped = (stop_bar <= tgt_bar) & (stop_bar < HORIZON)

            elif rule.startswith("time_"):
                hh = int(rule[5:-1])
                cut = min(hh, HORIZON) - 1
                sb = first_true(adv[:, :cut + 1] >= 1.0)
                hit = sb <= cut
                gross = np.where(hit, -1.0, (C[:, cut] - entry) * sides / Rpx)
                held = np.where(hit, sb + 1, cut + 1)
                stopped = hit

            elif rule == "be_at_1R":
                r1 = first_true(fav >= 1.0)
                # before +1R the original stop is live; after it, breakeven
                pre_stop = first_true(adv >= 1.0)
                be_hit = np.full(take, HORIZON)
                for i in range(take):
                    if r1[i] < HORIZON:
                        seg = adv[i, r1[i] + 1:]
                        j = np.argmax(seg >= 0.0) if (seg >= 0.0).any() else -1
                        be_hit[i] = (r1[i] + 1 + j) if j >= 0 else HORIZON
                reached = r1 < pre_stop
                gross = np.where(~reached,
                                 np.where(pre_stop < HORIZON, -1.0,
                                          (C[:, -1] - entry) * sides / Rpx),
                                 np.where(be_hit < HORIZON, 0.0,
                                          (C[:, -1] - entry) * sides / Rpx))
                held = np.where(~reached, np.minimum(pre_stop, HORIZON - 1) + 1,
                                np.minimum(be_hit, HORIZON - 1) + 1)
                stopped = (~reached) & (pre_stop < HORIZON)

            else:   # partial at 1R + trailing runner
                r1 = first_true(fav >= 1.0)
                pre_stop = first_true(adv >= 1.0)
                reached = r1 < pre_stop
                if rule == "partial_1R_har":
                    trail_px = emv
                elif rule == "partial_1R_atr":
                    trail_px = 2.0 * atrv
                else:
                    trail_px = 3.0 * atrv
                trail_R = trail_px / Rpx
                run = np.zeros(take)
                for i in range(take):
                    if not reached[i]:
                        continue
                    peak = fav[i, r1[i]]
                    j = r1[i] + 1
                    while j < HORIZON:
                        peak = max(peak, fav[i, j])
                        if fav[i, j] <= peak - trail_R[i]:
                            break
                        j += 1
                    run[i] = min(peak - trail_R[i], fav[i, min(j, HORIZON - 1)]) \
                        if j < HORIZON else (C[i, -1] - entry[i]) * sides[i] / Rpx[i]
                    held[i] = min(j, HORIZON - 1) + 1
                gross = np.where(~reached,
                                 np.where(pre_stop < HORIZON, -1.0,
                                          (C[:, -1] - entry) * sides / Rpx),
                                 0.5 * 1.0 + 0.5 * run)
                fee = np.where(reached, PARTIAL_FEE_BPS, FEE_BPS)
                held = np.where(~reached, np.minimum(pre_stop, HORIZON - 1) + 1, held)
                stopped = (~reached) & (pre_stop < HORIZON)

            # R -> bps of notional: R is K*em as a FRACTION of entry, so 1R = K*em*1e4 bps
            r_bps = (Rpx / entry) * 1e4
            net_bps = gross * r_bps - fee
            out.append({"coin": coin, "K": K, "rule": rule, "synthetic": bool(synthetic), "n": int(take),
                        "mean_bps": float(np.nanmean(net_bps)),
                        "median_bps": float(np.nanmedian(net_bps)),
                        "win_rate": float(np.nanmean(net_bps > 0)),
                        "p_stop": float(np.nanmean(stopped)),
                        "mae_R": float(np.nanmean(mae)),
                        "fee_bps": float(np.nanmean(fee)),
                        "bars_held": float(np.nanmean(held)),
                        "r_bps": float(np.nanmean(r_bps)),
                        "days": [int(x) for x in np.unique(day)][:0],   # not stored per row
                        "day_mean_bps": _day_means(net_bps, day)})
    return out


def _day_means(net, day):
    """Equal-weighted day means, so the pooled figure never stands alone."""
    o = {}
    for d in np.unique(day):
        m = day == d
        o[int(d)] = float(np.nanmean(net[m]))
    return o


def main():
    os.makedirs(CKPT, exist_ok=True)
    cs = coins()
    log("start: %d coins, %d rules x %d K, %d entries/coin, horizon %dh, fees %.0f bps"
        % (len(cs), len(RULES), len(K_SET), ENTRIES_PER_COIN, HORIZON, FEE_BPS))
    t0 = time.time()
    done = 0
    for i, coin in enumerate(cs):
        cf = os.path.join(CKPT, "%s.json" % coin)
        if os.path.exists(cf):
            done += 1
            continue
        b = bars_1h(coin)
        if b is None or len(b["c"]) < 200:
            io.open(cf, "w", encoding="utf-8").write("[]")
            continue
        em_bar, _ = daily_em(b)
        if em_bar is None:
            io.open(cf, "w", encoding="utf-8").write("[]")
            continue
        a = atr(b)
        rows = simulate(coin, b, em_bar, a, synthetic=False)
        rows += simulate(coin, b, em_bar, a, synthetic=True)     # no-edge control, same rule code
        io.open(cf, "w", encoding="utf-8").write(json.dumps(rows))
        done += 1
        if done % 10 == 0:
            el = time.time() - t0
            log("%d/%d coins (%.1f min, %.1fs/coin)" % (done, len(cs), el / 60, el / max(done, 1)))
    log("simulation complete: %d coins in %.1f min" % (done, (time.time() - t0) / 60))
    log("next: aggregate with m1_report.py (ORIG17 vs NEW156, day- and coin-clustered)")


if __name__ == "__main__":
    main()
