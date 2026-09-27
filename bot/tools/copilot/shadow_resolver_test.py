"""
shadow_resolver_test.py — Correctly re-resolve feedback/shadow_ledger.py's
data/shadow_ledger.csv (11,528 dormant-strategy shadow predictions) against
REAL OHLC at FIXED, entry-time-safe horizons, instead of the live bot's
broken resolve_shadows() which scores a shadow prediction against whatever
price an UNRELATED live position happened to close at (same symbol, 72s-8h
later, no fixed horizon -> ~81% of rows never resolve, and the ones that do
are noise: entry/exit spacing has nothing to do with the strategy's signal).

READ-ONLY. Standalone. Touches nothing in data/ except to READ csv/ohlc
files already on disk. Never imports or calls the live ShadowLedger class,
never writes to data/shadow_ledger.csv, never posts to Discord.

Usage:
    cd bot && python tools/copilot/shadow_resolver_test.py
"""

from __future__ import annotations

import bisect
import calendar
import csv
import glob
import math
import os
import statistics
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHADOW_CSV = os.path.join(BOT_DIR, "data", "shadow_ledger.csv")
CACHE_DIR = os.path.join(BOT_DIR, "data", "cache")

# Symbols actually present in the shadow ledger (checked empirically —
# only 5 of the ~30 traded/longtail symbols ever got a shadow signal).
SHADOW_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]

HORIZONS_H = [1, 4, 24]           # fixed horizons, hours, per the brief
ROUNDTRIP_FEE = 0.0009            # ~9bps round-trip, per the brief
TOLERANCE_S = 40 * 60             # 40 min: nearest-bar snap tolerance on
                                   # hourly grid before we call it a gap
REACT_MIN_N = 50                  # instrument's own simple gate (get_reactivation_candidates)
REACT_MIN_WR = 0.55
ALPHA = 0.05


# ─────────────────────────────────────────────────────────────────────────
# OHLC loading — merge every data/cache/{SYM}_1h_*.csv fragment (220d/420d/
# 60d/30d rolling windows all coexist on disk with overlapping ranges), dedup
# by bar timestamp, keep the union. This is the best-effort, most-complete
# hourly price series available on disk for each symbol — no live fetch.
# ─────────────────────────────────────────────────────────────────────────

