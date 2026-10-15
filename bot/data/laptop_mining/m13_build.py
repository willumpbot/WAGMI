"""M13 stage 1 -- per-entry POINT-IN-TIME features + outcomes under 7 exit arms. EXPLORATORY.

Owner priority (SERVER_REPLY 01:30Z). Design: M13_CONDITIONAL_EXIT_DESIGN.md + AMENDMENT 1 (red-team
panel, adopted before this first run). Stage 2 (tree / LOCO / day-shift placebo / null gate) is
m13_fit.py, which reads the table this file writes and never re-simulates.

What Amendment 1 changed in THIS file vs the first draft:
  * control is PER ENTRY: K=16 independent martingale draws per entry, mean per arm; +1 extra
    independent draw stored as `nullreal` so the whole fit pipeline can be negative-tested on
    outcomes with zero structure by construction;
  * fees charged on actual leg notionals (entry + each exit leg), identical model on control paths;
  * funding carry accrued per leg holding period from the coin's own settled rates (backward asof,
    <= 2h staleness, else that bar contributes 0; coverage reported) on real AND control paths;
  * a DAY-LEVEL feature table is dumped per coin so stage 2 can run the circular day-shift placebo
    through the identical pipeline (row permutation was red-teamed out: it destroys feature
    autocorrelation and certifies regime coincidence);
  * entry spacing 24 bars (was 12) to cut 72h-window overlap;
  * arm resolution vectorised (same semantics as the scalar draft: stop checked before the
    favourable trigger within a bar; trail live from the bar AFTER arming; trail hit on the bar
    LOW (adv >= -give), matching exit_style.py; trail floored at the original stop).

Point-in-time discipline (all closed before this run; see design section 3 + Amendment 1):
  em lagged one closed day (M12's same-day leak closed; live-consistent). ATR14 = 14 closed daily TRs
  before the entry day -- ONE array feeds both the features and the trail widths, and the control uses
  the identical widths. SMA20/50, ret7, beta on closed days. Swings need their 3-day confirmation
  closed before entry (swing day j counts iff j+3 <= D-1). Funding percentile strictly before entry,
  >= 200 prior settlements else NaN. oi_chg backward-asof both endpoints (6h/30h staleness) --
  31 syms / ~130d coverage, reported, never imputed.

Stated limits: fills AT the trigger level (optimistic, flatters frequent-exit arms); control bar-shape
pool is the coin's FULL history (a null pricing model, not point-in-time); entries require 72h of
forward bars (terminal-delisting paths excluded; arms share identical entries so the ranking is
internally consistent); excluded-entry fraction reported.
"""
import gzip
import io
import json
import math
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

import panel_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
OI_PATH = os.path.join(HERE, "server_exports", "funding_oi_history.jsonl.gz")
OUT = os.path.join(HERE, "m13_table.npz")
META = os.path.join(HERE, "m13_build_meta.json")

EPS = 1e-8
FEE_HALF = 0.00045          # 4.5 bps per side, charged on each leg's actual notional
K_STOP = 1.65
HORIZON = 72
ENTRIES = 250
SPACING = 24                # min bars between entries within a coin (Amendment 1)
ATR_N = 14
K_CTRL = 16                 # martingale draws per entry for the control
BIG = 10 ** 6
rng = np.random.default_rng(20261015)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]

ARMS = ("full_1R", "full_2R", "runner_0.75atr", "runner_1.00atr", "runner_1.50atr",
        "runner_1.00atr_72h", "trail_from_1R")
FEATS = ("atr_em", "atr_pct", "stop_atr", "trend", "room", "fund_pctl", "fund_cost",
         "btc_beta", "btc_r2", "hour_b", "ret7", "oi_chg")
# day-level table columns (unsigned where side-dependent; signed at lookup in stage 2)
DAYF = ("atr_em", "atr_pct", "stop_atr", "trend_raw", "room_long", "room_short",
        "fund_pctl", "fund_rate", "btc_beta", "btc_r2", "ret7_raw", "oi_chg")


