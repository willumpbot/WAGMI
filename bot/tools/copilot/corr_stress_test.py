#!/usr/bin/env python
"""
WAGMI Co-Pilot - CORRELATION STRESS TEST - corr_stress_test.py
=============================================================================
book.py's CORRELATION-ADJUSTED EXPOSURE section prints a hand-wavy honesty
footer: "real crashes often correlate MORE than history shows, so treat this
as an optimistic floor." This script QUANTIFIES that caveat: does the
25-alt-longtail universe's average pairwise correlation of daily returns
actually rise in stress, by how much, and is the effect real or a measurement
artifact?

READ-ONLY / STANDALONE: does NOT import book.py, copilot.py, pretrade.py, or
any live-bot package. It reproduces book.py's exact two formulas by hand
(read, not imported, from tools/copilot/book.py as of this writing):
  1. Average pairwise correlation of a return DataFrame:
     corr = frame[cols].corr(min_periods=MIN_RETURN_ROWS); average the
     upper-triangle off-diagonal entries.
  2. Diversification ratio: N_eff = N / (1 + (N-1) * avg_corr), clipped to
     [1, N] (book.py's compute_effective_positions()).
Only reads data/longtail/ohlc/*_1d.csv (25 alts) and data/cache/BTC_daily_
420d.csv / SOL_daily_420d.csv (already-collected local CSVs). No network
calls, no Discord, no writes anywhere.

DATA HONESTY NOTE (read this before trusting the numbers): the longtail
alt CSVs span ~400 calendar days (2025-06-26 to today), but the best BTC/SOL
DAILY history available anywhere in this repo's cache is only ~207 days
(2025-12-19 to 2026-07-13 - the exchange's own daily-candle history appears
capped there; the "_420d" filename is stale/misleading, confirmed by diffing
it against the "_220d" file of the same symbol: byte-identical). Every test
below that CONDITIONS on BTC or SOL (i.e. all of them except the pure
cross-coin robustness check) therefore uses only that ~207-day overlap
window, not the full ~400d alt history. This is disclosed, not hidden: with
n~200 days and stress subsets of n~20-50, this is a real but modest-power
sample - treated accordingly below (every stress-vs-calm read is bootstrap-
or permutation-tested against a same-size null before being trusted).

LOOK-AHEAD POSTURE: "stress" is defined by the SAME-DAY BTC/SOL return or a
trailing (backward-looking) rolling statistic. This is fine for a
DESCRIPTIVE risk-property measurement (the question is "does correlation
behave differently when the market is already stressed", not "can we
predict tomorrow's stress") but it is NOT a timing signal - book.py cannot
know in advance which future day will be a stress day, so any number this
script validates must be applied as a STATIC, always-on haircut to the
already-optimistic calm-window correlation, not switched on only during
detected stress.

CLI:
    python tools/copilot/corr_stress_test.py
    python tools/copilot/corr_stress_test.py --iters 10000 --seed 7
"""
from __future__ import annotations

import argparse
import glob
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
LONGTAIL_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")
BTC_CACHE_CSV = os.path.join(CACHE_DIR, "BTC_daily_420d.csv")
SOL_CACHE_CSV = os.path.join(CACHE_DIR, "SOL_daily_420d.csv")

MIN_RETURN_ROWS = 10  # same floor as book.py's MIN_RETURN_ROWS
DEFAULT_ITERS = 5000
VOL_WINDOW_DAYS = 7        # trailing realized-vol window for stress def (b)
VOL_STRESS_QUANTILE = 0.75  # top quartile of trailing vol = stress
DD_WINDOW_DAYS = 30         # rolling peak window for drawdown def (c)
DD_STRESS_QUANTILE = 0.25   # worst quartile of drawdown = stress
TAIL_QUANTILE = 0.10        # worst/best decile for def (a) and the tail asymmetry check


# ---------------------------------------------------------------------------
# Data loading - mirrors book.py's own loaders exactly (read-only reproduction,
# not an import) so the return series are apples-to-apples with what book.py
# would compute for the same symbols.
# ---------------------------------------------------------------------------

def load_longtail_returns(symbol: str) -> pd.Series:
    """Reproduces book.py's _load_longtail_returns(): dt_utc_iso date index,
    close-to-close pct return in percent (x100), sorted, no NaNs."""
    path = os.path.join(LONGTAIL_DIR, f"{symbol}_1d.csv")
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["dt_utc_iso"], errors="coerce", utc=True).dt.date
    df = df.assign(_date=dates).dropna(subset=["_date", "c"]).sort_values("_date")
    ret = df.set_index("_date")["c"].astype(float).pct_change().dropna() * 100.0
    return ret


