"""M28 stage 1 -- the MAP: per-MOMENT features + both-sides outcomes under the live machinery.

Design: M28_MAP_DESIGN.md + M28_AMENDMENT_1.md (panel: 7 FATALs adopted pre-run) + M28_SPLIT_SEAL.md
(boundary = calendar daykey 20693, unconditional). EXPLORATORY on discovery; the confirmation
population is built but its outcome columns are written to a SEPARATE file the fit stage must not
open before the condition freeze.

Amendment 1 structure encoded here:
  * THE MOMENT IS THE UNIT: one grid ts per 24h per coin (per-coin random day offset, seeded), BOTH
    sides evaluated on the SAME path -- real, every control draw, and nullreal all share one bar path
    per (coin, ts); the short side's excursions are the long side's mirrored (fav_S = adv_L etc.).
    Outcomes stored per side so the fit can form D = (L-S)/2 and A = (L+S)/2.
  * Styles as outcome dimensions: runner (half at +1R, 1.0 x ATR14 trail, 48h) and full_1R, both from
    the m13 resolver (em lagged one closed day; ONE point-in-time ATR14 for engine and features; leg
    fees on actual notionals; funding carry accrued per leg hold with side-correct sign).
  * Controls: K=8 martingale draws + 1 independent nullreal, resampling pool = bars STRICTLY BEFORE
    the moment (point-in-time; the full-history pool breached the seal for confirmation-era bars).
  * Condition columns (point-in-time, coverage reported, NaN never imputed):
      atr_em, atr_pct, stop_atr, trend_raw, room_long/short, ret7_raw, hour_b, btc_beta, btc_r2,
      oi_chg (31 syms / 130d -- partial), fund_pctl (own-history), fund_rate,
      fund_hot_xs  = strictly above the interpolated cross-sectional p80 of all coins' funding at that
                     hour (the LIVE definition, scanner.py:75-76/181 -- recomputed, never scan_log),
      waking_24h   = any 1h bar in the prior 24 with ret >= +0.5 x (lagged daily em) AND volume >=
                     2.5 x the trailing 480h closed-bar median volume (M11 B_up, thresholds frozen;
                     pre-stated expected sign NEGATIVE),
      btc_shock_24h= any |BTC 1h ret| > 3 x (BTC lagged em / sqrt(24)) in the prior 24 bars (fitted
                     HAR em, lagged -- never naive constants),
      vol_rank_xs  = coin's atr_pct percentile among all coins with finite ATR that day (cross-
                     sectional, point-in-time).
    EXCLUDED per Amendment 1: voice agreement (dropped), liq_burst (descriptive-only, not built here),
    dissent columns (gated), scan_log-sourced flags (time wedge).
  * Builder filter constants are hashed into the meta; changing them voids the run (seal).

Bar resolution: 1h (5m does not span the panel); the twin gates run separately on 5m via
exit_style.play (m28_gates.py) and the 5m-vs-1h delta is a stated optimism bound on every map number.
"""
import hashlib
import io
import json
import math
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

import panel_snapshot
from m13_build import (daily, em_pit, atr_pit, swings, room_atr, load_oi, oi_chg_at,
                       resolve_vec, net_outcomes, fund_series, rate_at, K_STOP, EPS)

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
OUT_DISC = os.path.join(HERE, "m28_map_discovery.npz")
OUT_CONF = os.path.join(HERE, "m28_map_confirmation_SEALED.npz")
META = os.path.join(HERE, "m28_build_meta.json")

