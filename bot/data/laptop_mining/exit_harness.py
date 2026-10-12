"""Mission X exit-simulation harness. Built to PREREG_MISSION_X_EXITS_2026-10-12.md (SHA-256 11349de3...).

Arm-agnostic: arm B (placebo, random entries) and arm A (real bot entries) both call
`simulate()` with a table of entries. Nothing in here knows which arm it is serving.

CONVENTIONS, all stated because each one is a place fake edge is manufactured:

  exp_move   HAR(1,5,22) on daily (high-low)/open, betas 0.35/0.35/0.30, intercept 0, smearing 1.0,
             log-linear: em% = exp(0.35*ln rv1 + 0.35*ln rv5 + 0.30*ln rv22). rv1 = previous
             complete UTC day's (h-l)/o in %, rv5/rv22 = means of the last 5/22 complete days.
             Daily bars are aggregated from the 1h files. Only days that CLOSED strictly before the
             entry bar are used -- no look-ahead.
             DEVIATION, see report: funding_stop.py applies those same betas to |daily close-to-close
             return %| / sd5 / sd22, not to (high-low)/open, and production scanner.py uses
             volatility_forecast.json y1_beta = [-0.3921, 0.0521, 0.2143, 0.5201] x smearing 1.7389.
             `EM_MODE` switches between the two input proxies for sensitivity.

  entry      at the CLOSE of the entry bar. The position is open for bars e+1 .. x.

  intrabar   ADVERSARIAL. Within one bar we cannot know whether the high or the low came first, so
             whenever stop and target are both inside the same bar the STOP is assumed to have
             filled first. A stop that gaps through fills at the bar OPEN (worse than the stop
             price); a target that gaps through fills at exactly the target (no gap bonus).
             Stop MODIFICATIONS that react to price (trail, breakeven) take effect from the NEXT
             bar, since the trigger is only known at that bar's close. A resting partial-take
             limit at 1R is pre-placed, so it fills intrabar at 1R.
             `OPTIMISTIC` flips the tie to target-first; used only as a positive control to
             quantify how much fake edge the optimistic convention invents.

  costs      fees 18 bps round trip = 2 legs x 9 bps of notional. The prereg flags that the brief
             said "9 bps round trip"; 18 is kept, so every net figure is 9 bps pessimistic if the
             brief meant 9 bps total. Partial exits pay 9 bps on each leg, which with proportional
             fees is the same 18 bps of entry notional.

  funding    realised, hourly, from crunch/panels.sqlite funding_hist(coin,t,rate,premium), summed
             over the actual hold and signed so PAYING funding REDUCES the return:
             funding_frac = -side * sum(rate). A missing hour is SOURCE-MISSING for that trade --
             never zero. Partial positions are charged notional-weighted funding.

  R          risk_frac = k * em / 100 (fraction of entry price). All P&L is expressed as a fraction
             of entry price divided by risk_frac.
             net_R = gross_R - fees_R + funding_R.

  max hold   96 hours for every cell. Entries are only sampled where a full 96-bar forward window
             exists, so no cell can win or lose by running out of data.
"""
import datetime
import glob
import math
import os
import sqlite3

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
H1 = os.path.join(ROOT, "history1h")
PANELS = os.path.join(ROOT, "crunch", "panels.sqlite")
LEDGER = os.path.join(ROOT, "server_exports", "trade_ledger.csv")
C5M = os.path.join(ROOT, "server_exports", "candles_5m")

HOUR_MS = 3_600_000
MAX_HOLD = 96
FEE_LEG = 0.0009                 # 9 bps per leg
HAR_BETA = (0.0, 0.35, 0.35, 0.30)
HAR_SMEAR = 1.0
EPS = 1e-9
MIN_EM_PCT = 0.10                # a coin forecast to range < 0.10%/day is stale, not tradeable
BONF_Z = 2.95                    # prereg section 4: two-sided 0.05/16
POWER_Z = 0.8416                 # 80% power

EM_MODE = "hl_open"              # "hl_open" (instructed primary) | "c2c" (funding_stop.py form)
OPTIMISTIC = False               # positive control only


# ---------------------------------------------------------------- price data
def symbols():
    return sorted(os.path.basename(p)[:-7] for p in glob.glob(os.path.join(H1, "*_1h.csv")))