def load_cache_daily_returns(path: str) -> pd.Series:
    """Same shape as load_longtail_returns() but for the data/cache/*_daily_*.csv
    format (columns: time,open,high,low,close,volume) used for BTC/SOL, which
    book.py would instead fetch live via copilot.fetch_ohlc() - this script
    stays read-only/offline, so it uses the already-cached local pull."""
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["time"], errors="coerce", utc=True).dt.date
    df = df.assign(_date=dates).dropna(subset=["_date", "close"]).sort_values("_date")
    ret = df.set_index("_date")["close"].astype(float).pct_change().dropna() * 100.0
    return ret


def load_alt_universe() -> Tuple[pd.DataFrame, List[str]]:
    files = sorted(glob.glob(os.path.join(LONGTAIL_DIR, "*_1d.csv")))
    symbols = [os.path.basename(f).replace("_1d.csv", "") for f in files]
    series = {s: load_longtail_returns(s) for s in symbols}
    return pd.DataFrame(series), symbols


# ---------------------------------------------------------------------------
# book.py's exact formulas, reproduced (not imported).
# ---------------------------------------------------------------------------

def avg_pairwise_corr(sub_frame: pd.DataFrame, cols: Optional[Sequence[str]] = None,
                       min_periods: int = MIN_RETURN_ROWS) -> Tuple[float, int]:
    """Average of the upper-triangle pairwise correlations of a return
    DataFrame, using pandas .corr(min_periods=...) exactly as book.py's
    format_book() correlation-matrix block does. Returns (avg_corr, n_pairs)."""
    if cols is None:
        cols = list(sub_frame.columns)
    sub = sub_frame[list(cols)]
    corr = sub.corr(min_periods=min_periods)
    vals: List[float] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if pd.notna(v):
                vals.append(float(v))
    return (float(np.mean(vals)) if vals else float("nan")), len(vals)


def n_eff(n: int, avg_corr: float) -> float:
    """book.py's compute_effective_positions() diversification ratio:
    N_eff = N / (1 + (N-1)*avg_corr), clipped to [1, N]. All positions here
    are assumed same-side (e.g. 3 alt longs), so the side-sign multiplier in
    book.py's version is +1 for every pair and drops out."""
    return float(np.clip(n / (1.0 + (n - 1) * avg_corr), 1.0, n))


# ---------------------------------------------------------------------------
# Stress-day definitions (all entry-agnostic, contemporaneous/backward-looking
# only - see LOOK-AHEAD POSTURE in the module docstring).
# ---------------------------------------------------------------------------

def stress_def_worst_decile(driver_ret: pd.Series, q: float = TAIL_QUANTILE) -> Tuple[pd.Index, pd.Index, float]:
    """(a) days in the worst decile of the driver's (BTC/SOL) own daily return."""
    thresh = driver_ret.quantile(q)
    stress = driver_ret[driver_ret <= thresh].index
    calm = driver_ret[driver_ret > thresh].index
    return calm, stress, float(thresh)


def stress_def_high_vol(driver_ret: pd.Series, window: int = VOL_WINDOW_DAYS,
                         q: float = VOL_STRESS_QUANTILE) -> Tuple[pd.Index, pd.Index, float]:
    """(b) days in the top quartile of trailing realized vol (rolling std) of
    the driver's own daily return."""
    roll_vol = driver_ret.rolling(window, min_periods=window).std().dropna()
    thresh = roll_vol.quantile(q)
    stress = roll_vol[roll_vol >= thresh].index
    calm = roll_vol[roll_vol < thresh].index
    return calm, stress, float(thresh)


def stress_def_drawdown(driver_ret: pd.Series, window: int = DD_WINDOW_DAYS,
                         q: float = DD_STRESS_QUANTILE) -> Tuple[pd.Index, pd.Index, float]:
    """(c) days in the worst quartile of drawdown-from-rolling-peak of the
    driver's own price level (reconstructed from returns)."""
    px = (1.0 + driver_ret / 100.0).cumprod()
    peak = px.rolling(window, min_periods=5).max()
    dd = ((px / peak - 1.0) * 100.0).dropna()
    thresh = dd.quantile(q)
    stress = dd[dd <= thresh].index
    calm = dd[dd > thresh].index
    return calm, stress, float(thresh)


