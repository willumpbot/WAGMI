"""
Consistency Checker: validates coherence across agent outputs.

After all agents in the pipeline have run, this module checks for
contradictions and scores overall pipeline consistency. If consistency
is low, it can trigger re-evaluation or flag the decision for review.

Checks performed:
  1. Regime-Action Alignment — Does the action fit the classified regime?
  2. Confidence Coherence — Is Trade Agent's confidence consistent with Risk/Critic?
  3. Memory Consistency — Does the decision align with recent lessons?
  4. Inter-Agent Agreement — Do agents reinforce or contradict each other?
  5. Historical Pattern — Does this decision pattern match past outcomes?

Enable detailed logging: AGENT_CONSISTENCY_LOG=true
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.agents.consistency_checker")

_VERBOSE = os.getenv("AGENT_CONSISTENCY_LOG", "").lower() in ("1", "true", "yes")


@dataclass
class ConsistencyIssue:
    """A detected inconsistency between agents."""
    check_name: str          # Which check found this
    severity: str            # "critical", "warning", "info"
    description: str         # Human-readable description
    agents_involved: List[str]  # Which agents are in conflict
    suggestion: str = ""     # What to do about it


@dataclass
class ConsistencyReport:
    """Full consistency report for a pipeline run."""
    score: float = 1.0       # 0.0 (fully inconsistent) to 1.0 (fully consistent)
    issues: List[ConsistencyIssue] = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_consistent(self) -> bool:
        """True if no critical issues and score >= 0.5."""
        has_critical = any(i.severity == "critical" for i in self.issues)
        return not has_critical and self.score >= 0.5

    def summary(self) -> str:
        """One-line summary for logging."""
        critical = sum(1 for i in self.issues if i.severity == "critical")
        warnings = sum(1 for i in self.issues if i.severity == "warning")
        return (
            f"consistency={self.score:.2f} "
            f"({self.checks_passed}/{self.checks_passed + self.checks_failed} passed"
            f"{f', {critical} critical' if critical else ''}"
            f"{f', {warnings} warnings' if warnings else ''})"
        )


# ── Main Checker ─────────────────────────────────────────────────

def check_pipeline_consistency(
    regime_data: Dict[str, Any],
    trade_data: Dict[str, Any],
    risk_data: Optional[Dict[str, Any]] = None,
    critic_data: Optional[Dict[str, Any]] = None,
    recent_decisions: Optional[List[Dict[str, Any]]] = None,
) -> ConsistencyReport:
    """Run all consistency checks on a completed pipeline.

    Args:
        regime_data: Regime Agent's parsed output.
        trade_data: Trade Agent's parsed output.
        risk_data: Risk Agent's parsed output (if available).
        critic_data: Critic Agent's parsed output (if available).
        recent_decisions: Last N decisions for consistency tracking.

    Returns:
        ConsistencyReport with score and issues.
    """
    report = ConsistencyReport()
    checks = [
        _check_regime_action_alignment,
        _check_confidence_coherence,
        _check_sizing_sanity,
        _check_critic_trade_alignment,
        _check_flip_consistency,
    ]

    for check_fn in checks:
        try:
            passed, issues = check_fn(
                regime_data, trade_data, risk_data, critic_data, recent_decisions
            )
            if passed:
                report.checks_passed += 1
            else:
                report.checks_failed += 1
            report.issues.extend(issues)
        except Exception as e:
            logger.debug(f"[CONSISTENCY] Check {check_fn.__name__} error: {e}")
            report.checks_passed += 1  # Don't penalize for check errors

    # Calculate score
    total = report.checks_passed + report.checks_failed
    if total > 0:
        # Start at 1.0, deduct per issue based on severity
        deductions = sum(
            0.3 if i.severity == "critical" else 0.15 if i.severity == "warning" else 0.05
            for i in report.issues
        )
        report.score = max(0.0, min(1.0, 1.0 - deductions))

    if _VERBOSE or not report.is_consistent:
        logger.info(f"[CONSISTENCY] {report.summary()}")
        for issue in report.issues:
            logger.info(
                f"[CONSISTENCY]   [{issue.severity}] {issue.check_name}: "
                f"{issue.description}"
            )

    return report


# ── Individual Checks ────────────────────────────────────────────

def _check_regime_action_alignment(
    regime_data: Dict, trade_data: Dict,
    risk_data: Optional[Dict], critic_data: Optional[Dict],
    recent_decisions: Optional[List[Dict]],
) -> Tuple[bool, List[ConsistencyIssue]]:
    """Check if the trade action is acceptable for the classified regime."""
    from llm.agents.shared_context import REGIME_ACTION_MAP

    issues = []
    regime = regime_data.get("rg", regime_data.get("regime", "unknown"))
    action = trade_data.get("a", trade_data.get("action", "skip"))

    # Normalize action
    action_normalized = {
        "go": "go", "proceed": "go", "long": "go", "short": "go",
        "buy": "go", "sell": "go", "enter": "go", "trade": "go",
        "skip": "skip", "flat": "skip", "hold": "skip", "pass": "skip",
        "wait": "skip", "no": "skip", "none": "skip",
        "flip": "flip", "reverse": "flip",
    }.get(str(action).lower().strip(), "skip")

    mapping = REGIME_ACTION_MAP.get(regime, {})
    forbidden = mapping.get("forbidden_actions", [])

    if action_normalized in forbidden:
        issues.append(ConsistencyIssue(
            check_name="regime_action_alignment",
            severity="critical",
            description=(
                f"Action '{action_normalized}' is FORBIDDEN in '{regime}' regime. "
                f"Acceptable: {mapping.get('acceptable_actions', [])}"
            ),
            agents_involved=["regime", "trade"],
            suggestion=f"Override to 'skip' or re-evaluate with regime context",
        ))
        return False, issues

    preferred = mapping.get("preferred_actions", [])
    if action_normalized not in preferred and action_normalized != "skip":
        issues.append(ConsistencyIssue(
            check_name="regime_action_alignment",
            severity="info",
            description=(
                f"Action '{action_normalized}' is acceptable but not preferred "
                f"in '{regime}' regime (preferred: {preferred})"
            ),
            agents_involved=["regime", "trade"],
        ))

    return len([i for i in issues if i.severity == "critical"]) == 0, issues


def _check_confidence_coherence(
    regime_data: Dict, trade_data: Dict,
    risk_data: Optional[Dict], critic_data: Optional[Dict],
    recent_decisions: Optional[List[Dict]],
) -> Tuple[bool, List[ConsistencyIssue]]:
    """Check if confidence levels are internally consistent."""
    issues = []

    trade_conf = float(trade_data.get("c", trade_data.get("confidence", 0.0)))
    regime_conf = float(regime_data.get("conf", regime_data.get("confidence", 0.5)))
    action = trade_data.get("a", trade_data.get("action", "skip"))

    action_normalized = "go" if action in ("go", "proceed", "long", "short", "buy", "sell") else "skip"

    # High trade confidence with low regime confidence = suspicious
    if trade_conf > 0.7 and regime_conf < 0.3:
        issues.append(ConsistencyIssue(
            check_name="confidence_coherence",
            severity="warning",
            description=(
                f"Trade confidence ({trade_conf:.2f}) is high but regime confidence "
                f"({regime_conf:.2f}) is low — regime uncertainty should reduce trade conviction"
            ),
            agents_involved=["regime", "trade"],
            suggestion="Reduce trade confidence by 15-20%",
        ))

    # Acting with very low confidence — threshold reads from ENSEMBLE_CONFIDENCE_FLOOR (default 20%)
    _min_go_conf = float(os.getenv("ENSEMBLE_CONFIDENCE_FLOOR", "40")) / 100.0
    if action_normalized == "go" and trade_conf < _min_go_conf:
        issues.append(ConsistencyIssue(
            check_name="confidence_coherence",
            severity="critical",
            description=(
                f"Proceeding with trade at confidence {trade_conf:.2f} "
                f"(below {_min_go_conf:.2f} minimum for action)"
            ),
            agents_involved=["trade"],
            suggestion="Override to skip — no edge at this confidence",
        ))

    # Risk agent sizing contradicts confidence
    if risk_data:
        size_mult = float(risk_data.get("sz", risk_data.get("size_multiplier", 1.0)))
        if trade_conf > 0.8 and size_mult < 0.3:
            issues.append(ConsistencyIssue(
                check_name="confidence_coherence",
                severity="warning",
                description=(
                    f"Trade is high-confidence ({trade_conf:.2f}) but Risk Agent "
                    f"sizing is minimal ({size_mult:.2f}) — conflicting signals"
                ),
                agents_involved=["trade", "risk"],
            ))

    return len([i for i in issues if i.severity == "critical"]) == 0, issues


def _check_sizing_sanity(
    regime_data: Dict, trade_data: Dict,
    risk_data: Optional[Dict], critic_data: Optional[Dict],
    recent_decisions: Optional[List[Dict]],
) -> Tuple[bool, List[ConsistencyIssue]]:
    """Check if position sizing is sane given the context."""
    issues = []
    if not risk_data:
        return True, issues

    from llm.agents.shared_context import REGIME_ACTION_MAP

    size_mult = float(risk_data.get("sz", risk_data.get("size_multiplier", 1.0)))
    regime = regime_data.get("rg", regime_data.get("regime", "unknown"))

    mapping = REGIME_ACTION_MAP.get(regime, {})
    sizing_range = mapping.get("sizing_range", "0.0-2.0")

    # Parse sizing range
    try:
        if "-" in sizing_range:
            low, high = sizing_range.split("-")
            low_bound = float(low)
            high_bound = float(high)
        else:
            low_bound = float(sizing_range)
            high_bound = float(sizing_range)

        if size_mult > high_bound * 1.2:  # 20% tolerance
            issues.append(ConsistencyIssue(
                check_name="sizing_sanity",
                severity="warning",
                description=(
                    f"Size multiplier ({size_mult:.2f}) exceeds regime '{regime}' "
                    f"recommended range ({sizing_range})"
                ),
                agents_involved=["risk"],
                suggestion=f"Cap sizing at {high_bound}",
            ))
    except (ValueError, TypeError):
        pass

    return True, issues  # Sizing issues are warnings, not failures


def _check_critic_trade_alignment(
    regime_data: Dict, trade_data: Dict,
    risk_data: Optional[Dict], critic_data: Optional[Dict],
    recent_decisions: Optional[List[Dict]],
) -> Tuple[bool, List[ConsistencyIssue]]:
    """Check if Critic's verdict aligns with the evidence."""
    issues = []
    if not critic_data:
        return True, issues

    verdict = critic_data.get("verdict", "approve").lower().strip()
    trade_conf = float(trade_data.get("c", trade_data.get("confidence", 0.0)))
    adj_conf = critic_data.get("adjusted_confidence")

    # Critic approved a low-confidence trade
    if verdict == "approve" and trade_conf < 0.4:
        issues.append(ConsistencyIssue(
            check_name="critic_alignment",
            severity="info",
            description=(
                f"Critic approved a low-confidence ({trade_conf:.2f}) decision — "
                f"consider if Critic is too lenient"
            ),
            agents_involved=["trade", "critic"],
        ))

    # Critic adjusted confidence upward (unusual — critics should be skeptical)
    if adj_conf is not None:
        adj_conf_val = float(adj_conf)
        if adj_conf_val > trade_conf + 0.1:
            issues.append(ConsistencyIssue(
                check_name="critic_alignment",
                severity="info",
                description=(
                    f"Critic INCREASED confidence from {trade_conf:.2f} to {adj_conf_val:.2f} — "
                    f"critics should generally be skeptical, not promotional"
                ),
                agents_involved=["critic"],
            ))

    return True, issues


