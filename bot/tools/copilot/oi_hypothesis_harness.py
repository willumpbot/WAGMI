#!/usr/bin/env python
"""
WAGMI Co-Pilot OI HYPOTHESIS HARNESS -- oi_hypothesis_harness.py
=============================================================================
PRE-REGISTRATION METHOD LOCK for H4 (OI-buildup flags elevated forward
cascade-risk) -- see data/copilot/PREREGISTRATION.md.

WHY THIS EXISTS, AND WHY NOW: H4 is pre-registered to be tested once the OI
corpus (data/funding_oi_history.jsonl, written by tools/funding_oi_collector.py)
spans >=60-90 days AND a second macro-vol regime. This script is written
BEFORE that bar is cleared so the METHOD is locked in before any qualifying
result exists -- if the method were designed after looking at a "promising"
cut of the data, any finding would be an overfit-by-construction, exactly the
failure mode the whole pre-registration ledger (H1-H5) exists to prevent.
Running this script's default (real-data) mode is safe at ANY maturity level
because the gating below makes it structurally incapable of printing a
significance claim before n>=30 independent WINDOWS exist per bucket -- see
"STRICT GATING". This is the last of the 5 pre-registered hypotheses to get
a dedicated harness (H1/H2 -> resolve_calls.py, H3/H5 -> liq_hypothesis_harness.py).

THE KNOWN FAILURE MODE THIS HARNESS EXISTS TO GUARD AGAINST (disclosed,
carried over from the origin one-shot script, tools/copilot/oi_risk_context_test.py):
on ~33 continuous days of BTC/ETH/SOL/HYPE/XRP OI history, OI-buildup states
showed elevated forward realized-vol vs OI-unwind (vol_ratio ~1.15, CI
[1.07,1.23], 5/5 coins same sign) -- BUT most of that spread survived only
because OI-buildup states happen to coincide with generally higher-volatility
stretches (vol-clustering), not because OI itself adds information on top of
what the coin's own trailing vol already implies. The origin script's own
H4a vol-regime control found the RESIDUAL OI-specific effect small, and with
only 33 continuous days there was no independent out-of-sample split either.
THE CENTRAL REQUIREMENT of this harness, per the pre-registration's own
"Success bar" language, is that the buildup-vs-unwind forward-vol spread
must be measured AFTER controlling for the coin's own trailing realized vol
(vol terciles, computed on the INDEPENDENT-WINDOW set, never on raw
autocorrelated ticks) -- a finding only counts as OI-SPECIFIC if it survives
that control. Both the naive (uncontrolled) and the controlled numbers are
always reported side by side so the gap between them is visible, never hidden.

THE PSEUDOREPLICATION LESSON (the reason this is a dedicated harness and not
another one-off script, same discipline as liq_hypothesis_harness.py's episode
collapse): raw OI-history rows are logged every ~16 minutes and are HEAVILY
autocorrelated -- consecutive rows mostly restate the same OI state, and
forward-looking windows computed at that cadence massively overlap once the
forward horizon (24h) is much longer than the sampling interval. Treating raw
row count as N would badly overstate independent sample size (exactly the
liq-feed partial-fill problem, but from time-series overlap rather than
exchange fill-splitting). The fix: collapse the tick stream into non-
overlapping, horizon-spaced INDEPENDENT WINDOWS (build_independent_windows()
below) -- at most one observation every PRIMARY_HORIZON_H hours per
continuous data segment per symbol. All gating, all N, and all reported
buckets are in INDEPENDENT-WINDOW units; raw eligible-tick counts are shown
only as a collapse-ratio diagnostic, never as a sample size.

THE OUTAGE-GAP GUARD: the OI collector had a ~22-day outage
(2026-06-07 -> 2026-06-29, confirmed by inspection, see oi_risk_context_test.py's
module docstring) plus smaller gaps. A window is never allowed to straddle a
gap larger than SEGMENT_GAP_H -- the tick stream is split into CONTINUOUS
SEGMENTS first, and the independent-window clock resets at every segment
boundary, so the outage can never be silently stitched into a single
window's trailing/forward statistics.

THE REGIME GUARD (beyond the n>=30 mandate, disclosed, mirrors
liq_hypothesis_harness.py's YOUNG-SAMPLE guard but per H4's own explicit
pre-registration language: "spans >=60-90 days AND a second macro-vol
regime"): a bucket can numerically clear n>=30 independent windows while the
whole dataset is still one macro-vol stretch -- 30 draws from one slice of
market conditions is not the same as 30 draws across varied regimes. This
harness computes a data-derived (not hardcoded) daily market-vol-level
tercile series and counts how many terciles persist for >=REGIME_MIN_DAYS
days as the disclosed proxy for "distinct macro-vol regime". Below
MIN_SPAN_DAYS_FOR_TRUST (60, the pre-registration's own lower bound) OR
MIN_REGIMES_FOR_TRUST (2) regimes, every number is tagged
[YOUNG-SAMPLE/SINGLE-REGIME, PROVISIONAL] -- this can only ADD caution, never
suppress or lower the n>=30 mechanism.

STRICT GATING (non-negotiable, mirrors resolve_calls.py's / liq_hypothesis_
harness.py's SIGNIFICANCE_N discipline): every bucket -- naive AND each
vol-tercile of the controlled test -- requires n>=30 INDEPENDENT WINDOWS on
BOTH the buildup and unwind side before a p-value/CI/significance verdict is
computed. Below that bar the ONLY thing ever printed for that bucket is
"n=X windows, UNDERPOWERED - descriptive only, not yet significant". This is
enforced in the COMPUTATION layer (compute_naive_bucket_test /
compute_vol_controlled_test leave welch/ci fields as None below the bar),
not just in printing, so there is no code path that can accidentally surface
a number below n=30.

REFUTE-YOURSELF HOOKS baked in (see run_real_data_readout()):
  1. THE VOL-CLUSTERING CONTROL (the central one, described above) --
     naive and vol-tercile-controlled spreads are always printed side by side.
  2. Single-symbol-dominance check -- flags when one symbol carries most of
     the pooled independent-window count.
  3. Outage-gap / continuous-segment report -- confirms the known ~22-day
     outage (and any other gap > SEGMENT_GAP_H) is detected and never stitched.
  4. Autocorrelation diagnostic -- raw-tick oi_roc_pctile lag-1 autocorrelation
     per symbol, printed to show WHY the independent-window collapse is
     necessary (this is the "OI is highly autocorrelated" caveat, computed,
     not just asserted).
  5. Cross-symbol consistency -- per-symbol buildup-vs-unwind sign agreement,
     descriptive only (never gates anything), flags a single-coin artifact.

READ-ONLY / STANDALONE: only reads data/funding_oi_history.jsonl. No imports
of llm/, execution/, core/, strategies/. No Discord. No network calls. Writes
nothing (--selftest and the default real-data mode both only print to stdout).

CLI:
    python tools/copilot/oi_hypothesis_harness.py                # real-data maturity readout (no conclusions drawn)
    python tools/copilot/oi_hypothesis_harness.py --horizon 24    # override the primary gated horizon (hours)
    python tools/copilot/oi_hypothesis_harness.py --selftest      # synthetic method-verification suite
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_PATH = os.path.join(BOT_DIR, "data", "funding_oi_history.jsonl")

# ---------------------------------------------------------------------------
# LOCKED METHOD PARAMETERS -- this is the pre-registration. Changing any of
# these after looking at a real-data result is exactly the p-hacking this
# file exists to prevent. If a change is ever truly warranted, date-stamp it
# here AND in PREREGISTRATION.md, same discipline as resolve_calls.py's
# "FORWARD-EVIDENCE ANCHOR FIX" notes and liq_hypothesis_harness.py's header.
# ---------------------------------------------------------------------------
MIN_ROWS_TO_USE = 500              # symbols with fewer raw rows are excluded entirely, not padded
OI_ROC_LOOKBACK_H = 24             # OI rate-of-change window (causal, as-of, tolerance-gated)
OI_STATE_LOOKBACK_H = 120          # 5d causal, STRICTLY-PRIOR percentile window for oi_roc_pctile
MIN_HIST_STATE = 200               # min prior oi_roc observations before trusting a percentile
TRAILING_VOL_H = 24                # own-baseline trailing-vol window (the vol-control's raw material)
GAP_GUARD_MIN = 60                 # invalidate any single tick-to-tick return spanning a gap > this (minutes)
SEGMENT_GAP_H = 6.0                # a gap bigger than this starts a new CONTINUOUS SEGMENT (independent-window clock resets)
ASOF_TOL_FACTOR = 3.0              # as-of lookback tolerance = cadence_s * this many multiples
DENSITY_FRAC = 0.5                 # trailing/forward windows need >= this fraction of a fully-dense window's tick count

PRIMARY_HORIZON_NAME = "24h"
PRIMARY_HORIZON_H = 24             # THE gated horizon (independent windows + naive + vol-control test)
CONTEXT_HORIZONS_H: Dict[str, int] = {"6h": 6, "48h": 48}   # printed descriptively only -- NEVER gated,
                                                              # to avoid multiple-comparison fishing across horizons
                                                              # (same discipline as resolve_calls.py scoring fwd_3d_pct only)

SIGNIFICANCE_N = 30                # min INDEPENDENT WINDOWS per bucket (both sides) before ANY p-value/CI is computed
MIN_SPAN_DAYS_FOR_TRUST = 60       # PREREGISTRATION.md's disclosed "60-90 days" lower bound
MIN_REGIMES_FOR_TRUST = 2          # PREREGISTRATION.md's disclosed "a second macro-vol regime"
REGIME_MIN_DAYS = 3                # a data-derived daily-vol tercile must persist this many days to count as a "distinct regime"
SINGLE_SYMBOL_DOMINANCE_WARN = 0.50  # flag if one symbol carries more than this share of pooled independent windows
TAIL_PCTILE = 90                   # living-value tail-move threshold: pooled 90th pctile of |tick log-return|

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 1337              # fixed seed -> reproducible bootstrap CIs, never re-rolled to chase a result


# ---------------------------------------------------------------------------
# Data loading (mirrors oi_risk_context_test.py's loader, but the usable
# symbol set is discovered dynamically from MIN_ROWS_TO_USE -- never a
# hardcoded symbol list -- so new symbols the collector accrues history for
# are picked up automatically, per this project's living-values discipline).
# ---------------------------------------------------------------------------

def load_oi_log(path: str) -> Dict[str, pd.DataFrame]:
    rows_by_symbol: Dict[str, List[dict]] = defaultdict(list)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = d.get("symbol")
            if not sym or d.get("price") is None or d.get("open_interest") is None or d.get("timestamp") is None:
                continue
            rows_by_symbol[sym].append(d)

    out: Dict[str, pd.DataFrame] = {}
    for sym, rows in rows_by_symbol.items():
        if len(rows) < MIN_ROWS_TO_USE:
            continue
        df = pd.DataFrame(rows)
        df["dt"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
        df["price"] = df["price"].astype(float)
        df["open_interest"] = df["open_interest"].astype(float)
        out[sym] = df[["dt", "price", "open_interest"]]
    return out


def estimate_tail_thresh(raw: Dict[str, pd.DataFrame]) -> Optional[float]:
    """Pooled TAIL_PCTILE-th percentile of |tick-to-tick log return| across all
    usable symbols, gap-guarded. A living-value threshold, not a hardcoded
    guess -- printed at runtime so it's auditable. Returns None if there is
    not enough data to estimate it (selftest thin-data paths skip tail-freq)."""
    pooled = []
    for sym, df in raw.items():
        if len(df) < 2:
            continue
        dt_s = df["dt"].dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype(np.int64).astype(float)
        price = df["price"].to_numpy(dtype=float)
        gaps = np.diff(dt_s)
        logret = np.diff(np.log(price))
        logret = logret[gaps <= GAP_GUARD_MIN * 60.0]
        if len(logret):
            pooled.append(np.abs(logret))
    if not pooled:
        return None
    all_abs = np.concatenate(pooled)
    if len(all_abs) < 30:
        return None
    return float(np.nanpercentile(all_abs, TAIL_PCTILE))


# ---------------------------------------------------------------------------
# Causal feature engineering (entry-time-safe throughout: every feature at
# row t uses ONLY OI/price data with timestamp <= t; forward labels are
# computed AFTER feature construction and never fed back into any feature).
# Ported/generalized from oi_risk_context_test.py's build_symbol_features --
# that logic was already proven on real data; this harness generalizes the
# horizon set and feeds BOTH real data and synthetic selftest data through
# the identical code path, same discipline as liq_hypothesis_harness.py
# running synthetic events through the real prepare_events() parser.
# ---------------------------------------------------------------------------

def _asof_index(dt_s: np.ndarray, i: int, lookback_s: float, tol_s: float) -> int:
    """Index of the last tick <= dt_s[i] - lookback_s, but ONLY if that tick
    is within tol_s of the intended lookback -- otherwise -1. Stops a lookup
    taken shortly after a gap (e.g. the 22-day outage) from silently grabbing
    a point from before the gap and mislabeling it 'N hours ago'."""
    target = dt_s[i] - lookback_s
    j = np.searchsorted(dt_s, target, side="right") - 1
    if j < 0:
        return -1
    if abs((dt_s[i] - dt_s[j]) - lookback_s) > tol_s:
        return -1
    return j


def build_symbol_features(
    df: pd.DataFrame, tail_thresh: Optional[float], horizons: Dict[str, int]
) -> pd.DataFrame:
    """df must have columns dt (tz-aware UTC), price, open_interest, sorted or
    not (sorted here). Returns a feature frame with oi_roc_24h, oi_roc_pctile,
    oi_state, trailing_vol24, and per-horizon fwd_vol_/fwd_tailfreq_/vol_ratio_
    columns (suffix = horizon dict key, e.g. 'vol_ratio_24h')."""
    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    dt_s = df["dt"].dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype(np.int64).astype(float)
    price = df["price"].to_numpy(dtype=float)
    oi = df["open_interest"].to_numpy(dtype=float)

    gaps = np.diff(dt_s)
    cadence_s = float(np.median(gaps)) if len(gaps) else 900.0

    # tick-to-tick log returns, gap-guarded: invalidate any return whose
    # underlying interval exceeds GAP_GUARD_MIN minutes -- quarantines gaps
    # (including the ~22-day outage) from the raw return series itself.
    logret = np.full(n, np.nan)
    logret[1:] = np.diff(np.log(price))
    gap_mask = np.zeros(n, dtype=bool)
    gap_mask[1:] = gaps > (GAP_GUARD_MIN * 60.0)
    logret[gap_mask] = np.nan

    H = 3600.0
    tol_s = cadence_s * ASOF_TOL_FACTOR

    oi_roc = np.full(n, np.nan)
    trailing_vol = np.full(n, np.nan)
    min_hist_trail = max(5, int(DENSITY_FRAC * TRAILING_VOL_H * H / cadence_s))

    for i in range(n):
        j = _asof_index(dt_s, i, OI_ROC_LOOKBACK_H * H, tol_s)
        if j >= 0 and oi[j] > 0:
            oi_roc[i] = oi[i] / oi[j] - 1.0
        cutoff = dt_s[i] - TRAILING_VOL_H * H
        k = np.searchsorted(dt_s, cutoff, side="right")
        if i - k >= min_hist_trail:
            trailing_vol[i] = np.nanstd(logret[k:i + 1], ddof=0)

    # oi_roc_pctile: causal, STRICTLY PRIOR window (never includes i itself)
    oi_roc_pctile = np.full(n, np.nan)
    for i in range(n):
        cutoff = dt_s[i] - OI_STATE_LOOKBACK_H * H
        k = np.searchsorted(dt_s, cutoff, side="right")
        hist = oi_roc[k:i]
        hist = hist[~np.isnan(hist)]
        if len(hist) >= MIN_HIST_STATE and not np.isnan(oi_roc[i]):
            oi_roc_pctile[i] = float((hist <= oi_roc[i]).mean() * 100.0)

    out = pd.DataFrame({
        "dt": df["dt"], "price": price, "open_interest": oi,
        "oi_roc_24h": oi_roc, "oi_roc_pctile": oi_roc_pctile,
        "trailing_vol24": trailing_vol,
    })

    for name, h in horizons.items():
        fv = np.full(n, np.nan)
        ftail = np.full(n, np.nan)
        min_hist_fwd = max(3, int(DENSITY_FRAC * h * H / cadence_s))
        for i in range(n):
            target = dt_s[i] + h * H
            j = np.searchsorted(dt_s, target, side="right")
            cnt = j - (i + 1)
            if cnt >= min_hist_fwd:
                seg_ret = logret[i + 1:j]
                fv[i] = np.nanstd(seg_ret, ddof=0)
                if tail_thresh is not None:
                    valid = seg_ret[~np.isnan(seg_ret)]
                    ftail[i] = float((np.abs(valid) > tail_thresh).mean()) if len(valid) else np.nan
        out[f"fwd_vol_{name}"] = fv
        out[f"fwd_tailfreq_{name}"] = ftail
        out[f"vol_ratio_{name}"] = fv / trailing_vol

    out["oi_state"] = pd.cut(
        out["oi_roc_pctile"], bins=[-0.01, 33.34, 66.67, 100.01],
        labels=["unwind", "neutral", "buildup"],
    )
    out["cadence_s"] = cadence_s
    return out


# ---------------------------------------------------------------------------
# CONTINUOUS SEGMENTS + INDEPENDENT WINDOWS -- THE pseudoreplication fix.
# ---------------------------------------------------------------------------

def build_continuous_segment_id(dt_series: pd.Series, segment_gap_h: float) -> np.ndarray:
    """A new segment id starts every time the gap to the previous row exceeds
    segment_gap_h hours -- this is what makes the ~22-day outage (and any
    other big gap) self-quarantining for window construction below."""
    dt = dt_series.reset_index(drop=True)
    n = len(dt)
    seg_id = np.zeros(n, dtype=int)
    if n <= 1:
        return seg_id
    gaps_sec = dt.diff().dt.total_seconds().to_numpy()[1:]
    cur = 0
    for i, g in enumerate(gaps_sec, start=1):
        if g > segment_gap_h * 3600.0:
            cur += 1
        seg_id[i] = cur
    return seg_id


def build_independent_windows(feat_df: pd.DataFrame, horizon_name: str, symbol: str) -> List[dict]:
    """THE pseudoreplication fix for H4: OI state and forward-vol windows are
    heavily autocorrelated at native (~16min) cadence -- consecutive rows
    largely restate the same OI state, and overlapping forward windows are
    correlated once the forward horizon is much longer than the sampling
    interval. Collapses the tick stream into non-overlapping,
    horizon-spaced INDEPENDENT WINDOWS per continuous segment (a run of data
    with no gap > SEGMENT_GAP_H): the first row at/after each
    `horizon`-hour boundary that carries a COMPLETE observation (oi_state,
    vol_ratio, trailing_vol24 all non-null) is kept as that window's single
    representative row; rows before the next boundary are dropped, never
    averaged (averaging would itself be a new form of look-ahead smoothing).
    A segment boundary always resets the window clock -- a window can NEVER
    straddle the known 22-day outage or any other qualifying gap."""
    vr_col = f"vol_ratio_{horizon_name}"
    d = feat_df.sort_values("dt").reset_index(drop=True)
    if len(d) == 0:
        return []
    seg_id = build_continuous_segment_id(d["dt"], SEGMENT_GAP_H)
    out: List[dict] = []
    next_allowed: Dict[int, pd.Timestamp] = {}
    for i in range(len(d)):
        sid = int(seg_id[i])
        row = d.iloc[i]
        na = next_allowed.get(sid)
        if na is not None and row["dt"] < na:
            continue
        if pd.isna(row.get("oi_state")) or pd.isna(row.get(vr_col)) or pd.isna(row.get("trailing_vol24")):
            continue
        out.append({
            "symbol": symbol,
            "dt": row["dt"],
            "oi_state": str(row["oi_state"]),
            "vol_ratio": float(row[vr_col]),
            "tail_freq": float(row[f"fwd_tailfreq_{horizon_name}"]) if pd.notna(row.get(f"fwd_tailfreq_{horizon_name}")) else float("nan"),
            "trailing_vol24": float(row["trailing_vol24"]),
            "oi_roc_pctile": float(row["oi_roc_pctile"]),
        })
        next_allowed[sid] = row["dt"] + pd.Timedelta(hours=PRIMARY_HORIZON_H if horizon_name == PRIMARY_HORIZON_NAME else int(horizon_name.rstrip("h")))
    return out


def window_dedup_report(feat_frames: Dict[str, pd.DataFrame], horizon_name: str) -> dict:
    per_symbol_windows: Dict[str, List[dict]] = {}
    all_windows: List[dict] = []
    per_symbol_raw_eligible: Dict[str, int] = {}
    for sym, feat in feat_frames.items():
        ws = build_independent_windows(feat, horizon_name, sym)
        per_symbol_windows[sym] = ws
        all_windows.extend(ws)
        per_symbol_raw_eligible[sym] = int(feat["oi_state"].notna().sum())
    n_windows = len(all_windows)
    n_raw_eligible = sum(per_symbol_raw_eligible.values())
    per_symbol_n = {sym: len(ws) for sym, ws in per_symbol_windows.items()}
    top_sym, top_n = (max(per_symbol_n.items(), key=lambda kv: kv[1]) if per_symbol_n else (None, 0))
    dominance = (top_n / n_windows) if n_windows else float("nan")
    return {
        "n_raw_eligible_ticks": n_raw_eligible,
        "n_independent_windows": n_windows,
        "collapse_ratio": (n_raw_eligible / n_windows) if n_windows else float("nan"),
        "per_symbol_raw_eligible": per_symbol_raw_eligible,
        "per_symbol_n": per_symbol_n,
        "per_symbol_windows": per_symbol_windows,
        "all_windows": all_windows,
        "top_symbol": top_sym, "top_symbol_n": top_n, "dominance_frac": dominance,
        "dominance_flag": (dominance >= SINGLE_SYMBOL_DOMINANCE_WARN) if n_windows else False,
    }


# ---------------------------------------------------------------------------
# MACRO-VOL REGIME GUARD -- data-derived, not hardcoded.
# ---------------------------------------------------------------------------

def compute_macro_vol_regimes(feat_frames: Dict[str, pd.DataFrame]) -> dict:
    """For each UTC calendar day, the mean of each usable symbol's LAST
    trailing_vol24 reading that day is averaged across symbols into a single
    'market vol level' proxy for that day. That daily series is split into
    terciles of ITS OWN distribution (no hardcoded vol thresholds, same
    tercile convention used for oi_state) -- a tercile counts as a DISTINCT
    regime only if it persists for >= REGIME_MIN_DAYS days. This is the
    disclosed, data-derived proxy for H4's pre-registered 'must span >=2
    distinct macro-vol regimes' guard."""
    daily = {}
    for sym, df in feat_frames.items():
        d = df.dropna(subset=["trailing_vol24"]).copy()
        if d.empty:
            continue
        d["day"] = d["dt"].dt.floor("D")
        daily[sym] = d.groupby("day")["trailing_vol24"].last()
    if not daily:
        return {"regime_count": 0, "daily_series": pd.Series(dtype=float), "regime_by_day": {}, "counts": {}}
    combined = pd.concat(daily.values(), axis=1)
    market_vol = combined.mean(axis=1, skipna=True).dropna().sort_index()
    if len(market_vol) < 3:
        return {"regime_count": 0, "daily_series": market_vol, "regime_by_day": {}, "counts": {}}
    edges = np.quantile(market_vol.to_numpy(), [1 / 3, 2 / 3])

    def label(v: float) -> str:
        if v <= edges[0]:
            return "low_vol_regime"
        if v <= edges[1]:
            return "mid_vol_regime"
        return "high_vol_regime"

    regime_by_day = {str(day.date()): label(v) for day, v in market_vol.items()}
    counts = Counter(regime_by_day.values())
    distinct = sum(1 for c in counts.values() if c >= REGIME_MIN_DAYS)
    return {
        "regime_count": distinct, "daily_series": market_vol,
        "regime_by_day": regime_by_day, "counts": counts, "edges": edges,
    }