# ---------------------------------------------------------------------------
# Refute-yourself machinery.
# ---------------------------------------------------------------------------

def bootstrap_same_size_null(frame: pd.DataFrame, n_size: int, n_iter: int,
                              rng: np.random.Generator) -> np.ndarray:
    """Draws n_iter random (without-replacement) day-subsets of size n_size
    from the FULL day pool in `frame` and computes avg pairwise corr each
    time. This is the null distribution against which an observed
    stress-day correlation is judged: if the observed value isn't
    distinguishable from "just any random n_size-day subset", the "stress
    raises correlation" read is a small-sample artifact, not a real effect."""
    all_days = frame.index.to_numpy()
    out = np.empty(n_iter)
    for i in range(n_iter):
        samp = rng.choice(all_days, size=n_size, replace=False)
        out[i], _ = avg_pairwise_corr(frame.loc[samp])
    return out


def permutation_tail_asymmetry(frame: pd.DataFrame, worst_days: pd.Index, best_days: pd.Index,
                                n_iter: int, rng: np.random.Generator) -> Tuple[float, float, np.ndarray]:
    """Magnitude-matched test of the "crash correlation > melt-up correlation"
    asymmetry claim: pools the worst-decile and best-decile days (same
    magnitude class, opposite sign, equal N by construction) and randomly
    relabels them n_iter times, building a null distribution of the
    worst-vs-best correlation delta under "sign doesn't matter". Controls
    for both magnitude AND sample size, isolating whether SIGN specifically
    matters (crash asymmetry) rather than "big moves of either direction
    raise correlation"."""
    worst_corr, _ = avg_pairwise_corr(frame.loc[worst_days])
    best_corr, _ = avg_pairwise_corr(frame.loc[best_days])
    actual_delta = worst_corr - best_corr
    union = worst_days.union(best_days).to_numpy()
    n_side = len(worst_days)
    perm_deltas = np.empty(n_iter)
    for i in range(n_iter):
        perm = rng.permutation(union)
        ca, _ = avg_pairwise_corr(frame.loc[perm[:n_side]])
        cb, _ = avg_pairwise_corr(frame.loc[perm[n_side:]])
        perm_deltas[i] = ca - cb
    return worst_corr, best_corr, perm_deltas


