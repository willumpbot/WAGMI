#!/usr/bin/env python
"""
Standalone, READ-ONLY value test for tools/copilot/weather.py's MARKET WEATHER
regime (breadth20 + BTC-vs-50dEMA -> STORMY/HEADWIND/WASHED_OUT/NEUTRAL).

Does NOT import copilot.py or weather.py (another agent is editing weather.py
concurrently) - the regime formulas are re-implemented standalone here, byte-
for-byte matched to weather.py's `_classify_regime` / `_closed_daily_df` /
breadth20 / BTC-EMA50 logic as read on 2026-07-31.

MEMORY ALREADY SETTLED (do NOT re-litigate here):
  - "washed-out makes dips better" -> REFUTED (ADD underperforms non-ADD
    inside washed-out by ~-2.6%/3d OOS).
  - "stormy-short" -> evaporates OOS with a fat squeeze tail.

THIS script tests the ACTUAL claimed use of weather: a CONTEXT / SIZING /
RISK gate. Does the regime separate high-tail-risk days from calm days OOS,
or is it noise / an era proxy / a restatement of "it's been volatile lately"?

DATA
----
- 25 alt daily OHLC CSVs: data/longtail/ohlc/*_1d.csv (already-collected,
  read-only).
- BTC/SOL daily OHLC: NOT present in data/longtail/ohlc (checked - only the
  live cache exists, and it's capped at ~208 rows / Dec-2025 onward, too
  short to cover the alts' 2025-06-26 start). Fetched fresh, read-only, from
  Hyperliquid's public info API (same source weather.py's `fetch_ohlc` would
  hit live) for the SAME 2025-06-26..today window the alt CSVs cover, saved
  to the scratchpad (not written into data/) as BTC_1d.csv / SOL_1d.csv.
  This is pure research data acquisition, no live/.env/copilot.py touched.

METHOD (entry-time-safe throughout)
------------------------------------
- Regime at day t uses ONLY closes through day t (breadth20 SMA + BTC EMA50
  are both causal/trailing by construction - pandas .ewm()/.rolling() never
  peek forward). Day t's regime is then used to condition day (t+1 .. t+H)
  forward outcomes - never the reverse.
- OOS = second half of the shared date range (chronological split, no
  shuffling).
- Forward tail metrics per (coin, day) pair, H=5 trading days, mirroring
  copilot.py's own `compute_horizon_tail_frac` MAE definition (see that
  function's docstring) rather than inventing a new one:
      LONG MAE(i, H) = (close[i] - min(low[i+1..i+H])) / close[i]   (>=0)
  plus forward 5d return, forward daily realized vol, and CVaR5% (mean of
  the worst 5% of forward-5d returns) - all pooled across the 25-coin
  universe, grouped by the regime label measured at day i.
- Sizing-gate backtest: an equal-weight "always long the alt book" daily
  return series, sized by regime (STORMY=0.25x, HEADWIND=0.5x,
  WASHED_OUT/NEUTRAL=1.0x - i.e. exactly weather.py's own printed
  permission language), vs a flat-1.0x baseline. A 9bps (taker round-trip,
  per data/longtail/universe.json's `taker_fee_bps_round_trip`) drag is
  charged on every day the size changes, so the comparison is net-of-fee.
- Ablation: BTC-alone (2 buckets) and breadth-alone (3 buckets, same 20/50
  thresholds) regimes, same forward-tail pipeline, to see whether the 2nd
  factor (breadth) earns its keep over BTC-EMA alone.
- Contamination check: forward realized vol grouped by regime label vs
  forward realized vol grouped by trailing-realized-vol tercile (same
  causal, entry-time-safe construction) - if trailing-vol terciles
  separate forward vol just as well, the regime is not adding information
  beyond "it's been volatile lately."
- Per-era breakdown: the shared date range split into ~2 month blocks,
  regime x forward-CVaR recomputed per block, to check the ordering isn't
  carried by one high-vol era (memory flags 2026-01/02 as the loud one).

No Discord. No writes outside this file + printed report.
"""
from __future__ import annotations

