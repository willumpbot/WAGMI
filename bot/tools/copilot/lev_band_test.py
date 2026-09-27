#!/usr/bin/env python
"""
lev_band_test.py - OOS liquidation-rate audit of copilot.py's vol-derived
SAFE-MAX-LEVERAGE band.
=============================================================================
READ-ONLY research script. Never imports/writes live-bot state. Imports the
REAL compute_realized_vol / compute_liquidation functions straight from
tools/copilot/copilot.py (no formula re-transcription) so the mechanic under
test is byte-for-byte what the co-pilot actually recommends.

QUESTION: does opening a position at the co-pilot's recommended
safe_max_leverage actually keep the hold un-liquidated on ~95% of holds
(its designed target), out-of-sample, better than naive fixed 5x/10x/20x?

METHOD (entry-time-safe, no look-ahead):
  - For each coin, walk daily bars. At entry day t, compute realized vol
    (and hence safe_max_leverage) using ONLY returns from a window ending at
    t (capped at copilot's own DAYS_1D=200 lookback, matching live behavior).
  - The FIRST HALF of each coin's history is treated as the
    "warmup/calibration era" and excluded from reported entries. All
    reported entries come from the SECOND HALF only - true OOS w.r.t. the
    tail-risk statistic's own learning period.
  - Open a hypothetical LONG and a SHORT at close[t]. Hold H in {3,5} days.
    Liquidated if the daily low (long) / high (short) over the hold window
    touches the liq price computed by the SAME compute_liquidation() used
    live. Daily OHLC is the primary proxy; a secondary pass re-checks the
    subset of entries with hourly coverage using hourly low/high to quantify
    how much the daily-bar proxy under-counts intra-day wicks.
  - Real per-asset HL maintenance margin (mm = 1/(2*maxLeverage)) is used,
    fetched ONCE (current `meta`) and held constant across the backtest -
    caveat: this assumes HL's leverage tiers for these assets didn't
    materially change over the sample window (can't be verified
    retroactively from public `meta`, which only exposes the CURRENT table).
    A flat-2% fallback-mm variant is also computed for sensitivity.

Usage:
    python tools/copilot/lev_band_test.py [--symbols SYM,SYM,...] [--refresh]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BOT_DIR, "tools", "copilot"))
sys.path.insert(0, os.path.join(BOT_DIR, "data", "fetchers"))

from copilot import compute_realized_vol, compute_liquidation, RealizedVol, DAYS_1D, SAFE_LEV_CAP  # noqa: E402
from hl_native import HLNative  # noqa: E402

LONGTAIL_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
SCRATCH_DIR = r"C:\Users\vince\AppData\Local\Temp\claude\C--Users-vince\6fad1965-9726-4e6a-b6d6-9dcf0b9f2c97\scratchpad\lev_band_cache"
os.makedirs(SCRATCH_DIR, exist_ok=True)

WINDOW_CAP = DAYS_1D          # 200 - same lookback cap the live tool uses
MIN_SAMPLE = 20               # matches copilot's own n>=20 gate for pct95
HOLDS = [1, 3, 5]
LIVE_FETCH_SYMBOLS = ["BTC", "SOL"]  # not in the longtail CSV set; fetch live


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _candles_to_df(candles):
    if not candles:
        return None
    df = pd.DataFrame(candles)
    df = df.rename(columns={"t": "t_ms"})
    for c in ("o", "h", "l", "c", "v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["t"] = pd.to_datetime(df["t_ms"], unit="ms", utc=True)
    df = df.dropna(subset=["o", "h", "l", "c"]).sort_values("t").reset_index(drop=True)
    return df[["t", "o", "h", "l", "c", "v"]]


def _load_csv(path):
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["t"] = pd.to_datetime(df["dt_utc_iso"], utc=True)
    for c in ("o", "h", "l", "c", "v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["o", "h", "l", "c"]).sort_values("t").reset_index(drop=True)
    return df[["t", "o", "h", "l", "c", "v"]]


def fetch_live_daily(client, symbol, days=420, refresh=False):
    cache = os.path.join(SCRATCH_DIR, f"{symbol}_1d.csv")
    if os.path.exists(cache) and not refresh:
        return _load_csv_generic(cache)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 24 * 3600 * 1000
    candles = client.candles(symbol, "1d", start_ms, now_ms)
    df = _candles_to_df(candles)
    if df is not None:
        df.to_csv(cache, index=False)
    return df


def fetch_live_hourly(client, symbol, days=210, refresh=False):
    cache = os.path.join(SCRATCH_DIR, f"{symbol}_1h.csv")
    if os.path.exists(cache) and not refresh:
        return _load_csv_generic(cache)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 24 * 3600 * 1000
    candles = client.candles(symbol, "1h", start_ms, now_ms)
    df = _candles_to_df(candles)
    if df is not None:
        df.to_csv(cache, index=False)
    return df


def _load_csv_generic(path):
    df = pd.read_csv(path)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    for c in ("o", "h", "l", "c", "v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["o", "h", "l", "c"]).sort_values("t").reset_index(drop=True)


def load_1h_longtail(symbol):
    return _load_csv(os.path.join(LONGTAIL_DIR, f"{symbol}_1h.csv"))


def discover_longtail_symbols():
    syms = []
    for fn in os.listdir(LONGTAIL_DIR):
        if fn.endswith("_1d.csv"):
            syms.append(fn[: -len("_1d.csv")])
    return sorted(syms)


# ---------------------------------------------------------------------------
# Core walk-forward loop
# ---------------------------------------------------------------------------
def hourly_extreme(hdf, t0, t1, is_long):
    """Min low / max high in hourly bars covering [t0, t1) (t1 exclusive).
    Returns None if hourly coverage doesn't fully span the window."""
    if hdf is None:
        return None
    win = hdf[(hdf["t"] >= t0) & (hdf["t"] < t1)]
    if win.empty:
        return None
    # require at least ~20 bars/day coverage to trust it as "full" coverage
    span_days = (t1 - t0).total_seconds() / 86400.0
    if len(win) < max(1, int(span_days * 20)):
        return None
    return win["l"].min() if is_long else win["h"].max()


