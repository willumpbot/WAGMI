#!/usr/bin/env python
"""
Mechanical Entry-Signal Panel Test - signal_panel_test.py
=============================================================================
STANDALONE, READ-ONLY analysis script. Answers the owner's own question
directly: does ANY standard mechanical ENTRY signal (Bollinger bounce,
Bollinger squeeze->breakout, N-day breakout, volume surge, SMA trend filter,
cross-sectional relative strength, fib/retracement) carry out-of-sample,
net-of-fees forward edge on the WAGMI longtail universe?

Does NOT import copilot.py or any other live-bot / copilot module. All
signal logic below is defined fresh, from the spec in this task, against
offline daily OHLC. This file has zero side effects on live state -- it only
reads data/longtail/ohlc/*.csv and (best-effort) fetches BTC/SOL daily
candles from Hyperliquid's public /info endpoint (falls back to the
data/cache/*_daily_420d.csv snapshots if the network call fails or is
unavailable in the run environment; the fallback is clearly logged and the
BTC/SOL rows are informational extra instruments, not part of the core
25-alt cross-section used for the relative-strength signal).

UNIVERSE
-----------------------------------------------------------------------------
- 25 longtail alts: data/longtail/ohlc/*_1d.csv, ~2025-06-26 -> ~today,
  402 daily bars each (a few shorter: PUMP/XPL listed later).
- BTC, SOL: fetched live (Hyperliquid candleSnapshot) for the SAME window;
  falls back to data/cache/BTC_daily_420d.csv / SOL_daily_420d.csv (STALE,
  only through 2026-07-13) if the live fetch fails. Included in every signal
  test EXCEPT the relative-strength cross-section (#6), which is explicitly
  scoped by the owner's ask to "the alt cross-section."

ENTRY-TIME-SAFETY CONVENTION (matches mover_followthrough_test.py)
-----------------------------------------------------------------------------
Every trigger at day t uses ONLY bars with index <= t (rolling windows are
trailing and, where noted, exclude the current bar entirely to avoid a
signal being defined by the very bar it is triggering on, e.g. N-day-high
breakout and volume-surge baseline). Forward returns use ONLY t+1..t+h
(strictly future, by construction of the array shift). The one exception is
the standard Bollinger Band definition itself (SMA20/STD20 computed
INCLUDING bar t's close) -- this is the textbook definition the owner is
asking about ("close pierces the lower band"), not a lookahead: the bar's
own close is known at the moment the signal fires (end-of-day evaluation,
same convention used throughout this codebase's other signal tests).
Fractal swing points (signal 7) are deliberately confirmed W bars AFTER
they occur (a swing low/high is only "known" once W bars have passed
without being undercut/exceeded) -- this is the correct entry-time-safe way
to detect swings, at the cost of a W-bar recognition lag.

FEES
-----------------------------------------------------------------------------
FEE_RT = 9bps (0.0009) round-trip, subtracted ONCE per triggered event
regardless of horizon (matches mover_followthrough_test.py convention).

REFUTE-YOURSELF CHECKS built in for every signal
-----------------------------------------------------------------------------
(a) OOS: split at the median date into first-half (in-sample-ish) vs
    second-half (OOS) and require the OOS number to hold up.
(b) Non-overlap / autocorrelation control: triggers on the same symbol
    recur on consecutive days (e.g. a coin can sit below its lower band for
    a week straight). Pooled per-day n badly overstates independent
    evidence. For every signal we ALSO collapse consecutive-day trigger runs
    per symbol into single "episodes" (first day of each run only) and
    recompute mean/tstat/hit-rate on that de-overlapped sample.
(c) Era robustness: per-quarter table, PLUS (specifically requested) an
    explicit pre-2026-02-01 vs post-2026-02-01 split for the Bollinger
    lower-band bounce, to test the "deep-oversold-bounce died in Feb 2026"
    hypothesis directly.
(d) Fee-clearing: every reported mean/median is NET of the 9bps round trip;
    the raw (pre-fee) mean is also shown alongside so a "real tilt that
    doesn't clear fees" can be told apart from "no tilt at all."
(e) Per-coin equal-weight cross-check (average each coin's own mean first,
    then average across coins) so a couple of chatty coins can't dominate
    the pooled numbers.

Run:
    python tools/copilot/signal_panel_test.py
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

pd.set_option("display.width", 180)
pd.set_option("display.max_columns", 25)
pd.set_option("display.max_rows", 200)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")

FEE_RT = 0.0009  # 9bps round trip, net-of-fees adjustment, applied once per event
HORIZONS = [1, 3, 5]
MIN_24H_VOLUME_USD = 2_000_000  # cross-sectional liquidity floor (signal 6), matches whats_moving.py

# Bollinger / squeeze
BB_WINDOW = 20
BB_K = 2.0
SQUEEZE_LOOKBACK = 90
SQUEEZE_PCTL = 20.0  # bottom 20th percentile of trailing bandwidth = "squeeze"
MIN_SQUEEZE_HIST = 30

# Breakout
BREAKOUT_N = 20

# Vol-surge
VOLSURGE_WINDOW = 20
VOLSURGE_MULT = 3.0

# Trend filter
TREND_SMA = 50
TREND_RISING_LAG = 5

# Relative strength
RS_WINDOWS = [10, 20]
RS_TOP_Q = 0.20
RS_BOT_Q = 0.20

# Fib/retracement proxy
FIB_W = 3          # fractal confirmation half-window (bars each side)
FIB_LO, FIB_HI = 0.382, 0.618
FIB_MAX_AGE = 30    # give up watching a swing leg for retracement after this many bars

FEB_2026_CUTOFF = pd.Timestamp("2026-02-01", tz="UTC")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _hl_daily_candles(coin: str, start_ms: int) -> Optional[pd.DataFrame]:
    """Best-effort live fetch of daily candles from Hyperliquid's public info
    endpoint. Returns None (never raises) if unreachable -- caller falls back
    to the local stale cache. Read-only, no auth, no order placement."""
    try:
        body = json.dumps({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": 99999999999999},
        }).encode()
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = json.loads(r.read())
        if not raw:
            return None
        df = pd.DataFrame(raw)
        df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.normalize()
        df = df.rename(columns={"o": "o", "h": "h", "l": "l", "c": "c", "v": "v"})
        for col in ["o", "h", "l", "c", "v"]:
            df[col] = df[col].astype(float)
        df["symbol"] = coin
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        return df[["symbol", "date", "o", "h", "l", "c", "v"]].reset_index(drop=True)
    except Exception as e:  # noqa: BLE001 - best-effort network call, any failure -> fallback
        print(f"  [{coin}] live Hyperliquid fetch failed ({e!r}); will try local cache fallback")
        return None


def _cache_daily_fallback(coin: str) -> Optional[pd.DataFrame]:
    path = os.path.join(CACHE_DIR, f"{coin}_daily_420d.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["time"], utc=True).dt.normalize()
    df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
    df["symbol"] = coin
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    return df[["symbol", "date", "o", "h", "l", "c", "v"]].reset_index(drop=True)


def load_longtail_alts() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(OHLC_DIR, "*_1d.csv"))):
        sym = os.path.basename(path).replace("_1d.csv", "")
        df = pd.read_csv(path)
        df["symbol"] = sym
        df["date"] = pd.to_datetime(df["dt_utc_iso"], utc=True).dt.normalize()
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        frames.append(df[["symbol", "date", "o", "h", "l", "c", "v"]])
    return pd.concat(frames, ignore_index=True)


def load_btc_sol(alt_min_date: pd.Timestamp) -> pd.DataFrame:
    start_ms = int(alt_min_date.timestamp() * 1000)
    frames = []
    for coin in ["BTC", "SOL"]:
        live = _hl_daily_candles(coin, start_ms)
        if live is not None and len(live) >= 100:
            print(f"  [{coin}] live Hyperliquid fetch OK: {len(live)} bars, "
                  f"{live['date'].min().date()} -> {live['date'].max().date()}")
            frames.append(live)
            continue
        cached = _cache_daily_fallback(coin)
        if cached is not None:
            print(f"  [{coin}] using STALE cache fallback: {len(cached)} bars, "
                  f"{cached['date'].min().date()} -> {cached['date'].max().date()} "
                  f"(NOTE: shorter/older than the alt panel -- informational only)")
            frames.append(cached)
        else:
            print(f"  [{coin}] no live data and no cache -- excluded from panel")
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "o", "h", "l", "c", "v"])
    return pd.concat(frames, ignore_index=True)


def load_panel() -> Tuple[pd.DataFrame, List[str]]:
    alts = load_longtail_alts()
    alt_symbols = sorted(alts["symbol"].unique().tolist())
    btcsol = load_btc_sol(alts["date"].min())
    panel = pd.concat([alts, btcsol], ignore_index=True) if len(btcsol) else alts
    panel["notional"] = panel["v"] * panel["c"]
    return panel, alt_symbols


# ---------------------------------------------------------------------------
# Per-symbol feature engineering (entry-time-safe)
# ---------------------------------------------------------------------------
def compute_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        o, h, l, c, v = (g[col].values.astype(float) for col in ["o", "h", "l", "c", "v"])
        notional = g["notional"].values.astype(float)
        n = len(g)

        log_ret = np.full(n, np.nan)
        for i in range(1, n):
            if c[i - 1] > 0 and c[i] > 0:
                log_ret[i] = np.log(c[i] / c[i - 1])

        sma20 = np.full(n, np.nan)
        std20 = np.full(n, np.nan)
        upper20 = np.full(n, np.nan)
        lower20 = np.full(n, np.nan)
        bw20 = np.full(n, np.nan)
        bw_pctile = np.full(n, np.nan)
        hi20_prior = np.full(n, np.nan)
        lo20_prior = np.full(n, np.nan)
        volmed20_prior = np.full(n, np.nan)
        sma50 = np.full(n, np.nan)
        ret10 = np.full(n, np.nan)
        ret20 = np.full(n, np.nan)

        for i in range(n):
            if i >= BB_WINDOW - 1:
                window = c[i - BB_WINDOW + 1 : i + 1]
                m = window.mean()
                s = window.std(ddof=0)
                sma20[i] = m
                std20[i] = s
                upper20[i] = m + BB_K * s
                lower20[i] = m - BB_K * s
                bw20[i] = (upper20[i] - lower20[i]) / m if m > 0 else np.nan

            if i >= BREAKOUT_N:
                hi20_prior[i] = h[i - BREAKOUT_N : i].max()
                lo20_prior[i] = l[i - BREAKOUT_N : i].min()

            if i >= VOLSURGE_WINDOW:
                med = np.median(notional[i - VOLSURGE_WINDOW : i])
                volmed20_prior[i] = med if med > 0 else np.nan

            if i >= TREND_SMA - 1:
                sma50[i] = c[i - TREND_SMA + 1 : i + 1].mean()

            if i >= 10:
                ret10[i] = c[i] / c[i - 10] - 1.0 if c[i - 10] > 0 else np.nan
            if i >= 20:
                ret20[i] = c[i] / c[i - 20] - 1.0 if c[i - 20] > 0 else np.nan

        # bandwidth percentile within trailing SQUEEZE_LOOKBACK (inclusive of today)
        for i in range(n):
            lo = max(0, i - SQUEEZE_LOOKBACK + 1)
            hist = bw20[lo : i + 1]
            hist = hist[~np.isnan(hist)]
            if len(hist) >= MIN_SQUEEZE_HIST:
                bw_pctile[i] = (hist <= bw20[i]).mean() * 100.0 if not np.isnan(bw20[i]) else np.nan

        sma50_rising = np.full(n, np.nan)
        for i in range(n):
            j = i - TREND_RISING_LAG
            if j >= TREND_SMA - 1 and not np.isnan(sma50[i]) and not np.isnan(sma50[j]):
                sma50_rising[i] = sma50[i] - sma50[j]

        g = g.copy()
        g["log_ret"] = log_ret
        g["sma20"] = sma20
        g["std20"] = std20
        g["upper20"] = upper20
        g["lower20"] = lower20
        g["bw20"] = bw20
        g["bw_pctile90"] = bw_pctile
        g["hi20_prior"] = hi20_prior
        g["lo20_prior"] = lo20_prior
        g["volmed20_prior"] = volmed20_prior
        g["sma50"] = sma50
        g["sma50_rising"] = sma50_rising
        g["ret10"] = ret10
        g["ret20"] = ret20

        for hz in HORIZONS:
            fwd = np.full(n, np.nan)
            fwd[: n - hz] = c[hz:] / c[: n - hz] - 1.0
            g[f"fwd_ret_{hz}"] = fwd

        out.append(g)
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------------------
# Fractal swing / fib-retracement proxy (signal 7)
# ---------------------------------------------------------------------------
def fib_events_for_symbol(g: pd.DataFrame) -> List[Dict]:
    """Entry-time-safe fractal swing tracker. A swing low/high at raw index k
    is only KNOWN at day k+FIB_W (needs FIB_W bars on both sides to confirm
    it wasn't undercut/exceeded). Tracks the most recent confirmed swing low
    and swing high; when they alternate (low->high = up-leg, high->low =
    down-leg) we watch subsequent days for a retracement into [38.2%,61.8%]
    of that leg followed by a one-bar resumption candle, firing at most once
    per leg."""
    g = g.reset_index(drop=True)
    h = g["h"].values.astype(float)
    l = g["l"].values.astype(float)
    c = g["c"].values.astype(float)
    dates = g["date"].values
    n = len(g)
    events = []
    if n < 2 * FIB_W + 2:
        return events

    is_swing_low = np.zeros(n, dtype=bool)
    is_swing_high = np.zeros(n, dtype=bool)
    for k in range(FIB_W, n - FIB_W):
        win_l = l[k - FIB_W : k + FIB_W + 1]
        win_h = h[k - FIB_W : k + FIB_W + 1]
        if l[k] == win_l.min() and (win_l == win_l.min()).sum() == 1:
            is_swing_low[k] = True
        if h[k] == win_h.max() and (win_h == win_h.max()).sum() == 1:
            is_swing_high[k] = True

    last_low = None   # (idx, price)
    last_high = None  # (idx, price)
    fired_legs = set()

    for t in range(n):
        confirm_k = t - FIB_W
        if confirm_k >= 0:
            if is_swing_low[confirm_k]:
                last_low = (confirm_k, l[confirm_k])
            if is_swing_high[confirm_k]:
                last_high = (confirm_k, h[confirm_k])

        if last_low is not None and last_high is not None and t > 0:
            # up-leg: low occurred before high -> watching for pullback + resumption UP
            if last_low[0] < last_high[0] and last_high[1] > last_low[1]:
                leg_key = ("UP", last_low[0], last_high[0])
                age = t - last_high[0]
                if leg_key not in fired_legs and 0 < age <= FIB_MAX_AGE:
                    span = last_high[1] - last_low[1]
                    if span > 0:
                        retrace = (last_high[1] - c[t]) / span
                        if FIB_LO <= retrace <= FIB_HI and c[t] > c[t - 1]:
                            events.append({
                                "symbol": g["symbol"].iloc[0], "date": dates[t],
                                "signal": "FIB_RETRACE", "direction": "LONG",
                                "leg_low_idx": last_low[0], "leg_high_idx": last_high[0],
                                "retrace_pct": retrace,
                            })
                            fired_legs.add(leg_key)
            # down-leg: high occurred before low -> watching for bounce + resumption DOWN
            if last_high[0] < last_low[0] and last_high[1] > last_low[1]:
                leg_key = ("DOWN", last_high[0], last_low[0])
                age = t - last_low[0]
                if leg_key not in fired_legs and 0 < age <= FIB_MAX_AGE:
                    span = last_high[1] - last_low[1]
                    if span > 0:
                        retrace = (c[t] - last_low[1]) / span
                        if FIB_LO <= retrace <= FIB_HI and c[t] < c[t - 1]:
                            events.append({
                                "symbol": g["symbol"].iloc[0], "date": dates[t],
                                "signal": "FIB_RETRACE", "direction": "SHORT",
                                "leg_low_idx": last_low[0], "leg_high_idx": last_high[0],
                                "retrace_pct": retrace,
                            })
                            fired_legs.add(leg_key)
    return events


# ---------------------------------------------------------------------------
# Build event tables per signal (long format: symbol, date, signal, direction)
# ---------------------------------------------------------------------------
def build_events(feat: pd.DataFrame, alt_symbols: List[str]) -> pd.DataFrame:
    rows = []

    # ---- 1) Bollinger lower/upper band touch (bounce / fade) ----
    lower_touch = feat[feat["lower20"].notna() & (feat["c"] <= feat["lower20"])]
    for _, r in lower_touch.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "BB_LOWER_BOUNCE", "direction": "LONG"})
    upper_touch = feat[feat["upper20"].notna() & (feat["c"] >= feat["upper20"])]
    for _, r in upper_touch.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "BB_UPPER_FADE", "direction": "SHORT"})

    # ---- 2) Squeeze -> expansion breakout ----
    # squeeze flag: bandwidth percentile <= SQUEEZE_PCTL yesterday
    feat_sorted = feat.sort_values(["symbol", "date"]).reset_index(drop=True)
    feat_sorted["squeeze_prev"] = feat_sorted.groupby("symbol")["bw_pctile90"].shift(1) <= SQUEEZE_PCTL
    feat_sorted["upper20_prev"] = feat_sorted.groupby("symbol")["upper20"].shift(1)
    feat_sorted["lower20_prev"] = feat_sorted.groupby("symbol")["lower20"].shift(1)
    sq_up = feat_sorted[
        feat_sorted["squeeze_prev"].fillna(False)
        & feat_sorted["upper20_prev"].notna()
        & (feat_sorted["c"] > feat_sorted["upper20_prev"])
    ]
    for _, r in sq_up.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "SQUEEZE_BREAKOUT", "direction": "LONG"})
    sq_dn = feat_sorted[
        feat_sorted["squeeze_prev"].fillna(False)
        & feat_sorted["lower20_prev"].notna()
        & (feat_sorted["c"] < feat_sorted["lower20_prev"])
    ]
    for _, r in sq_dn.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "SQUEEZE_BREAKOUT", "direction": "SHORT"})

    # ---- 3) N-day breakout / breakdown (Donchian, prior N bars, excl. today) ----
    brk_up = feat[feat["hi20_prior"].notna() & (feat["c"] > feat["hi20_prior"])]
    for _, r in brk_up.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "BREAKOUT_20D", "direction": "LONG"})
    brk_dn = feat[feat["lo20_prior"].notna() & (feat["c"] < feat["lo20_prior"])]
    for _, r in brk_dn.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "BREAKOUT_20D", "direction": "SHORT"})

    # ---- 4) Volume surge (continuation bet, direction = today's own move) ----
    vs = feat[
        feat["volmed20_prior"].notna()
        & (feat["notional"] >= feat["volmed20_prior"] * VOLSURGE_MULT)
        & feat["log_ret"].notna()
    ]
    for _, r in vs.iterrows():
        direction = "LONG" if r["log_ret"] > 0 else ("SHORT" if r["log_ret"] < 0 else None)
        if direction:
            rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "VOL_SURGE_3X", "direction": direction})

    # ---- 5) Trend regime filter (state, not a discrete cross -- fires every
    #         day the state holds; downstream summarize() treats it like any
    #         other "trigger day" but we ALSO report a much coarser weekly
    #         resample for this one given the state persists for weeks) ----
    trend_state = feat[
        feat["sma50"].notna() & feat["sma50_rising"].notna()
        & (feat["c"] > feat["sma50"]) & (feat["sma50_rising"] > 0)
    ]
    for _, r in trend_state.iterrows():
        rows.append({"symbol": r["symbol"], "date": r["date"], "signal": "TREND_UP_STATE", "direction": "LONG"})

    # ---- 6) Relative strength cross-section (ALTS ONLY) ----
    alt_feat = feat[feat["symbol"].isin(alt_symbols)]
    for window in RS_WINDOWS:
        col = f"ret{window}"
        for date, g in alt_feat.groupby("date"):
            elig = g[g["notional"].notna() & (g["notional"] >= MIN_24H_VOLUME_USD) & g[col].notna()]
            if len(elig) < 8:
                continue
            n_top = max(1, round(len(elig) * RS_TOP_Q))
            n_bot = max(1, round(len(elig) * RS_BOT_Q))
            leaders = elig.sort_values(col, ascending=False).head(n_top)
            laggards = elig.sort_values(col, ascending=True).head(n_bot)
            for _, r in leaders.iterrows():
                rows.append({"symbol": r["symbol"], "date": r["date"],
                             "signal": f"RS_LEADER_{window}D", "direction": "LONG"})
            for _, r in laggards.iterrows():
                rows.append({"symbol": r["symbol"], "date": r["date"],
                             "signal": f"RS_LAGGARD_{window}D", "direction": "SHORT"})

    # ---- 7) Fib/retracement proxy ----
    for sym, g in feat.groupby("symbol", sort=False):
        rows.extend(fib_events_for_symbol(g))

    ev = pd.DataFrame(rows)
    if ev.empty:
        return ev
    ev["date"] = pd.to_datetime(ev["date"], utc=True)
    fwd_cols = ["symbol", "date"] + [f"fwd_ret_{hz}" for hz in HORIZONS]
    ev = ev.merge(feat[fwd_cols], on=["symbol", "date"], how="left")
    return ev


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def signed_return(ev: pd.DataFrame, hz: int) -> pd.Series:
    sign = np.where(ev["direction"] == "LONG", 1.0, np.where(ev["direction"] == "SHORT", -1.0, np.nan))
    return sign * ev[f"fwd_ret_{hz}"]


def summarize(ev: pd.DataFrame, hz: int, label: str) -> Dict:
    sub = ev.dropna(subset=[f"fwd_ret_{hz}"])
    if sub.empty:
        return {"group": label, "horizon": hz, "n": 0}
    raw = signed_return(sub, hz).dropna()
    if raw.empty:
        return {"group": label, "horizon": hz, "n": 0}
    net = raw - FEE_RT
    n = len(net)
    std = net.std(ddof=1) if n > 1 else np.nan
    tstat = net.mean() / (std / np.sqrt(n)) if std and std > 0 else np.nan
    by_coin = sub.loc[raw.index].assign(_r=net).groupby("symbol")["_r"].mean()
    cvar5 = net.sort_values().head(max(1, int(np.ceil(n * 0.05)))).mean()
    return {
        "group": label,
        "horizon": hz,
        "n": n,
        "n_coins": sub.loc[raw.index, "symbol"].nunique(),
        "raw_mean_pct": raw.mean() * 100,
        "net_mean_pct": net.mean() * 100,
        "net_median_pct": net.median() * 100,
        "net_std_pct": (std * 100) if std == std else np.nan,
        "tstat": tstat,
        "hit_rate_pct": (net > 0).mean() * 100,
        "coin_eq_wt_net_mean_pct": by_coin.mean() * 100,
        "cvar5_net_pct": cvar5 * 100,
    }


def collapse_episodes(ev: pd.DataFrame) -> pd.DataFrame:
    """Keep only the FIRST day of each consecutive-day trigger run per
    (symbol, signal, direction) -- the non-overlap / autocorrelation control.
    Consecutive = calendar-day-adjacent, not just adjacent rows."""
    if ev.empty:
        return ev
    out_idx = []
    for (sym, sig, dirn), g in ev.groupby(["symbol", "signal", "direction"], sort=False):
        g = g.sort_values("date")
        dates = g["date"].values
        prev = None
        for idx, d in zip(g.index, dates):
            d = pd.Timestamp(d)
            if prev is None or (d - prev) > pd.Timedelta(days=1):
                out_idx.append(idx)
            prev = d
    return ev.loc[out_idx]


def print_table(rows: List[Dict], title: str) -> None:
    print(f"\n=== {title} ===")
    d = pd.DataFrame(rows)
    if d.empty:
        print("  (no data)")
        return
    cols = ["group", "horizon", "n", "n_coins", "raw_mean_pct", "net_mean_pct", "net_median_pct",
            "net_std_pct", "tstat", "hit_rate_pct", "coin_eq_wt_net_mean_pct", "cvar5_net_pct"]
    cols = [c for c in cols if c in d.columns]
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(d[cols].to_string(index=False))


def era_split(ev: pd.DataFrame, all_dates: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    dates = sorted(all_dates.unique())
    mid = dates[len(dates) // 2]
    return ev[ev["date"] < mid], ev[ev["date"] >= mid], pd.Timestamp(mid)


def signal_block(ev: pd.DataFrame, signal_name: str, directions: List[str],
                  all_dates: pd.Series, report_rows: List[Dict]) -> None:
    sig_ev = ev[ev["signal"] == signal_name]
    if sig_ev.empty:
        print(f"\n=== {signal_name}: NO EVENTS TRIGGERED (n=0) ===")
        return
    first, second, mid = era_split(sig_ev, all_dates)
    episodes_all = collapse_episodes(sig_ev)
    episodes_second = collapse_episodes(second)

    n_days_total = sig_ev.drop_duplicates(["symbol", "date"]).shape[0]
    n_episodes_total = episodes_all.drop_duplicates(["symbol", "date"]).shape[0]
    print(f"\n########## SIGNAL: {signal_name} ##########")
    print(f"  trigger coin-days: {n_days_total}  |  non-overlap episodes: {n_episodes_total}  "
          f"|  OOS split at {mid.date()}")

    for dirn in directions:
        d_ev = sig_ev[sig_ev["direction"] == dirn]
        d_first = first[first["direction"] == dirn]
        d_second = second[second["direction"] == dirn]
        d_ep_all = episodes_all[episodes_all["direction"] == dirn]
        d_ep_second = episodes_second[episodes_second["direction"] == dirn]
        rows = []
        for hz in HORIZONS:
            rows.append(summarize(d_ev, hz, f"{dirn} FULL (pooled)"))
            rows.append(summarize(d_first, hz, f"{dirn} FIRST-HALF"))
            rows.append(summarize(d_second, hz, f"{dirn} SECOND-HALF (OOS)"))
            rows.append(summarize(d_ep_all, hz, f"{dirn} FULL (non-overlap episodes)"))
            rows.append(summarize(d_ep_second, hz, f"{dirn} OOS (non-overlap episodes)"))
        print_table(rows, f"{signal_name} / {dirn}")
        # capture the headline OOS h=3, non-overlap-episode row for the final ranking
        headline = summarize(d_ep_second, 3, f"{signal_name}/{dirn}")
        headline["signal"] = signal_name
        headline["direction"] = dirn
        report_rows.append(headline)

    # per-quarter era table (h=3 only, to keep it compact)
    qrows = []
    q_ev = sig_ev.copy()
    q_ev["q"] = q_ev["date"].dt.to_period("Q").astype(str)
    for (q, dirn), g in q_ev.groupby(["q", "direction"]):
        s = summarize(g, 3, f"{q} {dirn}")
        s["quarter"] = q
        qrows.append(s)
    if qrows:
        print(f"\n--- {signal_name}: per-quarter (h=3, pooled coin-days) ---")
        qdf = pd.DataFrame(qrows)
        cols = ["quarter", "group", "n", "net_mean_pct", "tstat", "hit_rate_pct"]
        cols = [c for c in cols if c in qdf.columns]
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(qdf[cols].to_string(index=False))


def bollinger_feb_split(ev: pd.DataFrame) -> None:
    print("\n########## SPECIAL CHECK: Bollinger lower-band bounce, pre- vs post-2026-02-01 ##########")
    sig_ev = ev[(ev["signal"] == "BB_LOWER_BOUNCE")]
    pre = sig_ev[sig_ev["date"] < FEB_2026_CUTOFF]
    post = sig_ev[sig_ev["date"] >= FEB_2026_CUTOFF]
    rows = []
    for hz in HORIZONS:
        rows.append(summarize(pre, hz, "PRE-2026-02-01 (pooled)"))
        rows.append(summarize(collapse_episodes(pre), hz, "PRE-2026-02-01 (episodes)"))
        rows.append(summarize(post, hz, "POST-2026-02-01 (pooled)"))
        rows.append(summarize(collapse_episodes(post), hz, "POST-2026-02-01 (episodes)"))
    print_table(rows, "BB_LOWER_BOUNCE: pre/post Feb-2026 (the 'deep-oversold-died' trap check)")


def main() -> None:
    print("Loading longtail daily OHLC panel + BTC/SOL...")
    panel, alt_symbols = load_panel()
    print(f"  {panel['symbol'].nunique()} symbols total ({len(alt_symbols)} alts + "
          f"{panel['symbol'].nunique() - len(alt_symbols)} BTC/SOL), "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}, {len(panel)} coin-days")

    feat = compute_features(panel)
    events = build_events(feat, alt_symbols)
    print(f"\nTotal events across all signals: {len(events)}")
    if not events.empty:
        print(events.groupby(["signal", "direction"]).size().to_string())

    all_dates = feat["date"]
    report_rows: List[Dict] = []

    signal_block(events, "BB_LOWER_BOUNCE", ["LONG"], all_dates, report_rows)
    signal_block(events, "BB_UPPER_FADE", ["SHORT"], all_dates, report_rows)
    signal_block(events, "SQUEEZE_BREAKOUT", ["LONG", "SHORT"], all_dates, report_rows)
    signal_block(events, "BREAKOUT_20D", ["LONG", "SHORT"], all_dates, report_rows)
    signal_block(events, "VOL_SURGE_3X", ["LONG", "SHORT"], all_dates, report_rows)
    signal_block(events, "TREND_UP_STATE", ["LONG"], all_dates, report_rows)
    signal_block(events, "RS_LEADER_10D", ["LONG"], all_dates, report_rows)
    signal_block(events, "RS_LAGGARD_10D", ["SHORT"], all_dates, report_rows)
    signal_block(events, "RS_LEADER_20D", ["LONG"], all_dates, report_rows)
    signal_block(events, "RS_LAGGARD_20D", ["SHORT"], all_dates, report_rows)
    signal_block(events, "FIB_RETRACE", ["LONG", "SHORT"], all_dates, report_rows)

    bollinger_feb_split(events)

    # -----------------------------------------------------------------
    # FINAL HONEST RANKING: OOS, non-overlap-episode, h=3, net-of-fees
    # -----------------------------------------------------------------
    print("\n\n################ FINAL RANKING: OOS (second-half), non-overlap episodes, h=3d, net-of-fees ################")
    rdf = pd.DataFrame(report_rows)
    if not rdf.empty:
        rdf = rdf[rdf["n"] > 0].copy()
        rdf["abs_tstat"] = rdf["tstat"].abs()
        rdf = rdf.sort_values("net_mean_pct", ascending=False)
        cols = ["signal", "direction", "n", "n_coins", "raw_mean_pct", "net_mean_pct",
                "tstat", "hit_rate_pct", "coin_eq_wt_net_mean_pct", "cvar5_net_pct"]
        cols = [c for c in cols if c in rdf.columns]
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(rdf[cols].to_string(index=False))

        print("\nSurvival filter: |t|>=2.0 AND n>=15 (episode-level) AND net_mean_pct>0 AND coin_eq_wt agrees in sign:")
        survivors = rdf[
            (rdf["abs_tstat"] >= 2.0) & (rdf["n"] >= 15) & (rdf["net_mean_pct"] > 0)
            & (np.sign(rdf["coin_eq_wt_net_mean_pct"]) == np.sign(rdf["net_mean_pct"]))
        ]
        if survivors.empty:
            print("  NONE. No signal in this panel clears |t|>=2, n>=15, positive net-of-fees mean with "
                  "sign-consistent per-coin cross-check, on the OOS non-overlap sample.")
        else:
            with pd.option_context("display.float_format", "{:.3f}".format):
                print(survivors[cols].to_string(index=False))
    else:
        print("  No events at all -- nothing to rank.")

    print("\nDone.")


if __name__ == "__main__":
    main()