def _parse_bar_time(s: str) -> int:
    s = s.strip().split("+")[0]
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def load_ohlc(symbol: str) -> Tuple[List[int], List[float]]:
    files = glob.glob(os.path.join(CACHE_DIR, f"{symbol}_1h_*.csv"))
    bars: Dict[int, float] = {}
    for f in files:
        try:
            with open(f, newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                for row in reader:
                    if len(row) < 6:
                        continue
                    try:
                        ts = _parse_bar_time(row[5])
                        close = float(row[3])
                    except (ValueError, IndexError):
                        continue
                    bars[ts] = close
        except OSError:
            continue
    tss = sorted(bars.keys())
    closes = [bars[t] for t in tss]
    return tss, closes


def nearest_bar(tss: List[int], closes: List[float], target: float) -> Tuple[Optional[float], Optional[float]]:
    """Return (close_price, abs_seconds_delta) of the bar nearest `target`
    (unix seconds), or (None, None) if the series is empty."""
    if not tss:
        return None, None
    i = bisect.bisect_left(tss, target)
    candidates = []
    if i < len(tss):
        candidates.append(i)
    if i > 0:
        candidates.append(i - 1)
    best_i = min(candidates, key=lambda j: abs(tss[j] - target))
    return closes[best_i], abs(tss[best_i] - target)


# ─────────────────────────────────────────────────────────────────────────
# Shadow ledger loading
# ─────────────────────────────────────────────────────────────────────────

def load_shadow_rows() -> List[Dict[str, str]]:
    with open(SHADOW_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────
# Stats helpers (no scipy dependency, matches project convention in
# validation/power_analysis.py)
# ─────────────────────────────────────────────────────────────────────────

def z_test_wr_vs_null(wins: int, n: int, null_wr: float = 0.5) -> Tuple[float, float]:
    """Two-sided z-test of observed win rate vs a null win rate.
    Returns (z, wr)."""
    if n == 0:
        return 0.0, 0.0
    wr = wins / n
    se = math.sqrt(null_wr * (1 - null_wr) / n)
    if se == 0:
        return 0.0, wr
    z = (wr - null_wr) / se
    return z, wr


def t_test_mean_vs_zero(values: List[float]) -> Tuple[float, float, float]:
    """One-sample t-stat of mean return vs 0. Returns (t, mean, stdev)."""
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0), 0.0
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    if sd == 0:
        return 0.0, mean, 0.0
    t = mean / (sd / math.sqrt(n))
    return t, mean, sd


def approx_p_from_z(z: float) -> float:
    """Two-sided p-value from a z-score using erf (stdlib, no scipy)."""
    return math.erfc(abs(z) / math.sqrt(2))


# min required N for the statistical reactivation gate (mirrors
# validation/power_analysis.min_sample_for_significance(base_wr=0.5, delta=0.10))
def min_sample_for_significance(base_wr=0.5, delta=0.10, power=0.80, alpha=0.05) -> int:
    def norm_ppf(p):
        if p <= 0:
            return -10.0
        if p >= 1:
            return 10.0
        if p == 0.5:
            return 0.0
        if p > 0.5:
            t = math.sqrt(-2.0 * math.log(1 - p))
        else:
            t = math.sqrt(-2.0 * math.log(p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
        return result if p > 0.5 else -result

    z_alpha = norm_ppf(1 - alpha / 2)
    z_beta = norm_ppf(power)
    p = base_wr + delta / 2
    q = 1 - p
    n = ((z_alpha + z_beta) ** 2 * 2 * p * q) / (delta ** 2)
    return int(math.ceil(n))


STAT_GATE_REQUIRED_N = min_sample_for_significance(0.5, 0.10)  # ~389


# ─────────────────────────────────────────────────────────────────────────
# Main resolution pass
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 78)
    print("SHADOW LEDGER — CORRECT (fixed-horizon, entry-time-safe) RE-RESOLUTION")
    print("=" * 78)

    rows = load_shadow_rows()
    print(f"\nLoaded {len(rows)} shadow rows from {SHADOW_CSV}")

    factors = sorted(set(r["factor"] for r in rows))
    symbols_in_ledger = sorted(set(r["symbol"] for r in rows))
    print(f"Factors: {factors}")
    print(f"Symbols in ledger: {symbols_in_ledger}")

    # ---- broken-instrument baseline, straight from the CSV's own fields ----
    print("\n--- (0) BROKEN INSTRUMENT — as currently recorded in the CSV ---")
    resolved_flag_counts = defaultdict(int)
    for r in rows:
        resolved_flag_counts[r["resolved"]] += 1
    print(f"resolved flag counts: {dict(resolved_flag_counts)}")
    broken_true = [r for r in rows if r["resolved"] == "true"]
    print(f"'true'-resolved: {len(broken_true)} / {len(rows)} "
          f"({100*len(broken_true)/len(rows):.1f}%)  "
          f"[expired={resolved_flag_counts.get('expired',0)}, "
          f"pending(false)={resolved_flag_counts.get('false',0)}]")
    for fac in factors:
        sub = [r for r in broken_true if r["factor"] == fac]
        if not sub:
            print(f"  {fac:22s} n=0")
            continue
        rets = [_f(r["actual_return"]) for r in sub]
        wins = sum(1 for x in rets if x > 0)
        print(f"  {fac:22s} n={len(sub):5d}  WR={wins/len(sub):.1%}  "
              f"mean_ret={statistics.mean(rets):+.4%}")

    # ---- OHLC coverage ----
    print("\n--- OHLC coverage (data/cache/{SYM}_1h_*.csv, merged) ---")
    ohlc: Dict[str, Tuple[List[int], List[float]]] = {}
    for sym in SHADOW_SYMBOLS:
        tss, closes = load_ohlc(sym)
        ohlc[sym] = (tss, closes)
        if tss:
            print(f"  {sym:6s} n_bars={len(tss):5d}  span="
                  f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(tss[0]))} -> "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(tss[-1]))}")
        else:
            print(f"  {sym:6s} NO OHLC FOUND")

    missing_symbols = [s for s in symbols_in_ledger if s not in SHADOW_SYMBOLS]
    if missing_symbols:
        print(f"  WARNING: shadow symbols with no OHLC mapping attempted: {missing_symbols}")

    # ---- resolve each row at each horizon ----
    # per-row result: dict[(factor,horizon)] -> list of row-results
    ResultRow = Dict[str, object]
    results: Dict[Tuple[str, int], List[ResultRow]] = defaultdict(list)
    gap_reasons: Dict[Tuple[str, int], Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        sym = r["symbol"]
        fac = r["factor"]
        side = r["predicted_side"].upper()
        entry_ts = _f(r["timestamp"])
        entry_price = _f(r["entry_price"])
        day = time.strftime("%Y-%m-%d", time.gmtime(entry_ts))

        if side not in ("BUY", "SELL"):
            continue
        if entry_price <= 0:
            continue

        tss, closes = ohlc.get(sym, ([], []))
        if not tss:
            for h in HORIZONS_H:
                gap_reasons[(fac, h)]["no_ohlc_for_symbol"] += 1
            continue

        for h in HORIZONS_H:
            target = entry_ts + h * 3600
            exit_price, delta_s = nearest_bar(tss, closes, target)
            if exit_price is None:
                gap_reasons[(fac, h)]["no_ohlc_for_symbol"] += 1
                continue
            if target > tss[-1] + TOLERANCE_S:
                # target is beyond the end of available coverage entirely —
                # distinct from a mid-series hole
                gap_reasons[(fac, h)]["beyond_coverage_end"] += 1
                continue
            if delta_s > TOLERANCE_S:
                gap_reasons[(fac, h)]["mid_series_gap"] += 1
                continue

            if side == "BUY":
                raw_ret = (exit_price - entry_price) / entry_price
            else:
                raw_ret = (entry_price - exit_price) / entry_price
            net_ret = raw_ret - ROUNDTRIP_FEE

            results[(fac, h)].append({
                "symbol": sym,
                "day": day,
                "entry_ts": entry_ts,
                "side": side,
                "raw_ret": raw_ret,
                "net_ret": net_ret,
                "confidence": _f(r["confidence"]),
            })

    # ---- (1) correctly-resolved per-strategy per-horizon stats ----
    print("\n--- (1) CORRECTLY-RESOLVED per-strategy per-horizon ---")
    header = (f"{'factor':22s} {'h':>3s} {'N_res':>6s} {'resN%':>7s} "
              f"{'WR_raw':>7s} {'WR_net':>7s} {'mean_raw':>9s} {'mean_net':>9s} "
              f"{'z(WR-50)':>9s} {'p':>7s} {'t(ret-0)':>9s}")
    print(header)
    print("-" * len(header))

    summary_for_gates: Dict[Tuple[str, int], Dict[str, object]] = {}

    for fac in factors:
        fac_total_n = sum(1 for r in rows if r["factor"] == fac and r["predicted_side"].upper() in ("BUY", "SELL"))
        for h in HORIZONS_H:
            res = results[(fac, h)]
            n = len(res)
            res_pct = 100 * n / fac_total_n if fac_total_n else 0.0
            if n == 0:
                print(f"{fac:22s} {h:>3d} {n:6d} {res_pct:6.1f}% "
                      f"{'--':>7s} {'--':>7s} {'--':>9s} {'--':>9s} {'--':>9s} {'--':>7s} {'--':>9s}")
                continue
            raw_rets = [r["raw_ret"] for r in res]
            net_rets = [r["net_ret"] for r in res]
            wins_raw = sum(1 for x in raw_rets if x > 0)
            wins_net = sum(1 for x in net_rets if x > 0)
            wr_raw = wins_raw / n
            wr_net = wins_net / n
            z, _ = z_test_wr_vs_null(wins_net, n, 0.5)
            p = approx_p_from_z(z)
            t_stat, mean_net, sd_net = t_test_mean_vs_zero(net_rets)
            mean_raw = statistics.mean(raw_rets)

            print(f"{fac:22s} {h:>3d} {n:6d} {res_pct:6.1f}% "
                  f"{wr_raw:6.1%} {wr_net:6.1%} {mean_raw:+8.4%} {mean_net:+8.4%} "
                  f"{z:8.2f} {p:6.3f} {t_stat:8.2f}")

            summary_for_gates[(fac, h)] = {
                "n": n, "wr_raw": wr_raw, "wr_net": wr_net,
                "mean_raw": mean_raw, "mean_net": mean_net,
                "z": z, "p": p, "t": t_stat, "rows": res,
            }
        # gap breakdown for this factor
        gaps = {}
        for h in HORIZONS_H:
            for reason, cnt in gap_reasons[(fac, h)].items():
                gaps.setdefault(h, {})[reason] = cnt
        if gaps:
            print(f"    gaps: {gaps}")

    # ---- (2) reactivation gate re-run ----
    print("\n--- (2) REACTIVATION GATE RE-RUN ---")
    print(f"Simple gate (shadow_ledger.get_reactivation_candidates): n>={REACT_MIN_N}, WR>={REACT_MIN_WR:.0%}")
    print(f"Statistical gate (validation.power_analysis.can_reactivate_strategy): "
          f"n>={STAT_GATE_REQUIRED_N} (power=0.80,delta=10pp,alpha={ALPHA}), "
          f"z-significant WR>50%, mean_net_pnl>0")

    any_cleared_simple = []
    any_cleared_stat = []
    for (fac, h), s in summary_for_gates.items():
        n = s["n"]
        # Simple gate — instrument evaluates WR on raw actual_return (as coded);
        # show both raw and net-of-fee versions since raw is what the live
        # instrument actually checks, net is the economically honest version.
        simple_raw = (n >= REACT_MIN_N and s["wr_raw"] >= REACT_MIN_WR)
        simple_net = (n >= REACT_MIN_N and s["wr_net"] >= REACT_MIN_WR)

        significant = n >= 10 and s["wr_net"] > 0.5 and s["z"] > 1.6449  # one-sided z_crit(alpha=.05)
        stat_gate = (n >= STAT_GATE_REQUIRED_N and significant and s["mean_net"] > 0)

        flag = []
        if simple_raw:
            flag.append("SIMPLE-GATE(raw)")
        if simple_net:
            flag.append("SIMPLE-GATE(net)")
        if stat_gate:
            flag.append("STAT-GATE")
        if flag:
            print(f"  {fac:22s} h={h:2d}h  n={n:5d}  WR_raw={s['wr_raw']:.1%}  "
                  f"WR_net={s['wr_net']:.1%}  mean_net={s['mean_net']:+.4%}  -> {', '.join(flag)}")
            if simple_raw or simple_net:
                any_cleared_simple.append((fac, h))
            if stat_gate:
                any_cleared_stat.append((fac, h))

    if not any_cleared_simple and not any_cleared_stat:
        print("  NONE. No (factor, horizon) combination clears either gate on correctly-resolved data.")

    # Contrast: what did the BROKEN instrument's check_reactivation() actually
    # see, using its own pooled (cross-horizon, cross-symbol, mis-timed) numbers?
    print("\n  Contrast — broken instrument's own numbers (resolved=='true' rows, no horizon concept):")
    for fac in factors:
        sub = [r for r in broken_true if r["factor"] == fac]
        n = len(sub)
        if n == 0:
            continue
        rets = [_f(r["actual_return"]) for r in sub]
        wins = sum(1 for x in rets if x > 0)
        wr = wins / n
        cleared = n >= REACT_MIN_N and wr >= REACT_MIN_WR
        print(f"    {fac:22s} n={n:5d}  WR={wr:.1%}  simple-gate={'CLEARS' if cleared else 'no'}")

    # ---- (3) era-decisive + non-overlap ----
    print("\n--- (3) ERA-DECISIVE + NON-OVERLAP CHECK (for anything that cleared a gate) ---")
    cleared_combos = sorted(set(any_cleared_simple) | set(any_cleared_stat))
    if not cleared_combos:
        print("  Nothing cleared a gate in step (2) — checking underpowered per-strategy read instead.")
        for fac in factors:
            # best horizon by n for a quick underpowered-or-genuinely-null read
            best_h = max(HORIZONS_H, key=lambda h: summary_for_gates.get((fac, h), {}).get("n", 0))
            s = summary_for_gates.get((fac, best_h))
            if not s:
                continue
            required_n = STAT_GATE_REQUIRED_N
            verdict = "adequately powered, null result (dead)" if s["n"] >= required_n else \
                      f"UNDERPOWERED (n={s['n']} vs required {required_n} for a 10pp WR delta at 80% power)"
            print(f"  {fac:22s} h={best_h}h  n={s['n']}  WR_net={s['wr_net']:.1%}  mean_net={s['mean_net']:+.4%}  -> {verdict}")
    else:
        for fac, h in cleared_combos:
            s = summary_for_gates[(fac, h)]
            res = s["rows"]
            # era split: contiguous calendar-week buckets across the ledger span
            by_week: Dict[str, List[float]] = defaultdict(list)
            by_symbol: Dict[str, List[float]] = defaultdict(list)
            cluster_rets: Dict[Tuple[str, str], List[float]] = defaultdict(list)
            for row in res:
                week_start = time.strftime("%Y-%m-%d", time.gmtime(row["entry_ts"] - (int(time.gmtime(row["entry_ts"]).tm_wday) * 86400)))
                by_week[week_start].append(row["net_ret"])
                by_symbol[row["symbol"]].append(row["net_ret"])
                cluster_rets[(row["symbol"], row["day"])].append(row["net_ret"])

            n_clusters = len(cluster_rets)
            print(f"\n  {fac} @ {h}h  (raw n={s['n']}, WR_net={s['wr_net']:.1%}, z={s['z']:.2f}, p={s['p']:.4f})")
            print(f"    NON-OVERLAP: {s['n']} rows -> {n_clusters} unique (symbol,day) clusters "
                  f"({n_clusters/s['n']:.1%} of raw n) — avg {s['n']/n_clusters:.0f} near-duplicate "
                  f"predictions per cluster-day (same regime/trend re-fired every bot loop)")

            # Cluster-level test: one observation per (symbol,day) = its mean net
            # return. This is the honest effective-N test — raw-row p-values
            # above are inflated by autocorrelated re-firing within a cluster-day.
            cluster_means = [statistics.mean(v) for v in cluster_rets.values()]
            cluster_wins = sum(1 for m in cluster_means if m > 0)
            cluster_wr = cluster_wins / n_clusters
            ct, c_mean, c_sd = t_test_mean_vs_zero(cluster_means)
            cz, _ = z_test_wr_vs_null(cluster_wins, n_clusters, 0.5)
            cp = approx_p_from_z(cz)
            passes_simple_gate_clustered = n_clusters >= REACT_MIN_N and cluster_wr >= REACT_MIN_WR
            print(f"    CLUSTER-LEVEL (effective N={n_clusters}): WR={cluster_wr:.1%}  "
                  f"mean={c_mean:+.4%}  t(mean-0)={ct:.2f}  z(WR-50)={cz:.2f}  p={cp:.3f}  "
                  f"-> simple-gate(n>=50,WR>=55%) {'CLEARS' if passes_simple_gate_clustered else 'FAILS'} "
                  f"at cluster-level N")

            print(f"    by symbol (raw rows): " + ", ".join(
                f"{sym}: n={len(v)} WR={sum(1 for x in v if x>0)/len(v):.0%}"
                for sym, v in sorted(by_symbol.items(), key=lambda kv: -len(kv[1]))))
            max_symbol_share = max(len(v) for v in by_symbol.values()) / s["n"]
            print(f"    max single-symbol share of raw n: {max_symbol_share:.0%} "
                  f"{'(CONCENTRATED — likely one-symbol artifact)' if max_symbol_share > 0.6 else '(spread across symbols)'}")
            print(f"    by calendar week (Mon start):")
            for week in sorted(by_week.keys()):
                v = by_week[week]
                wr = sum(1 for x in v if x > 0) / len(v)
                print(f"      week of {week}: n={len(v):4d}  WR_net={wr:.1%}  mean_net={statistics.mean(v):+.4%}")
            week_wrs = [sum(1 for x in v if x > 0) / len(v) for v in by_week.values() if len(v) >= 5]
            n_active_weeks = len(by_week)
            if len(week_wrs) >= 2:
                stable = (max(week_wrs) - min(week_wrs)) < 0.30
                print(f"    era-stability: {n_active_weeks} active weeks, WR range "
                      f"[{min(week_wrs):.0%}, {max(week_wrs):.0%}] "
                      f"-> {'STABLE-ish' if stable else 'UNSTABLE (regime/era-dependent, likely a relic)'}")

    # ---- (4) instrument verdict ----
    print("\n--- (4) INSTRUMENT VERDICT ---")
    broken_resolved_pct = 100 * len(broken_true) / len(rows)
    correct_resolved_pcts = {}
    for h in HORIZONS_H:
        n_res = sum(s["n"] for (fac, hh), s in summary_for_gates.items() if hh == h)
        n_tot = sum(1 for r in rows if r["predicted_side"].upper() in ("BUY", "SELL"))
        correct_resolved_pcts[h] = 100 * n_res / n_tot if n_tot else 0.0
    print(f"  Broken instrument resolved: {broken_resolved_pct:.1f}% of rows (resolved=='true')")
    for h in HORIZONS_H:
        print(f"  Correct fixed-horizon resolution @ {h}h: {correct_resolved_pcts[h]:.1f}% of rows")
    print("  (Gap causes are broken out per-factor above: no_ohlc_for_symbol / "
          "beyond_coverage_end / mid_series_gap.)")

    print("\nDone.")


if __name__ == "__main__":
    main()
