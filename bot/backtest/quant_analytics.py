"""
Quant-grade analytics module for backtesting.

Pure functions — no side effects, no file I/O, no external API calls.
Accepts trade list + equity curve, returns a flat dict for JSON serialization.

Provides:
- Statistical rigor: Wilson CI on win rates, Sharpe significance, sample adequacy
- Tail risk: VaR, CVaR, skewness, kurtosis, streak stats
- Strategy independence: signal correlation matrix
- Expectancy & Kelly: optimal bet sizing
- Regime-conditional metrics: per-regime Sharpe, Sortino, VaR, expectancy
- Monte Carlo robustness: trade shuffle test
"""

import math
import logging
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional

import numpy as np

logger = logging.getLogger("bot.backtest.quant_analytics")


# ── Statistical Rigor ───────────────────────────────────────────────────────


def wilson_score_ci(wins: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for win rate — superior to normal approx for small n.

    Returns (lower, upper) bounds of 95% confidence interval.
    """
    if total == 0:
        return (0.0, 0.0)
    p = wins / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) / total + z * z / (4 * total * total))) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def sharpe_significance(daily_returns: List[float]) -> float:
    """One-sided t-test: H0 is mean daily return <= 0. Returns p-value.

    Low p-value (<0.05) = statistically significant positive Sharpe.
    """
    if len(daily_returns) < 5:
        return 1.0  # Not enough data
    arr = np.array(daily_returns, dtype=float)
    mean_r = np.mean(arr)
    std_r = np.std(arr, ddof=1)
    if std_r < 1e-12:
        return 0.0 if mean_r > 0 else 1.0
    n = len(arr)
    t_stat = mean_r / (std_r / math.sqrt(n))
    # One-sided p-value using t-distribution approximation
    # For large n, t-dist ≈ normal; for small n, use proper t-dist
    try:
        from scipy import stats as sp_stats
        p_value = 1.0 - sp_stats.t.cdf(t_stat, df=n - 1)
    except ImportError:
        # Fallback: normal approximation
        from math import erfc
        p_value = 0.5 * erfc(t_stat / math.sqrt(2))
    return float(p_value)


def sample_adequacy(n: int) -> Dict[str, Any]:
    """Check if sample size is adequate for statistical inference."""
    return {
        "n": n,
        "adequate_for_clt": n >= 30,
        "adequate_for_ci": n >= 10,
        "adequate_for_regime_split": n >= 50,
        "verdict": "strong" if n >= 50 else "moderate" if n >= 30 else "weak" if n >= 10 else "insufficient",
    }


# ── Tail Risk ───────────────────────────────────────────────────────────────


def compute_var(returns: List[float], confidence: float = 0.95) -> float:
    """Historical Value-at-Risk: the loss at the (1-confidence) quantile.

    Returns a negative number representing worst expected loss.
    Example: VaR(95%) = -0.03 means 95% of days lose less than 3%.
    """
    if len(returns) < 5:
        return 0.0
    arr = np.array(returns, dtype=float)
    return float(np.percentile(arr, (1 - confidence) * 100))


def compute_cvar(returns: List[float], confidence: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall): average of losses below VaR.

    Always more extreme than VaR — captures tail severity.
    """
    if len(returns) < 5:
        return 0.0
    arr = np.array(returns, dtype=float)
    var = np.percentile(arr, (1 - confidence) * 100)
    tail = arr[arr <= var]
    return float(np.mean(tail)) if len(tail) > 0 else float(var)


def distribution_moments(returns: List[float]) -> Dict[str, float]:
    """Skewness and kurtosis of return distribution.

    Crypto: expect negative skew (crashes > rallies) and high kurtosis (fat tails).
    """
    if len(returns) < 10:
        return {"skewness": 0.0, "kurtosis": 0.0, "is_normal": True}
    arr = np.array(returns, dtype=float)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    if std < 1e-12:
        return {"skewness": 0.0, "kurtosis": 0.0, "is_normal": True}
    n = len(arr)
    # Excess kurtosis (normal = 0)
    skew = float(np.mean(((arr - mean) / std) ** 3))
    kurt = float(np.mean(((arr - mean) / std) ** 4) - 3.0)
    # Jarque-Bera test for normality
    jb = n / 6 * (skew ** 2 + kurt ** 2 / 4)
    # Chi-squared with 2 df: p < 0.05 means non-normal
    try:
        from scipy import stats as sp_stats
        jb_pvalue = float(1.0 - sp_stats.chi2.cdf(jb, 2))
    except ImportError:
        jb_pvalue = 0.0 if jb > 5.99 else 1.0  # 5.99 ≈ chi2(2, 0.05)
    return {
        "skewness": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "jarque_bera": round(jb, 2),
        "jb_pvalue": round(jb_pvalue, 4),
        "is_normal": jb_pvalue > 0.05,
    }


def streak_stats(outcomes: List[bool]) -> Dict[str, int]:
    """Max consecutive wins and losses."""
    if not outcomes:
        return {"max_consecutive_wins": 0, "max_consecutive_losses": 0,
                "current_streak": 0, "current_streak_type": "none"}
    max_wins = max_losses = cur_wins = cur_losses = 0
    for win in outcomes:
        if win:
            cur_wins += 1
            cur_losses = 0
            max_wins = max(max_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_losses = max(max_losses, cur_losses)
    return {
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "current_streak": cur_wins if cur_wins > 0 else -cur_losses,
        "current_streak_type": "win" if cur_wins > 0 else "loss" if cur_losses > 0 else "none",
    }


# ── Strategy Independence ───────────────────────────────────────────────────


def compute_strategy_correlation(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute correlation between strategy signals from trade data.

    Groups trades into 1h time buckets and builds binary fire matrix.
    Returns correlation matrix, redundant pairs, and independence count.
    """
    if len(trades) < 10:
        return {"matrix": {}, "independent_count": 0, "redundant_pairs": [], "total_strategies": 0}

    # Group trades by time bucket (1h) and strategy
    buckets = defaultdict(set)
    all_strategies = set()
    for t in trades:
        strategy = t.get("strategy", "unknown")
        all_strategies.add(strategy)
        # Use trade timestamp rounded to hour
        ts = str(t.get("timestamp", t.get("time", "")))[:13]  # YYYY-MM-DD HH
        if ts:
            buckets[ts].add(strategy)

    if not buckets or len(all_strategies) < 2:
        return {"matrix": {}, "independent_count": len(all_strategies),
                "redundant_pairs": [], "total_strategies": len(all_strategies)}

    strat_list = sorted(all_strategies)
    n_strats = len(strat_list)
    n_buckets = len(buckets)
    strat_idx = {s: i for i, s in enumerate(strat_list)}

    # Build binary matrix: rows = time buckets, cols = strategies
    matrix = np.zeros((n_buckets, n_strats), dtype=float)
    for row, (_, strategies) in enumerate(sorted(buckets.items())):
        for s in strategies:
            matrix[row, strat_idx[s]] = 1.0

    # Pearson correlation
    corr_matrix = {}
    redundant_pairs = []
    independent_count = 0

    if n_strats >= 2 and n_buckets >= 5:
        corr = np.corrcoef(matrix, rowvar=False)  # n_strats x n_strats
        for i, s1 in enumerate(strat_list):
            corr_matrix[s1] = {}
            for j, s2 in enumerate(strat_list):
                r = float(corr[i, j]) if not np.isnan(corr[i, j]) else 0.0
                corr_matrix[s1][s2] = round(r, 3)
                if i < j and abs(r) > 0.7:
                    redundant_pairs.append({"pair": [s1, s2], "correlation": round(r, 3)})

        # Count independent strategies (max |corr| < 0.3 to all others)
        for i, s in enumerate(strat_list):
            max_corr = max(abs(float(corr[i, j])) for j in range(n_strats)
                          if j != i and not np.isnan(corr[i, j]))
            if max_corr < 0.3:
                independent_count += 1
    else:
        independent_count = n_strats

    return {
        "matrix": corr_matrix,
        "independent_count": independent_count,
        "redundant_pairs": redundant_pairs,
        "total_strategies": n_strats,
    }


# ── Expectancy & Kelly ──────────────────────────────────────────────────────


def compute_expectancy(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Statistical expectancy per trade.

    E = WR × avg_win - (1-WR) × |avg_loss|
    Positive = profitable system.
    """
    return win_rate * avg_win - (1 - win_rate) * abs(avg_loss)


def compute_kelly(win_rate: float, payoff_ratio: float) -> float:
    """Kelly criterion — optimal fraction of bankroll to bet.

    f* = (b*p - q) / b  where b = payoff_ratio, p = win_rate, q = 1-p
    Clamped to [0, 1].
    """
    if payoff_ratio <= 0:
        return 0.0
    q = 1.0 - win_rate
    kelly = (payoff_ratio * win_rate - q) / payoff_ratio
    return max(0.0, min(1.0, kelly))


# ── Regime-Conditional & Per-Strategy Metrics ────────────────────────────────


def _group_metrics(trades: List[Dict], group_key: str) -> Dict[str, Dict[str, Any]]:
    """Compute per-group quant metrics (used for both regime and strategy grouping)."""
    groups = defaultdict(list)
    for t in trades:
        key = t.get(group_key, "unknown")
        groups[key].append(t)

    result = {}
    for name, group_trades in groups.items():
        if len(group_trades) < 3:
            result[name] = {"n": len(group_trades), "insufficient_data": True}
            continue

        pnls = [float(t.get("pnl", 0)) for t in group_trades]
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)
        wr = wins / total if total > 0 else 0
        avg_win = float(np.mean([p for p in pnls if p > 0])) if wins > 0 else 0
        avg_loss = float(np.mean([abs(p) for p in pnls if p <= 0])) if wins < total else 0
        payoff = avg_win / avg_loss if avg_loss > 0 else 999

        # Daily returns for Sharpe/Sortino
        daily_pnls = _aggregate_daily_returns(group_trades)

        wr_ci = wilson_score_ci(wins, total)
        exp = compute_expectancy(wr, avg_win, avg_loss)
        kelly = compute_kelly(wr, payoff)

        metrics = {
            "n": total,
            "win_rate": round(wr, 4),
            "win_rate_ci_95": [round(wr_ci[0], 4), round(wr_ci[1], 4)],
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff_ratio": round(payoff, 3),
            "expectancy": round(exp, 2),
            "kelly_fraction": round(kelly, 4),
            "half_kelly": round(kelly / 2, 4),
            "total_pnl": round(sum(pnls), 2),
        }

        if len(daily_pnls) >= 5:
            daily_rets = [p / 10000 for p in daily_pnls]  # Approximate % returns
            std = float(np.std(daily_rets, ddof=1)) if len(daily_rets) > 1 else 0
            mean = float(np.mean(daily_rets))
            metrics["sharpe"] = round(mean / std * math.sqrt(365) if std > 0 else 0, 3)
            downside = [r for r in daily_rets if r < 0]
            ds_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0
            metrics["sortino"] = round(mean / ds_std * math.sqrt(365) if ds_std > 0 else 0, 3)
            metrics["var_95"] = round(compute_var(daily_rets), 6)

        result[name] = metrics

    return result


def _aggregate_daily_returns(trades: List[Dict]) -> List[float]:
    """Aggregate trade PnL into daily buckets."""
    daily = defaultdict(float)
    for t in trades:
        ts = str(t.get("timestamp", t.get("time", "")))[:10]  # YYYY-MM-DD
        if ts:
            daily[ts] += float(t.get("pnl", 0))
    return list(daily.values())


# ── Monte Carlo Robustness ──────────────────────────────────────────────────


def monte_carlo_shuffle(trades: List[Dict], n_simulations: int = 1000,
                        starting_equity: float = 10000.0) -> Dict[str, Any]:
    """Randomly reorder trade PnL sequence and measure robustness.

    If >95% of shuffles are profitable, the edge is robust regardless
    of trade order. If <50%, it depends on lucky sequencing = fragile.
    """
    pnls = [float(t.get("pnl", 0)) for t in trades]
    if len(pnls) < 5:
        return {"n_simulations": 0, "insufficient_data": True}

    pnl_arr = np.array(pnls, dtype=float)
    rng = np.random.default_rng(42)  # Reproducible

    final_equities = []
    max_drawdowns = []

    for _ in range(n_simulations):
        shuffled = rng.permutation(pnl_arr)
        equity = starting_equity
        peak = equity
        max_dd = 0.0
        for p in shuffled:
            equity += p
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    final_arr = np.array(final_equities)
    dd_arr = np.array(max_drawdowns)

    return {
        "n_simulations": n_simulations,
        "p_profitable": round(float(np.mean(final_arr > starting_equity)), 4),
        "median_final_equity": round(float(np.median(final_arr)), 2),
        "p5_final_equity": round(float(np.percentile(final_arr, 5)), 2),
        "p95_final_equity": round(float(np.percentile(final_arr, 95)), 2),
        "median_max_drawdown": round(float(np.median(dd_arr)), 4),
        "dd_95th_percentile": round(float(np.percentile(dd_arr, 95)), 4),
        "verdict": (
            "robust" if float(np.mean(final_arr > starting_equity)) > 0.95
            else "strong" if float(np.mean(final_arr > starting_equity)) > 0.80
            else "moderate" if float(np.mean(final_arr > starting_equity)) > 0.60
            else "weak" if float(np.mean(final_arr > starting_equity)) > 0.40
            else "fragile"
        ),
    }


# ── Main Entry Point ────────────────────────────────────────────────────────


def compute_quant_metrics(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    starting_equity: float = 10000.0,
) -> Dict[str, Any]:
    """Compute all quant-grade metrics from backtest results.

    Args:
        trades: List of trade dicts with keys: pnl, strategy, regime, side,
                confidence, leverage, timestamp/time, outcome/win
        equity_curve: List of dicts with: time, equity, mtm_equity
        starting_equity: Starting capital

    Returns:
        Flat dict suitable for JSON serialization and report merging.
    """
    if not trades:
        return {"error": "no_trades", "total_trades": 0}

    # Extract basic stats
    pnls = [float(t.get("pnl", 0)) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = len(pnls) - wins
    total = len(pnls)
    wr = wins / total if total > 0 else 0

    avg_win = float(np.mean([p for p in pnls if p > 0])) if wins > 0 else 0
    avg_loss = float(np.mean([abs(p) for p in pnls if p <= 0])) if losses > 0 else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else 999

    outcomes = [p > 0 for p in pnls]

    # Daily returns from equity curve
    daily_returns = []
    if len(equity_curve) >= 2:
        prev_eq = None
        for pt in equity_curve:
            eq = float(pt.get("equity", pt.get("mtm_equity", starting_equity)))
            if prev_eq is not None and prev_eq > 0:
                daily_returns.append((eq - prev_eq) / prev_eq)
            prev_eq = eq

    result = {
        "total_trades": total,

        # ── Statistical Rigor ──
        "win_rate": round(wr, 4),
        "win_rate_ci_95": [round(x, 4) for x in wilson_score_ci(wins, total)],
        "sharpe_p_value": round(sharpe_significance(daily_returns), 4),
        "sharpe_significant": sharpe_significance(daily_returns) < 0.10,
        "sample_adequacy": sample_adequacy(total),

        # ── Expectancy & Kelly ──
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(payoff, 3),
        "expectancy_per_trade": round(compute_expectancy(wr, avg_win, avg_loss), 2),
        "kelly_fraction": round(compute_kelly(wr, payoff), 4),
        "half_kelly": round(compute_kelly(wr, payoff) / 2, 4),

        # ── Tail Risk ──
        "var_95_daily": round(compute_var(daily_returns), 6) if daily_returns else None,
        "cvar_95_daily": round(compute_cvar(daily_returns), 6) if daily_returns else None,
        "distribution": distribution_moments(daily_returns) if daily_returns else None,
        "streaks": streak_stats(outcomes),

        # ── Strategy Independence ──
        "strategy_correlation": compute_strategy_correlation(trades),

        # ── Regime-Conditional ──
        "by_regime": _group_metrics(trades, "regime"),

        # ── Per-Strategy ──
        "by_strategy": _group_metrics(trades, "strategy"),

        # ── Monte Carlo Robustness ──
        "monte_carlo": monte_carlo_shuffle(trades, n_simulations=1000,
                                           starting_equity=starting_equity),
    }

    return result