def sd(xs):
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def daily(b):
    day = (b["t"] // 86400000).astype(np.int64)
    uq, fi = np.unique(day, return_index=True)
    ends = np.append(fi[1:], len(b["c"]))
    dh = np.array([b["h"][i:j].max() for i, j in zip(fi, ends)])
    dl = np.array([b["l"][i:j].min() for i, j in zip(fi, ends)])
    dc = np.array([b["c"][j - 1] for j in ends])
    return day, uq, dh, dl, dc


def em_pit(dc):
    """HAR em per day index from returns up to the PREVIOUS day only (Amendment 1 FATAL 3)."""
    rets = np.concatenate(([0.0], (dc[1:] / dc[:-1] - 1.0) * 100.0))
    em = np.full(len(dc), np.nan)
    for i in range(31, len(dc)):
        rv1 = abs(rets[i - 1])
        rv5 = sd(rets[i - 5:i])
        rv22 = sd(rets[i - 22:i])
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[i] = v / 100.0
    return em


def atr_pit(dh, dl, dc):
    """ATR14 fraction per day index from the 14 closed days BEFORE that day (one array for
    features AND trail widths -- Amendment 1 FATAL 4)."""
    tr = np.maximum(dh[1:] - dl[1:], np.maximum(np.abs(dh[1:] - dc[:-1]), np.abs(dl[1:] - dc[:-1])))
    atr = np.full(len(dc), np.nan)
    for i in range(ATR_N + 1, len(dc)):
        atr[i] = np.mean(tr[i - ATR_N - 1:i - 1]) / dc[i - 1]
    return atr


def swings(dh, dl):
    """3-day fractals as (confirm_day, level); known at entry day D iff confirm_day <= D-1."""
    sh, sl = [], []
    for j in range(3, len(dh) - 3):
        if dh[j] == dh[j - 3:j + 4].max():
            sh.append((j + 3, dh[j]))
        if dl[j] == dl[j - 3:j + 4].min():
            sl.append((j + 3, dl[j]))
    return sh, sl


def room_atr(sw, up, px_1r, atr_abs, d):
    lv = [p for cj, p in sw if cj <= d - 1 and ((up and p > px_1r) or (not up and p < px_1r))]
    if not lv or not np.isfinite(atr_abs) or atr_abs <= 0:
        return 10.0
    return min(10.0, abs(min(lv, key=lambda p: abs(p - px_1r)) - px_1r) / atr_abs)


def load_oi():
    oi = {}
    try:
        with gzip.open(OI_PATH, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = datetime.fromisoformat(r["timestamp"].replace("Z", "")).replace(
                    tzinfo=timezone.utc).timestamp()
                oi.setdefault(r["symbol"], []).append((t, float(r["open_interest"] or 0)))
    except OSError:
        return {}
    return {k: np.asarray(sorted(v)) for k, v in oi.items()}


def oi_chg_at(arr, t_e):
    if arr is None or not len(arr):
        return np.nan
    i = np.searchsorted(arr[:, 0], t_e) - 1
    if i < 0 or t_e - arr[i, 0] > 6 * 3600:
        return np.nan
    j = np.searchsorted(arr[:, 0], arr[i, 0] - 24 * 3600) - 1
    if j < 0 or arr[i, 0] - arr[j, 0] > 30 * 3600 or arr[j, 1] <= 0:
        return np.nan
    return arr[i, 1] / arr[j, 1] - 1.0


def first_true(m):
    """(N,H) bool -> first True col per row, BIG if none."""
    has = m.any(axis=1)
    idx = m.argmax(axis=1)
    return np.where(has, idx, BIG)


def resolve_vec(fav, adv, close_ret, sf, atr_f):
    """Vectorised arm resolution. fav/adv/close_ret: (N,H) side-adjusted excursion fractions.
    sf, atr_f: (N,). Returns {arm: (ret_gross, a, x, banked_flag)} with a=arm bar (BIG if never),
    x=exit bar index (time exits use lim-1), ret_gross = side-adjusted fraction before fees/carry."""
    N, H = fav.shape
    cols = np.arange(H)[None, :]
    runmax = np.maximum.accumulate(fav, axis=1)
    rm_shift = np.concatenate((np.full((N, 1), -np.inf), runmax[:, :-1]), axis=1)
    out = {}
    sfc = sf[:, None]
    for name, mult, lim in (("full_1R", 1.0, 48), ("full_2R", 2.0, 48)):
        sb = first_true((adv >= sfc) & (cols < lim))
        tb = first_true((fav >= mult * sfc) & (cols < lim))
        stopped = (sb <= tb) & (sb < BIG)
        hit_t = (tb < BIG) & ~stopped
        ret = np.where(stopped, -sf, np.where(hit_t, mult * sf, close_ret[:, lim - 1]))
        x = np.where(stopped, sb, np.where(hit_t, tb, lim - 1)).astype(np.int64)
        out[name] = (ret, np.full(N, BIG, dtype=np.int64), x, np.zeros(N, bool))
    for name, w_mult, bank, lim in (("runner_0.75atr", 0.75, True, 48),
                                    ("runner_1.00atr", 1.00, True, 48),
                                    ("runner_1.50atr", 1.50, True, 48),
                                    ("runner_1.00atr_72h", 1.00, True, 72),
                                    ("trail_from_1R", 1.00, False, 48)):
        w = (w_mult * atr_f)[:, None]
        sb = first_true((adv >= sfc) & (cols < lim))
        ab = first_true((fav >= sfc) & (cols < lim))
        pre_stop = (sb <= ab) & (sb < BIG)          # stop first on the tie (conservative)
        armed = (~pre_stop) & (ab < BIG)
        give = np.maximum(rm_shift - w, -sfc)       # trail from best through the PREVIOUS bar
        hit = (adv >= -give) & (cols > ab[:, None]) & (cols < lim)
        xb = first_true(hit)
        got = armed & (xb < BIG)
        rem = np.where(got, np.take_along_axis(give, np.minimum(xb, H - 1)[:, None], 1)[:, 0],
                       close_ret[:, lim - 1])
        full_ret = np.where(pre_stop, -sf, close_ret[:, lim - 1])
        armed_ret = (0.5 * sf + 0.5 * rem) if bank else rem
        ret = np.where(armed, armed_ret, full_ret)
        x = np.where(pre_stop, sb, np.where(got, xb, lim - 1)).astype(np.int64)
        a = np.where(armed, ab, BIG).astype(np.int64)
        out[name] = (ret, a, x, np.full(N, bank, bool) & armed)
    return out


def net_outcomes(res, sf, side, rate_cum):
    """Apply leg fees + funding carry. res: resolve_vec output. rate_cum: (N,H) cumulative
    side-UNSIGNED funding rate (sum of settled hourly rates over bars 1..j+1).
    Returns {arm: net_frac}. Fee: FEE_HALF on entry notional 1.0 plus each exit leg's notional
    (1 + side*leg_ret). Carry: side * [full rate-sum to the bank bar + half after] (bank arms)."""
    out = {}
    N = len(sf)
    rows = np.arange(N)
    for arm, (ret, a, x, banked) in res.items():
        a_c = np.minimum(a, x)                       # bank bar (<= exit bar when armed)
        cum_x = rate_cum[rows, x]
        cum_a = rate_cum[rows, np.minimum(a_c, rate_cum.shape[1] - 1)]
        carry = np.where(banked, side * (cum_a + 0.5 * (cum_x - cum_a)), side * cum_x)
        # legs: banked -> 0.5 @ +sf and 0.5 @ rem (rem = 2*ret - sf); else 1.0 @ ret
        rem = 2.0 * ret - sf
        exit_notional = np.where(banked,
                                 0.5 * (1 + side * sf) + 0.5 * (1 + side * rem),
                                 1 + side * ret)
        fee = FEE_HALF * (1.0 + exit_notional)
        out[arm] = ret - fee - carry
    return out


def synth_paths(b, ent, side, k):
    """k independent martingale path sets; returns (fav, adv, close) each (len(ent)*k, HORIZON)."""
    entry = np.repeat(b["c"][ent], k)
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
    lr, up, dn = lr[g], np.maximum(up[g], 0.0), np.maximum(dn[g], 0.0)
    if len(lr) < 200:
        return None
    draw = rng.integers(0, len(lr), size=(len(entry), HORIZON))
    step = np.exp(lr[draw]) / float(np.mean(np.exp(lr)))
    C = entry[:, None] * np.cumprod(step, axis=1)
    prev = np.concatenate((entry[:, None], C[:, :-1]), axis=1)
    H = np.maximum(prev, C) * (1.0 + up[draw])
    L = np.minimum(prev, C) * (1.0 - dn[draw])
    s = np.repeat(side, k)[:, None]
    fav = np.where(s > 0, (H - entry[:, None]) / entry[:, None], (entry[:, None] - L) / entry[:, None])
    adv = np.where(s > 0, (entry[:, None] - L) / entry[:, None], (H - entry[:, None]) / entry[:, None])
    return fav, adv, s * (C / entry[:, None] - 1.0)


def real_paths(b, ent, side):
    pidx = ent[:, None] + np.arange(1, HORIZON + 1)[None, :]
    entry = b["c"][ent][:, None]
    H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
    s = side[:, None]
    fav = np.where(s > 0, (H - entry) / entry, (entry - L) / entry)
    adv = np.where(s > 0, (entry - L) / entry, (H - entry) / entry)
    return fav, adv, side[:, None] * (C / entry - 1.0) * 1.0


def pick_entries(ok):
    cand = rng.permutation(ok)
    chosen, taken = [], np.zeros(0, dtype=np.int64)
    for i in cand:
        if len(chosen) >= ENTRIES:
            break
        if len(taken) and np.abs(taken - i).min() < SPACING:
            continue
        chosen.append(i)
        taken = np.append(taken, i)
    return np.asarray(sorted(chosen), dtype=np.int64)


def fund_series(c, coin):
    fr = c.execute("SELECT t, rate FROM funding_hist WHERE coin=? ORDER BY t", (coin,)).fetchall()
    fr = np.asarray(fr, float) if fr else np.zeros((0, 2))
    if len(fr) and fr[:, 0].max() > 1e12:
        fr[:, 0] /= 1000.0
    return fr


def rate_at(fr, ts):
    """Settled hourly rate at timestamps ts (any shape); 0 where stale (>2h) or absent."""
    if not len(fr):
        return np.zeros_like(ts, dtype=float)
    flat = ts.ravel()
    i = np.searchsorted(fr[:, 0], flat) - 1
    ok = (i >= 0) & (flat - fr[np.maximum(i, 0), 0] <= 2 * 3600)
    r = np.where(ok, fr[np.maximum(i, 0), 1], 0.0)
    return r.reshape(ts.shape)


def main():
    print("M13 stage 1 (Amendment 1) -- building the feature/outcome table. EXPLORATORY.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    snap = panel_snapshot.stamp(c)
    print("SOURCE SNAPSHOT: %s" % panel_snapshot.describe(snap))

    btc = np.asarray(c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin='BTC' ORDER BY t").fetchall(), float)
    bb = {"t": btc[:, 0], "h": btc[:, 1], "l": btc[:, 2], "c": btc[:, 3]}
    _, buq, _, _, bdc = daily(bb)
    blr = np.concatenate(([np.nan], np.log(bdc[1:] / bdc[:-1])))

    oi = load_oi()
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]

    E = {"feats": [], "real": [], "ctrl": [], "null": [], "coin": [], "daykey": [], "side": [],
         "sf": [], "t": [], "hour": []}
    FD = {"rows": [], "coin": [], "daykey": []}
    oi_cov = fund_cov = 0
    carry_abs = []
    done = 0
    med_rates = []
    for coin in coins:
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < HORIZON + 900:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        if len(dc) < 70:
            continue
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        sh, sl = swings(dh, dl)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        fr = fund_series(c, coin)
        if len(fr) >= 10:
            med_rates.append(float(np.median(np.abs(fr[:, 1]))))
        clr = np.concatenate(([np.nan], np.log(dc[1:] / dc[:-1])))
        bpos = np.searchsorted(buq, uq)

        def day_feats(d, t0, px):
            """Features at (day index d, timestamp t0, reference price px). Unsigned where
            side-dependent. Returns None if em/atr not finite."""
            if not (np.isfinite(em_d[d]) and np.isfinite(atr_d[d]) and atr_d[d] > 0):
                return None
            sf_ = K_STOP * em_d[d]
            atr_abs = atr_d[d] * px
            rl = room_atr(sh, True, px * (1 + sf_), atr_abs, d)
            rs = room_atr(sl, False, px * (1 - sf_), atr_abs, d)
            s20 = dc[d - 20:d].mean()
            s50 = dc[d - 50:d].mean()
            fp = fr_now = np.nan
            if len(fr):
                i = np.searchsorted(fr[:, 0], t0) - 1
                if i >= 200:
                    fp = float((fr[:i + 1, 1] < fr[i, 1]).mean())
                    fr_now = float(fr[i, 1])
            bt = br = np.nan
            if d - 60 >= 1:
                x = blr[bpos[d - 60:d]]
                y = clr[d - 60:d]
                g = np.isfinite(x) & np.isfinite(y)
                if g.sum() >= 40:
                    x, y = x[g], y[g]
                    if x.var() > 0:
                        bt = float(np.cov(x, y)[0, 1] / x.var())
                        br = float(np.corrcoef(x, y)[0, 1] ** 2)
            r7 = float(dc[d - 1] / dc[d - 8] - 1.0) if d >= 9 else np.nan
            return (atr_d[d] / em_d[d], atr_d[d], sf_ / atr_d[d], float(np.sign(s20 - s50)),
                    rl, rs, fp, fr_now, bt, br, r7, oi_chg_at(oi.get(coin), t0))

        # ---- day-level table for the placebo (day-start lookups) ----
        fi = np.searchsorted(day, uq, side="left")
        for d in range(61, len(uq)):
            t0 = b["t"][fi[d]] / 1000.0
            px = dc[d - 1]
            f = day_feats(d, t0, px)
            if f is None:
                continue
            FD["rows"].append(f)
            FD["coin"].append(coin)
            FD["daykey"].append(int(uq[d]))

        # ---- entries ----
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h[:n - HORIZON - 1]) & np.isfinite(atr_h[:n - HORIZON - 1])
                              & (atr_h[:n - HORIZON - 1] > 0))
        elig = elig[dix[elig] >= 61]
        if len(elig) < 80:
            continue
        ent = pick_entries(elig)
        if len(ent) < 50:
            continue
        side = np.where(rng.random(len(ent)) < 0.5, 1.0, -1.0)
        sf = K_STOP * em_h[ent]
        atr_f = atr_h[ent]
        t_e = np.where(b["t"][ent] > 1e12, b["t"][ent] / 1000.0, b["t"][ent])
        bar_ts = t_e[:, None] + 3600.0 * np.arange(1, HORIZON + 1)[None, :]
        rc = np.cumsum(rate_at(fr, bar_ts), axis=1)
        fund_cov += int((np.abs(rc[:, -1]) > 0).sum())

        fv, av, cl = real_paths(b, ent, side)
        res_r = resolve_vec(fv, av, cl, sf, atr_f)
        net_r = net_outcomes(res_r, sf, side, rc)
        carry_abs.extend(np.abs(side * rc[np.arange(len(ent)), res_r["runner_1.00atr"][2]]).tolist())

        sp = synth_paths(b, ent, side, K_CTRL + 1)
        if sp is None:
            continue
        kN = len(ent) * (K_CTRL + 1)
        rep = lambda v: np.repeat(v, K_CTRL + 1)
        res_s = resolve_vec(sp[0], sp[1], sp[2], rep(sf), rep(atr_f))
        net_s = net_outcomes(res_s, rep(sf), rep(side), np.repeat(rc, K_CTRL + 1, axis=0))

        fe = []
        for k in range(len(ent)):
            e = ent[k]
            d = dix[e]
            f = day_feats(d, t_e[k], b["c"][e])    # entry-level: price/time of the entry itself
            s = side[k]
            room = f[4] if s > 0 else f[5]
            hour_b = float(int(datetime.fromtimestamp(t_e[k], tz=timezone.utc).hour) // 6)
            fe.append((f[0], f[1], f[2], f[3] * s, room, f[6], (s * f[7]) if np.isfinite(f[7]) else np.nan,
                       f[8], f[9], hour_b, f[10] * s if np.isfinite(f[10]) else np.nan, f[11]))
            if np.isfinite(f[11]):
                oi_cov += 1
        allidx = np.arange(len(ent) * (K_CTRL + 1)).reshape(len(ent), K_CTRL + 1)
        smat = np.stack([net_s[m] for m in ARMS], axis=1)      # (kN, 7)
        ctrl_mean = smat[allidx[:, :K_CTRL].ravel()].reshape(len(ent), K_CTRL, 7).mean(axis=1)
        nullreal = smat[allidx[:, K_CTRL]]
        E["feats"].extend(fe)
        E["real"].append(np.stack([net_r[m] for m in ARMS], axis=1))
        E["ctrl"].append(ctrl_mean)
        E["null"].append(nullreal)
        E["coin"].extend([coin] * len(ent))
        E["daykey"].extend([int(uq[dix[e]]) for e in ent])
        E["side"].extend(side.tolist())
        E["sf"].extend(sf.tolist())
        E["t"].extend(t_e.tolist())
        done += 1
        if done % 20 == 0:
            print("  %d coins, %d entries" % (done, len(E["coin"])))
    c.close()
    n_ent = len(E["coin"])
    if done < 50 or n_ent < 5000:
        raise SystemExit("HALT: only %d coins / %d entries built -- the table must not reach the fit."
                         % (done, n_ent))
    feats = np.asarray(E["feats"], float)
    for arr in ("real", "ctrl", "null"):
        E[arr] = np.concatenate(E[arr], axis=0)
        if not np.isfinite(E[arr]).all():
            raise SystemExit("HALT: non-finite outcomes in %s" % arr)
    np.savez_compressed(
        OUT, feats=feats, real=E["real"], ctrl=E["ctrl"], nullreal=E["null"],
        coins=np.asarray(E["coin"]), daykey=np.asarray(E["daykey"], np.int64),
        side=np.asarray(E["side"], float), sf=np.asarray(E["sf"], float),
        t=np.asarray(E["t"], float),
        fday=np.asarray(FD["rows"], float), fday_coin=np.asarray(FD["coin"]),
        fday_daykey=np.asarray(FD["daykey"], np.int64),
        arms=np.asarray(ARMS), featnames=np.asarray(FEATS), dayf=np.asarray(DAYF))
    meta = {"source_snapshot": snap, "coins": done, "entries": n_ent,
            "oi_coverage_frac": oi_cov / n_ent, "funding_any_frac": fund_cov / n_ent,
            "median_abs_hourly_rate": float(np.median(med_rates)) if med_rates else None,
            "median_abs_carry_frac_runner48": float(np.median(carry_abs)) if carry_abs else None,
            "k_ctrl": K_CTRL, "fee_half": FEE_HALF, "k_stop": K_STOP, "horizon": HORIZON,
            "spacing_bars": SPACING, "atr_n": ATR_N,
            "notes": "Amendment 1 build: per-entry K=16 control + nullreal draw; leg fees; funding "
                     "carry accrued; day-level feature table for the day-shift placebo; em lagged."}
    io.open(META, "w", encoding="utf-8").write(json.dumps(meta, indent=1, default=float))
    print("coins %d entries %d  oi cov %.1f%%  funding nonzero %.1f%%  median |carry48| %.2f bps"
          % (done, n_ent, 100 * meta["oi_coverage_frac"], 100 * meta["funding_any_frac"],
             1e4 * (meta["median_abs_carry_frac_runner48"] or 0)))
    print("wrote m13_table.npz + m13_build_meta.json")


if __name__ == "__main__":
    main()