HORIZON = 72
SPACING_H = 24            # one moment per 24h per coin (Amendment 1: applies to the (coin, ts) PAIR)
K_CTRL = 8
BOUNDARY_DAYKEY = 20693   # calendar constant, unconditional (seal amendment)
MIN_DAYIDX = 61
ATR_TRAIL = 1.00
ARMS = ("runner_1.00atr", "full_1R")   # resolve_vec computes more; we keep these two
FEATS = ("atr_em", "atr_pct", "stop_atr", "trend_raw", "room_long", "room_short", "ret7_raw",
         "hour_b", "btc_beta", "btc_r2", "oi_chg", "fund_pctl", "fund_rate", "fund_hot_xs",
         "waking_24h", "btc_shock_24h", "vol_rank_xs")
ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
FILTERS = {"min_1h_bars": HORIZON + 900, "min_days": 70, "min_dayidx": MIN_DAYIDX,
           "spacing_h": SPACING_H, "fwd_bars": HORIZON, "k_stop": K_STOP, "atr_trail": ATR_TRAIL,
           "k_ctrl": K_CTRL, "boundary_daykey": BOUNDARY_DAYKEY, "pool": "bars strictly before ts",
           "wake": "ret>=0.5*em_lag_daily AND vol>=2.5*median(vol[-480:]) closed bars",
           "btc_shock": "abs(1h ret) > 3*em_lag/sqrt(24)", "fund_hot": "xs interpolated p80 strict"}
rng = np.random.default_rng(20261016)


def synth_paths_pit(b, ent, k):
    """k martingale path sets per entry, pool = bars strictly before each entry (point-in-time).
    Returns fav/adv/close for the LONG side, (len(ent)*k, HORIZON); short mirrors in the caller."""
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
    # per-entry pool length = number of valid bars strictly before the entry index
    gidx = np.flatnonzero(g)
    pool_len = np.searchsorted(gidx, ent)                 # valid bars before each entry
    if (pool_len < 200).any():
        return None
    N = len(ent)
    u = rng.random((N * k, HORIZON))
    pl = np.repeat(pool_len, k)[:, None]
    draw = gidx[(u * pl).astype(np.int64)]                # indices into the pre-entry pool
    lr_d, up_d, dn_d = lr[draw], np.maximum(up[draw], 0.0), np.maximum(dn[draw], 0.0)
    # E[step]=1 within each entry's own pool
    norm = np.array([np.mean(np.exp(lr[gidx[:p]])) for p in pool_len])
    step = np.exp(lr_d) / np.repeat(norm, k)[:, None]
    entry = np.repeat(b["c"][ent], k)[:, None]
    C = entry * np.cumprod(step, axis=1)
    prev = np.concatenate((entry, C[:, :-1]), axis=1)
    H = np.maximum(prev, C) * (1.0 + up_d)
    L = np.minimum(prev, C) * (1.0 - dn_d)
    fav = (H - entry) / entry
    adv = (entry - L) / entry
    close = C / entry - 1.0
    return fav, adv, close


def both_sides(fav, adv, close, sf, atr_f, side_rate_cum):
    """Resolve the two kept arms for LONG and SHORT on the SAME paths.
    close is the signed price path (long convention); short mirrors: fav<->adv, close -> -close.
    Returns {('L'|'S', arm): net_frac}."""
    out = {}
    for tag, f, a, c, sgn in (("L", fav, adv, close, 1.0), ("S", adv, fav, -close, -1.0)):
        res = resolve_vec(f, a, c, sf, atr_f)
        side = np.full(len(sf), sgn)
        net = net_outcomes({k: res[k] for k in ARMS}, sf, side, side_rate_cum)
        for arm in ARMS:
            out[(tag, arm)] = net[arm]
    return out


