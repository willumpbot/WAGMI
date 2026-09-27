#!/usr/bin/env python
"""
tools/copilot/dd_tilt_test.py

READ-ONLY audit (4th of 4 in the risk-mechanic audit series, after
circuit_breaker_test.py) of whether the bot's REAL trades show a
"drawdown tilt" effect: does trading while already in a session drawdown
DIG THE HOLE DEEPER (adverse-regime persistence or revenge-sizing), which
would justify a pause-after-N%-drawdown rule?

*** FINDING #0 (before any bucketing): the raw `session_dd_pct` ledger
column is a POST-CLOSE snapshot, NOT a pre-trade/entry-time value. Traced
to source (multi_strategy_main.py:4188-4192 and :5105-5109):

    _session_dd = (cb.session_peak_equity - self.risk_mgr.equity) / cb.session_peak_equity * 100

computed AFTER `self.risk_mgr.equity` already reflects THIS trade's own
net_pnl (equity is updated by record_trade() earlier in the same close
handler). Using a row's own session_dd_pct to bucket that SAME row's
outcome is TAUTOLOGICAL: a big loser mechanically inflates its own
post-close DD reading, so "deep-DD rows look like losers" would be
partly true BY CONSTRUCTION, independent of any real tilt effect. This
is exactly the trap flagged in the task's own refute-yourself section 5(c).

FIX: every DD-at-entry metric in this script is LAGGED -- for trade i we
use `entry_time_i = timestamp_i - hold_hours_i * 3600` and only look at
information from closes that happened STRICTLY BEFORE entry_time_i (never
including trade i's own outcome). Section [4] below demonstrates the size
of the tautology artifact by contrasting the naive same-row correlation
against the correctly-lagged one.

*** FINDING #1: `session_peak_equity` (execution/risk.py:82, 94-95) is set
ONCE at `start_session()` and NEVER updated to a new running high anywhere
in the codebase (grep-confirmed: only `.session_peak_equity <= 0` guards
touch it). So the live "session DD" concept is "% below THIS SESSION'S
STARTING equity" (can go NEGATIVE = up for the session), not "% below the
highest equity ever seen this session." A "session" here == since the last
`start_session()` call (bot process start / manual epoch reset), not a
rolling high-water mark.

*** FINDING #2: `execution/risk.py: CircuitBreaker.get_drawdown_dial()`
(graduated 1.0x / 0.75x / 0.5x / 0.25x / 0.0x size-down by session-DD depth,
0-5/5-10/10-15/15-20/>20% tiers) is DEAD CODE in production -- grep across
the whole repo (execution/, core/, llm/, multi_strategy_main.py) finds ZERO
callers outside its own unit test (tests/test_quant_system.py). There is
currently NO live behavior change tied to drawdown depth at all. This
directly answers part of task question 3 (does the bot change behavior
when down) at the CODE level, independent of the data: no, there is no
wired mechanism that could -- any tilt found below would have to come from
the LLM agents' own emergent behavior (sizing/leverage/confidence), not a
scripted dial, since the scripted dial that exists is never called.

THREE drawdown-at-entry metrics are built, all lagged (no look-ahead):
  1. dd_entry_raw    -- the LIVE bot's own session_dd_pct field, looked up
                        from the most recent close before this trade's
                        entry (not this trade's own row). n=248/274 (missing
                        where no prior close exists yet, or the prior close
                        is one of the 23 RECONSTRUCTED_FROM_LOG rows with a
                        blank session_dd_pct). PRIMARY metric -- most
                        faithful to "what a live pause rule would see."
  2. dd_entry_roll20 -- reconstructed from the net_pnl equity curve using a
                        TRAILING 20-TRADE peak (not all-time-since-inception).
                        Available for all 274 rows. SECONDARY metric --
                        approximates "recent regime," avoids Finding #3 below.
  3. dd_entry_full   -- reconstructed using an ALL-TIME-SINCE-INCEPTION
                        running peak (the naive "cumsum net_pnl, track the
                        running max" reconstruction the task text describes).
                        Shown ONLY as a self-refutation example (Finding #3):
                        it is DEGENERATE on this ledger.

*** FINDING #3 (self-refutation of the naive full-history reconstruction):
the account's equity peak (~$6,184) was set within the first ~17 of 274
trades (June 1-3) and was NEVER RE-ATTAINED for the remaining ~257 trades /
~2 months. So dd_entry_full reads nearly the ENTIRE back 94% of the ledger
as "chronically 10-16% underwater," with almost no bucket variance -- not
because of any local/recent tilt dynamic, but because of one stale early
high-water mark. This construction is REJECTED as a primary metric (it
would make every post-week-1 trade "deep DD" by definition, which is
uninformative and does not correspond to how the live bot's own session
concept, or any sane pause rule, would behave -- see Finding #1: real
sessions reset on process restart, of which there were many). Pairwise
correlation matrix in section [2] shows dd_entry_full is nearly ORTHOGONAL
to both dd_entry_raw (r~0.11) and dd_entry_roll20 (r~-0.01), confirming it
is measuring something different (career-drawdown, not session/recent-tilt).

DATA: data/trade_ledger.csv (274 closed trades). realized_rr populated on
only 60/274 rows (22%) -- reported where available, flagged low-coverage,
never used as the sole basis for a claim.

USAGE:
    python tools/copilot/dd_tilt_test.py

OWNER-GATED: this script only reads data/trade_ledger.csv and prints a
report. It imports nothing from execution/risk.py and calls no live code
path -- ZERO chance of touching live state. Any resulting change (e.g.
wiring get_drawdown_dial(), adding a pause threshold) is an OWNER-GATED
live-bot edit, not made here.
"""
from __future__ import annotations

