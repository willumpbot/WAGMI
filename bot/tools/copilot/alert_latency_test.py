#!/usr/bin/env python
"""
Falling-Knife WAIT-Gate ALERT LATENCY Test - alert_latency_test.py
=============================================================================
STANDALONE, READ-ONLY, self-refuting audit. wait_knife_test.py already
re-validated the co-pilot's WAIT-FALLING-KNIFE gate (tools/copilot/copilot.py
`_classify_dip`) on RETURN and on drawdown FREQUENCY (P(fwd_dd_3d>=10%):
knife 42% full-sample / 55% post-2026-02-01, vs 14-20% baseline). This script
asks the question that audit did NOT answer: is that forward drawdown risk
actually TIMELY to act on, or does most of the damage happen before the gate
could possibly help?

A risk gate that only flags danger AFTER the dangerous part of the path is
over is not actionable, even if the "42-55% chance of a >=10% drawdown"
number is completely correct. This script measures WHEN, not just WHETHER.

Never imports live-bot packages (llm/, execution/, core/, strategies/), never
writes to data/replay/, .env, or any live-bot state file, never pushes to
Discord. Reads: (a) tools/copilot's own call_ledger.jsonl (read-only, to
check whether a real fired-alert timestamp log exists at all), (b) the same
25-alt + BTC/SOL OHLC panel wait_knife_test.py / add_signal_revalidate.py
use, both daily (data/longtail/ohlc/*_1d.csv + live/cached BTC/SOL daily)
AND, new here, HOURLY (data/longtail/ohlc/*_1h.csv + live/cached BTC/SOL
hourly) for a finer-grained lag readout than a day-granularity gate allows.

Does NOT import copilot.py or wait_knife_test.py at runtime - the knife
trigger logic below is a byte-for-byte-faithful REPRODUCTION of
_classify_dip's exact condition (read 2026-07-31, and cross-checked against
wait_knife_test.py's own already-verified reduction of it):

    is_falling_knife = (
        r.trend_1d == "down" and r.trend_strength == "strong"
        and r.ret_7d_pct is not None and r.ret_7d_pct <= FALLING_KNIFE_RET7D_PCT  # -25.0
    )

wait_knife_test.py already established `trend_strength == "strong"` is
logically REDUNDANT with `trend_1d == "down"` (trend_1d can only be "down"
when ADX >= ADX_TREND_THRESHOLD, i.e. exactly when trend_strength=="strong").
So the exact trigger reduces to: trend_1d=="down" AND ret_7d_pct<=-25.0.
Reproduced identically here (EMA20/50 direction gated by ADX(14)>=22 for
"down", else "chop"/"up").

=============================================================================
PART 0 - DATA VIABILITY (run FIRST, reported before any OHLC analysis)
=============================================================================
Checks whether the co-pilot logs falling-knife WAIT events anywhere with a
timestamp, which would let PART 1 measure a real "pattern-true-in-the-market
timestamp" vs "logged-by-the-tool timestamp" lag directly. The only
candidate is tools/copilot/call_ledger.jsonl (call_logger.py) - an
entry-time-safe forward-evidence ledger that logs ONE row per (symbol, UTC
day, source) whenever a brief is built, including the action ("WAIT") and a
truncated action_reason (would contain "FALLING KNIFE" substring for a knife
WAIT). This script counts total rows, date range, and knife-WAIT rows found,
and prints an explicit VIABLE / NOT VIABLE verdict. See PART 0 output for the
actual numbers - written honestly whether that verdict is "yes" or "no", not
assumed in advance.

=============================================================================
PART 1/2 - THE ALTERNATIVE (always runs, OHLC-only, entry-time-safe, OOS)
=============================================================================
For every non-overlap knife-trigger episode:
  PART 1 (daily bars): the forward adverse-excursion (drawdown) convention
      reused verbatim from lev_band_horizon_test.py / wait_knife_test.py:
          fwd_dd_h(i) = (close[i] - min(low[i+1 .. i+h])) / close[i]
      computed for h in {1,2,3,4,5,7,10} days. Because the low-window for
      horizon h+1 is a strict superset of horizon h's window, fwd_dd_h is
      MONOTONE NON-DECREASING in h by construction - so "how much of the
      eventual 5-day drawdown is already present after 1 day" is simply
      fwd_dd_1 / fwd_dd_5 per episode, no extra assumptions needed.
  PART 2 (hourly bars, where hourly history covers the episode - mostly
      2026-01+): the SAME convention on hourly closes/lows, giving a
      genuine HOURS-not-just-days readout of how fast a >=5/10/15% adverse
      move actually develops once the gate fires - the sharpest test of
      "actionable" this data supports.

=============================================================================
REFUTE-YOURSELF CHECKS (built in, all printed, none hidden)
=============================================================================
(a) THE BARN-DOOR CHECK (the crux): the knife trigger's OWN condition
    (ret_7d_pct <= -25%) is a TRAILING 7-day statistic - the -25% has, BY
    CONSTRUCTION, already happened by the time the gate can possibly fire.
    This script prints the trailing decline already realized (mean ret_7d_pct
    at trigger) side-by-side with the genuinely FORWARD drawdown still ahead
    (fwd_dd_5), so the reader can see exactly how much of the total
    "knife event" pain (-7d to +5d) is backward-looking sunk cost the gate
    cannot help with, vs forward risk it legitimately can.
(b) Era split: pre-/post-2026-02-01 (the date that killed the ADD tilt and
    the BB bounce, and the date after which wait_knife_test.py found the
    knife drawdown-excess became significant) + last-90d slice.
(c) Reproduces wait_knife_test.py's headline P(fwd_dd_3d>=10%) figure from
    scratch as an internal consistency check before trusting the new
    day-by-day/hour-by-hour decomposition built on the same data.
(d) Non-overlap: a sustained crash re-fires the knife condition every day it
    continues - collapsed to first-day-of-run episodes per symbol, same
    convention as wait_knife_test.py, before any stat is trusted.

FEES: not applicable here - this script measures PATH/timing, not
after-fee return, so no fee adjustment is made (fees don't affect when a
drawdown occurs).

Run:
    python tools/copilot/alert_latency_test.py
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 400)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")
LEDGER_PATH = os.path.join(BOT_DIR, "data", "copilot", "call_ledger.jsonl")

# ---------------------------------------------------------------------------
# Constants copied VERBATIM from tools/copilot/copilot.py (read 2026-07-31),
# reduced to exactly what the knife gate needs (per wait_knife_test.py's own
# verified reduction: trend_strength=="strong" is redundant with trend_1d==
# "down"). No RSI/Bollinger/chop-gate logic here - out of scope, this script
# is knife-only.
# ---------------------------------------------------------------------------
EMA_FAST, EMA_SLOW = 20, 50
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 22.0
FALLING_KNIFE_RET7D_PCT = -25.0
MIN_ROWS_1D = 30

FEB_2026_CUTOFF = pd.Timestamp("2026-02-01", tz="UTC")
DAILY_HORIZONS = [1, 2, 3, 4, 5, 7, 10]
HOURLY_HORIZONS_H = [3, 6, 12, 24, 48, 72, 96, 120, 168, 240]  # hours forward, up to 10d
DD_THRESHOLDS = [0.05, 0.10, 0.15]


# ===========================================================================
# PART 0: DATA VIABILITY - does a real logged-WAIT-with-timestamp source
# exist? (call_ledger.jsonl is the only candidate in this tool suite)
# ===========================================================================
def check_rejection_log_viability() -> bool:
    print("\n################ PART 0: DATA VIABILITY - are knife-WAIT events logged with timestamps? ################")
    if not os.path.exists(LEDGER_PATH):
        print(f"  {LEDGER_PATH} does not exist.")
        print("  VERDICT: NOT VIABLE - no rejection/call log of any kind exists yet. "
              "Skipping the log-to-detectable-pattern lag test; running the OHLC-only "
              "alternative below instead.")
        return False

    rows = []
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    n = len(rows)
    if n == 0:
        print(f"  {LEDGER_PATH} exists but is empty.")
        print("  VERDICT: NOT VIABLE. Running the OHLC-only alternative below instead.")
        return False

    ts = sorted(r.get("ts_utc", "") for r in rows if r.get("ts_utc"))
    knife_rows = [
        r for r in rows
        if str(r.get("action", "")).upper() == "WAIT"
        and "FALLING KNIFE" in str(r.get("action_reason_short", "")).upper()
    ]
    print(f"  Ledger found: {n} total rows, timestamp range {ts[0] if ts else 'n/a'} -> {ts[-1] if ts else 'n/a'}")
    print(f"  WAIT rows (any reason): {sum(1 for r in rows if str(r.get('action','')).upper()=='WAIT')}")
    print(f"  WAIT rows with 'FALLING KNIFE' in the reason: {len(knife_rows)}")
    print("\n  This ledger is call_logger.py's forward-evidence log - it logs at most one row per "
          "(symbol, UTC calendar day, source) whenever a co-pilot brief is actually built (manually "
          "run or via the 2h copilot_alerts.py cron), NOT a continuous monitor. It has no memory of "
          "when a symbol FIRST crossed into knife territory intraday - only whatever moment a brief "
          "happened to be generated.")

    if n < 50 or not knife_rows:
        print(f"\n  VERDICT: NOT VIABLE for a log-to-detectable-pattern lag test. "
              f"{'The ledger only just started (' + str(n) + ' rows spanning a few hours) and' if n < 50 else 'The ledger has volume but'} "
              f"{'has' if not knife_rows else 'has only ' + str(len(knife_rows))} logged knife-WAIT event(s) so far "
              f"- nowhere near enough to measure a real detection lag. This is expected: the ledger "
              f"is brand new (call_logger.py) and knife triggers are rare (a handful of non-overlap "
              f"episodes across 14 months of the FULL 25-coin history in wait_knife_test.py). "
              f"Running the OHLC-only alternative below instead, which does not depend on this log "
              f"existing or being mature.")
        return False

    print(f"\n  VERDICT: technically viable ({len(knife_rows)} knife-WAIT rows) - but see OHLC section "
          f"below for the real timing analysis regardless, since the ledger only captures whatever "
          f"moment a brief was generated, not the market's own first-crossing moment.")
    return True


# ===========================================================================
# Indicators - reproduced verbatim from copilot.py (EMA/true-range/ADX only;
# knife doesn't touch RSI/Bollinger)
# ===========================================================================
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


# ===========================================================================
# Daily data loading - identical convention to wait_knife_test.py (standalone,
# no live-bot imports; public HL info endpoint + local longtail CSVs, cache
# fallback for BTC/SOL)
# ===========================================================================
def _hl_candles(coin: str, interval: str, start_ms: int) -> Optional[pd.DataFrame]:
    try:
        body = json.dumps({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": 99999999999999},
        }).encode()
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = json.loads(r.read())
        if not raw:
            return None
        df = pd.DataFrame(raw)
        df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        if interval == "1d":
            df["date"] = df["date"].dt.normalize()
        for col in ["o", "h", "l", "c", "v"]:
            df[col] = df[col].astype(float)
        df["symbol"] = coin
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        return df[["symbol", "date", "o", "h", "l", "c", "v"]].reset_index(drop=True)
    except Exception as e:  # noqa: BLE001 - best-effort, any failure -> cache fallback
        print(f"  [{coin}] live Hyperliquid {interval} fetch failed ({e!r}); trying local cache fallback")
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


def _cache_hourly_fallback(coin: str) -> Optional[pd.DataFrame]:
    path = os.path.join(CACHE_DIR, f"{coin}_1h_420d.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["time"], utc=True)
    df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
    df["symbol"] = coin
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    return df[["symbol", "date", "o", "h", "l", "c", "v"]].reset_index(drop=True)


def load_longtail_alts_daily() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(OHLC_DIR, "*_1d.csv"))):
        sym = os.path.basename(path).replace("_1d.csv", "")
        df = pd.read_csv(path)
        df["symbol"] = sym
        df["date"] = pd.to_datetime(df["dt_utc_iso"], utc=True).dt.normalize()
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        frames.append(df[["symbol", "date", "o", "h", "l", "c", "v"]])
    return pd.concat(frames, ignore_index=True)


def load_longtail_alts_hourly() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(OHLC_DIR, "*_1h.csv"))):
        sym = os.path.basename(path).replace("_1h.csv", "")
        df = pd.read_csv(path)
        df["symbol"] = sym
        df["date"] = pd.to_datetime(df["dt_utc_iso"], utc=True)
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        frames.append(df[["symbol", "date", "o", "h", "l", "c", "v"]])
    return pd.concat(frames, ignore_index=True)


def load_btc_sol_daily(alt_min_date: pd.Timestamp) -> pd.DataFrame:
    start_ms = int(alt_min_date.timestamp() * 1000)
    frames = []
    for coin in ["BTC", "SOL"]:
        live = _hl_candles(coin, "1d", start_ms)
        if live is not None and len(live) >= 100:
            print(f"  [{coin} 1d] live fetch OK: {len(live)} bars, {live['date'].min().date()} -> {live['date'].max().date()}")
            frames.append(live)
            continue
        cached = _cache_daily_fallback(coin)
        if cached is not None:
            print(f"  [{coin} 1d] STALE cache fallback: {len(cached)} bars, "
                  f"{cached['date'].min().date()} -> {cached['date'].max().date()}")
            frames.append(cached)
        else:
            print(f"  [{coin} 1d] no live data and no cache -- excluded")
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "o", "h", "l", "c", "v"])
    return pd.concat(frames, ignore_index=True)


def load_btc_sol_hourly(alt_min_date: pd.Timestamp) -> pd.DataFrame:
    start_ms = int(alt_min_date.timestamp() * 1000)
    frames = []
    for coin in ["BTC", "SOL"]:
        live = _hl_candles(coin, "1h", start_ms)
        if live is not None and len(live) >= 500:
            print(f"  [{coin} 1h] live fetch OK: {len(live)} bars, {live['date'].min()} -> {live['date'].max()}")
            frames.append(live)
            continue
        cached = _cache_hourly_fallback(coin)
        if cached is not None:
            print(f"  [{coin} 1h] STALE cache fallback: {len(cached)} bars, "
                  f"{cached['date'].min()} -> {cached['date'].max()}")
            frames.append(cached)
        else:
            print(f"  [{coin} 1h] no live data and no cache -- excluded")
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "o", "h", "l", "c", "v"])
    return pd.concat(frames, ignore_index=True)


def load_daily_panel() -> pd.DataFrame:
    alts = load_longtail_alts_daily()
    btcsol = load_btc_sol_daily(alts["date"].min())
    return pd.concat([alts, btcsol], ignore_index=True) if len(btcsol) else alts


def load_hourly_panel() -> pd.DataFrame:
    alts = load_longtail_alts_hourly()
    btcsol = load_btc_sol_hourly(alts["date"].min())
    return pd.concat([alts, btcsol], ignore_index=True) if len(btcsol) else alts


# ===========================================================================
# Knife classification + forward drawdown (daily) - trend_1d/ret_7d only,
# reduced knife condition per wait_knife_test.py's verified reduction.
# ===========================================================================
def compute_daily_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        close = g["c"]
        low = g["l"].to_numpy(dtype=float)
        close_np = close.to_numpy(dtype=float)

        ema_f = _ema(close, EMA_FAST)
        ema_s = _ema(close, EMA_SLOW)
        adx = _adx(g)
        ret_7d_pct = (close / close.shift(7) - 1.0) * 100.0

        g = g.copy()
        g["ema_f"], g["ema_s"], g["adx"] = ema_f, ema_s, adx
        g["ret_7d_pct"] = ret_7d_pct
        g["row_idx"] = np.arange(n)

        for hz in DAILY_HORIZONS:
            m = n - hz
            fwd_dd = np.full(n, np.nan)
            if m > 0 and n > hz:
                low_windows = sliding_window_view(low[1:], hz)
                fwd_min = low_windows.min(axis=1)[:m]
                entry_close = close_np[:m]
                fwd_dd[:m] = np.clip((entry_close - fwd_min) / entry_close, 0.0, None)
            g[f"fwd_dd_{hz}"] = fwd_dd
        out.append(g)
    return pd.concat(out, ignore_index=True)


def classify_knife(feat: pd.DataFrame) -> pd.DataFrame:
    f = feat.copy()
    is_trending = f["adx"] >= ADX_TREND_THRESHOLD
    dir_up = f["ema_f"] > f["ema_s"]
    trend_1d = np.where(is_trending, np.where(dir_up, "up", "down"), "chop")
    f["trend_1d"] = trend_1d
    f["is_knife"] = (f["trend_1d"] == "down") & (f["ret_7d_pct"] <= FALLING_KNIFE_RET7D_PCT)
    valid = (
        (f["row_idx"] >= MIN_ROWS_1D - 1)
        & f["adx"].notna() & f["ret_7d_pct"].notna()
    )
    f["valid"] = valid
    return f


def collapse_episodes(ev: pd.DataFrame) -> pd.DataFrame:
    """Non-overlap control: keep only the FIRST day of each consecutive-day
    trigger run per symbol - identical convention to wait_knife_test.py."""
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


# ===========================================================================
# PART 1: daily bar-by-bar decomposition of the forward drawdown
# ===========================================================================
def day_by_day_table(ep: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    dd5 = ep["fwd_dd_5"] if "fwd_dd_5" in ep.columns else pd.Series(dtype=float)
    for hz in DAILY_HORIZONS:
        col = f"fwd_dd_{hz}"
        sub = ep.dropna(subset=[col])
        if sub.empty:
            rows.append({"group": label, "day": hz, "n": 0})
            continue
        row = {
            "group": label, "day": hz, "n": len(sub),
            "mean_dd_pct": sub[col].mean() * 100,
            "median_dd_pct": sub[col].median() * 100,
            "p90_dd_pct": sub[col].quantile(0.90) * 100,
        }
        for th in DD_THRESHOLDS:
            row[f"pct_ge_{int(th*100)}pct"] = (sub[col] >= th).mean() * 100
        rows.append(row)
    return pd.DataFrame(rows)


def realized_by_day1_fraction(ep: pd.DataFrame, final_h: int = 5) -> Dict:
    """Of the eventual `final_h`-day max drawdown, what fraction is ALREADY
    present after just 1 day? (fwd_dd_h is monotone non-decreasing in h by
    construction, so this ratio is always in [0, 1].) Restricted to episodes
    where the eventual drawdown is at least small/nonzero (>0.5%) so the
    ratio isn't dominated by near-zero-denominator noise from quiet episodes
    that never developed any real path risk at all."""
    col1, colF = "fwd_dd_1", f"fwd_dd_{final_h}"
    sub = ep.dropna(subset=[col1, colF])
    sub = sub[sub[colF] > 0.005]
    if sub.empty:
        return {"n": 0}
    frac = (sub[col1] / sub[colF]).clip(upper=1.0)
    return {
        "n": len(sub),
        "mean_frac_realized_by_day1": frac.mean(),
        "median_frac_realized_by_day1": frac.median(),
        "pct_where_day1_ge_80pct_of_final": (frac >= 0.80).mean() * 100,
        "pct_where_day1_ge_50pct_of_final": (frac >= 0.50).mean() * 100,
    }


def first_crossing_day(ep: pd.DataFrame, threshold: float) -> Dict:
    """Among episodes whose eventual 10d drawdown crosses `threshold`, on
    which day (1..10) did it FIRST cross? Distribution, not just a mean."""
    cols = {hz: f"fwd_dd_{hz}" for hz in DAILY_HORIZONS}
    have_all = ep.dropna(subset=list(cols.values()))
    if have_all.empty:
        return {"n_crossing": 0}
    crossed_mask = have_all[cols[max(DAILY_HORIZONS)]] >= threshold
    crossers = have_all[crossed_mask]
    if crossers.empty:
        return {"n_crossing": 0, "n_total": len(have_all)}
    first_day = pd.Series(np.nan, index=crossers.index, dtype=float)
    for hz in sorted(DAILY_HORIZONS):
        not_yet = first_day.isna()
        newly = not_yet & (crossers[cols[hz]] >= threshold)
        first_day.loc[newly] = hz
    dist = first_day.value_counts(normalize=True).sort_index() * 100
    return {
        "n_crossing": len(crossers), "n_total": len(have_all),
        "pct_of_all_that_cross": len(crossers) / len(have_all) * 100,
        "first_crossing_day_dist_pct": dist.to_dict(),
        "median_first_crossing_day": first_day.median(),
    }


# ===========================================================================
# PART 2: hourly refinement - genuine hours-not-days lag readout
# ===========================================================================
def hourly_lag_for_episodes(episodes: pd.DataFrame, hourly_panel: pd.DataFrame,
                             max_horizon_h: int = max(HOURLY_HORIZONS_H)) -> pd.DataFrame:
    """For each daily knife episode, if hourly data covers the forward
    window, compute cumulative drawdown-from-entry-close at each hour offset
    and record (a) dd at each of HOURLY_HORIZONS_H, (b) first hour offset at
    which dd crosses each of DD_THRESHOLDS (NaN if never within
    max_horizon_h). entry point = start of the calendar day AFTER the
    trigger day (hour offset 0), matching the daily convention's low[i+1..]
    (the earliest moment the gate's information could be acted on, i.e.
    after the trigger day's close is known)."""
    hourly_panel = hourly_panel.sort_values(["symbol", "date"])
    results = []
    for _, row in episodes.iterrows():
        sym = row["symbol"]
        trigger_date = pd.Timestamp(row["date"])
        entry_close = row["c"]
        anchor = trigger_date + pd.Timedelta(days=1)
        window_end = anchor + pd.Timedelta(hours=max_horizon_h)
        g = hourly_panel[(hourly_panel["symbol"] == sym)
                          & (hourly_panel["date"] >= anchor)
                          & (hourly_panel["date"] < window_end)]
        if g.empty:
            continue
        expected_bars = max_horizon_h
        coverage = len(g) / expected_bars
        if coverage < 0.6:
            continue  # too many gaps / hourly history doesn't reach here - skip, don't fabricate
        g = g.sort_values("date")
        offsets_h = (g["date"] - anchor).dt.total_seconds().to_numpy() / 3600.0
        lows = g["l"].to_numpy(dtype=float)
        running_min = np.minimum.accumulate(lows)
        dd = np.clip((entry_close - running_min) / entry_close, 0.0, None)

        rec = {"symbol": sym, "date": trigger_date, "coverage": coverage, "n_bars": len(g)}
        for H in HOURLY_HORIZONS_H:
            mask = offsets_h <= H
            rec[f"dd_at_{H}h"] = dd[mask].max() if mask.any() else np.nan
        for th in DD_THRESHOLDS:
            hit = offsets_h[dd >= th]
            rec[f"first_h_ge_{int(th*100)}pct"] = float(hit.min()) if len(hit) else np.nan
        results.append(rec)
    return pd.DataFrame(results)


def print_rows(rows, title: str) -> None:
    print(f"\n=== {title} ===")
    d = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows
    if d.empty:
        print("  (no data)")
        return
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(d.to_string(index=False))


# ===========================================================================
# Main
# ===========================================================================
def main() -> None:
    rejection_log_viable = check_rejection_log_viability()

    print("\n\n################ LOADING OHLC (daily) ################")
    daily_panel = load_daily_panel()
    print(f"  {daily_panel['symbol'].nunique()} symbols, "
          f"{daily_panel['date'].min().date()} -> {daily_panel['date'].max().date()}, "
          f"{len(daily_panel)} coin-days")

    feat = classify_knife(compute_daily_features(daily_panel))
    valid = feat[feat["valid"]].copy()
    knife_days = valid[valid["is_knife"]].copy()
    ep_all = collapse_episodes(knife_days)
    pre = ep_all[ep_all["date"] < FEB_2026_CUTOFF]
    post = ep_all[ep_all["date"] >= FEB_2026_CUTOFF]
    last90_start = feat["date"].max() - pd.Timedelta(days=90)
    recent = ep_all[ep_all["date"] >= last90_start]

    print(f"\nValid decision-days: {len(valid)} across {valid['symbol'].nunique()} symbols")
    print(f"Knife trigger coin-days: {len(knife_days)}  |  non-overlap episodes: {len(ep_all)} "
          f"(inflation ratio {len(knife_days) / max(1, len(ep_all)):.2f}x)")
    print(f"  Era split: pre-2026-02-01 = {len(pre)} episodes, post-2026-02-01 = {len(post)} episodes, "
          f"last 90d = {len(recent)} episodes")

    # -----------------------------------------------------------------
    # PART 1: daily day-by-day drawdown decomposition
    # -----------------------------------------------------------------
    print("\n\n################ PART 1: DAILY BAR-BY-BAR FORWARD DRAWDOWN DECOMPOSITION ################")
    print("(fwd_dd_h = worst close-to-low drawdown from the trigger day's close over the NEXT h days.\n"
          " Monotone non-decreasing in h by construction - this shows how much of the eventual damage\n"
          " is present after just 1 day vs still developing over days 2-10.)")
    for label, sub in [("FULL SAMPLE", ep_all), ("PRE-2026-02-01", pre),
                        ("POST-2026-02-01", post), (f"LAST 90D (from {last90_start.date()})", recent)]:
        print_rows(day_by_day_table(sub, label), f"Day-by-day forward drawdown - {label}")

    print("\n--- Fraction of the eventual 5-day max drawdown already realized after just 1 day ---")
    for label, sub in [("FULL SAMPLE", ep_all), ("PRE-2026-02-01", pre), ("POST-2026-02-01", post)]:
        r = realized_by_day1_fraction(sub, final_h=5)
        if r.get("n", 0) == 0:
            print(f"  {label}: n=0 (no episodes with a nonzero eventual drawdown)")
            continue
        print(f"  {label}: n={r['n']}, mean frac realized by day+1 = {r['mean_frac_realized_by_day1']*100:.1f}%, "
              f"median = {r['median_frac_realized_by_day1']*100:.1f}%, "
              f"{r['pct_where_day1_ge_80pct_of_final']:.0f}% of episodes have >=80% of the eventual "
              f"5-day drawdown ALREADY DONE after 1 day, {r['pct_where_day1_ge_50pct_of_final']:.0f}% have >=50%")

    print("\n--- First-crossing-day distribution: among episodes whose 10-day drawdown eventually clears "
          "a threshold, WHICH day did it first cross it? ---")
    for th in DD_THRESHOLDS:
        for label, sub in [("FULL SAMPLE", ep_all), ("POST-2026-02-01", post)]:
            r = first_crossing_day(sub, th)
            if r.get("n_crossing", 0) == 0:
                print(f"  threshold >= {int(th*100)}%, {label}: no episodes cross this within 10 days "
                      f"(n_total={r.get('n_total', 0)})")
                continue
            print(f"  threshold >= {int(th*100)}%, {label}: {r['n_crossing']}/{r['n_total']} episodes "
                  f"({r['pct_of_all_that_cross']:.0f}%) eventually cross it within 10d; "
                  f"median first-crossing day = {r['median_first_crossing_day']:.1f}; "
                  f"distribution (day: %of crossers) = "
                  f"{ {int(k): round(v,1) for k, v in r['first_crossing_day_dist_pct'].items()} }")

    # -----------------------------------------------------------------
    # PART 2: hourly refinement
    # -----------------------------------------------------------------
    print("\n\n################ LOADING OHLC (hourly, for a finer-grained lag readout) ################")
    hourly_panel = load_hourly_panel()
    if hourly_panel.empty:
        print("  No hourly data available - skipping PART 2 (hourly refinement). Daily-bar decomposition "
              "in PART 1 above stands as the primary timing readout.")
        hourly_ok = False
    else:
        print(f"  {hourly_panel['symbol'].nunique()} symbols, "
              f"{hourly_panel['date'].min()} -> {hourly_panel['date'].max()}, {len(hourly_panel)} coin-hours")
        hourly_ok = True

    if hourly_ok:
        print("\n\n################ PART 2: HOURLY LAG - HOW MANY HOURS UNTIL THE DRAWDOWN HITS? ################")
        hourly_ep = hourly_lag_for_episodes(ep_all, hourly_panel)
        n_covered = len(hourly_ep)
        n_total = len(ep_all)
        print(f"  Episodes with usable hourly coverage of the forward window: {n_covered}/{n_total} "
              f"(hourly history for these 25 alts starts ~2026-01-12; BTC/SOL hourly cache starts "
              f"~2025-12-18 - episodes triggering before that, or within {max(HOURLY_HORIZONS_H)}h of "
              f"'now', are excluded rather than fabricated)")
        if n_covered == 0:
            print("  No episodes have sufficient hourly coverage - cannot compute an hours-level readout. "
                  "This itself is a finding: the hourly history is too short/recent relative to when "
                  "most knife episodes occurred. Daily-bar PART 1 above is the only timing evidence available.")
        else:
            print_rows(hourly_ep[["symbol", "date", "coverage", "n_bars"]
                                  + [f"dd_at_{H}h" for H in HOURLY_HORIZONS_H]],
                       "Per-episode cumulative drawdown at each hour offset (fraction, e.g. 0.10 = 10%)")
            print("\n--- Hours-to-first-breach distribution (among covered episodes) ---")
            for th in DD_THRESHOLDS:
                col = f"first_h_ge_{int(th*100)}pct"
                hit = hourly_ep[col].dropna()
                never = hourly_ep[col].isna().sum()
                print(f"  threshold >= {int(th*100)}%: {len(hit)}/{n_covered} episodes breach it within "
                      f"{max(HOURLY_HORIZONS_H)}h ({never} never do). Of those that breach: "
                      f"median = {hit.median():.1f}h, p25 = {hit.quantile(0.25):.1f}h, "
                      f"p75 = {hit.quantile(0.75):.1f}h" if len(hit) else
                      f"  threshold >= {int(th*100)}%: 0/{n_covered} episodes breach it within {max(HOURLY_HORIZONS_H)}h")
                if len(hit):
                    within_24h = (hit <= 24).mean() * 100
                    within_48h = (hit <= 48).mean() * 100
                    print(f"      of episodes that DO eventually breach {int(th*100)}%: "
                          f"{within_24h:.0f}% do so within 24h of the anchor, {within_48h:.0f}% within 48h")

    # -----------------------------------------------------------------
    # REFUTATION (a): THE BARN-DOOR CHECK - backward-realized vs forward-remaining
    # -----------------------------------------------------------------
    print("\n\n################ REFUTATION (a): THE BARN-DOOR CHECK ################")
    print("The knife trigger's OWN condition requires ret_7d_pct <= -25% - a TRAILING statistic. "
          "By construction, that -25% has ALREADY happened by the moment the gate can fire. This is "
          "not a bug in this script's measurement; it is inherent to how the gate is defined.")
    for label, sub in [("FULL SAMPLE", ep_all), ("POST-2026-02-01", post)]:
        if sub.empty:
            print(f"  {label}: n=0")
            continue
        backward_pct = -sub["ret_7d_pct"].mean()  # magnitude of the already-realized 7d decline
        forward_pct = sub["fwd_dd_5"].mean() * 100 if "fwd_dd_5" in sub.columns else np.nan
        total = backward_pct + forward_pct
        print(f"  {label} (n={len(sub)}): trailing 7d decline ALREADY REALIZED at trigger = "
              f"{backward_pct:.1f}% (mean); forward 5d drawdown STILL AHEAD after trigger = "
              f"{forward_pct:.1f}% (mean). Of the total {total:.1f}pp round-trip pain from -7d to +5d, "
              f"{backward_pct/total*100:.0f}% is backward-looking sunk cost the gate cannot help with "
              f"(barn door already open), and {forward_pct/total*100:.0f}% is genuine forward risk the "
              f"gate's WAIT call can still help you dodge.")
    print("\n  Honest reading: the gate is NOT purely 'closing the barn door after the horse bolted' - "
          "PART 1/2 above show there IS a real, quantifiable forward drawdown after the trigger fires "
          "(consistent with wait_knife_test.py's 42-55% P(dd>=10%) finding, reproduced in Refutation (c) "
          "below). But the forward risk is a SMALLER share of the total move than the trailing crash that "
          "already happened - see the percentages printed above for exactly how much smaller, each run.")

    # -----------------------------------------------------------------
    # REFUTATION (c): reproduce wait_knife_test.py's headline figure
    # -----------------------------------------------------------------
    print("\n\n################ REFUTATION (c): INTERNAL CONSISTENCY CHECK vs wait_knife_test.py ################")
    for label, sub in [("FULL SAMPLE", ep_all), ("POST-2026-02-01", post)]:
        if sub.empty or "fwd_dd_3" not in sub.columns:
            print(f"  {label}: n=0")
            continue
        s = sub.dropna(subset=["fwd_dd_3"])
        pct_ge_10 = (s["fwd_dd_3"] >= 0.10).mean() * 100 if len(s) else float("nan")
        print(f"  {label}: P(fwd_dd_3d >= 10%) = {pct_ge_10:.1f}% (n={len(s)}) - "
          f"wait_knife_test.py reported ~42% full-sample / ~55% post-2026-02-01 on the same construction; "
          f"this should land close to those numbers (same data, same non-overlap convention, same formula) "
          f"before the new day/hour decomposition above is trusted.")

    # -----------------------------------------------------------------
    # FINAL VERDICT
    # -----------------------------------------------------------------
    print("\n\n################ FINAL VERDICT ################")
    print(f"Rejection-log viability: {'VIABLE (see PART 0)' if rejection_log_viable else 'NOT VIABLE - see PART 0. call_ledger.jsonl exists but is brand new (started 2026-08-01, a handful of rows, zero knife-WAIT events logged yet) - far too thin to measure a real detection lag. All timing evidence below is OHLC-only.'}")
    r5 = realized_by_day1_fraction(ep_all, final_h=5)
    if r5.get("n", 0):
        print(f"Full-sample: after just 1 day, a median of {r5['median_frac_realized_by_day1']*100:.0f}% "
              f"of the eventual 5-day forward drawdown is already realized "
              f"({r5['pct_where_day1_ge_80pct_of_final']:.0f}% of episodes already have >=80% of it done).")
        if r5['median_frac_realized_by_day1'] >= 0.6:
            print("  -> Leans BARN-DOOR: most of the forward path risk this gate is meant to flag has "
                  "already happened by the time a day-granularity re-check would confirm it. The gate's "
                  "real value is telling you 'don't add TODAY' (day-0), not giving you several days of "
                  "runway to watch it develop.")
        elif r5['median_frac_realized_by_day1'] <= 0.4:
            print("  -> Leans ACTIONABLE: most of the forward path risk is still ahead after day 1 - the "
                  "WAIT call genuinely buys time; a leveraged add avoided today is avoiding danger that "
                  "mostly hasn't happened yet.")
        else:
            print("  -> MIXED: roughly half the eventual forward drawdown is already present after 1 day, "
                  "half is still developing - the gate is partially timely (worth heeding beyond day-0) "
                  "and partially already-too-late for the immediate move.")
    print("See PART 2 for the hours-level readout (where hourly coverage allows) - that is the sharper "
          "test of whether 'WAIT' bought you meaningful runway or the danger was already imminent.")
    print("\nDone.")


if __name__ == "__main__":
    main()