# ---------------------------------------------------------------------------
# Stats helpers -- bootstrap CI + Welch's t-test, GATED IN THE COMPUTATION
# LAYER (never in the printer) at n>=SIGNIFICANCE_N per side.
# ---------------------------------------------------------------------------

def _bootstrap_mean_ci(x: np.ndarray, null: Optional[float] = None) -> Optional[dict]:
    x = x[~np.isnan(x)]
    n = len(x)
    if n < SIGNIFICANCE_N:
        return None
    npr = np.random.default_rng(BOOTSTRAP_SEED)
    boots = npr.choice(x, size=(BOOTSTRAP_ITERS, n), replace=True).mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    obs = float(x.mean())
    res = {"n": n, "mean": obs, "ci_lo": float(lo), "ci_hi": float(hi)}
    if null is not None:
        res["excludes_null"] = bool(lo > null or hi < null)
    return res


def welch_test(a: np.ndarray, b: np.ndarray) -> Optional[dict]:
    """Two-sided Welch's t-test, gated: returns None (no p-value/CI at all)
    whenever EITHER side has n < SIGNIFICANCE_N -- enforced here, in the
    computation layer, so no downstream printer can accidentally surface a
    number below the pre-registered bar."""
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < SIGNIFICANCE_N or len(b) < SIGNIFICANCE_N:
        return None
    from scipy.stats import ttest_ind
    t, p = ttest_ind(a, b, equal_var=False)
    return {"t": float(t), "p": float(p), "n_a": int(len(a)), "n_b": int(len(b))}


