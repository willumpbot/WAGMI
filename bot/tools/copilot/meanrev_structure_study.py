#!/usr/bin/env python
"""
WAGMI Co-Pilot MEAN-REVERSION STRUCTURE STUDY -- meanrev_structure_study.py
=============================================================================
FOUNDATIONAL market-structure study, mechanism-level test of the owner's
"accumulate on dips in thin alts" thesis. READ-ONLY: reads OHLC csvs under
data/longtail/ohlc/ and data/cache/, writes only its own output artifacts
under tools/copilot/meanrev_structure_output/. Never touches live bot state,
never posts to Discord, never trades.

QUESTION: where is dip-buying (mean-reversion) structurally viable vs where
does momentum/trend dominate, across coins x horizons x liquidity -- and is
mean-reversion actually stronger in thin alts (the owner's thesis), and does
it survive realistic round-trip trading costs once you account for it?

THIS IS DESCRIPTIVE STRUCTURE, NOT AN EDGE CLAIM. No position sizing, no
Kelly, no live-state writes. Four independent statistical methods are run
per (coin, horizon) so structure calls require multi-method agreement rather
than a single test's noise. See METHODOLOGY NOTES below for exact formulas
and honest limitations of each.

METHODOLOGY NOTES (read before trusting any number this script prints)
------------------------------------------------------------------------
1. Return autocorrelation (lags 1-5): acf(lag) = corr(r_t, r_{t-lag}).
   Significance uses the standard white-noise Bartlett SE = 1/sqrt(n-lag),
   z = acf/SE. This is the textbook approximation, not Newey-West -- with
   heteroskedastic crypto returns it can overstate significance slightly;
   that's exactly why method 2 (robust VR) is run alongside it.

2. Lo-MacKinlay (1988) variance ratio test, HETEROSKEDASTICITY-ROBUST
   variant, implemented from the paper's closed-form formulas (no
   statsmodels available in this environment -- verified against the
   textbook formulas by hand, see _variance_ratio()). VR(q) < 1 with
   robust z << 0 => mean-reversion; VR(q) > 1 with z >> 0 => trending
   (momentum/positive serial correlation in returns).

3. Ornstein-Uhlenbeck half-life: OLS regression of r_t (= delta log-price)
   on lagged log-price p_{t-1}. b < 0 and significant => mean-reverting,
   half_life = -ln(2)/ln(1+b). This method can only VOTE mean-reversion or
   abstain -- a near-zero b is consistent with both a random walk and a
   trending series (both look like a unit root to a levels regression), so
   it is never used to call "trending" on its own. Documented, not hidden.

4. Hurst exponent via classical rescaled-range (R/S) analysis on the return
   series, log-log regression of mean R/S against window size. H<0.5 =>
   mean-reverting, H>0.5 => trending/persistent, H~0.5 => random walk.
   R/S subsamples are NOT independent of each other (overlapping structure
   in the log-log fit), so the printed z-stat from the regression SE is a
   heuristic strength indicator, not a rigorous hypothesis test -- treated
   as a fourth VOTE, never as the sole basis for a claim.

Composite label = majority vote across the (up to 4) methods that produced
a decisive (non-abstain, |z|>=1.96) call. All four raw per-method outputs
are always written to the CSV so nothing is hidden behind the composite.

LIQUIDITY TIERS: every coin (25 alts + BTC + SOL) gets one entry-time-safe
representative liquidity value = mean of a rolling(20-bar, min 10).median()
of dollar volume (close*volume), SHIFTED by 1 bar so no bar's own volume
leaks into its own liquidity classification. Coins are then split into
terciles across the full 27-coin pool (data-driven, not hardcoded buckets)
and mapped to round-trip cost assumptions: top tercile "liquid" = 12bps,
mid tercile = 32bps, bottom tercile "thin" = 75bps (per owner's cost
assumptions for this study).

TRADEABLE FILTER: reversion amplitude (bps) is estimated two ways per
(coin, horizon): (a) AR(1)-implied expected reversal = |acf_lag1| * std(r),
i.e. what an average-sized move is expected to reverse by next bar; (b)
empirical dip-bounce = mean next-bar return conditional on the current bar
being in its own bottom decile of returns (the literal "buy the dip, does
it bounce" test). Both are compared against the coin's tier round-trip
cost. amplitude > cost => statistically tradeable; amplitude <= cost =>
statistical-only, indistinguishable from bid-ask bounce / spread noise.

ERA SPLIT: pre/post 2026-02-01 comparison on daily-derived horizons (1d,
3d, 5d) where both eras have >=40 obs; hourly horizons (1h, 4h) only have
data from 2026-01-12 onward so a pre/post split there would starve the
"pre" side -- flagged explicitly rather than faked.

CRASH-VS-OSCILLATION CHECK: n_dip_events (count of bottom-decile-return
bars) is reported per coin/horizon. A mean-reversion signal resting on
n_dip_events <= 2 is flagged POSSIBLE_SINGLE_EVENT_ARTIFACT -- i.e. the
"reversion" may be one crash-and-recover, not genuine repeated oscillation.

DATA INTEGRITY: the 25 longtail alts were verified gap-free before this
script was written (uniform row counts / calendar-day coverage per coin,
except PUMP and XPL which simply list later -- both still gap-free from
their first observation). BTC/SOL majors cache is STALE, ending ~2026-07-13
/14 while the alts run to ~2026-08-01 -- this is reported explicitly next
to every majors number, never silently normalized away.

Run: python tools/copilot/meanrev_structure_study.py
"""
from __future__ import annotations

