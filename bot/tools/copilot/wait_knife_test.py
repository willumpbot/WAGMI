#!/usr/bin/env python
"""
WAIT / Falling-Knife Gate Audit - wait_knife_test.py
=============================================================================
STANDALONE, READ-ONLY, self-refuting audit of the co-pilot's THIRD action
output: the falling-knife WAIT gate in tools/copilot/copilot.py
(`build_dip_read` / `_classify_dip`). Completes the ADD/HOLD/WAIT audit
trilogy - add_signal_revalidate.py already re-checked ADD (decayed to
noise OOS since Feb-2026) and signal_panel_test.py re-checked the lower-BB
bounce (died same date). This script gives WAIT the same scrutiny: does
"WAIT - FALLING KNIFE" actually avoid worse forward entries, or does it also
just miss the bounce with no measurable edge?

Does NOT import copilot.py at runtime. All falling-knife trigger logic below
is a byte-for-byte-faithful REPRODUCTION, transcribed by reading
_classify_dip / build_dip_read (copilot.py lines ~768-832, read 2026-07-31):

    daily_vol = r.vol.daily_vol_pct
    is_falling_knife = (
        r.trend_1d == "down" and r.trend_strength == "strong"
        and r.ret_7d_pct is not None and r.ret_7d_pct <= FALLING_KNIFE_RET7D_PCT
    )
    is_tight_range = (
        daily_vol is not None and daily_vol < TIGHT_RANGE_DAILY_VOL_PCT
        and r.trend_1d == "chop"
    )
    if is_falling_knife:
        r.action = "WAIT"   # "FALLING KNIFE" substring in action_reason
        return
    if is_tight_range:
        r.action = "WAIT"   # dead-chop WAIT - NOT this script's focus
        return
    ... (ADD/HOLD score logic, out of scope here - see add_signal_revalidate.py)

NOTE: `r.trend_strength == "strong"` is logically REDUNDANT with
`r.trend_1d == "down"` - trend_1d can only be "up"/"down" (never "chop")
when ADX >= ADX_TREND_THRESHOLD, i.e. exactly when trend_strength == "strong"
(see build_dip_read: `r.trend_1d = dir_1d if is_trending else "chop"`,
`r.trend_strength = "strong" if is_trending else "weak"`). So the exact
falling-knife condition reduces to: trend_1d == "down" AND ret_7d_pct <=
FALLING_KNIFE_RET7D_PCT (-25.0). Verified this is what add_signal_revalidate.py
also assumed in its own `classify()`. The falling-knife check runs BEFORE
the tight-range check and returns immediately, so WAIT-knife and WAIT-chop
are mutually exclusive by construction - reproduced here with the same
precedence (`wait_reason` column).

WHY THIS AUDIT MATTERS
-----------------------------------------------------------------------------
copilot.py's own docstring (ADD CALIBRATION v2.6, 2026-07-31) ALREADY claims
a specific number for this gate: "knife days actually bounce (+2.5%/3d on
average) - the gate exists because the PATH swings ~-10%+ intraday, which
would liquidate a leveraged add before any bounce." This script does NOT
trust that claim (same discipline as add_signal_revalidate.py did toward the
ADD docstring number before it) - it independently reconstructs the exact
trigger and re-measures FORWARD RETURN *and* FORWARD PATH/DRAWDOWN from
scratch, entry-time-safe, era-split, non-overlap, net-of-fees, to confirm,
refute, or sharpen that claim.

FIDELITY NOTE - same as add_signal_revalidate.py: EMA(20/50)/RSI(14)/ADX(14)
computed as ONE expanding pass per symbol (causal, never uses future bars) -
indistinguishable from live's per-day trailing-200 recompute since their ewm
decay makes bars >150-200d old contribute <0.1% weight. Bollinger(20,2),
swing S/R (20d), and daily_vol_pct (used only by the CHOP gate, not KNIFE)
ARE genuine trailing windows, matching live exactly.

UNIVERSE: same as add_signal_revalidate.py - 25 longtail alts
(data/longtail/ohlc/*_1d.csv) + BTC + SOL (live HL fetch, cache fallback).

FORWARD PATH / DRAWDOWN CONVENTION - reused verbatim from
tools/copilot/lev_band_horizon_test.py's `compute_horizon_tail_frac`:
    mae_long(i)  = (close[i] - min(low[i+1..i+H]))  / close[i]   (drawdown, >=0)
    mae_short(i) = (max(high[i+1..i+H]) - close[i]) / close[i]   (run-up, >=0)
This is the "PATH risk" the docstring's WAIT-knife framing refers to
(-10%+ intraday swing that liquidates a leveraged add before any bounce) -
distinct from the terminal close-to-close forward RETURN.

FEES: FEE_RT = 9bps round-trip, same convention as add_signal_revalidate.py,
applied to the hypothetical "you bought anyway on a knife day" comparison.

REFUTE-YOURSELF CHECKS BUILT IN
-----------------------------------------------------------------------------
(a) Era split: pre-/post-2026-02-01 (the date that killed the BB bounce and
    the ADD tilt) + per-quarter + last-90d slice.
(b) Non-overlap: knife triggers fire on consecutive days in a sustained
    crash - collapsed to first-day-of-run episodes per symbol before
    trusting any stat, exactly like add_signal_revalidate.py.
(c) Excess-vs-baseline: knife's forward return AND forward drawdown vs a
    same-era, same-universe ALL-DAYS baseline (Welch t-test on return;
    direct percentile/frequency comparison on drawdown).
(d) Downside-avoided vs upside-missed decomposition: conditional mean
    return in the positive (bounce/missed-upside) and negative
    (downside-avoided) buckets, hit rate, compared to baseline and to ADD.
(e) Component check: does the EXACT knife condition (down-trend confirmed by
    ADX>=22 AND ret_7d<=-25%) beat (i) momentum-only (ret_7d<=-25% regardless
    of trend/ADX classification) and (ii) plain-EMA-down-without-ADX-gate?
    If they're statistically indistinguishable, the "knife" framing adds
    nothing beyond a generic "big trailing loss -> mean reversion" effect -
    restating downtrend, not a bespoke gate.
(f) Per-coin equal-weight cross-check on the post-era sample.

Run:
    python tools/copilot/wait_knife_test.py
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy import stats

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 400)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")

# ---------------------------------------------------------------------------
# Constants copied VERBATIM from tools/copilot/copilot.py (read 2026-07-31)
# ---------------------------------------------------------------------------
EMA_FAST, EMA_SLOW = 20, 50
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 22.0
BB_PERIOD, BB_MULT = 20, 2.0
RSI_PERIOD = 14
SWING_LOOKBACK_D = 20

TIGHT_RANGE_DAILY_VOL_PCT = 3.0
FALLING_KNIFE_RET7D_PCT = -25.0

MIN_ROWS_1D = 30
DAYS_1D_WINDOW = 200

FEE_RT = 0.0009
HORIZONS = [1, 3, 5]
FEB_2026_CUTOFF = pd.Timestamp("2026-02-01", tz="UTC")
ADVERSE_DD_THRESHOLDS = [0.05, 0.10, 0.15]  # 5% / 10% / 15% intraday drawdown


# ---------------------------------------------------------------------------
# Data loading - identical to add_signal_revalidate.py (standalone, no
# live-bot imports; public HL info endpoint + local longtail CSVs)
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
# _bollinger, verbatim math (see add_signal_revalidate.py's identical copy).
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
# Per-symbol feature engineering: trend/momentum classification inputs +
# forward RETURN (terminal) and forward DRAWDOWN/RUN-UP (path) at each horizon
# ---------------------------------------------------------------------------
def compute_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        close = g["c"]
        low = g["l"].to_numpy(dtype=float)
        high = g["h"].to_numpy(dtype=float)
        close_np = close.to_numpy(dtype=float)

        ema_f = _ema(close, EMA_FAST)
        ema_s = _ema(close, EMA_SLOW)
        adx = _adx(g)
        rsi = _rsi(close, RSI_PERIOD)
        mid, bb_up, bb_lo = _bollinger(close)
        bb_pos = ((close - bb_lo) / (bb_up - bb_lo)).clip(-0.5, 1.5)
        bb_pos = bb_pos.where(bb_up != bb_lo)

        daily_ret_pct = close.pct_change() * 100.0
        daily_vol_pct = daily_ret_pct.rolling(window=DAYS_1D_WINDOW, min_periods=2).std()

        swing_high = g["h"].shift(1).rolling(SWING_LOOKBACK_D).max()
        swing_low = g["l"].shift(1).rolling(SWING_LOOKBACK_D).min()
        dist_to_high_pct = (swing_high - close) / close * 100.0
        dist_to_low_pct = (close - swing_low) / close * 100.0

        ret_7d_pct = (close / close.shift(7) - 1.0) * 100.0

        row_idx = np.arange(n)

        g = g.copy()
        g["ema_f"], g["ema_s"], g["adx"], g["rsi"] = ema_f, ema_s, adx, rsi
        g["bb_pos"] = bb_pos
        g["daily_vol_pct"] = daily_vol_pct
        g["swing_high"], g["swing_low"] = swing_high, swing_low
        g["dist_to_high_pct"], g["dist_to_low_pct"] = dist_to_high_pct, dist_to_low_pct
        g["ret_7d_pct"] = ret_7d_pct
        g["row_idx"] = row_idx

        for hz in HORIZONS:
            # terminal forward return (close-to-close)
            fwd = np.full(n, np.nan)
            fwd[: n - hz] = close_np[hz:] / close_np[: n - hz] - 1.0
            g[f"fwd_ret_{hz}"] = fwd

            # forward PATH: worst intraday drawdown / best intraday run-up
            # over the next hz days - convention from
            # lev_band_horizon_test.py's compute_horizon_tail_frac:
            #   mae_long(i)  = (close[i] - min(low[i+1..i+hz])) / close[i]
            #   mae_short(i) = (max(high[i+1..i+hz]) - close[i]) / close[i]
            m = n - hz
            fwd_dd = np.full(n, np.nan)
            fwd_ru = np.full(n, np.nan)
            if m > 0 and n > hz:
                low_windows = sliding_window_view(low[1:], hz)
                high_windows = sliding_window_view(high[1:], hz)
                fwd_min = low_windows.min(axis=1)[:m]
                fwd_max = high_windows.max(axis=1)[:m]
                entry_close = close_np[:m]
                fwd_dd[:m] = np.clip((entry_close - fwd_min) / entry_close, 0.0, None)
                fwd_ru[:m] = np.clip((fwd_max - entry_close) / entry_close, 0.0, None)
            g[f"fwd_dd_{hz}"] = fwd_dd
            g[f"fwd_ru_{hz}"] = fwd_ru

        out.append(g)
    return pd.concat(out, ignore_index=True)


def classify(feat: pd.DataFrame) -> pd.DataFrame:
    """Reproduces _classify_dip's gate precedence exactly (knife checked
    first and returns; chop checked second) plus the component-check flags
    used in PART 4."""
    f = feat.copy()

    is_trending = f["adx"] >= ADX_TREND_THRESHOLD
    dir_up = f["ema_f"] > f["ema_s"]
    trend_1d = np.where(is_trending, np.where(dir_up, "up", "down"), "chop")
    f["trend_1d"] = trend_1d

    is_falling_knife = (f["trend_1d"] == "down") & (f["ret_7d_pct"] <= FALLING_KNIFE_RET7D_PCT)
    is_tight_range = (~is_falling_knife) & (f["daily_vol_pct"] < TIGHT_RANGE_DAILY_VOL_PCT) & (f["trend_1d"] == "chop")

    lower_bb = f["bb_pos"] <= 0.25
    oversold = f["rsi"] <= 35.0
    near_support = f["dist_to_low_pct"] <= 6.0
    upper_bb = f["bb_pos"] >= 0.75
    overbought = f["rsi"] >= 65.0
    near_resistance = f["dist_to_high_pct"] <= 6.0
    add_score = lower_bb.astype(int) + oversold.astype(int) + near_support.astype(int)
    hold_score = upper_bb.astype(int) + overbought.astype(int) + near_resistance.astype(int)

    action = np.where(
        is_falling_knife, "WAIT",
        np.where(is_tight_range, "WAIT",
                 np.where((add_score >= 1) & (add_score > hold_score), "ADD",
                          np.where((hold_score >= 1) & (hold_score > add_score), "HOLD", "HOLD"))),
    )
    wait_reason = np.where(is_falling_knife, "KNIFE", np.where(is_tight_range, "CHOP", ""))

    f["action"] = action
    f["wait_reason"] = wait_reason
    f["is_falling_knife"] = is_falling_knife

    # -- Component-check flags (PART 4): does the exact knife condition add
    # anything beyond a generic "big trailing loss" or "in a downtrend"? --
    f["momentum_only"] = f["ret_7d_pct"] <= FALLING_KNIFE_RET7D_PCT              # drop trend/ADX requirement
    f["ema_down_no_adx"] = (f["ema_f"] < f["ema_s"]) & (f["ret_7d_pct"] <= FALLING_KNIFE_RET7D_PCT)  # drop ADX-strength gate only
    f["downtrend_any_momentum"] = (f["trend_1d"] == "down") & (f["ret_7d_pct"] > FALLING_KNIFE_RET7D_PCT)  # confirmed downtrend, NOT yet knife-extreme

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
    ret_col, dd_col = f"fwd_ret_{hz}", f"fwd_dd_{hz}"
    sub = ev.dropna(subset=[ret_col])
    if sub.empty:
        return {"group": label, "horizon": hz, "n": 0, "n_coins": 0}
    raw = sub[ret_col]
    net = raw - FEE_RT
    n = len(net)
    std = net.std(ddof=1) if n > 1 else np.nan
    tstat, pval = (np.nan, np.nan)
    if std and std > 0 and n > 1:
        tstat, pval = stats.ttest_1samp(net, 0.0)
    by_coin = sub.assign(_r=net).groupby("symbol")["_r"].mean()

    pos = net[net > 0]
    neg = net[net <= 0]
    dd_sub = sub.dropna(subset=[dd_col])[dd_col] if dd_col in sub.columns else pd.Series(dtype=float)

    row = {
        "group": label, "horizon": hz, "n": n, "n_coins": sub["symbol"].nunique(),
        "raw_mean_pct": raw.mean() * 100, "net_mean_pct": net.mean() * 100,
        "net_median_pct": net.median() * 100,
        "net_std_pct": (std * 100) if std == std else np.nan,
        "tstat_vs_0": tstat, "pval_vs_0": pval,
        "hit_rate_pct": (net > 0).mean() * 100,
        "mean_when_pos_pct": pos.mean() * 100 if len(pos) else np.nan,   # upside missed if you WAIT
        "mean_when_neg_pct": neg.mean() * 100 if len(neg) else np.nan,   # downside avoided if you WAIT
        "coin_eq_wt_net_mean_pct": by_coin.mean() * 100,
        "coin_eq_wt_min_pct": by_coin.min() * 100, "coin_eq_wt_max_pct": by_coin.max() * 100,
    }
    if len(dd_sub):
        row["fwd_dd_mean_pct"] = dd_sub.mean() * 100
        row["fwd_dd_median_pct"] = dd_sub.median() * 100
        row["fwd_dd_p90_pct"] = dd_sub.quantile(0.90) * 100
        for th in ADVERSE_DD_THRESHOLDS:
            row[f"pct_dd_ge_{int(th*100)}pct"] = (dd_sub >= th).mean() * 100
    return row


def excess_vs_baseline(ev: pd.DataFrame, baseline: pd.DataFrame, hz: int, label: str) -> Dict:
    """Welch two-sample t-test on RETURN, plus a direct drawdown-frequency
    comparison (does knife's forward path swing harder than a random day?)."""
    ret_col, dd_col = f"fwd_ret_{hz}", f"fwd_dd_{hz}"
    a = ev.dropna(subset=[ret_col])[ret_col]
    b = baseline.dropna(subset=[ret_col])[ret_col]
    if len(a) < 2 or len(b) < 2:
        return {"group": label, "horizon": hz, "n_group": len(a), "n_baseline": len(b)}
    tstat, pval = stats.ttest_ind(a, b, equal_var=False)
    add_by_coin = ev.dropna(subset=[ret_col]).groupby("symbol")[ret_col].mean()
    base_by_coin = baseline.dropna(subset=[ret_col]).groupby("symbol")[ret_col].mean()
    common = add_by_coin.index.intersection(base_by_coin.index)
    coin_eq_excess = (add_by_coin.loc[common] - base_by_coin.loc[common]).mean() * 100 if len(common) else np.nan

    dd_a = ev.dropna(subset=[dd_col])[dd_col]
    dd_b = baseline.dropna(subset=[dd_col])[dd_col]
    dd_tstat, dd_pval = (np.nan, np.nan)
    if len(dd_a) > 1 and len(dd_b) > 1:
        dd_tstat, dd_pval = stats.ttest_ind(dd_a, dd_b, equal_var=False)

    return {
        "group": label, "horizon": hz, "n_group": len(a), "n_baseline": len(b),
        "group_raw_mean_pct": a.mean() * 100, "baseline_raw_mean_pct": b.mean() * 100,
        "excess_pooled_pct": (a.mean() - b.mean()) * 100,
        "excess_coin_eq_wt_pct": coin_eq_excess,
        "welch_tstat_ret": tstat, "welch_pval_ret": pval,
        "group_fwd_dd_mean_pct": dd_a.mean() * 100 if len(dd_a) else np.nan,
        "baseline_fwd_dd_mean_pct": dd_b.mean() * 100 if len(dd_b) else np.nan,
        "dd_excess_pct_pts": (dd_a.mean() - dd_b.mean()) * 100 if len(dd_a) and len(dd_b) else np.nan,
        "welch_tstat_dd": dd_tstat, "welch_pval_dd": dd_pval,
    }


def collapse_episodes(ev: pd.DataFrame) -> pd.DataFrame:
    """Non-overlap control: keep only the FIRST day of each consecutive-day
    trigger run per symbol (calendar-day-adjacent) - identical convention to
    add_signal_revalidate.py / signal_panel_test.py."""
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
    print("\nWAIT reason breakdown:")
    print(valid.loc[valid["action"] == "WAIT", "wait_reason"].value_counts().to_string())

    knife_ev = valid[valid["wait_reason"] == "KNIFE"].copy()
    add_ev = valid[valid["action"] == "ADD"].copy()
    n_knife_days = len(knife_ev)
    ep_knife_all = collapse_episodes(knife_ev)
    ep_add_all = collapse_episodes(add_ev)
    print(f"\nWAIT-KNIFE trigger coin-days: {n_knife_days}  |  non-overlap episodes: {len(ep_knife_all)}  "
          f"(inflation ratio {n_knife_days / max(1, len(ep_knife_all)):.2f}x)")

    pre = valid[valid["date"] < FEB_2026_CUTOFF]
    post = valid[valid["date"] >= FEB_2026_CUTOFF]
    knife_pre = pre[pre["wait_reason"] == "KNIFE"]
    knife_post = post[post["wait_reason"] == "KNIFE"]
    ep_knife_pre = collapse_episodes(knife_pre)
    ep_knife_post = collapse_episodes(knife_post)

    last_q_start = feat["date"].max() - pd.Timedelta(days=90)
    knife_recent = valid[(valid["date"] >= last_q_start) & (valid["wait_reason"] == "KNIFE")]
    ep_knife_recent = collapse_episodes(knife_recent)

    # =======================================================================
    # PART 1: WAIT-knife forward RETURN + forward DRAWDOWN, by era, vs
    # ADD and vs baseline (net-of-fees, non-overlap episodes)
    # =======================================================================
    print("\n\n################ PART 1: WAIT-KNIFE FORWARD RETURN + DRAWDOWN, BY ERA ################")
    rows = []
    for label, sub in [("WAIT-KNIFE FULL", ep_knife_all), ("WAIT-KNIFE PRE-2026-02-01", ep_knife_pre),
                        ("WAIT-KNIFE POST-2026-02-01", ep_knife_post),
                        (f"WAIT-KNIFE LAST 90D (from {last_q_start.date()})", ep_knife_recent)]:
        for hz in HORIZONS:
            rows.append(summarize(sub, hz, label))
    print_rows(rows, "WAIT-KNIFE episodes: standalone net-of-fees return + forward drawdown, by era")

    print("\n--- Comparison groups at the same eras: ADD episodes, and ALL-DAYS baseline ---")
    rows_cmp = []
    for label, sub in [("ADD FULL", ep_add_all),
                        ("ADD PRE-2026-02-01", collapse_episodes(add_ev[add_ev["date"] < FEB_2026_CUTOFF])),
                        ("ADD POST-2026-02-01", collapse_episodes(add_ev[add_ev["date"] >= FEB_2026_CUTOFF])),
                        ("ALL-DAYS BASELINE FULL", valid),
                        ("ALL-DAYS BASELINE PRE-2026-02-01", pre),
                        ("ALL-DAYS BASELINE POST-2026-02-01", post)]:
        for hz in HORIZONS:
            rows_cmp.append(summarize(sub, hz, label))
    print_rows(rows_cmp, "ADD episodes + ALL-DAYS baseline, by era (for side-by-side comparison against WAIT-KNIFE above)")

    # excess vs same-era all-days baseline: return AND drawdown
    print("\n--- WAIT-KNIFE vs same-coin, same-era ALL-DAYS baseline (Welch t-test, return + drawdown) ---")
    rows_excess = []
    for label, sub, base in [
        ("FULL (episodes) vs full baseline", ep_knife_all, valid),
        ("PRE-2026-02-01 (episodes) vs pre baseline", ep_knife_pre, pre),
        ("POST-2026-02-01 (episodes) vs post baseline", ep_knife_post, post),
        ("LAST 90D (episodes) vs last-90d baseline", ep_knife_recent, valid[valid["date"] >= last_q_start]),
    ]:
        for hz in HORIZONS:
            rows_excess.append(excess_vs_baseline(sub, base, hz, label))
    print_rows(rows_excess, "WAIT-KNIFE vs random-day baseline, per era (return Welch t-test + drawdown comparison)")

    # per-quarter table (h=3, non-overlap episodes)
    print("\n--- Per-quarter table (h=3d, non-overlap episodes) ---")
    q_rows = []
    ep_q = ep_knife_all.copy()
    if not ep_q.empty:
        ep_q["q"] = ep_q["date"].dt.to_period("Q").astype(str)
        for q, g in ep_q.groupby("q"):
            q_rows.append(summarize(g, 3, q))
    print_rows(q_rows, "WAIT-KNIFE episodes by calendar quarter")

    # =======================================================================
    # PART 2: non-overlap correction
    # =======================================================================
    print("\n\n################ PART 2: NON-OVERLAP CORRECTION ################")
    print(f"Pooled coin-days: {n_knife_days}   Non-overlap episodes: {len(ep_knife_all)}   "
          f"Inflation ratio: {n_knife_days / max(1, len(ep_knife_all)):.2f}x")
    print("(a sustained crash re-fires the knife gate every day it continues - a single crash "
          "episode should not be allowed to masquerade as many independent 'knife' data points)")

    # =======================================================================
    # PART 3: adverse-move / drawdown frequency table + downside-avoided vs
    # upside-missed decomposition
    # =======================================================================
    print("\n\n################ PART 3: ADVERSE-MOVE (PATH) FREQUENCY + DOWNSIDE-AVOIDED vs UPSIDE-MISSED ################")
    print("(pct_dd_ge_Xpct = fraction of episodes whose worst intraday low over the horizon\n"
          " fell >= X% below the entry close - the PATH risk the docstring's leverage/liquidation\n"
          " framing refers to, distinct from the terminal close-to-close return below)")
    rows_dd = []
    for label, sub in [("WAIT-KNIFE FULL", ep_knife_all), ("WAIT-KNIFE POST-2026-02-01", ep_knife_post),
                        ("ADD FULL", ep_add_all), ("ALL-DAYS BASELINE FULL", valid)]:
        for hz in HORIZONS:
            rows_dd.append(summarize(sub, hz, label))
    print_rows(rows_dd, "Forward drawdown frequency + downside-avoided/upside-missed split, by group")

    print("\n--- Explicit trade-off read at h=3d (WAIT-KNIFE vs ALL-DAYS baseline) ---")
    k3 = summarize(ep_knife_all, 3, "knife")
    b3 = summarize(valid, 3, "baseline")
    if k3.get("n") and b3.get("n"):
        print(f"  hit-rate (bounces, i.e. upside you'd MISS by waiting): knife {k3['hit_rate_pct']:.1f}% vs baseline {b3['hit_rate_pct']:.1f}%")
        print(f"  mean gain WHEN it bounces (upside missed magnitude):   knife {k3['mean_when_pos_pct']:.2f}% vs baseline {b3['mean_when_pos_pct']:.2f}%")
        print(f"  mean loss WHEN it doesn't (downside avoided magnitude): knife {k3['mean_when_neg_pct']:.2f}% vs baseline {b3['mean_when_neg_pct']:.2f}%")
        print(f"  P(forward drawdown >= 10%) over 3d:                    knife {k3.get('pct_dd_ge_10pct', float('nan')):.1f}% vs baseline {b3.get('pct_dd_ge_10pct', float('nan')):.1f}%")
        print(f"  P(forward drawdown >= 15%) over 3d:                    knife {k3.get('pct_dd_ge_15pct', float('nan')):.1f}% vs baseline {b3.get('pct_dd_ge_15pct', float('nan')):.1f}%")

    # per-coin breakdown, post-era
    print("\n--- Per-coin breakdown, POST-2026-02-01 non-overlap WAIT-KNIFE episodes (h=3d) ---")
    if not ep_knife_post.empty:
        coin_tbl = ep_knife_post.dropna(subset=["fwd_ret_3"]).groupby("symbol").agg(
            n_episodes=("fwd_ret_3", "size"),
            net_mean_pct=("fwd_ret_3", lambda s: (s - FEE_RT).mean() * 100),
            mean_fwd_dd_pct=("fwd_dd_3", lambda s: s.mean() * 100),
        ).sort_values("net_mean_pct", ascending=False)
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(coin_tbl.to_string())
    else:
        print("  (no post-Feb-2026 WAIT-KNIFE episodes)")

    # =======================================================================
    # PART 4: component check - does the "knife" framing (ADX-confirmed
    # downtrend + -25% momentum) add anything beyond a plain momentum
    # threshold, or beyond plain EMA-direction without the ADX gate?
    # =======================================================================
    print("\n\n################ PART 4: COMPONENT CHECK - IS 'KNIFE' JUST RESTATING DOWNTREND? ################")
    momentum_only_ev = valid[valid["momentum_only"]].copy()
    ema_down_ev = valid[valid["ema_down_no_adx"]].copy()
    downtrend_moderate_ev = valid[valid["downtrend_any_momentum"]].copy()  # confirmed downtrend, NOT yet -25% extreme

    rows_comp = []
    for era_label, era_mask in [("FULL", valid["date"].notna()), ("PRE-2026-02-01", valid["date"] < FEB_2026_CUTOFF),
                                 ("POST-2026-02-01", valid["date"] >= FEB_2026_CUTOFF)]:
        era_df = valid[era_mask]
        exact = collapse_episodes(era_df[era_df["wait_reason"] == "KNIFE"])
        mom_only = collapse_episodes(era_df[era_df["momentum_only"]])
        ema_only = collapse_episodes(era_df[era_df["ema_down_no_adx"]])
        mod_down = collapse_episodes(era_df[era_df["downtrend_any_momentum"]])
        for hz in [3]:
            rows_comp.append(summarize(exact, hz, f"{era_label} / EXACT knife (ADX-down & ret7d<=-25%)"))
            rows_comp.append(summarize(mom_only, hz, f"{era_label} / momentum-only (ret7d<=-25%, any trend)"))
            rows_comp.append(summarize(ema_only, hz, f"{era_label} / EMA-down, no ADX gate (ret7d<=-25%)"))
            rows_comp.append(summarize(mod_down, hz, f"{era_label} / confirmed downtrend, NOT yet -25% extreme"))
    print_rows(rows_comp, "Component decomposition (h=3d, non-overlap episodes, net-of-fees)")

    print("\nInterpretation guide: if 'EXACT knife' and 'momentum-only' / 'EMA-down, no ADX gate' rows are\n"
          "statistically indistinguishable (similar net_mean/tstat/hit-rate/drawdown), the ADX-confirmed-\n"
          "trend requirement is doing ~nothing beyond the -25% momentum threshold itself - i.e. the whole\n"
          "'falling knife' gate reduces to 'big trailing loss', a generic mean-reversion setup, not a\n"
          "bespoke construct. If 'confirmed downtrend, NOT yet -25% extreme' behaves similarly to the exact\n"
          "knife (same sign/magnitude of return and drawdown), the -25% threshold itself is also not doing\n"
          "much marginal work over just 'in a downtrend' - i.e. the gate is trivially restating the trend.")

    # =======================================================================
    # FINAL HONEST VERDICT
    # =======================================================================
    print("\n\n################ FINAL VERDICT ################")
    k_full3 = summarize(ep_knife_all, 3, "knife-full")
    k_post3 = summarize(ep_knife_post, 3, "knife-post")
    k_recent3 = summarize(ep_knife_recent, 3, "knife-recent")
    b_full3 = summarize(valid, 3, "baseline-full")
    b_post3 = summarize(post, 3, "baseline-post")
    print(f"h=3d, non-overlap episodes, net-of-fees:")
    print(f"  WAIT-KNIFE FULL SAMPLE:  n={k_full3.get('n')}, net_mean={k_full3.get('net_mean_pct', float('nan')):.3f}%, "
          f"hit_rate={k_full3.get('hit_rate_pct', float('nan')):.1f}%, fwd_dd_mean={k_full3.get('fwd_dd_mean_pct', float('nan')):.2f}%, "
          f"P(dd>=10%)={k_full3.get('pct_dd_ge_10pct', float('nan')):.1f}%")
    print(f"  WAIT-KNIFE POST-Feb-2026: n={k_post3.get('n')}, net_mean={k_post3.get('net_mean_pct', float('nan')):.3f}%, "
          f"hit_rate={k_post3.get('hit_rate_pct', float('nan')):.1f}%, fwd_dd_mean={k_post3.get('fwd_dd_mean_pct', float('nan')):.2f}%, "
          f"P(dd>=10%)={k_post3.get('pct_dd_ge_10pct', float('nan')):.1f}%")
    print(f"  WAIT-KNIFE LAST 90D:      n={k_recent3.get('n')}, net_mean={k_recent3.get('net_mean_pct', float('nan')):.3f}%, "
          f"hit_rate={k_recent3.get('hit_rate_pct', float('nan')):.1f}%")
    print(f"  ALL-DAYS BASELINE FULL:   n={b_full3.get('n')}, net_mean={b_full3.get('net_mean_pct', float('nan')):.3f}%, "
          f"hit_rate={b_full3.get('hit_rate_pct', float('nan')):.1f}%, fwd_dd_mean={b_full3.get('fwd_dd_mean_pct', float('nan')):.2f}%, "
          f"P(dd>=10%)={b_full3.get('pct_dd_ge_10pct', float('nan')):.1f}%")
    print(f"  ALL-DAYS BASELINE POST:   n={b_post3.get('n')}, net_mean={b_post3.get('net_mean_pct', float('nan')):.3f}%, "
          f"hit_rate={b_post3.get('hit_rate_pct', float('nan')):.1f}%, fwd_dd_mean={b_post3.get('fwd_dd_mean_pct', float('nan')):.2f}%, "
          f"P(dd>=10%)={b_post3.get('pct_dd_ge_10pct', float('nan')):.1f}%")
    print("\nDone.")


if __name__ == "__main__":
    main()