def compute_naive_bucket_test(windows: List[dict], metric: str, null: Optional[float]) -> dict:
    """The UNCONTROLLED read: mean `metric` per oi_state bucket, pooled
    across symbols, on independent windows (NOT raw ticks). This is exactly
    the read that the origin script's H1 showed elevated for buildup -- and
    exactly the read this harness's vol-control (below) must be compared
    against, never trusted on its own."""
    by_state: Dict[str, List[float]] = defaultdict(list)
    for w in windows:
        by_state[w["oi_state"]].append(w[metric])
    result: Dict[str, dict] = {}
    for state in ("unwind", "neutral", "buildup"):
        arr = np.array(by_state.get(state, []), dtype=float)
        result[state] = {
            "n": len(arr),
            "mean": float(np.nanmean(arr)) if len(arr) else float("nan"),
            "ci": _bootstrap_mean_ci(arr, null=null),
        }
    b = np.array(by_state.get("buildup", []), dtype=float)
    u = np.array(by_state.get("unwind", []), dtype=float)
    result["buildup_minus_unwind"] = {
        "spread": float(np.nanmean(b) - np.nanmean(u)) if len(b) and len(u) else float("nan"),
        "welch": welch_test(b, u),
    }
    return result


def compute_vol_controlled_test(windows: List[dict], metric: str) -> dict:
    """THE CENTRAL CONTROL: repeats the buildup-vs-unwind spread WITHIN
    trailing-vol terciles, where the tercile edges are computed on the
    pooled INDEPENDENT-WINDOW set itself (never on raw autocorrelated
    ticks -- that would let the same handful of correlated high-vol ticks
    both define the tercile edges and populate them). Each tercile is gated
    independently at n>=SIGNIFICANCE_N on BOTH buildup and unwind before any
    p-value/CI is computed. A buildup-vs-unwind spread only counts as
    OI-SPECIFIC (as opposed to vol-clustering restated) if it survives here."""
    if len(windows) < 3:
        return {"edges": None, "terciles": {}, "n_terciles_cleared": 0}
    vols = np.array([w["trailing_vol24"] for w in windows], dtype=float)
    edges = np.quantile(vols, [1 / 3, 2 / 3])

    def tercile_of(v: float) -> str:
        if v <= edges[0]:
            return "low_vol"
        if v <= edges[1]:
            return "mid_vol"
        return "high_vol"

    by_t: Dict[str, List[dict]] = defaultdict(list)
    for w in windows:
        by_t[tercile_of(w["trailing_vol24"])].append(w)

    result: Dict[str, dict] = {}
    for name in ("low_vol", "mid_vol", "high_vol"):
        ws = by_t.get(name, [])
        b = np.array([w[metric] for w in ws if w["oi_state"] == "buildup"], dtype=float)
        u = np.array([w[metric] for w in ws if w["oi_state"] == "unwind"], dtype=float)
        result[name] = {
            "n_buildup": len(b), "n_unwind": len(u),
            "buildup_mean": float(np.nanmean(b)) if len(b) else float("nan"),
            "unwind_mean": float(np.nanmean(u)) if len(u) else float("nan"),
            "spread": float(np.nanmean(b) - np.nanmean(u)) if len(b) and len(u) else float("nan"),
            "welch": welch_test(b, u),
        }
    n_cleared = sum(1 for v in result.values() if v["welch"] is not None)
    return {"edges": (float(edges[0]), float(edges[1])), "terciles": result, "n_terciles_cleared": n_cleared}