import gc
import glob
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats as sstats

warnings.filterwarnings("ignore", category=FutureWarning)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALT_OHLC_DIR = os.path.join(BASE_DIR, "data", "longtail", "ohlc")
MAJORS_CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
OUT_DIR = os.path.join(BASE_DIR, "tools", "copilot", "meanrev_structure_output")

ERA_CUTOFF = pd.Timestamp("2026-02-01", tz="UTC")
Z_SIG = 1.96  # two-sided 95% threshold used for every method's significance call

HORIZONS = ["1h", "4h", "1d", "3d", "5d"]
# (source timeframe to load, resample rule or None if native)
HORIZON_SOURCE = {
    "1h": ("1h", None),
    "4h": ("1h", "4h"),
    "1d": ("1d", None),
    "3d": ("1d", "3D"),
    "5d": ("1d", "5D"),
}

TIER_COST_BPS = {"liquid": 12.0, "mid": 32.0, "thin": 75.0}


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_alt(symbol: str, tf: str) -> pd.DataFrame | None:
    path = os.path.join(ALT_OHLC_DIR, f"{symbol}_{tf}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["dt_utc_iso"], utc=True)
    df = df.set_index("dt").sort_index()
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def load_major(symbol: str, tf: str) -> pd.DataFrame | None:
    # tf in {"daily","1h"} matching the cache filenames (*_420d.csv)
    path = os.path.join(MAJORS_CACHE_DIR, f"{symbol}_{tf}_420d.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("dt").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    o = df["open"].resample(rule).first()
    h = df["high"].resample(rule).max()
    l = df["low"].resample(rule).min()
    c = df["close"].resample(rule).last()
    v = df["volume"].resample(rule).sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna(subset=["close"])


def get_horizon_df(df_native_by_tf: dict, horizon: str) -> pd.DataFrame | None:
    src_tf, rule = HORIZON_SOURCE[horizon]
    base = df_native_by_tf.get(src_tf)
    if base is None or len(base) < 30:
        return None
    if rule is None:
        return base
    return resample_ohlc(base, rule)


# --------------------------------------------------------------------------
# Method 1: autocorrelation
# --------------------------------------------------------------------------

def acf_battery(r: np.ndarray, max_lag: int = 5) -> list[dict]:
    n = len(r)
    out = []
    for lag in range(1, max_lag + 1):
        if n - lag < 15:
            break
        a = float(np.corrcoef(r[lag:], r[:-lag])[0, 1])
        se = 1.0 / np.sqrt(n - lag)
        z = a / se
        out.append({"lag": lag, "acf": a, "z": z})
    return out


def label_from_z(z: float | None, allow_trend: bool = True) -> str:
    if z is None or np.isnan(z):
        return "ABSTAIN"
    if z <= -Z_SIG:
        return "MR"
    if allow_trend and z >= Z_SIG:
        return "TR"
    return "RW"


# --------------------------------------------------------------------------
# Method 2: Lo-MacKinlay variance ratio (heteroskedasticity-robust)
# --------------------------------------------------------------------------

def variance_ratio(p: np.ndarray, q: int) -> dict | None:
    """p = log-price series (n+1 points), r implied = diff(p) (n points).
    Implements Lo & MacKinlay (1988) VR(q) with the robust (heteroskedasticity
    -consistent) test statistic, formulas reproduced by hand -- no statsmodels
    dependency available in this environment.
    """
    n = len(p) - 1
    if q < 2 or n <= q * 10:
        return None
    r = np.diff(p)
    mu = (p[-1] - p[0]) / n
    sigma_a2 = np.sum((r - mu) ** 2) / (n - 1)
    if sigma_a2 <= 0:
        return None
    diffs_q = p[q:] - p[:-q] - q * mu
    m = q * (n - q + 1) * (1 - q / n)
    if m <= 0:
        return None
    sigma_c2 = np.sum(diffs_q ** 2) / m
    vr = sigma_c2 / sigma_a2

    dev = r - mu
    denom = (np.sum(dev ** 2)) ** 2
    theta = 0.0
    if denom > 0:
        for j in range(1, q):
            num = n * np.sum((dev[j:] ** 2) * (dev[:-j] ** 2))
            delta_j = num / denom
            theta += ((2 * (q - j)) / q) ** 2 * delta_j
    z_robust = (vr - 1) / np.sqrt(theta) if theta > 0 else float("nan")

    phi = (2 * (2 * q - 1) * (q - 1)) / (3 * q * n)
    z_homo = (vr - 1) / np.sqrt(phi) if phi > 0 else float("nan")

    return {"q": q, "vr": vr, "z_robust": z_robust, "z_homo": z_homo}


# --------------------------------------------------------------------------
# Method 3: OU half-life
# --------------------------------------------------------------------------

def ou_half_life(p: np.ndarray) -> dict:
    x = p[:-1]
    y = np.diff(p)  # = r
    n = len(x)
    if n < 20:
        return {"b": None, "half_life": None, "z": None, "label": "ABSTAIN"}
    b, a = np.polyfit(x, y, 1)
    resid = y - (b * x + a)
    if n <= 2:
        return {"b": b, "half_life": None, "z": None, "label": "ABSTAIN"}
    s2 = np.sum(resid ** 2) / (n - 2)
    sxx = np.sum((x - x.mean()) ** 2)
    if sxx <= 0:
        return {"b": b, "half_life": None, "z": None, "label": "ABSTAIN"}
    se_b = np.sqrt(s2 / sxx)
    z = b / se_b if se_b > 0 else float("nan")
    half_life = None
    if b < 0 and (1 + b) > 0:
        half_life = -np.log(2) / np.log(1 + b)
    label = "MR" if (b < 0 and z <= -Z_SIG) else "ABSTAIN"
    return {"b": float(b), "half_life": half_life, "z": float(z), "label": label}


# --------------------------------------------------------------------------
# Method 4: Hurst exponent via R/S analysis
# --------------------------------------------------------------------------

def hurst_rs(r: np.ndarray) -> dict:
    n = len(r)
    if n < 40:
        return {"H": None, "z": None, "label": "ABSTAIN", "n_scales": 0}
    max_w = n // 4
    if max_w < 8:
        return {"H": None, "z": None, "label": "ABSTAIN", "n_scales": 0}
    sizes = sorted(set(np.unique(np.geomspace(8, max_w, num=10).astype(int))))
    log_w, log_rs = [], []
    for w in sizes:
        n_chunks = n // w
        if n_chunks < 2:
            continue
        rs_vals = []
        for i in range(n_chunks):
            chunk = r[i * w:(i + 1) * w]
            dev = chunk - chunk.mean()
            cum = np.cumsum(dev)
            R = cum.max() - cum.min()
            S = chunk.std(ddof=1)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            log_w.append(np.log(w))
            log_rs.append(np.log(np.mean(rs_vals)))
    if len(log_w) < 4:
        return {"H": None, "z": None, "label": "ABSTAIN", "n_scales": len(log_w)}
    slope, intercept, rval, pval, stderr = sstats.linregress(log_w, log_rs)
    H = slope
    z = (H - 0.5) / stderr if stderr > 0 else float("nan")
    label = label_from_z(z, allow_trend=True)
    return {"H": float(H), "z": float(z), "label": label, "n_scales": len(log_w)}


# --------------------------------------------------------------------------
# Amplitude / tradeability
# --------------------------------------------------------------------------

def reversion_amplitude(r: np.ndarray, acf1: float) -> dict:
    ret_std = float(np.std(r, ddof=1))
    amp_ar1_bps = abs(acf1) * ret_std * 1e4
    dip_thresh = np.percentile(r, 10)
    dip_mask = r <= dip_thresh
    idx = np.where(dip_mask)[0]
    idx = idx[idx + 1 < len(r)]
    next_rets = r[idx + 1] if len(idx) else np.array([])
    dip_bounce_bps = float(np.mean(next_rets) * 1e4) if len(next_rets) else float("nan")
    n_dip_events = int(dip_mask.sum())
    signs = np.sign(r)
    sign_changes = np.sum(signs[1:] != signs[:-1]) / max(1, len(r) - 1)
    return {
        "ret_std_bps": ret_std * 1e4,
        "amplitude_ar1_bps": amp_ar1_bps,
        "dip_bounce_bps": dip_bounce_bps,
        "n_dip_events": n_dip_events,
        "sign_change_rate": float(sign_changes),
    }


# --------------------------------------------------------------------------
# Per (coin, horizon) analysis
# --------------------------------------------------------------------------

def analyze_horizon(coin: str, asset_class: str, horizon: str, df: pd.DataFrame) -> dict:
    n = len(df) - 1
    row = {
        "coin": coin, "asset_class": asset_class, "horizon": horizon,
        "n_obs": n, "start": df.index[0], "end": df.index[-1],
    }
    if n < 30:
        row["status"] = "INSUFFICIENT_DATA"
        return row
    row["status"] = "OK"

    p = np.log(df["close"].values.astype(float))
    r = np.diff(p)

    acfs = acf_battery(r, max_lag=5)
    acf1 = acfs[0] if acfs else None
    row["acf1"] = acf1["acf"] if acf1 else None
    row["acf1_z"] = acf1["z"] if acf1 else None
    row["acf1_label"] = label_from_z(acf1["z"], allow_trend=True) if acf1 else "ABSTAIN"
    row["acf_lags"] = json.dumps([{"lag": a["lag"], "acf": round(a["acf"], 4), "z": round(a["z"], 2)} for a in acfs])

    q = int(np.clip(n // 40, 2, 10))
    vr = variance_ratio(p, q)
    if vr:
        row["vr_q"] = vr["q"]
        row["vr_stat"] = vr["vr"]
        row["vr_z_robust"] = vr["z_robust"]
        # VR<1 (mean reversion) => (vr-1) negative => z_robust negative => label_from_z handles sign correctly
        row["vr_label"] = label_from_z(vr["z_robust"], allow_trend=True) if not np.isnan(vr["z_robust"]) else "ABSTAIN"
    else:
        row["vr_q"], row["vr_stat"], row["vr_z_robust"], row["vr_label"] = None, None, None, "ABSTAIN"

    ou = ou_half_life(p)
    row["ou_b"] = ou["b"]
    row["ou_half_life"] = ou["half_life"]
    row["ou_z"] = ou["z"]
    row["ou_label"] = ou["label"]

    hu = hurst_rs(r)
    row["hurst_H"] = hu["H"]
    row["hurst_z"] = hu["z"]
    row["hurst_label"] = hu["label"]
    row["hurst_n_scales"] = hu["n_scales"]

    labels = [row["acf1_label"], row["vr_label"], row["ou_label"], row["hurst_label"]]
    votes_mr = sum(1 for l in labels if l == "MR")
    votes_tr = sum(1 for l in labels if l == "TR")
    votes_decisive = sum(1 for l in labels if l in ("MR", "TR"))
    row["votes_mr"] = votes_mr
    row["votes_tr"] = votes_tr
    row["votes_decisive_of_4"] = votes_decisive
    if votes_mr >= 3:
        composite = "STRONG_MEAN_REVERSION"
    elif votes_mr == 2 and votes_mr > votes_tr:
        composite = "WEAK_MEAN_REVERSION"
    elif votes_tr >= 3:
        composite = "STRONG_TRENDING"
    elif votes_tr == 2 and votes_tr > votes_mr:
        composite = "WEAK_TRENDING"
    else:
        composite = "RANDOM_WALK_NO_STRUCTURE"
    row["composite_label"] = composite

    amp = reversion_amplitude(r, row["acf1"] if row["acf1"] is not None else 0.0)
    row.update(amp)

    row["single_event_artifact_flag"] = bool(amp["n_dip_events"] <= 2)

    return row


def era_split(coin: str, asset_class: str, horizon: str, df: pd.DataFrame) -> dict:
    out = {"coin": coin, "asset_class": asset_class, "horizon": horizon}
    pre = df[df.index < ERA_CUTOFF]
    post = df[df.index >= ERA_CUTOFF]
    if len(pre) < 40 or len(post) < 40:
        out["era_status"] = f"INSUFFICIENT (pre={len(pre)}, post={len(post)})"
        return out
    out["era_status"] = "OK"
    for label, sub in (("pre", pre), ("post", post)):
        p = np.log(sub["close"].values.astype(float))
        r = np.diff(p)
        if len(r) < 20:
            out[f"{label}_acf1"] = None
            out[f"{label}_ou_b"] = None
            continue
        acfs = acf_battery(r, max_lag=1)
        out[f"{label}_acf1"] = acfs[0]["acf"] if acfs else None
        ou = ou_half_life(p)
        out[f"{label}_ou_b"] = ou["b"]
        out[f"{label}_n"] = len(r)
    if out.get("pre_acf1") is not None and out.get("post_acf1") is not None:
        out["sign_stable"] = bool(np.sign(out["pre_acf1"]) == np.sign(out["post_acf1"]))
    return out


# --------------------------------------------------------------------------
# Liquidity representative value (entry-time-safe rolling $volume)
# --------------------------------------------------------------------------

def representative_liquidity(df_1d: pd.DataFrame) -> float | None:
    if df_1d is None or len(df_1d) < 15:
        return None
    dollar_vol = df_1d["close"] * df_1d["volume"]
    safe = dollar_vol.rolling(20, min_periods=10).median().shift(1)
    val = safe.mean(skipna=True)
    return float(val) if pd.notna(val) else None


# --------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------

def discover_alt_symbols() -> list[str]:
    files = glob.glob(os.path.join(ALT_OHLC_DIR, "*_1d.csv"))
    syms = sorted({os.path.basename(f).replace("_1d.csv", "") for f in files})
    return syms


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[meanrev_structure_study] start {datetime.now(timezone.utc).isoformat()}")

    alt_syms = discover_alt_symbols()
    coins = [(s, "alt") for s in alt_syms] + [("BTC", "major"), ("SOL", "major")]
    print(f"[meanrev_structure_study] {len(alt_syms)} alts + 2 majors = {len(coins)} coins")

    all_rows = []
    era_rows = []
    liquidity = {}
    coverage_notes = {}

    for coin, asset_class in coins:
        try:
            if asset_class == "alt":
                df_1d = load_alt(coin, "1d")
                df_1h = load_alt(coin, "1h")
            else:
                df_1d = load_major(coin, "daily")
                df_1h = load_major(coin, "1h")

            if df_1d is None and df_1h is None:
                print(f"  [skip] {coin}: no data found")
                continue

            coverage_notes[coin] = {
                "asset_class": asset_class,
                "1d_n": None if df_1d is None else len(df_1d),
                "1d_start": None if df_1d is None else str(df_1d.index[0]),
                "1d_end": None if df_1d is None else str(df_1d.index[-1]),
                "1h_n": None if df_1h is None else len(df_1h),
                "1h_start": None if df_1h is None else str(df_1h.index[0]),
                "1h_end": None if df_1h is None else str(df_1h.index[-1]),
            }

            liquidity[coin] = representative_liquidity(df_1d)

            native = {"1d": df_1d, "1h": df_1h}
            for horizon in HORIZONS:
                hdf = get_horizon_df(native, horizon)
                if hdf is None:
                    all_rows.append({
                        "coin": coin, "asset_class": asset_class, "horizon": horizon,
                        "status": "NO_SOURCE_DATA", "n_obs": 0,
                    })
                    continue
                row = analyze_horizon(coin, asset_class, horizon, hdf)
                all_rows.append(row)

                # era split only meaningful for daily-derived horizons
                if horizon in ("1d", "3d", "5d"):
                    era_rows.append(era_split(coin, asset_class, horizon, hdf))
                elif horizon in ("1h", "4h"):
                    era_rows.append({
                        "coin": coin, "asset_class": asset_class, "horizon": horizon,
                        "era_status": "SKIPPED (hourly data window ~2026-01-12 onward, "
                                       "too short before 2026-02-01 cutoff for a fair pre/post split)",
                    })

            print(f"  [ok] {coin} ({asset_class}) processed")
        finally:
            del df_1d, df_1h
            if 'native' in dir():
                del native
            gc.collect()

    results_df = pd.DataFrame(all_rows)
    era_df = pd.DataFrame(era_rows)

    # ---- Liquidity tiers (data-driven terciles across all 27 coins) ----
    liq_series = pd.Series({k: v for k, v in liquidity.items() if v is not None}).sort_values(ascending=False)
    n_liq = len(liq_series)
    tier_of = {}
    third = n_liq / 3.0
    for rank, (coin, val) in enumerate(liq_series.items()):
        if rank < third:
            tier_of[coin] = "liquid"
        elif rank < 2 * third:
            tier_of[coin] = "mid"
        else:
            tier_of[coin] = "thin"

    results_df["repr_dollar_vol"] = results_df["coin"].map(liquidity)
    results_df["liquidity_tier"] = results_df["coin"].map(tier_of)
    results_df["cost_bps"] = results_df["liquidity_tier"].map(TIER_COST_BPS)
    results_df["tradeable_ar1"] = results_df["amplitude_ar1_bps"] > results_df["cost_bps"]
    results_df["tradeable_dip_bounce"] = results_df["dip_bounce_bps"].abs() > results_df["cost_bps"]

    # ---- Liquidity gradient: spearman corr(liquidity rank, MR-strength metrics) per horizon ----
    gradient_rows = []
    for horizon in HORIZONS:
        sub = results_df[(results_df["horizon"] == horizon) & (results_df["status"] == "OK")].copy()
        sub = sub.dropna(subset=["repr_dollar_vol"])
        if len(sub) < 6:
            gradient_rows.append({"horizon": horizon, "status": "INSUFFICIENT", "n": len(sub)})
            continue
        # More negative acf1 / lower half-life / lower VR / lower Hurst = "more mean-reverting"
        # liquidity rank: higher dollar vol = more liquid. We test corr(dollar_vol, metric).
        # Positive corr(dollar_vol, acf1) would mean MORE liquid -> LESS negative acf1 -> thesis holds if corr>0 significant.
        row = {"horizon": horizon, "n": len(sub)}
        for metric, higher_is_more_mr in [
            ("acf1", False),      # more negative = more MR
            ("hurst_H", False),   # lower = more MR
            ("vr_stat", False),   # lower (below 1) = more MR
        ]:
            m = sub.dropna(subset=[metric])
            if len(m) >= 6:
                rho, pval = sstats.spearmanr(m["repr_dollar_vol"], m[metric])
                row[f"spearman_liq_vs_{metric}"] = rho
                row[f"spearman_liq_vs_{metric}_p"] = pval
            else:
                row[f"spearman_liq_vs_{metric}"] = None
                row[f"spearman_liq_vs_{metric}_p"] = None
        # tier medians for monotonicity eyeball-check
        for tier in ("liquid", "mid", "thin"):
            tsub = sub[sub["liquidity_tier"] == tier]
            row[f"{tier}_median_acf1"] = tsub["acf1"].median() if len(tsub) else None
            row[f"{tier}_median_hurst"] = tsub["hurst_H"].median() if len(tsub) else None
            row[f"{tier}_median_vr"] = tsub["vr_stat"].median() if len(tsub) else None
            row[f"{tier}_median_ou_halflife"] = tsub["ou_half_life"].median() if len(tsub) else None
            row[f"{tier}_n"] = len(tsub)
        gradient_rows.append(row)
    gradient_df = pd.DataFrame(gradient_rows)

    # ---- write outputs ----
    map_path = os.path.join(OUT_DIR, "per_coin_horizon_map.csv")
    results_df.to_csv(map_path, index=False)
    era_path = os.path.join(OUT_DIR, "era_split.csv")
    era_df.to_csv(era_path, index=False)
    grad_path = os.path.join(OUT_DIR, "liquidity_gradient.csv")
    gradient_df.to_csv(grad_path, index=False)
    cov_path = os.path.join(OUT_DIR, "data_coverage.json")
    with open(cov_path, "w") as f:
        json.dump(coverage_notes, f, indent=2, default=str)
    tier_path = os.path.join(OUT_DIR, "liquidity_tiers.csv")
    pd.DataFrame({
        "coin": list(liq_series.index),
        "repr_dollar_vol": list(liq_series.values),
        "tier": [tier_of[c] for c in liq_series.index],
        "cost_bps": [TIER_COST_BPS[tier_of[c]] for c in liq_series.index],
    }).to_csv(tier_path, index=False)

    print(f"[meanrev_structure_study] wrote {map_path}")
    print(f"[meanrev_structure_study] wrote {era_path}")
    print(f"[meanrev_structure_study] wrote {grad_path}")
    print(f"[meanrev_structure_study] wrote {tier_path}")
    print(f"[meanrev_structure_study] wrote {cov_path}")

    print_console_summary(results_df, gradient_df, liq_series, tier_of)


def print_console_summary(results_df, gradient_df, liq_series, tier_of):
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)

    ok = results_df[results_df["status"] == "OK"]
    print(f"\nTotal (coin, horizon) cells analyzed: {len(ok)} / {len(results_df)}")

    print("\n-- Composite label counts by horizon --")
    print(ok.groupby(["horizon", "composite_label"]).size().unstack(fill_value=0))

    print("\n-- Liquidity tiers (data-driven terciles, all 27 coins) --")
    for tier in ("liquid", "mid", "thin"):
        members = [c for c, t in tier_of.items() if t == tier]
        print(f"  {tier} ({TIER_COST_BPS[tier]}bps): {members}")

    print("\n-- Liquidity gradient (spearman rho: $vol vs acf1/hurst/vr; "
          "POSITIVE rho with acf1/hurst/vr = thin-alt-more-MR thesis SUPPORTED) --")
    print(gradient_df[[c for c in gradient_df.columns if "spearman" in c or c == "horizon" or c == "n"]].to_string(index=False))

    print("\n-- Tradeable-after-cost counts (amplitude_ar1_bps > tier cost_bps) --")
    trad = ok.groupby(["horizon", "liquidity_tier"])["tradeable_ar1"].agg(["sum", "count"])
    print(trad)

    print("\n-- Strong mean-reversion cells that ARE tradeable after cost --")
    strong_mr_tradeable = ok[(ok["composite_label"].isin(["STRONG_MEAN_REVERSION", "WEAK_MEAN_REVERSION"])) & (ok["tradeable_ar1"])]
    cols = ["coin", "asset_class", "horizon", "liquidity_tier", "composite_label",
            "amplitude_ar1_bps", "cost_bps", "n_dip_events", "single_event_artifact_flag"]
    print(strong_mr_tradeable[cols].sort_values(["horizon", "liquidity_tier"]).to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()
