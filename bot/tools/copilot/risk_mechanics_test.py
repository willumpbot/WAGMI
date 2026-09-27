#!/usr/bin/env python
"""
risk_mechanics_test.py - OOS stress test of copilot.py's other TWO claimed
"AUTOMATABLE" RISK PLAN mechanics: the 2xATR disaster stop
(DISASTER_STOP_ATR_MULT) and the 3-5 day MAX-HOLD time-stop
(MAX_HOLD_DAYS_RANGE). Same rigor as lev_band_test.py / lev_band_horizon_test.py,
which already OOS-refuted the leverage mechanic (single-day tail stat guarding
a multi-day hold).
=============================================================================
READ-ONLY research script. Never imports/writes live-bot state and does NOT
modify tools/copilot/copilot.py. Reuses copilot.py's own `_atr` (Wilder ATR,
period=14) and lev_band_test.py's data loaders (no re-transcription) so the
mechanic under test is byte-for-byte what compute_risk_plan() would produce.

DESIGN: WE ALREADY PROVED THERE IS NO ENTRY EDGE (ADD CALIBRATION 2026-07-31 /
prior findings). So this test does NOT ask "does this make money" (answer is
~0 minus fees by construction). It isolates the MECHANIC's value independent
of entry by using an ENTRY-AGNOSTIC position set: every single day t in each
coin's OOS second-half is an entry (both LONG and SHORT) - "all-bars" is the
superset of any random-day sample, so it IS the entry-agnostic set (a random
subsample would just be a noisier draw from the same population). A second,
DECORRELATED non-overlapping "stride" sample is also run as an autocorrelation-
robustness check (see REFUTE-YOURSELF section 4).

Unlevered price-return space is used throughout (no leverage/liquidation
math needed here): DISASTER_STOP_ATR_MULT and MAX_HOLD_DAYS_RANGE are pure
price-distance / calendar-time rules in compute_risk_plan(); leverage only
scales the resulting $ P&L linearly and does not change the RELATIVE tail
benefit/cost of either mechanic, so comparing unlevered % returns is the
correct, leverage-independent test of the mechanic itself.

FEES: net_pct = raw_pct - ROUND_TRIP_FEE_PCT (0.09%, the same 9bps round-trip
taker convention used in resolve_calls.py / pretrade.py's fee accounting).
Applied once per trade regardless of stop/horizon exit (both are still one
open + one close).

TEST 1 - DISASTER STOP (2xATR): for H in {3,5}, side in {LONG,SHORT}, ATR
multiple in {1,1.5,2,3}: WITH-stop exit = stop price if touched intraday
(daily low/high proxy, filled exactly at the stop - no slippage, same
simplifying assumption lev_band_test.py uses for liq fills) else close[t+H];
WITHOUT-stop exit = close[t+H] always (ignores the stop entirely). Reports
CVaR(5%), ruin rate (<= -10% net, a fixed severe-loss threshold, disclosed as
a choice not derived), median/mean P&L, stopped-rate, and the WHIPSAW COST:
of trades that got stopped, how often (and by how much) would NOT stopping
have done better by the horizon end (stop-then-reverts).

TEST 2 - MAX-HOLD (3-5d): for H in {1,3,5,10,15}, no-stop horizon-only exit,
does the loss tail actually shrink at 3-5d vs shorter/longer holds? Also
repeated WITH the 2xATR stop active at each H, to see whether the stop
already does the tail-capping job independent of H (interaction check).

TEST 3 - REFUTE-YOURSELF: (a) per-era breakdown to spot single-era artifacts
(the Feb-2026 deep-oversold death trap the size-collapse memo flagged);
(b) headline numbers recomputed EXCLUDING the worst era, to see if the
"stop helps" or "hold-window helps" conclusion survives; (c) a decorrelated
non-overlapping stride sample (step = max hold) as an autocorrelation check
on the all-bars (heavily overlapping-window) sample.

Usage:
    python tools/copilot/risk_mechanics_test.py [--symbols SYM,SYM,...] [--refresh]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BOT_DIR, "tools", "copilot"))
sys.path.insert(0, os.path.join(BOT_DIR, "data", "fetchers"))

from copilot import _atr, ATR_PERIOD, DAYS_1D  # noqa: E402 - reuse the REAL ATR fn, no re-transcription
import lev_band_test as lbt  # noqa: E402 - reuse data loaders (discover_longtail_symbols, _load_csv, fetch_live_daily)
from hl_native import HLNative  # noqa: E402

SCRATCH_DIR = r"C:\Users\vince\AppData\Local\Temp\claude\C--Users-vince\6fad1965-9726-4e6a-b6d6-9dcf0b9f2c97\scratchpad\risk_mech_cache"
os.makedirs(SCRATCH_DIR, exist_ok=True)

WINDOW_CAP = DAYS_1D          # 200 - same trailing-window cap copilot.py itself uses for ATR/vol
MIN_SAMPLE = 20               # matches copilot's own n>=20 vol gate (kept for a consistent OOS-split definition)
ROUND_TRIP_FEE_PCT = 0.09     # 9bps round-trip taker convention (resolve_calls.py / pretrade.py)
RUIN_THRESH_PCT = -10.0       # fixed severe-loss threshold, net-of-fee % - a DISCLOSED CHOICE, not derived

ATR_MULTS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]  # 2.0 = copilot's DISASTER_STOP_ATR_MULT; finer sweep near the region that appears to matter
HOLDS_STOP = [3, 5]                   # copilot's own RISK PLAN window - Test 1
HOLDS_MAXHOLD = [1, 3, 5, 10, 15]     # Test 2 - does 3-5d beat shorter/longer?
MAX_H = max(HOLDS_STOP + HOLDS_MAXHOLD)  # 15 - longest path needed per entry


# ---------------------------------------------------------------------------
# Entry-time-safe ATR (mirrors copilot.py's DipRead.atr_1d computation exactly:
# _atr() Wilder ATR(14) on a window ending at t, capped at WINDOW_CAP=200)
# ---------------------------------------------------------------------------
def entry_time_atr(window_df: pd.DataFrame, period: int = ATR_PERIOD):
    a = _atr(window_df, period)
    val = a.iloc[-1] if not a.empty and pd.notna(a.iloc[-1]) else None
    return float(val) if val is not None else None


# ---------------------------------------------------------------------------
# Core path simulation - ONE pass per (symbol, t, side, mult) over the full
# MAX_H-day forward path; per-H exit/stop outcomes are then sliced from this
# single walk so results are internally consistent across H (a breach on day
# 2 stops the H=3 trade AND the H=5/10/15 trades identically).
# ---------------------------------------------------------------------------
def simulate_path(entry_price: float, side: str, atr: float, mult: float, path_df: pd.DataFrame):
    is_long = side == "LONG"
    stop_price = entry_price - mult * atr if is_long else entry_price + mult * atr
    lows = path_df["l"].to_numpy(dtype=float)
    highs = path_df["h"].to_numpy(dtype=float)
    closes = path_df["c"].to_numpy(dtype=float)
    breach_mask = (lows <= stop_price) if is_long else (highs >= stop_price)
    breach_day = int(np.argmax(breach_mask)) + 1 if breach_mask.any() else None  # 1-indexed day offset
    return stop_price, breach_day, closes


def exit_at_H(entry_price, side, stop_price, breach_day, closes, H, with_stop):
    """Returns raw_pct (before fees) for a hold of H days from this single
    simulated path. with_stop=False ignores the stop entirely (pure horizon)."""
    is_long = side == "LONG"
    stopped = with_stop and (breach_day is not None) and (breach_day <= H)
    if stopped:
        exit_price = stop_price
    else:
        exit_price = closes[H - 1]
    raw_pct = (exit_price - entry_price) / entry_price * 100.0 if is_long else (entry_price - exit_price) / entry_price * 100.0
    return raw_pct, stopped


# ---------------------------------------------------------------------------
# Per-symbol walk-forward (entry-time-safe: window <= t only; OOS = second
# half of THIS symbol's own history, same split lev_band_test.py uses)
# ---------------------------------------------------------------------------
def run_symbol(symbol, df, stride=1):
    n = len(df)
    half = n // 2
    start_t = max(half, MIN_SAMPLE)
    records = []
    for t in range(start_t, n - MAX_H, stride):
        entry_price = float(df["c"].iloc[t])
        entry_date = df["t"].iloc[t]
        era = entry_date.strftime("%Y-%m")
        w_start = max(0, t + 1 - WINDOW_CAP)
        window_df = df.iloc[w_start : t + 1].reset_index(drop=True)
        atr = entry_time_atr(window_df)
        if atr is None or atr <= 0:
            continue
        path_df = df.iloc[t + 1 : t + 1 + MAX_H].reset_index(drop=True)
        if len(path_df) < MAX_H:
            continue

        for side in ("LONG", "SHORT"):
            # ---- Test 1 + Test 2 "with stop": one simulate_path per mult ----
            for mult in ATR_MULTS:
                stop_price, breach_day, closes = simulate_path(entry_price, side, atr, mult, path_df)
                for H in sorted(set(HOLDS_STOP) | set(HOLDS_MAXHOLD)):
                    raw_with, stopped = exit_at_H(entry_price, side, stop_price, breach_day, closes, H, with_stop=True)
                    raw_without, _ = exit_at_H(entry_price, side, stop_price, breach_day, closes, H, with_stop=False)
                    records.append(dict(
                        symbol=symbol, t=t, entry_date=entry_date, era=era, side=side, H=H, mult=mult,
                        atr_pct_entry=atr / entry_price * 100.0,
                        stopped=stopped,
                        net_with_pct=raw_with - ROUND_TRIP_FEE_PCT,
                        net_without_pct=raw_without - ROUND_TRIP_FEE_PCT,
                    ))
    return records


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------
def cvar(series: pd.Series, pct: float = 5.0):
    s = series.dropna()
    if len(s) == 0:
        return np.nan
    thresh = np.percentile(s.values, pct)
    tail = s[s <= thresh]
    return float(tail.mean()) if len(tail) > 0 else float(thresh)


def summarize(df, group_cols):
    def agg_fn(g):
        stopped = g["stopped"]
        with_pct = g["net_with_pct"]
        without_pct = g["net_without_pct"]
        stopped_rows = g[g["stopped"]]
        reversion = np.nan
        reversion_pos = np.nan
        opp_cost = np.nan
        if len(stopped_rows) > 0:
            reversion = (stopped_rows["net_without_pct"] > stopped_rows["net_with_pct"]).mean() * 100.0
            reversion_pos = (stopped_rows["net_without_pct"] > 0).mean() * 100.0
            opp_cost = (stopped_rows["net_without_pct"] - stopped_rows["net_with_pct"]).mean()
        return pd.Series({
            "n": len(g),
            "stopped_rate_pct": stopped.mean() * 100.0,
            "median_with": with_pct.median(),
            "median_without": without_pct.median(),
            "mean_with": with_pct.mean(),
            "mean_without": without_pct.mean(),
            "cvar5_with": cvar(with_pct, 5),
            "cvar5_without": cvar(without_pct, 5),
            "ruin_rate_with_pct": (with_pct <= RUIN_THRESH_PCT).mean() * 100.0,
            "ruin_rate_without_pct": (without_pct <= RUIN_THRESH_PCT).mean() * 100.0,
            "whipsaw_reversion_pct": reversion,          # of STOPPED trades: without-stop would've beaten with-stop
            "whipsaw_to_positive_pct": reversion_pos,    # of STOPPED trades: without-stop ended net-positive anyway
            "avg_opp_cost_pct": opp_cost,                # mean(without - with) among STOPPED trades
        })
    return df.groupby(group_cols).apply(agg_fn, include_groups=False).reset_index()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    client = HLNative()
    longtail_syms = lbt.discover_longtail_symbols()
    all_syms = longtail_syms + lbt.LIVE_FETCH_SYMBOLS
    if args.symbols:
        want = set(s.strip() for s in args.symbols.split(","))
        all_syms = [s for s in all_syms if s in want]

    dfs = {}
    coverage = []
    for sym in all_syms:
        if sym in lbt.LIVE_FETCH_SYMBOLS:
            df = lbt.fetch_live_daily(client, sym, refresh=args.refresh)
        else:
            df = lbt._load_csv(os.path.join(lbt.LONGTAIL_DIR, f"{sym}_1d.csv"))
        if df is None or len(df) < MIN_SAMPLE + MAX_H + 5:
            print(f"[risk_mechanics_test] SKIP {sym}: insufficient daily data", file=sys.stderr)
            continue
        dfs[sym] = df
        coverage.append((sym, len(df), df["t"].iloc[0].date(), df["t"].iloc[-1].date()))

    print("=" * 100)
    print("COVERAGE (per symbol)")
    print("=" * 100)
    cov_df = pd.DataFrame(coverage, columns=["symbol", "n_days", "start", "end"])
    print(cov_df.to_string(index=False))

    # ---- ALL-BARS entry-agnostic set (primary) ----
    all_records = []
    for sym, df in dfs.items():
        recs = run_symbol(sym, df, stride=1)
        all_records.extend(recs)
        print(f"[risk_mechanics_test] {sym}: all-bars -> {len(recs)} records", file=sys.stderr)
    rec_df = pd.DataFrame(all_records)
    out_csv = os.path.join(SCRATCH_DIR, "risk_mechanics_test_records.csv")
    rec_df.to_csv(out_csv, index=False)
    print(f"\n[risk_mechanics_test] wrote {len(rec_df)} all-bars records -> {out_csv}\n")

    # =====================================================================
    # TEST 1: DISASTER STOP - ATR-multiple sweep, H in {3,5}, both sides
    # =====================================================================
    print("\n" + "=" * 100)
    print("TEST 1) DISASTER STOP - WITH vs WITHOUT, ATR-multiple sweep (2.0x = copilot's live DISASTER_STOP_ATR_MULT)")
    print("        net-of-fees (9bps rt), OOS second-half-of-history, all-bars entry-agnostic set")
    print("=" * 100)
    t1 = summarize(rec_df[rec_df["H"].isin(HOLDS_STOP)], ["mult", "H", "side"])
    cols = ["mult", "H", "side", "n", "stopped_rate_pct", "median_with", "median_without",
            "cvar5_with", "cvar5_without", "ruin_rate_with_pct", "ruin_rate_without_pct",
            "whipsaw_reversion_pct", "whipsaw_to_positive_pct", "avg_opp_cost_pct"]
    print(t1[cols].round(3).to_string(index=False))

    # =====================================================================
    # TEST 2: MAX-HOLD - does 3-5d beat shorter/longer? With and without the
    # live 2xATR stop (interaction check)
    # =====================================================================
    print("\n" + "=" * 100)
    print("TEST 2a) MAX-HOLD, NO STOP (pure horizon exit) - loss tail by H, both sides, OOS")
    print("=" * 100)
    t2a = summarize(rec_df[(rec_df["H"].isin(HOLDS_MAXHOLD)) & (rec_df["mult"] == 2.0)], ["H", "side"])
    cols2 = ["H", "side", "n", "median_without", "mean_without", "cvar5_without", "ruin_rate_without_pct"]
    print(t2a[cols2].round(3).to_string(index=False))

    print("\n" + "=" * 100)
    print("TEST 2b) MAX-HOLD, WITH 2xATR STOP ACTIVE - does the stop already cap the tail regardless of H?")
    print("=" * 100)
    t2b = summarize(rec_df[(rec_df["H"].isin(HOLDS_MAXHOLD)) & (rec_df["mult"] == 2.0)], ["H", "side"])
    cols2b = ["H", "side", "n", "stopped_rate_pct", "median_with", "mean_with", "cvar5_with", "ruin_rate_with_pct"]
    print(t2b[cols2b].round(3).to_string(index=False))

    # =====================================================================
    # TEST 3: REFUTE-YOURSELF
    # =====================================================================
    print("\n" + "=" * 100)
    print("TEST 3a) PER-ERA breakdown, mult=2.0 H=3, both sides pooled (single-era-artifact check)")
    print("=" * 100)
    era_slice = rec_df[(rec_df["mult"] == 2.0) & (rec_df["H"] == 3)]
    era_t = summarize(era_slice, ["era"])
    print(era_t[["era", "n", "stopped_rate_pct", "cvar5_with", "cvar5_without",
                 "ruin_rate_without_pct", "whipsaw_reversion_pct"]].round(3).to_string(index=False))

    print("\nTEST 3a-ii) Same, H=5")
    era_slice5 = rec_df[(rec_df["mult"] == 2.0) & (rec_df["H"] == 5)]
    era_t5 = summarize(era_slice5, ["era"])
    print(era_t5[["era", "n", "stopped_rate_pct", "cvar5_with", "cvar5_without",
                  "ruin_rate_without_pct", "whipsaw_reversion_pct"]].round(3).to_string(index=False))

    worst_era_row = era_t.sort_values("ruin_rate_without_pct", ascending=False).iloc[0]
    worst_era = worst_era_row["era"]
    print(f"\nTEST 3b) Worst single era by no-stop ruin-rate: {worst_era} "
          f"(ruin_rate_without={worst_era_row['ruin_rate_without_pct']:.2f}%, n={worst_era_row['n']:.0f}). "
          f"Recomputing TEST 1 headline (mult=2.0, H=3/5) EXCLUDING this era:")
    excl = rec_df[(rec_df["mult"] == 2.0) & (rec_df["era"] != worst_era)]
    t3b = summarize(excl[excl["H"].isin(HOLDS_STOP)], ["H", "side"])
    print(t3b[["H", "side", "n", "stopped_rate_pct", "cvar5_with", "cvar5_without",
              "ruin_rate_with_pct", "ruin_rate_without_pct", "whipsaw_reversion_pct"]].round(3).to_string(index=False))

    print("\nTEST 3c) DECORRELATED stride sample (non-overlapping windows, step=MAX_H) - "
          "autocorrelation-robustness check vs the all-bars sample above (mult=2.0)")
    stride_records = []
    for sym, df in dfs.items():
        recs = run_symbol(sym, df, stride=MAX_H)
        stride_records.extend(recs)
    stride_df = pd.DataFrame(stride_records)
    if len(stride_df) == 0:
        print("Insufficient non-overlapping entries per symbol for a stride sample - skipping.")
    else:
        t3c = summarize(stride_df[(stride_df["mult"] == 2.0) & (stride_df["H"].isin(HOLDS_STOP))], ["H", "side"])
        print(t3c[["H", "side", "n", "stopped_rate_pct", "cvar5_with", "cvar5_without",
                  "ruin_rate_with_pct", "ruin_rate_without_pct", "whipsaw_reversion_pct"]].round(3).to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()
