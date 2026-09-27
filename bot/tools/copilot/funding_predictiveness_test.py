#!/usr/bin/env python
"""
Funding Predictiveness Test - funding_predictiveness_test.py
=============================================================================
STANDALONE, READ-ONLY analysis script. Tests whether the co-pilot's FUNDING
line (tools/copilot/copilot.py, `_funding_direction_note`, labeled
"FUNDING (carry cost, not a signal)") is an honest label -- i.e. whether
funding rate (its level, extremes, or crowding) carries any FORWARD,
entry-time-safe, net-of-fees, OOS predictive information about price, or
whether it is genuinely just a carry cost with zero exploitable edge.

DOES NOT import copilot.py or weather.py (both are being edited by another
agent per the task constraint). The one number borrowed from copilot.py is
READ, not imported: FUNDING_LOOKBACK_D=30 and the funding_extreme threshold
|z| > 2.5 (copilot.py lines ~259, ~749) are reproduced here as constants so
hypothesis 1's "EXTREME funding" bucket matches exactly what a trader reading
the live brief would see flagged.

WHY THIS TEST NOW: an earlier note in copilot.py (THEME A, 2026-07-31) says
a funding-fade signal "was tested and came back null - see EDGE INSTRUMENTS
2026-07-27" -- but that finding predates this project's own funding/OI
history being long enough to test properly (data/longtail/funding/*.csv and
the funding candle-cache were thin or absent then). This script is the
actual, current, best-data attempt at that test. A null result here would
CONFIRM the label is honest with real evidence, not just recycle the old
under-powered conclusion; a real result would be news.

DATA INVENTORY (established by direct inspection before writing any test
code -- see report section 0 printed at runtime for the live version of
this):
  A. "Main" dataset -- BTC, ETH, SOL, XRP (deepest history):
     - Funding: tools/research/candle_cache/HL_FUNDING_{SYM}.json
       Hyperliquid hourly funding rate, fetched 2026-07-03. BTC/ETH/SOL:
       26983 rows, 2023-05-12 -> 2026-07-03 (~3.1yr). XRP: 26662 rows,
       2023-06-18 -> 2026-07-03. Timestamps are irregular (real funding-
       change events, not a clean grid) -> paired onto price via a causal
       backward as-of join (never looks forward).
     - Price: data/cache/multiyear_geom/{SYM}_1h.json (source:
       binance-vision spot/futures, NOT Hyperliquid). 21911 rows, exactly
       hourly (diff==3600000ms for all but the first row, 0 dupes),
       2024-01-01 00:00 -> 2026-07-01 22:00 UTC. This is the effective
       overlap window used (funding history starts earlier but price
       doesn't). LIMITATION: price is Binance, funding is HL -- for these
       four majors, cross-venue price co-movement is extremely tight, but
       this is a proxy, not the literal HL mark price the funding accrued
       against. Documented, not hidden.
  B. "Longtail" dataset -- 25 mid/small-cap alts (broader cross-section,
     shorter window, but funding AND price are the SAME exchange/collector
     and land on an EXACT shared hourly grid -- the cleaner pairing):
     - Funding: data/longtail/funding/{SYM}.csv (fundingRate, premium),
       hourly, ~4800-4801 rows/symbol, 2026-01-12 -> 2026-07-31 (~6.7mo).
     - Price: data/longtail/ohlc/{SYM}_1h.csv, same range, same cadence.
     - Verified: flooring both timestamp columns to the hour gives a clean
       1:1 join for every symbol (0 irregular grids, 0 duplicate hours).
     - Symbols: AAVE ADA APT ARB AVAX BCH CRV FARTCOIN LDO LINK LTC ONDO
       PAXG PENGU PUMP SUI TAO TRX UNI WLD XPL ZEC kBONK kPEPE kSHIB
       (FARTCOIN/XPL/PUMP shorter -- newer listings; handled by min-history
       gating, not padding/faking).
  Not used: data/funding_oi_history.jsonl (live snapshot log, only starts
  2026-06-06, ~2mo, snapshot cadence ~5min but many symbols have <10 rows --
  too thin, superseded by the two sources above for this test).

METHOD (entry-time-safe throughout -- every feature at row t uses ONLY
funding/price data with timestamp <= t; forward returns are labels, computed
AFTER feature construction, never fed back into any feature):
  1. funding_pctile(t)  = percentile rank of funding_rate(t) within the
     TRAILING lookback window ENDING at t (window excludes nothing "future");
     rank is computed against the window's OWN history strictly before t
     (matches copilot.py's `hist = fdf["fundingRate"].iloc[:-1]`).
     Lookback = 720h (30d, = copilot's FUNDING_LOOKBACK_D) for the main
     dataset, 336h (14d, shorter because total history is shorter) for
     longtail.
  2. funding_z(t) = (funding_rate(t) - mean(hist)) / std(hist), same window.
     funding_extreme(t) = |funding_z(t)| > 2.5, IDENTICAL definition/
     threshold to copilot.py's `r.funding_extreme`.
  3. trailing_vol24(t) = stdev of trailing 24 hourly log returns (causal).
  4. range_pos_pct(t) = position of close(t) in the trailing 20d [low,high]
     range (0=range low,100=range high) -- reused from
     mover_followthrough_test.py's definition, used only for hypothesis 2
     ("crowded AND parabolic").
  5. fwd_ret_24h(t), fwd_ret_72h(t) = simple forward return of close, t ->
     t+24h / t+72h. These are LABELS ONLY, never inputs to any feature above.
  6. Fee: FEE_ROUND_TRIP = 0.0009 (9bps), applied ONCE per directional bet
     regardless of horizon, same convention as mover_followthrough_test.py
     and lev_band_test.py in this same folder.

TESTS RUN (see main() for the printed report):
  H1  Crowding reversal / monotonicity: decile the funding percentile,
      report mean forward return per decile (both horizons), Spearman rho
      of pctile vs forward return with a BLOCK-PERMUTATION null (shuffles
      contiguous blocks to preserve the return series' own autocorrelation,
      so the p-value isn't fooled by funding's persistence). Then the
      actionable version: EXTREME-tail (|z|>2.5) contrarian strategy
      (short when funding extremely positive, long when extremely negative)
      -- mean net-of-fee return, block-bootstrap CI, t-stat, n.
  H2  Interaction: extreme-positive funding AND range_pos_pct>=90 (crowded
      long at a local high, i.e. "parabolic + crowded") vs extreme-positive
      funding NOT at a local high -- does the combo predict a bigger forward
      drawdown than funding alone? Only tested if H1's extreme-tail sample
      is large enough to split further.
  H3  Bottom-line verdict assembled from H1/H2/H4 -- printed at the end.
  H4  Self-refutation: (a) vol-regime control -- repeat the H1 decile spread
      test WITHIN each trailing-vol tercile, to check whether any apparent
      funding effect survives once volatility regime is held fixed (funding
      is regime-linked; if the "edge" vanishes within-vol-bucket, it was a
      vol proxy, not a funding effect). (b) era split -- main dataset by
      calendar year (2024/2025/2026-YTD), longtail by half (H1 2026-01..04
      vs H2 2026-04..07) -- same sign/magnitude required in >=2/3 (main) or
      2/2 (longtail) eras to call anything "stable", else flagged as a
      single-era artifact. (c) autocorrelation is reported explicitly
      (effective-N caveat) on every hourly-overlapping stat; a daily-
      resampled (non-overlapping-ish) cut of the SAME tests is also run as
      a cross-check.

This script performs NO live calls, imports nothing from copilot.py/
weather.py, writes no files, sends no Discord/Telegram messages. It only
reads the CSV/JSON paths listed above and prints a report to stdout.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]  # .../bot
CANDLE_CACHE = ROOT / "tools" / "research" / "candle_cache"
MULTIYEAR = ROOT / "data" / "cache" / "multiyear_geom"
LONGTAIL_FUNDING = ROOT / "data" / "longtail" / "funding"
LONGTAIL_OHLC = ROOT / "data" / "longtail" / "ohlc"

MAIN_SYMBOLS = ["BTC", "ETH", "SOL", "XRP"]

FEE_ROUND_TRIP = 0.0009          # 9bps, applied once per directional bet
EXTREME_Z = 2.5                  # matches copilot.py funding_extreme threshold
LOOKBACK_H_MAIN = 720            # 30d, matches copilot.py FUNDING_LOOKBACK_D
LOOKBACK_H_LONGTAIL = 336        # 14d (shorter total history available)
RANGE_LOOKBACK_H = 480           # 20d, for H2's "local high" definition
MIN_HIST = 20                    # min trailing obs before trusting pctile/z
HORIZONS = {"24h": 24, "72h": 72}

N_BOOTSTRAP = 1000
N_PERM = 500
RNG = np.random.default_rng(20260731)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_main_symbol(sym: str) -> pd.DataFrame:
    """BTC/ETH/SOL/XRP: HL hourly funding (irregular ts) as-of-joined onto
    binance-vision hourly price (uniform grid). Causal (backward) join only.
    """
    fpath = CANDLE_CACHE / f"HL_FUNDING_{sym}.json"
    ppath = MULTIYEAR / f"{sym}_1h.json"
    if not fpath.exists() or not ppath.exists():
        return pd.DataFrame()

    fd = json.load(open(fpath))
    frows = fd["rows"]  # [[ts_ms, rate], ...]
    fund_ts = np.array([r[0] for r in frows], dtype=np.int64)
    fund_rate = np.array([r[1] for r in frows], dtype=float)
    order = np.argsort(fund_ts)
    fund_df = pd.DataFrame(
        {"dt": pd.to_datetime(fund_ts[order], unit="ms", utc=True),
         "funding_rate": fund_rate[order]}
    ).drop_duplicates("dt").sort_values("dt")

    pd_raw = json.load(open(ppath))
    candles = pd_raw["candles"]
    price_df = pd.DataFrame(candles).rename(columns={"t": "t_ms", "c": "close"})
    price_df = price_df.sort_values("t_ms").drop_duplicates("t_ms").reset_index(drop=True)
    price_df["dt"] = pd.to_datetime(price_df["t_ms"], unit="ms", utc=True)

    merged = pd.merge_asof(
        price_df[["dt", "close"]], fund_df, on="dt", direction="backward"
    )
    merged["symbol"] = sym
    merged["dataset"] = "main"
    merged["price_source"] = pd_raw.get("source", "unknown")
    return merged


def load_longtail_symbol(sym: str) -> pd.DataFrame:
    """25 longtail alts: funding + OHLC collected together, exact hourly
    grid on both sides (verified). Join by floored hour (exact, not as-of)."""
    fpath = LONGTAIL_FUNDING / f"{sym}.csv"
    ppath = LONGTAIL_OHLC / f"{sym}_1h.csv"
    if not fpath.exists() or not ppath.exists():
        return pd.DataFrame()

    f = pd.read_csv(fpath)
    o = pd.read_csv(ppath)
    f["hour"] = f["time_ms"] // 3_600_000
    o["hour"] = o["open_time_ms"] // 3_600_000
    f = f.drop_duplicates("hour")
    o = o.drop_duplicates("hour")
    m = pd.merge(o[["hour", "open_time_ms", "c"]], f[["hour", "fundingRate"]], on="hour", how="inner")
    m = m.sort_values("hour").reset_index(drop=True)
    m["dt"] = pd.to_datetime(m["open_time_ms"], unit="ms", utc=True)
    m = m.rename(columns={"c": "close", "fundingRate": "funding_rate"})
    m["symbol"] = sym
    m["dataset"] = "longtail"
    m["price_source"] = "hl_longtail_collector"
    return m[["dt", "close", "funding_rate", "symbol", "dataset", "price_source"]]


LONGTAIL_SYMBOLS = sorted(p.stem for p in LONGTAIL_FUNDING.glob("*.csv"))


# ---------------------------------------------------------------------------
# Causal feature engineering
# ---------------------------------------------------------------------------

def add_features(df: pd.DataFrame, lookback_h: int) -> pd.DataFrame:
    df = df.sort_values("dt").reset_index(drop=True)
    fr = df["funding_rate"].to_numpy(dtype=float)
    n = len(fr)

    # --- funding_z: fully vectorized, causal (hist = strictly-prior window) ---
    s = pd.Series(fr)
    hist_mean = s.shift(1).rolling(lookback_h - 1, min_periods=MIN_HIST).mean()
    hist_std = s.shift(1).rolling(lookback_h - 1, min_periods=MIN_HIST).std(ddof=0)
    df["funding_z"] = (s - hist_mean) / hist_std.replace(0, np.nan)
    df["funding_extreme"] = df["funding_z"].abs() > EXTREME_Z

    # --- funding_pctile: rank of current value within trailing window
    # (rolling().apply is O(window) per row but simplest-to-verify-correct) ---
    def _pct_of_last(a: np.ndarray) -> float:
        if len(a) < MIN_HIST + 1:
            return np.nan
        hist, cur = a[:-1], a[-1]
        return float((hist <= cur).mean() * 100.0)

    df["funding_pctile"] = s.rolling(lookback_h, min_periods=MIN_HIST + 1).apply(
        _pct_of_last, raw=True
    ).to_numpy()

    # --- trailing realized vol (24h, causal) ---
    logret = np.log(df["close"]).diff()
    df["trailing_vol24"] = logret.rolling(24, min_periods=12).std()

    # --- range position over trailing RANGE_LOOKBACK_H (causal, inclusive of t) ---
    roll_max = df["close"].rolling(RANGE_LOOKBACK_H, min_periods=RANGE_LOOKBACK_H // 2).max()
    roll_min = df["close"].rolling(RANGE_LOOKBACK_H, min_periods=RANGE_LOOKBACK_H // 2).min()
    rng = (roll_max - roll_min).replace(0, np.nan)
    df["range_pos_pct"] = (df["close"] - roll_min) / rng * 100.0

    # --- forward return LABELS (never fed back into features above) ---
    for name, h in HORIZONS.items():
        df[f"fwd_ret_{name}"] = df["close"].shift(-h) / df["close"] - 1.0

    return df


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def block_bootstrap_mean_ci(x: np.ndarray, block: int, n_boot: int = N_BOOTSTRAP):
    """Block-bootstrap CI + two-sided p-value (H0: mean=0) for a series that
    may be autocorrelated (overlapping forward-return windows)."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < max(30, block * 3):
        return np.nan, (np.nan, np.nan), np.nan, n
    n_blocks = int(np.ceil(n / block))
    starts = np.arange(0, n - block + 1)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = RNG.integers(0, len(starts), size=n_blocks)
        sample = np.concatenate([x[starts[i]: starts[i] + block] for i in idx])[:n]
        boots[b] = sample.mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    obs = x.mean()
    # two-sided empirical p-value against 0, using the bootstrap distribution
    # recentered at 0 (standard percentile-bootstrap test)
    centered = boots - boots.mean()
    p = float((np.abs(centered) >= abs(obs)).mean())
    return obs, (lo, hi), p, n


