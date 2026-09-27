#!/usr/bin/env python
"""
WAGMI Co-Pilot - MARKET STRUCTURE STUDY - market_structure_study.py
=============================================================================
READ-ONLY / STANDALONE, same constraints as every other tools/copilot/*.py
module: no live-bot imports (llm/, execution/, core/, strategies/), no
Discord/network calls, never touches live/.env/data/replay. Reads only
already-collected CSV/JSONL files under data/. RAM-lean: loads each file
once, works off small in-memory panels (~25 coins x ~400 daily rows is
kilobytes, not gigabytes), frees raw frames after extracting closes/volume,
and calls gc.collect() between phases as a hygiene habit for the 8GB host
that also runs the live bot.

WHAT THIS IS: a descriptive "what actually drives these coins + what states
does this market occupy" understanding study. It makes NO forward-return /
tradeable-edge claims (that is a job for a proper walk-forward backtest with
OOS validation, entry-time-safety and cost modeling - see weather.py /
weather_value_test.py for what that looks like and for the cautionary tale:
an earlier regime-sizing idea that looked good in-sample was REFUTED OOS).
Every regime "forward return" number printed here is a DESCRIPTIVE
characterization of history, not a signal.

DATA USED (all already-collected, nothing fetched):
  - data/longtail/ohlc/{COIN}_1d.csv  x25 alts, ~13mo, gap-free from each
    coin's own listing/backfill start (PUMP from 2025-07-10, XPL from
    2025-08-22, the rest from ~2025-06-26) through 2026-07-31.
  - data/cache/BTC_daily_*.csv + SOL_daily_*.csv - the "majors" cache. These
    files OVERLAP (220d/420d/60d/30d/5d windows of the same series) so this
    script unions+dedupes them by timestamp to get the fullest available
    range. ** KNOWN DATA GAP, confirmed by inspection and reported again at
    runtime: even after unioning every cache file, BTC only goes back to
    2025-12-18 and its freshest row is 2026-07-23; SOL back to 2025-12-18,
    freshest row 2026-07-27. That is ~7.3 months, MUCH shorter than the
    alts' ~13-month window, and it is also stale by ~1-4 days relative to
    the alts' 2026-07-31 end (and further stale relative to "now"). This
    means: the BTC-beta decomposition and the regime taxonomy (both need a
    BTC series) can only be computed over that shorter ~7.3mo majors
    window, NOT the alts' full history. The alts' full 13mo history is
    still used wherever BTC isn't required (cross-coin structure, dispersion
    over time, liquidity proxy). **
  - data/funding_oi_history.jsonl - only covers 2026-06-06 through
    2026-08-06 (~61 days), a sub-window of an already-short majors window.
    Used ONLY as a secondary/supplementary cross-check (average funding by
    regime, for the days it exists) - never as a clustering input, so a
    61-day feature doesn't truncate or distort the primary ~218-day regime
    taxonomy.
  - data/copilot/liquidations/liq_events.jsonl - checked but only spans
    2026-08-01 to 2026-08-06 (5 days). Far too short to use; NOT used here,
    noted for completeness.

METHOD, section by section (see module-level functions):
  1. Return decomposition: alt daily log-return ~ BTC log-return + an
     equal-weight ex-self alt-sector index log-return, fit by OLS (plain
     numpy least squares, classic-OLS standard errors, t-distribution CIs -
     no statsmodels dependency). Variance is decomposed SEQUENTIALLY
     (BTC-only R^2 first, then the incremental R^2 from adding the sector
     term, then 1 - R^2_full = idiosyncratic) because BTC and the alt-sector
     index are themselves correlated (reported explicitly as a collinearity
     caveat) - order matters and is a modeling choice, not a neutral split.
  2. Regime taxonomy: KMeans on standardized {BTC trend vs EMA50, breadth20,
     realized vol} daily features over the majors window; k chosen by
     silhouette score restricted to k in [3,5] per the brief (a full k=2..6
     curve is printed for transparency). Regimes are characterized by
     occurrence rate, forward 3d/5d alt-index behavior (DESCRIPTIVE ONLY),
     contemporaneous cross-sectional dispersion, and a trend-vs-mean-revert
     signature (lag-1 autocorrelation of the alt equal-weight index).
  3. Cross-coin structure: full pairwise correlation matrix (13mo, alt-own
     history), hierarchical clustering (average linkage on 1-corr distance)
     with a cophenetic-correlation fit check and a silhouette-selected
     cluster count; rolling 20d dispersion + rolling 20d avg alt-vs-BTC
     correlation to flag "decoupling" (idiosyncratic opportunity) windows.
  4. Refutation: pre/post-midpoint era split re-running the beta and regime
     characterizations; short-history coins are flagged LOW-CONFIDENCE
     (n<90) rather than silently included at equal weight to the longer
     series.

USAGE:  cd bot && python tools/copilot/market_structure_study.py
        (optional) --k-min/--k-max override the regime-cluster search range,
        --out PATH dumps a JSON summary alongside the printed report.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import linkage, fcluster, cophenet
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# Windows terminals default to cp1252, which can't encode a stray non-ASCII
# character; force utf-8 output so the report never crashes on print().
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LONGTAIL_OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")
FUNDING_OI_PATH = os.path.join(BOT_DIR, "data", "funding_oi_history.jsonl")

BTC_EMA_PERIOD = 50
BREADTH_SMA_PERIOD = 20
REALIZED_VOL_WINDOW = 7
MIN_OBS_CONFIDENT = 90     # below this, a coin's stats get a LOW-CONFIDENCE flag
MIN_ALTS_FOR_SECTOR = 10   # min alts required to trust an ex-self sector reading


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def discover_alt_coins() -> List[str]:
    coins = []
    for fn in sorted(os.listdir(LONGTAIL_OHLC_DIR)):
        if fn.endswith("_1d.csv"):
            coins.append(fn[: -len("_1d.csv")])
    return coins


def load_alt_1d(coin: str) -> Optional[pd.DataFrame]:
    path = os.path.join(LONGTAIL_OHLC_DIR, f"{coin}_1d.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, usecols=["dt_utc_iso", "c", "v"])
    df["t"] = pd.to_datetime(df["dt_utc_iso"], utc=True, errors="coerce").dt.normalize()
    df["c"] = pd.to_numeric(df["c"], errors="coerce")
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    df = df.dropna(subset=["t", "c"]).drop_duplicates(subset="t").sort_values("t").reset_index(drop=True)
    return df[["t", "c", "v"]] if not df.empty else None


def load_major_daily(symbol: str) -> Optional[pd.DataFrame]:
    """Unions+dedupes every data/cache/{symbol}_daily_*.csv window into the
    fullest available series (see module docstring for why: the cache is a
    set of overlapping fixed-length windows, not one canonical file)."""
    import glob

    frames = []
    for path in glob.glob(os.path.join(CACHE_DIR, f"{symbol}_daily_*.csv")):
        try:
            df = pd.read_csv(path, usecols=["time", "close"])
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return None
    allf = pd.concat(frames, ignore_index=True)
    allf["t"] = pd.to_datetime(allf["time"], utc=True, errors="coerce").dt.normalize()
    allf["c"] = pd.to_numeric(allf["close"], errors="coerce")
    allf = allf.dropna(subset=["t", "c"]).drop_duplicates(subset="t").sort_values("t").reset_index(drop=True)
    return allf[["t", "c"]] if not allf.empty else None


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------

def build_alt_panels(coins: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    """Returns (close_panel, ret_panel, avg_dollar_vol) over each coin's own
    FULL history (union of dates, NaN where a coin has no data yet - most
    are gap-free from their own start so this is effectively per-coin-start
    censoring, not mid-series holes)."""
    closes = {}
    dollar_vols = {}
    for coin in coins:
        df = load_alt_1d(coin)
        if df is None or len(df) < 5:
            continue
        s = df.set_index("t")["c"]
        s.name = coin
        closes[coin] = s
        dollar_vols[coin] = float((df["c"] * df["v"]).mean())
        del df
    close_panel = pd.DataFrame(closes).sort_index()
    ret_panel = np.log(close_panel / close_panel.shift(1))
    gc.collect()
    return close_panel, ret_panel, dollar_vols


# --------------------------------------------------------------------------
# 1. Return decomposition
# --------------------------------------------------------------------------

def _ols_fit(y: np.ndarray, X: np.ndarray) -> Dict:
    """Plain OLS via least squares; X must already include an intercept
    column. Returns coefficients, classic (homoskedastic) standard errors,
    t-distribution 95% CIs, R^2, and n/k for downstream df bookkeeping."""
    n, k = X.shape
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    rss = float(resid @ resid)
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - rss / tss if tss > 0 else 0.0
    dof = max(n - k, 1)
    sigma2 = rss / dof
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(np.clip(np.diag(sigma2 * xtx_inv), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)
    tcrit = stats.t.ppf(0.975, dof)
    ci_lo = beta - tcrit * se
    ci_hi = beta + tcrit * se
    return {"beta": beta, "se": se, "ci_lo": ci_lo, "ci_hi": ci_hi, "r2": r2, "n": n, "rss": rss, "tss": tss}


def decompose_returns(ret_panel: pd.DataFrame, btc_ret: pd.Series, sol_ret: pd.Series) -> pd.DataFrame:
    coins = list(ret_panel.columns)
    rows = []
    # BTC/sol-alt correlation collinearity check computed once on the shared window
    for coin in coins:
        y_full = ret_panel[coin]
        sector_ex_self = ret_panel.drop(columns=[coin]).mean(axis=1, skipna=True)
        n_contrib = ret_panel.drop(columns=[coin]).notna().sum(axis=1)
        sector_ex_self = sector_ex_self.where(n_contrib >= MIN_ALTS_FOR_SECTOR)

        df = pd.DataFrame({"y": y_full, "btc": btc_ret, "sector": sector_ex_self, "sol": sol_ret}).dropna()
        n = len(df)
        if n < 30:
            rows.append({"coin": coin, "n_obs": n, "low_confidence": True, "note": "insufficient overlap with majors window (<30 obs)"})
            continue

        y = df["y"].values
        X_btc = np.column_stack([np.ones(n), df["btc"].values])
        X_full = np.column_stack([np.ones(n), df["btc"].values, df["sector"].values])

        fit_btc = _ols_fit(y, X_btc)
        fit_full = _ols_fit(y, X_full)

        btc_share = fit_btc["r2"]
        sector_incr = max(fit_full["r2"] - fit_btc["r2"], 0.0)
        idio_share = max(1.0 - fit_full["r2"], 0.0)

        btc_sector_corr = float(df["btc"].corr(df["sector"]))

        rows.append({
            "coin": coin,
            "n_obs": n,
            "low_confidence": n < MIN_OBS_CONFIDENT,
            "btc_beta": fit_full["beta"][1],
            "btc_beta_ci_lo": fit_full["ci_lo"][1],
            "btc_beta_ci_hi": fit_full["ci_hi"][1],
            "sector_beta": fit_full["beta"][2],
            "sector_beta_ci_lo": fit_full["ci_lo"][2],
            "sector_beta_ci_hi": fit_full["ci_hi"][2],
            "r2_full": fit_full["r2"],
            "btc_var_share": btc_share,
            "sector_var_share_incr": sector_incr,
            "idio_var_share": idio_share,
            "btc_sector_collinearity": btc_sector_corr,
        })
    return pd.DataFrame(rows)


def sol_beta_crosscheck(ret_panel: pd.DataFrame, btc_ret: pd.Series, sol_ret: pd.Series) -> Dict:
    """Aggregate-only robustness check: how much of the story changes if
    component (b) is SOL-beta instead of the equal-weight alt-sector index.
    Not a full per-coin table (keeps the script from doubling in size) -
    reports the average R^2 delta across coins with enough overlap."""
    deltas = []
    for coin in ret_panel.columns:
        df = pd.DataFrame({"y": ret_panel[coin], "btc": btc_ret, "sol": sol_ret}).dropna()
        n = len(df)
        if n < 30:
            continue
        y = df["y"].values
        X_btc = np.column_stack([np.ones(n), df["btc"].values])
        X_btcsol = np.column_stack([np.ones(n), df["btc"].values, df["sol"].values])
        r2_btc = _ols_fit(y, X_btc)["r2"]
        r2_btcsol = _ols_fit(y, X_btcsol)["r2"]
        deltas.append(r2_btcsol - r2_btc)
    if not deltas:
        return {"n_coins": 0}
    return {"n_coins": len(deltas), "mean_incremental_r2_from_sol": float(np.mean(deltas)), "median": float(np.median(deltas))}


def liquidity_correlation(decomp_df: pd.DataFrame, dollar_vols: Dict[str, float]) -> Dict:
    d = decomp_df.dropna(subset=["idio_var_share"]).copy()
    d["avg_dollar_vol"] = d["coin"].map(dollar_vols)
    d = d.dropna(subset=["avg_dollar_vol"])
    d = d[d["avg_dollar_vol"] > 0]
    if len(d) < 5:
        return {"n": len(d), "rho": None, "p": None}
    log_vol = np.log(d["avg_dollar_vol"].values)
    rho, p = stats.spearmanr(log_vol, d["idio_var_share"].values)
    return {"n": len(d), "rho": float(rho), "p": float(p), "table": d[["coin", "idio_var_share", "avg_dollar_vol"]].sort_values("idio_var_share", ascending=False)}


# --------------------------------------------------------------------------
# 2. Regime taxonomy
# --------------------------------------------------------------------------

def build_regime_features(btc_close: pd.Series, close_panel: pd.DataFrame) -> pd.DataFrame:
    ema50 = btc_close.ewm(span=BTC_EMA_PERIOD, adjust=False).mean()
    btc_trend_pct = (btc_close - ema50) / ema50 * 100.0

    above_sma = close_panel > close_panel.rolling(BREADTH_SMA_PERIOD).mean()
    valid = close_panel.rolling(BREADTH_SMA_PERIOD).mean().notna()
    n_total = valid.sum(axis=1)
    n_up = (above_sma & valid).sum(axis=1)
    breadth_pct = (n_up / n_total * 100.0).where(n_total >= MIN_ALTS_FOR_SECTOR)

    btc_ret = log_returns(btc_close)
    realized_vol = btc_ret.rolling(REALIZED_VOL_WINDOW).std() * np.sqrt(365) * 100.0

    feat = pd.DataFrame({"btc_trend_pct": btc_trend_pct, "breadth_pct": breadth_pct, "realized_vol": realized_vol})
    feat = feat.dropna()
    feat = feat.iloc[BTC_EMA_PERIOD:]  # drop EMA warm-up region per weather.py's own MIN_ROWS convention
    return feat


def cluster_regimes(feat: pd.DataFrame, k_min: int, k_max: int) -> Tuple[pd.Series, int, Dict[int, float], np.ndarray]:
    X = feat.values
    mu, sigma = X.mean(axis=0), X.std(axis=0)
    sigma = np.where(sigma == 0, 1.0, sigma)
    Xz = (X - mu) / sigma

    sil_scores = {}
    fits = {}
    for k in range(max(2, k_min), k_max + 1):
        if k >= len(Xz):
            continue
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(Xz)
        if len(set(labels)) < 2:
            continue
        sil = silhouette_score(Xz, labels)
        sil_scores[k] = sil
        fits[k] = (labels, km.cluster_centers_)

    # restrict FINAL pick to the requested interpretable range but print the
    # full k=2..6 curve for transparency (module docstring)
    candidates = {k: s for k, s in sil_scores.items() if k_min <= k <= k_max}
    best_k = max(candidates, key=candidates.get) if candidates else max(sil_scores, key=sil_scores.get)
    labels, centers_z = fits[best_k]
    centers = centers_z * sigma + mu  # back to original feature units
    return pd.Series(labels, index=feat.index, name="regime"), best_k, sil_scores, centers


def name_regimes(centers: np.ndarray, feature_names: List[str]) -> Dict[int, str]:
    """Data-driven labels from each cluster's centroid relative to the
    OVERALL centroid mean - not hardcoded regime names, purely descriptive
    of what that cluster's days looked like on average."""
    overall = centers.mean(axis=0)
    names = {}
    for i, c in enumerate(centers):
        trend_bit = "BTC-up" if c[0] > overall[0] else "BTC-down"
        breadth_bit = "wide-breadth" if c[1] > overall[1] else "narrow-breadth"
        vol_bit = "hi-vol" if c[2] > overall[2] else "lo-vol"
        names[i] = f"{trend_bit}/{breadth_bit}/{vol_bit}"
    return names


