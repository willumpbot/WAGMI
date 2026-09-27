#!/usr/bin/env python
"""
OI Risk-Context Test - oi_risk_context_test.py
=============================================================================
STANDALONE, READ-ONLY analysis script. RISK-CONTEXT test, NOT an edge hunt
(see tools/copilot/session_vol_test.py and funding_predictiveness_test.py in
this same folder for the sibling pattern this script follows).

QUESTION: does open-interest (OI) buildup / unwind carry information about
FORWARD VOLATILITY or liquidation-cascade risk? This is distinct from the
already-tested (and refuted, see funding_predictiveness_test.py) question of
whether FUNDING predicts forward RETURN. OI measures how much leveraged
positioning is stacked in the system -- the fuel for a cascade -- not the
cost of carrying it. If rising-OI states are stably more cascade-prone (bigger
forward vol / drawdowns / tail-move frequency, not just bigger forward
RETURN), the co-pilot briefing can honestly add a risk-context note. If not,
we surface nothing.

DOES NOT import copilot.py, weather.py, or any live-co-pilot module. Sends no
Discord/Telegram messages. Writes no files. Reads only the paths listed below
and prints a report to stdout.

DATA INVENTORY (established by direct inspection before writing any test
code -- see SECTION 0 printed at runtime for the live version of this):

  OI + PRICE (the only source used -- see "why not X" notes below):
    data/funding_oi_history.jsonl -- live snapshot collector
    (tools/funding_oi_collector.py), one JSON row per symbol per scan:
    {timestamp, symbol, funding_rate, open_interest, premium, volume_24h,
     price, oi_volume_ratio}. 23 symbols total, but only 5 have enough
     history to test:
        BTC   n=3024  2026-06-06 13:20 -> 2026-08-01 03:57
        ETH   n=3029  2026-06-06 13:20 -> 2026-08-01 03:57
        SOL   n=3025  2026-06-06 13:20 -> 2026-08-01 03:57
        HYPE  n=3007  2026-06-06 13:20 -> 2026-08-01 03:57
        XRP   n=2866  2026-06-29 17:10 -> 2026-08-01 03:57
     ALL FIVE have an internal ~22-DAY collector-outage gap
     (2026-06-07 08:52 -> 2026-06-29 17:10) plus one ~4h gap on 2026-07-15.
     After the outage, cadence is regular: median ~16min between snapshots.
     Effective CONTINUOUS usable window is 2026-06-29 -> 2026-08-01, i.e.
     ~33 CALENDAR DAYS, not ~2 months as the raw first/last timestamps
     suggest. The remaining 18 symbols (longtail alts + majors like UNI,
     AAVE, DOGE, etc.) only started collecting on 2026-08-01 itself
     (7-9 rows) -- far too thin to use; excluded entirely, not padded.
     Price used is the "price" field logged IN THE SAME ROW as OI (same
     collector tick, same timestamp, same exchange) -- deliberately NOT
     joined against data/cache/*.csv or data/longtail/ohlc/*.csv, both of
     which stop at 2026-07-14 (stale, predates most of the OI window) and
     would force a lossy cross-source join for no benefit: the OI log
     already carries a same-tick price column, so self-contained is both
     simpler and more faithful here.
  WHY NOT A DEEPER/HISTORICAL OI SOURCE: tools/funding_oi_collector.py calls
     ccxt's `fetch_open_interest()`, a CURRENT-snapshot-only endpoint --
     Hyperliquid (via ccxt) exposes no historical open-interest time series
     endpoint analogous to its funding-history endpoint. There is no
     "pull HL's public OI history" option to backfill further back than
     this project's own collector has been running. This 33-day window
     (worse: single-era, no independent OOS split, see H4d) IS the ceiling
     of what's available today. tools/research/candle_cache/ has years of
     price and funding history but zero OI. This is the underpowered case
     the task explicitly anticipated.
  LIQUIDATIONS (labeled underpowered peek, not a test):
     data/copilot/liquidations/liq_events.jsonl -- bybit taker-liquidation
     tape, n=19 total (FARTCOIN=8, kSHIB=7, kPEPE=2, BTC=2), all within
     2026-08-01 01:20 -> 04:10. Only BTC's 2 events fall on a symbol with
     usable OI history above -- n=2 is reported as an anecdote, explicitly
     not a statistical test.

METHOD (entry-time-safe throughout; every feature at row t uses ONLY OI/price
data with timestamp <= t; forward vol/drawdown/tail labels are computed AFTER
feature construction and never fed back into any feature):
  All OI-history rows for a symbol are IRREGULARLY spaced (median ~16min,
  occasional gaps). Rather than resampling onto a synthetic grid (which would
  either fabricate data via forward-fill or waste real ticks), every window
  (trailing or forward) is located directly on the true timestamps via
  np.searchsorted, and a window is only trusted if it contains at least
  DENSITY_FRAC (50%) of the ticks a fully-dense window of that length would
  have at the symbol's own measured cadence -- this is what makes the
  22-day and 4h gaps self-quarantining: any trailing/forward window that
  would need to reach across a gap comes back too sparse and is dropped
  (NaN), never silently stitched. The one AS-OF backward lookup used for
  oi_roc / price_roc (value ~24h ago) additionally requires the located
  point to fall within a tight tolerance of the intended lookback --
  without this a lookup taken shortly after the outage ended would silently
  grab a point from BEFORE the 22-day gap and mislabel it "24h ago" (a
  concrete failure mode found and fixed while building this test; see
  `_asof_lookback`).

  oi_roc_24h(t)      = OI(t) / OI(t-24h) - 1   [causal, as-of, tolerance-gated]
  price_roc_24h(t)   = price(t) / price(t-24h) - 1   [same, for H2 divergence]
  oi_roc_pctile(t)   = percentile rank of oi_roc_24h(t) within the trailing
                       120h (5d) window of oi_roc_24h values STRICTLY BEFORE
                       t (never includes t itself) -- same causal-percentile
                       convention as funding_predictiveness_test.py.
  oi_state(t)        = tercile of oi_roc_pctile(t): "unwind" (<=33.3),
                       "neutral" (33.3-66.7), "buildup" (>=66.7). Terciles,
                       not deciles, deliberately -- 33 days of history make
                       decile bins too thin per bucket for the forward-vol
                       comparisons below.
  trailing_vol24(t)  = std of tick-to-tick log returns in the trailing 24h
                       [t-24h, t] -- causal. This is the OWN-BASELINE control:
                       every forward-vol comparison below is expressed as a
                       RATIO to this, so "OI buildup states see more forward
                       vol" must survive being asked "...than what this same
                       coin was already doing right before t?"
  fwd_vol_H(t)       = std of tick-to-tick log returns in (t, t+H]  [label]
  fwd_maxdd_H(t)     = min cumulative log return in (t, t+H]        [label]
  fwd_maxrun_H(t)    = max cumulative log return in (t, t+H]        [label]
  fwd_tailfreq_H(t)  = fraction of ticks in (t, t+H] with |tick return| >
                       TAIL_THRESH, where TAIL_THRESH is the POOLED (all 5
                       symbols, whole window) 90th percentile of |tick
                       return| -- a living-value threshold computed from the
                       data itself, not a hardcoded guess, and printed at
                       runtime so it's auditable.
  vol_ratio_H(t)     = fwd_vol_H(t) / trailing_vol24(t)  -- the primary
                       risk-context metric: >1 means "forward vol elevated
                       vs. this coin's own immediate past", ~1 means "no
                       information beyond what current vol already implies."
  A gap-guard invalidates (sets to NaN) the single tick-to-tick return that
  spans any gap > 60min BEFORE any of the above are computed from it, so
  neither the ~22-day nor the 4h gap contaminates trailing/forward stats
  through the raw return series itself.

HYPOTHESES TESTED (see main() for the printed report, one section per
horizon in HORIZONS_H):
  H1  OI buildup = cascade fuel: decile oi_roc_pctile, report mean
      vol_ratio/maxdd/tailfreq per decile + Spearman rank correlation with a
      block-permutation null (preserves the metric's own autocorrelation).
      Then the actionable buildup-vs-unwind-vs-neutral tercile comparison
      with block-bootstrap CIs on vol_ratio (tested against null=1.0, i.e.
      "no different from the coin's own trailing vol").
  H2  OI + price divergence: among BUILDUP rows, split by price_roc_24h
      sign. "Long buildup" (OI up, price up) vs "short buildup" (OI up,
      price down) -- does long buildup predict a bigger forward DOWNSIDE
      (maxdd) than short buildup, and does short buildup predict a bigger
      forward UPSIDE (maxrun) than long buildup? Tested as risk/tail
      asymmetry, not as a directional return signal.
  H3  OI unwind = fuel already spent: is forward vol_ratio in the unwind
      tercile LOWER than buildup (and than neutral)? (deleveraging already
      happened -> calmer forward tape.)
  H4  Self-refutation (this is the section that decides the verdict):
      (a) vol-regime control -- repeat H1's tercile spread WITHIN trailing-
          vol terciles. If the spread disappears once current vol level is
          held fixed, OI was restating vol-clustering, not adding
          information.
      (b) autocorrelation -- oi_roc_pctile's own lag-1 autocorrelation is
          reported per symbol (effective-N caveat: overlapping windows and
          persistent OI states both inflate nominal n). A non-overlapping
          (~1 sample per horizon-length block) daily-resample cross-check
          repeats the core buildup-vs-neutral test on that thinned,
          approximately-independent sample.
      (c) cross-coin consistency -- the core test run per-symbol (BTC/ETH/
          SOL/HYPE/XRP); >=4/5 same sign required to call anything
          "consistent" rather than a single-coin artifact.
      (d) era split -- the one continuous 33-day window is split into two
          halves (first half vs second half) as the closest thing to an
          OOS check this dataset allows. EXPLICITLY flagged low-power: two
          ~16-day halves is not a real out-of-sample test, just a sanity
          check against "this is a single 3-day event dressed up as a
          33-day finding."

No fee/PnL numbers are computed anywhere in this script -- this is a
volatility/tail-risk question, not a strategy backtest.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]  # .../bot
OI_LOG_PATH = ROOT / "data" / "funding_oi_history.jsonl"
LIQ_PATH = ROOT / "data" / "copilot" / "liquidations" / "liq_events.jsonl"

SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]  # the only symbols with usable OI history
MIN_ROWS_TO_USE = 500  # everything else in the log has <10 rows, excluded

OI_ROC_LOOKBACK_H = 24          # OI rate-of-change window
OI_STATE_LOOKBACK_H = 120       # 5d, causal, strictly-prior percentile window
MIN_HIST_STATE = 200            # min prior oi_roc obs before trusting pctile (~42% fill of 120h@16min)
TRAILING_VOL_H = 24             # own-baseline trailing vol window
GAP_GUARD_MIN = 60              # invalidate any single tick-to-tick return spanning a gap > this
ASOF_TOL_FACTOR = 3.0           # as-of lookback tolerance = cadence_min * this many minutes
DENSITY_FRAC = 0.5              # trailing/forward windows need >= this fraction of a fully-dense window

HORIZONS_H = {"6h": 6, "24h": 24, "48h": 48}

N_BOOTSTRAP = 2000
N_PERM = 1000
RNG = np.random.default_rng(20260801)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_oi_log() -> dict[str, pd.DataFrame]:
    """Read data/funding_oi_history.jsonl once, split per symbol, sorted/
    deduped on timestamp. Returns only symbols with >= MIN_ROWS_TO_USE rows."""
    rows_by_symbol: dict[str, list[dict]] = {s: [] for s in SYMBOLS}
    with open(OI_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = d.get("symbol")
            if sym not in rows_by_symbol:
                continue
            if d.get("price") is None or d.get("open_interest") is None:
                continue
            rows_by_symbol[sym].append(d)

    out = {}
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


def load_liq_events() -> pd.DataFrame:
    if not LIQ_PATH.exists():
        return pd.DataFrame()
    rows = []
    with open(LIQ_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df.sort_values("dt").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Causal feature engineering (per symbol, on real irregular timestamps)
# ---------------------------------------------------------------------------

def _asof_index(dt_s: np.ndarray, i: int, lookback_s: float, tol_s: float) -> int:
    """Index of the last tick <= dt_s[i] - lookback_s, but ONLY if that tick
    is within tol_s of the intended lookback -- otherwise -1. This tolerance
    check is what stops a lookup taken shortly after the 22-day collector
    outage from silently grabbing a point from before the outage and
    mislabeling it '24h ago'."""
    target = dt_s[i] - lookback_s
    j = np.searchsorted(dt_s, target, side="right") - 1
    if j < 0:
        return -1
    if abs((dt_s[i] - dt_s[j]) - lookback_s) > tol_s:
        return -1
    return j


def build_symbol_features(df: pd.DataFrame, tail_thresh: float | None) -> pd.DataFrame:
    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    dt = df["dt"].to_numpy()
    # dt is tz-aware (UTC); strip tz before the numpy cast to avoid a spurious
    # "no explicit representation of timezones" warning (values are already UTC).
    dt_s = df["dt"].dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype(np.int64).astype(float)
    price = df["price"].to_numpy(dtype=float)
    oi = df["open_interest"].to_numpy(dtype=float)

    # native cadence (median gap), used to scale density thresholds
    gaps = np.diff(dt_s)
    cadence_s = float(np.median(gaps)) if len(gaps) else 900.0

    # tick-to-tick log returns, with gap-guard: invalidate any return whose
    # underlying interval exceeds GAP_GUARD_MIN minutes (real interval, not
    # native cadence) -- this is what quarantines the ~22d and ~4h gaps.
    logret = np.full(n, np.nan)
    logret[1:] = np.diff(np.log(price))
    gap_mask = np.zeros(n, dtype=bool)
    gap_mask[1:] = gaps > (GAP_GUARD_MIN * 60.0)
    logret[gap_mask] = np.nan
    clr = np.nancumsum(logret)  # cumulative log return, gap ticks contribute 0

    H = 3600.0
    tol_s = cadence_s * ASOF_TOL_FACTOR

    oi_roc = np.full(n, np.nan)
    price_roc = np.full(n, np.nan)
    trailing_vol = np.full(n, np.nan)
    min_hist_trail = max(5, int(DENSITY_FRAC * TRAILING_VOL_H * H / cadence_s))

    for i in range(n):
        j = _asof_index(dt_s, i, OI_ROC_LOOKBACK_H * H, tol_s)
        if j >= 0 and oi[j] > 0:
            oi_roc[i] = oi[i] / oi[j] - 1.0
        if j >= 0 and price[j] > 0:
            price_roc[i] = price[i] / price[j] - 1.0

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
        "oi_roc_24h": oi_roc, "price_roc_24h": price_roc,
        "oi_roc_pctile": oi_roc_pctile, "trailing_vol24": trailing_vol,
    })

    # forward labels per horizon
    for name, h in HORIZONS_H.items():
        fv = np.full(n, np.nan); fdd = np.full(n, np.nan)
        fru = np.full(n, np.nan); ftail = np.full(n, np.nan); fret = np.full(n, np.nan)
        min_hist_fwd = max(3, int(DENSITY_FRAC * h * H / cadence_s))
        for i in range(n):
            target = dt_s[i] + h * H
            j = np.searchsorted(dt_s, target, side="right")
            cnt = j - (i + 1)
            if cnt >= min_hist_fwd:
                seg_ret = logret[i + 1:j]
                seg_clr = clr[i + 1:j] - clr[i]
                fv[i] = np.nanstd(seg_ret, ddof=0)
                fdd[i] = np.nanmin(seg_clr)
                fru[i] = np.nanmax(seg_clr)
                fret[i] = seg_clr[-1]
                if tail_thresh is not None:
                    valid = seg_ret[~np.isnan(seg_ret)]
                    ftail[i] = float((np.abs(valid) > tail_thresh).mean()) if len(valid) else np.nan
        out[f"fwd_vol_{name}"] = fv
        out[f"fwd_maxdd_{name}"] = fdd
        out[f"fwd_maxrun_{name}"] = fru
        out[f"fwd_tailfreq_{name}"] = ftail
        out[f"fwd_ret_{name}"] = fret
        out[f"vol_ratio_{name}"] = fv / trailing_vol

    out["oi_state"] = pd.cut(
        out["oi_roc_pctile"], bins=[-0.01, 33.34, 66.67, 100.01],
        labels=["unwind", "neutral", "buildup"],
    )
    out["cadence_s"] = cadence_s
    return out


def estimate_tail_thresh(raw: dict[str, pd.DataFrame]) -> float:
    """Pooled 90th percentile of |tick-to-tick log return| across all usable
    symbols, computed AFTER the gap-guard would remove gap-spanning ticks
    (recomputed inline here since this runs before build_symbol_features).
    A living-value threshold, not a hardcoded guess."""
    pooled = []
    for sym, df in raw.items():
        dt_s = df["dt"].dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype(np.int64).astype(float)
        price = df["price"].to_numpy(dtype=float)
        gaps = np.diff(dt_s)
        logret = np.diff(np.log(price))
        logret = logret[gaps <= GAP_GUARD_MIN * 60.0]
        pooled.append(np.abs(logret))
    all_abs = np.concatenate(pooled)
    return float(np.nanpercentile(all_abs, 90))


# ---------------------------------------------------------------------------
# Stats helpers (block-bootstrap / block-permutation; positional blocking on
# the already time-ordered, filtered subset -- same convention as
# funding_predictiveness_test.py in this folder)
# ---------------------------------------------------------------------------

def block_bootstrap_mean_ci(x: np.ndarray, block: int, null: float = 0.0, n_boot: int = N_BOOTSTRAP):
    x = x[~np.isnan(x)]
    n = len(x)
    if n < max(30, block * 3):
        return np.nan, (np.nan, np.nan), np.nan, n
    n_blocks = int(np.ceil(n / block))
    starts = np.arange(0, n - block + 1)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = RNG.integers(0, len(starts), size=n_blocks)
        sample = np.concatenate([x[s:s + block] for s in starts[idx]])[:n]
        boots[b] = sample.mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    obs = x.mean()
    centered = boots - boots.mean() + null
    p = float((np.abs(centered - null) >= abs(obs - null)).mean())
    return obs, (lo, hi), p, n


def welch_t(a: np.ndarray, b: np.ndarray):
    from scipy.stats import ttest_ind
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    t, p = ttest_ind(a, b, equal_var=False)
    return float(t), float(p)


def spearman_block_perm_test(x: np.ndarray, y: np.ndarray, block: int, n_perm: int = N_PERM):
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < max(50, block * 3):
        return np.nan, np.nan, n
    from scipy.stats import spearmanr
    rho_obs, _ = spearmanr(x, y)
    starts = list(range(0, n - block + 1, block)) or [0]
    null = np.empty(n_perm)
    for i in range(n_perm):
        perm_starts = RNG.permutation(starts)
        y_perm = np.concatenate([y[s:s + block] for s in perm_starts])[:n]
        x_trim = x[:len(y_perm)]
        r, _ = spearmanr(x_trim, y_perm)
        null[i] = r
    p = float((np.abs(null) >= abs(rho_obs)).mean())
    return rho_obs, p, n


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def decile_table(panel: pd.DataFrame, horizon: str, label: str, block_rows: int):
    vr_col, dd_col, tf_col = f"vol_ratio_{horizon}", f"fwd_maxdd_{horizon}", f"fwd_tailfreq_{horizon}"
    d = panel.dropna(subset=["oi_roc_pctile", vr_col, dd_col, tf_col]).copy()
    if len(d) < 200:
        print(f"    [{label}] n={len(d)} too small for decile table, skipping")
        return
    d["decile"] = pd.qcut(d["oi_roc_pctile"].rank(method="first"), 10, labels=False)
    g = d.groupby("decile")[[vr_col, dd_col, tf_col]].agg(["mean", "count"])
    print(f"    [{label}] forward {horizon} risk metrics by oi_roc_pctile decile "
          f"(0=sharpest OI UNWIND, 9=sharpest OI BUILDUP):")
    print(f"      {'dec':>4} {'n':>6} {'vol_ratio':>10} {'maxdd%':>9} {'tailfreq%':>10}")
    for dec, row in g.iterrows():
        n = int(row[(vr_col, "count")])
        print(f"      {int(dec):>4} {n:>6} {row[(vr_col,'mean')]:>10.3f} "
              f"{row[(dd_col,'mean')]*100:>8.3f}% {row[(tf_col,'mean')]*100:>9.2f}%")
    rho, p, n_eff = spearman_block_perm_test(
        d["oi_roc_pctile"].to_numpy(), d[vr_col].to_numpy(), block=block_rows
    )
    print(f"      Spearman(oi_roc_pctile, {vr_col}) = {rho:+.4f}  block-permutation p={p:.3f}  "
          f"(n={n_eff}, block={block_rows} rows)")


def tercile_state_test(panel: pd.DataFrame, horizon: str, label: str, block_rows: int):
    vr_col = f"vol_ratio_{horizon}"
    d = panel.dropna(subset=["oi_state", vr_col]).copy()
    out = {}
    for state in ("unwind", "neutral", "buildup"):
        sub = d[d["oi_state"] == state][vr_col].to_numpy()
        obs, (lo, hi), p, n_eff = block_bootstrap_mean_ci(sub, block=block_rows, null=1.0)
        print(f"    [{label}] {state:>8s}: n={n_eff:>6}  mean vol_ratio={obs:.3f}  "
              f"95% CI=[{lo:.3f},{hi:.3f}]  p(vs null=1.0)={p:.3f}")
        out[state] = (obs, n_eff)
    if not np.isnan(out.get("buildup", (np.nan,))[0]) and not np.isnan(out.get("unwind", (np.nan,))[0]):
        t, p = welch_t(
            d[d["oi_state"] == "buildup"][vr_col].to_numpy(),
            d[d["oi_state"] == "unwind"][vr_col].to_numpy(),
        )
        diff = out["buildup"][0] - out["unwind"][0]
        print(f"    [{label}] buildup - unwind vol_ratio diff = {diff:+.3f}  t={t:.2f} p={p:.3f} "
              f"(positive = buildup sees MORE forward vol than unwind, relative to each coin's own baseline)")
    return out


def divergence_test(panel: pd.DataFrame, horizon: str, label: str):
    dd_col, ru_col = f"fwd_maxdd_{horizon}", f"fwd_maxrun_{horizon}"
    d = panel.dropna(subset=["oi_state", "price_roc_24h", dd_col, ru_col]).copy()
    buildup = d[d["oi_state"] == "buildup"]
    long_build = buildup[buildup["price_roc_24h"] > 0]
    short_build = buildup[buildup["price_roc_24h"] <= 0]
    if len(long_build) < 30 or len(short_build) < 30:
        print(f"    [{label}] H2 split too thin (long_build={len(long_build)}, short_build={len(short_build)}), skipping")
        return
    t_dd, p_dd = welch_t(long_build[dd_col].to_numpy(), short_build[dd_col].to_numpy())
    t_ru, p_ru = welch_t(short_build[ru_col].to_numpy(), long_build[ru_col].to_numpy())
    print(f"    [{label}] LONG buildup (OI up + price up, n={len(long_build)}): "
          f"mean fwd_maxdd={long_build[dd_col].mean()*100:+.3f}%  mean fwd_maxrun={long_build[ru_col].mean()*100:+.3f}%")
    print(f"    [{label}] SHORT buildup (OI up + price down, n={len(short_build)}): "
          f"mean fwd_maxdd={short_build[dd_col].mean()*100:+.3f}%  mean fwd_maxrun={short_build[ru_col].mean()*100:+.3f}%")
    print(f"      downside asymmetry (long_build maxdd more negative than short_build?): t={t_dd:.2f} p={p_dd:.3f}")
    print(f"      upside asymmetry   (short_build maxrun bigger than long_build?):       t={t_ru:.2f} p={p_ru:.3f}")


def vol_regime_control(panel: pd.DataFrame, horizon: str, label: str):
    vr_col = f"vol_ratio_{horizon}"
    d = panel.dropna(subset=["oi_state", "trailing_vol24", vr_col]).copy()
    if len(d) < 600:
        print(f"    [{label}] n={len(d)} too small for vol-regime control, skipping")
        return
    d["vol_tercile"] = pd.qcut(d["trailing_vol24"], 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
    print(f"    [{label}] within-vol-tercile buildup-minus-unwind vol_ratio spread ({horizon}):")
    for vt, sub in d.groupby("vol_tercile", observed=True):
        b = sub[sub["oi_state"] == "buildup"][vr_col].to_numpy()
        u = sub[sub["oi_state"] == "unwind"][vr_col].to_numpy()
        if len(b) < 30 or len(u) < 30:
            print(f"      {vt}: too thin (buildup n={len(b)}, unwind n={len(u)}), skip")
            continue
        t, p = welch_t(b, u)
        spread = np.nanmean(b) - np.nanmean(u)
        print(f"      {vt}: n={len(sub)}  buildup_mean={np.nanmean(b):.3f}  unwind_mean={np.nanmean(u):.3f}  "
              f"spread={spread:+.3f}  t={t:.2f} p={p:.3f}")


def cross_coin_consistency(frames: dict[str, pd.DataFrame], horizon: str, block_rows: int):
    vr_col = f"vol_ratio_{horizon}"
    print(f"    per-symbol buildup vs unwind vol_ratio spread ({horizon}):")
    signs = []
    for sym, df in frames.items():
        d = df.dropna(subset=["oi_state", vr_col])
        b = d[d["oi_state"] == "buildup"][vr_col].to_numpy()
        u = d[d["oi_state"] == "unwind"][vr_col].to_numpy()
        if len(b) < 20 or len(u) < 20:
            print(f"      {sym}: too thin (buildup n={len(b)}, unwind n={len(u)})")
            continue
        spread = np.nanmean(b) - np.nanmean(u)
        t, p = welch_t(b, u)
        signs.append(np.sign(spread))
        print(f"      {sym}: n_buildup={len(b)} n_unwind={len(u)}  buildup_mean={np.nanmean(b):.3f} "
              f"unwind_mean={np.nanmean(u):.3f}  spread={spread:+.3f}  t={t:.2f} p={p:.3f}")
    if signs:
        agree = max(signs.count(1), signs.count(-1))
        print(f"    -> {agree}/{len(signs)} symbols agree on sign of the buildup-vs-unwind spread "
              f"({'CONSISTENT' if agree >= max(4, int(np.ceil(0.8*len(signs)))) else 'NOT clearly consistent'})")


def era_split(panel: pd.DataFrame, horizon: str, label: str, block_rows: int):
    d = panel.dropna(subset=["dt"]).copy()
    mid = d["dt"].min() + (d["dt"].max() - d["dt"].min()) / 2
    for era_name, sub in [("H1 (first half)", d[d["dt"] < mid]), ("H2 (second half)", d[d["dt"] >= mid])]:
        print(f"    -- {label} / {era_name} ({sub['dt'].min()} .. {sub['dt'].max()}) --")
        tercile_state_test(sub, horizon, f"{label}/{era_name}", block_rows)


def daily_resample_crosscheck(panel: pd.DataFrame, horizon: str, label: str, h: int, cadence_s: float):
    """Thin the panel to ~1 row per horizon-length block per symbol, killing
    most overlap-induced autocorrelation, then repeat the core test."""
    vr_col = f"vol_ratio_{horizon}"
    d = panel.dropna(subset=["oi_state", vr_col]).copy()
    block_len = max(1, int(h * 3600 / cadence_s))
    d["blk"] = np.arange(len(d)) // block_len
    thinned = d.groupby(["symbol", "blk"], observed=True).first().reset_index(drop=True)
    b = thinned[thinned["oi_state"] == "buildup"][vr_col].to_numpy()
    u = thinned[thinned["oi_state"] == "unwind"][vr_col].to_numpy()
    if len(b) < 15 or len(u) < 15:
        print(f"    [{label}] non-overlapping cross-check: too thin (buildup n={len(b)}, unwind n={len(u)})")
        return
    t, p = welch_t(b, u)
    print(f"    [{label}] non-overlapping cross-check (~1 obs / {h}h / symbol): "
          f"buildup n={len(b)} mean={np.nanmean(b):.3f}  unwind n={len(u)} mean={np.nanmean(u):.3f}  "
          f"t={t:.2f} p={p:.3f}")


def liq_crosscheck(frames: dict[str, pd.DataFrame], liq_df: pd.DataFrame):
    if liq_df.empty:
        print("  No liquidation events found -- skipping.")
        return
    counts = liq_df["symbol"].value_counts()
    print(f"  liq_events.jsonl: n={len(liq_df)} total, by symbol: {dict(counts)}")
    usable = [s for s in counts.index if s in frames]
    print(f"  Of those, only symbols with usable OI history: {usable or 'NONE'}")
    if not usable:
        print("  -> 0 liq events land on a symbol with usable OI history. No cross-check possible.")
        return
    print("  Cross-check (labeled UNDERPOWERED PEEK, not a test -- see n below):")
    for _, ev in liq_df[liq_df["symbol"].isin(usable)].iterrows():
        sym = ev["symbol"]
        df = frames[sym]
        prior = df[df["dt"] <= ev["dt"]]
        if prior.empty:
            print(f"    {ev['dt']} {sym} {ev['side']} ${ev['notional_usd']:.0f} -- no OI data at/before this time")
            continue
        row = prior.iloc[-1]
        age_min = (ev["dt"] - row["dt"]).total_seconds() / 60.0
        state = row["oi_state"] if pd.notna(row["oi_state"]) else "n/a (insufficient history for pctile)"
        print(f"    {ev['dt']} {sym} {ev['side']} ${ev['notional_usd']:.0f} liq -> "
              f"nearest OI snapshot {age_min:.0f}min prior: oi_roc_pctile={row['oi_roc_pctile']:.1f} state={state}")
    n_usable = len(liq_df[liq_df["symbol"].isin(usable)])
    print(f"  n={n_usable} -- WAY too small to conclude anything; printed as an anecdote only.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 92)
    print("OI RISK-CONTEXT TEST -- does open-interest buildup/unwind carry forward")
    print("volatility / cascade-risk information, or is it vol-clustering restated?")
    print("=" * 92)

    print("\n--- SECTION 0: data actually loaded ---")
    raw = load_oi_log()
    for sym in SYMBOLS:
        if sym not in raw:
            print(f"  {sym}: <{MIN_ROWS_TO_USE} rows, EXCLUDED")
            continue
        df = raw[sym]
        gaps_min = df["dt"].diff().dt.total_seconds().dropna() / 60.0
        big_gaps = gaps_min[gaps_min > GAP_GUARD_MIN]
        head = f"  {sym}: n={len(df)}  {df['dt'].min()} -> {df['dt'].max()}  median_cadence={gaps_min.median():.1f}min"
        if len(big_gaps):
            print(f"{head}  gaps>{GAP_GUARD_MIN}min: {len(big_gaps)} (largest={big_gaps.max():.0f}min)")
        else:
            print(f"{head}  no gaps>{GAP_GUARD_MIN}min")

    if not raw:
        print("\nNo usable symbols found -- aborting.")
        return

    tail_thresh = estimate_tail_thresh(raw)
    print(f"\n  Living-value TAIL_THRESH (pooled 90th pctile of |tick log-return|, gap ticks excluded): "
          f"{tail_thresh*100:.3f}% per tick (~{tail_thresh*1e4:.1f}bps)")

    frames = {}
    for sym, df in raw.items():
        feats = build_symbol_features(df, tail_thresh)
        feats["symbol"] = sym
        frames[sym] = feats
        n_state = feats["oi_state"].notna().sum()
        print(f"  {sym}: {n_state} rows with a valid oi_roc_pctile/oi_state "
              f"(after {OI_STATE_LOOKBACK_H}h causal lookback + {MIN_HIST_STATE}-obs minimum)")

    panel = pd.concat(frames.values(), ignore_index=True)
    print(f"\n  Pooled panel: {len(panel)} rows across {len(frames)} symbols "
          f"({', '.join(frames.keys())})")
    print(f"  CAVEAT: this is a SINGLE ~33-day continuous era (2026-06-29 -> 2026-08-01) across all 5 "
          f"symbols simultaneously -- NOT independent eras. Any finding below could be one macro period's")
    print(f"  regime, not a stable OI effect. Treat every p-value here as suggestive, not confirmatory, and")
    print(f"  read section H4 before believing anything in H1-H3.")

    for horizon, h in HORIZONS_H.items():
        cadence_s = float(panel["cadence_s"].median())
        block_rows = max(20, int(h * 3600 / cadence_s))
        print(f"\n{'='*92}\nHORIZON = {horizon} forward  (block size for bootstrap/permutation = {block_rows} rows)\n{'='*92}")

        print(f"\n  -- H1: OI buildup = cascade fuel? (decile table, pooled) --")
        decile_table(panel, horizon, "POOLED", block_rows)
        print(f"\n  -- H1 actionable: buildup vs neutral vs unwind tercile, vol_ratio vs own-baseline (null=1.0) --")
        tercile_state_test(panel, horizon, "POOLED", block_rows)

        print(f"\n  -- H2: OI+price divergence (long-buildup vs short-buildup squeeze-risk asymmetry) --")
        divergence_test(panel, horizon, "POOLED")

        print(f"\n  -- H4a: vol-regime control (does the buildup/unwind spread survive within vol terciles?) --")
        vol_regime_control(panel, horizon, "POOLED")

        print(f"\n  -- H4b: non-overlapping cross-check --")
        daily_resample_crosscheck(panel, horizon, "POOLED", h, cadence_s)

        print(f"\n  -- H4c: cross-coin consistency --")
        cross_coin_consistency(frames, horizon, block_rows)

        print(f"\n  -- H4d: era split (first half vs second half of the ONE 33-day window -- LOW POWER, see caveat) --")
        era_split(panel, horizon, "POOLED", block_rows)

    print(f"\n{'='*92}\nAutocorrelation (effective-N caveat)\n{'='*92}")
    for sym, df in frames.items():
        s = df["oi_roc_pctile"].dropna()
        ac1 = s.autocorr(lag=1) if len(s) > 30 else np.nan
        print(f"  {sym}: oi_roc_pctile lag-1 autocorrelation = {ac1:.3f}  (n={len(s)}) "
              f"-- {'highly persistent' if not np.isnan(ac1) and ac1 > 0.9 else 'moderate/low persistence'}")

    print(f"\n{'='*92}\nLiquidation cross-check (n=19 total, UNDERPOWERED PEEK)\n{'='*92}")
    liq_df = load_liq_events()
    liq_crosscheck(frames, liq_df)

    print(f"\n{'='*92}\nVERDICT\n{'='*92}")
    print("""