def spearman_block_perm_test(x: np.ndarray, y: np.ndarray, block: int, n_perm: int = N_PERM):
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < max(50, block * 3):
        return np.nan, np.nan, n
    from scipy.stats import spearmanr
    rho_obs, _ = spearmanr(x, y)
    n_blocks = int(np.ceil(n / block))
    starts = list(range(0, n - block + 1, block)) or [0]
    null = np.empty(n_perm)
    for i in range(n_perm):
        perm_starts = RNG.permutation(starts)
        y_perm = np.concatenate([y[s: s + block] for s in perm_starts])[:n]
        x_trim = x[: len(y_perm)]
        r, _ = spearmanr(x_trim, y_perm)
        null[i] = r
    p = float((np.abs(null) >= abs(rho_obs)).mean())
    return rho_obs, p, n


def welch_t(a: np.ndarray, b: np.ndarray):
    from scipy.stats import ttest_ind
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    t, p = ttest_ind(a, b, equal_var=False)
    return float(t), float(p)


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def decile_table(panel: pd.DataFrame, horizon: str, label: str):
    col = f"fwd_ret_{horizon}"
    d = panel.dropna(subset=["funding_pctile", col]).copy()
    if len(d) < 200:
        print(f"    [{label}] n={len(d)} too small for decile table, skipping")
        return
    # funding_pctile is often tied (many symbols pin at HL's funding-rate cap
    # for long stretches) -> qcut on the raw value collapses bins near the
    # cap. Rank-break ties first (arbitrary but stable ordering, time-index-
    # based) so all 10 bins are populated and comparable in size.
    pinned = (d["funding_pctile"] >= 99.5).mean() * 100 + (d["funding_pctile"] <= 0.5).mean() * 100
    d["decile"] = pd.qcut(d["funding_pctile"].rank(method="first"), 10, labels=False)
    g = d.groupby("decile")[col].agg(["mean", "median", "count"])
    print(f"    [{label}] forward {horizon} return by funding-percentile decile (0=most-negative funding, 9=most-positive funding; "
          f"{pinned:.1f}% of rows pinned at/near the trailing-window extreme -- tie-broken by rank so bins stay even):")
    for dec, row in g.iterrows():
        bar = "#" * int(max(0, min(40, (row['mean'] * 4000))))
        print(f"      decile {int(dec)}: mean={row['mean']*100:+.3f}%  median={row['median']*100:+.3f}%  n={int(row['count']):>6}  {bar}")
    h = HORIZONS[horizon]
    block = max(h * 3, 72)
    rho, p, n_eff = spearman_block_perm_test(
        d["funding_pctile"].to_numpy(), d[col].to_numpy(), block=block
    )
    print(f"      Spearman(funding_pctile, fwd_{horizon}) = {rho:+.4f}  block-permutation p={p:.3f}  (n={n_eff}, block={block}h, preserves return autocorrelation under the null)")