import os
import sys
import csv
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from scipy import stats as sps
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False

warnings.filterwarnings("ignore")

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BOT_DIR)

LEDGER_PATH = os.path.join(BOT_DIR, "data", "trade_ledger.csv")
SIZE_COLLAPSE_DATE = datetime(2026, 7, 26, tzinfo=timezone.utc)  # per project memory
ROLL_WINDOW = 20  # trailing-peak window for dd_entry_roll20 ("recent regime" proxy)

RNG = np.random.default_rng(1234)  # fixed seed -> reproducible permutation p-values


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_trade_ledger(path: str) -> pd.DataFrame:
    rows = list(csv.DictReader(open(path)))
    df = pd.DataFrame(rows)
    for col in ["timestamp", "net_pnl", "hold_hours", "leverage", "confidence_score",
                "realized_rr", "running_equity", "session_dd_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["win"] = pd.to_numeric(df["win"], errors="coerce").fillna((df["net_pnl"] > 0).astype(int))
    df["dt_utc"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    n_recon = int((df["contributing_factors"] == "RECONSTRUCTED_FROM_LOG").sum())
    print(f"[dd_tilt_test] Loaded {len(df)} closed trades, "
          f"{df['dt_utc'].min()} -> {df['dt_utc'].max()}")
    print(f"[dd_tilt_test] NOTE: {n_recon}/{len(df)} rows are RECONSTRUCTED_FROM_LOG backfilled "
          f"entries (blank running_equity/session_dd_pct, fees hard-zeroed) -- same known gap "
          f"circuit_breaker_test.py documents. net_pnl/timestamp/hold_hours ARE real for these "
          f"rows and used as-is; they simply cannot supply a raw session_dd_pct reading.")
    return df


def backsolve_starting_equity(df: pd.DataFrame) -> float:
    return float(df.iloc[0]["running_equity"] - df.iloc[0]["net_pnl"])


# ---------------------------------------------------------------------------
# Core: lagged drawdown-at-entry reconstruction (no look-ahead)
# ---------------------------------------------------------------------------
def compute_dd_metrics(df: pd.DataFrame, roll_window: int = ROLL_WINDOW) -> pd.DataFrame:
    df = df.copy()
    n = len(df)
    starting_equity = backsolve_starting_equity(df)

    closes_t = df["timestamp"].values.astype(float)
    net_pnl = df["net_pnl"].values.astype(float)
    hold_h = df["hold_hours"].values.astype(float)
    entry_time = closes_t - hold_h * 3600.0
    raw_sdd = df["session_dd_pct"].values.astype(float)  # NaN where absent

    # idx[i] = index of the LAST close with timestamp < entry_time[i] (-1 if none)
    idx = np.searchsorted(closes_t, entry_time, side="left") - 1

    # Metric 1: PRIMARY -- live bot's own field, correctly lagged
    dd_entry_raw = np.where(idx >= 0, raw_sdd[np.clip(idx, 0, None)], np.nan)

    # Reconstructed equity path (close-order step function)
    equity_after = starting_equity + np.cumsum(net_pnl)
    peak_after_full = np.maximum.accumulate(np.concatenate([[starting_equity], equity_after]))[1:]
    eq_at_entry = np.where(idx >= 0, equity_after[np.clip(idx, 0, None)], starting_equity)

    # Metric 3: all-time-since-inception peak (naive reconstruction -- degenerate, see Finding #3)
    peak_at_entry_full = np.where(idx >= 0, peak_after_full[np.clip(idx, 0, None)], starting_equity)
    dd_entry_full = (peak_at_entry_full - eq_at_entry) / peak_at_entry_full * 100.0

    # Metric 2: SECONDARY -- trailing-K-trade peak ("recent regime" proxy)
    roll_peak_series = pd.Series(equity_after).rolling(roll_window, min_periods=1).max().values
    roll_peak_at_entry = np.where(idx >= 0, roll_peak_series[np.clip(idx, 0, None)], starting_equity)
    dd_entry_roll20 = (roll_peak_at_entry - eq_at_entry) / roll_peak_at_entry * 100.0

    # Naive/WRONG same-row (unlagged) raw field, kept ONLY for the tautology demo in section [4]
    dd_same_row_raw = raw_sdd.copy()

    df["entry_time"] = entry_time
    df["prior_close_idx"] = idx
    df["dd_entry_raw"] = dd_entry_raw
    df["dd_entry_roll20"] = dd_entry_roll20
    df["dd_entry_full"] = dd_entry_full
    df["dd_same_row_raw_UNLAGGED"] = dd_same_row_raw
    df["starting_equity"] = starting_equity
    return df


# ---------------------------------------------------------------------------
# Bucketing + significance
# ---------------------------------------------------------------------------
BUCKET_BINS = [-100.0, 0.5, 5.0, 100.0]
BUCKET_LABELS = ["flat/near-high (<=0.5%)", "mild DD (0.5-5%)", "deep DD (>5%)"]


def bucket_table(df: pd.DataFrame, dd_col: str, baseline_wr: float, baseline_mean: float) -> pd.DataFrame:
    sub = df.dropna(subset=[dd_col]).copy()
    sub["bucket"] = pd.cut(sub[dd_col], bins=BUCKET_BINS, labels=BUCKET_LABELS)
    recs = []
    for lbl in BUCKET_LABELS:
        g = sub[sub["bucket"] == lbl]
        n = len(g)
        if n == 0:
            recs.append({"bucket": lbl, "n": 0})
            continue
        wr = g["win"].mean() * 100
        mean_pnl = g["net_pnl"].mean()
        std_pnl = g["net_pnl"].std(ddof=1) if n > 1 else float("nan")
        se_pnl = std_pnl / np.sqrt(n) if n > 1 else float("nan")
        rr = g["realized_rr"].dropna()
        # two-proportion z-test of this bucket's WR vs baseline WR (excluding this bucket)
        rest = sub[sub["bucket"] != lbl]
        p_wr = wr_diff_pvalue(g["win"].values, rest["win"].values)
        p_pnl = permutation_pvalue(g["net_pnl"].values, rest["net_pnl"].values)
        recs.append({
            "bucket": lbl, "n": n,
            "win_rate_pct": round(wr, 1),
            "wr_vs_baseline_pp": round(wr - baseline_wr, 1),
            "p_wr_vs_rest": round(p_wr, 3) if p_wr == p_wr else np.nan,
            "mean_net_pnl": round(mean_pnl, 2),
            "pnl_vs_baseline": round(mean_pnl - baseline_mean, 2),
            "p_pnl_vs_rest": round(p_pnl, 3) if p_pnl == p_pnl else np.nan,
            "std_net_pnl": round(std_pnl, 2) if std_pnl == std_pnl else np.nan,
            "se_net_pnl": round(se_pnl, 2) if se_pnl == se_pnl else np.nan,
            "n_realized_rr": len(rr),
            "mean_realized_rr": round(rr.mean(), 3) if len(rr) else np.nan,
        })
    out = pd.DataFrame(recs)
    print(f"  (n covered by this metric: {len(sub)}/{len(df)})")
    return out


def wr_diff_pvalue(win_a: np.ndarray, win_b: np.ndarray) -> float:
    """Two-proportion z-test p-value (two-sided). Falls back gracefully for tiny n."""
    na, nb = len(win_a), len(win_b)
    if na == 0 or nb == 0:
        return float("nan")
    pa, pb = win_a.mean(), win_b.mean()
    p_pool = (win_a.sum() + win_b.sum()) / (na + nb)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / na + 1 / nb))
    if se == 0:
        return float("nan")
    z = (pa - pb) / se
    if _HAVE_SCIPY:
        return float(2 * (1 - sps.norm.cdf(abs(z))))
    # crude normal-approx fallback without scipy
    return float(2 * (1 - 0.5 * (1 + np.math.erf(abs(z) / np.sqrt(2)))))