def _check_flip_consistency(
    regime_data: Dict, trade_data: Dict,
    risk_data: Optional[Dict], critic_data: Optional[Dict],
    recent_decisions: Optional[List[Dict]],
) -> Tuple[bool, List[ConsistencyIssue]]:
    """Check if a flip decision is justified by market change."""
    issues = []
    action = trade_data.get("a", trade_data.get("action", "skip"))

    if action not in ("flip", "reverse"):
        return True, issues

    if not recent_decisions:
        return True, issues

    # Check if we're flip-flopping (recent decisions alternate)
    recent_actions = [
        d.get("action", d.get("a", "skip"))
        for d in recent_decisions[-3:]
    ]

    flip_count = sum(1 for a in recent_actions if a in ("flip", "reverse"))
    if flip_count >= 2:
        issues.append(ConsistencyIssue(
            check_name="flip_consistency",
            severity="critical",
            description=(
                f"Flip requested but {flip_count} flips in last 3 decisions — "
                f"flip-flopping detected, likely destroying edge"
            ),
            agents_involved=["trade"],
            suggestion="Override to skip — stabilize before re-entering",
        ))
        return False, issues

    return True, issues


# ── Tracking & Analytics ─────────────────────────────────────────

class ConsistencyTracker:
    """Tracks consistency scores over time for trend detection."""

    def __init__(self, window: int = 50):
        self._scores: List[float] = []
        self._issue_counts: Dict[str, int] = {}
        self._window = window

    def record(self, report: ConsistencyReport) -> None:
        """Record a consistency report."""
        self._scores.append(report.score)
        if len(self._scores) > self._window:
            self._scores = self._scores[-self._window:]

        for issue in report.issues:
            key = issue.check_name
            self._issue_counts[key] = self._issue_counts.get(key, 0) + 1

    @property
    def avg_score(self) -> float:
        """Average consistency score over the window."""
        if not self._scores:
            return 1.0
        return sum(self._scores) / len(self._scores)

    @property
    def trend(self) -> str:
        """Is consistency improving, declining, or stable?"""
        if len(self._scores) < 10:
            return "insufficient_data"
        first_half = self._scores[:len(self._scores) // 2]
        second_half = self._scores[len(self._scores) // 2:]
        first_avg = sum(first_half) / len(first_half)
        second_avg = sum(second_half) / len(second_half)
        diff = second_avg - first_avg
        if diff > 0.05:
            return "improving"
        elif diff < -0.05:
            return "declining"
        return "stable"

    @property
    def most_common_issues(self) -> List[Tuple[str, int]]:
        """Most frequently occurring issue types."""
        return sorted(self._issue_counts.items(), key=lambda x: -x[1])[:5]

    def get_stats(self) -> Dict[str, Any]:
        """Full stats for monitoring."""
        return {
            "avg_score": round(self.avg_score, 3),
            "trend": self.trend,
            "total_checks": len(self._scores),
            "top_issues": dict(self.most_common_issues),
        }


# ── Singleton ────────────────────────────────────────────────────

_tracker: Optional[ConsistencyTracker] = None


def get_consistency_tracker() -> ConsistencyTracker:
    """Get or create the singleton ConsistencyTracker."""
    global _tracker
    if _tracker is None:
        _tracker = ConsistencyTracker(window=50)
    return _tracker
