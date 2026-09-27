#!/usr/bin/env python
"""
ADD Signal Revalidation - add_signal_revalidate.py
=============================================================================
STANDALONE, READ-ONLY, self-refuting audit of the co-pilot's single
most-shown claim: the per-coin ADD / HOLD / WAIT call in
tools/copilot/copilot.py (`build_dip_read` / `_classify_dip`).

WHY THIS EXISTS
-----------------------------------------------------------------------------
signal_panel_test.py just proved the Bollinger LOWER-BAND BOUNCE (a dip/
oversold signal, same family as ADD) was real pre-2026-02-01 and DIED after
(t flipped from +8.1 in 2025Q4 to -3.3 in 2026Q2). copilot.py's own
docstring ALREADY claims a specific calibration result for ADD ("ADD
CALIBRATION v2.3, 2026-07-31": +0.5%/3d vs a random day, t=4.7, fading in
2026-H2, ADD-in-uptrend the one config that clears fees). This script does
NOT trust that claim - it independently reconstructs the exact ADD trigger
and re-measures it from scratch, entry-time-safe, era-split, non-overlap,
net-of-fees, to confirm/refute whether that claim itself is fresh or is
already a stale relic the same way the BB bounce was.

Does NOT import copilot.py (or any other live-bot/copilot module) at
runtime. All ADD-trigger logic below is a byte-for-byte-faithful
REPRODUCTION, transcribed by reading copilot.py's `_classify_dip` /
`build_dip_read` (constants + branch logic copied verbatim, functions
re-implemented from the same math) - never executed via import, so this
script has zero side effects on live state, .env, or any copilot output.

FIDELITY NOTE (honest, so nobody mistakes this for a byte-exact replay)
-----------------------------------------------------------------------------
Live `build_dip_read` fetches a trailing DAYS_1D=200-bar window and
recomputes every indicator fresh on just that slice, once, "as of now".
Reproducing that exactly (re-slicing to the trailing 200 bars and rebuilding
EMA/RSI/ADX from scratch at every historical day t) is unnecessary for
EMA(20/50, adjust=False), RSI(14, Wilder) and ADX(14, Wilder): their ewm
decay (alpha 1/14..2/51) makes bars older than ~150-200d contribute <0.1% of
weight, so computing them as ONE expanding pass over each symbol's full
history (causal by construction - never uses future bars) is
indistinguishable from the live per-day 200-slice recompute, and is what
this script does for speed/simplicity. Two places where the trailing window
DOES matter and ARE reproduced as genuine trailing windows, matching live
exactly:
  - Bollinger(20,2) and the swing-S/R 20d window: naturally <200, identical
    either way.
  - daily_vol_pct (used only by the tight-range WAIT gate, not ADD scoring):
    a genuine rolling 200-day trailing stdev of daily % returns, not an
    expanding one (volatility regime can shift over >200d of history, so
    this one is NOT decay-dominated the way EMA/RSI/ADX are).
This is disclosed, not swept under the rug - the moat here is honesty about
what's approximated, not the absence of approximation.

UNIVERSE (matches the "27 coins" the copilot docstring cites)
-----------------------------------------------------------------------------
25 longtail alts (data/longtail/ohlc/*_1d.csv, ~2025-06-26 -> today) + BTC +
SOL (live Hyperliquid fetch, falls back to data/cache/*_daily_420d.csv if
unreachable) = 27 symbols.

FEES
-----------------------------------------------------------------------------
FEE_RT = 9bps (0.0009) round-trip, subtracted ONCE per event, matching
signal_panel_test.py / mover_followthrough_test.py convention. ADD is
always a LONG-side call (deploy capital on a dip), so signed return = raw
forward return, no direction flip needed.

REFUTE-YOURSELF CHECKS BUILT IN
-----------------------------------------------------------------------------
(a) Era split: quarter table + the decisive pre-/post-2026-02-01 cut (the
    same date that killed the BB bounce), PLUS a most-recent-quarter slice.
(b) Non-overlap: ADD fires on consecutive days when a coin sits oversold for
    a week - collapsed to first-day-of-run episodes per symbol, exactly like
    signal_panel_test.py's collapse_episodes, before trusting any t-stat.
(c) Excess-vs-baseline: ADD's forward return compared against a same-coin,
    same-era ALL-DAYS baseline via a Welch two-sample t-test (does an ADD
    day actually differ from a random day?), separate from the one-sample
    test of whether ADD standalone clears zero net-of-fees.
(d) Per-coin equal-weight cross-check + explicit per-coin table on the
    recent-era episode sample, so one chatty coin can't manufacture a
    "signal".
(e) Decomposition: ADD-in-uptrend vs ADD-in-chop/downtrend, and deep-oversold
    (BB<=0.25 AND RSI<=35 together) vs single-condition ADD, each re-run
    through the full era/non-overlap/fee gauntlet independently.

Run:
    python tools/copilot/add_signal_revalidate.py
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 300)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")

# ---------------------------------------------------------------------------
# Constants copied VERBATIM from tools/copilot/copilot.py (read 2026-07-31,
# copilot.py lines ~262-287) - the exact numbers the live ADD gate uses.
# ---------------------------------------------------------------------------
EMA_FAST, EMA_SLOW = 20, 50
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 22.0
BB_PERIOD, BB_MULT = 20, 2.0
RSI_PERIOD = 14
SWING_LOOKBACK_D = 20   # days, excludes today

ADD_BB_MAX = 0.25       # bb_pos_1d at/below this = lower-band zone (ADD)
HOLD_BB_MIN = 0.75
RSI_OVERSOLD = 35.0
RSI_OVERBOUGHT = 65.0
NEAR_SR_PCT = 6.0

TIGHT_RANGE_DAILY_VOL_PCT = 3.0
FALLING_KNIFE_RET7D_PCT = -25.0

MIN_ROWS_1D = 30       # build_dip_read's own "insufficient history" gate
DAYS_1D_WINDOW = 200   # live's trailing fetch window (used here only for
                        # the genuine rolling daily_vol_pct - see FIDELITY NOTE)

FEE_RT = 0.0009
HORIZONS = [1, 3, 5]
FEB_2026_CUTOFF = pd.Timestamp("2026-02-01", tz="UTC")


# ---------------------------------------------------------------------------
# Data loading (standalone - public HL info endpoint + local CSV, no live-bot
# imports; same free-data convention already used by signal_panel_test.py)
# ---------------------------------------------------------------------------
def _hl_daily_candles(coin: str, start_ms: int) -> Optional[pd.DataFrame]:
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
        for col in ["o", "h", "l", "c", "v"]:
            df[col] = df[col].astype(float)
        df["symbol"] = coin
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        return df[["symbol", "date", "o", "h", "l", "c", "v"]].reset_index(drop=True)
    except Exception as e:  # noqa: BLE001 - best-effort, any failure -> cache fallback
        print(f"  [{coin}] live Hyperliquid fetch failed ({e!r}); trying local cache fallback")
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
            print(f"  [{coin}] live fetch OK: {len(live)} bars, {live['date'].min().date()} -> {live['date'].max().date()}")
            frames.append(live)
            continue
        cached = _cache_daily_fallback(coin)
        if cached is not None:
            print(f"  [{coin}] STALE cache fallback: {len(cached)} bars, "
                  f"{cached['date'].min().date()} -> {cached['date'].max().date()}")
            frames.append(cached)
        else:
            print(f"  [{coin}] no live data and no cache -- excluded")
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "o", "h", "l", "c", "v"])
    return pd.concat(frames, ignore_index=True)


def load_panel() -> Tuple[pd.DataFrame, List[str]]:
    alts = load_longtail_alts()
    alt_symbols = sorted(alts["symbol"].unique().tolist())
    btcsol = load_btc_sol(alts["date"].min())
    panel = pd.concat([alts, btcsol], ignore_index=True) if len(btcsol) else alts
    return panel, alt_symbols


# ---------------------------------------------------------------------------
# Indicators - re-implemented from copilot.py's _ema/_true_range/_adx/_rsi/
# _bollinger, verbatim math (see module docstring FIDELITY NOTE for the
# expanding-vs-trailing-200 discussion).
# ---------------------------------------------------------------------------
def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["h"], df["l"], df["c"]
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    high, low = df["h"], df["l"]
    tr = _true_range(df)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(~(avg_loss.eq(0) & avg_gain.gt(0)), 100.0)
    return rsi


def _bollinger(series: pd.Series, period: int = BB_PERIOD, mult: float = BB_MULT):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    return mid, mid + mult * std, mid - mult * std


# ---------------------------------------------------------------------------
# Per-symbol feature engineering + exact ADD/HOLD/WAIT reconstruction
# ---------------------------------------------------------------------------
def compute_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        close = g["c"]

        ema_f = _ema(close, EMA_FAST)
        ema_s = _ema(close, EMA_SLOW)
        adx = _adx(g)
        rsi = _rsi(close, RSI_PERIOD)
        mid, bb_up, bb_lo = _bollinger(close)
        bb_pos = ((close - bb_lo) / (bb_up - bb_lo)).clip(-0.5, 1.5)
        bb_pos = bb_pos.where(bb_up != bb_lo)

        # genuine trailing-200 rolling vol (see FIDELITY NOTE) - the ONLY
        # indicator here that is NOT an expanding/full-history approximation
        daily_ret_pct = close.pct_change() * 100.0
        daily_vol_pct = daily_ret_pct.rolling(window=DAYS_1D_WINDOW, min_periods=2).std()

        # swing S/R: trailing 20d window EXCLUDING today (shift(1) first)
        swing_high = g["h"].shift(1).rolling(SWING_LOOKBACK_D).max()
        swing_low = g["l"].shift(1).rolling(SWING_LOOKBACK_D).min()
        dist_to_high_pct = (swing_high - close) / close * 100.0
        dist_to_low_pct = (close - swing_low) / close * 100.0

        ret_7d_pct = (close / close.shift(7) - 1.0) * 100.0

        row_idx = np.arange(n)  # 0-based position within this symbol's series

        g = g.copy()
        g["ema_f"], g["ema_s"], g["adx"], g["rsi"] = ema_f, ema_s, adx, rsi
        g["bb_pos"] = bb_pos
        g["daily_vol_pct"] = daily_vol_pct
        g["swing_high"], g["swing_low"] = swing_high, swing_low
        g["dist_to_high_pct"], g["dist_to_low_pct"] = dist_to_high_pct, dist_to_low_pct
        g["ret_7d_pct"] = ret_7d_pct
        g["row_idx"] = row_idx

        for hz in HORIZONS:
            fwd = np.full(n, np.nan)
            fwd[: n - hz] = close.values[hz:] / close.values[: n - hz] - 1.0
            g[f"fwd_ret_{hz}"] = fwd

        out.append(g)
    return pd.concat(out, ignore_index=True)


def classify(feat: pd.DataFrame) -> pd.DataFrame:
    """Reproduces _classify_dip's branch logic exactly (gates first, then
    add_score/hold_score), vectorized. Adds action/is_uptrend/deep_oversold/
    component flags for the decomposition."""
    f = feat.copy()

    is_trending = f["adx"] >= ADX_TREND_THRESHOLD
    dir_up = f["ema_f"] > f["ema_s"]
    trend_1d = np.where(is_trending, np.where(dir_up, "up", "down"), "chop")
    f["trend_1d"] = trend_1d

    is_falling_knife = (f["trend_1d"] == "down") & (f["ret_7d_pct"] <= FALLING_KNIFE_RET7D_PCT)
    is_tight_range = (f["daily_vol_pct"] < TIGHT_RANGE_DAILY_VOL_PCT) & (f["trend_1d"] == "chop")

    lower_bb = f["bb_pos"] <= ADD_BB_MAX
    oversold = f["rsi"] <= RSI_OVERSOLD
    near_support = f["dist_to_low_pct"] <= NEAR_SR_PCT
    upper_bb = f["bb_pos"] >= HOLD_BB_MIN
    overbought = f["rsi"] >= RSI_OVERBOUGHT
    near_resistance = f["dist_to_high_pct"] <= NEAR_SR_PCT

    add_score = lower_bb.astype(int) + oversold.astype(int) + near_support.astype(int)
    hold_score = upper_bb.astype(int) + overbought.astype(int) + near_resistance.astype(int)

    action = np.where(
        is_falling_knife | is_tight_range, "WAIT",
        np.where((add_score >= 1) & (add_score > hold_score), "ADD",
                 np.where((hold_score >= 1) & (hold_score > add_score), "HOLD", "HOLD")),
    )

    f["lower_bb"], f["oversold"], f["near_support"] = lower_bb, oversold, near_support
    f["upper_bb"], f["overbought"], f["near_resistance"] = upper_bb, overbought, near_resistance
    f["add_score"], f["hold_score"] = add_score, hold_score
    f["action"] = action
    f["is_uptrend"] = f["trend_1d"] == "up"
    f["deep_oversold"] = lower_bb & oversold  # the exact combo copilot's note flags as a dead relic

    valid = (
        (f["row_idx"] >= MIN_ROWS_1D - 1)
        & f["bb_pos"].notna() & f["rsi"].notna() & f["adx"].notna()
        & f["daily_vol_pct"].notna() & f["dist_to_low_pct"].notna() & f["dist_to_high_pct"].notna()
        & f["ret_7d_pct"].notna()
    )
    f["valid"] = valid
    return f


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def summarize(ev: pd.DataFrame, hz: int, label: str) -> Dict:
    col = f"fwd_ret_{hz}"
    sub = ev.dropna(subset=[col])
    if sub.empty:
        return {"group": label, "horizon": hz, "n": 0, "n_coins": 0}
    raw = sub[col]
    net = raw - FEE_RT
    n = len(net)
    std = net.std(ddof=1) if n > 1 else np.nan
    tstat, pval = (np.nan, np.nan)
    if std and std > 0 and n > 1:
        tstat, pval = stats.ttest_1samp(net, 0.0)
    by_coin = sub.assign(_r=net).groupby("symbol")["_r"].mean()
    return {
        "group": label, "horizon": hz, "n": n, "n_coins": sub["symbol"].nunique(),
        "raw_mean_pct": raw.mean() * 100, "net_mean_pct": net.mean() * 100,
        "net_median_pct": net.median() * 100,
        "net_std_pct": (std * 100) if std == std else np.nan,
        "tstat_vs_0": tstat, "pval_vs_0": pval,
        "hit_rate_pct": (net > 0).mean() * 100,
        "coin_eq_wt_net_mean_pct": by_coin.mean() * 100,
        "coin_eq_wt_min_pct": by_coin.min() * 100, "coin_eq_wt_max_pct": by_coin.max() * 100,
    }


def excess_vs_baseline(ev: pd.DataFrame, baseline: pd.DataFrame, hz: int, label: str) -> Dict:
    """Welch two-sample t-test: does an ADD day's forward return differ from
    a same-era, same-universe random day (the co-pilot's own '+0.5%/3d vs a
    random day' framing)? Uses RAW returns (fee cancels out in a difference
    against an equally-costed baseline)."""
    col = f"fwd_ret_{hz}"
    a = ev.dropna(subset=[col])[col]
    b = baseline.dropna(subset=[col])[col]
    if len(a) < 2 or len(b) < 2:
        return {"group": label, "horizon": hz, "n_add": len(a), "n_baseline": len(b)}
    tstat, pval = stats.ttest_ind(a, b, equal_var=False)
    # coin-equal-weight excess: average each coin's ADD mean minus that SAME
    # coin's baseline mean, then average across coins (a chatty coin with a
    # strong baseline drift can't masquerade as ADD edge)
    add_by_coin = ev.dropna(subset=[col]).groupby("symbol")[col].mean()
    base_by_coin = baseline.dropna(subset=[col]).groupby("symbol")[col].mean()
    common = add_by_coin.index.intersection(base_by_coin.index)
    coin_eq_excess = (add_by_coin.loc[common] - base_by_coin.loc[common]).mean() * 100 if len(common) else np.nan
    return {
        "group": label, "horizon": hz, "n_add": len(a), "n_baseline": len(b),
        "add_raw_mean_pct": a.mean() * 100, "baseline_raw_mean_pct": b.mean() * 100,
        "excess_pooled_pct": (a.mean() - b.mean()) * 100,
        "excess_coin_eq_wt_pct": coin_eq_excess,
        "welch_tstat": tstat, "welch_pval": pval,
    }


def collapse_episodes(ev: pd.DataFrame) -> pd.DataFrame:
    """Non-overlap control: keep only the FIRST day of each consecutive-day
    ADD run per symbol (calendar-day-adjacent), matching
    signal_panel_test.py's collapse_episodes exactly."""
    if ev.empty:
        return ev
    out_idx = []
    for sym, g in ev.groupby("symbol", sort=False):
        g = g.sort_values("date")
        prev = None
        for idx, d in zip(g.index, g["date"].values):
            d = pd.Timestamp(d)
            if prev is None or (d - prev) > pd.Timedelta(days=1):
                out_idx.append(idx)
            prev = d
    return ev.loc[out_idx]