def permutation_pvalue(a: np.ndarray, b: np.ndarray, n_iter: int = 20000) -> float:
    """Permutation test on the difference in means, mean(a) - mean(b). Robust for small n."""
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    obs = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    na = len(a)
    count = 0
    for _ in range(n_iter):
        RNG.shuffle(pooled)
        diff = pooled[:na].mean() - pooled[na:].mean()
        if abs(diff) >= abs(obs):
            count += 1
    return count / n_iter


def episode_clustering(df: pd.DataFrame, dd_col: str, gap_hours: float = 48.0) -> Dict[str, object]:
    """How many INDEPENDENT episodes does the deep-DD bucket actually represent?

    chi-square/permutation tests assume independent draws. If every deep-DD
    row comes from one contiguous stretch of calendar time (one bad run),
    the effective sample size for inference is close to 1 EPISODE, not N
    TRADES -- pseudo-replication. This counts episodes via a gap-based
    clustering on entry_time (a new episode starts whenever the gap since
    the last deep-DD trade's entry_time exceeds `gap_hours`).
    """
    sub = df.dropna(subset=[dd_col]).copy()
    deep = sub[sub[dd_col] > 5.0].sort_values("entry_time")
    if deep.empty:
        return {"n": 0, "n_episodes": 0, "span_days": 0.0}
    gaps_h = deep["entry_time"].diff().fillna(1e9) / 3600.0
    n_episodes = int((gaps_h > gap_hours).sum()) + 1
    span_days = (deep["dt_utc"].max() - deep["dt_utc"].min()).total_seconds() / 86400.0
    return {
        "n": len(deep), "n_episodes": n_episodes, "span_days": round(span_days, 1),
        "first": deep["dt_utc"].min(), "last": deep["dt_utc"].max(),
    }