def load_1h(sym):
    """Returns dict of int64 t_ms and float64 o,h,l,c,v arrays, oldest first."""
    d = pd.read_csv(os.path.join(H1, f"{sym}_1h.csv"))
    tcol = d.columns[0]           # the files ship 't_ms'; the brief said 't'
    d = d.rename(columns={tcol: "t"}).sort_values("t").reset_index(drop=True)
    return {k: (d[k].to_numpy(np.int64) if k == "t" else d[k].to_numpy(float))
            for k in ("t", "o", "h", "l", "c", "v")}


def _daily(bars):
    """UTC-day OHLC aggregated from 1h bars. Returns (day_key int, o, h, l, c, end_ms)."""
    day = bars["t"] // 86_400_000
    keys, first = np.unique(day, return_index=True)
    last = np.r_[first[1:], len(day)] - 1
    return dict(day=keys, o=bars["o"][first], h=np.maximum.reduceat(bars["h"], first),
                l=np.minimum.reduceat(bars["l"], first), c=bars["c"][last],
                end_ms=bars["t"][last] + HOUR_MS)


def exp_move_series(bars, mode=None):
    """exp_move in PERCENT for every 1h bar, using only daily bars that closed before that bar.

    NaN where fewer than 23 complete days are available or a vol input is non-positive.
    """
    mode = mode or EM_MODE
    d = _daily(bars)
    if mode == "hl_open":
        x = (d["h"] - d["l"]) / np.where(d["o"] > 0, d["o"], np.nan) * 100.0
        rv1 = x.copy()
        rv5 = pd.Series(x).rolling(5).mean().to_numpy()
        rv22 = pd.Series(x).rolling(22).mean().to_numpy()
    elif mode == "c2c":                      # exactly funding_stop.py's inputs
        r = np.r_[np.nan, np.diff(d["c"]) / d["c"][:-1] * 100.0]
        rv1 = np.abs(r)
        rv5 = pd.Series(r).rolling(5).std(ddof=1).to_numpy()
        rv22 = pd.Series(r).rolling(22).std(ddof=1).to_numpy()
    else:
        raise ValueError(mode)

    b = HAR_BETA
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (b[0] + b[1] * np.log(rv1 + EPS) + b[2] * np.log(rv5 + EPS)
             + b[3] * np.log(rv22 + EPS))
        em_day = np.exp(z) * HAR_SMEAR
    bad = ~np.isfinite(em_day) | (rv1 <= 0) | ~(rv5 > 0) | ~(rv22 > 0) | (em_day < MIN_EM_PCT)
    em_day = np.where(bad, np.nan, em_day)

    # a bar at time t may use day j only if that day CLOSED at or before t
    idx = np.searchsorted(d["end_ms"], bars["t"], side="right") - 1
    out = np.full(len(bars["t"]), np.nan)
    ok = idx >= 0
    out[ok] = em_day[idx[ok]]
    return out


