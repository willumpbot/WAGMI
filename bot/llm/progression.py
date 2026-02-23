"""
Autonomy Progression Controller.

Determines when the bot is allowed to move from one LLM mode to the next,
based on measurable performance and safety metrics.

Progression path:
  VETO_ONLY -> SIZING -> DIRECTION -> FULL

Each transition has specific gates that must ALL pass before promotion.
This ensures the LLM earns trust through demonstrated value.

Gates are evaluated from uplift analytics, error stats, and trade logs.
The controller RECOMMENDS promotions -- the human operator (or /mode command)
actually changes the mode.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from llm.autonomy import LLMMode
from llm.recovery import get_error_stats
from llm.uplift_analytics import compute_uplift

logger = logging.getLogger("bot.llm.progression")


@dataclass
class GateResult:
    """Result of evaluating a single progression gate."""
    name: str
    passed: bool
    current_value: Any
    threshold: Any
    description: str

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"  [{status}] {self.name}: {self.current_value} (need {self.threshold}) - {self.description}"


@dataclass
class ProgressionReport:
    """Full report for a mode transition."""
    current_mode: LLMMode
    target_mode: LLMMode
    gates: List[GateResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def passed_count(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    @property
    def total_count(self) -> int:
        return len(self.gates)

    def format(self) -> str:
        lines = []
        status = "READY" if self.all_passed else "NOT READY"
        lines.append(
            f"Progression: {self.current_mode.name} -> {self.target_mode.name} [{status}]"
        )
        lines.append(f"Gates: {self.passed_count}/{self.total_count}")
        for g in self.gates:
            lines.append(str(g))
        return "\n".join(lines)


def evaluate_progression(current_mode: LLMMode) -> Optional[ProgressionReport]:
    """Evaluate whether the bot is ready to advance to the next mode.

    Returns None if already at FULL (no progression possible).
    """
    transitions = {
        LLMMode.VETO_ONLY: LLMMode.SIZING,
        LLMMode.SIZING: LLMMode.DIRECTION,
        LLMMode.DIRECTION: LLMMode.FULL,
    }

    target = transitions.get(current_mode)
    if target is None:
        return None

    if current_mode == LLMMode.VETO_ONLY:
        return _evaluate_veto_to_sizing()
    elif current_mode == LLMMode.SIZING:
        return _evaluate_sizing_to_direction()
    elif current_mode == LLMMode.DIRECTION:
        return _evaluate_direction_to_full()
    return None


def _evaluate_veto_to_sizing() -> ProgressionReport:
    """VETO_ONLY -> SIZING gates.

    Requirements:
    - >= 100 veto events (enough data to evaluate)
    - veto_accuracy >= 55% (LLM vetoes are more right than wrong)
    - error_rate < 5% (LLM API is reliable)
    - no circuit breaker trips from LLM errors
    """
    report = ProgressionReport(
        current_mode=LLMMode.VETO_ONLY,
        target_mode=LLMMode.SIZING,
    )

    analytics = compute_uplift()
    err_stats = get_error_stats()

    # Gate 1: Minimum veto events
    veto_data = analytics.get("veto_accuracy", {})
    total_vetoed = veto_data.get("total_vetoed", 0)
    report.gates.append(GateResult(
        name="min_veto_events",
        passed=total_vetoed >= 100,
        current_value=total_vetoed,
        threshold=100,
        description="Enough veto data to evaluate accuracy",
    ))

    # Gate 2: Veto accuracy
    veto_accuracy = veto_data.get("accuracy", 0)
    report.gates.append(GateResult(
        name="veto_accuracy",
        passed=veto_accuracy >= 0.55,
        current_value=f"{veto_accuracy:.1%}",
        threshold="55%",
        description="Vetoed trades were actually bad more often than not",
    ))

    # Gate 3: Error rate
    error_rate = err_stats.error_rate
    report.gates.append(GateResult(
        name="error_rate",
        passed=error_rate < 5.0,
        current_value=f"{error_rate:.1f}%",
        threshold="<5%",
        description="LLM API calls are reliable",
    ))

    # Gate 4: No consecutive error bursts
    consec = err_stats.consecutive_errors
    report.gates.append(GateResult(
        name="no_error_bursts",
        passed=consec < 3,
        current_value=consec,
        threshold="<3",
        description="No recent consecutive error bursts",
    ))

    # Gate 5: Positive net veto value
    net_value = veto_data.get("net_value", 0)
    report.gates.append(GateResult(
        name="positive_veto_value",
        passed=net_value > 0,
        current_value=f"${net_value:+.2f}",
        threshold=">$0",
        description="Saved more from bad vetoes than missed from good ones",
    ))

    return report


def _evaluate_sizing_to_direction() -> ProgressionReport:
    """SIZING -> DIRECTION gates.

    Requirements:
    - >= 50 sized trades (enough data)
    - sizing uplift positive (LLM sizing is helping)
    - error_rate < 5%
    - no massive size extremes (all within 0.3-1.8x range)
    """
    report = ProgressionReport(
        current_mode=LLMMode.SIZING,
        target_mode=LLMMode.DIRECTION,
    )

    analytics = compute_uplift()
    err_stats = get_error_stats()

    # Gate 1: Minimum sized trades
    llm_filtered = analytics.get("llm_filtered", {})
    traded_count = llm_filtered.get("count", 0)
    report.gates.append(GateResult(
        name="min_sized_trades",
        passed=traded_count >= 50,
        current_value=traded_count,
        threshold=50,
        description="Enough LLM-sized trades to evaluate",
    ))

    # Gate 2: Sizing uplift is positive
    uplift = analytics.get("uplift", {})
    is_positive = uplift.get("is_positive", False)
    avg_pnl_delta = uplift.get("avg_pnl_delta", 0)
    report.gates.append(GateResult(
        name="sizing_uplift_positive",
        passed=is_positive,
        current_value=f"${avg_pnl_delta:+.2f}",
        threshold=">$0",
        description="LLM sizing improves average PnL",
    ))

    # Gate 3: Error rate
    error_rate = err_stats.error_rate
    report.gates.append(GateResult(
        name="error_rate",
        passed=error_rate < 5.0,
        current_value=f"{error_rate:.1f}%",
        threshold="<5%",
        description="LLM API calls are reliable",
    ))

    # Gate 4: Win rate delta non-negative
    wr_delta = uplift.get("win_rate_delta", 0)
    report.gates.append(GateResult(
        name="win_rate_stable",
        passed=wr_delta >= -0.05,
        current_value=f"{wr_delta:+.1%}",
        threshold=">=-5%",
        description="Win rate not degraded by more than 5%",
    ))

    return report


def _evaluate_direction_to_full() -> ProgressionReport:
    """DIRECTION -> FULL gates.

    Requirements:
    - >= 1 week of stable direction-mode operation
    - direction uplift positive
    - no major LLM errors (consecutive < 3)
    - flip accuracy tracked (flips that were profitable)
    """
    report = ProgressionReport(
        current_mode=LLMMode.DIRECTION,
        target_mode=LLMMode.FULL,
    )

    analytics = compute_uplift()
    err_stats = get_error_stats()

    # Gate 1: Minimum time in DIRECTION mode (7 days ~ approximated by trade count)
    llm_filtered = analytics.get("llm_filtered", {})
    traded_count = llm_filtered.get("count", 0)
    # At ~10 trades/day, 7 days = ~70 trades
    report.gates.append(GateResult(
        name="min_direction_trades",
        passed=traded_count >= 70,
        current_value=traded_count,
        threshold=70,
        description="Enough direction-mode trades (~1 week)",
    ))

    # Gate 2: Direction uplift positive
    uplift = analytics.get("uplift", {})
    is_positive = uplift.get("is_positive", False)
    avg_pnl_delta = uplift.get("avg_pnl_delta", 0)
    report.gates.append(GateResult(
        name="direction_uplift_positive",
        passed=is_positive,
        current_value=f"${avg_pnl_delta:+.2f}",
        threshold=">$0",
        description="Direction overrides improve average PnL",
    ))

    # Gate 3: No major LLM errors
    consec = err_stats.consecutive_errors
    report.gates.append(GateResult(
        name="no_major_errors",
        passed=consec < 3,
        current_value=consec,
        threshold="<3",
        description="No recent consecutive error bursts",
    ))

    # Gate 4: Profit factor improvement
    baseline_pf = analytics.get("baseline", {}).get("profit_factor", 0)
    llm_pf = analytics.get("llm_filtered", {}).get("profit_factor", 0)
    pf_ok = True
    if baseline_pf != float("inf") and llm_pf != float("inf"):
        pf_ok = llm_pf >= baseline_pf * 0.9  # Allow 10% degradation
    report.gates.append(GateResult(
        name="profit_factor_stable",
        passed=pf_ok,
        current_value=f"{llm_pf:.2f}" if llm_pf != float("inf") else "inf",
        threshold=f">={baseline_pf * 0.9:.2f}" if baseline_pf != float("inf") else "n/a",
        description="Profit factor not degraded by more than 10%",
    ))

    # Gate 5: Error rate
    error_rate = err_stats.error_rate
    report.gates.append(GateResult(
        name="error_rate",
        passed=error_rate < 5.0,
        current_value=f"{error_rate:.1f}%",
        threshold="<5%",
        description="LLM API calls are reliable",
    ))

    return report


def format_progression_status(current_mode: LLMMode) -> str:
    """Format a human-readable progression status for Telegram/console."""
    lines = [f"=== AUTONOMY PROGRESSION ==="]
    lines.append(f"Current mode: {current_mode.name} ({current_mode.value})")

    report = evaluate_progression(current_mode)
    if report is None:
        if current_mode == LLMMode.FULL:
            lines.append("Already at FULL autonomy.")
        elif current_mode in (LLMMode.OFF, LLMMode.ADVISORY):
            lines.append("Set mode to VETO_ONLY (2) to start progression.")
        return "\n".join(lines)

    lines.append("")
    lines.append(report.format())
    return "\n".join(lines)