def chi_square_bucket_vs_win(df: pd.DataFrame, dd_col: str) -> Optional[Tuple[float, float, int]]:
    sub = df.dropna(subset=[dd_col]).copy()
    sub["bucket"] = pd.cut(sub[dd_col], bins=BUCKET_BINS, labels=BUCKET_LABELS)
    ct = pd.crosstab(sub["bucket"], sub["win"])
    ct = ct.loc[(ct.sum(axis=1) > 0)]
    if ct.shape[0] < 2 or not _HAVE_SCIPY:
        return None
    chi2, p, dof, _ = sps.chi2_contingency(ct)
    return chi2, p, dof


# ---------------------------------------------------------------------------
# Revenge-trading signature: does behavior (leverage/confidence) shift with DD?
# ---------------------------------------------------------------------------
def revenge_signature(df: pd.DataFrame, dd_col: str) -> pd.DataFrame:
    sub = df.dropna(subset=[dd_col]).copy()
    sub["bucket"] = pd.cut(sub[dd_col], bins=BUCKET_BINS, labels=BUCKET_LABELS)
    conf_masked = sub["confidence_score"].where(sub["confidence_score"] > 0)  # 0 = pre-instrumentation, not "zero conviction"
    sub["_conf_masked"] = conf_masked
    recs = []
    for lbl in BUCKET_LABELS:
        g = sub[sub["bucket"] == lbl]
        recs.append({
            "bucket": lbl, "n": len(g),
            "mean_leverage": round(g["leverage"].mean(), 2) if len(g) else np.nan,
            "mean_confidence(masked>0)": round(g["_conf_masked"].mean(), 1) if g["_conf_masked"].notna().any() else np.nan,
            "n_confidence_available": int(g["_conf_masked"].notna().sum()),
            "pct_post_collapse": round((g["dt_utc"] >= SIZE_COLLAPSE_DATE).mean() * 100, 1) if len(g) else np.nan,
        })
    corr_lev = sub[dd_col].corr(sub["leverage"])
    corr_conf = sub.dropna(subset=["_conf_masked"])[dd_col].corr(sub.dropna(subset=["_conf_masked"])["_conf_masked"])
    print(f"  Pearson corr(dd_entry, leverage) = {corr_lev:.3f}   "
          f"Pearson corr(dd_entry, confidence[masked>0], n={sub['_conf_masked'].notna().sum()}) = {corr_conf:.3f}")
    return pd.DataFrame(recs)


# ---------------------------------------------------------------------------
# Pause-rule simulation
# ---------------------------------------------------------------------------
@dataclass
class PauseResult:
    threshold: float
    n_skipped: int
    n_kept: int
    dd_avoided: float          # $ of skipped LOSERS
    opportunity_cost: float    # $ of skipped WINNERS
    net_effect: float
    baseline_max_dd_pct: float
    kept_max_dd_pct: float
    skipped_win_rate: float