def extreme_contrarian(panel: pd.DataFrame, horizon: str, label: str):
    col = f"fwd_ret_{horizon}"
    d = panel.dropna(subset=["funding_z", col]).copy()
    pos = d[d["funding_z"] > EXTREME_Z]
    neg = d[d["funding_z"] < -EXTREME_Z]
    if len(pos) + len(neg) < 30:
        print(f"    [{label}] extreme-funding sample too small (pos={len(pos)}, neg={len(neg)}), skipping")
        return None
    # contrarian: short the crowded-long extreme, long the crowded-short extreme
    net_pos = -pos[col].to_numpy() - FEE_ROUND_TRIP
    net_neg = neg[col].to_numpy() - FEE_ROUND_TRIP
    net_all = np.concatenate([net_pos, net_neg])
    h = HORIZONS[horizon]
    block = max(h, 24)
    obs, (lo, hi), p, n_eff = block_bootstrap_mean_ci(net_all, block=block)
    print(f"    [{label}] EXTREME-funding contrarian strategy, fwd {horizon}, net of {FEE_ROUND_TRIP*1e4:.0f}bps fee:")
    print(f"      n_extreme_pos(crowded-long,SHORT)={len(pos)}  raw_mean_ret={pos[col].mean()*100:+.3f}%")
    print(f"      n_extreme_neg(crowded-short,LONG)={len(neg)}  raw_mean_ret={neg[col].mean()*100:+.3f}%")
    print(f"      pooled net mean={obs*100:+.4f}%  95% block-bootstrap CI=[{lo*100:+.4f}%, {hi*100:+.4f}%]  p={p:.3f}  n={n_eff} (block={block}h)")
    return dict(label=label, horizon=horizon, n=n_eff, net_mean=obs, ci=(lo, hi), p=p)