def cross_symbol_consistency(per_symbol_windows: Dict[str, List[dict]], metric: str) -> dict:
    """Descriptive-only refute-yourself diagnostic (never gates anything):
    per-symbol buildup-vs-unwind sign agreement -- flags a pooled-looking
    finding that's really a single coin's artifact (matches origin script's
    H4c, 4/5-coin-agreement convention)."""
    signs = []
    details: Dict[str, dict] = {}
    for sym, ws in per_symbol_windows.items():
        b = np.array([w[metric] for w in ws if w["oi_state"] == "buildup"], dtype=float)
        u = np.array([w[metric] for w in ws if w["oi_state"] == "unwind"], dtype=float)
        if len(b) < 5 or len(u) < 5:
            details[sym] = {"n_buildup": len(b), "n_unwind": len(u), "spread": None}
            continue
        spread = float(np.mean(b) - np.mean(u))
        signs.append(1 if spread > 0 else (-1 if spread < 0 else 0))
        details[sym] = {"n_buildup": len(b), "n_unwind": len(u), "spread": spread}
    agree = max(signs.count(1), signs.count(-1)) if signs else 0
    return {"details": details, "n_symbols_with_signal": len(signs), "n_agree": agree}


def era_split_check(windows: List[dict], metric: str) -> dict:
    """Descriptive-only refute-yourself diagnostic: splits the pooled
    independent-window set at its time midpoint and reports the
    buildup-vs-unwind spread sign in each half -- a sanity check against a
    single short volatile stretch dressed up as a stable finding (matches
    origin script's H4d era-split, explicitly low-power / descriptive)."""
    if not windows:
        return {}
    ws_sorted = sorted(windows, key=lambda w: w["dt"])
    mid = ws_sorted[len(ws_sorted) // 2]["dt"]
    out = {}
    for era_name, sub in (("first_half", [w for w in ws_sorted if w["dt"] < mid]),
                          ("second_half", [w for w in ws_sorted if w["dt"] >= mid])):
        b = np.array([w[metric] for w in sub if w["oi_state"] == "buildup"], dtype=float)
        u = np.array([w[metric] for w in sub if w["oi_state"] == "unwind"], dtype=float)
        out[era_name] = {
            "n_buildup": len(b), "n_unwind": len(u),
            "spread": float(np.mean(b) - np.mean(u)) if len(b) and len(u) else None,
        }
    return out


# ---------------------------------------------------------------------------
# Real-data maturity readout -- draws NO conclusion, ever.
# ---------------------------------------------------------------------------

def _hdr(title: str) -> None:
    print("\n" + "=" * 84)
    print(title)
    print("=" * 84)


def _fmt_bucket_line(name: str, r: dict) -> str:
    n = r["n"]
    if n < SIGNIFICANCE_N:
        return (f"    {name:<10s} n={n:<5d}  UNDERPOWERED - descriptive only, not yet significant "
                f"(need n>={SIGNIFICANCE_N} independent windows)")
    ci = r["ci"]
    ci_bit = f"95% CI=[{ci['ci_lo']:.3f},{ci['ci_hi']:.3f}]" if ci else "CI unavailable"
    return f"    {name:<10s} n={n:<5d}  mean={r['mean']:.4f}  {ci_bit}"


def _fmt_welch(label: str, wt: Optional[dict], spread: float) -> str:
    if wt is None:
        return f"    {label}: spread={spread:+.4f}  UNDERPOWERED - no p-value below n>={SIGNIFICANCE_N} per side"
    sig = "p<0.05" if wt["p"] < 0.05 else "n.s."
    return (f"    {label}: spread={spread:+.4f}  t={wt['t']:.2f}  p={wt['p']:.4f} ({sig})  "
            f"(n_buildup={wt['n_a']}, n_unwind={wt['n_b']})")


def run_real_data_readout(path: str, horizon_h: int) -> None:
    horizon_name = f"{horizon_h}h"
    print("=" * 84)
    print("WAGMI OI HYPOTHESIS HARNESS -- H4 MATURITY READOUT")
    print("(pre-registered method, data/copilot/PREREGISTRATION.md -- H4)")
    print("=" * 84)
    print(
        "\n*** NO SIGNIFICANCE CONCLUSION IS DRAWN BY THIS RUN. ***\n"
        "This prints descriptive independent-window counts and, only where the\n"
        f"n>={SIGNIFICANCE_N} independent-WINDOW bar is already cleared on BOTH sides of a\n"
        "comparison, the mechanically-gated stat -- always re-read the REGIME-GUARD\n"
        "caveat and the vol-control section below before treating any such number as\n"
        "an answer. The vol-clustering control is the CENTRAL requirement: a naive\n"
        "spread that does not survive it is NOT an OI-specific finding."
    )

    all_horizons = dict(CONTEXT_HORIZONS_H)
    all_horizons[horizon_name] = horizon_h
    raw = load_oi_log(path)
    print(f"\nfile: {path}")
    print(f"usable symbols (n_rows >= {MIN_ROWS_TO_USE}): {sorted(raw.keys()) or 'NONE'}")
    if not raw:
        print("\nNo usable symbols -- nothing to report. Expected on a fresh/empty collector.")
        return

    _hdr("SECTION 0 -- data inventory / outage-gap detection")
    for sym, df in raw.items():
        gaps_h = df["dt"].diff().dt.total_seconds().dropna() / 3600.0
        big = gaps_h[gaps_h > SEGMENT_GAP_H]
        span_days = (df["dt"].max() - df["dt"].min()).total_seconds() / 86400.0
        head = f"  {sym}: n={len(df):<6d} {df['dt'].min()} -> {df['dt'].max()}  raw_span={span_days:.1f}d"
        if len(big):
            print(f"{head}  segment-breaking gaps(>{SEGMENT_GAP_H}h): {len(big)} (largest={big.max():.1f}h / {big.max()/24:.1f}d)")
        else:
            print(f"{head}  no segment-breaking gaps (>{SEGMENT_GAP_H}h)")

    tail_thresh = estimate_tail_thresh(raw)
    if tail_thresh is not None:
        print(f"\nliving-value TAIL_THRESH (pooled {TAIL_PCTILE}th pctile of |tick log-return|): "
              f"{tail_thresh*100:.3f}% per tick (~{tail_thresh*1e4:.1f}bps)")
    else:
        print("\nTAIL_THRESH could not be estimated (insufficient data) -- tail-freq metric will be all-NaN.")

    feat_frames: Dict[str, pd.DataFrame] = {}
    for sym, df in raw.items():
        feat_frames[sym] = build_symbol_features(df, tail_thresh, all_horizons)
        n_state = feat_frames[sym]["oi_state"].notna().sum()
        print(f"  {sym}: {n_state} raw ticks with a valid oi_state "
              f"(after {OI_STATE_LOOKBACK_H}h causal lookback + {MIN_HIST_STATE}-obs minimum)")

    # ---- Independent-window construction (THE pseudoreplication fix) ----
    _hdr(f"SECTION 1 -- INDEPENDENT-WINDOW CONSTRUCTION (primary horizon = {horizon_name})")
    dd = window_dedup_report(feat_frames, horizon_name)
    print(f"raw eligible ticks (has a valid oi_state -- NOT the sample size): {dd['n_raw_eligible_ticks']}")
    print(f"independent windows (non-overlapping, {horizon_h}h-spaced, segment-aware -- the official N): "
          f"{dd['n_independent_windows']}")
    print(f"collapse ratio (raw eligible ticks per independent window): {dd['collapse_ratio']:.1f}x")
    print("\nindependent windows per symbol (distance to n>=30):")
    for sym, n in sorted(dd["per_symbol_n"].items(), key=lambda kv: -kv[1]):
        gap = max(0, SIGNIFICANCE_N - n)
        status = "CLEARS n>=30" if n >= SIGNIFICANCE_N else f"needs {gap} more"
        print(f"    {sym:<10s} n={n:<5d} {status}")
    if dd["dominance_flag"]:
        print(f"\n*** SINGLE-SYMBOL DOMINANCE WARNING: {dd['top_symbol']} carries "
              f"{dd['dominance_frac']*100:.1f}% of all pooled independent windows -- any pooled-looking "
              f"finding may really be a {dd['top_symbol']}-specific finding. ***")
    else:
        print(f"\n(no single symbol clears the {SINGLE_SYMBOL_DOMINANCE_WARN*100:.0f}% dominance-warning threshold: "
              f"top={dd['top_symbol']} at {dd['dominance_frac']*100:.1f}%)")

    print("\nautocorrelation diagnostic (why the independent-window collapse is necessary):")
    for sym, feat in feat_frames.items():
        s = feat["oi_roc_pctile"].dropna()
        ac1 = s.autocorr(lag=1) if len(s) > 30 else float("nan")
        print(f"    {sym:<10s} raw-tick oi_roc_pctile lag-1 autocorrelation = {ac1:.3f}  (n={len(s)}) "
              f"{'-- highly persistent, raw ticks are NOT independent' if not math.isnan(ac1) and ac1 > 0.9 else ''}")

    # ---- Macro-vol regime guard ----
    _hdr("SECTION 2 -- MACRO-VOL REGIME GUARD (data-derived, disclosed)")
    regimes = compute_macro_vol_regimes(feat_frames)
    span_days = (
        (max(f["dt"].max() for f in feat_frames.values()) - min(f["dt"].min() for f in feat_frames.values())).total_seconds() / 86400.0
        if feat_frames else 0.0
    )
    print(f"total raw collection span across usable symbols: {span_days:.1f} days "
          f"(MIN_SPAN_DAYS_FOR_TRUST={MIN_SPAN_DAYS_FOR_TRUST})")
    print(f"distinct macro-vol regimes detected (daily market-vol tercile persisting "
          f">={REGIME_MIN_DAYS}d): {regimes['regime_count']} (need >={MIN_REGIMES_FOR_TRUST})")
    if regimes.get("counts"):
        print(f"  regime day-counts: {dict(regimes['counts'])}")
    young = span_days < MIN_SPAN_DAYS_FOR_TRUST or regimes["regime_count"] < MIN_REGIMES_FOR_TRUST
    if young:
        print(
            f"\n*** YOUNG-SAMPLE / SINGLE-REGIME: span={span_days:.1f}d (need {MIN_SPAN_DAYS_FOR_TRUST}) and/or "
            f"regimes={regimes['regime_count']} (need {MIN_REGIMES_FOR_TRUST}). ***\n"
            "*** EVERY number below is tagged [YOUNG-SAMPLE/SINGLE-REGIME, PROVISIONAL] regardless of ***\n"
            "*** whether it numerically clears n>=30 -- per PREREGISTRATION.md, H4 requires BOTH the ***\n"
            "*** n>=30 bar AND this span/regime guard before anything is read as resolved. ***"
        )
    young_tag = "  [YOUNG-SAMPLE/SINGLE-REGIME, PROVISIONAL]" if young else ""

    windows = dd["all_windows"]
    per_symbol_windows = dd["per_symbol_windows"]

    for metric, null in (("vol_ratio", 1.0), ("tail_freq", None)):
        _hdr(f"SECTION 3 -- H4 NAIVE TEST (metric={metric}, horizon={horizon_name}) -- UNCONTROLLED, do not trust alone")
        naive = compute_naive_bucket_test(windows, metric, null=null)
        for state in ("unwind", "neutral", "buildup"):
            print(_fmt_bucket_line(state, naive[state]) + young_tag)
        print(_fmt_welch("buildup - unwind (naive, POSITIVE = buildup sees more forward risk)",
                          naive["buildup_minus_unwind"]["welch"], naive["buildup_minus_unwind"]["spread"]) + young_tag)

        _hdr(f"SECTION 4 -- H4 VOL-CLUSTERING CONTROL (metric={metric}, horizon={horizon_name}) -- THE CENTRAL TEST")
        print("Buildup-vs-unwind spread WITHIN trailing-vol terciles. A finding only counts as")
        print("OI-SPECIFIC if it survives here -- compare against the naive numbers above.\n")
        controlled = compute_vol_controlled_test(windows, metric)
        if controlled.get("edges"):
            print(f"trailing_vol24 tercile edges (independent-window set): "
                  f"low<={controlled['edges'][0]:.5f}  mid<={controlled['edges'][1]:.5f}  high=rest")
        for tname in ("low_vol", "mid_vol", "high_vol"):
            t = controlled["terciles"].get(tname)
            if not t:
                print(f"    {tname}: no data")
                continue
            print(f"    {tname}: n_buildup={t['n_buildup']:<4d} n_unwind={t['n_unwind']:<4d} "
                  f"buildup_mean={t['buildup_mean']:.4f} unwind_mean={t['unwind_mean']:.4f}")
            print("      " + _fmt_welch("spread", t["welch"], t["spread"]) + young_tag)
        print(f"\nterciles clearing n>={SIGNIFICANCE_N} on both sides: {controlled['n_terciles_cleared']}/3")
        if controlled["n_terciles_cleared"] == 0:
            print(f"  -> VOL-CONTROLLED TEST IS FULLY UNDERPOWERED for {metric} at this maturity -- "
                  "the central control cannot be evaluated yet, so NO OI-specific claim is possible.")

    # ---- Refute-yourself: cross-symbol consistency + era split ----
    _hdr("REFUTE-YOURSELF HOOK -- cross-symbol consistency (descriptive only, never gates)")
    cc = cross_symbol_consistency(per_symbol_windows, "vol_ratio")
    for sym, det in cc["details"].items():
        if det["spread"] is None:
            print(f"    {sym:<10s} too thin (n_buildup={det['n_buildup']}, n_unwind={det['n_unwind']})")
        else:
            print(f"    {sym:<10s} n_buildup={det['n_buildup']:<4d} n_unwind={det['n_unwind']:<4d} spread={det['spread']:+.4f}")
    if cc["n_symbols_with_signal"]:
        print(f"  -> {cc['n_agree']}/{cc['n_symbols_with_signal']} symbols with a computable spread agree on sign "
              f"(descriptive only -- NOT a significance test).")

    _hdr("REFUTE-YOURSELF HOOK -- era split (first half vs second half of the qualifying window set)")
    era = era_split_check(windows, "vol_ratio")
    for era_name, r in era.items():
        spread_str = f"{r['spread']:+.4f}" if r["spread"] is not None else "n/a (too thin)"
        print(f"    {era_name:<12s} n_buildup={r['n_buildup']:<4d} n_unwind={r['n_unwind']:<4d} spread={spread_str}")
    print("  (descriptive only, explicitly low-power -- a sign flip or single-half-only effect is a")
    print("   single-stretch artifact, not a stable pattern; agreement here does NOT itself confer significance.)")

    # ---- Context horizons: descriptive only, never gated ----
    _hdr(f"CONTEXT HORIZONS (descriptive only -- NOT independent-deduped, NOT gated, avoids multi-horizon fishing)")
    for name in CONTEXT_HORIZONS_H:
        vr_col = f"vol_ratio_{name}"
        rows = []
        for sym, feat in feat_frames.items():
            d = feat.dropna(subset=["oi_state", vr_col])
            for state in ("unwind", "neutral", "buildup"):
                sub = d[d["oi_state"] == state][vr_col]
                if len(sub):
                    rows.append((sym, state, len(sub), float(sub.mean())))
        print(f"  horizon={name} (raw-tick pooled means, for CONTEXT only -- never compared to a significance bar):")
        by_state_pool: Dict[str, List[float]] = defaultdict(list)
        for sym, state, n, mean in rows:
            by_state_pool[state].append(mean)
        for state in ("unwind", "neutral", "buildup"):
            vals = by_state_pool.get(state, [])
            if vals:
                print(f"    {state:<10s} pooled-across-symbols mean of per-symbol means = {np.mean(vals):.4f} "
                      f"(n_symbols={len(vals)})")

    # ---- When answerable? ----
    _hdr("WHEN WILL H4 BE ANSWERABLE? (rough linear projection, not a promise)")
    days_elapsed = max(span_days, 1e-6)
    print(f"Collection has run {days_elapsed:.1f} days so far. Projections below linearly extrapolate each")
    print("bucket's CURRENT accrual rate of INDEPENDENT WINDOWS -- real accrual is not guaranteed linear.\n")
    for sym, n in sorted(dd["per_symbol_n"].items(), key=lambda kv: -kv[1]):
        if n >= SIGNIFICANCE_N:
            print(f"    {sym:<10s} already clears n>={SIGNIFICANCE_N} independent windows ({n})" + young_tag)
        else:
            rate = n / days_elapsed
            eta = (SIGNIFICANCE_N / rate) if rate > 0 else float("inf")
            eta_str = f"~{eta:.0f} more day(s)" if math.isfinite(eta) else "no data yet to project from"
            print(f"    {sym:<10s} n={n:<4d} -> needs {SIGNIFICANCE_N - n} more, projected ETA {eta_str}")
    print(f"\nSeparately, the regime guard needs span>={MIN_SPAN_DAYS_FOR_TRUST}d "
          f"(currently {span_days:.1f}d) AND >={MIN_REGIMES_FOR_TRUST} distinct regimes "
          f"(currently {regimes['regime_count']}) before ANY number above -- even one that numerically "
          f"clears n>=30 -- is read as more than provisional.")

    print("\n" + "=" * 84)
    print("END OF READOUT -- no H4 significance conclusion has been asserted above.")
    print("=" * 84)


# ---------------------------------------------------------------------------
# SELF-TEST -- synthetic verification. Proves the METHOD (not any real
# finding): (a) independent-window collapse behaves as intended, (b) a
# continuous-segment break (e.g. the outage) resets the window clock, (c)
# a planted OI-SPECIFIC forward-vol effect is recovered AND SURVIVES the
# vol-tercile control, (d) a pure vol-clustering confound produces a
# misleading NAIVE spread that the control correctly KILLS, (e) both tests
# refuse to conclude below n=30 independent windows even on a "perfect"
# thin sample.
# ---------------------------------------------------------------------------

def _mk_row(symbol: str, dt: datetime, price: float, oi: float) -> dict:
    return {
        "timestamp": dt.isoformat(), "symbol": symbol, "funding_rate": 0.0,
        "open_interest": oi, "premium": 0.0, "volume_24h": 1.0, "price": price,
        "oi_volume_ratio": 1.0,
    }


def _rows_to_df(rows: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
    df["price"] = df["price"].astype(float)
    df["open_interest"] = df["open_interest"].astype(float)
    return df[["dt", "price", "open_interest"]]


def _gen_synthetic_series(
    rng: np.random.Generator,
    symbol: str,
    n_windows: int,
    window_h: float,
    cadence_min: float,
    regime_block_windows: int,
    sigma_levels: List[float],
    oi_effect_mult: float,
    confound_oi_with_regime: bool,
    start: datetime,
) -> List[dict]:
    """Generates raw OI+price TICK rows (same schema as the real collector,
    same code path as real data: it is fed through the identical
    build_symbol_features()/build_independent_windows() pipeline, never a
    shortcut). Walks window_h-hour blocks; each block gets an assigned
    macro-vol-regime sigma level (cycled through `sigma_levels` every
    `regime_block_windows` blocks, so multiple regimes are genuinely present
    -- required for the vol-tercile control to have something to control
    FOR) and an OI-state label (buildup/neutral/unwind) that drives a real
    OI drift over the block (so oi_roc_pctile is computed CAUSALLY by the
    real pipeline, never fabricated directly).

    oi_effect_mult > 1.0 (with confound_oi_with_regime=False) plants a
    GENUINE OI-specific forward-vol bump applied identically at every sigma
    level -- must survive the tercile control.

    confound_oi_with_regime=True (with oi_effect_mult=1.0, no true bump)
    instead biases the OI-state draw to correlate with the regime's sigma
    level (buildup more likely in the highest-sigma level, unwind in the
    lowest) -- a pure vol-clustering confound: naively, buildup looks
    "riskier" only because it coincides with high-vol stretches. The
    control must correctly kill this once vol level is held fixed."""
    price = 100.0
    oi = 1_000_000.0
    t = start
    rows: List[dict] = []
    n_ticks = max(1, int(window_h * 60 / cadence_min))
    n_levels = len(sigma_levels)
    prev_state = "neutral"
    # NOTE on timing alignment (found + fixed during selftest development):
    # the pipeline's oi_state at a window's picked (near block-START) row is
    # computed from the trailing 24h OI ROC, which mostly covers the
    # PRECEDING block, not the block whose ticks the forward-vol window is
    # about to observe. To plant an effect the pipeline can actually detect,
    # the sigma bump/confound below must be a function of the PREVIOUS
    # block's decided state (prev_state), applied to THIS block's ticks --
    # not the state decided for this block itself.
    for wi in range(n_windows):
        level_idx = (wi // regime_block_windows) % n_levels
        sigma_base = sigma_levels[level_idx]

        # Decide THIS block's OI-drift state. Confound case biases it toward
        # THIS block's own regime level (buildup more likely at the highest
        # sigma level) -- since the state decided here becomes causally
        # visible (via trailing OI ROC) at the START of the NEXT block, and
        # this block's regime level is highly correlated with the next
        # block's (same multi-block regime run except at a boundary), this
        # plants "OI state correlates with the vol regime that follows it"
        # without the generator needing to look ahead.
        if confound_oi_with_regime and n_levels > 1:
            frac = level_idx / (n_levels - 1)
            p_buildup = 0.15 + 0.55 * frac
            p_unwind = 0.15 + 0.55 * (1.0 - frac)
            tot = p_buildup + p_unwind
            if tot > 0.95:
                p_buildup *= 0.95 / tot
                p_unwind *= 0.95 / tot
        else:
            p_buildup = p_unwind = 1.0 / 3.0
        r = rng.random()
        if r < p_buildup:
            state, oi_drift = "buildup", 0.0025
        elif r < p_buildup + p_unwind:
            state, oi_drift = "unwind", -0.0025
        else:
            state, oi_drift = "neutral", 0.0

        # THE PLANTED BUMP (true-positive case only): applied to THIS
        # block's sigma based on the PREVIOUS block's state -- see alignment
        # note above.
        apply_bump = (prev_state == "buildup") and (not confound_oi_with_regime)
        sigma = sigma_base * (oi_effect_mult if apply_bump else 1.0)
        for _ in range(n_ticks):
            ret = rng.normal(0.0, sigma)
            price *= math.exp(ret)
            oi *= max(1e-6, 1.0 + oi_drift + rng.normal(0.0, 0.0005))
            oi = max(oi, 1000.0)
            rows.append(_mk_row(symbol, t, price, oi))
            t += timedelta(minutes=cadence_min)
        prev_state = state
    return rows


def _gen_confound_series(
    rng: np.random.Generator,
    symbol: str,
    n_windows: int,
    window_h: float,
    cadence_min: float,
    mu_log_sigma: float,
    phi: float,
    eps_std: float,
    start: datetime,
) -> List[dict]:
    """A DEDICATED generator for the vol-clustering-CONFOUND selftest
    (separate from `_gen_synthetic_series`'s discrete persistent-regime
    model, which is kept for the true-positive/regime-guard/collapse/gap
    checks -- that model works well there, but its oi_state reflects a
    percentile RANK over a rolling 5-day/120h window that spans MULTIPLE
    regime blocks, so it does not map cleanly 1:1 onto a single block's
    level -- exactly the kind of subtlety that made an early version of
    this confound generator leak a small, real, non-chance residual through
    the vol-tercile control instead of being fully absorbed by it).

    Here sigma follows a mean-reverting AR(1) process in log-space, updated
    once per block. Because sigma(k) (a) directly generates block k's own
    realized vol (which becomes the NEXT window's trailing_vol), (b) is used
    directly (same block, no other-block timing) to bias the OI-state draw
    for block k, and (c) determines block (k+1)'s expected sigma via the
    SAME AR(1) mean-reversion relationship that gives vol_ratio its
    regime-dependent conditional mean -- the confound (state <-> regime) and
    the vol_ratio bias (regime <-> forward/trailing ratio) are both DIRECT
    functions of the SAME block's sigma. This is the honest "OI buildup
    tends to coincide with elevated recent vol, and elevated vol tends to
    mean-revert (GARCH-style)" story pre-registered as H4's central failure
    mode -- and because both effects route through sigma(k) alone, a
    tercile-of-trailing-vol control (which is measuring sigma(k) with some
    estimation noise) should be able to fully absorb it."""
    price = 100.0
    oi = 1_000_000.0
    t = start
    rows: List[dict] = []
    n_ticks = max(1, int(window_h * 60 / cadence_min))
    log_sigma = mu_log_sigma
    stat_std = eps_std / math.sqrt(max(1e-9, 1.0 - phi ** 2))
    for _wi in range(n_windows):
        sigma = math.exp(log_sigma)
        # Sign convention: buildup is biased toward LOW-z (recently BELOW
        # -average vol) blocks. Combined with AR(1) mean reversion (a
        # below-average trailing vol tends to bounce UP toward the mean),
        # this makes buildup naively correlate with an ELEVATED forward/
        # trailing vol_ratio -- matching the DIRECTION of the real
        # (unvalidated) origin-script finding this harness guards against
        # (PREREGISTRATION.md H4: "buildup vol_ratio ~1.15"). The mechanism
        # being demonstrated (a real confound that the tercile control must
        # kill) does not depend on this sign choice -- it is fixed here
        # purely so the selftest output reads consistently with H4's
        # documented failure mode instead of its mirror image.
        z = (log_sigma - mu_log_sigma) / max(1e-9, stat_std)
        p_buildup = 0.05 + 0.90 / (1.0 + math.exp(3.0 * z))
        p_unwind = 0.05 + 0.90 / (1.0 + math.exp(-3.0 * z))
        tot = p_buildup + p_unwind
        if tot > 0.95:
            p_buildup *= 0.95 / tot
            p_unwind *= 0.95 / tot
        r = rng.random()
        if r < p_buildup:
            oi_drift = 0.0025
        elif r < p_buildup + p_unwind:
            oi_drift = -0.0025
        else:
            oi_drift = 0.0
        for _ in range(n_ticks):
            ret = rng.normal(0.0, sigma)
            price *= math.exp(ret)
            oi *= max(1e-6, 1.0 + oi_drift + rng.normal(0.0, 0.0005))
            oi = max(oi, 1000.0)
            rows.append(_mk_row(symbol, t, price, oi))
            t += timedelta(minutes=cadence_min)
        # advance the AR(1) sigma path for the NEXT block
        log_sigma = mu_log_sigma + phi * (log_sigma - mu_log_sigma) + rng.normal(0.0, eps_std)
    return rows


def selftest_independent_window_collapse() -> bool:
    rng = np.random.default_rng(20260805)
    rows = _gen_synthetic_series(
        rng, "SYNTH_COLLAPSE", n_windows=60, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=6, sigma_levels=[0.0008, 0.0015, 0.0025],
        oi_effect_mult=1.0, confound_oi_with_regime=False,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    df = _rows_to_df(rows)
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    windows = build_independent_windows(feat, PRIMARY_HORIZON_NAME, "SYNTH_COLLAPSE")
    n_win = len(windows)
    n_raw_eligible = int(feat["oi_state"].notna().sum())
    collapse_ratio = (n_raw_eligible / n_win) if n_win else float("nan")
    ok = (0 < n_win <= 60) and (collapse_ratio > 10)
    print(f"  [collapse] 60 blocks x 72 ticks -> raw_eligible_ticks={n_raw_eligible} "
          f"independent_windows={n_win} collapse_ratio={collapse_ratio:.1f}x "
          f"(expect <=60 windows, ratio well above 1x): {'PASS' if ok else 'FAIL'}")
    return ok


def selftest_outage_gap_creates_new_segment() -> bool:
    rng = np.random.default_rng(20260806)
    rows_a = _gen_synthetic_series(
        rng, "SYNTH_GAP", n_windows=20, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=5, sigma_levels=[0.0015], oi_effect_mult=1.0,
        confound_oi_with_regime=False, start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    last_dt = datetime.fromisoformat(rows_a[-1]["timestamp"])
    rows_b = _gen_synthetic_series(
        rng, "SYNTH_GAP", n_windows=20, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=5, sigma_levels=[0.0015], oi_effect_mult=1.0,
        confound_oi_with_regime=False, start=last_dt + timedelta(days=22),  # the known outage length
    )
    df = _rows_to_df(rows_a + rows_b)
    seg_id = build_continuous_segment_id(df["dt"], SEGMENT_GAP_H)
    n_segments = len(set(seg_id.tolist()))
    ok_segments = n_segments == 2
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    windows = build_independent_windows(feat, PRIMARY_HORIZON_NAME, "SYNTH_GAP")
    # Fewer than the full 40 blocks are expected (each side re-pays the
    # MIN_HIST_STATE/OI_STATE_LOOKBACK_H warmup cost after the gap) -- if the
    # gap were silently stitched, warmup would only be paid ONCE, not twice,
    # and the count would land implausibly close to 40.
    ok_warmup = 0 < len(windows) < 36
    result = ok_segments and ok_warmup
    print(f"  [outage-gap] 22-day synthetic gap -> segments detected={n_segments} (expect 2), "
          f"independent windows={len(windows)}/40 blocks (warmup re-paid both sides expected): "
          f"{'PASS' if result else 'FAIL'}")
    return result


def selftest_survives_control_true_positive() -> bool:
    rng = np.random.default_rng(20260803)
    rows = _gen_synthetic_series(
        rng, "SYNTH_OI_TRUE", n_windows=600, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=6, sigma_levels=[0.0008, 0.0015, 0.0025],
        oi_effect_mult=1.6, confound_oi_with_regime=False,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    df = _rows_to_df(rows)
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    windows = build_independent_windows(feat, PRIMARY_HORIZON_NAME, "SYNTH_OI_TRUE")

    naive = compute_naive_bucket_test(windows, "vol_ratio", null=1.0)
    controlled = compute_vol_controlled_test(windows, "vol_ratio")

    naive_wt = naive["buildup_minus_unwind"]["welch"]
    naive_ok = (naive_wt is not None and naive_wt["p"] < 0.05 and naive["buildup_minus_unwind"]["spread"] > 0)

    cleared = [v for v in controlled["terciles"].values() if v["welch"] is not None]
    controlled_ok = (
        len(cleared) >= 2
        and all(v["spread"] > 0 for v in cleared)
        and sum(1 for v in cleared if v["welch"]["p"] < 0.05) >= max(1, len(cleared) - 1)
    )
    print(f"  [true-positive] naive: n_windows={len(windows)} spread={naive['buildup_minus_unwind']['spread']:+.3f} "
          f"welch={naive_wt}: {'PASS' if naive_ok else 'FAIL'}")
    for name, v in controlled["terciles"].items():
        print(f"    tercile={name:<8s} n_buildup={v['n_buildup']:<4d} n_unwind={v['n_unwind']:<4d} "
              f"spread={v['spread']:+.3f} welch={v['welch']}")
    print(f"  [true-positive] controlled: {sum(1 for v in cleared if v['spread']>0)}/{len(cleared)} cleared terciles "
          f"positive-sign, {sum(1 for v in cleared if v['welch']['p']<0.05)}/{len(cleared)} significant: "
          f"{'PASS (planted OI-specific effect survives the vol control)' if controlled_ok else 'FAIL'}")
    return naive_ok and controlled_ok


def selftest_control_kills_vol_clustering_confound() -> bool:
    rng = np.random.default_rng(20260804)
    rows = _gen_confound_series(
        rng, "SYNTH_OI_CONFOUND", n_windows=1200, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        mu_log_sigma=math.log(0.0015), phi=0.5, eps_std=0.5,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    df = _rows_to_df(rows)
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    windows = build_independent_windows(feat, PRIMARY_HORIZON_NAME, "SYNTH_OI_CONFOUND")

    naive = compute_naive_bucket_test(windows, "vol_ratio", null=1.0)
    controlled = compute_vol_controlled_test(windows, "vol_ratio")

    naive_wt = naive["buildup_minus_unwind"]["welch"]
    naive_shows_false_positive = (
        naive_wt is not None and naive_wt["p"] < 0.05 and naive["buildup_minus_unwind"]["spread"] > 0
    )
    cleared = [v for v in controlled["terciles"].values() if v["welch"] is not None]
    controlled_quiet = (
        len(cleared) >= 2 and sum(1 for v in cleared if v["welch"]["p"] < 0.05) == 0
    )
    print(f"  [confound] naive: n_windows={len(windows)} spread={naive['buildup_minus_unwind']['spread']:+.3f} "
          f"welch={naive_wt} (expected: LOOKS like a real effect before control): "
          f"{'PASS (naive is fooled, as expected)' if naive_shows_false_positive else 'FAIL'}")
    for name, v in controlled["terciles"].items():
        print(f"    tercile={name:<8s} n_buildup={v['n_buildup']:<4d} n_unwind={v['n_unwind']:<4d} "
              f"spread={v['spread']:+.3f} welch={v['welch']}")
    print(f"  [confound] controlled: {sum(1 for v in cleared if v['welch']['p']<0.05)}/{len(cleared)} cleared "
          f"terciles significant: "
          f"{'PASS (control correctly stays quiet on the vol-clustering confound)' if controlled_quiet else 'FAIL'}")
    return naive_shows_false_positive and controlled_quiet


def selftest_refuses_below_n30() -> bool:
    rng = np.random.default_rng(555)
    rows = _gen_synthetic_series(
        rng, "SYNTH_THIN", n_windows=15, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=3, sigma_levels=[0.0008, 0.0025],
        oi_effect_mult=3.0, confound_oi_with_regime=False,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    df = _rows_to_df(rows)
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    windows = build_independent_windows(feat, PRIMARY_HORIZON_NAME, "SYNTH_THIN")
    naive = compute_naive_bucket_test(windows, "vol_ratio", null=1.0)
    controlled = compute_vol_controlled_test(windows, "vol_ratio")

    ok = len(windows) < 3 * SIGNIFICANCE_N
    for state in ("unwind", "neutral", "buildup"):
        if naive[state]["n"] >= SIGNIFICANCE_N:
            ok = False
        if naive[state]["n"] < SIGNIFICANCE_N and naive[state]["ci"] is not None:
            ok = False
    naive_welch_ok = naive["buildup_minus_unwind"]["welch"] is None
    controlled_ok = all(v["welch"] is None for v in controlled["terciles"].values())
    result = ok and naive_welch_ok and controlled_ok
    print(f"  [gating] n_independent_windows={len(windows)} (<{3*SIGNIFICANCE_N}) -> "
          f"naive buildup n={naive['buildup']['n']} ci={naive['buildup']['ci']}, "
          f"naive welch={naive['buildup_minus_unwind']['welch']}, "
          f"controlled all-terciles-None={controlled_ok}: {'PASS' if result else 'FAIL'}")
    return result


def selftest_regime_guard_detects_planted_regimes() -> bool:
    """Sanity-checks compute_macro_vol_regimes() itself: the true-positive
    generator plants 3 alternating sigma levels every 6 blocks (~6 days) --
    the data-derived regime detector should recover >=2 distinct regimes."""
    rng = np.random.default_rng(20260807)
    rows = _gen_synthetic_series(
        rng, "SYNTH_REGIME", n_windows=200, window_h=PRIMARY_HORIZON_H, cadence_min=20,
        regime_block_windows=6, sigma_levels=[0.0008, 0.0015, 0.0025],
        oi_effect_mult=1.0, confound_oi_with_regime=False,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    df = _rows_to_df(rows)
    feat = build_symbol_features(df, tail_thresh=None, horizons={PRIMARY_HORIZON_NAME: PRIMARY_HORIZON_H})
    regimes = compute_macro_vol_regimes({"SYNTH_REGIME": feat})
    ok = regimes["regime_count"] >= MIN_REGIMES_FOR_TRUST
    print(f"  [regime-guard] planted 3 alternating sigma levels -> detected regime_count="
          f"{regimes['regime_count']} (need >={MIN_REGIMES_FOR_TRUST}): {'PASS' if ok else 'FAIL'}")
    return ok


def run_selftest() -> int:
    print("=" * 84)
    print("SELF-TEST -- SYNTHETIC METHOD VERIFICATION (no real data touched)")
    print("=" * 84)
    print(
        "Proves the METHOD, not any live finding: independent-window collapse behaves\n"
        "correctly, a segment-breaking gap resets the window clock, a PLANTED\n"
        "OI-specific forward-vol effect is recovered and SURVIVES the vol-tercile\n"
        "control, a pure vol-clustering CONFOUND fools the naive test but is correctly\n"
        "KILLED by the control, the data-derived regime guard recovers planted regimes,\n"
        "and both tests refuse to compute a p-value/CI below n=30 independent windows\n"
        "even when the tiny-n pattern looks 'perfect'.\n"
    )
    results = []
    print("-- Independent-window collapse (pseudoreplication fix) --")
    results.append(selftest_independent_window_collapse())
    print("\n-- Outage-gap / continuous-segment handling --")
    results.append(selftest_outage_gap_creates_new_segment())
    print("\n-- Macro-vol regime guard recovers planted regimes --")
    results.append(selftest_regime_guard_detects_planted_regimes())
    print("\n-- Planted OI-specific effect: recovered AND survives vol control --")
    results.append(selftest_survives_control_true_positive())
    print("\n-- Vol-clustering confound: fools naive test, KILLED by control --")
    results.append(selftest_control_kills_vol_clustering_confound())
    print("\n-- Strict gating: refuses to conclude below n=30 --")
    results.append(selftest_refuses_below_n30())

    n_pass = sum(1 for r in results if r)
    n_total = len(results)
    print("\n" + "=" * 84)
    print(f"SELF-TEST RESULT: {n_pass}/{n_total} checks PASSED")
    print("=" * 84)
    return 0 if n_pass == n_total else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "WAGMI Co-Pilot OI hypothesis harness (H4: OI-buildup vs forward cascade-risk, "
            "vol-clustering controlled). Default: real-data maturity readout (no conclusions "
            "drawn). --selftest: synthetic method verification."
        )
    )
    ap.add_argument("--path", type=str, default=DEFAULT_PATH, help="Path to funding_oi_history.jsonl")
    ap.add_argument(
        "--horizon", type=int, default=PRIMARY_HORIZON_H,
        help=f"Primary GATED forward horizon in hours (default {PRIMARY_HORIZON_H})",
    )
    ap.add_argument("--selftest", action="store_true", help="Run synthetic method-verification suite and exit")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(run_selftest())
    else:
        run_real_data_readout(args.path, args.horizon)


if __name__ == "__main__":
    main()
