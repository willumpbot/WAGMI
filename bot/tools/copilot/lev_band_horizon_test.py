#!/usr/bin/env python
"""
lev_band_horizon_test.py - OOS validation of a HORIZON-AWARE recalibration of
copilot.py's SAFE-MAX-LEVERAGE mechanic.
=============================================================================
READ-ONLY research script. Never imports/writes live-bot state and does NOT
modify tools/copilot/copilot.py. This is a validated PROPOSAL only.

BACKGROUND (see lev_band_test.py / lev_band_test_records.csv): copilot.py's
`compute_liquidation()` sizes "safe_max_leverage" off `vol.pct95_daily_drop_pct`
- the 95th-percentile worst SINGLE-DAY move. But the tool's own RISK PLAN
recommends 3-5 DAY holds. lev_band_test.py proved that opening at the
"safe" single-day band and holding 3-5 days gives an OOS liquidation rate of
~25-40%, not the ~5% the single-day statistic was designed to bound. That
finding is already surfaced honestly in copilot.py's risk_reason text as a
stopgap disclaimer (see compute_liquidation, "SAFE" branch), pending this fix.

THE FIX UNDER TEST: replace the single-day tail_frac with a HOLD-HORIZON
adverse-excursion percentile, estimated entry-time-safe from history <= t
only, AND made SIDE-SPECIFIC (the old mechanic reuses one "worst DOWN day"
tail_frac for shorts too, which is the wrong tail for a short - a short is
killed by a big UP move). For a hold of H days:

    tail_frac_H(side) = 95th-pct WORST adverse excursion over any H-day path
    starting at day i (i.e. max drawdown from entry for LONG, max run-up from
    entry for SHORT), computed over all valid i <= t - H in the trailing
    window (same WINDOW_CAP=200d cap copilot.py itself uses).

Then safe_max_lev_H solves the SAME formula copilot.py already uses,
1/L - mm >= tail_frac_H, via compute_liquidation() itself (imported
unmodified, fed a synthetic RealizedVol whose pct95_daily_drop_pct field is
swapped for tail_frac_H*100 - no re-transcription of the leverage-solving
math, so the mechanic under test is byte-for-byte what copilot.py would
produce if fed this number).

VALIDATION (same 27 coins, same OOS second-half-only split, same
entry-time-safe walk-forward, same real-HL-mm, same daily-low/high path
proxy as lev_band_test.py):
  lev_label:
    old_1d       - CURRENT LIVE mechanic (single-day tail_frac, side-agnostic)
    new_H_p95    - THE FIX (horizon-H tail_frac, side-specific, 95th pct)
    new_H_p90    - robustness variant (90th pct instead of 95th - refute-
                   yourself check: does the ~5% target hold up, or was p95
                   a lucky fit to this particular sample?)

Usage:
    python tools/copilot/lev_band_horizon_test.py [--symbols SYM,SYM,...] [--refresh]
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BOT_DIR, "tools", "copilot"))
sys.path.insert(0, os.path.join(BOT_DIR, "data", "fetchers"))

from copilot import compute_realized_vol, compute_liquidation, RealizedVol  # noqa: E402
import lev_band_test as lbt  # noqa: E402 - reuse data loaders/helpers, no re-transcription
from hl_native import HLNative  # noqa: E402

SCRATCH_DIR = lbt.SCRATCH_DIR
WINDOW_CAP = lbt.WINDOW_CAP      # 200 - same lookback cap copilot.py itself uses
MIN_SAMPLE = lbt.MIN_SAMPLE      # 20 - matches copilot's own n>=20 gate for pct95
HOLDS = [3, 5]                   # the horizons under test (copilot's own 3-5d RISK PLAN window)
PCTS = [95, 90]                  # main pct + robustness variant


# ---------------------------------------------------------------------------
# THE FIX: horizon-H, side-specific adverse-excursion tail fraction
# ---------------------------------------------------------------------------
def compute_horizon_tail_frac(window_df: pd.DataFrame, H: int, pct: float = 95.0):
    """Entry-time-safe: uses ONLY rows already in window_df (which the caller
    truncates to <= day t). For every candidate entry index i in the window
    with i+H within the window, computes:
      mae_long(i)  = (close[i] - min(low[i+1..i+H]))  / close[i]   (drawdown)
      mae_short(i) = (max(high[i+1..i+H]) - close[i]) / close[i]   (run-up)
    and returns the `pct`-th percentile of each distribution (magnitude,
    already non-negative) as (long_frac, short_frac), or (None, None) if
    fewer than MIN_SAMPLE overlapping H-day paths are available.

    NOTE: these overlapping H-day windows are not independent draws (heavy
    autocorrelation from the rolling construction) - the effective sample
    size for the percentile is smaller than the raw count. This is the same
    caveat that already applies to copilot's own single-day pct95 (daily
    returns are autocorrelated at short lags too), so it is a like-for-like
    comparison, not a new weakness introduced by the fix.
    """
    close = window_df["c"].to_numpy(dtype=float)
    low = window_df["l"].to_numpy(dtype=float)
    high = window_df["h"].to_numpy(dtype=float)
    n = len(close)
    m = n - H  # number of valid entry indices i = 0..m-1, each needs low/high[i+1..i+H]
    if m < MIN_SAMPLE or n <= H:
        return None, None

    low_windows = sliding_window_view(low[1:], H)    # window i -> low[i+1:i+1+H]
    high_windows = sliding_window_view(high[1:], H)  # window i -> high[i+1:i+1+H]
    fwd_min = low_windows.min(axis=1)[:m]
    fwd_max = high_windows.max(axis=1)[:m]
    entry_close = close[:m]

    mae_long = np.clip((entry_close - fwd_min) / entry_close, 0.0, None)
    mae_short = np.clip((fwd_max - entry_close) / entry_close, 0.0, None)

    long_frac = float(np.percentile(mae_long, pct))
    short_frac = float(np.percentile(mae_short, pct))
    return long_frac, short_frac


def safe_lev_for_tail_frac(entry_price, side, tail_frac, base_vol, hl_max_leverage, symbol):
    """Feeds a synthetic RealizedVol (pct95_daily_drop_pct swapped for
    tail_frac*100, everything else passed through from base_vol) through the
    REAL, unmodified compute_liquidation() so the leverage-solving arithmetic
    is byte-for-byte what copilot.py already runs. Returns the LiquidationRead
    priced at that resulting safe_max_leverage (so liq_price/distance_pct are
    for the ACTUAL position size this fix would open)."""
    synth_vol = dataclasses.replace(base_vol, pct95_daily_drop_pct=tail_frac * 100.0)
    probe = compute_liquidation(entry_price, side, 1.0, synth_vol, hl_max_leverage, symbol)
    safe_lev = probe.safe_max_leverage
    return compute_liquidation(entry_price, side, safe_lev, synth_vol, hl_max_leverage, symbol)


# ---------------------------------------------------------------------------
# Walk-forward loop (mirrors lev_band_test.run_symbol's entry-time-safe
# second-half-only OOS split)
# ---------------------------------------------------------------------------
def run_symbol(symbol, df, hl_max_leverage):
    n = len(df)
    half = n // 2
    start_t = max(half, MIN_SAMPLE)
    max_h = max(HOLDS)
    records = []
    for t in range(start_t, n - max_h):
        entry_price = float(df["c"].iloc[t])
        entry_date = df["t"].iloc[t]
        era = entry_date.strftime("%Y-%m")
        w_start = max(0, t + 1 - WINDOW_CAP)
        window_df = df.iloc[w_start : t + 1].reset_index(drop=True)

        vol = compute_realized_vol(window_df)
        if vol.pct95_daily_drop_pct is None:
            continue  # copilot's own n>=20 gate not met - matches live behavior

        # ---- OLD mechanic: single-day, side-agnostic tail_frac (current live) ----
        old_probe = compute_liquidation(entry_price, "LONG", 1.0, vol, hl_max_leverage, symbol)
        old_safe = old_probe.safe_max_leverage  # side-independent by construction

        for H in HOLDS:
            hold = df.iloc[t + 1 : t + 1 + H]
            if len(hold) < H:
                continue
            low_extreme = hold["l"].min()
            high_extreme = hold["h"].max()

            for side in ("LONG", "SHORT"):
                is_long = side == "LONG"

                # OLD baseline at this H
                lr_old = compute_liquidation(entry_price, side, old_safe, vol, hl_max_leverage, symbol)
                liq_old = (low_extreme <= lr_old.liq_price) if is_long else (high_extreme >= lr_old.liq_price)
                records.append(dict(
                    symbol=symbol, t=t, entry_date=entry_date, era=era, side=side, H=H,
                    lev_label="old_1d", leverage=lr_old.leverage,
                    distance_pct=lr_old.distance_pct, past_liq_line=(lr_old.distance_pct == 0.0),
                    tail_frac_pct=vol.pct95_daily_drop_pct, liquidated=bool(liq_old),
                ))

                # NEW mechanic(s): horizon-H, side-specific tail_frac at pct in PCTS
                for pct in PCTS:
                    long_frac, short_frac = compute_horizon_tail_frac(window_df, H, pct=pct)
                    if long_frac is None:
                        continue
                    tail_frac = long_frac if is_long else short_frac
                    lr_new = safe_lev_for_tail_frac(entry_price, side, tail_frac, vol, hl_max_leverage, symbol)
                    liq_new = (low_extreme <= lr_new.liq_price) if is_long else (high_extreme >= lr_new.liq_price)
                    label = "new_H_p95" if pct == 95 else f"new_H_p{pct}"
                    records.append(dict(
                        symbol=symbol, t=t, entry_date=entry_date, era=era, side=side, H=H,
                        lev_label=label, leverage=lr_new.leverage,
                        distance_pct=lr_new.distance_pct, past_liq_line=(lr_new.distance_pct == 0.0),
                        tail_frac_pct=tail_frac * 100.0, liquidated=bool(liq_new),
                    ))
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
    print("[lev_band_horizon_test] fetching HL meta (real per-asset maxLeverage)...", file=sys.stderr)
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

    longtail_syms = lbt.discover_longtail_symbols()
    all_syms = longtail_syms + lbt.LIVE_FETCH_SYMBOLS
    if args.symbols:
        want = set(s.strip() for s in args.symbols.split(","))
        all_syms = [s for s in all_syms if s in want]

    all_records = []
    coverage = []
    for sym in all_syms:
        if sym in lbt.LIVE_FETCH_SYMBOLS:
            df = lbt.fetch_live_daily(client, sym, refresh=args.refresh)
        else:
            df = lbt._load_csv(os.path.join(lbt.LONGTAIL_DIR, f"{sym}_1d.csv"))
        if df is None or len(df) < MIN_SAMPLE + max(HOLDS) + 5:
            print(f"[lev_band_horizon_test] SKIP {sym}: insufficient daily data", file=sys.stderr)
            continue
        hlmax = hl_max.get(sym)
        recs = run_symbol(sym, df, hlmax)
        all_records.extend(recs)
        coverage.append((sym, len(df), df["t"].iloc[0].date(), df["t"].iloc[-1].date(), hlmax))
        print(f"[lev_band_horizon_test] {sym}: n_days={len(df)} hl_max={hlmax} -> {len(recs)} records", file=sys.stderr)

    rec_df = pd.DataFrame(all_records)
    out_csv = os.path.join(SCRATCH_DIR, "lev_band_horizon_test_records.csv")
    rec_df.to_csv(out_csv, index=False)
    print(f"\n[lev_band_horizon_test] wrote {len(rec_df)} records -> {out_csv}\n")

    print("=" * 100)
    print("COVERAGE (per symbol)")
    print("=" * 100)
    cov_df = pd.DataFrame(coverage, columns=["symbol", "n_days", "start", "end", "hl_max_lev"])
    print(cov_df.to_string(index=False))

    # -----------------------------------------------------------------
    # 1) MAIN TABLE: OOS liquidation rate, OLD vs NEW, by H x side
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("1) OOS LIQUIDATION RATE - OLD (single-day, side-agnostic) vs NEW (horizon-H, side-specific)")
    print("   Target for the NEW mechanic: ~5% at each H/side cell.")
    print("=" * 100)
    agg = (
        rec_df.groupby(["lev_label", "H", "side"])
        .agg(n=("liquidated", "size"), liq_rate_pct=("liquidated", lambda x: round(x.mean() * 100, 2)),
             median_lev=("leverage", "median"))
        .reset_index()
    )
    order = {"old_1d": 0, "new_H_p95": 1, "new_H_p90": 2}
    agg["ord"] = agg["lev_label"].map(order)
    agg = agg.sort_values(["H", "side", "ord"]).drop(columns=["ord"])
    print(agg.to_string(index=False))

    # -----------------------------------------------------------------
    # 2) Recommended leverage distribution under the NEW (p95) mechanic
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("2) RECOMMENDED SAFE-MAX-LEVERAGE DISTRIBUTION under the NEW (horizon-H, p95) mechanic")
    print("=" * 100)
    for H in HOLDS:
        for side in ("LONG", "SHORT"):
            rows = rec_df[(rec_df["lev_label"] == "new_H_p95") & (rec_df["H"] == H) & (rec_df["side"] == side)]
            if rows.empty:
                continue
            lev = rows["leverage"]
            q1, med, q3 = lev.quantile([0.25, 0.5, 0.75])
            usable = ((lev >= 3.0) & (lev <= 15.0)).mean() * 100.0
            floor_1x = (lev <= 1.01).mean() * 100.0
            print(f"H={H} {side}: n={len(rows)}  median={med:.2f}x  IQR=[{q1:.2f},{q3:.2f}]x  "
                  f"%in[3-15x]={usable:.1f}%  %at-floor(<=1x)={floor_1x:.1f}%  "
                  f"min={lev.min():.2f}x max={lev.max():.2f}x")

    print("\nPer-symbol MEDIAN new_H_p95 safe leverage (H=3, H=5) vs OLD (H=3) vs HL max, LONG side:")
    piv_rows = []
    for sym in rec_df["symbol"].unique():
        base = rec_df[(rec_df["symbol"] == sym) & (rec_df["side"] == "LONG")]
        old3 = base[(base["lev_label"] == "old_1d") & (base["H"] == 3)]["leverage"].median()
        new3 = base[(base["lev_label"] == "new_H_p95") & (base["H"] == 3)]["leverage"].median()
        new5 = base[(base["lev_label"] == "new_H_p95") & (base["H"] == 5)]["leverage"].median()
        piv_rows.append((sym, old3, new3, new5, hl_max.get(sym)))
    piv = pd.DataFrame(piv_rows, columns=["symbol", "old_1d_median", "new_H3_p95_median", "new_H5_p95_median", "hl_max_lev"])
    print(piv.sort_values("new_H3_p95_median").to_string(index=False))

    # -----------------------------------------------------------------
    # 3) Per-era breakdown (regime robustness) + p95 vs p90 stability
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("3a) PER-ERA OOS LIQUIDATION RATE, new_H_p95, H=3, both sides pooled (regime robustness)")
    print("=" * 100)
    era_rows = rec_df[(rec_df["lev_label"] == "new_H_p95") & (rec_df["H"] == 3)]
    era_agg = era_rows.groupby("era").agg(n=("liquidated", "size"), liq_rate_pct=("liquidated", lambda x: round(x.mean() * 100, 2)))
    print(era_agg.to_string())

    print("\n3b) PER-ERA OOS LIQUIDATION RATE, new_H_p95, H=5, both sides pooled")
    era_rows5 = rec_df[(rec_df["lev_label"] == "new_H_p95") & (rec_df["H"] == 5)]
    era_agg5 = era_rows5.groupby("era").agg(n=("liquidated", "size"), liq_rate_pct=("liquidated", lambda x: round(x.mean() * 100, 2)))
    print(era_agg5.to_string())

    print("\n3c) ROBUSTNESS: p95 vs p90 variant - is the ~5% target stable to the percentile choice, "
          "or a lucky fit? (from table 1 above, repeated here compactly)")
    rob = agg[agg["lev_label"].isin(["new_H_p95", "new_H_p90"])][["lev_label", "H", "side", "n", "liq_rate_pct", "median_lev"]]
    print(rob.to_string(index=False))

    # -----------------------------------------------------------------
    # 4) Liquidation-cascade cross-check
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("4) CROSS-CHECK vs collected liquidation-cascade data (data/copilot/liquidations/)")
    print("=" * 100)
    liq_dir = os.path.join(BOT_DIR, "data", "copilot", "liquidations")
    liq_csvs = [f for f in os.listdir(liq_dir)] if os.path.isdir(liq_dir) else []
    data_csvs = [f for f in liq_csvs if f.endswith(".csv") or f.endswith(".jsonl")]
    if not data_csvs:
        print(f"No liquidation-event data files in {liq_dir} yet (only {liq_csvs} present, e.g. collector.log) - "
              "collector has been running but has captured 0 real forced-liq events so far. Cannot cross-check "
              "model-implied liquidation levels against real events yet; noting as an open gap, not a pass/fail.")
    else:
        print(f"Found data files: {data_csvs} - manual inspection required (not auto-joined by this script).")

    print("\nDone.")


if __name__ == "__main__":
    main()