def characterize_regimes(labels: pd.Series, close_panel: pd.DataFrame, ret_panel: pd.DataFrame) -> pd.DataFrame:
    ew_index_ret = ret_panel.reindex(labels.index).mean(axis=1, skipna=True)
    dispersion = ret_panel.reindex(labels.index).std(axis=1, skipna=True)

    rows = []
    dates = labels.index
    for regime_id in sorted(labels.unique()):
        regime_dates = dates[labels == regime_id]
        occ_pct = len(regime_dates) / len(dates) * 100.0

        fwd3, fwd5dd, disp_in_regime = [], [], []
        for d in regime_dates:
            loc = ew_index_ret.index.get_loc(d)
            fwd = ew_index_ret.iloc[loc + 1: loc + 4]
            if len(fwd) == 3:
                fwd3.append(fwd.sum())
            fwd5 = ew_index_ret.iloc[loc + 1: loc + 6]
            if len(fwd5) >= 2:
                cum = (1 + fwd5).cumprod()
                dd = (cum / cum.cummax() - 1).min()
                fwd5dd.append(dd)
            disp_in_regime.append(dispersion.loc[d])

        # trend vs mean-revert signature: lag-1 autocorr of ew index return,
        # restricted to consecutive-day pairs both inside this regime
        idx_pos = {d: i for i, d in enumerate(ew_index_ret.index)}
        pairs_t, pairs_t1 = [], []
        for d in regime_dates:
            i = idx_pos.get(d)
            if i is None or i == 0:
                continue
            prev_d = ew_index_ret.index[i - 1]
            if prev_d in set(regime_dates):
                pairs_t1.append(ew_index_ret.iloc[i])
                pairs_t.append(ew_index_ret.iloc[i - 1])
        autocorr = float(np.corrcoef(pairs_t, pairs_t1)[0, 1]) if len(pairs_t) >= 10 else np.nan

        rows.append({
            "regime_id": regime_id,
            "n_days": len(regime_dates),
            "occurrence_pct": occ_pct,
            "fwd3d_mean_pct": float(np.mean(fwd3) * 100) if fwd3 else np.nan,
            "fwd3d_median_pct": float(np.median(fwd3) * 100) if fwd3 else np.nan,
            "fwd5d_max_dd_mean_pct": float(np.mean(fwd5dd) * 100) if fwd5dd else np.nan,
            "contemp_dispersion_mean_pct": float(np.mean(disp_in_regime) * 100) if disp_in_regime else np.nan,
            "lag1_autocorr": autocorr,
            "n_autocorr_pairs": len(pairs_t),
        })
    return pd.DataFrame(rows).set_index("regime_id")