def simulate_pause(df: pd.DataFrame, dd_col: str, threshold: float, starting_equity: float) -> PauseResult:
    sub = df.dropna(subset=[dd_col]).copy().reset_index(drop=True)
    skip_mask = sub[dd_col] > threshold

    # Baseline equity path (all trades kept, close order)
    eq = starting_equity + np.cumsum(sub["net_pnl"].values)
    peak = np.maximum.accumulate(np.concatenate([[starting_equity], eq]))[1:]
    baseline_max_dd = float(((peak - eq) / peak * 100.0).max())

    # Simulated equity path: skipped trades' pnl simply does not happen (same
    # first-order simplification as circuit_breaker_test.py -- no resizing/
    # re-entry feedback, stated as a limitation in REFUTE-YOURSELF).
    kept_pnl = np.where(skip_mask.values, 0.0, sub["net_pnl"].values)
    eq_kept = starting_equity + np.cumsum(kept_pnl)
    peak_kept = np.maximum.accumulate(np.concatenate([[starting_equity], eq_kept]))[1:]
    kept_max_dd = float(((peak_kept - eq_kept) / peak_kept * 100.0).max()) if len(eq_kept) else 0.0

    skipped = sub[skip_mask]
    dd_avoided = float(-skipped.loc[skipped["net_pnl"] < 0, "net_pnl"].sum())
    opp_cost = float(skipped.loc[skipped["net_pnl"] > 0, "net_pnl"].sum())

    return PauseResult(
        threshold=threshold,
        n_skipped=int(skip_mask.sum()),
        n_kept=int((~skip_mask).sum()),
        dd_avoided=round(dd_avoided, 2),
        opportunity_cost=round(opp_cost, 2),
        net_effect=round(dd_avoided - opp_cost, 2),
        baseline_max_dd_pct=round(baseline_max_dd, 2),
        kept_max_dd_pct=round(kept_max_dd, 2),
        skipped_win_rate=round(skipped["win"].mean() * 100, 1) if len(skipped) else float("nan"),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    pd.set_option("display.width", 170)
    pd.set_option("display.max_columns", 20)

    print("=" * 100)
    print("DRAWDOWN-TILT AUDIT -- READ ONLY (4th of 4 risk-mechanic audits; no live state touched)")
    print("=" * 100)

    df = load_trade_ledger(LEDGER_PATH)
    df = compute_dd_metrics(df)
    starting_equity = df["starting_equity"].iloc[0]
    n = len(df)
    baseline_wr = df["win"].mean() * 100
    baseline_mean = df["net_pnl"].mean()
    print(f"\nBack-solved starting equity: ${starting_equity:,.2f}")
    print(f"BASELINE (all 274 trades): win_rate={baseline_wr:.1f}%  mean_net_pnl=${baseline_mean:.2f}  "
          f"total_net_pnl=${df['net_pnl'].sum():.2f}")
    print("This baseline is already well below 50% (bot has no proven edge per prior audits) -- "
          "question 2 (below) is whether in-drawdown buckets are worse than THIS, not worse than a coin flip.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[1] THREE DD-AT-ENTRY METRICS -- construction + cross-validation")
    print("=" * 100)
    print(f"""
1. dd_entry_raw    = live bot's own session_dd_pct field, LAGGED to the last close
                     before this trade's entry_time (entry_time = close_timestamp - hold_hours).
                     Coverage: {df['dd_entry_raw'].notna().sum()}/{n}. Range: [{df['dd_entry_raw'].min():.2f}, {df['dd_entry_raw'].max():.2f}]%
                     NOTE: session_peak_equity resets on every bot restart/epoch-reset (Finding #1)
                     -- max observed is only {df['dd_entry_raw'].max():.1f}%, meaning the bot's own
                     "session" never got anywhere near even the code's own 10% dial tier in this ledger.
2. dd_entry_roll20 = reconstructed, trailing {ROLL_WINDOW}-trade peak (recent-regime proxy).
                     Coverage: {n}/{n} (no missingness). Range: [{df['dd_entry_roll20'].min():.2f}, {df['dd_entry_roll20'].max():.2f}]%
3. dd_entry_full   = reconstructed, ALL-TIME-SINCE-INCEPTION peak (naive full-history cumsum).
                     Coverage: {n}/{n}. Range: [{df['dd_entry_full'].min():.2f}, {df['dd_entry_full'].max():.2f}]%
                     ** REJECTED as a primary metric -- see Finding #3 in module docstring. **
""")
    corr_mat = df[["dd_entry_raw", "dd_entry_roll20", "dd_entry_full"]].corr()
    print("Pairwise correlation matrix (lagged metrics):")
    print(corr_mat.round(3).to_string())
    print(f"\n-> dd_entry_full correlates weakly with dd_entry_raw (r={corr_mat.loc['dd_entry_full','dd_entry_raw']:.2f}) "
          f"and ~ZERO with dd_entry_roll20 (r={corr_mat.loc['dd_entry_full','dd_entry_roll20']:.2f}): confirms it is "
          f"measuring stale career-drawdown, not session/recent tilt. It is shown once more below purely to "
          f"illustrate the degeneracy, then dropped.")
    full_bucket_counts = pd.cut(df["dd_entry_full"], bins=[-100, 5, 10, 100],
                                 labels=["<5%", "5-10%", ">10%"]).value_counts().sort_index()
    print(f"\ndd_entry_full bucket counts (illustration only): \n{full_bucket_counts.to_string()}")
    print(f"-> {full_bucket_counts.get('>10%', 0)}/{n} trades ({full_bucket_counts.get('>10%', 0)/n*100:.0f}%) "
          f"read as '>10% underwater' under the naive full-history reconstruction -- essentially the entire "
          f"post-week-1 ledger. Not usable for bucketing; dropped from the rest of this report.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[2] OUTCOME BY DRAWDOWN-AT-ENTRY BUCKET (win rate / expectancy / rr / variance)")
    print("=" * 100)

    for metric, name in [("dd_entry_raw", "PRIMARY: live bot's own session_dd_pct (lagged)"),
                          ("dd_entry_roll20", f"SECONDARY: reconstructed trailing-{ROLL_WINDOW} peak (lagged)")]:
        print(f"\n--- {name} ---")
        tbl = bucket_table(df, metric, baseline_wr, baseline_mean)
        print(tbl.to_string(index=False))
        chi = chi_square_bucket_vs_win(df, metric)
        if chi:
            chi2, p, dof = chi
            print(f"  Chi-square (bucket x win/loss): chi2={chi2:.2f}, dof={dof}, p={p:.3f} "
                  f"{'(SIGNIFICANT at 0.05)' if p < 0.05 else '(not significant at 0.05)'}")
        else:
            print("  Chi-square: not computable (degenerate table / scipy missing).")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[3] REVENGE-TRADING SIGNATURE: does leverage/confidence shift when the bot is down?")
    print("=" * 100)
    for metric, name in [("dd_entry_raw", "PRIMARY (raw, lagged)"), ("dd_entry_roll20", "SECONDARY (roll20, lagged)")]:
        print(f"\n--- {name} ---")
        rv = revenge_signature(df, metric)
        print(rv.to_string(index=False))
    print("""
Interpretation: a real "revenge-sizing" signature would show mean_leverage and/or mean_confidence
RISING monotonically from the flat bucket into the deep-DD bucket (bot sizing UP or getting more
"confident" specifically when already underwater). Also check `pct_post_collapse` per bucket above --
if the deep-DD bucket is concentrated in one calendar era, any apparent leverage/confidence shift may
be an ERA CONFOUND (different bot config over time), not a live conditional response to drawdown.
Recall Finding #2: execution/risk.py's own graduated drawdown_dial (which WOULD scale size down when
underwater) is dead code -- so any shift found here is emergent LLM-agent behavior, not a scripted
mechanism, and its absence is exactly what you'd expect if nothing in the pipeline reads DD state at
entry-sizing time at all.
""")

    # ------------------------------------------------------------------
    print("=" * 100)
    print("[4] TAUTOLOGY GUARD: same-row (unlagged) vs correctly-lagged correlation with net_pnl")
    print("=" * 100)
    unlagged = df.dropna(subset=["dd_same_row_raw_UNLAGGED"])
    corr_unlagged = unlagged["dd_same_row_raw_UNLAGGED"].corr(unlagged["net_pnl"])
    lagged = df.dropna(subset=["dd_entry_raw"])
    corr_lagged = lagged["dd_entry_raw"].corr(lagged["net_pnl"])
    print(f"corr(session_dd_pct SAME ROW [unlagged, WRONG], net_pnl)      = {corr_unlagged:+.3f}  (n={len(unlagged)})")
    print(f"corr(dd_entry_raw [correctly LAGGED to entry_time], net_pnl)  = {corr_lagged:+.3f}  (n={len(lagged)})")
    print(f"""
The unlagged correlation is mechanically negative-biased: a bigger loss this trade DIRECTLY inflates
this trade's own post-close session_dd_pct reading (same formula, same event). That correlation
partly measures "losses correlate with themselves," not a predictive/actionable relationship. The
LAGGED correlation above (and all bucket tables in section [2]) uses only information available
BEFORE this trade opened -- if the lagged relationship survives at similar strength, that's evidence
of a genuine predictive/actionable effect; if it collapses toward zero relative to the unlagged
number, most of what looked like "tilt" was tautological.
Delta: {corr_unlagged - corr_lagged:+.3f} ({'large drop -> much of the naive effect is tautological' if abs(corr_unlagged) > abs(corr_lagged) * 1.5 else 'comparable magnitude -> not primarily a tautology artifact'}).
""")

    # ------------------------------------------------------------------
    print("=" * 100)
    print("[5] WOULD A PAUSE-WHEN-DOWN RULE HELP? threshold sweep on realized sequence")
    print("=" * 100)

    for metric, name in [("dd_entry_raw", "PRIMARY (raw, lagged)"), ("dd_entry_roll20", "SECONDARY (roll20, lagged)")]:
        print(f"\n--- {name} ---")
        max_val = df[metric].max()
        print(f"  Max dd_entry observed on this metric: {max_val:.2f}%")
        headline_thresholds = [5.0, 8.0, 10.0]
        for t in headline_thresholds:
            r = simulate_pause(df, metric, t, starting_equity)
            print(f"  threshold={t:>4.1f}%: skipped={r.n_skipped:>3} kept={r.n_kept:>3}  "
                  f"dd_avoided=${r.dd_avoided:>8.2f}  opp_cost=${r.opportunity_cost:>8.2f}  "
                  f"net_effect=${r.net_effect:>8.2f}  skipped_WR={r.skipped_win_rate:>5.1f}%  "
                  f"kept_max_DD={r.kept_max_dd_pct:>5.2f}% (baseline_max_DD={r.baseline_max_dd_pct:.2f}%)")
            if r.n_skipped == 0:
                print(f"      -> threshold {t}% is ABOVE the metric's max observed value: NEVER BINDS on this ledger.")

        # Fine grid for flatness/peakiness verdict
        fine_grid = [round(x, 1) for x in np.arange(0.5, max(max_val, 1.0) + 0.5, 0.5)]
        grid_results = [simulate_pause(df, metric, t, starting_equity) for t in fine_grid]
        net_vals = np.array([r.net_effect for r in grid_results])
        binding = np.array([r.n_skipped > 0 for r in grid_results])
        if binding.sum() >= 2:
            net_binding = net_vals[binding]
            rng_ = net_binding.max() - net_binding.min()
            best_idx = int(np.argmax(net_vals))
            print(f"\n  FLATNESS CHECK (fine grid {fine_grid[0]}-{fine_grid[-1]}%, step 0.5, "
                  f"{binding.sum()} binding points): net_effect range=${rng_:,.2f}, "
                  f"std=${net_binding.std():,.2f}, best=${net_vals[best_idx]:,.2f} @ threshold={fine_grid[best_idx]}%")
            verdict = "FLAT (robust-ish)" if rng_ < 50 else "PEAKY (suspect overfit to this exact 274-trade draw)"
            print(f"  -> Grid shape verdict: {verdict}")
        else:
            print(f"\n  FLATNESS CHECK: fewer than 2 binding grid points on this metric -- cannot assess "
                  f"flat-vs-peaky (the threshold range barely touches this metric's observed values).")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[6] REFUTE-YOURSELF")
    print("=" * 100)

    # (a) in-sample overfit -- already demonstrated by the flatness checks above; restate explicitly.
    print("""
(a) IN-SAMPLE OVERFITTING: every threshold and bucket edge above is chosen and scored on the SAME
    274-trade sequence. See the FLATNESS CHECK verdicts in section [5] -- if PEAKY, do not trust a
    single "best" threshold; prefer round numbers on a flat plateau, or conclude "no threshold clearly
    dominates" and do not ship one.""")

    # (b) power + pseudo-replication (episode clustering)
    print(f"""
(b) POWER + PSEUDO-REPLICATION: deep-DD bucket sample sizes on this ledger:""")
    for metric in ["dd_entry_raw", "dd_entry_roll20"]:
        sub = df.dropna(subset=[metric]).copy()
        sub["bucket"] = pd.cut(sub[metric], bins=BUCKET_BINS, labels=BUCKET_LABELS)
        n_deep = int((sub["bucket"] == "deep DD (>5%)").sum())
        ep = episode_clustering(df, metric)
        print(f"    {metric}: n_deep={n_deep} (of {len(sub)} covered). "
              f"At n={n_deep}, a two-proportion test can only reliably detect LARGE (>=20-25pp) win-rate "
              f"gaps from baseline ({baseline_wr:.0f}%) -- a true 5-10pp tilt effect would likely NOT reach "
              f"significance at this sample size (underpowered, not evidence of no effect).")
        if ep["n"] > 0:
            print(f"      PSEUDO-REPLICATION CHECK: all {ep['n']} deep-DD trades fall into "
                  f"{ep['n_episodes']} contiguous episode(s) (48h-gap clustering), spanning "
                  f"{ep['span_days']} calendar days ({ep['first'].date()} -> {ep['last'].date()}).")
            if ep["n_episodes"] <= 2:
                print(f"      -> chi-square/permutation p-values above ASSUME independent draws across "
                      f"trades. With effectively {ep['n_episodes']} independent episode(s) generating "
                      f"ALL {ep['n']} deep-DD rows, the TRUE degrees of freedom for this comparison is "
                      f"closer to {ep['n_episodes']} than {ep['n']} -- treat the 'significant' p-value in "
                      f"section [2] (if any) as describing ONE historical bad stretch, not a repeatable "
                      f"conditional pattern sampled across the bot's history. This is a stronger and more "
                      f"concrete version of the generic small-n caveat above.")

    # (c) tautology -- restate + a plain-language distinction
    print("""
(c) TAUTOLOGY CHECK: "drawdowns contain losses by definition" would show up as a STRONG unlagged
    correlation in section [4] that collapses once lagged. The distinction that matters: "the
    drawdown level BEFORE this trade opened predicts THIS trade's outcome" (actionable -- a pause
    rule could exploit it) vs. "a trade that just lost pushed the account further into drawdown"
    (tautological -- true by arithmetic, not predictive of anything forward-looking). Every bucket
    table and pause simulation in this script uses only the lagged, entry-time-prior version -- if
    section [2]'s buckets still show a real gap, it survives this check by construction.""")

    # (d) era split
    print("\n(d) SIZE-COLLAPSE ERA SPLIT (pre/post 2026-07-26, per project memory):")
    pre = df[df["dt_utc"] < SIZE_COLLAPSE_DATE]
    post = df[df["dt_utc"] >= SIZE_COLLAPSE_DATE]
    print(f"    Pre-collapse:  n={len(pre)}, win_rate={pre['win'].mean()*100:.1f}%, "
          f"mean|net_pnl|=${pre['net_pnl'].abs().mean():.2f}, dd_entry_raw coverage={pre['dd_entry_raw'].notna().sum()}")
    print(f"    Post-collapse: n={len(post)}, win_rate={post['win'].mean()*100:.1f}%, "
          f"mean|net_pnl|=${post['net_pnl'].abs().mean():.2f}, dd_entry_raw coverage={post['dd_entry_raw'].notna().sum()}")
    if len(post) >= 5:
        for metric in ["dd_entry_raw", "dd_entry_roll20"]:
            post_sub = post.dropna(subset=[metric])
            if len(post_sub) >= 5:
                print(f"    Post-collapse {metric}: range=[{post_sub[metric].min():.2f}, {post_sub[metric].max():.2f}]%, "
                      f"n_deep(>5%)={(post_sub[metric] > 5).sum()}")
    else:
        print(f"    Post-collapse n={len(post)} is TOO SMALL for any independent bucket read -- "
              f"any post-collapse-specific claim about drawdown-tilt would be pure noise. Not attempted.")
    print("    At collapsed notional (~$278 median per project memory), dollar amounts in section [5]'s")
    print("    pause simulation are dominated by the PRE-collapse era's larger trades -- a pause rule sized")
    print("    off this ledger's dollar totals would be calibrated mostly to a regime that no longer exists.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[7] VERDICT")
    print("=" * 100)

    raw_tbl = bucket_table(df, "dd_entry_raw", baseline_wr, baseline_mean)
    deep_row = raw_tbl[raw_tbl["bucket"] == "deep DD (>5%)"]
    deep_n = int(deep_row["n"].iloc[0]) if not deep_row.empty else 0
    deep_p = float(deep_row["p_wr_vs_rest"].iloc[0]) if not deep_row.empty and deep_row["n"].iloc[0] > 0 else float("nan")
    chi = chi_square_bucket_vs_win(df, "dd_entry_raw")
    chi_p = chi[1] if chi else float("nan")

    print(f"""
Baseline: {n} trades, {baseline_wr:.1f}% WR, ${baseline_mean:.2f} mean net_pnl (bot has no proven
entry edge per prior audits -- this is the correct comparison point, not 50%).

PRIMARY metric (live bot's own session_dd_pct, correctly lagged to entry time):
  - deep-DD bucket (>5%): n={deep_n}, p(WR vs rest)={deep_p if deep_p==deep_p else float('nan'):.3f}
  - overall chi-square bucket-vs-outcome: p={chi_p if chi_p==chi_p else float('nan'):.3f}
  - max session DD ever seen at entry, this whole ledger: {df['dd_entry_raw'].max():.1f}% -- the bot's
    OWN session concept never got remotely close to a serious drawdown in this data (sessions reset
    on every restart; see Finding #1). A "pause after -5/-8/-10% session DD" rule would almost never
    fire on this metric as defined, because the live session rarely runs long enough to accumulate one.

SECONDARY metric (reconstructed trailing-{ROLL_WINDOW}-trade peak, more "recent regime" flavored):
  - gives more binding thresholds (max {df['dd_entry_roll20'].max():.1f}%) and DOES show a
    statistically-significant bucket-vs-outcome chi-square in section [2] (flat WR 47% -> deep WR
    14%). But before reading that as "real": (i) it is a RECONSTRUCTION the live bot does not
    track -- a pause rule on it needs NEW live state (a rolling-peak tracker) that doesn't exist
    today; (ii) the dollar-magnitude difference for the SAME bucket is NOT significant (only the
    win-rate framing is) -- see p_pnl_vs_rest in section [2]; (iii) the pause-threshold sweep for
    this metric is PEAKY, with the "best" net_effect sitting at the edge of the grid (0.5%), a
    classic overfit signature, not a plateau; (iv) most importantly -- see section [6](b) -- EVERY
    deep-DD trade under BOTH metrics falls inside ONE contiguous mid-June episode (2026-06-08 to
    2026-06-22), not scattered independent draws across the bot's 2-month history. The effective
    sample size behind the "significant" p-value is closer to ONE bad stretch than {deep_n}+
    independent trials.

REVENGE-TRADING SIGNATURE: NOT FOUND. Section [3] shows leverage essentially flat-to-LOWER in the
deep-DD bucket (roll20: 1.19x deep vs 1.72x flat -- opposite of sizing-up-to-recover), and confidence
data is entirely UNAVAILABLE for the deep-DD trades (they predate confidence-score logging, another
symptom of the single-episode confound above). Combined with Finding #2 (the codebase's own
drawdown-based size dial is dead code, never called), there is no evidence -- neither behavioral nor
mechanistic -- of the bot trading more aggressively when down.

HONEST READ: with n this small in the only bucket that would matter (deep DD, n={deep_n} on the
PRIMARY live-tracked metric, confined to one historical episode on either metric), this script is
UNDERPOWERED and CONFOUNDED-BY-EPISODE-CLUSTERING to confirm a real, repeatable drawdown-tilt effect.
The PRIMARY (live) metric alone shows a clean null (p=0.698 overall, p=0.397 for the deep bucket).
The SECONDARY metric's nominally-significant win-rate gap is better read as "one bad mid-June stretch
looked bad while it was happening" (autocorrelation/tautology-adjacent) rather than "being in a
drawdown causally predicts the next trade will lose," especially given Finding #2 shows nothing in
the live pipeline even reads drawdown state at sizing time to produce such an effect mechanistically.

RECOMMENDATION: DO NOT ship a pause-after-drawdown rule off this analysis alone. If the owner wants
to pursue it: (1) wire and A/B the ALREADY-WRITTEN but dead execution/risk.py `get_drawdown_dial()`
in SHADOW/logging-only mode first (zero behavior risk, generates the exact live-conditioned data this
ledger cannot provide), (2) revisit this test after collecting enough post-collapse-era trades to
have a real deep-DD bucket, (3) treat any threshold from section [5] as a hypothesis to shadow-test,
not a number to hardcode. All of this is OWNER-GATED -- nothing in execution/ or core/ was touched by
this script.
""")


if __name__ == "__main__":
    main()