def main():
    print("M28 stage 1 -- building the map (moments, both sides, shared paths). EXPLORATORY.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    snap = panel_snapshot.stamp(c)
    print("SOURCE SNAPSHOT: %s" % panel_snapshot.describe(snap))

    co = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
    btc = np.asarray(c.execute("SELECT t,h,l,c,v FROM candles_1h WHERE coin='BTC' ORDER BY t").fetchall(), float)
    bb = {"t": btc[:, 0], "h": btc[:, 1], "l": btc[:, 2], "c": btc[:, 3]}
    bday, buq, bdh, bdl, bdc = daily(bb)
    bem = em_pit(bdc)
    blr = np.concatenate(([np.nan], np.log(bdc[1:] / bdc[:-1])))
    # BTC 1h returns + per-bar shock flag (lagged em / sqrt 24)
    bret = np.concatenate(([0.0], bb["c"][1:] / bb["c"][:-1] - 1.0))
    bdix = np.searchsorted(buq, bday)
    bshock_bar = np.abs(bret) > 3.0 * (bem[bdix] / math.sqrt(24))
    bshock_bar &= np.isfinite(bem[bdix])
    # btc_shock_24h at bar e: any shock in [e-24, e-1]
    cs = np.concatenate(([0], np.cumsum(bshock_bar.astype(np.int64))))
    btc_t = bb["t"]

    oi = load_oi()
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]

    # ---- cross-sectional funding p80 per hour, and xs vol rank per day (two passes) ----
    print("pass 1/2: cross-sectional funding + vol tables...")
    fund_by_coin = {}
    atrpct_day = {}         # coin -> (uq, atr_frac per day)
    for coin in coins:
        fr = fund_series(c, coin)
        if len(fr):
            fund_by_coin[coin] = fr
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < FILTERS["min_1h_bars"]:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        if len(dc) < FILTERS["min_days"]:
            continue
        atrpct_day[coin] = (uq, atr_pit(dh, dl, dc))
    # hourly grid for funding xs: use epoch-hour keys
    all_hours = {}
    for coin, fr in fund_by_coin.items():
        hrs = (fr[:, 0] // 3600).astype(np.int64)
        for h_, r_ in zip(hrs, fr[:, 1]):
            all_hours.setdefault(int(h_), []).append((coin, float(r_)))
    xs_p80 = {}
    for h_, lst in all_hours.items():
        if len(lst) >= 20:
            xs_p80[h_] = float(np.percentile([r for _, r in lst], 80))
    # xs vol rank per (daykey): coin's atr_pct percentile among coins with finite atr that day
    day_atr = {}
    for coin, (uq, atr) in atrpct_day.items():
        for dk, v in zip(uq, atr):
            if np.isfinite(v):
                day_atr.setdefault(int(dk), []).append((coin, v))
    xs_rank = {}
    for dk, lst in day_atr.items():
        vals = np.array([v for _, v in lst])
        xs_rank[dk] = {coin: float((vals < v).mean()) for coin, v in lst}

    print("pass 2/2: moments...")
    M = {"feats": [], "coin": [], "daykey": [], "t": [], "sf": [], "disc": [],
         "L_real": [], "S_real": [], "L_ctrl": [], "S_ctrl": [], "L_null": [], "S_null": []}
    FD = {"rows": [], "coin": [], "daykey": []}
    done = 0
    for coin in coins:
        if coin not in atrpct_day:
            continue
        rows = c.execute("SELECT t,h,l,c,v FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        vol = a[:, 4]
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        sh, sl = swings(dh, dl)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h[:n - HORIZON - 1]) & np.isfinite(atr_h[:n - HORIZON - 1])
                              & (atr_h[:n - HORIZON - 1] > 0))
        elig = elig[dix[elig] >= MIN_DAYIDX]
        elig = elig[elig >= 500]            # >=500 prior bars for the point-in-time control pool
        if len(elig) < 40:
            continue
        # one moment per 24 bars: stride grid with per-coin random offset over eligible indices
        off = int(rng.integers(0, SPACING_H))
        ent, last = [], -10 ** 9
        for e in elig:
            if e >= off and e - last >= SPACING_H:
                ent.append(e)
                last = e
        ent = np.asarray(ent, dtype=np.int64)
        if len(ent) < 30:
            continue
        sf = K_STOP * em_h[ent]
        atr_f = atr_h[ent]
        t_e = np.where(b["t"][ent] > 1e12, b["t"][ent] / 1000.0, b["t"][ent])
        fr = fund_by_coin.get(coin, np.zeros((0, 2)))
        bar_ts = t_e[:, None] + 3600.0 * np.arange(1, HORIZON + 1)[None, :]
        rc = np.cumsum(rate_at(fr, bar_ts), axis=1)
        # real paths (long convention)
        pidx = ent[:, None] + np.arange(1, HORIZON + 1)[None, :]
        entry = b["c"][ent][:, None]
        H_, L_, C_ = b["h"][pidx], b["l"][pidx], b["c"][pidx]
        fav = (H_ - entry) / entry
        adv = (entry - L_) / entry
        close = C_ / entry - 1.0
        real = both_sides(fav, adv, close, sf, atr_f, rc)
        sp = synth_paths_pit(b, ent, K_CTRL + 1)
        if sp is None:
            continue
        rep = lambda v: np.repeat(v, K_CTRL + 1)
        syn = both_sides(sp[0], sp[1], sp[2], rep(sf), rep(atr_f), np.repeat(rc, K_CTRL + 1, axis=0))
        idxm = np.arange(len(ent) * (K_CTRL + 1)).reshape(len(ent), K_CTRL + 1)

        # features per moment (unsigned)
        bpos = np.searchsorted(buq, uq)
        clr = np.concatenate(([np.nan], np.log(dc[1:] / dc[:-1])))
        vmed = np.full(n, np.nan)
        vv = np.asarray(vol, float)
        for e in ent:                      # trailing 480 closed bars median volume
            lo = max(0, e - 480)
            if e - lo >= 100:
                vmed[e] = np.median(vv[lo:e])
        ret1 = np.concatenate(([0.0], b["c"][1:] / b["c"][:-1] - 1.0))
        feats = []
        for k_i, e in enumerate(ent):
            d = dix[e]
            px = b["c"][e]
            sfv, af = sf[k_i], atr_f[k_i]
            s20 = dc[d - 20:d].mean()
            s50 = dc[d - 50:d].mean()
            rl = room_atr(sh, True, px * (1 + sfv), af * px, d)
            rs = room_atr(sl, False, px * (1 - sfv), af * px, d)
            fp = frate = np.nan
            hot = np.nan
            if len(fr):
                i = np.searchsorted(fr[:, 0], t_e[k_i]) - 1
                if i >= 200:
                    fp = float((fr[:i + 1, 1] < fr[i, 1]).mean())
                    frate = float(fr[i, 1])
                    p80 = xs_p80.get(int(fr[i, 0] // 3600))
                    if p80 is not None:
                        hot = 1.0 if frate > p80 else 0.0
            bt = br = np.nan
            if d - 60 >= 1:
                x = blr[bpos[d - 60:d]]
                y = clr[d - 60:d]
                g = np.isfinite(x) & np.isfinite(y)
                if g.sum() >= 40 and x[g].var() > 0:
                    bt = float(np.cov(x[g], y[g])[0, 1] / x[g].var())
                    br = float(np.corrcoef(x[g], y[g])[0, 1] ** 2)
            # waking_24h: any bar in [e-24, e-1] with ret >= 0.5*daily em AND vol >= 2.5*vmed(at e)
            wake = np.nan
            if np.isfinite(vmed[e]) and vmed[e] > 0 and np.isfinite(em_h[e]):
                w = ret1[e - 24:e] >= 0.5 * em_h[e]
                w &= vv[e - 24:e] >= 2.5 * vmed[e]
                wake = 1.0 if w.any() else 0.0
            # btc shock in prior 24 BTC bars (align by timestamp)
            bi = np.searchsorted(btc_t, b["t"][e])
            shock = np.nan
            if bi >= 25:
                shock = 1.0 if (cs[bi] - cs[bi - 24]) > 0 else 0.0
            vr = xs_rank.get(int(uq[d]), {}).get(coin, np.nan)
            hour_b = float(int(datetime.fromtimestamp(t_e[k_i], tz=timezone.utc).hour) // 6)
            r7 = float(dc[d - 1] / dc[d - 8] - 1.0) if d >= 9 else np.nan
            feats.append((af / em_h[e], af, sfv / af, float(np.sign(s20 - s50)), rl, rs, r7, hour_b,
                          bt, br, oi_chg_at(oi.get(coin), t_e[k_i]), fp, frate, hot, wake, shock, vr))
        M["feats"].extend(feats)
        for tag in ("L", "S"):
            M["%s_real" % tag].append(np.stack([real[(tag, a_)] for a_ in ARMS], axis=1))
            smat = np.stack([syn[(tag, a_)] for a_ in ARMS], axis=1)
            M["%s_ctrl" % tag].append(smat[idxm[:, :K_CTRL].ravel()].reshape(len(ent), K_CTRL, 2).mean(axis=1))
            M["%s_null" % tag].append(smat[idxm[:, K_CTRL]])
        M["coin"].extend([coin] * len(ent))
        M["daykey"].extend([int(uq[dix[e]]) for e in ent])
        M["t"].extend(t_e.tolist())
        M["sf"].extend(sf.tolist())
        M["disc"].extend([(coin in ORIG17) or (int(uq[dix[e]]) < BOUNDARY_DAYKEY) for e in ent])
        # day-level table rows (for day-shift placebos in the fit)
        fi = np.searchsorted(day, uq, side="left")
        for d in range(MIN_DAYIDX, len(uq)):
            if not (np.isfinite(em_d[d]) and np.isfinite(atr_d[d]) and atr_d[d] > 0):
                continue
            FD["rows"].append((atr_d[d] / em_d[d], atr_d[d], K_STOP * em_d[d] / atr_d[d],
                               float(np.sign(dc[d - 20:d].mean() - dc[d - 50:d].mean())),
                               float(dc[d - 1] / dc[d - 8] - 1.0) if d >= 9 else np.nan,
                               xs_rank.get(int(uq[d]), {}).get(coin, np.nan)))
            FD["coin"].append(coin)
            FD["daykey"].append(int(uq[d]))
        done += 1
        if done % 20 == 0:
            print("  %d coins, %d moments" % (done, len(M["coin"])))
    c.close()
    n_m = len(M["coin"])
    if done < 50 or n_m < 5000:
        raise SystemExit("HALT: only %d coins / %d moments -- the map must not reach the fit." % (done, n_m))
    disc = np.asarray(M["disc"], bool)
    feats = np.asarray(M["feats"], float)
    keyarr = {"coins": np.asarray(M["coin"]), "daykey": np.asarray(M["daykey"], np.int64),
              "t": np.asarray(M["t"], float), "sf": np.asarray(M["sf"], float)}
    outs = {k: np.concatenate(M[k], axis=0) for k in
            ("L_real", "S_real", "L_ctrl", "S_ctrl", "L_null", "S_null")}
    for k, v in outs.items():
        if not np.isfinite(v).all():
            raise SystemExit("HALT: non-finite outcomes in %s" % k)
    fday = {"fday": np.asarray(FD["rows"], float), "fday_coin": np.asarray(FD["coin"]),
            "fday_daykey": np.asarray(FD["daykey"], np.int64)}
    # DISCOVERY file: all features/keys, outcomes for discovery moments only
    np.savez_compressed(OUT_DISC, feats=feats[disc], **{k: v[disc] for k, v in keyarr.items()},
                        **{k: v[disc] for k, v in outs.items()}, **fday,
                        arms=np.asarray(ARMS), featnames=np.asarray(FEATS))
    # CONFIRMATION file: sealed; the fit must not open it before the condition freeze
    np.savez_compressed(OUT_CONF, feats=feats[~disc], **{k: v[~disc] for k, v in keyarr.items()},
                        **{k: v[~disc] for k, v in outs.items()},
                        arms=np.asarray(ARMS), featnames=np.asarray(FEATS))
    cov = {FEATS[i]: float(np.isfinite(feats[:, i]).mean()) for i in range(len(FEATS))}
    meta = {"source_snapshot": snap, "coins": done, "moments": n_m,
            "discovery_moments": int(disc.sum()), "confirmation_moments": int((~disc).sum()),
            "coverage": cov, "filters": FILTERS,
            "filters_hash": hashlib.sha256(json.dumps(FILTERS, sort_keys=True).encode()).hexdigest()[:8],
            "notes": "moment unit; shared-path both sides; point-in-time control pools; boundary 20693"}
    io.open(META, "w", encoding="utf-8").write(json.dumps(meta, indent=1, default=float))
    print("coins %d moments %d (disc %d / conf %d SEALED)" % (done, n_m, disc.sum(), (~disc).sum()))
    print("coverage:", {k: round(v, 2) for k, v in cov.items()})
    print("wrote m28_map_discovery.npz + m28_map_confirmation_SEALED.npz + meta (filters %s)"
          % meta["filters_hash"])


if __name__ == "__main__":
    main()