# ---------------------------------------------------------------- funding
class FundingBook:
    """Hourly realised funding per coin, aligned to the 1h candle grid.

    rate[i] applies to the hour that STARTS at bars['t'][i]. valid[i] is False where funding_hist
    has no row for that hour -- SOURCE-MISSING, never zero.
    """

    def __init__(self, path=PANELS):
        self.con = sqlite3.connect(path)
        self._c = {}

    def coverage_table(self):
        q = "select coin, count(*) n, min(t) t0, max(t) t1 from funding_hist group by coin"
        return pd.read_sql(q, self.con)

    def get(self, sym, bars):
        if sym in self._c:
            return self._c[sym]
        q = "select t, rate from funding_hist where coin=? order by t"
        f = pd.read_sql(q, self.con, params=(sym,))
        rate = np.zeros(len(bars["t"]))
        valid = np.zeros(len(bars["t"]), bool)
        if len(f):
            fh = (f["t"].to_numpy(np.int64) // HOUR_MS) * HOUR_MS
            g = pd.DataFrame({"h": fh, "r": f["rate"].to_numpy(float)}).groupby("h")["r"].sum()
            pos = np.searchsorted(bars["t"], g.index.to_numpy())
            hit = (pos < len(bars["t"]))
            pos, vals = pos[hit], g.to_numpy()[hit]
            same = bars["t"][pos] == g.index.to_numpy()[hit]
            rate[pos[same]] = vals[same]
            valid[pos[same]] = True
        # cumulative, so a hold is two lookups
        self._c[sym] = (np.r_[0.0, np.cumsum(rate)], np.r_[0, np.cumsum(valid)])
        return self._c[sym]


# ---------------------------------------------------------------- cells
# (name, k_stop, target_in_R or None, mode)
CELLS = [
    ("c01_stop1_tgt2",      1.0, 2.0, "plain"),
    ("c02_stop1_tgt4",      1.0, 4.0, "plain"),
    ("c03_stop1_notgt",     1.0, None, "plain"),
    ("c04_stop2_tgt2",      2.0, 2.0, "plain"),
    ("c05_stop2_tgt4",      2.0, 4.0, "plain"),
    ("c06_stop2_notgt",     2.0, None, "plain"),
    ("c07_stop3_tgt2",      3.0, 2.0, "plain"),
    ("c08_stop3_tgt4",      3.0, 4.0, "plain"),
    ("c09_stop3_notgt",     3.0, None, "plain"),
    ("c10_stop4_tgt2",      4.0, 2.0, "plain"),
    ("c11_stop4_tgt4",      4.0, 4.0, "plain"),
    ("c12_stop4_notgt",     4.0, None, "plain"),
    ("c13_partial50_1R",    2.0, 4.0, "partial"),
    ("c14_trail_after_1R",  2.0, None, "trail"),
    ("c15_breakeven_1R",    2.0, None, "breakeven"),
    ("c16_time_48h",        2.0, None, "time48"),
]
CELL_NAMES = [c[0] for c in CELLS]


def _first_true(mask):
    """Index of the first True, or len(mask) if none."""
    i = int(np.argmax(mask))
    return i if mask[i] else len(mask)


def _run_cell(spec, side, p0, risk, em_frac, o, h, l, c, optimistic):
    """One cell on one forward window. Returns (gross_frac, exit_bar, legs, half_bar).

    gross_frac is P&L as a fraction of entry price (sign already applied).
    exit_bar is the 0-based offset into the window of the bar the position closed on.
    legs is total notional traded / entry notional (1 entry leg + exit legs).
    half_bar is the offset where the position halved (cell 13) else -1.
    """
    _, kst, tgt_r, mode = spec
    n = len(c)
    up = side > 0
    stop_px = p0 * (1 - risk) if up else p0 * (1 + risk)
    # adverse excursion / favourable excursion masks
    adv = (l <= stop_px) if up else (h >= stop_px)
    s_i = _first_true(adv)

    def fav_i(level_r):
        lv = p0 * (1 + level_r * risk) if up else p0 * (1 - level_r * risk)
        m = (h >= lv) if up else (l <= lv)
        return _first_true(m), lv

    def px_at_stop(i, sp):
        """Adversarial stop fill: gap through fills at the open."""
        return min(sp, o[i]) if up else max(sp, o[i])

    def sgn(exit_px):
        return (exit_px / p0 - 1.0) if up else (1.0 - exit_px / p0)

    horizon = n - 1
    if mode == "time48":
        horizon = min(47, n - 1)          # bars e+1..e+48 -> offsets 0..47

    if mode in ("plain", "time48"):
        t_i, lv = (n, None) if tgt_r is None else fav_i(tgt_r)
        s_ok = s_i <= horizon
        t_ok = t_i <= horizon
        if s_ok and t_ok:
            first_stop = (s_i < t_i) or (s_i == t_i and not optimistic)
        else:
            first_stop = s_ok
        if s_ok and first_stop:
            return sgn(px_at_stop(s_i, stop_px)), s_i, 2.0, -1
        if t_ok:
            return sgn(lv), t_i, 2.0, -1
        return sgn(c[horizon]), horizon, 2.0, -1

    if mode == "partial":
        p_i, p_lv = fav_i(1.0)
        t_i, t_lv = fav_i(tgt_r)
        # if the stop is in the same bar as 1R (or earlier), adversarially the stop went first
        if s_i <= horizon and ((s_i < p_i) or (s_i == p_i and not optimistic)):
            return sgn(px_at_stop(s_i, stop_px)), s_i, 2.0, -1
        if p_i > horizon:                                    # never reached 1R, never stopped
            return sgn(c[horizon]), horizon, 2.0, -1
        g = 0.5 * sgn(p_lv)                                  # half out at 1R
        # remainder: 4R or the original stop, searching from the partial bar onward
        s2 = s_i if s_i >= p_i else n
        if s2 <= horizon and ((s2 < t_i) or (s2 == t_i and not optimistic)):
            return g + 0.5 * sgn(px_at_stop(s2, stop_px)), s2, 2.0, p_i
        if t_i <= horizon:
            return g + 0.5 * sgn(t_lv), t_i, 2.0, p_i
        return g + 0.5 * sgn(c[horizon]), horizon, 2.0, p_i

    # reactive-stop modes: 1R trigger is only known at that bar's close, so the modified stop
    # is live from the NEXT bar. Walk forward.
    trig_i, trig_lv = fav_i(1.0)
    sp = stop_px
    armed = False
    peak = p0
    for i in range(horizon + 1):
        hit = (l[i] <= sp) if up else (h[i] >= sp)
        if hit:
            return sgn(px_at_stop(i, sp)), i, 2.0, -1
        if armed and mode == "trail":
            peak = max(peak, h[i]) if up else min(peak, l[i])
            sp = max(sp, peak * (1 - em_frac)) if up else min(sp, peak * (1 + em_frac))
        if not armed and i >= trig_i:
            armed = True
            peak = max(peak, h[i]) if up else min(peak, l[i])
            if mode == "breakeven":
                sp = p0
            else:
                sp = max(sp, peak * (1 - em_frac)) if up else min(sp, peak * (1 + em_frac))
    return sgn(c[horizon]), horizon, 2.0, -1


# ---------------------------------------------------------------- driver
def simulate(entries, fb=None, cells=CELLS, optimistic=None, progress=None, bars_by_sym=None):
    """entries: DataFrame with columns sym, bar (int index into that coin's 1h file), side (+1/-1).

    Optional column `risk_frac` overrides the k*em stop (arm A passes stop_initial this way; when
    present, k is ignored and every cell shares that risk). Returns a long DataFrame:
    sym, bar, side, day, em_pct, cell, risk_frac, gross_R, fees_R, funding_R, net_R, fund_ok,
    hold_h, exit_bar.
    """
    optimistic = OPTIMISTIC if optimistic is None else optimistic
    if bars_by_sym is None and fb is None:
        fb = FundingBook()
    out = []
    for si, (sym, grp) in enumerate(entries.groupby("sym", sort=True)):
        bars = bars_by_sym[sym] if bars_by_sym is not None else load_1h(sym)
        em = exp_move_series(bars)
        if fb is None:                       # synthetic control: no funding source at all
            fcum = np.zeros(len(bars["t"]) + 1)
            vcum = np.arange(len(bars["t"]) + 1)
        else:
            fcum, vcum = fb.get(sym, bars)
        o, h, l, c, t = bars["o"], bars["h"], bars["l"], bars["c"], bars["t"]
        for e, side, rf_over in zip(grp["bar"].to_numpy(int), grp["side"].to_numpy(int),
                                    (grp["risk_frac"].to_numpy(float) if "risk_frac" in grp
                                     else np.full(len(grp), np.nan))):
            em_pct = em[e]
            if not np.isfinite(em_pct):
                continue
            p0 = c[e]
            lo, hi = e + 1, min(e + MAX_HOLD, len(c) - 1)
            if hi < lo:
                continue
            wo, wh, wl, wc = o[lo:hi + 1], h[lo:hi + 1], l[lo:hi + 1], c[lo:hi + 1]
            em_frac = em_pct / 100.0
            day = int(t[e] // 86_400_000)
            for spec in cells:
                risk = rf_over if np.isfinite(rf_over) else spec[1] * em_frac
                if not (risk > 0):
                    continue
                g, xb, legs, hb = _run_cell(spec, side, p0, risk, em_frac, wo, wh, wl, wc,
                                            optimistic)
                a, b = lo, lo + xb                      # hours held: bars a..b inclusive
                if hb >= 0:                             # notional-weighted after the partial
                    m = lo + hb
                    f = (fcum[m + 1] - fcum[a]) + 0.5 * (fcum[b + 1] - fcum[m + 1])
                else:
                    f = fcum[b + 1] - fcum[a]
                fund_ok = (vcum[b + 1] - vcum[a]) == (b - a + 1)
                fee_frac = FEE_LEG * legs
                fR, feR = (-side * f) / risk, fee_frac / risk
                out.append((sym, e, side, day, em_pct, spec[0], risk, g / risk, feR, fR,
                            g / risk - feR + fR, bool(fund_ok), b - a + 1, xb))
        if progress and si % progress == 0:
            print(f"  ... {si} coins, {len(out)} rows", flush=True)
    return pd.DataFrame(out, columns=["sym", "bar", "side", "day", "em_pct", "cell", "risk_frac",
                                      "gross_R", "fees_R", "funding_R", "net_R", "fund_ok",
                                      "hold_h", "exit_bar"])


# ---------------------------------------------------------------- statistics
def day_block_stats(df, col, nrep=4000, seed=20261011):
    """Pooled and equal-weighted-by-day means with a day-block bootstrap CI and the MDE.

    Day blocks are the clustering unit (prereg section 4); the day-weighted figure governs.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for cell, g in df.groupby("cell", sort=True):
        y = g[col].to_numpy(float)
        d = g["day"].to_numpy()
        days, inv = np.unique(d, return_inverse=True)
        S = np.bincount(inv, weights=y, minlength=len(days))
        N = np.bincount(inv, minlength=len(days)).astype(float)
        dm = S / N
        pooled, dayw = y.mean(), dm.mean()
        idx = rng.integers(0, len(days), size=(nrep, len(days)))
        bs_day = dm[idx].mean(axis=1)
        bs_pool = S[idx].sum(axis=1) / N[idx].sum(axis=1)
        se_day = bs_day.std(ddof=1)
        se_pool = bs_pool.std(ddof=1)
        corr = (np.corrcoef(N, dm)[0, 1] if len(days) > 2 and N.std() > 0 and dm.std() > 0
                else np.nan)
        rows.append(dict(
            cell=cell, n=len(y), n_days=len(days),
            pooled=pooled, pooled_se=se_pool,
            dayw=dayw, dayw_se=se_day,
            ci_lo=np.percentile(bs_day, 2.5), ci_hi=np.percentile(bs_day, 97.5),
            z_dayw=dayw / se_day if se_day > 0 else np.nan,
            mde=(BONF_Z + POWER_Z) * se_day,
            corr_n_mean=corr,
            med=float(np.median(y)), p1=float(np.percentile(y, 1)),
            p99=float(np.percentile(y, 99))))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- arm B sampler
def ledger_mix(path=LEDGER):
    L = pd.read_csv(path)
    mix = L["symbol"].value_counts(normalize=True)
    long_share = float((L["side"].str.upper() == "LONG").mean())
    return mix, long_share, len(L)


def sample_entries(n, mix=None, long_share=0.5, seed=20261012, syms=None, bars_by_sym=None):
    """Random (coin, bar, side). Bars are uniform over every bar with a valid exp_move AND a full
    96-bar forward window, so no entry is selected on anything about its own outcome.
    """
    rng = np.random.default_rng(seed)
    if mix is None:
        syms = syms or (list(bars_by_sym) if bars_by_sym is not None else symbols())
        mix = pd.Series(1.0 / len(syms), index=syms)
    counts = np.floor(mix.to_numpy() * n).astype(int)
    counts[:max(0, n - counts.sum())] += 1
    rows = []
    for sym, k in zip(mix.index, counts):
        if k <= 0:
            continue
        bars = bars_by_sym[sym] if bars_by_sym is not None else load_1h(sym)
        em = exp_move_series(bars)
        ok = np.where(np.isfinite(em))[0]
        ok = ok[ok <= len(bars["t"]) - 1 - MAX_HOLD]
        if len(ok) == 0:
            print(f"  SOURCE-MISSING: {sym} has no eligible bar")
            continue
        rows.append(pd.DataFrame({"sym": sym, "bar": rng.choice(ok, size=k, replace=True)}))
    e = pd.concat(rows, ignore_index=True)
    nl = int(round(long_share * len(e)))
    side = np.r_[np.ones(nl, int), -np.ones(len(e) - nl, int)]
    rng.shuffle(side)
    e["side"] = side
    return e


def fmt(df, cols=None, f="{:.4f}"):
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda v: "nan" if not np.isfinite(v) else f.format(v))
    return d[cols].to_string(index=False) if cols else d.to_string(index=False)