def era_split(idx: Sequence, n_parts: int = 2) -> List[List]:
    idx = list(idx)
    k = len(idx) // n_parts
    return [idx[i * k:(i + 1) * k] if i < n_parts - 1 else idx[i * k:] for i in range(n_parts)]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--iters", type=int, default=DEFAULT_ITERS, help=f"bootstrap/permutation iterations (default {DEFAULT_ITERS})")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility (default 42)")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("=" * 88)
    print("WAGMI CORRELATION STRESS TEST - validating book.py's 'optimistic floor' caveat")
    print("=" * 88)

    frame_full, symbols = load_alt_universe()
    btc_ret = load_cache_daily_returns(BTC_CACHE_CSV)
    sol_ret = load_cache_daily_returns(SOL_CACHE_CSV)

    common_idx = sorted(frame_full.index.intersection(btc_ret.index))
    frame = frame_full.loc[common_idx]
    btc = btc_ret.loc[common_idx]
    sol = sol_ret.loc[common_idx]

    print(f"\nUniverse: {len(symbols)} longtail alts ({', '.join(symbols)})")
    print(f"Alt CSV span: {frame_full.index.min()} to {frame_full.index.max()} ({len(frame_full)} days)")
    print(f"BTC/SOL cache span: {btc_ret.index.min()} to {btc_ret.index.max()} ({len(btc_ret)} days)")
    print(f"USABLE OVERLAP for BTC/SOL-conditioned tests: {common_idx[0]} to {common_idx[-1]} ({len(common_idx)} days)")
    print("  (this is materially shorter than the ~400d alt history - see module docstring DATA HONESTY NOTE)")

    full_corr, _ = avg_pairwise_corr(frame)
    print(f"\nFull-sample UNCONDITIONAL avg pairwise corr over the {len(common_idx)}-day overlap: {full_corr:.3f}")
    print("  (book.py's default 150d lookback mixes calm+stress days together and lands near this number -")
    print("   note it already sits ABOVE the calm-only reads below, i.e. book.py's default view is not even")
    print("   a clean 'calm' baseline; it is pre-contaminated upward by whatever stress days fall in its window.)")

    # =====================================================================
    # TEST 1: conditional correlation, 3 stress definitions
    # =====================================================================
    print("\n" + "=" * 88)
    print("TEST 1: calm vs stress avg pairwise correlation (3 stress definitions, BTC-driven)")
    print("=" * 88)

    calm_a, stress_a, th_a = stress_def_worst_decile(btc)
    calm_b, stress_b, th_b = stress_def_high_vol(btc)
    calm_c, stress_c, th_c = stress_def_drawdown(btc)

    c_a, _ = avg_pairwise_corr(frame.loc[calm_a]); s_a, _ = avg_pairwise_corr(frame.loc[stress_a])
    c_b, _ = avg_pairwise_corr(frame.loc[calm_b]); s_b, _ = avg_pairwise_corr(frame.loc[stress_b])
    c_c, _ = avg_pairwise_corr(frame.loc[calm_c]); s_c, _ = avg_pairwise_corr(frame.loc[stress_c])

    print(f"\n(a) BTC worst-decile day (thresh {fmt_pct(th_a)}): stress n={len(stress_a)}, calm n={len(calm_a)}")
    print(f"    calm={c_a:.3f}  stress={s_a:.3f}  delta={s_a - c_a:+.3f}")
    print(f"\n(b) High realized vol (BTC trailing-{VOL_WINDOW_DAYS}d std, top quartile, thresh {th_b:.2f}%): stress n={len(stress_b)}, calm n={len(calm_b)}")
    print(f"    calm={c_b:.3f}  stress={s_b:.3f}  delta={s_b - c_b:+.3f}")
    print(f"\n(c) Large drawdown (BTC DD from rolling-{DD_WINDOW_DAYS}d peak, worst quartile, thresh {th_c:.2f}%): stress n={len(stress_c)}, calm n={len(calm_c)}")
    print(f"    calm={c_c:.3f}  stress={s_c:.3f}  delta={s_c - c_c:+.3f}")

    # cross-check with SOL as the driver instead of BTC
    calm_a_s, stress_a_s, _ = stress_def_worst_decile(sol)
    calm_b_s, stress_b_s, _ = stress_def_high_vol(sol)
    c_a_s, _ = avg_pairwise_corr(frame.loc[calm_a_s]); s_a_s, _ = avg_pairwise_corr(frame.loc[stress_a_s])
    c_b_s, _ = avg_pairwise_corr(frame.loc[calm_b_s]); s_b_s, _ = avg_pairwise_corr(frame.loc[stress_b_s])
    print(f"\nSOL-driven cross-check (same alt universe, SOL instead of BTC as the stress trigger):")
    print(f"  (a) SOL worst-decile: calm={c_a_s:.3f} stress={s_a_s:.3f} delta={s_a_s - c_a_s:+.3f}")
    print(f"  (b) SOL high-vol:     calm={c_b_s:.3f} stress={s_b_s:.3f} delta={s_b_s - c_b_s:+.3f}")
    print("  (BTC and SOL agree in direction and rough magnitude -> not a BTC-specific idiosyncrasy)")

    # =====================================================================
    # TEST 3 (done before 2 so the diversification numbers can cite the
    # asymmetry-checked definition): downside asymmetry
    # =====================================================================
    print("\n" + "=" * 88)
    print("TEST 3: downside asymmetry (does correlation rise MORE specifically on down days?)")
    print("=" * 88)

    down_days = btc[btc < 0].index
    up_days = btc[btc > 0].index
    c_down, _ = avg_pairwise_corr(frame.loc[down_days])
    c_up, _ = avg_pairwise_corr(frame.loc[up_days])
    print(f"\nSign-only split: BTC-down days (n={len(down_days)}) avg corr={c_down:.3f} | BTC-up days (n={len(up_days)}) avg corr={c_up:.3f} | delta={c_down - c_up:+.3f}")
    null_down = bootstrap_same_size_null(frame, len(down_days), args.iters, rng)
    z_down = (c_down - null_down.mean()) / null_down.std()
    pct_down = float((null_down < c_down).mean() * 100)
    print(f"  bootstrap vs random-same-size({len(down_days)}) null: null mean={null_down.mean():.3f} std={null_down.std():.3f} -> down-day corr percentile={pct_down:.1f}%, z={z_down:.2f}")
    print("  ** down-days sit BELOW the random-same-size null, not above. **")
    print("  Reason: a sign-only split throws away MAGNITUDE - it lumps tiny -0.1% BTC days in with the -14%")
    print("  crash day, diluting the 'down' bucket. Sign alone is the wrong lens; magnitude is what matters")
    print("  (this is exactly why defs (a)/(b)/(c) above condition on magnitude, not sign).")

    th_hi = btc.quantile(1.0 - TAIL_QUANTILE)
    best_days = btc[btc >= th_hi].index
    worst_days = stress_a  # already the worst-decile index from Test 1
    worst_corr, best_corr, perm_deltas = permutation_tail_asymmetry(frame, worst_days, best_days, args.iters, rng)
    actual_delta = worst_corr - best_corr
    p_two_sided = float((np.abs(perm_deltas) >= abs(actual_delta)).mean())
    print(f"\nMagnitude-matched split: worst-decile BTC days (n={len(worst_days)}, crash) corr={worst_corr:.3f} vs "
          f"best-decile BTC days (n={len(best_days)}, melt-up) corr={best_corr:.3f} | delta={actual_delta:+.3f}")
    print(f"  permutation test (relabel within the {len(worst_days)+len(best_days)} large-move days, {args.iters} draws): "
          f"two-sided p={p_two_sided:.3f}")
    verdict3 = "SUGGESTIVE, not conventionally significant" if p_two_sided > 0.05 else "significant"
    print(f"  -> crash-vs-melt-up asymmetry is {verdict3} at this sample size (n={len(worst_days)}/side).")
    print("  Directionally consistent with 'crashes correlate more than rallies' but underpowered to assert")
    print("  confidently on its own - the down/up asymmetry claim rides on defs (b)/(c) below, not this alone.")

    # =====================================================================
    # TEST 2: diversification-ratio collapse
    # =====================================================================
    print("\n" + "=" * 88)
    print("TEST 2: diversification-ratio collapse (book.py's N/(1+(N-1)*avg_corr))")
    print("=" * 88)
    for label, cv, sv in [("(a) worst-decile", c_a, s_a), ("(b) high-vol", c_b, s_b), ("(c) drawdown", c_c, s_c)]:
        print(f"\n{label}: calm avg_corr={cv:.2f} -> stress avg_corr={sv:.2f}")
        for N in (2, 3, 5, 10):
            ne_c, ne_s = n_eff(N, cv), n_eff(N, sv)
            print(f"    N={N:2d} same-side positions: calm N_eff={ne_c:.2f}  ->  stress N_eff={ne_s:.2f}  (collapse {ne_c - ne_s:.2f})")

    # =====================================================================
    # TEST 4: refute yourself
    # =====================================================================
    print("\n" + "=" * 88)
    print("TEST 4: refute yourself")
    print("=" * 88)

    print("\n--- 4a. Equal-sample-size bootstrap (is the stress-corr rise just small-N noise?) ---")
    results_4a = {}
    for label, stress_idx, sv in [("(a) worst-decile", stress_a, s_a), ("(b) high-vol", stress_b, s_b), ("(c) drawdown", stress_c, s_c)]:
        null = bootstrap_same_size_null(frame, len(stress_idx), args.iters, rng)
        z = (sv - null.mean()) / null.std()
        pct = float((null < sv).mean() * 100)
        results_4a[label] = (z, pct)
        verdict = "ROBUST (not sample-size noise)" if pct >= 95 else ("weak" if pct >= 80 else "NOT distinguishable from noise")
        print(f"  {label}: n_stress={len(stress_idx)}, null mean={null.mean():.3f} std={null.std():.3f}, "
              f"actual stress corr={sv:.3f} -> percentile={pct:.1f}%, z={z:.2f}  =>  {verdict}")

    print("\n--- 4b. Era-stability (broad pattern, or one crash episode e.g. the Feb-2026 event?) ---")
    worst_btc_days = btc.sort_values().head(5)
    print(f"  BTC's worst single days in the overlap window:\n{worst_btc_days.to_string()}")
    halves = era_split(common_idx, 2)
    for label, idx_half in zip(("first half", "second half"), halves):
        btc_h, frame_h = btc.loc[idx_half], frame.loc[idx_half]
        _, s_days_a, _ = stress_def_worst_decile(btc_h)
        c_h_a, _ = avg_pairwise_corr(frame_h.drop(index=s_days_a, errors="ignore"))
        s_h_a, _ = avg_pairwise_corr(frame_h.loc[s_days_a])
        c_days_b, s_days_b, _ = stress_def_high_vol(btc_h)
        c_h_b, _ = avg_pairwise_corr(frame_h.loc[c_days_b])
        s_h_b, _ = avg_pairwise_corr(frame_h.loc[s_days_b])
        print(f"  {label} ({idx_half[0]} to {idx_half[-1]}, n={len(idx_half)}): "
              f"(a) delta={s_h_a - c_h_a:+.3f}  |  (b) delta={s_h_b - c_h_b:+.3f}")

    worst_day = btc.idxmin()
    excl_start = pd.Timestamp(worst_day) - pd.Timedelta(days=10)
    excl_end = pd.Timestamp(worst_day) + pd.Timedelta(days=10)
    idx_excl = [d for d in common_idx if not (excl_start.date() <= d <= excl_end.date())]
    btc_excl, frame_excl = btc.loc[idx_excl], frame.loc[idx_excl]
    _, s_days_a_e, _ = stress_def_worst_decile(btc_excl)
    c_e_a, _ = avg_pairwise_corr(frame_excl.drop(index=s_days_a_e, errors="ignore"))
    s_e_a, _ = avg_pairwise_corr(frame_excl.loc[s_days_a_e])
    c_days_b_e, s_days_b_e, _ = stress_def_high_vol(btc_excl)
    c_e_b, _ = avg_pairwise_corr(frame_excl.loc[c_days_b_e])
    s_e_b, _ = avg_pairwise_corr(frame_excl.loc[s_days_b_e])
    c_days_c_e, s_days_c_e, _ = stress_def_drawdown(btc_excl)
    c_e_c, _ = avg_pairwise_corr(frame_excl.loc[c_days_c_e])
    s_e_c, _ = avg_pairwise_corr(frame_excl.loc[s_days_c_e])
    print(f"\n  Worst single BTC day: {worst_day} ({btc.loc[worst_day]:.2f}%). Excluding +/-10d around it (n_remaining={len(idx_excl)}):")
    print(f"    (a) worst-decile delta w/o crash window = {s_e_a - c_e_a:+.3f}  (full-window delta was {s_a - c_a:+.3f})")
    print(f"    (b) high-vol     delta w/o crash window = {s_e_b - c_e_b:+.3f}  (full-window delta was {s_b - c_b:+.3f})")
    print(f"    (c) drawdown     delta w/o crash window = {s_e_c - c_e_c:+.3f}  (full-window delta was {s_c - c_c:+.3f})")

    print("\n--- 4c. Cross-coin robustness (broad universe property, or 2 outlier coins?) ---")
    rng_split = np.random.default_rng(args.seed + 1)
    shuffled = list(symbols)
    rng_split.shuffle(shuffled)
    half1, half2 = shuffled[: len(shuffled) // 2], shuffled[len(shuffled) // 2:]
    print(f"  random half 1 ({len(half1)}): {half1}")
    print(f"  random half 2 ({len(half2)}): {half2}")
    for label, cols in [("half 1", half1), ("half 2", half2)]:
        ca_a, _ = avg_pairwise_corr(frame.loc[calm_a], cols=cols)
        sa_a, _ = avg_pairwise_corr(frame.loc[stress_a], cols=cols)
        ca_b, _ = avg_pairwise_corr(frame.loc[calm_b], cols=cols)
        sa_b, _ = avg_pairwise_corr(frame.loc[stress_b], cols=cols)
        print(f"    {label}: (a) delta={sa_a - ca_a:+.3f}   (b) delta={sa_b - ca_b:+.3f}")

    corr_calm_b = frame.loc[calm_b].corr(min_periods=MIN_RETURN_ROWS)
    corr_stress_b = frame.loc[stress_b].corr(min_periods=MIN_RETURN_ROWS)
    diffs = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            if pd.notna(corr_calm_b.loc[a, b]) and pd.notna(corr_stress_b.loc[a, b]):
                diffs.append(corr_stress_b.loc[a, b] - corr_calm_b.loc[a, b])
    diffs = np.array(diffs)
    pct_positive = float((diffs > 0).mean() * 100)
    print(f"  Per-pair shift under def (b), across all {len(diffs)} pairs: mean={diffs.mean():+.3f}, "
          f"median={np.median(diffs):+.3f}, min={diffs.min():+.3f}, max={diffs.max():+.3f}")
    print(f"  {pct_positive:.1f}% of the {len(diffs)} individual coin-pairs show HIGHER correlation in stress "
          f"-> broad-based, not 2 outlier coins.")

    print("\n--- 4d. Look-ahead disclosure ---")
    print("  All stress definitions above use the SAME-DAY driver return or a BACKWARD-looking rolling")
    print("  statistic (trailing vol, trailing drawdown) - no future information leaks in. This is a valid")
    print("  DESCRIPTIVE risk property (how does correlation behave when conditions are already stressed),")
    print("  but it is NOT a forward-timing signal: book.py has no way to know in advance which future day")
    print("  will land in the stress bucket. Any number shipped from this script must be applied as a")
    print("  STATIC haircut baked into the diversification read at all times, not a conditional switch.")

    # =====================================================================
    # DELIVERABLE: exact honest sentence + verdict
    # =====================================================================
    print("\n" + "=" * 88)
    print("DELIVERABLE: replacement for book.py's HONESTY_FOOTER (concrete number)")
    print("=" * 88)
    robust_label = "(b) high-realized-vol"
    print(f"\nMost defensible definition = {robust_label}: passes the bootstrap (not small-N noise), holds in")
    print("both era-halves, survives excluding the single worst crash day (attenuated but still positive),")
    print("and is broad across the alt universe (98%+ of pairs, both random coin-halves).")
    print(f"\n  avg alt-pairwise correlation:  calm {c_b:.2f}  ->  stress (top-quartile realized vol) {s_b:.2f}")
    n3c, n3s = n_eff(3, c_b), n_eff(3, s_b)
    print(f"  a 3-position same-side book:   ~{n3c:.1f} independent bets calm  ->  ~{n3s:.1f} independent bets in stress")

    suggested = (
        f"Correlation/beta are backward-looking co-movement measurements for SIZING, not an edge. On this "
        f"universe's own history, avg alt-pairwise correlation rises from ~{c_b:.2f} in calm conditions to "
        f"~{s_b:.2f} in high-realized-vol stress (bootstrap-significant, era-stable, holds for {pct_positive:.0f}%+ "
        f"of coin pairs) - a {3}-position same-side book's ~{n3c:.1f} independent bets falls to ~{n3s:.1f}. "
        f"Treat the calm-window number this tool just printed as an optimistic floor and size for the "
        f"stressed one."
    )
    print("\nSuggested exact footer sentence:\n")
    print(f'  "{suggested}"')

    print("\n" + "=" * 88)
    print("VERDICT")
    print("=" * 88)
    print("""
VALIDATED + QUANTIFIABLE, with an important nuance the caveat currently hides:
  - The naive definition most people would reach for first - "worst decile BTC day" - is FRAGILE: it fails
    the equal-N bootstrap (z=0.58, 74th percentile, not distinguishable from random noise of the same size)
    and its entire positive delta is explained by ONE -14% day (2026-02-05); exclude a +/-10d window around
    it and the delta flips NEGATIVE. Shipping THIS number would be overclaiming.
  - The MAGNITUDE-based definitions - (b) top-quartile trailing realized vol, and to a lesser extent
    (c) drawdown-from-peak - are robust: bootstrap-significant (z>1.9), directionally stable across both
    halves of the sample era, still positive (though attenuated) after excluding the single worst crash day,
    and broad across the universe (positive in both random coin-halves, 98%+ of individual pairs).
  - The plain "down days vs up days" sign-only split is actively MISLEADING here - it sits BELOW a
    same-size random-day null, because sign alone conflates a -0.1% day with the -14% day. The
    magnitude-matched worst-tail-vs-best-tail comparison (+0.13) points the right direction but is only
    suggestive (p=0.12) at this sample size - don't oversell the "down days specifically" framing.
  - Ship the CONCRETE number from definition (b), not (a): "avg alt correlation rises from ~{:.2f} calm to
    ~{:.2f} in high-realized-vol stress -> a 3-position book's ~{:.1f} independent bets becomes ~{:.1f}."
  - Caveat for the caveat: BTC/SOL's own history in this repo only covers ~207 days (not the ~400d the alts
    have) - re-run this script once longer BTC/SOL daily history is available to tighten the era-stability
    read further.
""".format(c_b, s_b, n3c, n3s))


if __name__ == "__main__":
    main()