def print_rows(rows: List[Dict], title: str) -> None:
    print(f"\n=== {title} ===")
    d = pd.DataFrame(rows)
    if d.empty:
        print("  (no data)")
        return
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(d.to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("Loading longtail daily OHLC panel + BTC/SOL...")
    panel, alt_symbols = load_panel()
    print(f"  {panel['symbol'].nunique()} symbols total ({len(alt_symbols)} alts + "
          f"{panel['symbol'].nunique() - len(alt_symbols)} BTC/SOL), "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}, {len(panel)} coin-days")

    feat = classify(compute_features(panel))
    valid = feat[feat["valid"]].copy()
    print(f"\nValid decision-days (>= {MIN_ROWS_1D} bars history): {len(valid)} across {valid['symbol'].nunique()} symbols")
    print(valid["action"].value_counts().to_string())

    add_ev = valid[valid["action"] == "ADD"].copy()
    n_add_days = len(add_ev)
    ep_all = collapse_episodes(add_ev)
    print(f"\nADD trigger coin-days: {n_add_days}  |  non-overlap episodes: {len(ep_all)}  "
          f"(inflation ratio {n_add_days / max(1, len(ep_all)):.2f}x)")

    pre = valid[valid["date"] < FEB_2026_CUTOFF]
    post = valid[valid["date"] >= FEB_2026_CUTOFF]
    add_pre = pre[pre["action"] == "ADD"]
    add_post = post[post["action"] == "ADD"]
    ep_pre = collapse_episodes(add_pre)
    ep_post = collapse_episodes(add_post)

    # most-recent-quarter slice (finer than the pre/post-Feb cut, to catch
    # continued decay within the "post" era, mirroring the BB-bounce finding
    # that even within 2026 it kept fading quarter over quarter)
    last_q_start = feat["date"].max() - pd.Timedelta(days=90)
    add_recent = valid[(valid["date"] >= last_q_start) & (valid["action"] == "ADD")]
    ep_recent = collapse_episodes(add_recent)

    # =======================================================================
    # PART 1: ADD forward-return by era, net-of-fees, non-overlap, significance
    # =======================================================================
    print("\n\n################ PART 1: ADD FORWARD RETURN BY ERA (net-of-fees, non-overlap episodes) ################")
    rows = []
    for label, sub in [("FULL SAMPLE", ep_all), ("PRE-2026-02-01", ep_pre),
                        ("POST-2026-02-01", ep_post), (f"LAST 90D (from {last_q_start.date()})", ep_recent)]:
        for hz in HORIZONS:
            rows.append(summarize(sub, hz, label))
    print_rows(rows, "ADD episodes: standalone net-of-fees mean/tstat-vs-0 by era")

    print("\n--- Also on the RAW pooled (non-collapsed) sample, for comparison against the copilot docstring's own numbers ---")
    rows_pooled = []
    for label, sub in [("FULL SAMPLE (pooled)", add_ev), ("PRE-2026-02-01 (pooled)", add_pre),
                        ("POST-2026-02-01 (pooled)", add_post)]:
        for hz in HORIZONS:
            rows_pooled.append(summarize(sub, hz, label))
    print_rows(rows_pooled, "ADD pooled coin-days (autocorrelation-inflated n - see PART 2)")

    # excess vs same-era all-days baseline
    print("\n--- Excess vs same-coin, same-era ALL-DAYS baseline (Welch t-test) ---")
    rows_excess = []
    for label, sub, base in [
        ("FULL (episodes) vs full baseline", ep_all, valid),
        ("PRE-2026-02-01 (episodes) vs pre baseline", ep_pre, pre),
        ("POST-2026-02-01 (episodes) vs post baseline", ep_post, post),
        (f"LAST 90D (episodes) vs last-90d baseline", ep_recent, valid[valid["date"] >= last_q_start]),
    ]:
        for hz in HORIZONS:
            rows_excess.append(excess_vs_baseline(sub, base, hz, label))
    print_rows(rows_excess, "ADD vs random-day baseline, per era")

    # per-quarter table (h=3 only, non-overlap episodes)
    print("\n--- Per-quarter table (h=3d, non-overlap episodes) ---")
    q_rows = []
    ep_all_q = ep_all.copy()
    ep_all_q["q"] = ep_all_q["date"].dt.to_period("Q").astype(str)
    for q, g in ep_all_q.groupby("q"):
        s = summarize(g, 3, q)
        q_rows.append(s)
    print_rows(q_rows, "ADD episodes by calendar quarter")

    # =======================================================================
    # PART 2: non-overlap correction, explicit before/after comparison
    # =======================================================================
    print("\n\n################ PART 2: NON-OVERLAP CORRECTION ################")
    print(f"Pooled coin-days: {n_add_days}   Non-overlap episodes: {len(ep_all)}   "
          f"Inflation ratio: {n_add_days / max(1, len(ep_all)):.2f}x")
    print("(compare PART 1's 'pooled' vs 'episodes' tstat/n above for each era - "
          "if pooled t-stats are much larger than episode t-stats, the pooled numbers "
          "were autocorrelation-inflated, exactly like the BB-bounce case.)")

    # =======================================================================
    # PART 3: refute-yourself checks
    # =======================================================================
    print("\n\n################ PART 3: REFUTE-YOURSELF ################")

    # (3a) deep-oversold combo, pre/post Feb-2026 - re-derive the docstring's
    # own claim independently instead of trusting it
    print("\n--- (3a) Deep-oversold (BB<=0.25 AND RSI<=35 together) vs single-condition ADD, pre/post-Feb-2026 ---")
    do_pre = collapse_episodes(add_pre[add_pre["deep_oversold"]])
    do_post = collapse_episodes(add_post[add_post["deep_oversold"]])
    single_pre = collapse_episodes(add_pre[~add_pre["deep_oversold"]])
    single_post = collapse_episodes(add_post[~add_post["deep_oversold"]])
    rows_do = []
    for label, sub in [("DEEP-OVERSOLD pre-Feb-2026", do_pre), ("DEEP-OVERSOLD post-Feb-2026", do_post),
                        ("single-condition ADD pre-Feb-2026", single_pre), ("single-condition ADD post-Feb-2026", single_post)]:
        rows_do.append(summarize(sub, 3, label))
    print_rows(rows_do, "Deep-oversold vs single-condition ADD (h=3d, episodes)")

    # (3b) concentration check - per-coin breakdown of the POST-era episode sample
    print("\n--- (3b) Per-coin breakdown, POST-2026-02-01 non-overlap episodes (h=3d) - is any tilt one coin's doing? ---")
    if not ep_post.empty:
        coin_tbl = ep_post.dropna(subset=["fwd_ret_3"]).groupby("symbol").agg(
            n_episodes=("fwd_ret_3", "size"),
            net_mean_pct=("fwd_ret_3", lambda s: (s - FEE_RT).mean() * 100),
        ).sort_values("net_mean_pct", ascending=False)
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(coin_tbl.to_string())
    else:
        print("  (no post-Feb-2026 ADD episodes)")

    # (3c) fee-clearing OOS check, explicit
    print("\n--- (3c) Does ADD clear the 9bps round-trip fee, net, on the POST-2026-02-01 non-overlap sample? ---")
    for hz in HORIZONS:
        s = summarize(ep_post, hz, f"POST-Feb-2026 episodes h={hz}d")
        verdict = "CLEARS FEES (net mean > 0)" if s.get("n", 0) and s["net_mean_pct"] > 0 else "DOES NOT CLEAR FEES (net mean <= 0)"
        print(f"  h={hz}d: n={s.get('n')}, net_mean={s.get('net_mean_pct', float('nan')):.3f}%, "
              f"t={s.get('tstat_vs_0', float('nan')):.2f} -> {verdict}")

    # =======================================================================
    # PART 4: decomposition - ADD-in-uptrend vs ADD-in-chop/downtrend
    # =======================================================================
    print("\n\n################ PART 4: DECOMPOSITION - ADD-IN-UPTREND vs NOT ################")
    rows_decomp = []
    for era_label, era_df in [("FULL", add_ev), ("PRE-2026-02-01", add_pre), ("POST-2026-02-01", add_post),
                               (f"LAST 90D", add_recent)]:
        up = collapse_episodes(era_df[era_df["is_uptrend"]])
        not_up = collapse_episodes(era_df[~era_df["is_uptrend"]])
        for hz in HORIZONS:
            rows_decomp.append(summarize(up, hz, f"{era_label} / ADD-in-UPTREND"))
            rows_decomp.append(summarize(not_up, hz, f"{era_label} / ADD-in-chop-or-downtrend"))
    print_rows(rows_decomp, "ADD-in-uptrend vs not, by era (non-overlap episodes, net-of-fees)")

    # excess-vs-baseline for the uptrend slice specifically (does ADD+uptrend
    # actually beat a random day IN AN UPTREND, or just ride uptrend drift?)
    print("\n--- ADD-in-uptrend vs an UPTREND-ONLY baseline (controls for 'uptrends just go up anyway') ---")
    rows_ut_excess = []
    for era_label, era_add, era_base in [
        ("FULL", add_ev[add_ev["is_uptrend"]], valid[valid["is_uptrend"]]),
        ("PRE-2026-02-01", add_pre[add_pre["is_uptrend"]], pre[pre["is_uptrend"]]),
        ("POST-2026-02-01", add_post[add_post["is_uptrend"]], post[post["is_uptrend"]]),
    ]:
        for hz in HORIZONS:
            rows_ut_excess.append(excess_vs_baseline(collapse_episodes(era_add), era_base, hz, era_label))
    print_rows(rows_ut_excess, "ADD-in-uptrend vs all-uptrend-days baseline (Welch t-test)")

    # =======================================================================
    # FINAL HONEST VERDICT
    # =======================================================================
    print("\n\n################ FINAL VERDICT ################")
    full_h3 = summarize(ep_all, 3, "full")
    post_h3 = summarize(ep_post, 3, "post")
    recent_h3 = summarize(ep_recent, 3, "recent")
    ut_post_h3 = summarize(collapse_episodes(add_post[add_post["is_uptrend"]]), 3, "post-uptrend")
    print(f"ADD, h=3d, non-overlap episodes:")
    print(f"  FULL SAMPLE:            n={full_h3.get('n')}, net_mean={full_h3.get('net_mean_pct', float('nan')):.3f}%, t={full_h3.get('tstat_vs_0', float('nan')):.2f}")
    print(f"  POST-2026-02-01:        n={post_h3.get('n')}, net_mean={post_h3.get('net_mean_pct', float('nan')):.3f}%, t={post_h3.get('tstat_vs_0', float('nan')):.2f}")
    print(f"  LAST 90 DAYS:           n={recent_h3.get('n')}, net_mean={recent_h3.get('net_mean_pct', float('nan')):.3f}%, t={recent_h3.get('tstat_vs_0', float('nan')):.2f}")
    print(f"  POST-Feb ADD-in-uptrend: n={ut_post_h3.get('n')}, net_mean={ut_post_h3.get('net_mean_pct', float('nan')):.3f}%, t={ut_post_h3.get('tstat_vs_0', float('nan')):.2f}")
    print("\nDone.")


if __name__ == "__main__":
    main()
