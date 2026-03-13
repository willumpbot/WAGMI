"""
Statistical Power Analysis — Minimum sample size calculator.

No strategy should be re-enabled without meeting minimum sample size for
significance. This module computes required sample sizes and validates
whether current data is sufficient for reliable conclusions.

Usage:
    n = min_sample_for_significance(base_wr=0.50, delta=0.10)
    # n ≈ 392 trades needed to detect 10% WR improvement with 80% power
"""

import math
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("bot.validation.power_analysis")


def _norm_ppf(p: float) -> float:
    """Approximate inverse normal CDF (percent point function).

    Uses Abramowitz & Stegun approximation 26.2.23 — accurate to 4.5e-4.
    No scipy dependency required.
    """
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    if p == 0.5:
        return 0.0

    # Work with the upper tail
    if p > 0.5:
        t = math.sqrt(-2.0 * math.log(1 - p))
    else:
        t = math.sqrt(-2.0 * math.log(p))

    # Rational approximation
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)

    return result if p > 0.5 else -result


def min_sample_for_significance(
    base_wr: float = 0.50,
    delta: float = 0.10,
    power: float = 0.80,
    alpha: float = 0.05,
) -> int:
    """Compute minimum sample size to detect a win rate improvement.

    Uses two-proportion z-test power formula.

    Args:
        base_wr: Null hypothesis win rate (default 50% = coin flip)
        delta: Minimum detectable improvement in win rate
        power: Statistical power (1 - type II error rate)
        alpha: Significance level (type I error rate)

    Returns:
        Minimum number of trades needed per group.
    """
    z_alpha = _norm_ppf(1 - alpha / 2)
    z_beta = _norm_ppf(power)

    p = base_wr + delta / 2
    q = 1 - p

    n = ((z_alpha + z_beta) ** 2 * 2 * p * q) / (delta ** 2)
    return int(math.ceil(n))


def assess_sample_adequacy(
    n_trades: int,
    win_rate: float = 0.50,
    target_delta: float = 0.10,
) -> Dict[str, Any]:
    """Assess whether current sample size is sufficient.

    Returns:
        Dict with required_n, current_n, adequate (bool), power estimate,
        and confidence level in the observed win rate.
    """
    required_n = min_sample_for_significance(
        base_wr=0.50, delta=target_delta
    )

    # Estimate achieved power with current sample
    if n_trades > 0 and n_trades < required_n:
        # Approximate: power scales roughly with sqrt(n/required_n)
        achieved_power = min(0.99, 0.80 * math.sqrt(n_trades / required_n))
    elif n_trades >= required_n:
        achieved_power = 0.80
    else:
        achieved_power = 0.0

    # Wilson CI width on observed win rate
    if n_trades > 0:
        z = 1.96
        p = win_rate
        denom = 1 + z * z / n_trades
        spread = z * math.sqrt((p * (1 - p) / n_trades + z * z / (4 * n_trades * n_trades))) / denom
        ci_width = spread * 2
    else:
        ci_width = 1.0

    return {
        "current_n": n_trades,
        "required_n": required_n,
        "adequate": n_trades >= required_n,
        "achieved_power": round(achieved_power, 3),
        "win_rate_ci_width": round(ci_width, 4),
        "verdict": (
            "SUFFICIENT" if n_trades >= required_n
            else "APPROACHING" if n_trades >= required_n * 0.7
            else "INSUFFICIENT" if n_trades >= 10
            else "MINIMAL"
        ),
    }


def strategy_power_report(
    strategy_stats: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Generate power analysis report for all strategies.

    Args:
        strategy_stats: Dict of strategy_name -> {trades: int, win_rate: float}

    Returns:
        Dict of strategy_name -> power analysis results
    """
    report = {}
    for name, stats in strategy_stats.items():
        n = stats.get("trades", 0)
        wr = stats.get("win_rate", 0.5)
        report[name] = assess_sample_adequacy(n, wr)
        report[name]["strategy"] = name

    return report


def can_reactivate_strategy(
    strategy_name: str,
    shadow_trades: int,
    shadow_win_rate: float,
    shadow_avg_pnl: float,
    min_delta: float = 0.10,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Check if a disabled strategy has enough shadow data to justify reactivation.

    Args:
        strategy_name: Name of the disabled strategy
        shadow_trades: Number of shadow ledger trades
        shadow_win_rate: Win rate on shadow trades
        shadow_avg_pnl: Average PnL on shadow trades
        min_delta: Minimum WR improvement to detect
        alpha: Significance level

    Returns:
        Dict with recommendation, evidence strength, and rationale.
    """
    required_n = min_sample_for_significance(base_wr=0.50, delta=min_delta)
    adequacy = assess_sample_adequacy(shadow_trades, shadow_win_rate)

    # Binomial test: is WR significantly above 50%?
    if shadow_trades >= 10 and shadow_win_rate > 0.5:
        # Normal approximation to binomial
        z = (shadow_win_rate - 0.5) / math.sqrt(0.25 / shadow_trades)
        z_crit = _norm_ppf(1 - alpha)
        significant = z > z_crit
    else:
        significant = False

    can_reactivate = (
        shadow_trades >= required_n
        and significant
        and shadow_avg_pnl > 0
    )

    return {
        "strategy": strategy_name,
        "shadow_trades": shadow_trades,
        "shadow_win_rate": round(shadow_win_rate, 3),
        "shadow_avg_pnl": round(shadow_avg_pnl, 4),
        "required_trades": required_n,
        "statistically_significant": significant,
        "can_reactivate": can_reactivate,
        "adequacy": adequacy["verdict"],
        "recommendation": (
            f"REACTIVATE: {strategy_name} shows significant edge on {shadow_trades} shadow trades"
            if can_reactivate
            else f"WAIT: Need {required_n - shadow_trades} more shadow trades"
            if shadow_trades < required_n
            else f"REJECT: WR {shadow_win_rate:.1%} not significant or PnL negative"
        ),
    }