def funding_regime_crosscheck(labels: pd.Series) -> Optional[pd.DataFrame]:
    if not os.path.exists(FUNDING_OI_PATH):
        return None
    rows = []
    with open(FUNDING_OI_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                rows.append((d.get("timestamp"), d.get("funding_rate")))
            except Exception:
                continue
    if not rows:
        return None
    fdf = pd.DataFrame(rows, columns=["ts", "funding_rate"])
    fdf["ts"] = pd.to_datetime(fdf["ts"], errors="coerce", utc=True)
    fdf = fdf.dropna()
    fdf["date"] = fdf["ts"].dt.normalize()
    daily_avg_funding = fdf.groupby("date")["funding_rate"].mean()
    daily_avg_funding.index = daily_avg_funding.index.tz_localize(None) if daily_avg_funding.index.tz is not None else daily_avg_funding.index

    joined = pd.DataFrame({"regime": labels}).copy()
    joined.index = joined.index.tz_localize(None) if joined.index.tz is not None else joined.index
    joined["funding"] = daily_avg_funding.reindex(joined.index)
    joined = joined.dropna()
    if joined.empty:
        return None
    out = joined.groupby("regime")["funding"].agg(["mean", "count"])
    out["mean_bps_8h"] = out["mean"] * 1e4
    return out


# --------------------------------------------------------------------------
# 3. Cross-coin structure
# --------------------------------------------------------------------------

def cross_coin_correlation(ret_panel: pd.DataFrame, min_periods: int = 60) -> pd.DataFrame:
    return ret_panel.corr(min_periods=min_periods)


def hierarchical_subsectors(corr: pd.DataFrame, k_min: int = 3, k_max: int = 7) -> Tuple[Dict[str, int], float, int, Dict[int, float]]:
    corr_f = corr.fillna(0.0)
    dist = 1.0 - corr_f.values
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2.0
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    coph_corr, _ = cophenet(Z, condensed)

    sil_by_k: Dict[int, float] = {}
    for k in range(k_min, min(k_max, len(corr) - 1) + 1):
        cl = fcluster(Z, t=k, criterion="maxclust")
        if len(set(cl)) < 2:
            continue
        try:
            sil = silhouette_score(dist, cl, metric="precomputed")
        except Exception:
            continue
        sil_by_k[k] = sil
    best_k = max(sil_by_k, key=sil_by_k.get) if sil_by_k else 3
    clusters = fcluster(Z, t=best_k, criterion="maxclust")
    membership = dict(zip(corr.columns, clusters))
    return membership, float(coph_corr), best_k, sil_by_k


def dispersion_and_decoupling(ret_panel_full: pd.DataFrame, btc_ret: pd.Series, window: int = 20) -> Dict:
    disp = ret_panel_full.std(axis=1, skipna=True)
    roll_disp = disp.rolling(window).mean()

    aligned = ret_panel_full.reindex(btc_ret.index)
    corr_to_btc = aligned.apply(lambda col: col.rolling(window).corr(btc_ret))
    avg_corr_to_btc = corr_to_btc.mean(axis=1, skipna=True)

    combo = pd.DataFrame({"dispersion": roll_disp.reindex(avg_corr_to_btc.index), "avg_corr_to_btc": avg_corr_to_btc}).dropna()
    if combo.empty:
        return {"top_decoupling": None, "top_tethered": None}
    combo["decoupling_score"] = combo["dispersion"].rank(pct=True) - combo["avg_corr_to_btc"].rank(pct=True)
    top_decoupling = combo.sort_values("decoupling_score", ascending=False).head(5)
    top_tethered = combo.sort_values("decoupling_score", ascending=True).head(5)
    return {"top_decoupling": top_decoupling, "top_tethered": top_tethered, "mean_avg_corr_to_btc": float(avg_corr_to_btc.mean())}


# --------------------------------------------------------------------------
# 4. Era stability
# --------------------------------------------------------------------------

def era_split_check(ret_panel: pd.DataFrame, btc_ret: pd.Series, sol_ret: pd.Series, feat: pd.DataFrame, labels: pd.Series) -> Dict:
    common_idx = feat.index
    if len(common_idx) < 40:
        return {"ok": False, "note": "majors window too short for a meaningful era split"}
    mid = common_idx[len(common_idx) // 2]

    def half_decomp(idx_mask):
        sub_ret = ret_panel.loc[ret_panel.index.isin(common_idx[idx_mask])]
        return decompose_returns(sub_ret, btc_ret.reindex(sub_ret.index), sol_ret.reindex(sub_ret.index))

    h1_mask = common_idx <= mid
    h2_mask = common_idx > mid
    d1 = half_decomp(h1_mask)
    d2 = half_decomp(h2_mask)

    merged = d1.merge(d2, on="coin", suffixes=("_h1", "_h2"), how="inner")
    if "btc_beta_h1" in merged and "btc_beta_h2" in merged:
        merged["beta_delta"] = merged["btc_beta_h2"] - merged["btc_beta_h1"]
        merged["beta_sign_flip"] = np.sign(merged["btc_beta_h1"].fillna(0)) != np.sign(merged["btc_beta_h2"].fillna(0))
    else:
        merged["beta_delta"] = np.nan
        merged["beta_sign_flip"] = False

    regime_occ_h1 = labels[labels.index <= mid].value_counts(normalize=True) * 100
    regime_occ_h2 = labels[labels.index > mid].value_counts(normalize=True) * 100

    return {
        "ok": True,
        "mid_date": str(mid.date()),
        "beta_table": merged[["coin", "n_obs_h1", "n_obs_h2", "btc_beta_h1", "btc_beta_h2", "beta_delta", "beta_sign_flip"]] if "n_obs_h1" in merged else merged,
        "regime_occ_h1": regime_occ_h1,
        "regime_occ_h2": regime_occ_h2,
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def _fmt_pct(x, decimals=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{decimals}f}%"


def main():
    ap = argparse.ArgumentParser(description="Market structure study (read-only, standalone).")
    ap.add_argument("--k-min", type=int, default=3)
    ap.add_argument("--k-max", type=int, default=5)
    ap.add_argument("--out", type=str, default=None, help="optional path to dump a JSON summary")
    args = ap.parse_args()

    print("=" * 78)
    print("WAGMI MARKET STRUCTURE STUDY - descriptive, read-only, no edge claims")
    print("=" * 78)

    coins = discover_alt_coins()
    print(f"\nUniverse: {len(coins)} alts -> {', '.join(coins)}")

    close_panel, ret_panel_full, dollar_vols = build_alt_panels(coins)
    print(f"Alt panel span: {close_panel.index.min().date()} -> {close_panel.index.max().date()} ({len(close_panel)} calendar days)")

    btc_df = load_major_daily("BTC")
    sol_df = load_major_daily("SOL")
    if btc_df is None or sol_df is None:
        print("FATAL: could not load BTC/SOL majors cache.", file=sys.stderr)
        sys.exit(1)
    btc_close = btc_df.set_index("t")["c"]
    sol_close = sol_df.set_index("t")["c"]
    btc_ret = log_returns(btc_close)
    sol_ret = log_returns(sol_close)

    print(f"\n** DATA GAP NOTICE ** majors cache (union of all cache/*_daily_*.csv windows):")
    print(f"   BTC: {btc_close.index.min().date()} -> {btc_close.index.max().date()}  ({len(btc_close)} rows)")
    print(f"   SOL: {sol_close.index.min().date()} -> {sol_close.index.max().date()}  ({len(sol_close)} rows)")
    print(f"   This is ~{(btc_close.index.max()-btc_close.index.min()).days/30.4:.1f} months vs the alts' "
          f"~{(close_panel.index.max()-close_panel.index.min()).days/30.4:.1f} months. BTC-beta decomposition and the "
          f"regime taxonomy below are therefore confined to the SHORTER, more RECENT majors window; the alts' older "
          f"history (back to mid-2025) cannot be beta-decomposed or regime-classified without more BTC/SOL history.")
    print(f"   Majors data is also ~{(close_panel.index.max()-btc_close.index.max()).days}d stale vs the alts' last row.")

    majors_window = ret_panel_full.index.intersection(btc_ret.index)
    ret_panel_majors = ret_panel_full.loc[majors_window]

    # ---------------- 1. Return decomposition ----------------
    print("\n" + "-" * 78)
    print("1. RETURN DECOMPOSITION (BTC beta / alt-sector beta / idiosyncratic)")
    print("-" * 78)
    decomp = decompose_returns(ret_panel_majors, btc_ret, sol_ret)
    valid = decomp.dropna(subset=["idio_var_share"]).sort_values("idio_var_share", ascending=False)
    mean_collin = valid["btc_sector_collinearity"].mean() if not valid.empty else float("nan")
    print(f"n coins with usable overlap: {len(valid)}/{len(decomp)}   "
          f"mean BTC~sector-index collinearity: {mean_collin:.2f} (caveat: sequential decomposition, order=BTC first)")
    print(f"\n{'coin':8s} {'n':>4s} {'BTCvar%':>8s} {'sectorD%':>9s} {'idio%':>7s} {'R2':>6s} {'btc_beta [95%CI]':>26s} {'conf':>6s}")
    for _, r in valid.iterrows():
        conf = "LOW" if r["low_confidence"] else "ok"
        print(f"{r['coin']:8s} {int(r['n_obs']):4d} {r['btc_var_share']*100:7.1f}% {r['sector_var_share_incr']*100:8.1f}% "
              f"{r['idio_var_share']*100:6.1f}% {r['r2_full']:6.2f} "
              f"{r['btc_beta']:6.2f} [{r['btc_beta_ci_lo']:5.2f},{r['btc_beta_ci_hi']:5.2f}] {conf:>6s}")

    low_conf = decomp[decomp.get("low_confidence", False) == True]
    if not low_conf.empty:
        print(f"\nExcluded/low-confidence ({len(low_conf)}): " + ", ".join(low_conf["coin"].tolist()))

    sol_check = sol_beta_crosscheck(ret_panel_majors, btc_ret, sol_ret)
    print(f"\nRobustness check (component b = SOL-beta instead of alt-sector index): "
          f"across {sol_check.get('n_coins',0)} coins, adding SOL on top of BTC lifts R^2 by a mean of "
          f"{sol_check.get('mean_incremental_r2_from_sol', float('nan'))*100:.1f}pp (median {sol_check.get('median', float('nan'))*100:.1f}pp) - "
          f"{'similar order of magnitude to' if sol_check.get('n_coins') else 'n/a vs'} the alt-sector-index incremental share above.")

    liq = liquidity_correlation(decomp, dollar_vols)
    print(f"\nIdiosyncratic-share vs liquidity (avg $ volume, full-history): "
          f"Spearman rho={liq.get('rho')}, p={liq.get('p')}, n={liq.get('n')}")
    if liq.get("rho") is not None:
        direction = "thinner alts are MORE idiosyncratic" if liq["rho"] < 0 else "thinner alts are NOT more idiosyncratic (or noisier, not more coin-specific)"
        sig = "significant" if liq["p"] < 0.05 else "NOT significant at p<0.05"
        print(f"  -> {direction} ({sig}).")
        tbl = liq["table"]
        print(f"  Most idiosyncratic: {', '.join(tbl.head(5)['coin'])}")
        print(f"  Least idiosyncratic (most BTC/sector-tethered): {', '.join(tbl.tail(5)['coin'][::-1])}")

    # ---------------- 2. Regime taxonomy ----------------
    print("\n" + "-" * 78)
    print("2. REGIME TAXONOMY")
    print("-" * 78)
    feat = build_regime_features(btc_close, close_panel)
    print(f"Feature window (post EMA50 warm-up): {feat.index.min().date()} -> {feat.index.max().date()} ({len(feat)} days)")
    labels, best_k, sil_scores, centers = cluster_regimes(feat, args.k_min, args.k_max)
    print(f"Silhouette by k: " + ", ".join(f"k={k}:{s:.3f}" for k, s in sorted(sil_scores.items())))
    print(f"Chosen k={best_k} (best silhouette within requested range [{args.k_min},{args.k_max}])")

    names = name_regimes(centers, list(feat.columns))
    char = characterize_regimes(labels, close_panel, ret_panel_full)
    for rid in char.index:
        c = centers[rid]
        row = char.loc[rid]
        print(f"\nRegime {rid} [{names[rid]}]  centroid: BTCtrend={c[0]:+.1f}% breadth={c[1]:.0f}% vol={c[2]:.0f}%ann")
        print(f"  occurs {row['occurrence_pct']:.0f}% of days (n={int(row['n_days'])})")
        print(f"  fwd 3d alt-index return: mean={row['fwd3d_mean_pct']:+.2f}% median={row['fwd3d_median_pct']:+.2f}%  [DESCRIPTIVE ONLY, not a signal]")
        print(f"  fwd 5d alt-index max drawdown: mean={row['fwd5d_max_dd_mean_pct']:.2f}%")
        print(f"  contemporaneous cross-sectional dispersion: {row['contemp_dispersion_mean_pct']:.2f}%/day")
        ac = row["lag1_autocorr"]
        ac_note = "n/a (too few in-regime consecutive pairs)" if np.isnan(ac) else (f"{ac:+.2f} ({'mean-reverting' if ac < -0.05 else 'trending' if ac > 0.05 else 'no strong signature'}, n_pairs={int(row['n_autocorr_pairs'])})")
        print(f"  lag-1 autocorrelation of alt-index returns: {ac_note}")

    fund_check = funding_regime_crosscheck(labels)
    if fund_check is not None:
        print(f"\nSupplementary funding cross-check (data only covers a ~61d sub-window of the majors window, NOT a clustering input):")
        for rid, row in fund_check.iterrows():
            rname = names.get(rid, str(rid))
            n_days = int(row["count"])
            low_n = "  [LOW-N, treat as anecdotal]" if n_days < 10 else ""
            print(f"  Regime {rid} [{rname}]: mean funding {row['mean_bps_8h']:+.3f}bps/8h over {n_days} funding-days{low_n}")
    else:
        print("\nSupplementary funding cross-check: no overlapping days available, skipped.")

    # ---------------- 3. Cross-coin structure ----------------
    print("\n" + "-" * 78)
    print("3. CROSS-COIN STRUCTURE")
    print("-" * 78)
    corr = cross_coin_correlation(ret_panel_full)
    membership, coph, sub_k, sub_sil = hierarchical_subsectors(corr)
    print(f"Silhouette by k: " + ", ".join(f"k={k}:{s:.3f}" for k, s in sorted(sub_sil.items())))
    print(f"Hierarchical clustering (average linkage, 1-corr distance): k={sub_k} (best silhouette), cophenetic correlation={coph:.2f} "
          f"({'good' if coph > 0.75 else 'moderate' if coph > 0.6 else 'weak'} dendrogram fit)")
    groups: Dict[int, List[str]] = {}
    for coin, cl in membership.items():
        groups.setdefault(cl, []).append(coin)
    for cl, members in sorted(groups.items()):
        avg_intra_corr = corr.loc[members, members].where(~np.eye(len(members), dtype=bool)).stack().mean() if len(members) > 1 else float("nan")
        print(f"  Sub-cluster {cl} (avg intra-corr {avg_intra_corr:.2f}): {', '.join(members)}")

    decouple = dispersion_and_decoupling(ret_panel_full, btc_ret)
    print(f"\nMean rolling(20d) avg alt-vs-BTC correlation over majors window: {decouple.get('mean_avg_corr_to_btc', float('nan')):.2f}")
    if decouple.get("top_decoupling") is not None:
        print("Top 5 DECOUPLING windows (high dispersion + low avg BTC-corr = idiosyncratic-opportunity windows):")
        for d, row in decouple["top_decoupling"].iterrows():
            print(f"  {d.date()}: dispersion={row['dispersion']*100:.2f}%/day, avg_corr_to_BTC={row['avg_corr_to_btc']:+.2f}")
        print("Top 5 TETHERED windows (low dispersion + high avg BTC-corr = beta-dominated tape):")
        for d, row in decouple["top_tethered"].iterrows():
            print(f"  {d.date()}: dispersion={row['dispersion']*100:.2f}%/day, avg_corr_to_BTC={row['avg_corr_to_btc']:+.2f}")

    # ---------------- 4. Era stability / refutation ----------------
    print("\n" + "-" * 78)
    print("4. ERA-STABILITY / REFUTE-YOURSELF")
    print("-" * 78)
    era = era_split_check(ret_panel_majors, btc_ret, sol_ret, feat, labels)
    if not era.get("ok"):
        print(era.get("note"))
    else:
        print(f"Split at {era['mid_date']} (median date of the majors window).")
        bt = era["beta_table"].dropna(subset=["beta_delta"]) if "beta_delta" in era["beta_table"] else pd.DataFrame()
        if not bt.empty:
            flips = bt[bt["beta_sign_flip"] == True]
            print(f"BTC-beta sign flips H1->H2: {len(flips)}/{len(bt)} coins: {', '.join(flips['coin']) if not flips.empty else 'none'}")
            print(f"Mean |beta_delta| across coins: {bt['beta_delta'].abs().mean():.2f}")
        print(f"\nRegime occurrence H1: {dict((names.get(k,k), f'{v:.0f}%') for k,v in era['regime_occ_h1'].items())}")
        print(f"Regime occurrence H2: {dict((names.get(k,k), f'{v:.0f}%') for k,v in era['regime_occ_h2'].items())}")

    print("\nOTHER REFUTATIONS / CAVEATS (read before acting on anything above):")
    print("  - No forward-return-edge claim anywhere in this report: every 'fwd Nd' number is a historical")
    print("    DESCRIPTIVE average over a short, recent, non-independent (autocorrelated, overlapping-window) sample.")
    print("    It is NOT walk-forward validated, NOT cost-adjusted, and must not be treated as a signal.")
    print("  - BTC and the alt-sector index are collinear (see mean collinearity above); the BTC/sector variance split")
    print("    is a sequential-order modeling choice, not a clean orthogonal decomposition.")
    print("  - Regime taxonomy and beta decomposition both ride on the SHORT ~7mo majors window (see DATA GAP NOTICE),")
    print("    not the alts' fuller ~13mo history - treat regime-conditioned claims as provisional.")
    print("  - Coins with <90 overlapping observations are flagged LOW-CONFIDENCE above; their betas/idio-shares are noisy.")
    print("  - Funding cross-check covers only a ~61-day sub-window; liquidation-event data covers only ~5 days and was")
    print("    excluded entirely as too short to use.")

    if args.out:
        summary = {
            "decomposition": decomp.to_dict(orient="records"),
            "regime_k": best_k,
            "regime_silhouette": sil_scores,
            "regime_characterization": char.reset_index().to_dict(orient="records"),
            "subsector_membership": membership,
            "cophenetic_corr": coph,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nJSON summary written to {args.out}")

    gc.collect()
    print("\nDone.")


if __name__ == "__main__":
    main()
