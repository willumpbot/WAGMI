#!/usr/bin/env python
"""
WAGMI Co-Pilot CONFLUENCE HYPOTHESIS ENGINE -- confluence_harness.py
=============================================================================
THE REUSABLE ENGINE for the CONFLUENCE research campaign (see
tools/copilot/CONFLUENCE_CAMPAIGN.md for the hypothesis space + methodology
this engine executes). This file does NOT contain hypotheses -- it contains
the machinery that tests EVERY hypothesis with IDENTICAL rigor, so a family
of dozens/hundreds of confluence ideas can be screened without the multiple-
comparisons problem silently manufacturing "edges" out of noise.

WHY THIS EXISTS: testing many conditional/confluence rules against history
is exactly the setup where p-hacking happens by default -- try enough rules
and some will look significant by chance alone. Three structural defenses
are built in, non-optional, always computed:
  1. PSEUDOREPLICATION control -- consecutive same-symbol triggers collapse
     into one independent EPISODE (same discipline as liq_hypothesis_harness.py
     and oi_hypothesis_harness.py) before any n/p-value is computed.
  2. OOS DISCIPLINE -- every hypothesis is scored on a TRAIN split and a
     held-out TEST split (temporal, same cutoff date for every symbol so
     it's a genuine forward holdout, not a per-symbol leak), plus an
     independent pre/post-era split. A "finding" is never read off the full
     sample.
  3. MULTIPLE-COMPARISONS layer -- run_campaign() takes the WHOLE hypothesis
     family, collects one p-value per test, applies Benjamini-Hochberg FDR,
     and only calls something a "survivor" if it (a) clears FDR on TRAIN and
     (b) independently clears p<0.05 on TEST with the SAME SIGN. This turns
     "we tested 200 ideas and 11 look good" into an honest number instead of
     a p-hacked one.

LIQUIDITY DIMENSION: every hypothesis can additionally be broken out by a
per-coin, per-day LIQUIDITY BUCKET (thin/mid/liquid), entry-time-safe,
computed from rolling dollar volume ranked cross-sectionally across the
loaded universe every bar. This lets the campaign ask "is this edge null on
BTC/SOL but alive on thin alts?" directly, with a MATCHED baseline (random
days from bars in the SAME bucket, not the whole symbol) so the bucket
comparison isn't confounded by mixing liquidity regimes into one baseline.
When a campaign turns on `with_liquidity_buckets`, each bucket-conditioned
test is added to the FDR family as ITS OWN test (never a free extra look).

SCORING MODEL: every forward return is UNLEVERED net expectancy -- 1x spot,
buy-and-hold from trigger bar to the horizon bar, no leverage/liquidation/
path modeling (that belongs to a downstream sizing/execution layer, not this
screening engine). Cost is NOT a flat round-trip fee -- it is keyed to the
triggering bar's own LIQUIDITY BUCKET (liquid ~12.5bps RT, mid ~32.5bps RT,
thin ~75bps RT midpoints, unknown-liquidity bars default to the thin/most-
conservative cost; see LIQUIDITY_COST_BPS_RT for the full disclosed
assumption). Every stat is reported BOTH gross (no cost) and net (cost-
adjusted) so a thin-alt hypothesis's edge is honestly judged against ITS
OWN, wider, cost hurdle -- p-values/FDR/OOS confirmation are always computed
on NET returns, the tradeable number.

READ-ONLY / STANDALONE: only reads files under bot/data/ (longtail OHLC,
cache OHLC, funding_oi_history.jsonl, liq_events.jsonl). No imports of llm/,
execution/, core/, strategies/. No Discord. No network calls. Never writes
to any file under data/ (only prints to stdout; --selftest and the smoke
test are pure computation).

RAM-LEAN: DataStore loads each symbol's OHLC ONCE and computes its indicator
columns once, cached in memory as compact pandas frames (a few MB total for
the whole universe). run_campaign() processes hypotheses SEQUENTIALLY and
retains only the compact per-hypothesis summary (HypothesisResult, a few KB)
across a run -- the large per-bar boolean masks and permutation arrays used
inside run_hypothesis() are local and freed on return. --batch N chunks a
large hypothesis list into batches of N, running gc.collect() between
batches, so a campaign of hundreds of hypotheses never holds more than one
batch's transient arrays in memory at once.

CLI:
    python tools/copilot/confluence_harness.py --inventory        # data-join feasibility report
    python tools/copilot/confluence_harness.py --list-indicators  # indicator/column reference for hypothesis authors
    python tools/copilot/confluence_harness.py --selftest         # synthetic method-verification suite
    python tools/copilot/confluence_harness.py --smoke            # tiny real-data join/compute smoke test (NO conclusions)
    python tools/copilot/confluence_harness.py --campaign specs.json [--batch 25] [--alpha 0.05] [--no-liquidity-fdr]
    python tools/copilot/confluence_harness.py --null-control 200 [--timeframe 1d]  # noise-hypothesis FDR proof

INTERFACE (for CONFLUENCE_CAMPAIGN.md authors -- python usage, not just CLI):
    from confluence_harness import DataStore, HypothesisSpec, Rule, run_hypothesis, run_campaign

    store = DataStore(universe="all", timeframe="1d")               # loads once
    spec = HypothesisSpec(
        name="bb_oversold_rsi_confluence",
        side="long",                                                 # "long" | "short"
        timeframe="1d",
        universe="all",                                               # or an explicit symbol list
        rules=[Rule("bb_pctb", "<", 0.1), Rule("rsi14", "<", 30)],    # ANDed by default
        min_agree=None,                                                # or an int -> OR-of-N-of-M confluence
        horizons=(1, 3, 5),                                            # forward days
    )
    result = run_hypothesis(spec, store)                              # HypothesisResult: .train/.test/.full/.pre_era/.post_era
    campaign = run_campaign([spec, ...], store)                       # CampaignResult: FDR table + survivors
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths (standalone -- no imports of bot internals)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DATA_DIR = os.path.join(BOT_DIR, "data")
LONGTAIL_DIR = os.path.join(DATA_DIR, "longtail", "ohlc")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
FUNDING_OI_PATH = os.path.join(DATA_DIR, "funding_oi_history.jsonl")
LIQ_EVENTS_PATH = os.path.join(DATA_DIR, "copilot", "liquidations", "liq_events.jsonl")

# ---------------------------------------------------------------------------
# LOCKED METHOD PARAMETERS -- disclosed, tunable via CLI/kwargs, never
# silently changed after looking at a result (same discipline as
# liq_hypothesis_harness.py / oi_hypothesis_harness.py).
# ---------------------------------------------------------------------------
MIN_N = 20                             # min INDEPENDENT events per split before ANY p-value is computed.
                                        # Lower than the tick-level harnesses' n>=30 because confluence
                                        # day-bar triggers are structurally rarer events; still a real,
                                        # disclosed floor -- never bypassed to manufacture significance.
TRAIN_FRACTION_DEFAULT = 0.70          # temporal train fraction of the loaded date range (by time, not row count)
ERA_SPLIT_DEFAULT = "2026-02-01"       # pre/post era cutoff (configurable)
DEDUP_GAP_DAYS_DEFAULT = 1.0           # same-symbol triggers within this many days collapse to ONE episode
PERM_ITERS_DEFAULT = 1000              # permutation-test resamples for the matched-baseline p-value
PERM_SEED = 1337                       # fixed seed -> reproducible p-values, never re-rolled to chase a result
FDR_ALPHA_DEFAULT = 0.05
SINGLE_SYMBOL_DOMINANCE_WARN = 0.50    # flag if one symbol carries more than this share of a split's events
CVAR_TAIL_FRAC = 0.05                  # worst-5% mean = CVaR proxy

BARS_PER_DAY = {"1d": 1, "1h": 24}

ROLL_WINDOW = 20                        # bars, for BB/support/resistance/volume-ratio/rvol
LIQUIDITY_SMOOTH_DAYS = 20              # rolling smoothing window (in DAYS, converted to bars per timeframe)
LIQUIDITY_THIN_CUTOFF = 1.0 / 3.0        # cross-sectional percentile rank cutoffs -> thin / mid / liquid terciles
LIQUIDITY_LIQUID_CUTOFF = 2.0 / 3.0

# ---------------------------------------------------------------------------
# TRADING COST MODEL -- unlevered, buy-and-hold-to-horizon (1x spot). Every
# forward return in this file is scored two ways: GROSS (raw price move,
# sign-flipped for shorts, no cost) and NET (gross minus a round-trip cost
# keyed to the SYMBOL'S OWN LIQUIDITY BUCKET AT ENTRY TIME). This is a
# disclosed ASSUMPTION, not measured execution data -- thin names get a
# materially wider cost hurdle than liquid ones (wider spreads/slippage),
# so a thin-alt "edge" has to clear a much higher bar before it's read as
# real. p-values, FDR, and OOS confirmation are all computed on NET returns
# (net is the tradeable, decision-relevant number); gross is always reported
# alongside it so the cost drag itself is visible, never hidden.
#   liquid (top tercile, e.g. BTC/SOL/majors): ~10-15bps RT -> midpoint 12.5bps
#   mid    (middle tercile)                  : ~25-40bps RT -> midpoint 32.5bps
#   thin   (bottom tercile, thin alts)        : ~50-100bps+ RT -> midpoint 75bps
# A bar with no liquidity_bucket yet (insufficient trailing history) uses the
# THIN (most conservative / highest-cost) assumption, never the cheapest --
# an unknown-liquidity bar must never look artificially profitable.
# ---------------------------------------------------------------------------
LIQUIDITY_COST_BPS_RANGE: Dict[str, Tuple[float, float]] = {
    "liquid": (10.0, 15.0),
    "mid": (25.0, 40.0),
    "thin": (50.0, 100.0),
}
LIQUIDITY_COST_BPS_RT: Dict[Optional[str], float] = {
    "liquid": 12.5,
    "mid": 32.5,
    "thin": 75.0,
    None: 75.0,
}


def _normalize_bucket(b: Any) -> Optional[str]:
    if b is None:
        return None
    if isinstance(b, float) and math.isnan(b):
        return None
    return b


def _cost_bps_for_bucket(bucket: Any) -> float:
    return LIQUIDITY_COST_BPS_RT.get(_normalize_bucket(bucket), LIQUIDITY_COST_BPS_RT[None])

FUNDING_Z_WINDOW = 50                   # readings (irregular cadence -- see inventory notes)
OI_ROC_LOOKBACK = 20                    # readings
LIQ_CASCADE_LOOKBACK_HOURS = 6.0
LIQ_EPISODE_GAP_SEC = 300               # same discipline as liq_hypothesis_harness.py DEFAULT_GAP_SEC

# Longtail alts confirmed present as of the last inventory pass (25 alts,
# discovered dynamically below via glob -- this list is documentation only).
_KNOWN_LONGTAIL = [
    "AAVE", "ADA", "APT", "ARB", "AVAX", "BCH", "CRV", "FARTCOIN", "LDO",
    "LINK", "LTC", "ONDO", "PAXG", "PENGU", "PUMP", "SUI", "TAO", "TRX",
    "UNI", "WLD", "XPL", "ZEC", "kBONK", "kPEPE", "kSHIB",
]
# Majors sourced from data/cache/{SYM}_{daily,1h}_420d.csv (NOT the 30d/60d/
# 220d variants -- those were found to be stale/gapped, see inventory notes).
MAJOR_CACHE_SYMBOLS = ["BTC", "SOL", "ETH", "HYPE", "XRP"]

INDICATOR_COLUMNS = [
    ("c", "close price"),
    ("ema20", "20-period EMA of close"),
    ("ema50", "50-period EMA of close"),
    ("ema_trend_up", "bool: ema20 > ema50"),
    ("rsi14", "Wilder RSI(14)"),
    ("bb_pctb", "Bollinger %B (20,2): 0=lower band, 1=upper band"),
    ("bb_z", "Bollinger z-score: (close - mid20) / std20"),
    ("support_dist", "(close - 20-bar prior low) / close, prior bars only (no lookahead)"),
    ("breakout", "bool: close > 20-bar prior high, prior bars only"),
    ("vol_ratio", "volume / 20-bar prior mean volume"),
    ("rvol20", "20-bar realized vol of returns (std of pct-change)"),
    ("high_vol_regime", "bool: rvol20 above its own trailing (expanding) 66th pct -- relative, not absolute"),
    ("rel_strength_rank", "cross-sectional pct rank (0-1) of 5-bar trailing return vs loaded universe, same-date"),
    ("funding_z", "z-score of funding_rate vs its own trailing window (majors + recent memes only)"),
    ("oi_roc", "pct change of open_interest over OI_ROC_LOOKBACK readings (majors + recent memes only)"),
    ("liq_cascade_flag", "bool: a liquidation episode ended within LIQ_CASCADE_LOOKBACK_HOURS before this bar"),
    ("liquidity_score", "rolling smoothed 24h-equivalent dollar volume (c*v), entry-time-safe"),
    ("liquidity_rank", "cross-sectional pct rank (0-1) of liquidity_score vs loaded universe, same-date (0=thinnest)"),
    ("liquidity_bucket", "'thin' | 'mid' | 'liquid' tercile of liquidity_rank, or None if insufficient history"),
]


# ===========================================================================
# LOADERS
# ===========================================================================

def discover_longtail_symbols() -> List[str]:
    import glob
    syms = set()
    for f in glob.glob(os.path.join(LONGTAIL_DIR, "*_1d.csv")):
        base = os.path.basename(f)
        syms.add(base[: -len("_1d.csv")])
    return sorted(syms)


def _read_csv_safe(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def load_ohlc(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Loads OHLC for `symbol`/`timeframe` from whichever source has it
    (longtail alt file, or majors' cache/_420d.csv), normalized to a
    canonical frame: columns dt (tz-aware UTC), o,h,l,c,v -- sorted,
    deduped, index reset. Returns None if not found. Never raises on a
    malformed row (rows that fail to parse are dropped)."""
    df = None
    longtail_path = os.path.join(LONGTAIL_DIR, f"{symbol}_{timeframe}.csv")
    if os.path.exists(longtail_path):
        raw = _read_csv_safe(longtail_path)
        if raw is not None and "dt_utc_iso" in raw.columns:
            df = pd.DataFrame({
                "dt": pd.to_datetime(raw["dt_utc_iso"], utc=True, errors="coerce"),
                "o": pd.to_numeric(raw["o"], errors="coerce"),
                "h": pd.to_numeric(raw["h"], errors="coerce"),
                "l": pd.to_numeric(raw["l"], errors="coerce"),
                "c": pd.to_numeric(raw["c"], errors="coerce"),
                "v": pd.to_numeric(raw["v"], errors="coerce"),
            })
    if df is None and symbol in MAJOR_CACHE_SYMBOLS:
        cache_key = "daily" if timeframe == "1d" else "1h"
        cache_path = os.path.join(CACHE_DIR, f"{symbol}_{cache_key}_420d.csv")
        raw = _read_csv_safe(cache_path)
        if raw is not None and "time" in raw.columns:
            df = pd.DataFrame({
                "dt": pd.to_datetime(raw["time"], utc=True, errors="coerce"),
                "o": pd.to_numeric(raw["open"], errors="coerce"),
                "h": pd.to_numeric(raw["high"], errors="coerce"),
                "l": pd.to_numeric(raw["low"], errors="coerce"),
                "c": pd.to_numeric(raw["close"], errors="coerce"),
                "v": pd.to_numeric(raw["volume"], errors="coerce"),
            })
    if df is None:
        return None
    df = df.dropna(subset=["dt", "c"]).drop_duplicates(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    return df if len(df) > 0 else None


def load_funding_oi() -> pd.DataFrame:
    """Reads data/funding_oi_history.jsonl once. Returns a frame with
    columns dt (tz-aware UTC), symbol, funding_rate, open_interest, premium,
    volume_24h, price, oi_volume_ratio, sorted by symbol,dt. Malformed lines
    are skipped."""
    rows = []
    if os.path.exists(FUNDING_OI_PATH):
        with open(FUNDING_OI_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not rows:
        return pd.DataFrame(columns=["dt", "symbol", "funding_rate", "open_interest", "premium",
                                      "volume_24h", "price", "oi_volume_ratio"])
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    keep = ["dt", "symbol", "funding_rate", "open_interest", "premium", "volume_24h", "price", "oi_volume_ratio"]
    for c in keep:
        if c not in df.columns:
            df[c] = np.nan
    df = df[keep].dropna(subset=["dt", "symbol"]).sort_values(["symbol", "dt"]).reset_index(drop=True)
    return df


def load_liq_episodes(gap_sec: int = LIQ_EPISODE_GAP_SEC) -> Dict[str, List[Tuple[pd.Timestamp, pd.Timestamp]]]:
    """Reads data/copilot/liquidations/liq_events.jsonl and collapses
    correlated partial-fill events into independent EPISODES per symbol
    (same pseudoreplication discipline as liq_hypothesis_harness.py: same-
    symbol events within `gap_sec` collapse to one episode). Returns
    {symbol: [(start, end), ...]} sorted by start. This is diagnostic/
    conditioning data (liq_cascade_flag), never itself the subject of a
    significance test in this file."""
    if not os.path.exists(LIQ_EVENTS_PATH):
        return {}
    by_symbol: Dict[str, List[pd.Timestamp]] = {}
    with open(LIQ_EVENTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym, ts = d.get("symbol"), d.get("ts_utc")
            if not sym or not ts:
                continue
            try:
                dt = pd.Timestamp(ts)
                if dt.tzinfo is None:
                    dt = dt.tz_localize("UTC")
                else:
                    dt = dt.tz_convert("UTC")
            except Exception:
                continue
            by_symbol.setdefault(sym, []).append(dt)

    episodes: Dict[str, List[Tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for sym, times in by_symbol.items():
        times = sorted(times)
        eps = []
        cur_start = cur_end = times[0]
        for t in times[1:]:
            if (t - cur_end).total_seconds() > gap_sec:
                eps.append((cur_start, cur_end))
                cur_start = t
            cur_end = t
        eps.append((cur_start, cur_end))
        episodes[sym] = eps
    return episodes


# ===========================================================================
# INDICATORS (all entry-time-safe: rolling windows use only bars up to and
# including the CURRENT bar for smoothing indicators (BB/RSI/EMA -- standard
# "live indicator reading" convention), and STRICTLY PRIOR bars (shift(1)
# first) for support/resistance/breakout/volume-ratio, so a breakout signal
# can never be tautologically satisfied by the triggering bar's own high.)
# ===========================================================================

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)  # no losses in window -> RSI 100, not NaN/inf
    return rsi


def compute_price_indicators(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]

    df["ema20"] = c.ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
    df["ema_trend_up"] = df["ema20"] > df["ema50"]

    df["rsi14"] = _rsi(c, 14)

    bb_mid = c.rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).mean()
    bb_std = c.rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).std(ddof=0)
    df["bb_pctb"] = (c - (bb_mid - 2 * bb_std)) / (4 * bb_std).replace(0.0, np.nan)
    df["bb_z"] = (c - bb_mid) / bb_std.replace(0.0, np.nan)

    prior_low20 = l.shift(1).rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).min()
    prior_high20 = h.shift(1).rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).max()
    df["support_dist"] = (c - prior_low20) / c
    df["breakout"] = c > prior_high20

    prior_vol_mean20 = v.shift(1).rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).mean()
    df["vol_ratio"] = v / prior_vol_mean20.replace(0.0, np.nan)

    ret1 = c.pct_change()
    df["rvol20"] = ret1.rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).std(ddof=0)
    thresh = df["rvol20"].expanding(min_periods=max(60, 3 * ROLL_WINDOW)).quantile(0.66)
    df["high_vol_regime"] = df["rvol20"] > thresh

    df["ret5"] = c.pct_change(5)  # used for cross-sectional rel-strength ranking

    dollar_vol = c * v
    n_smooth = LIQUIDITY_SMOOTH_DAYS * BARS_PER_DAY[timeframe]
    n_day_bars = BARS_PER_DAY[timeframe]
    dollar_vol_period = dollar_vol.rolling(n_day_bars, min_periods=1).sum()
    df["liquidity_score"] = dollar_vol_period.rolling(n_smooth, min_periods=max(5, n_smooth // 4)).mean()

    # forward raw returns (sign-agnostic; side flip + fee applied at stats time)
    for h_days in (1, 3, 5, 10):
        bars = h_days * BARS_PER_DAY[timeframe]
        df[f"fwd_raw_{h_days}"] = c.shift(-bars) / c - 1.0

    return df


def _attach_cross_sectional(frames: Dict[str, pd.DataFrame], source_col: str, rank_col: str) -> None:
    """Ranks `source_col` cross-sectionally across all symbols in `frames`,
    PER TIMESTAMP, using only that timestamp's own (already entry-time-safe)
    column values -- no future information crosses the rank. Mutates each
    frame in place, adding `rank_col` (0-1 pct rank, NaN where no peers with
    non-NaN values exist that day)."""
    if not frames:
        return
    wide = pd.DataFrame({sym: df.set_index("dt")[source_col] for sym, df in frames.items()})
    wide = wide.sort_index()
    ranks = wide.rank(axis=1, pct=True, na_option="keep")
    for sym, df in frames.items():
        r = ranks[sym].reindex(df["dt"]).reset_index(drop=True)
        df[rank_col] = r.values


def _attach_liquidity_bucket(frames: Dict[str, pd.DataFrame]) -> None:
    """liquidity_rank (continuous 0-1 pct rank, exposed as an indicator for
    direct Rule use) is kept as-is. liquidity_bucket is derived separately
    via RANK-POSITION terciles (not raw pct-rank threshold cuts): each row's
    non-NaN symbols are split into three near-equal-size groups by ordinal
    position. This avoids the boundary-tie artifact a pct-rank threshold cut
    has on small/round symbol counts (e.g. exactly 1/3 landing ON the cutoff)
    and guarantees a genuine ~even 3-way split of whatever universe is
    loaded, every day, entry-time-safe (uses only that day's own values)."""
    _attach_cross_sectional(frames, "liquidity_score", "liquidity_rank")
    if not frames:
        return
    wide = pd.DataFrame({sym: df.set_index("dt")["liquidity_score"] for sym, df in frames.items()}).sort_index()
    order_rank = wide.rank(axis=1, method="first", na_option="keep")  # 1..k distinct integer ranks per row
    count = wide.notna().sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        tercile = np.floor((order_rank.sub(1, axis=0)).mul(3, axis=0).div(count, axis=0))
    tercile = tercile.clip(upper=2)
    label_map = {0.0: "thin", 1.0: "mid", 2.0: "liquid"}
    bucket_wide = tercile.apply(lambda col: col.map(lambda x: label_map.get(x) if pd.notna(x) else None))
    for sym, df in frames.items():
        b = bucket_wide[sym].reindex(df["dt"]).reset_index(drop=True)
        df["liquidity_bucket"] = b.values


def _attach_rel_strength(frames: Dict[str, pd.DataFrame]) -> None:
    _attach_cross_sectional(frames, "ret5", "rel_strength_rank")


def _attach_funding_oi(df: pd.DataFrame, funding_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = df.copy()
    df["funding_z"] = np.nan
    df["oi_roc"] = np.nan
    sub = funding_df[funding_df["symbol"] == symbol].sort_values("dt")
    if len(sub) < 5:
        return df
    sub = sub.copy()
    fr = sub["funding_rate"]
    sub["funding_z"] = (fr - fr.rolling(FUNDING_Z_WINDOW, min_periods=10).mean()) / \
                        fr.rolling(FUNDING_Z_WINDOW, min_periods=10).std(ddof=0).replace(0.0, np.nan)
    sub["oi_roc"] = sub["open_interest"].pct_change(OI_ROC_LOOKBACK)
    sub = sub[["dt", "funding_z", "oi_roc"]].dropna(subset=["dt"])
    # merge_asof(direction="backward"): only funding rows AT OR BEFORE the bar
    # time are visible to that bar -- no lookahead.
    df = df.sort_values("dt")
    merged = pd.merge_asof(df, sub, on="dt", direction="backward", suffixes=("", "_f"))
    df["funding_z"] = merged["funding_z_f"] if "funding_z_f" in merged.columns else merged["funding_z"]
    df["oi_roc"] = merged["oi_roc_f"] if "oi_roc_f" in merged.columns else merged["oi_roc"]
    return df.reset_index(drop=True)


def _attach_liq_flag(df: pd.DataFrame, episodes: List[Tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    df = df.copy()
    if not episodes:
        df["liq_cascade_flag"] = False
        return df
    ends = pd.Series(sorted(e for _, e in episodes))
    ends_df = pd.DataFrame({"dt": ends, "_end": ends})
    df = df.sort_values("dt")
    merged = pd.merge_asof(df, ends_df, on="dt", direction="backward",
                            tolerance=pd.Timedelta(hours=LIQ_CASCADE_LOOKBACK_HOURS))
    df["liq_cascade_flag"] = merged["_end"].notna().values
    return df.reset_index(drop=True)


# ===========================================================================
# DATA STORE -- loads each symbol once, computes indicators once, cached.
# ===========================================================================

class DataStore:
    def __init__(self, universe: Union[str, Sequence[str]] = "all", timeframe: str = "1d",
                 include_funding_oi: bool = True, include_liq_flag: bool = True,
                 verbose: bool = False):
        self.timeframe = timeframe
        if universe == "all":
            symbols = discover_longtail_symbols() + MAJOR_CACHE_SYMBOLS
        else:
            symbols = list(universe)
        self.requested_universe = symbols

        funding_df = load_funding_oi() if include_funding_oi else pd.DataFrame()
        liq_eps = load_liq_episodes() if include_liq_flag else {}

        frames: Dict[str, pd.DataFrame] = {}
        skipped: List[str] = []
        for sym in symbols:
            raw = load_ohlc(sym, timeframe)
            if raw is None or len(raw) < ROLL_WINDOW + 5:
                skipped.append(sym)
                continue
            f = compute_price_indicators(raw, timeframe)
            if include_funding_oi and not funding_df.empty:
                f = _attach_funding_oi(f, funding_df, sym)
            else:
                f["funding_z"] = np.nan
                f["oi_roc"] = np.nan
            if include_liq_flag:
                f = _attach_liq_flag(f, liq_eps.get(sym, []))
            else:
                f["liq_cascade_flag"] = False
            frames[sym] = f
            if verbose:
                print(f"  loaded {sym:<10s} {timeframe:<3s} n={len(f):<5d} "
                      f"{f['dt'].iloc[0].date()} -> {f['dt'].iloc[-1].date()}")

        _attach_rel_strength(frames)
        _attach_liquidity_bucket(frames)

        self.frames = frames
        self.skipped = skipped
        if frames:
            all_min = min(f["dt"].iloc[0] for f in frames.values())
            all_max = max(f["dt"].iloc[-1] for f in frames.values())
            self.global_start, self.global_end = all_min, all_max
        else:
            self.global_start = self.global_end = None

    def symbols(self) -> List[str]:
        return list(self.frames.keys())

    def get(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.frames.get(symbol)

    def resolve_universe(self, universe: Union[str, Sequence[str]]) -> List[str]:
        if universe == "all":
            return self.symbols()
        return [s for s in universe if s in self.frames]

    def split_date(self, train_frac: float = TRAIN_FRACTION_DEFAULT) -> pd.Timestamp:
        span = (self.global_end - self.global_start)
        return self.global_start + span * train_frac


# ===========================================================================
# HYPOTHESIS SPEC
# ===========================================================================

_OPS: Dict[str, Callable[[pd.Series, float], pd.Series]] = {
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
}


@dataclass
class Rule:
    indicator: str
    op: str
    value: float

    def mask(self, df: pd.DataFrame) -> pd.Series:
        if self.indicator not in df.columns:
            return pd.Series(False, index=df.index)
        fn = _OPS.get(self.op)
        if fn is None:
            raise ValueError(f"unknown op {self.op!r}")
        col = df[self.indicator]
        m = fn(col, self.value)
        return m.fillna(False).astype(bool)


@dataclass
class HypothesisSpec:
    name: str
    side: str                                  # "long" | "short"
    timeframe: str = "1d"
    universe: Union[str, Sequence[str]] = "all"
    rules: List[Rule] = field(default_factory=list)
    min_agree: Optional[int] = None            # None -> AND all rules; else -> >=N of len(rules) true
    horizons: Tuple[int, ...] = (1, 3, 5)
    dedup_gap_days: float = DEDUP_GAP_DAYS_DEFAULT
    precomputed_mask: Optional[Dict[str, np.ndarray]] = None  # advanced/null-control: bypass rules entirely
    condition_fn: Optional[Callable[[pd.DataFrame], pd.Series]] = None  # advanced: custom vectorized condition

    def primary_horizon(self) -> int:
        return self.horizons[0]

    def build_mask(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if self.precomputed_mask is not None:
            arr = self.precomputed_mask.get(symbol)
            if arr is None:
                return pd.Series(False, index=df.index)
            return pd.Series(arr, index=df.index).astype(bool)
        if self.condition_fn is not None:
            return self.condition_fn(df).fillna(False).astype(bool)
        if not self.rules:
            return pd.Series(False, index=df.index)
        masks = [r.mask(df) for r in self.rules]
        if self.min_agree is None:
            out = masks[0]
            for m in masks[1:]:
                out = out & m
            return out
        agree = sum(m.astype(int) for m in masks)
        return agree >= self.min_agree


# ===========================================================================
# STATS
# ===========================================================================

@dataclass
class HorizonStats:
    n: int
    wr_gross: Optional[float]
    wr_net: Optional[float]
    mean_gross: Optional[float]
    mean_net: Optional[float]
    median_gross: Optional[float]
    median_net: Optional[float]
    cvar5_gross: Optional[float]
    cvar5_net: Optional[float]
    p_value: Optional[float]                # permutation p-value on NET returns vs matched NET baseline
    baseline_n: int
    baseline_mean_net: Optional[float]
    baseline_mean_gross: Optional[float]

    @property
    def underpowered(self) -> bool:
        return self.n < MIN_N

    # backward/convenience alias -- "the" edge number downstream code reads
    # is net-of-realistic-cost (mean_net), never gross.
    @property
    def wr(self) -> Optional[float]:
        return self.wr_net


@dataclass
class SplitStats:
    split_name: str
    n_events: int
    n_symbols: int
    dominance_frac: float
    dominance_flag: bool
    per_horizon: Dict[int, HorizonStats]
    by_liquidity: Dict[str, Dict[int, HorizonStats]] = field(default_factory=dict)


@dataclass
class HypothesisResult:
    spec_name: str
    side: str
    universe: List[str]
    n_universe_symbols: int
    n_events_total_raw: int          # pre-dedup trigger-bar count (diagnostic only, never used as N)
    full: SplitStats
    train: SplitStats
    test: SplitStats
    pre_era: SplitStats
    post_era: SplitStats
    split_date: pd.Timestamp
    era_split_date: pd.Timestamp
    diagnostics: Dict[str, Any]


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _permutation_p_value(a: np.ndarray, b: np.ndarray, iters: int, rng: np.random.Generator,
                          max_baseline: int = 2000) -> Optional[float]:
    """Two-sided permutation p-value for H0: mean(a) == mean(b), where `a` is
    the event-return sample and `b` is the matched-baseline pool. Vectorized
    (no Python-level loop over iters). `b` is subsampled to `max_baseline` if
    larger, for bounded runtime/memory -- documented, not silently dropped."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return None
    if len(b) > max_baseline:
        idx = rng.choice(len(b), size=max_baseline, replace=False)
        b = b[idx]
    n_a = len(a)
    pooled = np.concatenate([a, b])
    n = len(pooled)
    obs = abs(a.mean() - b.mean())
    keys = rng.random((iters, n))
    order = np.argsort(keys, axis=1)
    idx_a = order[:, :n_a]
    idx_b = order[:, n_a:]
    vals_a = pooled[idx_a]
    vals_b = pooled[idx_b]
    diffs = np.abs(vals_a.mean(axis=1) - vals_b.mean(axis=1))
    p = (np.sum(diffs >= obs - 1e-15) + 1) / (iters + 1)
    return float(p)


def _event_returns_for_symbol(df: pd.DataFrame, idxs: List[int], horizon: int,
                               side: str) -> Tuple[List[float], List[float], List[Optional[str]]]:
    """For each idx in `idxs`, returns (gross, net, bucket) using the FORWARD
    raw return and THAT bar's own liquidity_bucket-keyed cost. Drops idx
    where the forward return is unavailable (right-censored). Parallel lists,
    aligned and same length (post-drop)."""
    col = f"fwd_raw_{horizon}"
    if col not in df.columns or not idxs:
        return [], [], []
    fwd = df[col].values
    buckets = df["liquidity_bucket"].values if "liquidity_bucket" in df.columns else [None] * len(df)
    gross_l, net_l, bucket_l = [], [], []
    for i in idxs:
        raw = fwd[i]
        if pd.isna(raw):
            continue
        gross = -raw if side == "short" else raw
        b = _normalize_bucket(buckets[i])
        net = gross - _cost_bps_for_bucket(b) / 10000.0
        gross_l.append(float(gross))
        net_l.append(float(net))
        bucket_l.append(b)
    return gross_l, net_l, bucket_l


def _dedup_trigger_indices(idxs: np.ndarray, gap_bars: int) -> np.ndarray:
    """Collapses a run of consecutive (within `gap_bars`) trigger indices for
    ONE symbol into a single independent event, keeping the FIRST index of
    each run -- the pseudoreplication fix (mirrors liq_hypothesis_harness.py
    episode collapse, applied to bar-index runs instead of raw timestamps)."""
    if len(idxs) == 0:
        return idxs
    idxs = np.sort(idxs)
    kept = [idxs[0]]
    for i in idxs[1:]:
        if i - kept[-1] > gap_bars:
            kept.append(i)
    return np.array(kept)


def _extract_events_for_symbol(spec: HypothesisSpec, df: pd.DataFrame, symbol: str) -> List[int]:
    mask = spec.build_mask(df, symbol)
    idxs = np.where(mask.values)[0]
    gap_bars = max(1, round(spec.dedup_gap_days * BARS_PER_DAY[spec.timeframe]))
    return list(_dedup_trigger_indices(idxs, gap_bars))


def _baseline_pool_for_symbol(df: pd.DataFrame, event_idxs: List[int], horizon: int, side: str,
                               bucket_filter: Optional[str] = None,
                               gap_bars: int = 1) -> Tuple[List[float], List[float]]:
    """Non-event bars for this symbol (excluding a `gap_bars` buffer around
    each event, so the baseline isn't contaminated by the same signal state),
    optionally restricted to a liquidity bucket -- a MATCHED comparison
    population for the permutation test. Each baseline bar is costed by ITS
    OWN contemporaneous liquidity_bucket (same convention as events), so a
    bucket-filtered baseline is apples-to-apples on both return AND cost.
    Returns (gross_list, net_list)."""
    n = len(df)
    excluded = set()
    for i in event_idxs:
        for j in range(max(0, i - gap_bars), min(n, i + gap_bars + 1)):
            excluded.add(j)
    col = f"fwd_raw_{horizon}"
    if col not in df.columns:
        return [], []
    fwd = df[col].values
    buckets = df["liquidity_bucket"].values if "liquidity_bucket" in df.columns else [None] * n
    gross_out, net_out = [], []
    for i in range(n):
        if i in excluded:
            continue
        if pd.isna(fwd[i]):
            continue
        b = _normalize_bucket(buckets[i])
        if bucket_filter is not None and b != bucket_filter:
            continue
        raw = -fwd[i] if side == "short" else fwd[i]
        gross_out.append(float(raw))
        net_out.append(float(raw - _cost_bps_for_bucket(b) / 10000.0))
    return gross_out, net_out


def _horizon_stats(event_gross: List[float], event_net: List[float], baseline_gross: List[float],
                    baseline_net: List[float], rng: np.random.Generator, iters: int) -> HorizonStats:
    n = len(event_net)
    if n == 0:
        return HorizonStats(n=0, wr_gross=None, wr_net=None, mean_gross=None, mean_net=None,
                             median_gross=None, median_net=None, cvar5_gross=None, cvar5_net=None,
                             p_value=None, baseline_n=len(baseline_net), baseline_mean_net=None,
                             baseline_mean_gross=None)
    ag, an = np.array(event_gross, dtype=float), np.array(event_net, dtype=float)
    k = max(1, int(math.ceil(CVAR_TAIL_FRAC * n)))
    baseline_mean_net = float(np.mean(baseline_net)) if baseline_net else None
    baseline_mean_gross = float(np.mean(baseline_gross)) if baseline_gross else None
    p_value = None
    if n >= MIN_N and baseline_net:
        # p-value is always computed on NET returns -- the tradeable,
        # cost-adjusted number -- never on gross.
        p_value = _permutation_p_value(an, np.array(baseline_net, dtype=float), iters, rng)
    return HorizonStats(
        n=n, wr_gross=float((ag > 0).mean()), wr_net=float((an > 0).mean()),
        mean_gross=float(ag.mean()), mean_net=float(an.mean()),
        median_gross=float(np.median(ag)), median_net=float(np.median(an)),
        cvar5_gross=float(np.sort(ag)[:k].mean()), cvar5_net=float(np.sort(an)[:k].mean()),
        p_value=p_value, baseline_n=len(baseline_net),
        baseline_mean_net=baseline_mean_net, baseline_mean_gross=baseline_mean_gross,
    )


def _build_split_stats(split_name: str, events_by_symbol: Dict[str, List[int]],
                        frames: Dict[str, pd.DataFrame], side: str, horizons: Tuple[int, ...],
                        rng: np.random.Generator, iters: int,
                        compute_liquidity: bool = True) -> SplitStats:
    n_events = sum(len(v) for v in events_by_symbol.values())
    n_symbols = sum(1 for v in events_by_symbol.values() if v)
    per_symbol_counts = {s: len(v) for s, v in events_by_symbol.items() if v}
    dominance_frac = (max(per_symbol_counts.values()) / n_events) if n_events else 0.0
    dominance_flag = dominance_frac >= SINGLE_SYMBOL_DOMINANCE_WARN

    per_horizon: Dict[int, HorizonStats] = {}
    by_liquidity: Dict[str, Dict[int, HorizonStats]] = {"thin": {}, "mid": {}, "liquid": {}}

    for h in horizons:
        all_event_gross: List[float] = []
        all_event_net: List[float] = []
        all_baseline_gross: List[float] = []
        all_baseline_net: List[float] = []
        bucket_event_gross = {"thin": [], "mid": [], "liquid": []}
        bucket_event_net = {"thin": [], "mid": [], "liquid": []}
        bucket_baseline_gross = {"thin": [], "mid": [], "liquid": []}
        bucket_baseline_net = {"thin": [], "mid": [], "liquid": []}
        for sym, idxs in events_by_symbol.items():
            if not idxs:
                continue
            df = frames[sym]
            g_l, n_l, b_l = _event_returns_for_symbol(df, idxs, h, side)
            all_event_gross.extend(g_l)
            all_event_net.extend(n_l)
            bg, bn = _baseline_pool_for_symbol(df, idxs, h, side)
            all_baseline_gross.extend(bg)
            all_baseline_net.extend(bn)
            if compute_liquidity:
                for g, ne, b in zip(g_l, n_l, b_l):
                    if b in bucket_event_gross:
                        bucket_event_gross[b].append(g)
                        bucket_event_net[b].append(ne)
                for b in ("thin", "mid", "liquid"):
                    bg2, bn2 = _baseline_pool_for_symbol(df, idxs, h, side, bucket_filter=b)
                    bucket_baseline_gross[b].extend(bg2)
                    bucket_baseline_net[b].extend(bn2)
        per_horizon[h] = _horizon_stats(all_event_gross, all_event_net, all_baseline_gross, all_baseline_net,
                                         rng, iters)
        if compute_liquidity:
            for b in ("thin", "mid", "liquid"):
                by_liquidity[b][h] = _horizon_stats(bucket_event_gross[b], bucket_event_net[b],
                                                     bucket_baseline_gross[b], bucket_baseline_net[b], rng, iters)

    return SplitStats(split_name, n_events, n_symbols, dominance_frac, dominance_flag, per_horizon,
                       by_liquidity if compute_liquidity else {})


def run_hypothesis(spec: HypothesisSpec, store: DataStore,
                    train_frac: float = TRAIN_FRACTION_DEFAULT,
                    split_date: Optional[pd.Timestamp] = None,
                    era_split: str = ERA_SPLIT_DEFAULT,
                    perm_iters: int = PERM_ITERS_DEFAULT,
                    seed: int = PERM_SEED,
                    compute_liquidity: bool = True) -> HypothesisResult:
    universe = store.resolve_universe(spec.universe)
    rng = np.random.default_rng(seed)
    sd = split_date if split_date is not None else store.split_date(train_frac)
    era_dt = pd.Timestamp(era_split, tz="UTC")

    events_all: Dict[str, List[int]] = {}
    events_train: Dict[str, List[int]] = {}
    events_test: Dict[str, List[int]] = {}
    events_pre: Dict[str, List[int]] = {}
    events_post: Dict[str, List[int]] = {}
    n_raw_triggers = 0

    for sym in universe:
        df = store.get(sym)
        if df is None:
            continue
        mask = spec.build_mask(df, sym)
        n_raw_triggers += int(mask.sum())
        idxs = _extract_events_for_symbol(spec, df, sym)
        events_all[sym] = idxs
        # Vectorized, tz-aware comparisons on the Series itself (avoids the
        # tz-naive np.datetime64 coercion warning from comparing element-wise
        # against a raw .values array).
        is_train = (df["dt"] < sd).values
        is_pre = (df["dt"] < era_dt).values
        train_idx = [i for i in idxs if is_train[i]]
        test_idx = [i for i in idxs if not is_train[i]]
        pre_idx = [i for i in idxs if is_pre[i]]
        post_idx = [i for i in idxs if not is_pre[i]]
        events_train[sym] = train_idx
        events_test[sym] = test_idx
        events_pre[sym] = pre_idx
        events_post[sym] = post_idx

    full = _build_split_stats("full", events_all, store.frames, spec.side, spec.horizons, rng, perm_iters, compute_liquidity)
    train = _build_split_stats("train", events_train, store.frames, spec.side, spec.horizons, rng, perm_iters, compute_liquidity)
    test = _build_split_stats("test", events_test, store.frames, spec.side, spec.horizons, rng, perm_iters, compute_liquidity)
    pre_era = _build_split_stats("pre_era", events_pre, store.frames, spec.side, spec.horizons, rng, perm_iters, compute_liquidity)
    post_era = _build_split_stats("post_era", events_post, store.frames, spec.side, spec.horizons, rng, perm_iters, compute_liquidity)

    diagnostics = {
        "n_raw_triggers": n_raw_triggers,
        "collapse_ratio": (n_raw_triggers / full.n_events) if full.n_events else None,
        "symbols_with_events": [s for s, v in events_all.items() if v],
        "symbols_zero_events": [s for s, v in events_all.items() if not v],
    }

    return HypothesisResult(
        spec_name=spec.name, side=spec.side, universe=universe, n_universe_symbols=len(universe),
        n_events_total_raw=n_raw_triggers, full=full, train=train, test=test,
        pre_era=pre_era, post_era=post_era, split_date=sd, era_split_date=era_dt, diagnostics=diagnostics,
    )


# ===========================================================================
# LIQUIDITY MONOTONICITY READOUT
# ===========================================================================

def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 2:
        return None
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def liquidity_monotonicity(split: SplitStats, horizon: int, metric: str = "mean_net",
                            min_n: int = MIN_N) -> Dict[str, Any]:
    """Does the hypothesis's edge STRENGTHEN as liquidity decreases
    (liquid -> mid -> thin)? Requires each bucket to individually clear
    min_n before it counts. Direction convention: `metric` is already in
    profit units for either side (net_return sign already flips for
    shorts), so 'increasing thin>mid>liquid' always means 'edge gets
    stronger down the liquidity ladder', matching the owner's thesis
    framing regardless of hypothesis side."""
    order = ["liquid", "mid", "thin"]
    pts = []
    for b in order:
        hs = split.by_liquidity.get(b, {}).get(horizon)
        if hs is not None and hs.n >= min_n and getattr(hs, metric) is not None:
            pts.append((b, getattr(hs, metric)))
    if len(pts) < 2:
        return {"status": "insufficient_data", "buckets_available": [b for b, _ in pts]}
    vals = [v for _, v in pts]
    is_monotonic = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
    is_strict = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    rho = _pearson(list(range(len(vals))), vals)
    return {
        "status": "ok",
        "buckets_available": [b for b, _ in pts],
        "values": {b: v for b, v in pts},
        "monotonic_liquidity_ladder": is_monotonic,
        "strictly_monotonic": is_strict,
        "correlation": rho,
    }


# ===========================================================================
# MULTIPLE-COMPARISONS LAYER (Benjamini-Hochberg FDR)
# ===========================================================================

def benjamini_hochberg(pvalues: List[Optional[float]], alpha: float = FDR_ALPHA_DEFAULT) -> List[bool]:
    """Standard BH step-up procedure. Entries with p_value=None (underpowered
    / not tested) never participate and are never rejected. Returns a
    reject-null boolean list aligned to the input order."""
    n = len(pvalues)
    idxs = [i for i, p in enumerate(pvalues) if p is not None]
    m = len(idxs)
    reject = [False] * n
    if m == 0:
        return reject
    idxs_sorted = sorted(idxs, key=lambda i: pvalues[i])
    max_k = 0
    for rank, i in enumerate(idxs_sorted, start=1):
        if pvalues[i] <= (rank / m) * alpha:
            max_k = rank
    for rank, i in enumerate(idxs_sorted, start=1):
        if rank <= max_k:
            reject[i] = True
    return reject


@dataclass
class CampaignEntry:
    test_id: str                # spec.name, or "spec.name::bucket" for bucket-conditioned tests
    spec_name: str
    bucket: Optional[str]       # None for the full-universe test
    horizon: int
    train_n: int
    train_p: Optional[float]
    train_mean_net: Optional[float]
    train_mean_gross: Optional[float]
    test_n: int
    test_p: Optional[float]
    test_mean_net: Optional[float]
    test_mean_gross: Optional[float]
    fdr_survivor: bool = False
    confirmed: bool = False
    dominance_flag: bool = False


@dataclass
class CampaignResult:
    alpha: float
    n_tested: int
    expected_false_positives: float
    n_surviving_fdr: int
    n_confirmed: int
    entries: List[CampaignEntry]
    results_by_spec: Dict[str, HypothesisResult]


def run_campaign(specs: List[HypothesisSpec], store: DataStore,
                  alpha: float = FDR_ALPHA_DEFAULT, batch_size: Optional[int] = None,
                  with_liquidity_buckets: bool = True, perm_iters: int = PERM_ITERS_DEFAULT,
                  seed: int = PERM_SEED, verbose: bool = False, **run_kwargs) -> CampaignResult:
    """Runs the WHOLE hypothesis family, builds the FDR entry list, and
    reports honest multiple-comparisons-corrected survivors. If
    `with_liquidity_buckets`, each hypothesis contributes 4 tests to the
    family (full + thin + mid + liquid) instead of 1 -- each bucket-
    conditioned test is counted as ITS OWN comparison, never a free extra
    look. --batch chunks `specs` so only compact HypothesisResult/CampaignEntry
    objects are retained across batches; large per-hypothesis boolean masks
    and permutation arrays are freed (gc.collect()) between batches."""
    entries: List[CampaignEntry] = []
    results_by_spec: Dict[str, HypothesisResult] = {}

    batches = [specs] if not batch_size else [specs[i:i + batch_size] for i in range(0, len(specs), batch_size)]
    for bi, batch in enumerate(batches):
        if verbose:
            print(f"  [campaign] batch {bi + 1}/{len(batches)} ({len(batch)} hypotheses)")
        for spec in batch:
            res = run_hypothesis(spec, store, perm_iters=perm_iters, seed=seed,
                                  compute_liquidity=with_liquidity_buckets, **run_kwargs)
            results_by_spec[spec.name] = res
            h = spec.primary_horizon()

            def _mk_entry(test_id: str, bucket: Optional[str], train_hs: Optional[HorizonStats],
                          test_hs: Optional[HorizonStats], dominance: bool) -> CampaignEntry:
                return CampaignEntry(
                    test_id=test_id, spec_name=spec.name, bucket=bucket, horizon=h,
                    train_n=train_hs.n if train_hs else 0,
                    train_p=train_hs.p_value if train_hs else None,
                    train_mean_net=train_hs.mean_net if train_hs else None,
                    train_mean_gross=train_hs.mean_gross if train_hs else None,
                    test_n=test_hs.n if test_hs else 0,
                    test_p=test_hs.p_value if test_hs else None,
                    test_mean_net=test_hs.mean_net if test_hs else None,
                    test_mean_gross=test_hs.mean_gross if test_hs else None,
                    dominance_flag=dominance,
                )

            entries.append(_mk_entry(spec.name, None, res.train.per_horizon.get(h),
                                      res.test.per_horizon.get(h), res.train.dominance_flag or res.test.dominance_flag))
            if with_liquidity_buckets:
                for b in ("thin", "mid", "liquid"):
                    train_hs = res.train.by_liquidity.get(b, {}).get(h)
                    test_hs = res.test.by_liquidity.get(b, {}).get(h)
                    entries.append(_mk_entry(f"{spec.name}::{b}", b, train_hs, test_hs, False))
        del batch
        gc.collect()

    train_pvalues = [e.train_p for e in entries]
    fdr_reject = benjamini_hochberg(train_pvalues, alpha=alpha)
    n_tested = sum(1 for p in train_pvalues if p is not None)

    # Permutation-test RESOLUTION check: the smallest p a permutation test can
    # ever report is 1/(iters+1). BH's strictest (rank-1) critical value is
    # alpha/n_tested -- if the resolution floor is coarser than that, even a
    # dead-certain real edge cannot numerically clear FDR in this family, and
    # that would silently look like "nothing survived" for the wrong reason.
    if n_tested > 0:
        min_resolvable_p = 1.0 / (perm_iters + 1)
        strictest_critical = alpha / n_tested
        if min_resolvable_p > strictest_critical and verbose:
            print(f"  [campaign] WARNING: perm_iters={perm_iters} resolves p no finer than "
                  f"{min_resolvable_p:.5f}, coarser than this family's strictest BH critical value "
                  f"({strictest_critical:.5f}) -- increase perm_iters for a family this large.")

    for e, survived in zip(entries, fdr_reject):
        e.fdr_survivor = survived
        same_sign = (e.train_mean_net is not None and e.test_mean_net is not None and
                     np.sign(e.train_mean_net) == np.sign(e.test_mean_net) and e.train_mean_net != 0)
        e.confirmed = bool(survived and e.test_p is not None and e.test_p < 0.05 and
                            e.test_n >= MIN_N and same_sign and not e.dominance_flag)

    n_surviving = sum(1 for e in entries if e.fdr_survivor)
    n_confirmed = sum(1 for e in entries if e.confirmed)

    return CampaignResult(
        alpha=alpha, n_tested=n_tested, expected_false_positives=n_tested * alpha,
        n_surviving_fdr=n_surviving, n_confirmed=n_confirmed, entries=entries,
        results_by_spec=results_by_spec,
    )


# ===========================================================================
# NULL-CONTROL GENERATOR (shuffled entry conditions)
# ===========================================================================

_NULL_CANDIDATE_INDICATORS = ["bb_pctb", "bb_z", "rsi14", "support_dist", "vol_ratio",
                               "rvol20", "rel_strength_rank", "liquidity_rank"]


def make_shuffled_null_specs(n: int, store: DataStore, timeframe: str = "1d",
                              universe: Union[str, Sequence[str]] = "all",
                              horizons: Tuple[int, ...] = (1,), seed: int = 4242) -> List[HypothesisSpec]:
    """Generates `n` NULL hypotheses: for each, pick a real indicator + a
    random quantile threshold (so trigger COUNTS/base-rates look realistic),
    then SHUFFLE which bar indices are flagged True, independently per
    symbol -- this is the textbook permutation null. It preserves each
    symbol's exact trigger count while destroying any true temporal
    alignment with forward returns, so any hypothesis surviving FDR here is
    by construction a false positive."""
    rng = random.Random(seed)
    resolved = store.resolve_universe(universe)
    specs = []
    for i in range(n):
        ind = rng.choice(_NULL_CANDIDATE_INDICATORS)
        q = rng.uniform(0.05, 0.5)
        direction = rng.choice(["low", "high"])
        side = rng.choice(["long", "short"])
        precomputed: Dict[str, np.ndarray] = {}
        for sym in resolved:
            df = store.get(sym)
            if df is None or ind not in df.columns:
                continue
            col = df[ind]
            valid = col.dropna()
            if len(valid) < MIN_N:
                continue
            thresh = valid.quantile(q if direction == "low" else 1 - q)
            mask = (col < thresh) if direction == "low" else (col > thresh)
            mask = mask.fillna(False).values
            n_true = int(mask.sum())
            new_mask = np.zeros(len(mask), dtype=bool)
            if n_true > 0:
                positions = rng.sample(range(len(mask)), min(n_true, len(mask)))
                new_mask[positions] = True
            precomputed[sym] = new_mask
        specs.append(HypothesisSpec(
            name=f"NULL_{i:03d}_{ind}_{direction}_{side}", side=side, timeframe=timeframe,
            universe=universe, rules=[], precomputed_mask=precomputed, horizons=horizons,
        ))
    return specs


# ===========================================================================
# INVENTORY REPORT
# ===========================================================================

def inventory_report() -> None:
    print("=" * 78)
    print("CONFLUENCE HARNESS -- DATA-JOIN FEASIBILITY INVENTORY")
    print("=" * 78)

    longtail = discover_longtail_symbols()
    print(f"\nLongtail alts discovered: {len(longtail)} -> {longtail}")

    print("\n-- 1d OHLC coverage --")
    for sym in longtail + MAJOR_CACHE_SYMBOLS:
        df = load_ohlc(sym, "1d")
        if df is None:
            print(f"  {sym:<10s} NOT FOUND (1d)")
            continue
        print(f"  {sym:<10s} n={len(df):<5d} {df['dt'].iloc[0].date()} -> {df['dt'].iloc[-1].date()}")

    print("\n-- 1h OHLC coverage --")
    for sym in longtail + MAJOR_CACHE_SYMBOLS:
        df = load_ohlc(sym, "1h")
        if df is None:
            print(f"  {sym:<10s} NOT FOUND (1h)")
            continue
        print(f"  {sym:<10s} n={len(df):<5d} {df['dt'].iloc[0]} -> {df['dt'].iloc[-1]}")

    print("\n-- funding_oi_history.jsonl coverage --")
    fdf = load_funding_oi()
    if fdf.empty:
        print("  NOT FOUND / EMPTY")
    else:
        for sym, g in fdf.groupby("symbol"):
            print(f"  {sym:<10s} n={len(g):<5d} {g['dt'].min()} -> {g['dt'].max()}")

    print("\n-- liq_events.jsonl episodes (gap_sec=%d) --" % LIQ_EPISODE_GAP_SEC)
    eps = load_liq_episodes()
    if not eps:
        print("  NOT FOUND / EMPTY")
    else:
        for sym, e in sorted(eps.items(), key=lambda kv: -len(kv[1])):
            starts = [s for s, _ in e]
            print(f"  {sym:<10s} n_episodes={len(e):<5d} {min(starts)} -> {max(starts)}")

    print("\n" + "-" * 78)
    print("READ THIS SECTION -- what's cleanly joinable entry-time-safe, and the gaps:")
    print("-" * 78)
    print("""
  PRICE (25 longtail alts + BTC/SOL/ETH/HYPE/XRP):
    - 25 longtail alts: 1d full ~13mo history (401 bars, 2025-06-26 -> ~2026-07-31),
      1h ~7mo history (~4828 bars, 2026-01-12 -> ~2026-08-01). Clean, gap-free daily
      cadence confirmed. PUMP/XPL shorter (listed later). This is the primary,
      freshest, most complete price corpus -- use it as the main universe.
    - BTC/SOL/ETH/HYPE/XRP: cache/*_420d.csv. STALE -- all five end 2026-07-13,
      about 3 weeks behind the longtail alts and behind funding/liq data. Full
      ~1yr history back to the cache start, gap-free at daily/1h granularity in
      the *_420d variant specifically (the *_30d/*_60d/*_220d cache variants were
      found to have an internal collection gap in at least one file -- NOT used
      by this harness).

  DERIVATIVES (funding/OI, data/funding_oi_history.jsonl):
    - BTC/ETH/SOL/HYPE/XRP: dense, ~5-25min cadence, 2026-06-06 -> present (~2mo).
      Overlaps PRICE only through 2026-07-13 (the majors' price cache staleness),
      i.e. ~5-6 usable weeks of price+funding join for majors, not the full 2mo.
    - kPEPE/WIF/POPCAT/kSHIB/FARTCOIN/PENGU/kBONK: only since 2026-08-01 (~5 days).
      WIF and POPCAT are NOT in the longtail alt universe (no OHLC join available
      there at all -- see below). The other 5 overlap longtail 1h price only on
      2026-08-01 itself (longtail 1h ends 2026-08-01 17:00) -- essentially NO
      usable overlap window yet for meme funding-conditioned hypotheses.
    - A long tail of majors-adjacent symbols (UNI/ZEC/AAVE/PUMP/KAITO/DOGE/LIT/
      XMR/NEAR/BNB/ONDO) have ~27-30 rows total, all on 2026-08-01 -- a single
      snapshot burst, NOT a time series. Not usable for any hypothesis.
    VERDICT: funding_z/oi_roc are only meaningfully testable on BTC/SOL (best
    price+funding overlap) and, with the staleness caveat above, ETH/HYPE/XRP.
    Meme funding conditioning is NOT YET testable -- needs either fresher majors'
    price cache or several more weeks of meme funding collection.

  LIQUIDATIONS (data/copilot/liquidations/liq_events.jsonl):
    - Only 2026-08-01 -> present (~5 days), symbols BTC/SOL/FARTCOIN/kPEPE/WIF/
      PENGU/kSHIB/POPCAT/kBONK. After episode-collapse this is well under any
      reasonable independent-N floor for a NEW hypothesis test (contrast:
      liq_hypothesis_harness.py's pre-registered H3/H5 anticipate needing
      60-90 days). liq_cascade_flag is wired and entry-time-safe, but any
      hypothesis gated on it today will be structurally underpowered
      (n<MIN_N) by this harness's own gating -- that's a feature, not a bug:
      it will correctly print UNDERPOWERED rather than a fabricated p-value.

  LIQUIDITY BUCKETING: works on the full universe (25 alts + BTC/SOL/ETH/HYPE/
    XRP) using rolling dollar volume (c*v), which every symbol has for its
    full price history -- no derivatives dependency, no gap. This is the most
    ROBUST conditioning dimension available right now.

  BOTTOM LINE for campaign design: the 25 longtail alts + BTC/SOL on 1d/1h
  price + liquidity bucketing is fully joinable and well-powered TODAY.
  funding/OI conditioning is usable but era-limited (majors only, ~5-6wk
  window). liq_cascade_flag conditioning is wired but will read UNDERPOWERED
  until the collector accrues more history -- re-run --inventory periodically
  to see when that crosses MIN_N.
""")


def list_indicators() -> None:
    print("Indicator / column reference for HypothesisSpec rules:\n")
    for name, desc in INDICATOR_COLUMNS:
        print(f"  {name:<20s} {desc}")
    print("\nScoring model: UNLEVERED net expectancy, 1x spot buy-and-hold trigger-bar-to-horizon.")
    print("Trading cost is keyed to the triggering bar's liquidity_bucket (round-trip, disclosed midpoints):")
    for b, (lo, hi) in LIQUIDITY_COST_BPS_RANGE.items():
        print(f"  {b:<8s} {lo:.1f}-{hi:.1f}bps RT  -> midpoint used: {LIQUIDITY_COST_BPS_RT[b]:.1f}bps")
    print(f"  unknown  (no bucket yet) -> conservative default: {LIQUIDITY_COST_BPS_RT[None]:.1f}bps (= thin)")
    print("Every stat is reported gross (no cost) AND net (cost-adjusted); p-values/FDR/OOS confirmation")
    print("always use NET -- a thin-alt hypothesis must clear its OWN wider cost hurdle to count as an edge.")


# ===========================================================================
# SELFTEST
# ===========================================================================

def _make_synthetic_frame(rng: np.random.Generator, n_bars: int, start: str,
                           dip_starts: List[int], bounce_bars: int, bounce_size: float,
                           shock_size: float = 0.15, vol: float = 0.02) -> pd.DataFrame:
    """Builds one synthetic daily OHLCV series: a random walk with, at each
    index in `dip_starts`, a single SHARP shock bar (`shock_size`, e.g. -15%
    in one bar -- guaranteed to push RSI/BB oversold via the REAL indicator
    formulas on that bar or the very next one) immediately followed by a
    forced bounce of `bounce_size` spread over the next `bounce_bars` bars.
    The shock is deliberately ONE bar (not a multi-bar gradual decline) so
    that whichever bar the oversold condition actually fires on is always at
    or immediately after the trough -- a multi-bar decline would let the
    condition fire mid-decline, with the forward window landing before the
    bounce even starts (a real bug this design specifically avoids). Returns
    a canonical dt/o/h/l/c/v frame."""
    dts = pd.date_range(start, periods=n_bars, freq="D", tz="UTC")
    logret = rng.normal(0, vol, n_bars)
    price = 100.0
    closes = []
    i = 0
    dip_set = set(dip_starts)
    while i < n_bars:
        if i in dip_set:
            price *= (1 - shock_size + rng.normal(0, vol * 0.3))
            closes.append(price)
            i += 1
            for k in range(bounce_bars):
                if i >= n_bars:
                    break
                step = bounce_size / bounce_bars
                price *= (1 + step + rng.normal(0, vol * 0.3))
                closes.append(price)
                i += 1
        else:
            price *= (1 + logret[i])
            closes.append(price)
            i += 1
    closes = np.array(closes[:n_bars])
    highs = closes * (1 + np.abs(rng.normal(0, 0.005, n_bars)))
    lows = closes * (1 - np.abs(rng.normal(0, 0.005, n_bars)))
    vols = np.abs(rng.normal(1000, 200, n_bars))
    return pd.DataFrame({"dt": dts, "o": closes, "h": highs, "l": lows, "c": closes, "v": vols})


def selftest_a_recovers_planted_edge() -> bool:
    """(a) Plant a genuine confluence edge (oversold BB+RSI reliably bounces)
    across several synthetic symbols, spanning both train and test periods ->
    the harness must recover it: train AND test both p<0.05, same sign, and
    it must survive FDR when run alongside noise hypotheses."""
    rng = np.random.default_rng(11)
    frames = {}
    for si in range(6):
        symbol = f"SYNTH_EDGE_{si}"
        dips = list(range(15 + si * 3, 480, 25))  # dense dips spread across the whole timeline
        raw = _make_synthetic_frame(rng, 500, "2024-01-01", dips, bounce_bars=4, bounce_size=0.06)
        frames[symbol] = compute_price_indicators(raw, "1d")
        frames[symbol]["funding_z"] = np.nan
        frames[symbol]["oi_roc"] = np.nan
        frames[symbol]["liq_cascade_flag"] = False
    # a few flat/noise symbols too, so it isn't a single-symbol-dominance artifact
    for si in range(3):
        symbol = f"SYNTH_FLAT_{si}"
        raw = _make_synthetic_frame(rng, 500, "2024-01-01", [], bounce_bars=1, bounce_size=0.0)
        frames[symbol] = compute_price_indicators(raw, "1d")
        frames[symbol]["funding_z"] = np.nan
        frames[symbol]["oi_roc"] = np.nan
        frames[symbol]["liq_cascade_flag"] = False
    _attach_rel_strength(frames)
    _attach_liquidity_bucket(frames)

    store = DataStore.__new__(DataStore)
    store.timeframe = "1d"
    store.frames = frames
    store.skipped = []
    store.requested_universe = list(frames.keys())
    store.global_start = min(f["dt"].iloc[0] for f in frames.values())
    store.global_end = max(f["dt"].iloc[-1] for f in frames.values())

    spec = HypothesisSpec(name="planted_oversold_bounce", side="long", timeframe="1d",
                           universe="all", rules=[Rule("bb_pctb", "<", 0.15), Rule("rsi14", "<", 35)],
                           horizons=(3,))
    res = run_hypothesis(spec, store, compute_liquidity=False)
    h = 3
    train_hs, test_hs = res.train.per_horizon[h], res.test.per_horizon[h]
    ok = (
        train_hs.n >= MIN_N and test_hs.n >= MIN_N and
        train_hs.p_value is not None and train_hs.p_value < 0.05 and
        test_hs.p_value is not None and test_hs.p_value < 0.05 and
        train_hs.mean_net > 0 and test_hs.mean_net > 0
    )
    print(f"  [A] planted edge: train n={train_hs.n} p={train_hs.p_value} mean={train_hs.mean_net}; "
          f"test n={test_hs.n} p={test_hs.p_value} mean={test_hs.mean_net}: "
          f"{'PASS' if ok else 'FAIL'}")

    # survives FDR alongside 30 noise hypotheses
    noise_specs = make_shuffled_null_specs(30, store, timeframe="1d", horizons=(3,), seed=99)
    # NOTE iters=1000 (not the lower value used elsewhere for speed): with m=31
    # tests in this family, BH's rank-1 critical value is (1/31)*0.05=0.0016 --
    # a permutation test's smallest ACHIEVABLE p-value is 1/(iters+1), so iters
    # must resolve finer than that critical value or even a dead-certain real
    # edge cannot numerically clear FDR. This is a real property of permutation
    # tests (not a bug to paper over) -- campaigns with large hypothesis
    # families need proportionally more iters for the same resolving power.
    campaign = run_campaign([spec] + noise_specs, store, batch_size=10, with_liquidity_buckets=False, perm_iters=1000)
    entry = next(e for e in campaign.entries if e.spec_name == spec.name and e.bucket is None)
    fdr_ok = entry.confirmed
    print(f"  [A] planted edge survives FDR alongside 30 noise hypotheses "
          f"(n_tested={campaign.n_tested}, n_confirmed={campaign.n_confirmed}): "
          f"{'PASS' if fdr_ok else 'FAIL'}")
    return ok and fdr_ok


def selftest_b_noise_yields_zero_survivors() -> bool:
    """(b) 200 PURE-NOISE (shuffled) hypotheses on REAL longtail data -> the
    FDR layer must correctly report ~0 survivors. This is the key property:
    it proves the harness will not manufacture false positives at scale."""
    store = DataStore(universe="all", timeframe="1d")
    if len(store.frames) < 5:
        print("  [B] SKIPPED -- insufficient real data loaded")
        return True
    specs = make_shuffled_null_specs(200, store, timeframe="1d", horizons=(1,), seed=2026)
    campaign = run_campaign(specs, store, batch_size=25, with_liquidity_buckets=False, perm_iters=400)
    expected_fp = campaign.n_tested * campaign.alpha
    ok = campaign.n_confirmed <= 3
    print(f"  [B] 200 noise hypotheses on real data: n_tested={campaign.n_tested}, "
          f"expected_false_positives={expected_fp:.1f}, n_surviving_FDR={campaign.n_surviving_fdr}, "
          f"n_CONFIRMED (train FDR + test-set agreement)={campaign.n_confirmed}: "
          f"{'PASS (~0 survivors)' if ok else 'FAIL'}")
    return ok


def selftest_c_oos_split_flags_train_only_edge() -> bool:
    """(c) An edge planted ONLY in the train portion of the timeline (test
    portion has the same trigger but a random, unbiased forward move) must be
    correctly flagged as failing test -- i.e. NOT in the confirmed survivors,
    even though it clears train significance/FDR."""
    rng = np.random.default_rng(55)
    frames = {}
    n_bars = 500
    split_bar = int(n_bars * TRAIN_FRACTION_DEFAULT)
    for si in range(6):
        symbol = f"SYNTH_TRAINONLY_{si}"
        train_dips = list(range(15 + si * 3, split_bar - 15, 22))
        raw = _make_synthetic_frame(rng, split_bar, "2024-01-01", train_dips, bounce_bars=4, bounce_size=0.06)
        # test portion: same dip pattern generator but bounce_size=0.0 (no planted edge)
        test_dips_local = list(range(8, n_bars - split_bar - 12, 22))
        raw2 = _make_synthetic_frame(rng, n_bars - split_bar,
                                      str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=split_bar)).date()),
                                      test_dips_local, bounce_bars=4, bounce_size=0.0)
        raw2["c"] = raw2["c"] * (raw["c"].iloc[-1] / raw2["c"].iloc[0])
        raw2["o"] = raw2["o"] * (raw["c"].iloc[-1] / raw2["o"].iloc[0])
        raw2["h"] = raw2["h"] * (raw["c"].iloc[-1] / raw2["h"].iloc[0])
        raw2["l"] = raw2["l"] * (raw["c"].iloc[-1] / raw2["l"].iloc[0])
        full_raw = pd.concat([raw, raw2], ignore_index=True)
        frames[symbol] = compute_price_indicators(full_raw, "1d")
        frames[symbol]["funding_z"] = np.nan
        frames[symbol]["oi_roc"] = np.nan
        frames[symbol]["liq_cascade_flag"] = False
    _attach_rel_strength(frames)
    _attach_liquidity_bucket(frames)

    store = DataStore.__new__(DataStore)
    store.timeframe = "1d"
    store.frames = frames
    store.skipped = []
    store.requested_universe = list(frames.keys())
    store.global_start = min(f["dt"].iloc[0] for f in frames.values())
    store.global_end = max(f["dt"].iloc[-1] for f in frames.values())
    sd = store.global_start + (store.global_end - store.global_start) * TRAIN_FRACTION_DEFAULT

    spec = HypothesisSpec(name="train_only_edge", side="long", timeframe="1d", universe="all",
                           rules=[Rule("bb_pctb", "<", 0.15), Rule("rsi14", "<", 35)], horizons=(3,))
    res = run_hypothesis(spec, store, split_date=sd, compute_liquidity=False)
    h = 3
    train_hs, test_hs = res.train.per_horizon[h], res.test.per_horizon[h]
    train_sig = train_hs.n >= MIN_N and train_hs.p_value is not None and train_hs.p_value < 0.05 and train_hs.mean_net > 0
    test_not_confirmatory = not (test_hs.n >= MIN_N and test_hs.p_value is not None and
                                  test_hs.p_value < 0.05 and test_hs.mean_net > 0)
    ok = train_sig and test_not_confirmatory
    print(f"  [C] train-only edge: train n={train_hs.n} p={train_hs.p_value} mean={train_hs.mean_net} "
          f"(expect significant+positive); test n={test_hs.n} p={test_hs.p_value} mean={test_hs.mean_net} "
          f"(expect NOT significant+positive): {'PASS' if ok else 'FAIL'}")

    campaign = run_campaign([spec], store, split_date=sd, with_liquidity_buckets=False, perm_iters=500)
    entry = campaign.entries[0]
    not_confirmed = not entry.confirmed
    print(f"  [C] campaign correctly EXCLUDES it from confirmed survivors "
          f"(fdr_survivor={entry.fdr_survivor}, confirmed={entry.confirmed}): "
          f"{'PASS' if not_confirmed else 'FAIL'}")
    return ok and not_confirmed


def selftest_d_liquidity_monotonicity() -> bool:
    """Plants an edge that is NULL on 'liquid' symbols but present on 'thin'
    symbols (by construction: thin symbols get the bounce, liquid symbols get
    a flat/random response to the same oversold trigger), with liquidity
    driven structurally by trading volume level -- confirms by_liquidity
    breakout + liquidity_monotonicity() correctly detect the ladder."""
    rng = np.random.default_rng(303)
    frames = {}
    liquid_syms = [f"SYNTH_LIQUID_{i}" for i in range(3)]
    thin_syms = [f"SYNTH_THIN_{i}" for i in range(3)]
    for si, symbol in enumerate(liquid_syms):
        dips = list(range(15 + si * 3, 480, 22))
        raw = _make_synthetic_frame(rng, 500, "2024-01-01", dips, bounce_bars=4, bounce_size=0.0)  # no edge
        raw["v"] = raw["v"] * 50000.0  # much higher volume -> liquid bucket
        frames[symbol] = compute_price_indicators(raw, "1d")
    for si, symbol in enumerate(thin_syms):
        dips = list(range(15 + si * 3, 480, 22))
        raw = _make_synthetic_frame(rng, 500, "2024-01-01", dips, bounce_bars=4, bounce_size=0.07)  # real edge
        raw["v"] = raw["v"] * 1.0  # low volume -> thin bucket
        frames[symbol] = compute_price_indicators(raw, "1d")
    for f in frames.values():
        f["funding_z"] = np.nan
        f["oi_roc"] = np.nan
        f["liq_cascade_flag"] = False
    _attach_rel_strength(frames)
    _attach_liquidity_bucket(frames)

    store = DataStore.__new__(DataStore)
    store.timeframe = "1d"
    store.frames = frames
    store.skipped = []
    store.requested_universe = list(frames.keys())
    store.global_start = min(f["dt"].iloc[0] for f in frames.values())
    store.global_end = max(f["dt"].iloc[-1] for f in frames.values())

    # sanity: liquidity bucketing actually separated the two groups
    liquid_bucket_share = np.mean([np.mean([b == "liquid" for b in frames[s]["liquidity_bucket"].dropna()])
                                    for s in liquid_syms])
    thin_bucket_share = np.mean([np.mean([b == "thin" for b in frames[s]["liquidity_bucket"].dropna()])
                                  for s in thin_syms])
    bucket_ok = liquid_bucket_share > 0.6 and thin_bucket_share > 0.6

    spec = HypothesisSpec(name="liquidity_ladder_edge", side="long", timeframe="1d", universe="all",
                           rules=[Rule("bb_pctb", "<", 0.15), Rule("rsi14", "<", 35)], horizons=(3,))
    res = run_hypothesis(spec, store, compute_liquidity=True)
    mono = liquidity_monotonicity(res.full, horizon=3, metric="mean_net")
    mono_ok = mono["status"] == "ok" and mono.get("monotonic_liquidity_ladder") is True
    print(f"  [D] liquidity bucketing separates groups: liquid_share={liquid_bucket_share:.2f} "
          f"thin_share={thin_bucket_share:.2f}: {'PASS' if bucket_ok else 'FAIL'}")
    print(f"  [D] liquidity_monotonicity readout: {mono}: "
          f"{'PASS (edge strengthens down the liquidity ladder)' if mono_ok else 'FAIL'}")
    return bucket_ok and mono_ok


def selftest_bh_fdr_known_example() -> bool:
    """BH-FDR sanity check: hand-verified step-up computation. m=10, alpha=0.05
    -> critical value at rank k is (k/10)*0.05. Sorted p=[0.001,0.008,0.039,
    0.041,0.042,0.06,0.074,0.205,0.212,0.216] vs crit=[.005,.010,.015,.020,
    .025,.030,.035,.040,.045,.050] -- only ranks 1,2 individually clear their
    critical value (0.001<=.005, 0.008<=.010; rank 3's 0.039 > .015 and every
    later rank likewise fails), so the largest satisfying rank is k=2 and BH
    rejects ranks 1-2 only. A second case (all p=0.001, unambiguous) checks
    the all-reject boundary."""
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    reject = benjamini_hochberg(pvals, alpha=0.05)
    expected = [True, True, False, False, False, False, False, False, False, False]
    ok = reject == expected
    print(f"  [BH-FDR] reject={reject} expected={expected}: {'PASS' if ok else 'FAIL'}")

    pvals2 = [0.001] * 10
    reject2 = benjamini_hochberg(pvals2, alpha=0.05)
    ok2 = all(reject2)
    print(f"  [BH-FDR] all-significant case: reject={reject2}: {'PASS' if ok2 else 'FAIL'}")

    pvals3 = [0.9] * 10
    reject3 = benjamini_hochberg(pvals3, alpha=0.05)
    ok3 = not any(reject3)
    print(f"  [BH-FDR] all-null case: reject={reject3}: {'PASS' if ok3 else 'FAIL'}")
    return ok and ok2 and ok3


def run_selftest() -> int:
    print("=" * 78)
    print("CONFLUENCE HARNESS -- SELFTEST")
    print("=" * 78)
    results = []
    print("\n[BH-FDR mechanics]")
    results.append(selftest_bh_fdr_known_example())
    print("\n[A] Plant a genuine confluence edge -> harness recovers it, survives FDR")
    results.append(selftest_a_recovers_planted_edge())
    print("\n[B] 200 pure-noise hypotheses -> ~0 FDR survivors (the key anti-p-hacking proof)")
    results.append(selftest_b_noise_yields_zero_survivors())
    print("\n[C] OOS split -> train-only edge correctly fails test / excluded from survivors")
    results.append(selftest_c_oos_split_flags_train_only_edge())
    print("\n[D] Liquidity dimension -> bucketing + monotonicity readout recover a planted ladder edge")
    results.append(selftest_d_liquidity_monotonicity())

    print("\n" + "=" * 78)
    all_ok = all(results)
    print(f"SELFTEST {'ALL PASS' if all_ok else 'FAILURES PRESENT'} ({sum(results)}/{len(results)})")
    print("=" * 78)
    return 0 if all_ok else 1


# ===========================================================================
# REAL-DATA SMOKE TEST (join/compute verification only -- NO conclusions)
# ===========================================================================

def run_smoke() -> None:
    print("=" * 78)
    print("CONFLUENCE HARNESS -- REAL-DATA SMOKE TEST")
    print("SMOKE TEST ONLY -- verifies joins/computation run end-to-end on real data.")
    print("NO CONCLUSIONS DRAWN. Not statistically vetted for the campaign yet.")
    print("=" * 78)
    store = DataStore(universe="all", timeframe="1d", verbose=True)
    print(f"\nLoaded {len(store.frames)} symbols, skipped {len(store.skipped)}: {store.skipped}")
    print(f"Global range: {store.global_start} -> {store.global_end}")

    specs = [
        HypothesisSpec(name="smoke_bb_oversold_long", side="long", universe="all",
                        rules=[Rule("bb_pctb", "<", 0.2)], horizons=(1, 3, 5)),
        HypothesisSpec(name="smoke_rsi_overbought_short", side="short", universe="all",
                        rules=[Rule("rsi14", ">", 70)], horizons=(1, 3, 5)),
        HypothesisSpec(name="smoke_breakout_trend_long", side="long", universe="all",
                        rules=[Rule("breakout", "==", 1), Rule("ema_trend_up", "==", 1)], horizons=(1, 3, 5)),
    ]
    for spec in specs:
        res = run_hypothesis(spec, store, compute_liquidity=True)
        print(f"\n-- {spec.name} (side={spec.side}) --")
        print(f"  universe={res.n_universe_symbols} symbols, raw_triggers={res.n_events_total_raw}, "
              f"collapse_ratio={res.diagnostics['collapse_ratio']}")
        for split_name, split in [("full", res.full), ("train", res.train), ("test", res.test),
                                   ("pre_era", res.pre_era), ("post_era", res.post_era)]:
            for h, hs in split.per_horizon.items():
                tag = "UNDERPOWERED" if hs.underpowered else f"p={hs.p_value}"
                print(f"    [{split_name:<8s}] h={h}d n={hs.n:<4d} wr_net={hs.wr_net} "
                      f"gross={hs.mean_gross} net={hs.mean_net} {tag}")
        mono = liquidity_monotonicity(res.full, horizon=spec.primary_horizon())
        print(f"  liquidity_monotonicity (full, h={spec.primary_horizon()}d): {mono}")
    print("\n" + "=" * 78)
    print("SMOKE TEST COMPLETE -- joins + computation verified. NO CONCLUSIONS DRAWN.")
    print("=" * 78)


# ===========================================================================
# CLI
# ===========================================================================

def _spec_from_json(d: dict) -> HypothesisSpec:
    rules = [Rule(r["indicator"], r["op"], r["value"]) for r in d.get("rules", [])]
    return HypothesisSpec(
        name=d["name"], side=d["side"], timeframe=d.get("timeframe", "1d"),
        universe=d.get("universe", "all"), rules=rules, min_agree=d.get("min_agree"),
        horizons=tuple(d.get("horizons", (1, 3, 5))),
        dedup_gap_days=d.get("dedup_gap_days", DEDUP_GAP_DAYS_DEFAULT),
    )


def run_campaign_cli(path: str, batch_size: Optional[int], alpha: float, with_liq: bool,
                      timeframe: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    specs = [_spec_from_json(d) for d in raw]
    store = DataStore(universe="all", timeframe=timeframe, verbose=False)
    print(f"Loaded {len(store.frames)} symbols for timeframe={timeframe}. Running {len(specs)} hypotheses "
          f"(batch_size={batch_size}, with_liquidity_buckets={with_liq})...")
    campaign = run_campaign(specs, store, alpha=alpha, batch_size=batch_size,
                             with_liquidity_buckets=with_liq, verbose=True)
    print("\n" + "=" * 78)
    print(f"CAMPAIGN RESULT: n_tested={campaign.n_tested} alpha={campaign.alpha} "
          f"expected_false_positives={campaign.expected_false_positives:.2f} "
          f"n_surviving_FDR={campaign.n_surviving_fdr} n_CONFIRMED={campaign.n_confirmed}")
    print("=" * 78)
    for e in campaign.entries:
        if e.confirmed:
            print(f"  CONFIRMED: {e.test_id}  "
                  f"train(n={e.train_n},p={e.train_p},gross={e.train_mean_gross},net={e.train_mean_net})  "
                  f"test(n={e.test_n},p={e.test_p},gross={e.test_mean_gross},net={e.test_mean_net})")


def main() -> int:
    ap = argparse.ArgumentParser(description="WAGMI Confluence Hypothesis Engine")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--list-indicators", action="store_true")
    ap.add_argument("--campaign", type=str, default=None, help="path to a JSON list of hypothesis specs")
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--alpha", type=float, default=FDR_ALPHA_DEFAULT)
    ap.add_argument("--timeframe", type=str, default="1d", choices=["1d", "1h"])
    ap.add_argument("--no-liquidity-fdr", action="store_true")
    ap.add_argument("--null-control", type=int, default=None, help="run N shuffled-null hypotheses through the campaign")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()
    if args.inventory:
        inventory_report()
        return 0
    if args.list_indicators:
        list_indicators()
        return 0
    if args.smoke:
        run_smoke()
        return 0
    if args.null_control:
        store = DataStore(universe="all", timeframe=args.timeframe)
        specs = make_shuffled_null_specs(args.null_control, store, timeframe=args.timeframe, seed=2026)
        campaign = run_campaign(specs, store, alpha=args.alpha, batch_size=args.batch or 25,
                                 with_liquidity_buckets=not args.no_liquidity_fdr, verbose=True)
        print(f"\nnull-control: n_tested={campaign.n_tested} expected_false_positives="
              f"{campaign.expected_false_positives:.2f} n_surviving_FDR={campaign.n_surviving_fdr} "
              f"n_CONFIRMED={campaign.n_confirmed}")
        return 0
    if args.campaign:
        run_campaign_cli(args.campaign, args.batch, args.alpha, not args.no_liquidity_fdr, args.timeframe)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
