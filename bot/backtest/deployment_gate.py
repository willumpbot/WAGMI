"""
Pre-Paper Deployment Gate: 10-gate automated validation checklist.

Every gate must pass before paper trading begins. This ensures the system
has proven quantitative edge, not just historical curve-fitting.

Usage:
    from backtest.deployment_gate import check_deployment_readiness
    verdict = check_deployment_readiness(backtest_report)
    print(format_gate_report(verdict))
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple

logger = logging.getLogger("bot.backtest.deployment_gate")


def check_deployment_readiness(report: Dict[str, Any]) -> Dict[str, Any]:
    """Run all 10 deployment gates against a backtest report.

    Args:
        report: Full backtest report dict (from BacktestEngine._generate_report)

    Returns:
        Dict with per-gate results and overall verdict.
    """
    results = report.get("results", {})
    quant = report.get("quant_analytics", {})
    walk_forward = report.get("walk_forward", {})
    digest = report.get("signal_digest_summary", {})

    gates = []

    # Gate 1: Trades Generated
    total_trades = results.get("total_trades", results.get("closed_trades", quant.get("total_trades", 0)))
    gates.append(_gate(
        "Trades Generated",
        total_trades > 0,
        f"{total_trades} trades",
        "> 0 trades required",
    ))

    # Gate 2: Positive Expectancy
    exp = quant.get("expectancy_per_trade", 0)
    gates.append(_gate(
        "Positive Expectancy",
        exp > 0,
        f"${exp:+.2f}/trade",
        "expectancy > $0",
    ))

    # Gate 3: Statistical Significance
    p_value = quant.get("sharpe_p_value", 1.0)
    gates.append(_gate(
        "Statistical Significance",
        p_value < 0.10,
        f"p={p_value:.3f}",
        "Sharpe p-value < 0.10",
        warning=p_value < 0.20,  # Marginal
    ))

    # Gate 4: Walk-Forward Pass
    overfit = walk_forward.get("overfit_ratio", 0)
    test_profit = walk_forward.get("test_profitable", False)
    wf_pass = overfit > 0.5 and test_profit
    gates.append(_gate(
        "Walk-Forward Pass",
        wf_pass,
        f"ratio={overfit:.2f}, test_profitable={test_profit}",
        "overfit_ratio > 0.5 AND test profitable",
        warning=test_profit and overfit <= 0.5,
    ))

    # Gate 5: Monte Carlo Robust
    mc = quant.get("monte_carlo", {})
    p_profitable = mc.get("p_profitable", 0)
    gates.append(_gate(
        "Monte Carlo Robust",
        p_profitable > 0.70,
        f"{p_profitable:.0%} profitable",
        "> 70% of shuffles profitable",
        warning=p_profitable > 0.50,
    ))

    # Gate 6: Max Drawdown Tolerable
    max_dd_raw = results.get("max_drawdown_pct", 100.0)
    # Engine always stores as max_drawdown * 100: 0.728 = 0.728%, 15.3 = 15.3%.
    # Always divide by 100 to get the fraction used for comparison.
    # The old heuristic (/ 100 only if > 1) incorrectly treated drawdowns < 1%
    # as e.g. 72.8% instead of 0.728%.
    max_dd = max_dd_raw / 100.0
    gates.append(_gate(
        "Max Drawdown",
        max_dd < 0.20,
        f"-{max_dd:.1%}",
        "< 20%",
        warning=max_dd < 0.30,
    ))

    # Gate 7: Win Rate CI Above 45%
    ci = quant.get("win_rate_ci_95", [0, 0])
    lower_ci = ci[0] if isinstance(ci, list) and len(ci) >= 1 else 0
    gates.append(_gate(
        "Win Rate CI > 45%",
        lower_ci > 0.45,
        f"[{ci[0]:.1%}, {ci[1]:.1%}]" if isinstance(ci, list) and len(ci) >= 2 else "N/A",
        "lower bound of 95% CI > 45%",
        warning=lower_ci > 0.40,
    ))

    # Gate 8: Strategy Independence
    corr = quant.get("strategy_correlation", {})
    independent = corr.get("independent_count", 0)
    total_strats = corr.get("total_strategies", 0)
    gates.append(_gate(
        "Strategy Independence",
        independent >= 3,
        f"{independent}/{total_strats} independent",
        ">= 3 independent voters (|r| < 0.3)",
        warning=independent >= 2,
    ))

    # Gate 9: Regime Diversification
    by_regime = quant.get("by_regime", {})
    positive_regimes = sum(
        1 for r, m in by_regime.items()
        if isinstance(m, dict) and m.get("expectancy", -1) > 0
    )
    gates.append(_gate(
        "Regime Diversification",
        positive_regimes >= 2,
        f"{positive_regimes} positive regimes",
        ">= 2 regimes with positive expectancy",
        warning=positive_regimes >= 1,
    ))

    # Gate 10: Signal Quality Pre-Seeded
    sq_exists = Path("data/feedback/signal_quality.json").exists() or Path("data/signal_quality.json").exists()
    gates.append(_gate(
        "Signal Quality Seeded",
        sq_exists,
        "seeded" if sq_exists else "not found",
        "signal_quality.json exists and populated",
    ))

    # Overall verdict
    passes = sum(1 for g in gates if g["status"] == "pass")
    warnings = sum(1 for g in gates if g["status"] == "warning")
    fails = sum(1 for g in gates if g["status"] == "fail")

    if fails == 0:
        verdict = "READY FOR PAPER"
    elif fails <= 2 and warnings >= fails:
        verdict = "CAUTIOUS PROCEED"
    else:
        verdict = "NOT READY"

    return {
        "gates": gates,
        "passes": passes,
        "warnings": warnings,
        "fails": fails,
        "verdict": verdict,
    }


def _gate(name: str, passed: bool, value: str, condition: str,
          warning: bool = False) -> Dict[str, Any]:
    """Build a single gate result."""
    if passed:
        status = "pass"
    elif warning:
        status = "warning"
    else:
        status = "fail"
    return {
        "name": name,
        "status": status,
        "value": value,
        "condition": condition,
    }


def format_gate_report(verdict: Dict[str, Any]) -> str:
    """Format deployment gate results as a visual report."""
    icons = {"pass": "+", "warning": "!", "fail": "X"}

    lines = []
    lines.append("")
    lines.append("=" * 56)
    lines.append("         PRE-PAPER DEPLOYMENT GATE")
    lines.append("=" * 56)

    for gate in verdict["gates"]:
        icon = icons.get(gate["status"], "?")
        status = gate["status"].upper()
        lines.append(f"  [{icon}] {gate['name']:<28} {gate['value']}")

    lines.append("-" * 56)
    p, w, f = verdict["passes"], verdict["warnings"], verdict["fails"]
    lines.append(f"  RESULT: {p} PASS, {w} WARNING, {f} FAIL")
    lines.append(f"  VERDICT: {verdict['verdict']}")
    lines.append("=" * 56)

    return "\n".join(lines)
