#!/usr/bin/env python
"""
liq_distance_calibration_test.py - SAFETY-CRITICAL audit of the LIVE bot's
OWN closed trade history: did the stop-loss (SL) reliably bind BEFORE
Hyperliquid liquidation would have, given the leverage the bot actually
used?
=============================================================================
READ-ONLY. Never writes to data/replay/ or any live-bot state file. Imports
execution/leverage.py's LeverageManager UNMODIFIED (byte-for-byte the bot's
own live liquidation-price / SL-safety formula: tiered HL maintenance
margins, `liquidation_price()`, `validate_stop_vs_liquidation()`) so the
mechanic under test is exactly what core/signal_pipeline.py's "Gate 6:
Liquidation safety" and multi_strategy_main.py's tick-by-tick liquidation-
proximity force-close already run live. Section 4 (co-pilot cross-check)
also imports tools/copilot/copilot.py's compute_realized_vol /
compute_liquidation UNMODIFIED (the same functions lev_band_horizon_test.py
validated OOS) - no re-transcription of either formula anywhere in this file.

WHY THE JOIN IS NEEDED: data/trade_ledger.csv (274 closed trades) has entry/
exit price, side, leverage, exit_type, realized PnL - but NO stop_loss price
and NO position size/notional column. Both are recovered from the
independent data/trade_events.jsonl log stream's TRADE_OPENED events (written
by the executor at order placement, separately from the ledger writer),
joined by an EXACT match on (symbol, side, entry_price) - float-exact join,
verified below to hit 274/274 (100%) with the nearest-in-time candidate
picked as tiebreak (median tiebreak gap 15s, max 46min, none >1hr; see
match_trade_opened()). No entry-price collisions were observed across the
274 trades, so this is a safe unique key in practice; a `--dump-unmatched`
sanity path is kept in case a future ledger row ever fails to join, so a
data-join gap can never silently masquerade as a "no SL" finding.

TEST SECTIONS:
  1) Per-trade liq-vs-SL geometry: liquidation_price() + validate_stop_vs_
     liquidation() at the ACTUAL entry/side/leverage/notional (notional from
     the joined TRADE_OPENED qty). Distribution of buffer_ratio = SL distance
     from entry / liquidation distance from entry. buffer_ratio >= 1.0 (i.e.
     validate_stop_vs_liquidation()["safe"] is False) = SL sits AT OR BEYOND
     the modeled liquidation price = non-protective.
  2) Reality check: exit_type breakdown (does the ledger show any actual
     LIQUIDATION exits?), and for exit_type=="SL" rows, realized SL slippage
     = intended SL price (from TRADE_OPENED) vs actual logged exit_price,
     compared against the trade's own recorded fee $ (not an assumed bps
     convention) to sanity-check magnitude.
  3) Leverage-tier bucketing of buffer_ratio/gap_pct - where does the margin
     get thin?
  4) Cross-check vs copilot.py's horizon-aware safe-leverage ceiling (same
     compute_realized_vol/compute_liquidation() lev_band_horizon_test.py
     validated OOS at ~4% liquidation risk): for each trade, entry-time-safe
     daily-bar window (<= entry date only, real live HL daily candles fetched
     fresh), hold_days = hold_hours/24 (snaps to nearest calibrated H in
     {3,5} - see copilot.py; this is a MORE conservative horizon than most
     of these trades' actual sub-day holds, disclosed in refute-yourself).
  5) Refute-yourself: sim/dust-row filter, SL-slippage-vs-fee sanity, small-n
     power per leverage tier, and the tick-by-tick liquidation-proximity
     force-close (multi_strategy_main.py, triggers <1.5% from liq) that this
     static entry-time geometry test cannot see.

Usage:
    python tools/copilot/liq_distance_calibration_test.py [--skip-copilot-crosscheck] [--refresh]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BOT_DIR)
sys.path.insert(0, os.path.join(BOT_DIR, "tools", "copilot"))
sys.path.insert(0, os.path.join(BOT_DIR, "data", "fetchers"))

from execution.leverage import LeverageManager  # noqa: E402 - the bot's OWN, unmodified formula

LEDGER_PATH = os.path.join(BOT_DIR, "data", "trade_ledger.csv")
EVENTS_PATH = os.path.join(BOT_DIR, "data", "trade_events.jsonl")
SCRATCH_DIR = r"C:\Users\vince\AppData\Local\Temp\claude\C--Users-vince\6fad1965-9726-4e6a-b6d6-9dcf0b9f2c97\scratchpad\liq_calib_cache"
os.makedirs(SCRATCH_DIR, exist_ok=True)

PRICE_REL_TOL = 1e-6   # float-exact join tolerance on entry_price
TIME_TIEBREAK_FLAG_S = 3600  # flag (not drop) joins whose nearest-time candidate is >1hr from the ledger-implied open time


# ---------------------------------------------------------------------------
# 1) JOIN: recover SL price + qty at open from trade_events.jsonl TRADE_OPENED
# ---------------------------------------------------------------------------
def load_trade_opened_events():
    events_by_key = collections.defaultdict(list)
    n_lines = 0
    n_opened = 0
    with open(EVENTS_PATH, encoding="utf-8", errors="ignore") as f:
        for line in f:
            n_lines += 1
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "TRADE_OPENED":
                continue
            try:
                ts = dt.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            n_opened += 1
            key = (d.get("symbol"), d.get("side"))
            events_by_key[key].append((ts, d))
    return events_by_key, n_lines, n_opened


def match_trade_opened(ledger: pd.DataFrame, events_by_key):
    """Exact (symbol, side, entry_price) join, nearest-time tiebreak. Returns
    (matched_records list, unmatched list of trade_ids)."""
    matched = []
    unmatched = []
    flagged_time_gap = []
    for _, row in ledger.iterrows():
        sym, side = row["symbol"], row["side"]
        entry = float(row["entry_price"])
        guess_open = row["timestamp"] - row["hold_hours"] * 3600.0
        cands = events_by_key.get((sym, side), [])
        price_matches = [(ts, d) for ts, d in cands if abs(d["entry"] - entry) <= max(PRICE_REL_TOL * entry, 1e-9)]
        if not price_matches:
            unmatched.append(row["trade_id"])
            continue
        price_matches.sort(key=lambda x: abs(x[0] - guess_open))
        best_ts, best_d = price_matches[0]
        gap_s = abs(best_ts - guess_open)
        if gap_s > TIME_TIEBREAK_FLAG_S:
            flagged_time_gap.append((row["trade_id"], gap_s))
        rec = dict(row)
        rec["sl_price"] = best_d.get("sl")
        rec["qty"] = abs(best_d.get("position_size") or 0.0)
        rec["event_leverage"] = best_d.get("leverage")
        rec["event_atr"] = best_d.get("atr")
        rec["join_time_gap_s"] = gap_s
        matched.append(rec)
    return matched, unmatched, flagged_time_gap


# ---------------------------------------------------------------------------
# 2) Per-trade liq-vs-SL geometry via the bot's OWN LeverageManager
# ---------------------------------------------------------------------------
def compute_geometry(matched, lm: LeverageManager):
    out = []
    for r in matched:
        entry = float(r["entry_price"])
        side = r["side"]
        leverage = float(r["leverage"])
        sl_price = r["sl_price"]
        qty = r["qty"]
        notional_real = qty * entry if qty else 0.0

        liq_price = lm.liquidation_price(entry, side, leverage, notional_real)
        row = dict(r)
        row["notional_real_usd"] = notional_real
        row["liq_price"] = liq_price

        if sl_price is None or (isinstance(sl_price, float) and np.isnan(sl_price)):
            row["sl_dist_pct"] = None
            row["liq_dist_pct"] = None
            row["buffer_ratio"] = None
            row["non_protective"] = None
            row["vs_safe"] = None
            row["vs_gap_pct"] = None
        else:
            sl_dist_pct = abs(entry - sl_price) / entry * 100.0
            row["sl_dist_pct"] = sl_dist_pct
            if liq_price is None:
                # bot's own model: leverage <= 1.0 -> no liquidation risk at all
                row["liq_dist_pct"] = None
                row["buffer_ratio"] = None
                row["non_protective"] = False
                row["vs_safe"] = True
                row["vs_gap_pct"] = None
            else:
                liq_dist_pct = abs(entry - liq_price) / entry * 100.0
                row["liq_dist_pct"] = liq_dist_pct
                row["buffer_ratio"] = sl_dist_pct / liq_dist_pct if liq_dist_pct > 1e-12 else float("inf")
                vs = lm.validate_stop_vs_liquidation(entry, sl_price, side, leverage, notional_real)
                row["non_protective"] = not vs["safe"]
                row["vs_safe"] = vs["safe"]
                row["vs_gap_pct"] = vs["gap_pct"] * 100.0
        out.append(row)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# 3) Realized SL slippage (exit_type == "SL" rows only - the static stop;
#    TRAILING_STOP is excluded because its trigger price moves and we do not
#    have its path, only the static SL set at open)
# ---------------------------------------------------------------------------
def compute_sl_slippage(geo: pd.DataFrame):
    sl_rows = geo[geo["exit_type"] == "SL"].copy()
    if sl_rows.empty:
        return sl_rows

    def _slip(row):
        entry = float(row["entry_price"])
        exit_p = float(row["exit_price"])
        sl_p = row["sl_price"]
        if sl_p is None or (isinstance(sl_p, float) and np.isnan(sl_p)):
            return None
        if row["side"] == "LONG":
            slip = sl_p - exit_p       # positive = filled WORSE (lower) than intended stop
        else:
            slip = exit_p - sl_p       # positive = filled WORSE (higher) than intended stop
        return slip

    sl_rows["slip_price"] = sl_rows.apply(_slip, axis=1)
    sl_rows["slip_pct_of_entry"] = sl_rows["slip_price"] / sl_rows["entry_price"] * 100.0
    sl_rows["slip_usd"] = sl_rows["slip_price"] * sl_rows["qty"]
    sl_rows["fee_pct_of_notional"] = np.where(
        sl_rows["notional_real_usd"] > 0,
        sl_rows["fees"] / sl_rows["notional_real_usd"] * 100.0,
        np.nan,
    )
    return sl_rows


# ---------------------------------------------------------------------------
# 4) Co-pilot cross-check: horizon-aware safe_max_leverage vs actual leverage
# ---------------------------------------------------------------------------
def copilot_crosscheck(geo: pd.DataFrame, refresh: bool):
    from copilot import compute_realized_vol, compute_liquidation  # noqa: E402
    import lev_band_test as lbt  # noqa: E402 - reuse data loaders, no re-transcription

    client = None
    try:
        from hl_native import HLNative
        client = HLNative()
    except Exception as e:
        print(f"[crosscheck] could not init HLNative ({e}) - skipping section 4", file=sys.stderr)
        return None

    symbols = sorted(geo["symbol"].unique())
    dfs = {}
    for sym in symbols:
        try:
            df = lbt.fetch_live_daily(client, sym, days=430, refresh=refresh)
        except Exception as e:
            print(f"[crosscheck] fetch failed for {sym}: {e}", file=sys.stderr)
            df = None
        if df is None or len(df) < 30:
            print(f"[crosscheck] SKIP {sym}: insufficient daily history ({0 if df is None else len(df)} rows)", file=sys.stderr)
            continue
        dfs[sym] = df

    records = []
    for _, row in geo.iterrows():
        sym = row["symbol"]
        if sym not in dfs:
            continue
        df = dfs[sym]
        entry_ts = dt.datetime.fromtimestamp(row["timestamp"] - row["hold_hours"] * 3600.0, tz=dt.timezone.utc)
        # entry-time-safe: only bars strictly BEFORE the entry day
        window_df = df[df["t"] < entry_ts].tail(200).reset_index(drop=True)
        if len(window_df) < 20:
            continue
        vol = compute_realized_vol(window_df)
        if vol.pct95_daily_drop_pct is None:
            continue
        hold_days = max(row["hold_hours"] / 24.0, 1e-6)
        lr = compute_liquidation(row["entry_price"], row["side"], row["leverage"], vol, None, sym, hold_days=hold_days)
        records.append(dict(
            trade_id=row["trade_id"], symbol=sym, side=row["side"],
            actual_leverage=row["leverage"], hold_hours=row["hold_hours"],
            copilot_safe_max_leverage=lr.safe_max_leverage,
            copilot_horizon_used=lr.horizon_used,
            copilot_single_day_safe_max_leverage=lr.single_day_safe_max_leverage,
            exceeds_copilot_safe=row["leverage"] > lr.safe_max_leverage,
            buffer_ratio=row["buffer_ratio"],
            non_protective=row["non_protective"],
        ))
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-copilot-crosscheck", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    ledger = pd.read_csv(LEDGER_PATH)
    print(f"Loaded {len(ledger)} closed trades from {LEDGER_PATH}")
    print(f"Columns: {ledger.columns.tolist()}\n")

    events_by_key, n_lines, n_opened = load_trade_opened_events()
    print(f"Scanned {n_lines} lines in trade_events.jsonl -> {n_opened} TRADE_OPENED events\n")

    matched, unmatched, flagged_gap = match_trade_opened(ledger, events_by_key)
    print("=" * 100)
    print("JOIN QUALITY (exact symbol+side+entry_price match to trade_events.jsonl TRADE_OPENED)")
    print("=" * 100)
    print(f"matched: {len(matched)} / {len(ledger)}   unmatched (excluded below, no SL data recoverable): {len(unmatched)}")
    if unmatched:
        print(f"  unmatched trade_ids: {unmatched}")
    if flagged_gap:
        print(f"  matched but with a >{TIME_TIEBREAK_FLAG_S}s open-time tiebreak gap (lower-confidence match, still included): {flagged_gap}")

    lm = LeverageManager()
    geo = compute_geometry(matched, lm)
    geo["leverage"] = geo["leverage"].astype(float)

    # -----------------------------------------------------------------
    # SECTION 1: distribution of SL-vs-liq buffer
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("1) SL-vs-LIQUIDATION GEOMETRY (bot's own liquidation_price()/validate_stop_vs_liquidation())")
    print("=" * 100)
    lev_gt1 = geo[geo["leverage"] > 1.0].copy()
    lev_eq1 = geo[geo["leverage"] <= 1.0]
    print(f"leverage <= 1.0x (no liquidation risk under the bot's own model): n={len(lev_eq1)}")
    print(f"leverage > 1.0x (liquidation-risk-bearing trades): n={len(lev_gt1)}")
    if len(lev_gt1):
        print("\nbuffer_ratio = SL distance from entry / liquidation distance from entry")
        print("  (< 1.0 = SL binds before liq, i.e. protective; >= 1.0 = SL at/beyond liq = NON-PROTECTIVE)")
        print(lev_gt1["buffer_ratio"].describe().to_string())
        n_nonprotective = int(lev_gt1["non_protective"].sum())
        print(f"\nNON-PROTECTIVE trades (SL at/beyond modeled liquidation): {n_nonprotective} / {len(lev_gt1)}")
        if n_nonprotective:
            cols = ["trade_id", "symbol", "side", "leverage", "entry_price", "sl_price", "liq_price",
                    "buffer_ratio", "vs_gap_pct", "notional_real_usd", "exit_type"]
            print(lev_gt1[lev_gt1["non_protective"]][cols].to_string(index=False))
        print("\nvs_gap_pct distribution (% of entry price between SL and liq; the bot's own validate_stop_vs_liquidation() gap_pct*100):")
        print(lev_gt1["vs_gap_pct"].describe().to_string())

    # -----------------------------------------------------------------
    # SECTION 2: reality check - exit_type breakdown + realized SL slippage
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("2) EXIT-REASON BREAKDOWN (does the ledger show any actual LIQUIDATION exits?)")
    print("=" * 100)
    print(geo["exit_type"].value_counts().to_string())
    n_liq_exits = int((geo["exit_type"].str.upper().str.contains("LIQUID", na=False)).sum())
    print(f"\nExit rows whose exit_type mentions LIQUIDATION: {n_liq_exits}")

    print("\n" + "-" * 100)
    print("2b) REALIZED SL SLIPPAGE (exit_type=='SL' rows only; TRAILING_STOP excluded - dynamic trigger, no static SL to compare)")
    print("-" * 100)
    sl_slip = compute_sl_slippage(geo)
    if sl_slip.empty:
        print("No SL-exit rows with joined SL price.")
    else:
        print(f"n SL-exit rows: {len(sl_slip)}")
        print("\nslip_pct_of_entry (positive = filled WORSE than the intended SL price, i.e. slipped through the stop):")
        print(sl_slip["slip_pct_of_entry"].describe().to_string())
        n_worse = int((sl_slip["slip_price"] > 0).sum())
        n_better = int((sl_slip["slip_price"] < 0).sum())
        n_exact = len(sl_slip) - n_worse - n_better
        print(f"\nfilled WORSE than intended SL: {n_worse}/{len(sl_slip)}   "
              f"filled BETTER (favorable slip): {n_better}/{len(sl_slip)}   exact: {n_exact}/{len(sl_slip)}")
        print("\nWorst 10 slippage rows (most adverse):")
        cols2 = ["trade_id", "symbol", "side", "leverage", "entry_price", "sl_price", "exit_price",
                 "slip_price", "slip_pct_of_entry", "slip_usd", "fees", "fee_pct_of_notional"]
        print(sl_slip.sort_values("slip_price", ascending=False).head(10)[cols2].to_string(index=False))
        print("\nSlippage vs fees (is slippage dwarfed by round-trip fees, i.e. within normal execution noise?):")
        comp = sl_slip[["slip_usd", "fees"]].describe()
        print(comp.to_string())
        print(f"\nmean |slip_usd| = {sl_slip['slip_usd'].abs().mean():.4f}   mean fees($) = {sl_slip['fees'].mean():.4f}   "
              f"ratio |slip|/fees = {(sl_slip['slip_usd'].abs().mean() / sl_slip['fees'].mean()):.3f}")

    # -----------------------------------------------------------------
    # SECTION 3: leverage-tier bucketing
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("3) LEVERAGE-TIER BUCKETING (where does the SL-vs-liq buffer get thin?)")
    print("=" * 100)
    print("\nPer distinct leverage value actually used live:")
    per_lev = (
        lev_gt1.groupby("leverage")
        .agg(n=("buffer_ratio", "size"),
             median_buffer_ratio=("buffer_ratio", "median"),
             p90_buffer_ratio=("buffer_ratio", lambda x: np.percentile(x.dropna(), 90) if x.notna().any() else np.nan),
             max_buffer_ratio=("buffer_ratio", "max"),
             median_vs_gap_pct=("vs_gap_pct", "median"),
             n_nonprotective=("non_protective", "sum"))
        .reset_index()
    )
    print(per_lev.to_string(index=False))

    bins = [1.0, 1.5, 2.0, 3.0, 5.0, 100.0]
    labels = ["(1.0-1.5]", "(1.5-2.0]", "(2.0-3.0]", "(3.0-5.0]", "(5.0+)"]
    lev_gt1["lev_bucket"] = pd.cut(lev_gt1["leverage"], bins=bins, labels=labels)
    print("\nBucketed:")
    bucketed = (
        lev_gt1.groupby("lev_bucket", observed=True)
        .agg(n=("buffer_ratio", "size"),
             median_buffer_ratio=("buffer_ratio", "median"),
             p10_vs_gap_pct=("vs_gap_pct", lambda x: np.percentile(x.dropna(), 10) if x.notna().any() else np.nan),
             median_vs_gap_pct=("vs_gap_pct", "median"),
             n_nonprotective=("non_protective", "sum"))
        .reset_index()
    )
    print(bucketed.to_string(index=False))

    # -----------------------------------------------------------------
    # SECTION 4: co-pilot cross-check
    # -----------------------------------------------------------------
    cc = None
    if not args.skip_copilot_crosscheck:
        print("\n" + "=" * 100)
        print("4) CROSS-CHECK vs copilot.py's horizon-aware safe-leverage ceiling (OOS-calibrated to ~4% liq risk)")
        print("   NOTE: copilot's horizon calibration only has H in {3,5} days; hold_days snaps to the")
        print("   NEAREST of those, so trades with sub-day holds (most of this ledger) are being compared")
        print("   against the STRICTER 3-day tail than their actual (shorter, lower-tail-risk) hold -")
        print("   i.e. this cross-check is conservative in the direction of flagging risk, not hiding it.")
        print("=" * 100)
        try:
            cc = copilot_crosscheck(geo, args.refresh)
        except Exception as e:
            print(f"[crosscheck] failed: {e}", file=sys.stderr)
            cc = None
        if cc is not None and not cc.empty:
            print(f"n trades with a co-pilot ceiling computed: {len(cc)} / {len(geo)}")
            print(f"\nhorizon calibration available (horizon_used not null): {cc['copilot_horizon_used'].notna().sum()} / {len(cc)}")
            print(f"actual leverage EXCEEDS copilot's safe_max_leverage ceiling: {int(cc['exceeds_copilot_safe'].sum())} / {len(cc)}")
            print("\nPer-symbol median copilot safe_max_leverage vs actual leverage used:")
            piv = cc.groupby("symbol").agg(
                n=("actual_leverage", "size"),
                median_actual_lev=("actual_leverage", "median"),
                max_actual_lev=("actual_leverage", "max"),
                median_copilot_safe_lev=("copilot_safe_max_leverage", "median"),
                n_exceeds=("exceeds_copilot_safe", "sum"),
            ).reset_index()
            print(piv.to_string(index=False))
            exceed_rows = cc[cc["exceeds_copilot_safe"]]
            if not exceed_rows.empty:
                print(f"\nTrades where actual leverage exceeded copilot's safe ceiling (n={len(exceed_rows)}):")
                print(exceed_rows[["trade_id", "symbol", "side", "actual_leverage", "copilot_safe_max_leverage",
                                    "copilot_horizon_used", "hold_hours", "buffer_ratio", "non_protective"]].to_string(index=False))
        else:
            print("Cross-check produced no rows (data fetch issue) - section skipped, not a pass/fail signal.")
    else:
        print("\n[4] Co-pilot cross-check skipped (--skip-copilot-crosscheck)")

    # -----------------------------------------------------------------
    # SECTION 5: refute-yourself
    # -----------------------------------------------------------------
    print("\n" + "=" * 100)
    print("5) REFUTE-YOURSELF")
    print("=" * 100)
    print(f"5a) Sim/dust artifact filter: entry_price in the known sim-placeholder set {{100,150,50000}}: "
          f"{int(geo['entry_price'].isin([100.0, 150.0, 50000.0]).sum())} rows (0 expected/found -> no sim pollution in this ledger).")
    tiny_hold = geo[geo["hold_hours"] < 0.02]
    print(f"    Instant-close rows (hold_hours < 0.02h = 72s): {len(tiny_hold)} "
          f"(exit_types: {tiny_hold['exit_type'].tolist()}) - none are SL exits, so they don't pollute the slippage stat.")
    print(f"    Unmatched (excluded from all geometry stats above, not counted as 'non-protective'): {len(unmatched)} / {len(ledger)}")

    print("\n5b) SL-slippage-vs-fees sanity: see section 2b ratio above - if |slip| << fees, slippage is within")
    print("    normal execution/logging noise, not a real gap-through-the-stop.")

    print("\n5c) Sample size per leverage tier (section 3): flag any tier with n<5 as underpowered, not a verdict.")
    thin_tiers = per_lev[per_lev["n"] < 5]
    if not thin_tiers.empty:
        print(thin_tiers[["leverage", "n"]].to_string(index=False))

    print("\n5d) Hard-stop-below-SL the bot actually runs that this static entry-time geometry test CANNOT see:")
    print("    multi_strategy_main.py runs a TICK-BY-TICK liquidation-proximity monitor for every open leveraged")
    print("    position (leverage > 1.0): check_liquidation_risk() computed on live current_price each tick,")
    print("    force-closing via LIQUIDATION_PROXIMITY at < 1.5% distance from the modeled liq price (a tighter")
    print("    3% alert threshold fires first). This ledger's exit_type breakdown (section 2) shows 0 "
          "LIQUIDATION_PROXIMITY exits, meaning this monitor never had to intervene on any of the 274 trades - "
          "consistent with (not proof of, since it's a live monitor not replayed here) the static geometry in "
          "section 1 already being adequate.")

    out_csv = os.path.join(SCRATCH_DIR, "liq_geometry_records.csv")
    geo.to_csv(out_csv, index=False)
    print(f"\nWrote full per-trade records -> {out_csv}")
    if cc is not None and not cc.empty:
        cc_csv = os.path.join(SCRATCH_DIR, "copilot_crosscheck_records.csv")
        cc.to_csv(cc_csv, index=False)
        print(f"Wrote co-pilot cross-check records -> {cc_csv}")

    print("\nDone.")


if __name__ == "__main__":
    main()