Read the numbers above, not this summary, before acting on anything. As a
rule of thumb consistent with the sibling tests in this folder: a stable,
honest "OI is stacked X% above trailing -- elevated cascade risk" note is
only justified if ALL of the following hold:
  1. H1's buildup-vs-unwind vol_ratio spread is positive with a bootstrap CI
     excluding 0 (i.e. buildup sees MORE forward vol than unwind, relative
     to the coin's OWN trailing vol -- not just more vol in absolute terms).
  2. H4a shows the spread SURVIVES within vol terciles. If it only appears
     in the high-vol tercile, OI is a vol-clustering proxy, not new
     information.
  3. H4c shows the spread is the SAME SIGN on at least 4/5 symbols. A
     single-coin effect (most likely HYPE or SOL, the two most volatile
     names here) is not a general OI-risk rule.
  4. H4d shows the SAME SIGN in both halves of the window. A flip (or an
     effect that only exists in one half) is a single-event artifact of
     this one 33-day stretch, not a stable seasonal/structural pattern.
Given this dataset is ONE continuous 33-day era with no independent OOS
period available (see SECTION 0 -- HL exposes no historical OI endpoint,
and the rest of this project's own OI collection only started 2026-08-01),
even a full pass on 1-4 above should be read as "plausible, revisit once the
collector has 60-90 days and at least one more distinct macro regime to
test against" -- NOT as a validated, ship-it signal. A "too thin to conclude
yet" verdict here is a completely acceptable, likely, and honest outcome.
""")


if __name__ == "__main__":
    main()
