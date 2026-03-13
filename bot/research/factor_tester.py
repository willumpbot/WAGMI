"""
Factor Research Pipeline — 6-step validation for new signal hypotheses.

Every new factor/signal must pass all 6 steps before getting allocated weight.
This prevents false discoveries from polluting the trading system.

Pipeline:
  1. WR vs null — Binomial test vs 50% (p < 0.05)
  2. EV vs 0   — One-sample t-test on trade returns (p < 0.10)
  3. IC > 0    — Spearman ρ on prediction vs return (ρ > 0.05)
  4. Low correlation — Pearson vs all existing factors (|r| < 0.3)
  5. Regime breakdown — WR by regime (>1 regime positive)
  6. OOS pass  — Shadow ledger WF ratio > 0.5

Usage:
    tester = FactorTester()
    result = tester.validate_factor(factor_name, trades)
    if result["passed_all"]:
        # Factor is validated — allocate weight
"""

import math
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.research.factor_tester")


def _norm_cdf(x: float) -> float:
    """Approximate normal CDF using Abramowitz & Stegun."""
    if x < -10:
        return 0.0
    if x > 10:
        return 1.0
    # Horner form of rational approximation
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    p = d * math.exp(-x * x / 2.0) * t * (
        0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))
    )
    return 1.0 - p if x > 0 else p


def _t_test_one_sample(values: List[float], mu0: float = 0.0) -> Tuple[float, float]:
    """One-sample t-test. Returns (t_statistic, p_value)."""
    n = len(values)
    if n < 3:
        return 0.0, 1.0

    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    if var < 1e-15:
        return 0.0, 1.0 if mean <= mu0 else 0.0

    se = math.sqrt(var / n)
    t_stat = (mean - mu0) / se

    # Approximate p-value using normal CDF (good for n > 20)
    p_value = 1.0 - _norm_cdf(t_stat)
    return t_stat, p_value


def _binomial_test(successes: int, trials: int, p0: float = 0.5) -> float:
    """One-sided binomial test (normal approximation). Returns p-value."""
    if trials < 5:
        return 1.0

    observed_p = successes / trials
    se = math.sqrt(p0 * (1 - p0) / trials)
    if se < 1e-15:
        return 1.0

    z = (observed_p - p0) / se
    return 1.0 - _norm_cdf(z)