import glob
import os
import warnings
from datetime import timedelta, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LONGTAIL_OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
SCRATCH_DIR = (
    r"C:\Users\vince\AppData\Local\Temp\claude\C--Users-vince"
    r"\6fad1965-9726-4e6a-b6d6-9dcf0b9f2c97\scratchpad"
)

BREADTH_SMA_PERIOD = 20
BTC_EMA_PERIOD = 50
BREADTH_HIGH_PCT = 50.0
BREADTH_LOW_PCT = 20.0
H = 5                      # forward horizon, trading days
FEE_BPS_ROUND_TRIP = 9.0   # from data/longtail/universe.json taker_fee_bps_round_trip
SIZE_MAP = {"STORMY": 0.25, "HEADWIND": 0.5, "WASHED_OUT": 1.0, "NEUTRAL": 1.0}

EXCLUDE_FROM_UNIVERSE = {"PUMP", "XPL"}  # too-short history distorts early-sample breadth; noted, not hidden


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _load_1d(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["t"] = pd.to_datetime(df["dt_utc_iso"], utc=True, errors="coerce")
    df["c"] = pd.to_numeric(df["c"], errors="coerce")
    df["l"] = pd.to_numeric(df["l"], errors="coerce")
    df["h"] = pd.to_numeric(df["h"], errors="coerce")
    df = df.dropna(subset=["t", "c", "l", "h"]).sort_values("t").reset_index(drop=True)
    # entry-time-safe: drop an in-progress "today" candle if present (same
    # guard as weather.py's _closed_daily_df)
    now = pd.Timestamp.now(tz=timezone.utc)
    if len(df) and (df["t"].iloc[-1] + timedelta(days=1)) > now:
        df = df.iloc[:-1].reset_index(drop=True)
    return df


def load_universe() -> dict:
    coins = {}
    for path in sorted(glob.glob(os.path.join(LONGTAIL_OHLC_DIR, "*_1d.csv"))):
        coin = os.path.basename(path).replace("_1d.csv", "")
        coins[coin] = _load_1d(path)
    return coins


def build_regime_frame(alt_dfs: dict, btc_df: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar day in BTC's date range; breadth20/regime computed
    entry-time-safe. Returns columns: t, btc_c, btc_ema50, btc_above,
    breadth_pct, breadth_n, regime, breadth_only, btc_only, trail_vol10."""
    btc = btc_df.set_index("t")["c"].sort_index()
    ema50 = _ema(btc, BTC_EMA_PERIOD)
    btc_above = (btc > ema50)

    # per-coin above/below-SMA20 series aligned to their own dates, then
    # reindexed onto the BTC date grid (ffill=False - a coin missing a date
    # simply doesn't vote that day, exactly like weather.py's per-coin loop
    # which just skips coins with < BREADTH_SMA_PERIOD rows).
    above_by_coin = {}
    for coin, df in alt_dfs.items():
        if coin in EXCLUDE_FROM_UNIVERSE:
            continue
        s = df.set_index("t")["c"].sort_index()
        sma20 = s.rolling(BREADTH_SMA_PERIOD).mean()
        above = (s > sma20)
        above.loc[sma20.isna()] = np.nan  # not-yet-warmed-up -> abstain
        above_by_coin[coin] = above

    above_df = pd.DataFrame(above_by_coin).reindex(btc.index)
    n_total = above_df.notna().sum(axis=1)
    n_up = (above_df == True).sum(axis=1)  # noqa: E712
    breadth_pct = np.where(n_total > 0, n_up / n_total.replace(0, np.nan) * 100.0, np.nan)

    out = pd.DataFrame({
        "t": btc.index,
        "btc_c": btc.values,
        "btc_ema50": ema50.values,
        "btc_above": btc_above.values,
        "breadth_pct": breadth_pct,
        "breadth_n": n_total.values,
    }).reset_index(drop=True)

    def classify(row):
        if pd.isna(row["btc_above"]) or pd.isna(row["breadth_pct"]):
            return None
        btc_above = bool(row["btc_above"])
        b = row["breadth_pct"]
        breadth_high = b > BREADTH_HIGH_PCT
        breadth_low = b < BREADTH_LOW_PCT
        if btc_above and breadth_high:
            return "STORMY"
        if (not btc_above) and breadth_low:
            return "WASHED_OUT"
        if btc_above != breadth_high:
            return "HEADWIND"
        return "NEUTRAL"

    out["regime"] = out.apply(classify, axis=1)

    # ablation labels
    out["btc_only"] = np.where(out["btc_above"] == True, "BTC_ABOVE",   # noqa: E712
                        np.where(out["btc_above"] == False, "BTC_BELOW", None))  # noqa: E712

    def breadth_only(b):
        if pd.isna(b):
            return None
        if b > BREADTH_HIGH_PCT:
            return "BREADTH_HIGH"
        if b < BREADTH_LOW_PCT:
            return "BREADTH_LOW"
        return "BREADTH_MID"

    out["breadth_only"] = out["breadth_pct"].apply(breadth_only)

    # trailing realized vol (10d stdev of BTC daily returns), entry-time-safe,
    # used for the look-back-contamination check
    btc_ret = btc.pct_change()
    out["trail_vol10"] = btc_ret.rolling(10).std().reindex(btc.index).values

    return out


def forward_metrics_table(alt_dfs: dict, regime_frame: pd.DataFrame) -> pd.DataFrame:
    """Pooled (coin, day) rows: fwd_ret5, mae5 (long, magnitude), fwd_vol5,
    plus the regime label + date carried over from regime_frame at day i."""
    rf = regime_frame.set_index("t")
    rows = []
    for coin, df in alt_dfs.items():
        if coin in EXCLUDE_FROM_UNIVERSE:
            continue
        d = df.set_index("t").sort_index()
        c = d["c"].to_numpy(dtype=float)
        low = d["l"].to_numpy(dtype=float)
        n = len(c)
        m = n - H
        if m <= 0:
            continue
        idx = d.index[:m]
        entry_c = c[:m]
        # fwd 5d return
        fwd_c = c[H:H + m]
        fwd_ret5 = fwd_c / entry_c - 1.0
        # long MAE (mirrors copilot.py compute_horizon_tail_frac, H=5, LONG)
        low_windows = np.lib.stride_tricks.sliding_window_view(low[1:], H)
        fwd_min = low_windows.min(axis=1)[:m]
        mae5 = np.clip((entry_c - fwd_min) / entry_c, 0.0, None)
        # forward realized vol over the same 5-day window
        daily_ret = d["c"].pct_change()
        fwd_vol_vals = []
        dvals = daily_ret.to_numpy(dtype=float)
        for i in range(m):
            window = dvals[i + 1:i + 1 + H]
            fwd_vol_vals.append(np.nanstd(window) if len(window) == H else np.nan)
        sub = pd.DataFrame({
            "t": idx,
            "coin": coin,
            "fwd_ret5": fwd_ret5,
            "mae5": mae5,
            "fwd_vol5": fwd_vol_vals,
        })
        rows.append(sub)
    pooled = pd.concat(rows, ignore_index=True)
    pooled = pooled.merge(
        rf[["regime", "btc_only", "breadth_only", "trail_vol10"]],
        left_on="t", right_index=True, how="left",
    )
    return pooled


def cvar(x: pd.Series, q: float = 0.05) -> float:
    x = x.dropna()
    if len(x) == 0:
        return np.nan
    k = max(1, int(len(x) * q))
    return float(x.nsmallest(k).mean())


def summarize(pooled: pd.DataFrame, group_col: str) -> pd.DataFrame:
    def agg(g):
        return pd.Series({
            "n": len(g),
            "mean_fwd_ret5_%": g["fwd_ret5"].mean() * 100,
            "cvar5_fwd_ret5_%": cvar(g["fwd_ret5"]) * 100,
            "mean_mae5_%": g["mae5"].mean() * 100,
            "p90_mae5_%": g["mae5"].quantile(0.90) * 100,
            "freq_mae>=10%": (g["mae5"] >= 0.10).mean() * 100,
            "freq_mae>=20%": (g["mae5"] >= 0.20).mean() * 100,
            "freq_mae>=30%": (g["mae5"] >= 0.30).mean() * 100,
            "mean_fwd_dailyvol_%": g["fwd_vol5"].mean() * 100,
        })
    return pooled.groupby(group_col).apply(agg)


def print_table(title: str, df: pd.DataFrame):
    print(f"\n--- {title} ---")
    with pd.option_context("display.width", 160, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print(df)


def main():
    print("=" * 90)
    print("WEATHER VALUE TEST - risk/sizing-gate audit (standalone, read-only)")
    print("=" * 90)

    alt_dfs = load_universe()
    btc_df = _load_1d(os.path.join(SCRATCH_DIR, "BTC_1d.csv"))
    sol_df = _load_1d(os.path.join(SCRATCH_DIR, "SOL_1d.csv"))

    print(f"\nLoaded {len(alt_dfs)} alt CSVs, BTC rows={len(btc_df)} "
          f"({btc_df['t'].iloc[0].date()} -> {btc_df['t'].iloc[-1].date()}), "
          f"SOL rows={len(sol_df)}")
    print(f"Universe used for breadth20 (excluding short-history {sorted(EXCLUDE_FROM_UNIVERSE)}): "
          f"{sorted(c for c in alt_dfs if c not in EXCLUDE_FROM_UNIVERSE)}")

    rf = build_regime_frame(alt_dfs, btc_df)
    rf_valid = rf.dropna(subset=["regime"]).reset_index(drop=True)
    print(f"\nRegime-labeled days: {len(rf_valid)} / {len(rf)} "
          f"({rf_valid['t'].iloc[0].date()} -> {rf_valid['t'].iloc[-1].date()})")
    print("\nRegime distribution (full sample):")
    print((rf_valid["regime"].value_counts(normalize=True) * 100).round(1))

    # chronological IS/OOS split on the regime frame's date grid
    split_idx = len(rf_valid) // 2
    split_date = rf_valid["t"].iloc[split_idx]
    is_dates = set(rf_valid["t"].iloc[:split_idx])
    oos_dates = set(rf_valid["t"].iloc[split_idx:])
    print(f"\nIS/OOS split date: {split_date.date()}  (IS n={len(is_dates)}, OOS n={len(oos_dates)})")

    pooled = forward_metrics_table(alt_dfs, rf)
    pooled = pooled.dropna(subset=["regime"])
    pooled_is = pooled[pooled["t"].isin(is_dates)]
    pooled_oos = pooled[pooled["t"].isin(oos_dates)]

    # ---------------- TEST 1: risk conditioning, OOS ----------------
    print("\n" + "#" * 90)
    print("# TEST 1 - forward 5d tail metrics by regime (the real claim)")
    print("#" * 90)
    print_table("FULL SAMPLE (IS+OOS) by regime", summarize(pooled, "regime"))
    print_table("IS HALF by regime", summarize(pooled_is, "regime"))
    print_table("OOS HALF by regime (PRIMARY)", summarize(pooled_oos, "regime"))

    order = ["STORMY", "HEADWIND", "NEUTRAL", "WASHED_OUT"]
    oos_summary = summarize(pooled_oos, "regime").reindex(order)
    print("\nClaimed ordering check (STORMY worst -> NEUTRAL/WASHED_OUT calmer), OOS CVaR5 (fwd 5d ret %):")
    print(oos_summary["cvar5_fwd_ret5_%"])
    print("\nClaimed ordering check, OOS mean MAE5 (%) [higher = worse]:")
    print(oos_summary["mean_mae5_%"])
    print("\nClaimed ordering check, OOS freq(MAE>=20%) - crude liq-frequency proxy:")
    print(oos_summary["freq_mae>=20%"])

    # SOL out-of-universe robustness check: SOL is excluded from the breadth20
    # screen (weather.py docstring), so its forward tail-by-regime is a clean
    # external check that the regime's tail-risk read isn't an artifact of
    # the specific 25-coin breadth basket it's built from.
    sol_metrics = forward_metrics_table({"SOL": sol_df}, rf)
    sol_metrics = sol_metrics.dropna(subset=["regime"])
    sol_oos = sol_metrics[sol_metrics["t"].isin(oos_dates)]
    print_table("SOL-ONLY (excluded from breadth universe) OOS by regime - external check", summarize(sol_oos, "regime"))

    # ---------------- TEST 2: sizing gate ----------------
    print("\n" + "#" * 90)
    print("# TEST 2 - weather-conditioned sizing gate vs flat baseline (OOS, net of fee)")
    print("#" * 90)
    # equal-weight "alt book" daily return series, aligned on rf's date grid
    alt_daily_rets = []
    for coin, df in alt_dfs.items():
        if coin in EXCLUDE_FROM_UNIVERSE:
            continue
        s = df.set_index("t")["c"].sort_index().pct_change()
        alt_daily_rets.append(s.rename(coin))
    book_ret = pd.concat(alt_daily_rets, axis=1).mean(axis=1)  # equal-weight, NaN-safe via mean(skipna)

    reg_series = rf.set_index("t")["regime"]
    # regime known at close of day t applies to day t+1's return (shift by 1
    # calendar day on this daily grid - entry-time-safe)
    sched = reg_series.reindex(book_ret.index).shift(1)
    sizes = sched.map(SIZE_MAP).fillna(1.0)  # unlabeled days -> flat/neutral size, conservative
    flat = pd.Series(1.0, index=book_ret.index)

    def apply_fee(size_series: pd.Series, ret_series: pd.Series) -> pd.Series:
        gross = size_series * ret_series
        turn = size_series.diff().abs().fillna(size_series.iloc[0])
        fee = turn * (FEE_BPS_ROUND_TRIP / 10000.0)
        return gross - fee

    gated_ret = apply_fee(sizes, book_ret)
    flat_ret = apply_fee(flat, book_ret)  # flat baseline: one-time fee at start only, ~0 drag thereafter

    # REFUTE-YOURSELF counterfactuals:
    # (a) flat-but-scaled to the SAME average OOS exposure as the weather
    #     gate - isolates "is the improvement just lower average leverage
    #     during a losing half" from "is it correctly TIMED de-risking".
    # (b) a risk-optimal remap that derisks whichever regime TEST 1 actually
    #     showed has the fattest forward tail (checked after the fact, from
    #     the OOS summary computed above) instead of trusting weather.py's
    #     own STORMY/HEADWIND-down, WASHED_OUT-full labels.
    sizes_oos = sizes[sizes.index.isin(oos_dates)]
    avg_exposure = float(sizes_oos.mean())
    flat_scaled = pd.Series(avg_exposure, index=book_ret.index)
    flat_scaled_ret = apply_fee(flat_scaled, book_ret)

    worst_tail_regime = oos_summary["cvar5_fwd_ret5_%"].idxmin()  # most negative CVaR = fattest tail
    risk_optimal_map = {r: 1.0 for r in SIZE_MAP}
    risk_optimal_map[worst_tail_regime] = 0.25
    ro_sizes = sched.map(risk_optimal_map).fillna(1.0)
    ro_ret = apply_fee(ro_sizes, book_ret)

    results = {}
    for label, ret in [
        ("FLAT (always 1.0x)", flat_ret),
        ("WEATHER-GATED sizing", gated_ret),
        (f"FLAT-SCALED (always {avg_exposure:.3f}x, = gate's avg exposure)", flat_scaled_ret),
        (f"RISK-OPTIMAL remap (derisk {worst_tail_regime} only, 0.25x)", ro_ret),
    ]:
        r_oos = ret[ret.index.isin(oos_dates)].dropna()
        cum = (1 + r_oos).cumprod()
        run_max = cum.cummax()
        dd = (cum / run_max - 1.0)
        results[label] = {
            "total_return_%": (cum.iloc[-1] - 1) * 100,
            "mean_daily_%": r_oos.mean() * 100,
            "vol_%": r_oos.std() * 100,
            "cvar5_%": cvar(r_oos) * 100,
            "max_dd_%": dd.min() * 100,
            "ret_over_vol": r_oos.mean() / r_oos.std() if r_oos.std() else float("nan"),
        }
        print(f"\n{label} - OOS ({len(r_oos)} days):")
        for k, v in results[label].items():
            print(f"  {k:16s}: {v:+.4f}")

    print(f"\n(gate's average OOS exposure = {avg_exposure:.3f}x; worst-tail regime found in TEST 1 OOS = {worst_tail_regime})")
    print("If WEATHER-GATED does not clearly beat FLAT-SCALED on CVaR/max-DD, its apparent edge over FLAT "
          "is just 'lower average leverage in a losing half', not correctly-timed risk reduction.")
    print("If RISK-OPTIMAL (derisking the empirically worst-tail regime) beats WEATHER-GATED on CVaR/max-DD "
          "for similar or less give-up in return, weather.py's own STORMY/HEADWIND-down mapping is mis-targeted.")

    # ---------------- TEST 3: ablation ----------------
    print("\n" + "#" * 90)
    print("# TEST 3 - ablation: breadth20 add value over BTC-EMA alone? (OOS)")
    print("#" * 90)
    print_table("OOS by BTC-alone (2 buckets)", summarize(pooled_oos, "btc_only"))
    print_table("OOS by breadth-alone (3 buckets)", summarize(pooled_oos, "breadth_only"))
    print_table("OOS by full 2-factor regime (4 buckets)", summarize(pooled_oos, "regime"))

    def spread(df, col):
        s = df[col].dropna()
        return float(s.max() - s.min()) if len(s) else float("nan")

    btc_only_sum = summarize(pooled_oos, "btc_only")
    breadth_only_sum = summarize(pooled_oos, "breadth_only")
    full_sum = summarize(pooled_oos, "regime")
    print("\nSpread (worst-best) of OOS mean_mae5_% across buckets:")
    print(f"  BTC-alone   : {spread(btc_only_sum, 'mean_mae5_%'):.3f}")
    print(f"  breadth-alone: {spread(breadth_only_sum, 'mean_mae5_%'):.3f}")
    print(f"  full regime : {spread(full_sum, 'mean_mae5_%'):.3f}")
    print("\nSpread (worst-best) of OOS cvar5_fwd_ret5_%:")
    print(f"  BTC-alone   : {spread(btc_only_sum, 'cvar5_fwd_ret5_%'):.3f}")
    print(f"  breadth-alone: {spread(breadth_only_sum, 'cvar5_fwd_ret5_%'):.3f}")
    print(f"  full regime : {spread(full_sum, 'cvar5_fwd_ret5_%'):.3f}")

    # within-BTC-bucket breadth marginal contribution
    print("\nWithin BTC>50EMA days: STORMY (breadth-high) vs HEADWIND (breadth-mid), OOS:")
    sub = pooled_oos[pooled_oos["btc_only"] == "BTC_ABOVE"]
    print(summarize(sub, "regime")[["n", "mean_mae5_%", "cvar5_fwd_ret5_%"]])
    print("\nWithin BTC<50EMA days: WASHED_OUT (breadth-low) vs HEADWIND (breadth-mid), OOS:")
    sub = pooled_oos[pooled_oos["btc_only"] == "BTC_BELOW"]
    print(summarize(sub, "regime")[["n", "mean_mae5_%", "cvar5_fwd_ret5_%"]])

    # ---------------- TEST 4a: per-era breakdown ----------------
    print("\n" + "#" * 90)
    print("# TEST 4a - per-era robustness (is the ordering just the 2026-01/02 era?)")
    print("#" * 90)
    pooled_all = pooled.copy()
    pooled_all["era"] = pooled_all["t"].dt.to_period("2M" if False else "M")
    # 2-month eras for readable n
    era_bounds = pd.date_range(rf_valid["t"].min(), rf_valid["t"].max() + pd.Timedelta(days=60), freq="2MS", tz="UTC")
    pooled_all["era2m"] = pd.cut(pooled_all["t"], bins=era_bounds, right=False)
    for era, g in pooled_all.groupby("era2m", observed=True):
        if len(g) == 0:
            continue
        s = summarize(g, "regime")
        print(f"\nEra {era}  (n={len(g)}):")
        print(s[["n", "mean_mae5_%", "cvar5_fwd_ret5_%"]])

    print("\nRegime frequency by era2m (does STORMY/WASHED_OUT cluster in one era?):")
    rf_valid2 = rf_valid.copy()
    rf_valid2["era2m"] = pd.cut(rf_valid2["t"], bins=era_bounds, right=False)
    print(pd.crosstab(rf_valid2["era2m"], rf_valid2["regime"], normalize="index").round(2) * 100)

    # ---------------- TEST 4b: look-back contamination check ----------------
    print("\n" + "#" * 90)
    print("# TEST 4b - look-back contamination: regime vs plain trailing-vol tercile")
    print("#" * 90)
    trail = rf_valid[["t", "trail_vol10"]].dropna()
    tv = trail["trail_vol10"]
    terciles = pd.qcut(tv, 3, labels=["LOW_TRAILVOL", "MID_TRAILVOL", "HIGH_TRAILVOL"])
    trail_labeled = trail.assign(trailvol_bucket=terciles)
    pooled_tv = pooled.merge(trail_labeled[["t", "trailvol_bucket"]], on="t", how="left")
    pooled_tv_oos = pooled_tv[pooled_tv["t"].isin(oos_dates)]

    print_table("OOS by trailing-vol10 tercile (BTC-based, entry-time-safe)",
                summarize(pooled_tv_oos, "trailvol_bucket"))
    print_table("OOS by regime (repeated for side-by-side comparison)",
                summarize(pooled_oos, "regime"))

    tv_sum = summarize(pooled_tv_oos, "trailvol_bucket")
    print("\nSpread (worst-best) OOS mean_fwd_dailyvol_% :")
    print(f"  trailing-vol tercile buckets: {spread(tv_sum, 'mean_fwd_dailyvol_%'):.4f}")
    print(f"  regime buckets              : {spread(full_sum, 'mean_fwd_dailyvol_%'):.4f}")
    print("\nIf these two spreads are comparable, regime's forward-vol signal is materially "
          "just a restatement of 'it has been volatile lately' (BTC trailing vol), not new info.")

    # cross-tab: does regime add anything conditional on trailing-vol tercile?
    print("\nRegime distribution conditional on trailing-vol tercile (OOS, look-back overlap check):")
    cross = rf_valid.merge(trail_labeled[["t", "trailvol_bucket"]], on="t", how="left")
    cross_oos = cross[cross["t"].isin(oos_dates)]
    print(pd.crosstab(cross_oos["trailvol_bucket"], cross_oos["regime"], normalize="index").round(2) * 100)

    print("\n" + "=" * 90)
    print("END OF REPORT")
    print("=" * 90)


if __name__ == "__main__":
    pd.set_option("future.no_silent_downcasting", True)
    main()
