#!/usr/bin/env python
"""
exec_maker_taker_test.py - does patient MAKER-first entry beat TAKER (market)
entry, net of fees AND net of missed-fill/adverse-selection cost, OOS?
=============================================================================
WHY THIS EXISTS

Entry-EDGE (which symbol/direction/timing to pick) is a proven null on this
project (~13 tests refuted it - see project memory). The productive frontier
left for a semi-auto "co-pilot execution harness" (idea #5) is EXECUTION
MECHANICS: given a trade the owner has already decided to take, does resting
a MAKER limit order instead of firing a TAKER market order save real money?

A maker fill is cheaper (HL maker ~1.5bps/side vs taker ~4.5bps/side - see
tools/copilot/pretrade.py TAKER_FEE_BPS_PER_SIDE / MAKER_FEE_BPS_PER_SIDE,
values reproduced below, NOT imported - this script makes zero co-pilot /
live-bot imports, per the read-only-standalone mandate) AND it can capture
extra price improvement by resting away from the touch. But it can also
simply NOT FILL if price runs away - and the trades that run away without
dipping to your limit are, by construction, disproportionately the ones
that would have been profitable had you chased them with a market order.
That's the "adverse selection" cost this script tries to price honestly.

READ-ONLY / STANDALONE: no imports of copilot.py, pretrade.py, or any
live-bot package (llm/, execution/, core/, strategies/). Reads only local
historical OHLC CSVs already on disk. No network calls, no Discord, no
writes to live/replay state. Safe to run any time.

=============================================================================
METHOD

UNIVERSE: 25 alts (data/longtail/ohlc/{SYM}_1h.csv, ~200 days of 1h bars)
+ BTC, SOL (data/cache/{SYM}_1h_420d.csv, ~208 days of 1h bars). 1h is the
finest granularity available for the alts; used uniformly for BTC/SOL too
so the fill/miss mechanics are apples-to-apples across the whole universe.

DATA HONESTY NOTE: the two universes do not share an end date. The longtail
alt CSVs run through ~2026-07-31 (last backfill), while the BTC/SOL cache
(data/cache/BTC_1h_420d.csv / SOL_1h_420d.csv) tops out ~2026-07-14 - a
~17-day gap (see corr_stress_test.py's module docstring for the same
BTC/SOL cache ceiling). Every metric here is computed PER-SYMBOL over each
symbol's own history, so this does not bias fill rates or adverse-selection
deltas within a symbol - but it means BTC/SOL results reflect ~2.5 weeks
less-recent market conditions than the alt results when compared side by
side. Disclosed, not hidden.

SAMPLING FRAME (entry-agnostic, stated explicitly per the moat): since
entry timing has no proven edge, there is no principled way to reconstruct
"the bot's real entries" cheaply and honestly. Instead every bar at a fixed
stride (default: 24 bars = once/day) across each symbol's OOS half is
treated as a hypothetical decision point, for BOTH a hypothetical LONG and
a hypothetical SHORT. This is a SAMPLING FRAME for execution mechanics, not
a claim about the bot's actual trade list - the question under test
(maker vs taker AT a decision point) does not depend on which decision
points you pick, only on there being enough of them, spread across enough
regimes, to measure fill rates and adverse selection honestly.

OOS: entry-time-safe. For each symbol independently, the FIRST HALF of its
own history is treated as burn-in/ignored; only the SECOND HALF (OOS) is
used for decision points. The OOS half is further split into two equal
sub-eras (OOS-A older, OOS-B newer) to check the verdict doesn't flip
across eras (per-era refute-yourself).

FILL MODEL:
  TAKER: fill at close[t], pay TAKER_FEE_BPS_PER_SIDE. Always fills
  (that's the point of a market order) - zero miss risk, zero price
  improvement.

  MAKER: rest a limit at close[t] * (1 -+ K bps) (LONG places it K bps
  BELOW close, SHORT places it K bps ABOVE close) for up to M forward bars.
    - "touch" fill model (OPTIMISTIC): fills the instant the bar's low
      (long) / high (short) reaches the limit. This is the standard
      backtest simplification and it is optimistic - a mere touch does not
      guarantee you had queue priority to actually get filled.
    - "through" fill model (CONSERVATIVE): requires the bar to trade
      THROUGH the limit by an extra THROUGH_BUFFER_BPS, not just touch it -
      a crude proxy for queue-position risk. Reported side-by-side with
      "touch" so the fill-model-optimism gap is visible, not hidden.
  If unfilled after M bars, two policies are scored:
    - MISS: no trade taken. The economic cost is scored as the forward
      return a TAKER would have captured from t over a fixed holding
      horizon H (H in {24h, 72h}, both > max(M) so this is a genuine
      post-window persistence read, not just re-measuring the fill
      window). This can be NEGATIVE (missing a loser is a benefit).
    - CHASE: fill at close[t+M] via a market (taker) order - fee +
      whatever adverse price move happened while waiting.

METRIC (bps of notional, all per ONE-WAY entry, not round-trip):
  TAKER total cost            = TAKER_FEE_BPS_PER_SIDE                (flat)
  MAKER cost | filled         = MAKER_FEE_BPS_PER_SIDE - K            (flat given K; the whole
                                                                        point of resting is capturing K)
  MAKER total (CHASE policy)  = fill_rate*(maker cost|filled)
                                 + (1-fill_rate)*(TAKER_FEE_BPS_PER_SIDE + mean adverse chase move)
  MAKER total (MISS policy,H) = fill_rate*(maker cost|filled)
                                 + (1-fill_rate)*(mean taker fwd return on the MISSED subset, horizon H)
  NET BENEFIT of maker        = TAKER total - MAKER total   (positive = maker wins)
  ADVERSE-SELECTION DELTA(H)  = mean taker fwd return on MISSED subset
                                 - mean taker fwd return on the FULL decision set (same H)
                                 -> the honesty number: how much more (or less) favorable
                                    are the specific trades the maker order misses, versus
                                    an unconditional draw from the same universe/era.

REFUTE-YOURSELF, EXPLICITLY:
  1. The "touch" fill model is optimistic by construction - always compare
     against "through" before believing a maker win.
  2. A maker win that only shows up on the MISS policy at long-ish M/K and
     disappears at CHASE policy is capturing something OTHER than genuine
     execution savings - if the adverse-selection delta is small (misses
     aren't special) but the miss-policy "win" is large, that's a
     mean-reversion artifact of the specific sample era, not a durable
     execution edge. This script prints the delta so that read is visible,
     not asserted.
  3. Liquidity split (MAJOR = BTC/SOL, n=2 symbols; ALT = the 25 longtail
     names, n=25) is coarse and the MAJOR group's n is small - flagged
     explicitly in the output, not smoothed over. A secondary, data-driven
     dollar-volume tercile split within the ALT group is also reported.

Usage:
    python tools/copilot/exec_maker_taker_test.py
    python tools/copilot/exec_maker_taker_test.py --stride 12 --k-list 5,10,20,30 --m-list 1,4,12,24
    python tools/copilot/exec_maker_taker_test.py --out-csv sweep.csv
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LONGTAIL_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")

# ---------------------------------------------------------------------------
# FEES - reproduced (NOT imported, per the no-live-copilot-import mandate)
# from tools/copilot/pretrade.py's TAKER_FEE_BPS_PER_SIDE / MAKER_FEE_BPS_PER_SIDE
# (HL base-tier, no VIP discount assumed). Verify against that file if HL's
# published schedule changes - this script deliberately does not import it
# so it can never accidentally pull in a live/network-touching dependency.
# ---------------------------------------------------------------------------
TAKER_FEE_BPS_PER_SIDE = 4.5   # one-way; pretrade.py RT = 2x this = ~9bps
MAKER_FEE_BPS_PER_SIDE = 1.5   # one-way; pretrade.py RT = 2x this = ~3bps

ALT_SYMBOLS = [
    "AAVE", "ADA", "APT", "ARB", "AVAX", "BCH", "CRV", "FARTCOIN", "LDO",
    "LINK", "LTC", "ONDO", "PAXG", "PENGU", "PUMP", "SUI", "TAO", "TRX",
    "UNI", "WLD", "XPL", "ZEC", "kBONK", "kPEPE", "kSHIB",
]
MAJOR_SYMBOLS = ["BTC", "SOL"]
ALL_SYMBOLS = ALT_SYMBOLS + MAJOR_SYMBOLS

DEFAULT_K_LIST_BPS = [5, 10, 20, 30]
DEFAULT_M_LIST_BARS = [1, 4, 12, 24]     # 1h .. 24h ("up to a day", per spec)
FILL_MODELS = ["touch", "through"]
THROUGH_BUFFER_BPS = 3.0                  # conservative-variant queue-position proxy
ADVERSE_HORIZONS_H = [24, 72]             # forward hold horizons (hours) for miss-cost, > max(M)
DEFAULT_STRIDE_BARS = 24                  # entry-agnostic sampling frame: once/day
MAX_LOOKAHEAD = max(max(DEFAULT_M_LIST_BARS), max(ADVERSE_HORIZONS_H))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_alt(symbol: str) -> pd.DataFrame:
    path = os.path.join(LONGTAIL_DIR, f"{symbol}_1h.csv")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["dt_utc_iso"], utc=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["time", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return df


def load_major(symbol: str) -> pd.DataFrame:
    path = os.path.join(CACHE_DIR, f"{symbol}_1h_420d.csv")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df[["time", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return df


def load_all_symbols() -> Dict[str, pd.DataFrame]:
    out = {}
    for sym in ALT_SYMBOLS:
        try:
            out[sym] = load_alt(sym)
        except FileNotFoundError:
            print(f"  [skip] {sym}: no 1h longtail file found")
    for sym in MAJOR_SYMBOLS:
        try:
            out[sym] = load_major(sym)
        except FileNotFoundError:
            print(f"  [skip] {sym}: no 1h cache file found")
    return out


def liquidity_ranking(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Data-driven sanity check: median hourly dollar volume per symbol.
    Used only to sanity-check the MAJOR-vs-ALT split and to build a
    secondary within-ALT tercile split - NOT the primary grouping (the
    primary grouping is the task's own MAJOR=BTC/SOL vs ALT=25-longtail
    framing, kept because it's the honest a-priori split, not one picked
    after seeing the results)."""
    rows = []
    for sym, df in data.items():
        dollar_vol = (df["close"] * df["volume"]).median()
        rows.append({"symbol": sym, "median_hourly_dollar_vol": dollar_vol, "n_bars": len(df)})
    rank = pd.DataFrame(rows).sort_values("median_hourly_dollar_vol", ascending=False).reset_index(drop=True)
    return rank


