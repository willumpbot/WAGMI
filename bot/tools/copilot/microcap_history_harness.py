#!/usr/bin/env python
"""
WAGMI Co-Pilot MICRO-CAP HISTORY HARNESS -- microcap_history_harness.py
=============================================================================
SLIPPAGE-NAIVE UPPER-BOUND read of the 7 HISTORY-testable hypotheses in
tools/copilot/MICROCAP_CAMPAIGN.md (Part C), run ONLY on the survivor-safe
clean universe (data/microcap/universe_testable.json, wash_heavy == false ->
the 12 coins with Jupiter organic_score >= 40). THIS IS NOT A TRADEABLE
BACKTEST. Every number here is an upper bound on ALREADY-SURVIVED coins:
these 12 are alive today; the dead clones that would drag the mean down were
never in the file (survivorship). Read every headline with that in mind.

WHY THIS EXISTS, AND WHAT IT REUSES: it is the micro-cap sibling of
tools/copilot/confluence_harness.py and tools/copilot/liq_hypothesis_harness.py
and reuses their integrity moat VERBATIM in spirit -- entry-time-safe signals
(a bar-t signal uses only data through bar-t's close; the outcome is a
STRICTLY-FORWARD return to t+k close), net-of-realistic-cost scoring (the
per-liquidity DEX round-trip table from MICROCAP_CAMPAIGN.md A1d, harsher than
the HL table), a single-calendar-cutoff OOS split (A3: micro-caps have
wildly staggered launch dates, so a per-coin percentile split would leave
some coins with days of TEST), Benjamini-Hochberg FDR across the whole
family, pseudoreplication control (consecutive same-coin triggers collapse to
ONE independent episode before any N/p is computed), an n>=30-independent-
episode significance floor, and a refute-yourself negative control
(--selftest asserts ~0 survivors on shuffled noise, like confluence_harness's
selftest_b).

FOUR MICRO-CAP-SPECIFIC HONESTY RULES baked in (MICROCAP_CAMPAIGN.md A1c-e,
A4.6-7), every one load-bearing, printed every run:
  * [SLIPPAGE-NAIVE UPPER BOUND]  -- price fields never reflect a real fill;
    a close-price "buy" on a $30k pool assumes a $200-1000 order walks
    straight through at close. The net cost table is applied ON TOP of that
    already-optimistic assumption, so even the NET number is an upper bound.
  * [LIQUIDITY-AT-TIME UNVERIFIED] -- GT OHLCV has no reserve/liquidity
    history; every coin's liquidity bucket (hence its cost hurdle) is keyed
    to a SINGLE current-state snapshot (universe_testable.json), not the
    liquidity at each historical bar. Any age<14d bucket is additionally
    un-verifiable and flagged.
  * WASH-DRIVEN check -- the campaign's A4.6 organic-vs-raw re-run needs
    Jupiter organic-volume HISTORY, which does not exist (FORWARD-only). The
    HISTORY track instead addresses wash structurally: the universe is
    pre-filtered to organic_score>=40 (wash_heavy==false) BEFORE any test, so
    the whole population already cleared the only wash instrument available.
    This is disclosed as a weaker mitigation than the forward organic re-run,
    not a substitute for it.
  * Rug/tail-loss check -- every result reports the WORST single-episode net
    return and the 5% CVaR alongside the mean, because a mean built on 29
    small wins + 1 rug is a different claim than 29 wins + no rug.

TRACK DISCIPLINE (A1b/A2): everything here is HISTORY track and therefore, per
the campaign, ORIGIN / UNVALIDATED -- a survivor is a hypothesis-generation
lead for a FORWARD re-test, never an edge, never a trade, never shipped near
the live bot. A clean null is the correct, honest result and is reported as
"0 survived", not dressed up.

READ-ONLY / STANDALONE: reads only data/microcap/ (universe_testable.json,
universe.json, ohlcv/*.csv). No imports of llm/, execution/, core/,
strategies/. No Discord. No network. Writes NOTHING under data/ -- only prints
to stdout (the results file is authored separately from this run's output).

CLI:
    python tools/copilot/microcap_history_harness.py --selftest   # negative-control + method verification (asserts ~0 noise survivors)
    python tools/copilot/microcap_history_harness.py --run        # run the 7 HISTORY hypotheses on the 12 clean coins
    python tools/copilot/microcap_history_harness.py --inventory  # data-join feasibility readout (no conclusions)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths (standalone -- no bot imports)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
MICROCAP_DIR = os.path.join(BOT_DIR, "data", "microcap")
UNIVERSE_TESTABLE = os.path.join(MICROCAP_DIR, "universe_testable.json")
UNIVERSE_FULL = os.path.join(MICROCAP_DIR, "universe.json")

# ---------------------------------------------------------------------------
# LOCKED METHOD PARAMETERS -- disclosed; changing any after seeing a result is
# the p-hacking this file exists to prevent (same discipline as the sibling
# harnesses' pre-registration blocks).
# ---------------------------------------------------------------------------
SIGNIFICANCE_N = 30                 # min INDEPENDENT episodes per bucket before ANY p-value (A3 / PREREGISTRATION.md convention)
DEDUP_GAP_DAYS = 1.0                # same-coin triggers within this many days collapse to ONE episode (A3 collapse rule #1)
PERM_ITERS_DEFAULT = 2000           # permutation resamples for the matched-baseline p-value
PERM_SEED = 1337                    # fixed seed -> reproducible p-values, never re-rolled to chase a result
FDR_ALPHA = 0.10                    # BH q=0.10 (MICROCAP_CAMPAIGN.md A3; Bonferroni reported alongside)
SINGLE_COIN_DOMINANCE_WARN = 0.50   # flag if one coin carries > this share of a split's episodes (few names here -> critical, A5.2)
CVAR_TAIL_FRAC = 0.05               # worst-5% mean = CVaR proxy (A4.7 tail-loss)
MIN_DAY_CANDLES = 20                # skip a coin with fewer than this many daily bars
HORIZONS_DAYS: Tuple[int, ...] = (1, 3, 7)   # forward horizons in days
TURNOVER_BASELINE_WIN = 30          # trailing bars for the entry-time-safe turnover z-score baseline
TURNOVER_Z_TRIGGER = 2.0            # turnover z-score >= this = a turnover spike (M19)
RS_TOP_QUINTILE = 0.80              # cross-sectional rel-strength pct-rank >= this = top quintile (M21)
BREADTH_LOOKBACK_DAYS = 7           # trailing window for breadth + rel-strength (M21/M22)
CLUSTER_CORR_MIN = 0.50             # pairwise daily-return correlation >= this = same cluster (M23)
CLUSTER_LAG_GAP = 0.05              # coin trails cluster-median 3d return by >= this (5%) = laggard (M23)

# ---------------------------------------------------------------------------
# COST TABLE -- per-liquidity-bucket realistic DEX round-trip cost, VERBATIM
# from MICROCAP_CAMPAIGN.md A1d (harsher than the HL alt table -- an AMM curve,
# not a CEX book, at the $200-$1,000 reference size). Buckets are keyed to the
# coin's SINGLE current-state liquidity snapshot (there is no liquidity
# HISTORY -- this is exactly the [LIQUIDITY-AT-TIME UNVERIFIED] caveat).
# Midpoints used for the NET number; the range is disclosed so it can be
# argued with, not hidden. Overlapping campaign rows ($1M-$5M 30-75bps and
# "POPCAT-scale $2-3M+" 15-40bps) are split at $2M so each coin lands in
# exactly one bucket.
# ---------------------------------------------------------------------------
COST_BUCKETS: List[Tuple[float, float, str, Tuple[float, float]]] = [
    #  lo_usd,      hi_usd,   label,                     (bps_lo, bps_hi)
    (0.0,          50_000.0,  "15k-50k (newborn)",       (250.0, 400.0)),
    (50_000.0,     200_000.0, "50k-200k",                (150.0, 250.0)),
    (200_000.0,    1_000_000.0, "200k-1M",               (75.0, 150.0)),
    (1_000_000.0,  2_000_000.0, "1M-2M",                 (30.0, 75.0)),
    (2_000_000.0,  float("inf"), "POPCAT-scale (2M+)",   (15.0, 40.0)),
]


def cost_bucket_for_liquidity(liq_usd: float) -> Tuple[str, float, Tuple[float, float]]:
    """Returns (label, midpoint_bps, (lo_bps, hi_bps)) for a liquidity level.
    A missing/NaN liquidity value defaults to the THINNEST (most conservative,
    highest-cost) bucket -- an unknown-liquidity coin must never look cheap."""
    if liq_usd is None or (isinstance(liq_usd, float) and math.isnan(liq_usd)):
        lo, hi = COST_BUCKETS[0][3]
        return COST_BUCKETS[0][2] + " [liq unknown -> conservative]", (lo + hi) / 2.0, (lo, hi)
    for lo_usd, hi_usd, label, (blo, bhi) in COST_BUCKETS:
        if lo_usd <= liq_usd < hi_usd:
            return label, (blo + bhi) / 2.0, (blo, bhi)
    lo, hi = COST_BUCKETS[-1][3]
    return COST_BUCKETS[-1][2], (lo + hi) / 2.0, (lo, hi)


# ===========================================================================
# LOADERS
# ===========================================================================

def load_clean_universe() -> List[dict]:
    """The analyzable set: universe_testable.json rows with wash_heavy==false
    (Jupiter organic_score>=40). This is the survivorship + wash filter, applied
    BEFORE any test -- the whole population already cleared the only wash
    instrument available on the HISTORY track (A1c mitigation)."""
    with open(UNIVERSE_TESTABLE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [c for c in data.get("coins", []) if not c.get("wash_heavy", True)]


def load_metadata_by_mint() -> Dict[str, dict]:
    """pair_created_at / fdv_usd / mcap_usd / age_days live in universe.json
    (tier_a_named + tier_b_established), keyed by mint. Used for M1/M4 (age)
    and M7 (liquidity-to-FDV). Returns {mint: {...}}."""
    out: Dict[str, dict] = {}
    if not os.path.exists(UNIVERSE_FULL):
        return out
    with open(UNIVERSE_FULL, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("tier_a_named", "tier_b_established", "tier_b_systematic"):
        for row in (data.get(key) or []):
            mint = row.get("mint")
            if mint and mint not in out:
                out[mint] = row
    return out


def load_ohlcv_day(rel_path: str) -> Optional[pd.DataFrame]:
    """Reads one GT daily OHLCV csv into a canonical dt/o/h/l/c/v frame
    (dt tz-aware UTC), sorted/deduped. Never raises on a malformed row."""
    path = os.path.join(MICROCAP_DIR, rel_path)
    if not os.path.exists(path):
        return None
    try:
        raw = pd.read_csv(path)
    except Exception:
        return None
    if "timestamp_iso" not in raw.columns or "close" not in raw.columns:
        return None
    df = pd.DataFrame({
        "dt": pd.to_datetime(raw["timestamp_iso"], utc=True, errors="coerce"),
        "o": pd.to_numeric(raw.get("open"), errors="coerce"),
        "h": pd.to_numeric(raw.get("high"), errors="coerce"),
        "l": pd.to_numeric(raw.get("low"), errors="coerce"),
        "c": pd.to_numeric(raw.get("close"), errors="coerce"),
        "v": pd.to_numeric(raw.get("volume_usd"), errors="coerce"),
    })
    df = df.dropna(subset=["dt", "c"]).drop_duplicates(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    return df if len(df) > 0 else None


# ===========================================================================
# INDICATORS (entry-time-safe: smoothing indicators read up to and including
# the current bar's CLOSE, which is known at decision time; trailing baselines
# that must not see the current bar use .shift(1) first. Forward returns are
# STRICTLY forward -- close[t] -> close[t+k], never touching the signal bar's
# own future.)
# ===========================================================================

def compute_indicators(df: pd.DataFrame, meta: dict, static_liq: float) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]

    # --- static per-coin cost (keyed to current-state liquidity snapshot) ---
    _label, cost_bps, _rng = cost_bucket_for_liquidity(static_liq)
    df["cost_bps"] = cost_bps  # round-trip, applied once to each forward return

    # --- forward RAW returns (sign-agnostic; side flip + cost applied at stats time) ---
    for k in HORIZONS_DAYS:
        df[f"fwd_raw_{k}"] = c.shift(-k) / c - 1.0

    # --- trailing returns (through current close -> entry-time-safe) ---
    df["ret1"] = c.pct_change(1)
    df["ret3"] = c.pct_change(3)
    df["ret7"] = c.pct_change(BREADTH_LOOKBACK_DAYS)

    # --- realized vol (M4): rolling std of daily returns over a trailing window,
    #     using only PRIOR bars (shift(1)) so it never reads the current bar ---
    df["rvol14"] = df["ret1"].shift(1).rolling(14, min_periods=7).std(ddof=0)
    # single-bar wick range (high-low)/close -- descriptive noisiness of THIS bar
    df["wick_range"] = (h - l) / c.replace(0.0, np.nan)

    # --- turnover (M19): daily $volume / STATIC current liquidity (denominator
    #     is [LIQUIDITY-AT-TIME UNVERIFIED]). z-score vs the coin's OWN trailing
    #     baseline built from strictly-prior bars (shift(1)). ---
    if static_liq and static_liq > 0:
        turnover = v / static_liq
    else:
        turnover = pd.Series(np.nan, index=df.index)
    df["turnover"] = turnover
    base_mean = turnover.shift(1).rolling(TURNOVER_BASELINE_WIN, min_periods=15).mean()
    base_std = turnover.shift(1).rolling(TURNOVER_BASELINE_WIN, min_periods=15).std(ddof=0)
    df["turnover_z"] = (turnover - base_mean) / base_std.replace(0.0, np.nan)

    # --- age at bar (M1/M4): days since pair_created_at (static event date) ---
    created = meta.get("pair_created_at")
    created_dt = pd.to_datetime(created, utc=True, errors="coerce") if created else pd.NaT
    if pd.notna(created_dt):
        df["age_days"] = (df["dt"] - created_dt).dt.total_seconds() / 86400.0
    else:
        df["age_days"] = np.nan

    return df


# --- age buckets (M1/M4), campaign-defined ---
AGE_BUCKETS: List[Tuple[str, float, float, bool]] = [
    # label,      lo_days, hi_days, liquidity_at_time_unverifiable(<14d)
    ("<24h",       0.0,     1.0,     True),
    ("1-3d",       1.0,     3.0,     True),
    ("3-7d",       3.0,     7.0,     True),
    ("7-14d",      7.0,     14.0,    True),
    ("14-30d",     14.0,    30.0,    False),
    ("30-90d",     30.0,    90.0,    False),
    ("90-180d",    90.0,    180.0,   False),
    ("180d+",      180.0,   float("inf"), False),
]


def age_bucket_label(age_days: float) -> Optional[str]:
    if age_days is None or (isinstance(age_days, float) and math.isnan(age_days)):
        return None
    for label, lo, hi, _unver in AGE_BUCKETS:
        if lo <= age_days < hi:
            return label
    return None


# ===========================================================================
# DATA STORE
# ===========================================================================

class MicrocapStore:
    def __init__(self, verbose: bool = False):
        clean = load_clean_universe()
        meta_by_mint = load_metadata_by_mint()
        frames: Dict[str, pd.DataFrame] = {}
        info: Dict[str, dict] = {}
        skipped: List[str] = []
        for coin in clean:
            sym = coin["symbol"]
            df = load_ohlcv_day(coin["ohlcv_day_path"])
            if df is None or len(df) < MIN_DAY_CANDLES:
                skipped.append(sym)
                continue
            meta = meta_by_mint.get(coin["mint"], {})
            static_liq = coin.get("liquidity_usd")
            f = compute_indicators(df, meta, static_liq)
            key = sym  # symbols are unique within the clean set
            frames[key] = f
            label, cost_bps, cost_rng = cost_bucket_for_liquidity(static_liq)
            info[key] = {
                "symbol": sym,
                "mint": coin["mint"],
                "liquidity_usd": static_liq,
                "organic_score": coin.get("organic_score"),
                "fdv_usd": meta.get("fdv_usd"),
                "mcap_usd": meta.get("mcap_usd") or coin.get("mcap_usd"),
                "pair_created_at": meta.get("pair_created_at"),
                "meta_age_days": meta.get("age_days"),
                "cost_label": label,
                "cost_bps": cost_bps,
                "cost_range_bps": cost_rng,
                "n_bars": len(f),
                "first": f["dt"].iloc[0],
                "last": f["dt"].iloc[-1],
            }
            if verbose:
                print(f"  loaded {sym:<11s} n={len(f):<4d} {f['dt'].iloc[0].date()} -> {f['dt'].iloc[-1].date()} "
                      f"liq=${static_liq:,.0f} cost={cost_bps:.1f}bps ({label})")

        self.frames = frames
        self.info = info
        self.skipped = skipped
        self._attach_cross_sectional()
        if frames:
            self.global_start = min(f["dt"].iloc[0] for f in frames.values())
            self.global_end = max(f["dt"].iloc[-1] for f in frames.values())
        else:
            self.global_start = self.global_end = None

    def _attach_cross_sectional(self) -> None:
        """Panel-level, PER-DATE, entry-time-safe rankings (M21) and breadth
        (M22). Each uses only that date's own already-entry-time-safe trailing
        returns -- no future info crosses the cross-section."""
        if not self.frames:
            return
        rs = pd.DataFrame({s: df.set_index("dt")["ret3"] for s, df in self.frames.items()}).sort_index()
        rs_rank = rs.rank(axis=1, pct=True, na_option="keep")
        # breadth: fraction of coins with positive trailing 7d return, per date
        br = pd.DataFrame({s: df.set_index("dt")["ret7"] for s, df in self.frames.items()}).sort_index()
        breadth = (br > 0).sum(axis=1) / br.notna().sum(axis=1).replace(0, np.nan)
        for s, df in self.frames.items():
            df["rel_strength_rank"] = rs_rank[s].reindex(df["dt"]).values
            df["breadth7"] = breadth.reindex(df["dt"]).values
        # cluster (M23): pairwise correlation of daily returns across full panel.
        # NOTE: correlation is computed on the FULL sample -> a mild, DISCLOSED
        # structural look-ahead (cluster membership is a slow, near-static
        # property of a coin's theme, not a per-bar tradeable signal). The
        # laggard TRIGGER itself (ret3 vs cluster-median ret3) is strictly
        # entry-time-safe; only the cluster-definition uses full-sample corr.
        ret1 = pd.DataFrame({s: df.set_index("dt")["ret1"] for s, df in self.frames.items()}).sort_index()
        self._corr = ret1.corr(min_periods=20)
        # cluster-median trailing 3d return per date (over each coin's cluster peers)
        syms = list(self.frames.keys())
        for s in syms:
            peers = [o for o in syms if o != s and self._corr.get(s, {}).get(o, np.nan) >= CLUSTER_CORR_MIN]
            self.info[s]["cluster_peers"] = peers
            if peers:
                peer_ret3 = pd.DataFrame({p: self.frames[p].set_index("dt")["ret3"] for p in peers}).sort_index()
                cluster_med = peer_ret3.median(axis=1)
            else:
                cluster_med = pd.Series(np.nan, index=ret1.index)
            self.frames[s]["cluster_med_ret3"] = cluster_med.reindex(self.frames[s]["dt"]).values

    def symbols(self) -> List[str]:
        return list(self.frames.keys())

    def calendar_split_date(self) -> pd.Timestamp:
        """Single calendar cutoff = midpoint of the COMBINED observed range
        across all coins (A3: not a per-coin percentile split)."""
        return self.global_start + (self.global_end - self.global_start) / 2.0


# ===========================================================================
# STATS (net-of-cost, permutation p-value, CVaR/worst-episode tail)
# ===========================================================================

@dataclass
class HorizonStats:
    n: int
    wr_gross: Optional[float]
    wr_net: Optional[float]
    mean_gross: Optional[float]
    mean_net: Optional[float]
    median_net: Optional[float]
    cvar5_net: Optional[float]
    worst_net: Optional[float]         # A4.7 rug/tail-loss: single worst episode
    p_value: Optional[float]           # permutation p on NET returns vs matched NET baseline
    baseline_n: int
    baseline_mean_net: Optional[float]

    @property
    def underpowered(self) -> bool:
        return self.n < SIGNIFICANCE_N


@dataclass
class SplitStats:
    split_name: str
    n_episodes: int
    n_coins: int
    dominance_frac: float
    dominance_flag: bool
    per_horizon: Dict[int, HorizonStats]


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _permutation_p_value(a: np.ndarray, b: np.ndarray, iters: int, rng: np.random.Generator,
                         max_baseline: int = 3000) -> Optional[float]:
    """Two-sided permutation p-value for H0: mean(a)==mean(b). `a` = event NET
    returns, `b` = matched-baseline NET returns. Vectorized. `b` subsampled to
    max_baseline if larger (bounded runtime), disclosed not silent."""
    a = np.asarray(a, dtype=float); a = a[~np.isnan(a)]
    b = np.asarray(b, dtype=float); b = b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return None
    if len(b) > max_baseline:
        b = b[rng.choice(len(b), size=max_baseline, replace=False)]
    n_a = len(a)
    pooled = np.concatenate([a, b])
    obs = abs(a.mean() - b.mean())
    keys = rng.random((iters, len(pooled)))
    order = np.argsort(keys, axis=1)
    vals_a = pooled[order[:, :n_a]]
    vals_b = pooled[order[:, n_a:]]
    diffs = np.abs(vals_a.mean(axis=1) - vals_b.mean(axis=1))
    return float((np.sum(diffs >= obs - 1e-15) + 1) / (iters + 1))


def _dedup_indices(idxs: np.ndarray, gap_bars: int) -> np.ndarray:
    """Collapse a run of consecutive (within gap_bars) same-coin trigger indices
    into one independent episode, keeping the FIRST -- the pseudoreplication
    fix (A3 collapse rule #1 / confluence_harness _dedup_trigger_indices)."""
    if len(idxs) == 0:
        return idxs
    idxs = np.sort(idxs)
    kept = [idxs[0]]
    for i in idxs[1:]:
        if i - kept[-1] > gap_bars:
            kept.append(i)
    return np.array(kept)


def _event_returns(df: pd.DataFrame, idxs: List[int], horizon: int, side: str) -> Tuple[List[float], List[float]]:
    col = f"fwd_raw_{horizon}"
    if col not in df.columns or not idxs:
        return [], []
    fwd = df[col].values
    cost = df["cost_bps"].values
    g, nt = [], []
    for i in idxs:
        raw = fwd[i]
        if pd.isna(raw):
            continue
        gross = -raw if side == "short" else raw
        g.append(float(gross))
        nt.append(float(gross - cost[i] / 10000.0))
    return g, nt


def _baseline_returns(df: pd.DataFrame, event_idxs: List[int], horizon: int, side: str,
                      gap_bars: int = 1) -> Tuple[List[float], List[float]]:
    """Non-event bars for this coin (excluding a gap buffer around each event),
    a matched comparison population costed by the coin's own bucket."""
    n = len(df)
    excluded = set()
    for i in event_idxs:
        for j in range(max(0, i - gap_bars), min(n, i + gap_bars + 1)):
            excluded.add(j)
    col = f"fwd_raw_{horizon}"
    if col not in df.columns:
        return [], []
    fwd = df[col].values
    cost = df["cost_bps"].values
    g, nt = [], []
    for i in range(n):
        if i in excluded or pd.isna(fwd[i]):
            continue
        gross = -fwd[i] if side == "short" else fwd[i]
        g.append(float(gross))
        nt.append(float(gross - cost[i] / 10000.0))
    return g, nt


def _horizon_stats(ev_g, ev_n, base_g, base_n, rng, iters) -> HorizonStats:
    n = len(ev_n)
    if n == 0:
        return HorizonStats(0, None, None, None, None, None, None, None, None, len(base_n), None)
    ag, an = np.array(ev_g, float), np.array(ev_n, float)
    k = max(1, int(math.ceil(CVAR_TAIL_FRAC * n)))
    p = None
    if n >= SIGNIFICANCE_N and base_n:
        p = _permutation_p_value(an, np.array(base_n, float), iters, rng)
    return HorizonStats(
        n=n, wr_gross=float((ag > 0).mean()), wr_net=float((an > 0).mean()),
        mean_gross=float(ag.mean()), mean_net=float(an.mean()), median_net=float(np.median(an)),
        cvar5_net=float(np.sort(an)[:k].mean()), worst_net=float(an.min()),
        p_value=p, baseline_n=len(base_n),
        baseline_mean_net=float(np.mean(base_n)) if base_n else None,
    )


def _build_split(name: str, events_by_coin: Dict[str, List[int]], frames: Dict[str, pd.DataFrame],
                 side: str, rng, iters) -> SplitStats:
    n_ep = sum(len(v) for v in events_by_coin.values())
    counts = {s: len(v) for s, v in events_by_coin.items() if v}
    n_coins = len(counts)
    dom = (max(counts.values()) / n_ep) if n_ep else 0.0
    per_h: Dict[int, HorizonStats] = {}
    for h in HORIZONS_DAYS:
        eg, en, bg, bn = [], [], [], []
        for s, idxs in events_by_coin.items():
            if not idxs:
                continue
            df = frames[s]
            g, nt = _event_returns(df, idxs, h, side)
            eg += g; en += nt
            b_g, b_n = _baseline_returns(df, idxs, h, side)
            bg += b_g; bn += b_n
        per_h[h] = _horizon_stats(eg, en, bg, bn, rng, iters)
    return SplitStats(name, n_ep, n_coins, dom, dom >= SINGLE_COIN_DOMINANCE_WARN, per_h)


# ===========================================================================
# HYPOTHESIS DEFINITION + RUNNER
# ===========================================================================

@dataclass
class Hypothesis:
    hid: str                                   # e.g. "M19_turnover_spike_long"
    label: str
    side: str                                  # "long" | "short"
    mask_fn: Callable[[pd.DataFrame, str, "MicrocapStore"], pd.Series]
    notes: str = ""


@dataclass
class HypoResult:
    hid: str
    label: str
    side: str
    notes: str
    n_raw_triggers: int
    full: SplitStats
    train: SplitStats
    test: SplitStats
    split_date: pd.Timestamp
    coins_with_events: List[str]


def run_hypothesis(hyp: Hypothesis, store: MicrocapStore, iters: int = PERM_ITERS_DEFAULT,
                   seed: int = PERM_SEED) -> HypoResult:
    rng = np.random.default_rng(seed)
    sd = store.calendar_split_date()
    gap_bars = max(1, round(DEDUP_GAP_DAYS))
    ev_all: Dict[str, List[int]] = {}
    ev_train: Dict[str, List[int]] = {}
    ev_test: Dict[str, List[int]] = {}
    n_raw = 0
    for s in store.symbols():
        df = store.frames[s]
        mask = hyp.mask_fn(df, s, store).fillna(False).astype(bool)
        n_raw += int(mask.sum())
        idxs = list(_dedup_indices(np.where(mask.values)[0], gap_bars))
        ev_all[s] = idxs
        is_train = (df["dt"] < sd).values
        ev_train[s] = [i for i in idxs if is_train[i]]
        ev_test[s] = [i for i in idxs if not is_train[i]]
    full = _build_split("full", ev_all, store.frames, hyp.side, rng, iters)
    train = _build_split("train", ev_train, store.frames, hyp.side, rng, iters)
    test = _build_split("test", ev_test, store.frames, hyp.side, rng, iters)
    return HypoResult(hyp.hid, hyp.label, hyp.side, hyp.notes, n_raw, full, train, test, sd,
                      [s for s, v in ev_all.items() if v])


# ===========================================================================
# THE 7 HISTORY-TESTABLE HYPOTHESES (MICROCAP_CAMPAIGN.md Part C)
# M1, M4, M7, M19, M21, M22, M23. M1 expands into one directional test per
# age bucket that has data; M4 and M7 are calibration/underpowered by
# construction (reported descriptively, NOT scored into the FDR family).
# ===========================================================================

def _mask_turnover_spike(df, s, store):        # M19
    return df["turnover_z"] >= TURNOVER_Z_TRIGGER

def _mask_rs_top_quintile(df, s, store):       # M21
    return df["rel_strength_rank"] >= RS_TOP_QUINTILE

def _mask_high_breadth(df, s, store):          # M22 (regime gate operationalized: buy long in high-breadth regime)
    med = np.nanmedian(df["breadth7"].values)
    return df["breadth7"] > med

def _mask_cluster_laggard(df, s, store):       # M23
    return (df["ret3"] + CLUSTER_LAG_GAP < df["cluster_med_ret3"]) & (df["cluster_med_ret3"] > 0)

def _mask_age_bucket(bucket_label: str):       # M1 (one test per bucket)
    def fn(df, s, store):
        return df["age_days"].apply(lambda a: age_bucket_label(a) == bucket_label)
    return fn


def build_scored_family(store: MicrocapStore) -> List[Hypothesis]:
    """The DIRECTIONAL, p-value-scored FDR family. M19 is run BOTH long and
    short (direction TBD by TRAIN per campaign -> both directions enter the
    family as their own comparisons, never a free look). M1 contributes one
    long test per age bucket that has >=1 coin with data. M4/M7 are NOT here
    (calibration / structurally underpowered -- see run_descriptive)."""
    fam: List[Hypothesis] = [
        Hypothesis("M19_turnover_spike_long", "M19 turnover-spike (vol/liq z>=2), LONG", "long",
                   _mask_turnover_spike, "[LIQUIDITY-AT-TIME UNVERIFIED] denom = static liquidity"),
        Hypothesis("M19_turnover_spike_short", "M19 turnover-spike (vol/liq z>=2), SHORT", "short",
                   _mask_turnover_spike, "[LIQUIDITY-AT-TIME UNVERIFIED] denom = static liquidity"),
        Hypothesis("M21_rs_top_quintile_long", "M21 cross-sectional top-quintile rel-strength, LONG", "long",
                   _mask_rs_top_quintile, "meme-peer rotation within the 12-coin panel"),
        Hypothesis("M22_high_breadth_long", "M22 buy-LONG in high meme-breadth regime", "long",
                   _mask_high_breadth, "regime gate operationalized as a conditioned long"),
        Hypothesis("M23_cluster_laggard_long", "M23 correlated-cluster laggard convergence, LONG", "long",
                   _mask_cluster_laggard, "cluster def uses full-sample corr (disclosed structural look-ahead); trigger is entry-time-safe"),
    ]
    # M1: only add buckets that actually have episodes somewhere (avoids
    # cluttering the family with structurally-empty <14d buckets, though we
    # still REPORT their emptiness as the honest A1e finding).
    for label, _lo, _hi, unver in AGE_BUCKETS:
        has = False
        for s in store.symbols():
            if store.frames[s]["age_days"].apply(lambda a: age_bucket_label(a) == label).any():
                has = True
                break
        if has:
            tag = " [LIQUIDITY-AT-TIME UNVERIFIED, age<14d]" if unver else ""
            fam.append(Hypothesis(f"M1_age_{label}_long", f"M1 age-bucket {label} forward return, LONG", "long",
                                  _mask_age_bucket(label), "age = days since pair_created_at" + tag))
    return fam


# ===========================================================================
# BH-FDR (+ Bonferroni companion)
# ===========================================================================

def benjamini_hochberg(pvalues: List[Optional[float]], alpha: float) -> List[bool]:
    n = len(pvalues)
    idxs = [i for i, p in enumerate(pvalues) if p is not None]
    m = len(idxs)
    reject = [False] * n
    if m == 0:
        return reject
    order = sorted(idxs, key=lambda i: pvalues[i])
    max_k = 0
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= (rank / m) * alpha:
            max_k = rank
    for rank, i in enumerate(order, start=1):
        if rank <= max_k:
            reject[i] = True
    return reject


@dataclass
class FamilyEntry:
    hid: str
    horizon: int
    train_n: int
    train_p: Optional[float]
    train_mean_net: Optional[float]
    train_mean_gross: Optional[float]
    test_n: int
    test_p: Optional[float]
    test_mean_net: Optional[float]
    worst_net: Optional[float]
    dominance_flag: bool
    fdr_survivor: bool = False
    bonferroni_survivor: bool = False
    confirmed: bool = False


def score_family(results: List[HypoResult], alpha: float = FDR_ALPHA) -> Tuple[List[FamilyEntry], Dict[str, Any]]:
    """One family across every scored hypothesis x every horizon. BH-FDR on
    TRAIN p-values; a CONFIRMED survivor must (a) clear BH-FDR on train, (b)
    independently clear p<0.05 on TEST with the SAME sign of net edge, (c)
    have test n>=SIGNIFICANCE_N, and (d) not be single-coin dominated. Bonferroni
    reported alongside (A3)."""
    entries: List[FamilyEntry] = []
    for r in results:
        for h in HORIZONS_DAYS:
            tr = r.train.per_horizon.get(h)
            te = r.test.per_horizon.get(h)
            entries.append(FamilyEntry(
                hid=f"{r.hid}@{h}d", horizon=h,
                train_n=tr.n if tr else 0, train_p=tr.p_value if tr else None,
                train_mean_net=tr.mean_net if tr else None, train_mean_gross=tr.mean_gross if tr else None,
                test_n=te.n if te else 0, test_p=te.p_value if te else None,
                test_mean_net=te.mean_net if te else None,
                worst_net=(te.worst_net if te and te.n else (tr.worst_net if tr else None)),
                dominance_flag=(r.train.dominance_flag or r.test.dominance_flag),
            ))
    train_p = [e.train_p for e in entries]
    reject = benjamini_hochberg(train_p, alpha)
    n_tested = sum(1 for p in train_p if p is not None)
    bonf_alpha = (0.05 / n_tested) if n_tested else 0.05
    for e, surv in zip(entries, reject):
        e.fdr_survivor = surv
        e.bonferroni_survivor = bool(e.train_p is not None and e.train_p <= bonf_alpha)
        same_sign = (e.train_mean_net is not None and e.test_mean_net is not None and
                     np.sign(e.train_mean_net) == np.sign(e.test_mean_net) and e.train_mean_net != 0)
        e.confirmed = bool(surv and e.test_p is not None and e.test_p < 0.05 and
                           e.test_n >= SIGNIFICANCE_N and same_sign and not e.dominance_flag)
    diag = {
        "n_tested": n_tested,
        "alpha": alpha,
        "expected_false_positives": n_tested * alpha,
        "bonferroni_alpha": bonf_alpha,
        "n_fdr_survivors": sum(1 for e in entries if e.fdr_survivor),
        "n_bonferroni": sum(1 for e in entries if e.bonferroni_survivor),
        "n_confirmed": sum(1 for e in entries if e.confirmed),
        "perm_resolution_floor": 1.0 / (PERM_ITERS_DEFAULT + 1),
        "strictest_bh_critical": (alpha / n_tested) if n_tested else None,
    }
    return entries, diag


# ===========================================================================
# DESCRIPTIVE / CALIBRATION READOUTS (M4 vol-vs-age, M7 liq-to-FDV) --
# reported honestly as calibration / structurally-underpowered, NOT scored.
# ===========================================================================

def descriptive_m4(store: MicrocapStore) -> Dict[str, dict]:
    """M4: realized-vol & wick-range by age bucket -> a defensible age floor.
    Pooled across coins, dedup not applicable (calibration, not a test).
    Reports n_bars, so the reader sees which buckets have any HISTORY at all."""
    out: Dict[str, dict] = {}
    for label, _lo, _hi, _u in AGE_BUCKETS:
        rvols, wicks, coins = [], [], set()
        for s in store.symbols():
            df = store.frames[s]
            in_b = df["age_days"].apply(lambda a: age_bucket_label(a) == label)
            if in_b.any():
                coins.add(s)
                rvols += list(df.loc[in_b, "rvol14"].dropna().values)
                wicks += list(df.loc[in_b, "wick_range"].dropna().values)
        out[label] = {
            "n_bars": len(rvols), "n_coins": len(coins),
            "median_rvol14": float(np.median(rvols)) if rvols else None,
            "median_wick_range": float(np.median(wicks)) if wicks else None,
        }
    return out


def descriptive_m7(store: MicrocapStore) -> dict:
    """M7: liquidity-to-FDV ratio (static snapshot) vs forward risk-adjusted
    return. STRUCTURALLY UNDERPOWERED: the ratio is one static number per coin,
    so the independent N is the number of COINS (<=12), never the number of
    autocorrelated daily bars -> below SIGNIFICANCE_N=30 by construction.
    Reported descriptively only, never as a p-value (A3)."""
    rows = []
    for s in store.symbols():
        info = store.info[s]
        liq, fdv = info.get("liquidity_usd"), info.get("fdv_usd")
        ratio = (liq / fdv) if (liq and fdv and fdv > 0) else None
        df = store.frames[s]
        fwd7 = df["fwd_raw_7"].dropna()
        cost = info["cost_bps"] / 10000.0
        mean_net7 = float(fwd7.mean() - cost) if len(fwd7) else None
        vol7 = float(fwd7.std(ddof=0)) if len(fwd7) > 1 else None
        rows.append({"symbol": s, "liq_to_fdv": ratio, "mean_net_fwd7": mean_net7, "vol_fwd7": vol7})
    return {"n_coins": len(rows), "rows": rows,
            "note": f"independent N = {len(rows)} coins < SIGNIFICANCE_N={SIGNIFICANCE_N} -> UNDERPOWERED, descriptive only"}


# ===========================================================================
# REPORTING
# ===========================================================================

def _fmt_pct(x: Optional[float]) -> str:
    return f"{x*100:+.2f}%" if x is not None else "  n/a "


def _fmt_p(p: Optional[float]) -> str:
    return f"{p:.4f}" if p is not None else "n/a"


def print_run_report(store: MicrocapStore, results: List[HypoResult],
                     entries: List[FamilyEntry], diag: Dict[str, Any],
                     m4: Dict[str, dict], m7: dict) -> None:
    print("=" * 90)
    print("WAGMI MICRO-CAP HISTORY HARNESS -- RESULTS  [SLIPPAGE-NAIVE UPPER BOUND]")
    print("=" * 90)
    print("*** This is a slippage-naive UPPER BOUND on ALREADY-SURVIVED coins (survivorship:")
    print("*** these 12 are alive today; dead clones were excluded). NOT a tradeable backtest.")
    print("*** HISTORY track = ORIGIN/UNVALIDATED: any survivor is a lead for a FORWARD re-test,")
    print("*** never an edge, never a trade. Net returns subtract the MICROCAP_CAMPAIGN.md A1d")
    print("*** per-liquidity DEX round-trip cost (keyed to a SINGLE current-state liquidity")
    print("*** snapshot -> [LIQUIDITY-AT-TIME UNVERIFIED]). [MEV/PRIORITY-FEE UNMODELED].")
    print("=" * 90)

    print("\n-- UNIVERSE (clean: wash_heavy==false, organic_score>=40) --")
    print(f"loaded {len(store.frames)} coins, skipped {len(store.skipped)}: {store.skipped}")
    print(f"combined calendar range: {store.global_start.date()} -> {store.global_end.date()}")
    print(f"OOS calendar split (midpoint, single cutoff for all coins): {store.calendar_split_date().date()}")
    print(f"pseudoreplication: consecutive same-coin triggers within {DEDUP_GAP_DAYS}d collapse to 1 episode.")
    print(f"same-day serial-launch collapse (A3 rule #2): N/A -- these are established coins, not a launch cohort.")
    print(f"\n{'coin':<11s}{'liq_usd':>13s}{'cost_bps':>9s}  {'bucket':<26s}{'bars':>5s}  range")
    for s in store.symbols():
        i = store.info[s]
        print(f"{s:<11s}{i['liquidity_usd']:>13,.0f}{i['cost_bps']:>9.1f}  {i['cost_label']:<26s}{i['n_bars']:>5d}  "
              f"{i['first'].date()}->{i['last'].date()}")

    print("\n-- FAMILY (BH-FDR q={:.2f}, one family across all scored hypotheses x horizons) --".format(diag["alpha"]))
    print(f"n_tested (train p-values available) = {diag['n_tested']}   "
          f"expected false positives @q = {diag['expected_false_positives']:.2f}")
    print(f"Bonferroni companion alpha = {diag['bonferroni_alpha']:.5f}   "
          f"perm resolution floor = 1/(iters+1) = {diag['perm_resolution_floor']:.5f}   "
          f"strictest BH critical = {_fmt_p(diag['strictest_bh_critical'])}")
    if diag["strictest_bh_critical"] is not None and diag["perm_resolution_floor"] > diag["strictest_bh_critical"]:
        print("  NOTE: perm resolution floor is coarser than the strictest BH critical value -- a")
        print("        dead-certain edge could still clear via a LESS strict rank; not a concern for a null.")

    print("\n-- PER-HYPOTHESIS (net-of-cost; gross shown so cost drag is visible; worst = single-episode rug check) --")
    hdr = f"{'hypothesis@h':<34s}{'trN':>5s}{'trP':>8s}{'tr_net':>9s}{'tr_gr':>9s}{'teN':>5s}{'teP':>8s}{'te_net':>9s}{'worst':>9s} flags"
    print(hdr)
    print("-" * len(hdr))
    by_hid = {r.hid: r for r in results}
    for e in entries:
        base_hid = e.hid.split("@")[0]
        r = by_hid.get(base_hid)
        flags = []
        if e.dominance_flag:
            flags.append("SINGLE-COIN-DOM")
        if e.train_n < SIGNIFICANCE_N:
            flags.append(f"trUNDERPWR(n={e.train_n})")
        if e.fdr_survivor:
            flags.append("FDR")
        if e.bonferroni_survivor:
            flags.append("BONF")
        if e.confirmed:
            flags.append("*** CONFIRMED ***")
        print(f"{e.hid:<34s}{e.train_n:>5d}{_fmt_p(e.train_p):>8s}{_fmt_pct(e.train_mean_net):>9s}"
              f"{_fmt_pct(e.train_mean_gross):>9s}{e.test_n:>5d}{_fmt_p(e.test_p):>8s}"
              f"{_fmt_pct(e.test_mean_net):>9s}{_fmt_pct(e.worst_net):>9s} {' '.join(flags)}")

    print("\n-- SURVIVOR TABLE --")
    survivors = [e for e in entries if e.confirmed]
    if not survivors:
        print("  0 survived. (Clean null. This is the correct, honest result -- see bottom line.)")
    else:
        for e in survivors:
            print(f"  CONFIRMED: {e.hid}  train(n={e.train_n},p={_fmt_p(e.train_p)},net={_fmt_pct(e.train_mean_net)})  "
                  f"test(n={e.test_n},p={_fmt_p(e.test_p)},net={_fmt_pct(e.test_mean_net)})  worst_ep={_fmt_pct(e.worst_net)}")

    print("\n-- M1 AGE-BUCKET COVERAGE (A1e: HISTORY cannot see a coin's first days if it predates the 180d window) --")
    for label, _lo, _hi, unver in AGE_BUCKETS:
        n_bars = sum(int(store.frames[s]["age_days"].apply(lambda a: age_bucket_label(a) == label).sum())
                     for s in store.symbols())
        tag = " [LIQUIDITY-AT-TIME UNVERIFIED]" if unver else ""
        status = "no HISTORY data" if n_bars == 0 else f"{n_bars} bar(s)"
        print(f"    {label:<9s} {status}{tag}")

    print("\n-- M4 VOLATILITY-VS-AGE (calibration only, NOT scored -> age floor) --")
    for label, info in m4.items():
        if info["n_bars"] == 0:
            print(f"    {label:<9s} no data")
        else:
            print(f"    {label:<9s} n_bars={info['n_bars']:<5d} coins={info['n_coins']:<2d} "
                  f"median_rvol14={info['median_rvol14']:.4f} median_wick_range={info['median_wick_range']:.4f}")

    print("\n-- M7 LIQUIDITY-TO-FDV (structurally UNDERPOWERED: N = coins < 30, descriptive only) --")
    print(f"    {m7['note']}")
    for row in sorted(m7["rows"], key=lambda r: (r["liq_to_fdv"] is None, r["liq_to_fdv"] or 0)):
        r = row["liq_to_fdv"]
        print(f"    {row['symbol']:<11s} liq/fdv={('n/a' if r is None else f'{r:.4f}'):>8s}  "
              f"mean_net_fwd7={_fmt_pct(row['mean_net_fwd7'])}  vol_fwd7={_fmt_pct(row['vol_fwd7'])}")

    print("\n-- REFUTE-YOURSELF (A4) --")
    print("  A4.6 WASH-DRIVEN: organic-vs-raw re-run needs Jupiter organic HISTORY (does not exist,")
    print("       FORWARD-only). Mitigation: universe pre-filtered to organic_score>=40 before any test.")
    print("  A4.7 RUG/TAIL-LOSS: worst single-episode net return printed per hypothesis above.")
    print("  A5.2 SINGLE-COIN DOMINANCE: flagged per hypothesis; with so few names it is disqualifying.")
    print("=" * 90)


# ===========================================================================
# INVENTORY
# ===========================================================================

def run_inventory() -> None:
    store = MicrocapStore(verbose=True)
    print(f"\nclean coins loaded: {len(store.frames)}; skipped: {store.skipped}")
    if store.global_start:
        print(f"combined range: {store.global_start.date()} -> {store.global_end.date()}")
        print(f"OOS midpoint split: {store.calendar_split_date().date()}")
    print("\nHISTORY-testable per Part C: M1(age), M4(vol-vs-age calib), M7(liq/FDV static),")
    print("M19(turnover), M21(rotation), M22(breadth), M23(cluster laggard).")


# ===========================================================================
# SELF-TEST -- negative control (the load-bearing anti-p-hacking proof) plus
# planted-edge recovery, BH mechanics, and OOS train-only rejection.
# ===========================================================================

def _synth_store_from_frames(frames: Dict[str, pd.DataFrame]) -> MicrocapStore:
    store = MicrocapStore.__new__(MicrocapStore)
    store.frames = frames
    store.info = {s: {"symbol": s, "liquidity_usd": 3_000_000.0, "cost_bps": 27.5,
                      "cost_label": "synthetic", "cost_range_bps": (15.0, 40.0), "fdv_usd": None,
                      "mcap_usd": None, "pair_created_at": None, "n_bars": len(f),
                      "first": f["dt"].iloc[0], "last": f["dt"].iloc[-1]} for s, f in frames.items()}
    store.skipped = []
    store.global_start = min(f["dt"].iloc[0] for f in frames.values())
    store.global_end = max(f["dt"].iloc[-1] for f in frames.values())
    return store


def _mk_frame(rng: np.random.Generator, n: int, start: str, trigger_col: str,
              trigger_idx: List[int], edge: float, cost_bps: float = 27.5) -> pd.DataFrame:
    """Random-walk daily closes; at each trigger index, force a signal value in
    `trigger_col` and (if edge!=0) a genuine forward bounce over the next bars."""
    dts = pd.date_range(start, periods=n, freq="D", tz="UTC")
    ret = rng.normal(0, 0.03, n)
    trig = np.zeros(n, dtype=bool)
    for i in trigger_idx:
        if 0 <= i < n:
            trig[i] = True
            if edge != 0:
                for k in range(1, 4):
                    if i + k < n:
                        ret[i + k] += edge / 3.0
    closes = 100.0 * np.cumprod(1 + ret)
    df = pd.DataFrame({
        "dt": dts, "o": closes, "h": closes * 1.01, "l": closes * 0.99, "c": closes,
        "v": np.abs(rng.normal(1e5, 1e4, n)),
    })
    for k in HORIZONS_DAYS:
        df[f"fwd_raw_{k}"] = df["c"].shift(-k) / df["c"] - 1.0
    df["cost_bps"] = cost_bps
    df["ret1"] = df["c"].pct_change(1)
    df["ret3"] = df["c"].pct_change(3)
    df["ret7"] = df["c"].pct_change(7)
    df["rvol14"] = df["ret1"].shift(1).rolling(14, min_periods=7).std(ddof=0)
    df["wick_range"] = (df["h"] - df["l"]) / df["c"]
    df["turnover"] = np.nan
    df["turnover_z"] = 0.0
    df["age_days"] = np.arange(n, dtype=float) + 200.0
    df["rel_strength_rank"] = 0.5
    df["breadth7"] = 0.5
    df["cluster_med_ret3"] = np.nan
    df["_synthtrig"] = trig
    return df


def selftest_bh_mechanics() -> bool:
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    got = benjamini_hochberg(pvals, alpha=0.05)
    exp = [True, True, False, False, False, False, False, False, False, False]
    ok1 = got == exp
    ok2 = all(benjamini_hochberg([0.001] * 10, 0.05))
    ok3 = not any(benjamini_hochberg([0.9] * 10, 0.05))
    print(f"  [BH] step-up={got==exp}, all-sig={ok2}, all-null={ok3}: {'PASS' if (ok1 and ok2 and ok3) else 'FAIL'}")
    return ok1 and ok2 and ok3


def selftest_negative_control() -> bool:
    """THE load-bearing proof: many PURE-NOISE hypotheses (random triggers, no
    relation to forward returns) on real-shaped random-walk data -> the FDR +
    OOS-confirmation layer must return ~0 confirmed survivors. If it doesn't,
    the harness manufactures false positives and must not be trusted."""
    rng = np.random.default_rng(2026)
    frames = {}
    for si in range(8):
        n = 400
        frames[f"NOISE_{si}"] = _mk_frame(rng, n, "2025-01-01", "_synthtrig",
                                          sorted(rng.choice(range(n - 10), size=90, replace=False).tolist()),
                                          edge=0.0)
    store = _synth_store_from_frames(frames)

    # 120 independent noise hypotheses: each flags a fresh random ~20-35% of bars
    results: List[HypoResult] = []
    n_specs = 120
    for j in range(n_specs):
        hrng = np.random.default_rng(5000 + j)
        masks = {s: pd.Series(hrng.random(len(store.frames[s])) < hrng.uniform(0.2, 0.35),
                              index=store.frames[s].index) for s in store.symbols()}
        side = "long" if j % 2 == 0 else "short"
        hyp = Hypothesis(f"NULL_{j:03d}", "noise", side,
                         (lambda ms: (lambda df, s, st: ms[s]))(masks))
        results.append(run_hypothesis(hyp, store, iters=400, seed=7000 + j))
    entries, diag = score_family(results, alpha=FDR_ALPHA)
    n_conf = diag["n_confirmed"]
    # expected false positives at q=0.10 across the family; allow a small slack.
    ok = n_conf <= max(3, int(0.03 * diag["n_tested"]))
    print(f"  [neg-control] {n_specs} noise hypotheses x {len(HORIZONS_DAYS)} horizons: "
          f"n_tested={diag['n_tested']}, expected_FP@q={diag['expected_false_positives']:.1f}, "
          f"FDR_survivors={diag['n_fdr_survivors']}, CONFIRMED={n_conf}: "
          f"{'PASS (~0 survivors on noise)' if ok else 'FAIL -- harness manufactures false positives'}")
    return ok, n_conf


def selftest_planted_edge() -> bool:
    """A genuine forward edge planted on a random-trigger column spanning train
    AND test must be recovered: train & test both significant, same sign, net>0
    after cost, and CONFIRMED in the family."""
    rng = np.random.default_rng(11)
    frames = {}
    for si in range(6):
        n = 400
        trigs = sorted(rng.choice(range(n - 10), size=90, replace=False).tolist())
        f = _mk_frame(rng, n, "2025-01-01", "_synthtrig", trigs, edge=0.12)  # +12% bounce, big vs 27.5bps cost
        frames[f"EDGE_{si}"] = f
    store = _synth_store_from_frames(frames)
    hyp = Hypothesis("PLANTED", "planted edge", "long", lambda df, s, st: df["_synthtrig"])
    r = run_hypothesis(hyp, store, iters=1000)
    tr = r.train.per_horizon[3]; te = r.test.per_horizon[3]
    ok = (tr.n >= SIGNIFICANCE_N and te.n >= SIGNIFICANCE_N and
          tr.p_value is not None and tr.p_value < 0.05 and tr.mean_net > 0 and
          te.p_value is not None and te.p_value < 0.05 and te.mean_net > 0)
    entries, diag = score_family([hyp and r], alpha=FDR_ALPHA)
    conf = any(e.confirmed for e in entries)
    print(f"  [planted] train n={tr.n} p={_fmt_p(tr.p_value)} net={_fmt_pct(tr.mean_net)}; "
          f"test n={te.n} p={_fmt_p(te.p_value)} net={_fmt_pct(te.mean_net)}; confirmed={conf}: "
          f"{'PASS' if (ok and conf) else 'FAIL'}")
    return ok and conf


def selftest_oos_trainonly() -> bool:
    """An edge present ONLY in the train slice (test slice = same trigger, no
    edge) must clear train significance but be EXCLUDED from confirmed
    survivors -- proves the OOS split is decisive."""
    rng = np.random.default_rng(55)
    frames = {}
    for si in range(6):
        n = 400
        split = n // 2
        trigs_train = sorted(rng.choice(range(10, split - 10), size=60, replace=False).tolist())
        trigs_test = sorted(rng.choice(range(split + 5, n - 10), size=60, replace=False).tolist())
        f = _mk_frame(rng, n, "2025-01-01", "_synthtrig", trigs_train, edge=0.12)
        # add test-slice triggers with NO edge
        for i in trigs_test:
            f.at[i, "_synthtrig"] = True
        frames[f"TO_{si}"] = f
    store = _synth_store_from_frames(frames)
    hyp = Hypothesis("TRAINONLY", "train-only edge", "long", lambda df, s, st: df["_synthtrig"])
    r = run_hypothesis(hyp, store, iters=1000)
    tr = r.train.per_horizon[3]; te = r.test.per_horizon[3]
    train_sig = tr.n >= SIGNIFICANCE_N and tr.p_value is not None and tr.p_value < 0.05 and tr.mean_net > 0
    entries, diag = score_family([r], alpha=FDR_ALPHA)
    not_conf = not any(e.confirmed for e in entries)
    ok = train_sig and not_conf
    print(f"  [OOS] train sig+positive={train_sig}; excluded from confirmed={not_conf}: "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def run_selftest() -> int:
    print("=" * 90)
    print("MICRO-CAP HISTORY HARNESS -- SELFTEST (synthetic; no real data conclusions)")
    print("=" * 90)
    print("Proves the METHOD: BH mechanics, a PLANTED edge is recovered & confirmed, an edge that")
    print("lives only in TRAIN is correctly rejected by the OOS split, and -- the load-bearing check --")
    print("a large family of PURE-NOISE hypotheses yields ~0 confirmed survivors.\n")
    results = []
    print("-- BH-FDR mechanics --")
    results.append(selftest_bh_mechanics())
    print("\n-- Planted edge recovered + confirmed --")
    results.append(selftest_planted_edge())
    print("\n-- OOS split rejects a train-only edge --")
    results.append(selftest_oos_trainonly())
    print("\n-- NEGATIVE CONTROL: noise -> ~0 confirmed survivors --")
    neg_ok, neg_conf = selftest_negative_control()
    results.append(neg_ok)

    n_pass = sum(1 for r in results if r)
    print("\n" + "=" * 90)
    print(f"SELFTEST RESULT: {n_pass}/{len(results)} checks PASSED "
          f"(negative-control confirmed-noise-survivors = {neg_conf})")
    print("=" * 90)
    return 0 if n_pass == len(results) else 1


# ===========================================================================
# RUN (real data)
# ===========================================================================

def run_real() -> int:
    store = MicrocapStore(verbose=False)
    if len(store.frames) < 2:
        print("Not enough clean coins loaded -- aborting.")
        return 1
    family = build_scored_family(store)
    results = [run_hypothesis(h, store) for h in family]
    entries, diag = score_family(results, alpha=FDR_ALPHA)
    m4 = descriptive_m4(store)
    m7 = descriptive_m7(store)
    print_run_report(store, results, entries, diag, m4, m7)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="WAGMI micro-cap HISTORY harness (slippage-naive upper bound).")
    ap.add_argument("--selftest", action="store_true", help="synthetic method verification incl. negative control")
    ap.add_argument("--run", action="store_true", help="run the 7 HISTORY hypotheses on the clean 12-coin universe")
    ap.add_argument("--inventory", action="store_true", help="data-join feasibility readout (no conclusions)")
    args = ap.parse_args()
    if args.selftest:
        return run_selftest()
    if args.inventory:
        run_inventory()
        return 0
    if args.run:
        return run_real()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