def vol_regime_control(panel: pd.DataFrame, horizon: str, label: str):
    col = f"fwd_ret_{horizon}"
    d = panel.dropna(subset=["funding_pctile", "trailing_vol24", col]).copy()
    if len(d) < 600:
        print(f"    [{label}] n={len(d)} too small for vol-tercile control, skipping")
        return
    d["vol_tercile"] = pd.qcut(d["trailing_vol24"], 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
    print(f"    [{label}] within-vol-tercile funding top-decile-minus-bottom-decile spread ({horizon}):")
    for vt, sub in d.groupby("vol_tercile", observed=True):
        if len(sub) < 200:
            print(f"      {vt}: n={len(sub)} too small, skip")
            continue
        sub = sub.copy()
        sub["decile"] = pd.qcut(sub["funding_pctile"].rank(method="first"), 10, labels=False)
        top = sub[sub["decile"] == sub["decile"].max()][col].to_numpy()
        bot = sub[sub["decile"] == sub["decile"].min()][col].to_numpy()
        spread = np.nanmean(top) - np.nanmean(bot)
        t, p = welch_t(top, bot)
        print(f"      {vt}: n={len(sub)}  top_decile_mean={np.nanmean(top)*100:+.3f}%  bottom_decile_mean={np.nanmean(bot)*100:+.3f}%  spread={spread*100:+.3f}%  t={t:.2f} p={p:.3f}")


def era_stability(panel: pd.DataFrame, horizon: str, label: str, era_col: str):
    for era, sub in panel.groupby(era_col, observed=True):
        r = extreme_contrarian(sub, horizon, f"{label}/{era}")
        if r is None:
            continue


def interaction_local_high(panel: pd.DataFrame, horizon: str, label: str):
    col = f"fwd_ret_{horizon}"
    d = panel.dropna(subset=["funding_z", "range_pos_pct", col]).copy()
    crowded = d[d["funding_z"] > EXTREME_Z]
    if len(crowded) < 60:
        print(f"    [{label}] crowded-long sample too small (n={len(crowded)}) for H2 interaction test, skipping")
        return
    at_high = crowded[crowded["range_pos_pct"] >= 90]
    not_high = crowded[crowded["range_pos_pct"] < 90]
    if len(at_high) < 20 or len(not_high) < 20:
        print(f"    [{label}] H2 split too thin (at_high={len(at_high)}, not_high={len(not_high)}), skipping")
        return
    net_high = -at_high[col].to_numpy() - FEE_ROUND_TRIP
    net_not = -not_high[col].to_numpy() - FEE_ROUND_TRIP
    t, p = welch_t(net_high, net_not)
    print(f"    [{label}] H2: crowded-long (funding_z>{EXTREME_Z}) AT local high (range_pos>=90) vs NOT:")
    print(f"      at_high:  n={len(at_high)}  net_mean(short strat)={np.nanmean(net_high)*100:+.3f}%")
    print(f"      not_high: n={len(not_high)}  net_mean(short strat)={np.nanmean(net_not)*100:+.3f}%")
    print(f"      diff t={t:.2f} p={p:.3f}  (positive diff = parabolic+crowded is a BETTER short than crowded alone)")


def daily_resample_crosscheck(panel: pd.DataFrame, horizon: str, label: str):
    """Non-overlapping-ish cross-check: keep only 1 row per symbol per
    HORIZON-length block, killing most of the overlap-induced autocorrelation
    inflation, to see if the hourly-overlapping stat survives on an
    (approximately) independent sample."""
    h = HORIZONS[horizon]
    col = f"fwd_ret_{horizon}"
    d = panel.dropna(subset=["funding_z", col]).copy()
    d["blk"] = (np.arange(len(d)) // h)
    d = d.groupby(["symbol", "blk"], observed=True).first().reset_index(drop=True)
    pos = d[d["funding_z"] > EXTREME_Z][col].to_numpy()
    neg = d[d["funding_z"] < -EXTREME_Z][col].to_numpy()
    net = np.concatenate([-pos - FEE_ROUND_TRIP, neg - FEE_ROUND_TRIP])
    net = net[~np.isnan(net)]
    if len(net) < 20:
        print(f"    [{label}] daily-resample cross-check: n={len(net)} too small")
        return
    from scipy.stats import ttest_1samp
    t, p = ttest_1samp(net, 0.0)
    print(f"    [{label}] non-overlapping cross-check (1 obs / {h}h block): n={len(net)}  net_mean={net.mean()*100:+.3f}%  t={t:.2f} p={p:.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 88)
    print("FUNDING PREDICTIVENESS TEST -- is copilot.py's FUNDING line honestly")
    print('labeled "carry cost, not a signal", or is there a real forward edge?')
    print("=" * 88)

    print("\n--- SECTION 0: data actually loaded (verify before trusting anything below) ---")
    main_frames = []
    for sym in MAIN_SYMBOLS:
        df = load_main_symbol(sym)
        if df.empty:
            print(f"  MAIN {sym}: NOT FOUND, skipped")
            continue
        df = add_features(df, LOOKBACK_H_MAIN)
        df["year"] = df["dt"].dt.year
        main_frames.append(df)
        print(f"  MAIN {sym}: n={len(df)}  {df['dt'].min()} -> {df['dt'].max()}  "
              f"price_source={df['price_source'].iloc[0]}  funding_rate_source=HL_FUNDING_{sym}.json")

    lt_frames = []
    for sym in LONGTAIL_SYMBOLS:
        df = load_longtail_symbol(sym)
        if df.empty or len(df) < 500:
            print(f"  LONGTAIL {sym}: n={len(df)} (<500), skipped (insufficient history for a 336h lookback + 72h forward horizon)")
            continue
        df = add_features(df, LOOKBACK_H_LONGTAIL)
        df["half"] = np.where(df["dt"] < pd.Timestamp("2026-04-15", tz="UTC"), "H1_JanApr", "H2_AprJul")
        lt_frames.append(df)
    print(f"  LONGTAIL: {len(lt_frames)}/{len(LONGTAIL_SYMBOLS)} symbols usable, "
          f"range {min(f['dt'].min() for f in lt_frames)} -> {max(f['dt'].max() for f in lt_frames)}")

    main_panel = pd.concat(main_frames, ignore_index=True) if main_frames else pd.DataFrame()
    lt_panel = pd.concat(lt_frames, ignore_index=True) if lt_frames else pd.DataFrame()
    print(f"\n  MAIN panel total rows: {len(main_panel)}  |  LONGTAIL panel total rows: {len(lt_panel)}")
    print(f"  Fee assumption: {FEE_ROUND_TRIP*1e4:.0f}bps round-trip, applied once per directional bet, regardless of horizon.")
    print(f"  EXTREME funding threshold: |z| > {EXTREME_Z} (identical to copilot.py's funding_extreme flag).")
    print(f"  CAVEAT: hourly-overlapping forward windows are autocorrelated -> raw n overstates independent")
    print(f"  information content. Block-bootstrap/permutation tests below use block sizes >= the forward")
    print(f"  horizon to partially account for this; a non-overlapping cross-check is also run per dataset.")

    for horizon in HORIZONS:
        print(f"\n{'='*88}\nHORIZON = {horizon} forward\n{'='*88}")

        if not main_panel.empty:
            print(f"\n  -- H1 MAIN (BTC/ETH/SOL/XRP, {main_panel['dt'].min().date()}..{main_panel['dt'].max().date()}) --")
            decile_table(main_panel, horizon, "MAIN pooled")
            extreme_contrarian(main_panel, horizon, "MAIN pooled")
            daily_resample_crosscheck(main_panel, horizon, "MAIN pooled")
            print(f"\n  -- H4a vol-regime control (MAIN) --")
            vol_regime_control(main_panel, horizon, "MAIN pooled")
            print(f"\n  -- H4b era stability (MAIN, by calendar year) --")
            era_stability(main_panel, horizon, "MAIN", "year")
            print(f"\n  -- H2 interaction: crowded + local-high (MAIN) --")
            interaction_local_high(main_panel, horizon, "MAIN pooled")

        if not lt_panel.empty:
            print(f"\n  -- H1 LONGTAIL (25 alts, {lt_panel['dt'].min().date()}..{lt_panel['dt'].max().date()}) --")
            decile_table(lt_panel, horizon, "LONGTAIL pooled")
            extreme_contrarian(lt_panel, horizon, "LONGTAIL pooled")
            daily_resample_crosscheck(lt_panel, horizon, "LONGTAIL pooled")
            print(f"\n  -- H4a vol-regime control (LONGTAIL) --")
            vol_regime_control(lt_panel, horizon, "LONGTAIL pooled")
            print(f"\n  -- H4b era stability (LONGTAIL, by half) --")
            era_stability(lt_panel, horizon, "LONGTAIL", "half")
            print(f"\n  -- H2 interaction: crowded + local-high (LONGTAIL) --")
            interaction_local_high(lt_panel, horizon, "LONGTAIL pooled")

        if not main_panel.empty and not lt_panel.empty:
            pooled = pd.concat([main_panel, lt_panel], ignore_index=True)
            print(f"\n  -- H1 POOLED (main + longtail, all {pooled['symbol'].nunique()} symbols) --")
            extreme_contrarian(pooled, horizon, "ALL pooled")

    print(f"\n{'='*88}\nVERDICT (see full numbers above -- this is a summary, not a substitute)\n{'='*88}")
    print("""
Read the per-decile tables and the EXTREME-funding contrarian p-values above.
The label "FUNDING (carry cost, not a signal)" should be KEPT as-is unless
ALL of the following hold simultaneously:
  1. The decile table shows a genuinely monotonic (not just noisy top/bottom)
     relationship, with a block-permutation p < 0.05 on BOTH datasets
     (or at least MAIN, since it has the longest/deepest history).
  2. The EXTREME-funding contrarian strategy's net-of-fee mean return is
     positive with a bootstrap CI that excludes 0, AND the non-overlapping
     daily cross-check points the same direction (not just the
     overlap-inflated hourly stat).
  3. The vol-regime control shows the spread survives WITHIN vol terciles
     (if it only appears in the high-vol tercile and vanishes elsewhere,
     it's a vol-regime proxy, not a funding effect).
  4. The era split shows the SAME SIGN in most/all eras (a flip in sign or
     an effect that only exists in one year/half is a single-era artifact,
     not a tradeable edge).
If even one of these fails, the honest call is: funding is real-time
crowding CONTEXT (useful to a human deciding hold length / squeeze risk
qualitatively) but it is NOT, on this evidence, an exploitable net-of-fee
forward-return signal -- the current label is correct and should not change.
""")


if __name__ == "__main__":
    main()