# ---------------------------------------------------------------------------
# Core per-symbol computation
# ---------------------------------------------------------------------------
@dataclass
class SweepConfig:
    k_list: List[float]
    m_list: List[int]
    stride: int
    through_buffer_bps: float = THROUGH_BUFFER_BPS
    horizons: List[int] = None

    def __post_init__(self):
        if self.horizons is None:
            self.horizons = ADVERSE_HORIZONS_H


def decision_indices(n: int, stride: int, max_lookahead: int) -> np.ndarray:
    """OOS = second half of the symbol's own history. Decision points are
    every `stride`-th bar within that OOS half, subject to enough forward
    bars remaining for the longest M/H lookahead (entry-time-safe: nothing
    here uses information from before the decision bar to choose K/M/side;
    the lookahead is only used to SCORE the outcome, which is standard
    backtest evaluation, not leakage)."""
    oos_start = n // 2
    last_valid = n - 1 - max_lookahead
    if last_valid <= oos_start:
        return np.array([], dtype=int)
    return np.arange(oos_start, last_valid + 1, stride)


def compute_symbol_rows(symbol: str, df: pd.DataFrame, cfg: SweepConfig) -> List[dict]:
    n = len(df)
    idx = decision_indices(n, cfg.stride, MAX_LOOKAHEAD)
    if len(idx) < 5:
        return []

    close = df["close"].to_numpy()
    low = df["low"].to_numpy()
    high = df["high"].to_numpy()

    # era split by POSITION within the chronologically-ordered decision array
    half = len(idx) // 2
    era_labels = np.array(["A"] * half + ["B"] * (len(idx) - half))

    ref = close[idx]
    rows: List[dict] = []

    for side in ("LONG", "SHORT"):
        # forward taker return at each horizon H (signed toward the side's profit direction)
        fwd_ret_h = {}
        for h in cfg.horizons:
            fut = close[idx + h]
            if side == "LONG":
                fwd_ret_h[h] = (fut - ref) / ref * 1e4
            else:
                fwd_ret_h[h] = (ref - fut) / ref * 1e4

        for m in cfg.m_list:
            # forward extreme reached within the next m bars (excludes bar t itself)
            if side == "LONG":
                fwd_extreme = np.array([low[i + 1:i + 1 + m].min() for i in idx])
            else:
                fwd_extreme = np.array([high[i + 1:i + 1 + m].max() for i in idx])

            chase_price = close[idx + m]
            if side == "LONG":
                adverse_chase_bps = (chase_price - ref) / ref * 1e4
            else:
                adverse_chase_bps = (ref - chase_price) / ref * 1e4

            for fill_model in FILL_MODELS:
                buf = cfg.through_buffer_bps if fill_model == "through" else 0.0
                for k in cfg.k_list:
                    if side == "LONG":
                        limit = ref * (1 - k / 1e4)
                        threshold = limit * (1 - buf / 1e4)
                        filled = fwd_extreme <= threshold
                    else:
                        limit = ref * (1 + k / 1e4)
                        threshold = limit * (1 + buf / 1e4)
                        filled = fwd_extreme >= threshold

                    for era in ("ALL", "A", "B"):
                        mask = np.ones(len(idx), dtype=bool) if era == "ALL" else (era_labels == era)
                        n_era = int(mask.sum())
                        if n_era == 0:
                            continue
                        filled_e = filled[mask]
                        unfilled_e = ~filled_e
                        n_unfilled = int(unfilled_e.sum())
                        fill_rate = float(filled_e.mean())

                        adv_chase = adverse_chase_bps[mask]
                        mean_adverse_chase = float(adv_chase[unfilled_e].mean()) if n_unfilled > 0 else np.nan

                        row = {
                            "symbol": symbol, "side": side, "M": m, "fill_model": fill_model,
                            "K": k, "era": era, "n": n_era, "n_unfilled": n_unfilled,
                            "fill_rate": fill_rate, "mean_adverse_chase_bps": mean_adverse_chase,
                        }
                        for h in cfg.horizons:
                            fr = fwd_ret_h[h][mask]
                            row[f"mean_taker_fwd_missed_h{h}"] = (
                                float(fr[unfilled_e].mean()) if n_unfilled > 0 else np.nan
                            )
                            row[f"mean_taker_fwd_all_h{h}"] = float(fr.mean())
                        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Aggregation across symbols (weighted by decision count, not symbol-of-symbol
# averaging - a symbol with more OOS history shouldn't be diluted to the same
# weight as one with a short history)
# ---------------------------------------------------------------------------
def weighted_group_agg(df: pd.DataFrame, group_cols: List[str], horizons: List[int]) -> pd.DataFrame:
    def agg_one(g: pd.DataFrame) -> pd.Series:
        n_sum = g["n"].sum()
        nu_sum = g["n_unfilled"].sum()
        out = {
            "n": n_sum,
            "n_unfilled": nu_sum,
            "fill_rate": (g["fill_rate"] * g["n"]).sum() / n_sum if n_sum else np.nan,
        }
        if nu_sum > 0:
            out["mean_adverse_chase_bps"] = (g["mean_adverse_chase_bps"] * g["n_unfilled"]).sum() / nu_sum
        else:
            out["mean_adverse_chase_bps"] = np.nan
        for h in horizons:
            colm = f"mean_taker_fwd_missed_h{h}"
            cola = f"mean_taker_fwd_all_h{h}"
            out[cola] = (g[cola] * g["n"]).sum() / n_sum if n_sum else np.nan
            out[colm] = (g[colm] * g["n_unfilled"]).sum() / nu_sum if nu_sum > 0 else np.nan
        return pd.Series(out)

    return df.groupby(group_cols, dropna=False).apply(agg_one, include_groups=False).reset_index()


def add_verdict_columns(g: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    g = g.copy()
    g["taker_total_bps"] = TAKER_FEE_BPS_PER_SIDE
    g["maker_filled_cost_bps"] = MAKER_FEE_BPS_PER_SIDE - g["K"]
    g["maker_total_chase_bps"] = (
        g["fill_rate"] * g["maker_filled_cost_bps"]
        + (1 - g["fill_rate"]) * (TAKER_FEE_BPS_PER_SIDE + g["mean_adverse_chase_bps"].fillna(0.0))
    )
    g["net_benefit_chase_bps"] = g["taker_total_bps"] - g["maker_total_chase_bps"]
    for h in horizons:
        colm = f"mean_taker_fwd_missed_h{h}"
        cola = f"mean_taker_fwd_all_h{h}"
        g[f"maker_total_miss_h{h}_bps"] = (
            g["fill_rate"] * g["maker_filled_cost_bps"]
            + (1 - g["fill_rate"]) * g[colm].fillna(0.0)
        )
        g[f"net_benefit_miss_h{h}_bps"] = g["taker_total_bps"] - g[f"maker_total_miss_h{h}_bps"]
        g[f"adverse_selection_delta_h{h}_bps"] = g[colm] - g[cola]
    return g


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def fmt_bps(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=DEFAULT_STRIDE_BARS, help="bars between decision points (default 24 = once/day)")
    ap.add_argument("--k-list", type=str, default=",".join(str(k) for k in DEFAULT_K_LIST_BPS), help="comma list of limit-offset bps to sweep")
    ap.add_argument("--m-list", type=str, default=",".join(str(m) for m in DEFAULT_M_LIST_BARS), help="comma list of wait windows (bars=hours) to sweep")
    ap.add_argument("--out-csv", type=str, default=None, help="optional path to dump the full per-symbol sweep to CSV")
    args = ap.parse_args()

    k_list = [float(x) for x in args.k_list.split(",")]
    m_list = [int(x) for x in args.m_list.split(",")]
    cfg = SweepConfig(k_list=k_list, m_list=m_list, stride=args.stride)

    print("=" * 100)
    print("MAKER-vs-TAKER ENTRY EXECUTION TEST - read-only, standalone, OOS, entry-agnostic")
    print("=" * 100)
    print(f"Fees (from pretrade.py, reproduced not imported): TAKER {TAKER_FEE_BPS_PER_SIDE}bps/side, "
          f"MAKER {MAKER_FEE_BPS_PER_SIDE}bps/side (savings if filled at touch = {TAKER_FEE_BPS_PER_SIDE - MAKER_FEE_BPS_PER_SIDE:.1f}bps + K bps price improvement)")
    print(f"Sweep: K(bps)={k_list}  M(hours)={m_list}  fill_models={FILL_MODELS} (through buffer={THROUGH_BUFFER_BPS}bps)  "
          f"stride={args.stride}h  horizons(h)={ADVERSE_HORIZONS_H}")
    print()

    print("Loading data...")
    data = load_all_symbols()
    print(f"  loaded {len(data)} symbols: {sorted(data.keys())}")
    print()

    rank = liquidity_ranking(data)
    print("-- Data-driven liquidity sanity check (median hourly $ volume, full history) --")
    print(rank.to_string(index=False, float_format=lambda x: f"{x:,.0f}"))
    print()

    all_rows: List[dict] = []
    for sym, df in data.items():
        rows = compute_symbol_rows(sym, df, cfg)
        if not rows:
            print(f"  [skip] {sym}: insufficient OOS bars for lookahead={MAX_LOOKAHEAD}")
            continue
        all_rows.extend(rows)

    sweep = pd.DataFrame(all_rows)
    if sweep.empty:
        print("No decision points produced - check data files.")
        return

    if args.out_csv:
        sweep.to_csv(args.out_csv, index=False)
        print(f"Full per-symbol sweep written to {args.out_csv} ({len(sweep)} rows)")

    sweep["liquidity_group"] = np.where(sweep["symbol"].isin(MAJOR_SYMBOLS), "MAJOR(BTC/SOL)", "ALT(25 longtail)")

    # secondary data-driven tercile split within ALT group (robustness, not primary)
    alt_rank = rank[rank["symbol"].isin(ALT_SYMBOLS)].copy()
    alt_rank["alt_tercile"] = pd.qcut(alt_rank["median_hourly_dollar_vol"], 3, labels=["ALT-thin", "ALT-mid", "ALT-liquid"])
    tercile_map = dict(zip(alt_rank["symbol"], alt_rank["alt_tercile"]))
    sweep["alt_tercile"] = sweep["symbol"].map(tercile_map)

    horizons = ADVERSE_HORIZONS_H

    # ---- Main table: pooled both sides, era=ALL, by liquidity_group x M x fill_model x K
    pooled = sweep[sweep["era"] == "ALL"]
    grp = weighted_group_agg(pooled, ["liquidity_group", "M", "fill_model", "K"], horizons)
    grp = add_verdict_columns(grp, horizons)

    print()
    print("=" * 100)
    print("MAIN RESULT: net entry-cost benefit of MAKER vs TAKER (bps/trade, positive = maker wins), OOS, pooled sides")
    print("=" * 100)
    h72 = horizons[-1]
    cols = ["liquidity_group", "M", "fill_model", "K", "n", "fill_rate",
            f"net_benefit_miss_h{h72}_bps", "net_benefit_chase_bps", f"adverse_selection_delta_h{h72}_bps"]
    disp = grp[cols].sort_values(["liquidity_group", "M", "fill_model", "K"])
    disp = disp.round({"fill_rate": 3, f"net_benefit_miss_h{h72}_bps": 2, "net_benefit_chase_bps": 2, f"adverse_selection_delta_h{h72}_bps": 2})
    print(disp.to_string(index=False))
    print()
    print("(net_benefit_miss = TAKER cost minus MAKER's cost-if-filled blended with the forgone taker P&L")
    print(f" on missed decisions over a {h72}h hold; net_benefit_chase = same blend but unfilled orders")
    print(" chase at market after M bars instead of walking away; adverse_selection_delta = how much MORE")
    print(f" favorable (for a taker) the missed decisions were vs an unconditional draw, over {h72}h -")
    print(" positive means misses are disproportionately the good ones, i.e. adverse selection is real.)")
    print()

    # ---- Best config per liquidity group, by miss-policy net benefit ----
    print("=" * 100)
    print("BEST CONFIG PER LIQUIDITY GROUP (ranked by net_benefit_miss_h72_bps)")
    print("=" * 100)
    best_rows = {}
    for group in grp["liquidity_group"].unique():
        sub = grp[grp["liquidity_group"] == group].sort_values(f"net_benefit_miss_h{h72}_bps", ascending=False)
        best = sub.iloc[0]
        best_rows[group] = best
        print(f"\n[{group}]  n_symbols={sweep[sweep['liquidity_group']==group]['symbol'].nunique()}")
        print(f"  best K={best['K']:.0f}bps, M={best['M']:.0f}h, fill_model={best['fill_model']}")
        print(f"  n_decisions={int(best['n'])}  fill_rate={best['fill_rate']:.1%}")
        print(f"  MAKER cost if filled: {fmt_bps(best['maker_filled_cost_bps'])}bps  (vs TAKER flat {TAKER_FEE_BPS_PER_SIDE:+.2f}bps)")
        for h in horizons:
            print(f"  net_benefit @ MISS policy, H={h}h: {fmt_bps(best[f'net_benefit_miss_h{h}_bps'])}bps/trade   "
                  f"(adverse-selection delta: {fmt_bps(best[f'adverse_selection_delta_h{h}_bps'])}bps)")
        print(f"  net_benefit @ CHASE policy:        {fmt_bps(best['net_benefit_chase_bps'])}bps/trade   "
              f"(mean adverse chase move: {fmt_bps(best['mean_adverse_chase_bps'])}bps)")

        # fill-model-optimism check: same K,M, opposite fill_model
        other_model = "through" if best["fill_model"] == "touch" else "touch"
        cmp_row = grp[(grp["liquidity_group"] == group) & (grp["M"] == best["M"]) &
                      (grp["K"] == best["K"]) & (grp["fill_model"] == other_model)]
        if not cmp_row.empty:
            cr = cmp_row.iloc[0]
            print(f"  [fill-model-optimism check] same K/M under '{other_model}': "
                  f"fill_rate={cr['fill_rate']:.1%} (vs {best['fill_rate']:.1%} optimistic), "
                  f"net_benefit_miss_h{h72}={fmt_bps(cr[f'net_benefit_miss_h{h72}_bps'])}bps "
                  f"(vs {fmt_bps(best[f'net_benefit_miss_h{h72}_bps'])}bps optimistic)")

    # ---- Era stability check for each best config ----
    print()
    print("=" * 100)
    print("PER-ERA STABILITY CHECK (best config per group, OOS-A = older half, OOS-B = newer half)")
    print("=" * 100)
    for group, best in best_rows.items():
        era_sub = sweep[(sweep["liquidity_group"] == group) & (sweep["era"].isin(["A", "B"])) &
                         (sweep["M"] == best["M"]) & (sweep["K"] == best["K"]) & (sweep["fill_model"] == best["fill_model"])]
        era_grp = weighted_group_agg(era_sub, ["era"], horizons)
        era_grp["K"] = best["K"]  # constant within era_sub (filtered on it above); not a groupby col so re-attach
        era_grp = add_verdict_columns(era_grp, horizons)
        print(f"\n[{group}] K={best['K']:.0f}bps M={best['M']:.0f}h {best['fill_model']}:")
        for _, r in era_grp.sort_values("era").iterrows():
            print(f"  era {r['era']}: n={int(r['n'])} fill_rate={r['fill_rate']:.1%} "
                  f"net_benefit_miss_h{h72}={fmt_bps(r[f'net_benefit_miss_h{h72}_bps'])}bps "
                  f"net_benefit_chase={fmt_bps(r['net_benefit_chase_bps'])}bps")

    # ---- Within-ALT liquidity tercile breakdown (secondary, data-driven) ----
    print()
    print("=" * 100)
    print("SECONDARY: within-ALT data-driven liquidity tercile (does it grade smoothly by $ volume?)")
    print("=" * 100)
    tercile_pooled = sweep[(sweep["era"] == "ALL") & (sweep["liquidity_group"] == "ALT(25 longtail)")]
    tgrp = weighted_group_agg(tercile_pooled, ["alt_tercile", "M", "fill_model", "K"], horizons)
    tgrp = add_verdict_columns(tgrp, horizons)
    for tercile in ["ALT-liquid", "ALT-mid", "ALT-thin"]:
        sub = tgrp[tgrp["alt_tercile"] == tercile].sort_values(f"net_benefit_miss_h{h72}_bps", ascending=False)
        if sub.empty:
            continue
        best = sub.iloc[0]
        print(f"  {tercile}: best K={best['K']:.0f} M={best['M']:.0f} {best['fill_model']} -> "
              f"fill_rate={best['fill_rate']:.1%} net_benefit_miss_h{h72}={fmt_bps(best[f'net_benefit_miss_h{h72}_bps'])}bps "
              f"net_benefit_chase={fmt_bps(best['net_benefit_chase_bps'])}bps")

    # ---- Side symmetry sanity check (fixed representative K/M/fill_model so
    # the comparison isn't averaging across incompatible configs) ----
    print()
    rep_k, rep_m, rep_fm = 20.0, 4, "touch"
    print(f"-- sanity check: LONG vs SHORT should be roughly mirror images (no directional bug); "
          f"fixed K={rep_k:.0f}bps M={rep_m}h {rep_fm} --")
    side_pooled = sweep[(sweep["era"] == "ALL") & (sweep["K"] == rep_k) & (sweep["M"] == rep_m) & (sweep["fill_model"] == rep_fm)]
    sgrp = weighted_group_agg(side_pooled, ["side", "liquidity_group"], horizons)
    sgrp["K"] = rep_k  # constant within side_pooled; re-attach since it's not a groupby col
    sgrp = add_verdict_columns(sgrp, horizons)
    print(sgrp[["side", "liquidity_group", "n", "fill_rate", f"net_benefit_miss_h{h72}_bps", "net_benefit_chase_bps"]]
          .round(3).to_string(index=False))

    # ---- Programmatic verdict ----
    print()
    print("=" * 100)
    print("VERDICT (generated from the numbers above, not asserted)")
    print("=" * 100)
    for group, best in best_rows.items():
        nb_miss = best[f"net_benefit_miss_h{h72}_bps"]
        nb_chase = best["net_benefit_chase_bps"]
        adv_delta = best[f"adverse_selection_delta_h{h72}_bps"]
        n_sym = sweep[sweep["liquidity_group"] == group]["symbol"].nunique()
        small_n_flag = "  [CAUTION: n_symbols is small, treat as directional not conclusive]" if n_sym <= 3 else ""
        if nb_chase < 0 and nb_miss < 0:
            verdict = "adverse selection / chase cost EATS the fee saving -> do NOT build maker-first for this group"
        elif nb_miss > 0 and nb_chase > 0:
            verdict = f"maker-first WINS net under both unfilled policies -> worth building for this group"
        else:
            verdict = "policy-dependent: wins if you're willing to walk away on a miss, but chasing erodes it - a MISS-only (never chase) harness might be worth it, a chase-prone one is not"
        print(f"[{group}]{small_n_flag}")
        print(f"  best K={best['K']:.0f}bps/M={best['M']:.0f}h/{best['fill_model']}: "
              f"net_benefit(MISS,H={h72}h)={fmt_bps(nb_miss)}bps, net_benefit(CHASE)={fmt_bps(nb_chase)}bps, "
              f"adverse_selection_delta={fmt_bps(adv_delta)}bps")
        print(f"  -> {verdict}")
    print()
    print("Reminder: 'touch' fill model is optimistic (see fill-model-optimism check above for the 'through'")
    print("conservative variant's fill-rate haircut) and this is bps/trade on the ENTRY LEG ONLY - it does not")
    print("re-litigate entry-edge (proven null) or exit discipline, only the mechanical cost of HOW you get in.")


if __name__ == "__main__":
    main()