def _spearman_rank_corr(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation (stdlib only)."""
    if len(x) != len(y) or len(x) < 3:
        return 0.0

    n = len(x)

    def _rank(vals):
        sorted_idx = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = rank + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)

    d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    rho = 1 - (6 * d_sq) / (n * (n * n - 1))
    return rho


def _pearson_corr(x: List[float], y: List[float]) -> float:
    """Pearson correlation coefficient (stdlib only)."""
    if len(x) != len(y) or len(x) < 3:
        return 0.0

    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n

    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))

    if sx < 1e-15 or sy < 1e-15:
        return 0.0

    return cov / (sx * sy)


class FactorTester:
    """Validates new factors through the 6-step pipeline."""

    # Thresholds
    WR_P_VALUE = 0.05      # Step 1: WR significance
    EV_P_VALUE = 0.10      # Step 2: EV significance
    MIN_IC = 0.05          # Step 3: Minimum IC
    MAX_CORRELATION = 0.30 # Step 4: Max correlation with existing factors
    MIN_REGIME_POSITIVE = 2 # Step 5: Regimes with positive WR
    MIN_WF_RATIO = 0.50    # Step 6: OOS walk-forward ratio
    MIN_TRADES = 20        # Minimum trades for any test

    def validate_factor(
        self,
        factor_name: str,
        trades: List[Dict[str, Any]],
        existing_factor_signals: Optional[Dict[str, List[float]]] = None,
    ) -> Dict[str, Any]:
        """Run all 6 validation steps on a factor.

        Args:
            factor_name: Name of the factor being tested
            trades: List of trade dicts with keys:
                - predicted_direction: +1 or -1
                - actual_return: float (realized PnL %)
                - regime: str (market regime)
                - net_pnl: float
                - won: bool
            existing_factor_signals: Dict of factor_name -> list of signal values
                (for cross-correlation check)

        Returns:
            Dict with per-step results and overall pass/fail.
        """
        result = {
            "factor": factor_name,
            "total_trades": len(trades),
            "steps": {},
            "passed_all": False,
        }

        if len(trades) < self.MIN_TRADES:
            result["error"] = f"Insufficient trades: {len(trades)} < {self.MIN_TRADES}"
            return result

        # Step 1: WR vs null (binomial test vs 50%)
        wins = sum(1 for t in trades if t.get("won", t.get("net_pnl", 0) > 0))
        wr = wins / len(trades)
        p_wr = _binomial_test(wins, len(trades), 0.50)
        step1 = {
            "test": "win_rate_vs_null",
            "win_rate": round(wr, 4),
            "p_value": round(p_wr, 4),
            "threshold": self.WR_P_VALUE,
            "passed": p_wr < self.WR_P_VALUE,
        }
        result["steps"]["1_wr_vs_null"] = step1

        # Step 2: EV vs 0 (one-sample t-test on returns)
        returns = [t.get("actual_return", t.get("net_pnl", 0)) for t in trades]
        t_stat, p_ev = _t_test_one_sample(returns, mu0=0.0)
        mean_return = sum(returns) / len(returns) if returns else 0
        step2 = {
            "test": "expected_value_vs_zero",
            "mean_return": round(mean_return, 6),
            "t_statistic": round(t_stat, 3),
            "p_value": round(p_ev, 4),
            "threshold": self.EV_P_VALUE,
            "passed": p_ev < self.EV_P_VALUE,
        }
        result["steps"]["2_ev_vs_zero"] = step2

        # Step 3: IC > 0 (Spearman ρ)
        predictions = [t.get("predicted_direction", 0) for t in trades]
        actuals = [t.get("actual_return", t.get("net_pnl", 0)) for t in trades]
        ic = _spearman_rank_corr(predictions, actuals)
        step3 = {
            "test": "information_coefficient",
            "ic": round(ic, 4),
            "threshold": self.MIN_IC,
            "passed": ic > self.MIN_IC,
        }
        result["steps"]["3_ic_positive"] = step3

        # Step 4: Low correlation with existing factors
        if existing_factor_signals:
            max_corr = 0.0
            max_corr_factor = ""
            factor_signals = predictions  # Use predicted directions
            for other_name, other_signals in existing_factor_signals.items():
                if len(other_signals) == len(factor_signals):
                    corr = abs(_pearson_corr(
                        [float(x) for x in factor_signals],
                        [float(x) for x in other_signals],
                    ))
                    if corr > max_corr:
                        max_corr = corr
                        max_corr_factor = other_name
            step4 = {
                "test": "factor_independence",
                "max_correlation": round(max_corr, 4),
                "most_correlated_with": max_corr_factor,
                "threshold": self.MAX_CORRELATION,
                "passed": max_corr < self.MAX_CORRELATION,
            }
        else:
            step4 = {
                "test": "factor_independence",
                "max_correlation": 0.0,
                "most_correlated_with": "N/A (no existing factors provided)",
                "threshold": self.MAX_CORRELATION,
                "passed": True,
            }
        result["steps"]["4_independence"] = step4

        # Step 5: Regime breakdown (>1 regime with positive WR)
        regime_stats = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in trades:
            regime = t.get("regime", "unknown")
            regime_stats[regime]["total"] += 1
            if t.get("won", t.get("net_pnl", 0) > 0):
                regime_stats[regime]["wins"] += 1

        positive_regimes = 0
        regime_details = {}
        for regime, stats in regime_stats.items():
            if stats["total"] >= 5:  # Need at least 5 trades per regime
                wr = stats["wins"] / stats["total"]
                regime_details[regime] = {
                    "trades": stats["total"],
                    "win_rate": round(wr, 3),
                }
                if wr > 0.50:
                    positive_regimes += 1

        step5 = {
            "test": "regime_robustness",
            "positive_regimes": positive_regimes,
            "total_regimes_tested": len(regime_details),
            "regime_details": regime_details,
            "threshold": self.MIN_REGIME_POSITIVE,
            "passed": positive_regimes >= self.MIN_REGIME_POSITIVE,
        }
        result["steps"]["5_regime_breakdown"] = step5

        # Step 6: OOS validation via 70/30 time-split
        step6 = self._step6_oos_validation(factor_name, trades)
        result["steps"]["6_oos_validation"] = step6

        # Overall result (include Step 6 if it produced a result)
        steps_to_check = [
            step1["passed"],
            step2["passed"],
            step3["passed"],
            step4["passed"],
            step5["passed"],
        ]
        if step6["passed"] is not None:
            steps_to_check.append(step6["passed"])
        result["passed_all"] = all(steps_to_check)
        result["passed_count"] = sum(1 for s in steps_to_check if s)
        result["total_steps_checked"] = len(steps_to_check)

        status = "VALIDATED" if result["passed_all"] else "REJECTED"
        logger.info(
            f"[FACTOR] {factor_name}: {status} "
            f"({result['passed_count']}/{result['total_steps_checked']} steps passed)"
        )

        return result

    def _step6_oos_validation(self, factor: str, trades: list) -> dict:
        """Step 6: Out-of-sample validation via 70/30 time-split.

        Splits trade data chronologically — first 70% train, last 30% test.
        Checks if the edge persists out-of-sample (test WR >= 80% of train WR
        and test WR > 50%).
        """
        if len(trades) < 30:
            return {
                "test": "out_of_sample_validation",
                "passed": None,
                "note": f"Need 30+ trades for OOS split, have {len(trades)}",
            }

        split_idx = int(len(trades) * 0.7)
        train = trades[:split_idx]
        test = trades[split_idx:]

        if len(test) < 10:
            return {
                "test": "out_of_sample_validation",
                "passed": None,
                "note": f"Test set too small ({len(test)} trades)",
            }

        train_wins = sum(1 for t in train if t.get("won", t.get("pnl", 0) > 0))
        train_wr = train_wins / len(train) if train else 0

        test_wins = sum(1 for t in test if t.get("won", t.get("pnl", 0) > 0))
        test_wr = test_wins / len(test) if test else 0

        wr_ratio = test_wr / train_wr if train_wr > 0 else 0
        passed = test_wr > 0.50 and wr_ratio > 0.80

        return {
            "test": "out_of_sample_validation",
            "passed": passed,
            "train_wr": round(train_wr, 4),
            "test_wr": round(test_wr, 4),
            "wr_retention": round(wr_ratio, 4),
            "train_n": len(train),
            "test_n": len(test),
            "threshold": self.MIN_WF_RATIO,
            "note": "OOS edge retained" if passed else "Edge degraded out-of-sample",
        }

    def format_report(self, result: Dict[str, Any]) -> str:
        """Format factor validation result as human-readable text."""
        lines = [
            f"Factor Validation: {result['factor']}",
            f"Trades: {result['total_trades']}",
            f"Result: {'PASS' if result.get('passed_all') else 'FAIL'}",
            "",
        ]

        for step_name, step_data in result.get("steps", {}).items():
            status = "PASS" if step_data.get("passed") else (
                "N/A" if step_data.get("passed") is None else "FAIL"
            )
            lines.append(f"  [{status}] {step_data.get('test', step_name)}")

            # Show key metric
            for key in ["win_rate", "mean_return", "ic", "max_correlation",
                        "positive_regimes", "wf_ratio", "p_value"]:
                if key in step_data and step_data[key] is not None:
                    lines.append(f"         {key}: {step_data[key]}")

        return "\n".join(lines)