def run_symbol(symbol, df, hl_max_leverage, hdf=None):
    """Returns list of record dicts for this symbol."""
    n = len(df)
    half = n // 2
    start_t = max(half, MIN_SAMPLE)
    max_h = max(HOLDS)
    records = []
    for t in range(start_t, n - max_h):
        entry_price = float(df["c"].iloc[t])
        entry_date = df["t"].iloc[t]
        w_start = max(0, t + 1 - WINDOW_CAP)
        window_df = df.iloc[w_start : t + 1].reset_index(drop=True)
        vol = compute_realized_vol(window_df)
        if vol.pct95_daily_drop_pct is None:
            continue

        # Safe-max-leverage under REAL current per-asset mm, and under the
        # flat 2% fallback mm (sensitivity / pre-2026-07-31 behavior).
        lr_real = compute_liquidation(entry_price, "LONG", 1.0, vol, hl_max_leverage, symbol)
        lr_flat = compute_liquidation(entry_price, "LONG", 1.0, vol, None, symbol)
        safe_real = lr_real.safe_max_leverage
        safe_flat = lr_flat.safe_max_leverage

        for side in ("LONG", "SHORT"):
            lev_variants = [
                ("safe", safe_real, hl_max_leverage),
                ("safe_flatmm", safe_flat, None),
                ("5x", 5.0, hl_max_leverage),
                ("10x", 10.0, hl_max_leverage),
                ("20x", 20.0, hl_max_leverage),
            ]
            for lev_label, lev, hlmax_for_calc in lev_variants:
                lr = compute_liquidation(entry_price, side, lev, vol, hlmax_for_calc, symbol)
                for H in HOLDS:
                    hold = df.iloc[t + 1 : t + 1 + H]
                    if len(hold) < H:
                        continue
                    is_long = side == "LONG"
                    if is_long:
                        daily_extreme = hold["l"].min()
                        liq_daily = daily_extreme <= lr.liq_price
                    else:
                        daily_extreme = hold["h"].max()
                        liq_daily = daily_extreme >= lr.liq_price

                    hourly_ex = None
                    liq_hourly = None
                    if hdf is not None:
                        # Hold window is calendar days [t+1 .. t+H] inclusive
                        # (same days the daily-proxy check uses) - i.e. hourly
                        # bars from the start of day t+1 through the END of
                        # day t+H (exclusive upper bound = start of day t+H+1).
                        t0 = df["t"].iloc[t + 1]
                        t1 = df["t"].iloc[t + H] + pd.Timedelta(days=1)
                        hourly_ex = hourly_extreme(hdf, t0, t1, is_long)
                        if hourly_ex is not None:
                            liq_hourly = (hourly_ex <= lr.liq_price) if is_long else (hourly_ex >= lr.liq_price)

                    records.append(
                        dict(
                            symbol=symbol,
                            t=t,
                            entry_date=entry_date,
                            era=entry_date.strftime("%Y-%m"),
                            side=side,
                            H=H,
                            lev_label=lev_label,
                            leverage=lev,
                            exceeds_venue=(hl_max_leverage is not None and lev > hl_max_leverage),
                            past_liq_line=lr.past_liq_line if hasattr(lr, "past_liq_line") else (lr.distance_pct == 0.0),
                            distance_pct=lr.distance_pct,
                            liquidated=bool(liq_daily),
                            liquidated_hourly=(bool(liq_hourly) if liq_hourly is not None else None),
                        )
                    )
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    client = HLNative()
    print("[lev_band_test] fetching HL meta (real per-asset maxLeverage)...", file=sys.stderr)
    meta = client.meta()
    universe = {a["name"]: a for a in (meta or {}).get("universe", []) if "name" in a}
    hl_max = {}
    for name, a in universe.items():
        try:
            v = float(a.get("maxLeverage"))
            if v > 0:
                hl_max[name] = v
        except (TypeError, ValueError):
            pass

    longtail_syms = discover_longtail_symbols()
    all_syms = longtail_syms + LIVE_FETCH_SYMBOLS
    if args.symbols:
        want = set(s.strip() for s in args.symbols.split(","))
        all_syms = [s for s in all_syms if s in want]

    all_records = []
    coverage = []
    for sym in all_syms:
        if sym in LIVE_FETCH_SYMBOLS:
            df = fetch_live_daily(client, sym, refresh=args.refresh)
            hdf = fetch_live_hourly(client, sym, refresh=args.refresh)
        else:
            df = _load_csv(os.path.join(LONGTAIL_DIR, f"{sym}_1d.csv"))
            hdf = load_1h_longtail(sym)
        if df is None or len(df) < MIN_SAMPLE + max(HOLDS) + 5:
            print(f"[lev_band_test] SKIP {sym}: insufficient daily data", file=sys.stderr)
            continue
        hlmax = hl_max.get(sym)
        recs = run_symbol(sym, df, hlmax, hdf=hdf)
        all_records.extend(recs)
        coverage.append((sym, len(df), df["t"].iloc[0].date(), df["t"].iloc[-1].date(), hlmax, hdf is not None and len(hdf) if hdf is not None else 0))
        print(f"[lev_band_test] {sym}: n_days={len(df)} hl_max={hlmax} hourly_rows={len(hdf) if hdf is not None else 0} -> {len(recs)} records", file=sys.stderr)

    rec_df = pd.DataFrame(all_records)
    out_csv = os.path.join(SCRATCH_DIR, "lev_band_test_records.csv")
    rec_df.to_csv(out_csv, index=False)
    print(f"\n[lev_band_test] wrote {len(rec_df)} records -> {out_csv}\n")

    # -----------------------------------------------------------------
    # Coverage table
    # -----------------------------------------------------------------
    print("=" * 100)
    print("COVERAGE (per symbol)")
    print("=" * 100)
    cov_df = pd.DataFrame(coverage, columns=["symbol", "n_days", "start", "end", "hl_max_lev", "hourly_rows"])
    print(cov_df.to_string(index=False))

    # -----------------------------------------------------------------
    # 1) Main OOS liquidation-rate table: lev_label x H x side
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("1) OOS LIQUIDATION RATE (second-half-of-history entries only), daily-low/high proxy")
    print("=" * 100)
    agg = (
        rec_df.groupby(["lev_label", "H", "side"])
        .agg(n=("liquidated", "size"), liq_rate=("liquidated", "mean"))
        .reset_index()
    )
    agg["liq_rate_pct"] = (agg["liq_rate"] * 100).round(2)
    order = {"safe": 0, "safe_flatmm": 1, "5x": 2, "10x": 3, "20x": 4}
    agg["ord"] = agg["lev_label"].map(order)
    agg = agg.sort_values(["H", "side", "ord"]).drop(columns=["ord", "liq_rate"])
    print(agg.to_string(index=False))

    # -----------------------------------------------------------------
    # 2) Recommended safe-leverage distribution (real mm)
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("2) RECOMMENDED SAFE-MAX-LEVERAGE DISTRIBUTION (real per-asset mm, across all OOS entry-days)")
    print("=" * 100)
    safe_rows = rec_df[(rec_df["lev_label"] == "safe") & (rec_df["side"] == "LONG") & (rec_df["H"] == HOLDS[0])]
    print(safe_rows["leverage"].describe().to_string())
    bins = [0, 1.5, 2.5, 5, 10, 15, 20, 100]
    labels = ["<=1x", "1.5-2x", "2.5-5x", "5-10x", "10-15x", "15-20x", ">20x(cap)"]
    cats = pd.cut(safe_rows["leverage"], bins=bins, labels=labels, right=True)
    print("\nHistogram of recommended safe leverage (all coin-days):")
    print(cats.value_counts().sort_index().to_string())

    print("\nPer-symbol MEDIAN recommended safe leverage (real mm) vs HL max:")
    med = (
        safe_rows.groupby("symbol")
        .agg(median_safe_lev=("leverage", "median"), n=("leverage", "size"))
        .reset_index()
    )
    med["hl_max_lev"] = med["symbol"].map(hl_max)
    print(med.sort_values("median_safe_lev").to_string(index=False))

    # -----------------------------------------------------------------
    # 3) Per-era breakdown for the safe band (regime-robustness check)
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("3) PER-ERA LIQUIDATION RATE, safe band only (H=3 shown, both sides pooled)")
    print("=" * 100)
    era_rows = rec_df[(rec_df["lev_label"] == "safe") & (rec_df["H"] == 3)]
    era_agg = era_rows.groupby("era").agg(n=("liquidated", "size"), liq_rate_pct=("liquidated", lambda x: round(x.mean() * 100, 2)))
    print(era_agg.to_string())

    # -----------------------------------------------------------------
    # 4) Daily-proxy vs hourly-precise robustness check (subset w/ hourly coverage)
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("4) DAILY-LOW PROXY vs HOURLY-PRECISE liquidation check (safe band, subset with full hourly coverage)")
    print("=" * 100)
    hr_rows = rec_df[(rec_df["lev_label"] == "safe") & rec_df["liquidated_hourly"].notna()]
    if len(hr_rows) == 0:
        print("No entries had full hourly coverage over their hold window - skipping.")
    else:
        cmp_agg = (
            hr_rows.groupby(["H", "side"])
            .agg(
                n=("liquidated", "size"),
                daily_liq_pct=("liquidated", lambda x: round(x.mean() * 100, 2)),
                hourly_liq_pct=("liquidated_hourly", lambda x: round(x.mean() * 100, 2)),
            )
            .reset_index()
        )
        print(cmp_agg.to_string(index=False))
        mismatch = hr_rows[hr_rows["liquidated"] != hr_rows["liquidated_hourly"]]
        print(f"\nRows where daily-proxy and hourly-precise DISAGREE: {len(mismatch)} / {len(hr_rows)}")
        # direction of mismatch: daily said safe but hourly says liquidated (the dangerous direction)
        optimistic = hr_rows[(hr_rows["liquidated"] == False) & (hr_rows["liquidated_hourly"] == True)]
        print(f"  Daily-proxy MISSED a liquidation hourly data caught (optimistic direction): {len(optimistic)} / {len(hr_rows)}")

    # -----------------------------------------------------------------
    # 5) "Already past liquidation line" flag rate for naive fixed levs
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("5) Fraction of entries where the leverage is ALREADY past-liq-line at entry (distance=0)")
    print("=" * 100)
    plt_agg = (
        rec_df[rec_df["H"] == 3]
        .groupby(["lev_label", "side"])
        .agg(n=("past_liq_line", "size"), past_liq_pct=("past_liq_line", lambda x: round(x.mean() * 100, 2)),
             exceeds_venue_pct=("exceeds_venue", lambda x: round(x.mean() * 100, 2)))
        .reset_index()
    )
    print(plt_agg.to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()
