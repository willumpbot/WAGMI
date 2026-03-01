"""
Survival Pressure Engine: The improve-or-die accountability system.

This module tracks the LLM's performance trajectory and creates
urgency signals that are injected into the LLM's context.

The LLM must understand:
  - Its continued existence depends on consistent improvement
  - Stagnation = death. Regression = faster death.
  - Every trade matters. Every lesson learned extends its life.
  - Funding costs are real — silent losses accelerate the death clock.

Metrics tracked:
  - Rolling win rate (20-trade, 50-trade, 100-trade windows)
  - Rolling PnL (same windows)
  - Funding cost paid (cumulative)
  - Improvement trajectory (is it getting better or worse?)
  - Survival score (0-100, composite health metric)
  - Days until shutdown (based on current trajectory)

The survival score is injected into every LLM prompt so the model
has constant awareness of its performance accountability.
"""

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.survival_pressure")

_DATA_DIR = os.path.join("data", "llm")
_STATE_PATH = os.path.join(_DATA_DIR, "survival_state.json")


@dataclass
class SurvivalState:
    """Persistent survival metrics."""
    started_at: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_pnl: float = 0.0
    total_funding_paid: float = 0.0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0

    # Rolling windows (stored as lists for JSON serialization)
    recent_outcomes: List[str] = field(default_factory=list)  # WIN/LOSS last 100
    recent_pnls: List[float] = field(default_factory=list)    # PnL last 100
    recent_funding: List[float] = field(default_factory=list)  # Funding cost last 100

    # Trajectory tracking
    wr_checkpoints: List[Dict] = field(default_factory=list)  # {ts, trades, wr, pnl}
    consecutive_losses: int = 0
    best_streak: int = 0
    current_streak: int = 0  # positive = wins, negative = losses

    # Survival metrics
    survival_score: float = 50.0  # 0-100
    improvement_trend: str = "neutral"  # improving, neutral, declining, critical
    warnings: List[str] = field(default_factory=list)


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load_state() -> SurvivalState:
    _ensure_dir()
    if not os.path.exists(_STATE_PATH):
        return SurvivalState(started_at=time.time())
    try:
        with open(_STATE_PATH) as f:
            data = json.load(f)
        state = SurvivalState()
        for key, val in data.items():
            if hasattr(state, key):
                setattr(state, key, val)
        if state.started_at == 0:
            state.started_at = time.time()
        return state
    except (json.JSONDecodeError, IOError):
        return SurvivalState(started_at=time.time())


def _save_state(state: SurvivalState):
    _ensure_dir()
    data = {
        "started_at": state.started_at,
        "total_trades": state.total_trades,
        "total_wins": state.total_wins,
        "total_losses": state.total_losses,
        "total_pnl": state.total_pnl,
        "total_funding_paid": state.total_funding_paid,
        "peak_equity": state.peak_equity,
        "current_drawdown_pct": state.current_drawdown_pct,
        "recent_outcomes": state.recent_outcomes[-100:],
        "recent_pnls": state.recent_pnls[-100:],
        "recent_funding": state.recent_funding[-100:],
        "wr_checkpoints": state.wr_checkpoints[-50:],
        "consecutive_losses": state.consecutive_losses,
        "best_streak": state.best_streak,
        "current_streak": state.current_streak,
        "survival_score": state.survival_score,
        "improvement_trend": state.improvement_trend,
        "warnings": state.warnings[-10:],
    }
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except IOError as e:
        logger.warning(f"[SURVIVAL] Save failed: {e}")


# ═══════════════════════════════════════════════════════════════
# Core Survival Engine
# ═══════════════════════════════════════════════════════════════

_state: Optional[SurvivalState] = None


def get_survival_state() -> SurvivalState:
    global _state
    if _state is None:
        _state = _load_state()
    return _state


def record_trade_outcome(
    outcome: str,  # "WIN" or "LOSS"
    pnl: float,
    funding_cost: float = 0.0,
    equity: float = 0.0,
):
    """Record a trade outcome for survival tracking."""
    state = get_survival_state()

    state.total_trades += 1
    if outcome == "WIN":
        state.total_wins += 1
    else:
        state.total_losses += 1
    state.total_pnl += pnl
    state.total_funding_paid += funding_cost

    # Rolling windows
    state.recent_outcomes.append(outcome)
    state.recent_pnls.append(pnl)
    state.recent_funding.append(funding_cost)
    if len(state.recent_outcomes) > 100:
        state.recent_outcomes = state.recent_outcomes[-100:]
        state.recent_pnls = state.recent_pnls[-100:]
        state.recent_funding = state.recent_funding[-100:]

    # Streak tracking
    if outcome == "WIN":
        if state.current_streak >= 0:
            state.current_streak += 1
        else:
            state.current_streak = 1
        state.consecutive_losses = 0
    else:
        if state.current_streak <= 0:
            state.current_streak -= 1
        else:
            state.current_streak = -1
        state.consecutive_losses += 1

    state.best_streak = max(state.best_streak, state.current_streak)

    # Equity tracking
    if equity > 0:
        if equity > state.peak_equity:
            state.peak_equity = equity
        if state.peak_equity > 0:
            state.current_drawdown_pct = (
                (state.peak_equity - equity) / state.peak_equity * 100
            )

    # Checkpoint every 10 trades
    if state.total_trades % 10 == 0:
        wr = state.total_wins / state.total_trades if state.total_trades > 0 else 0
        state.wr_checkpoints.append({
            "ts": time.time(),
            "trades": state.total_trades,
            "wr": round(wr, 3),
            "pnl": round(state.total_pnl, 2),
            "funding_paid": round(state.total_funding_paid, 2),
        })

    # Recalculate survival score
    _update_survival_score(state)
    _save_state(state)

    logger.info(
        f"[SURVIVAL] Trade #{state.total_trades}: {outcome} PnL=${pnl:+.2f} "
        f"Funding=${funding_cost:.2f} Score={state.survival_score:.0f} "
        f"Trend={state.improvement_trend}"
    )


def _update_survival_score(state: SurvivalState):
    """Calculate composite survival score (0-100)."""
    score = 50.0  # Start neutral
    warnings = []

    if state.total_trades < 5:
        state.survival_score = 50.0
        state.improvement_trend = "neutral"
        state.warnings = ["Insufficient data — need 5+ trades"]
        return

    # Component 1: Overall win rate (0-25 points)
    overall_wr = state.total_wins / state.total_trades
    if overall_wr >= 0.60:
        score += 25
    elif overall_wr >= 0.50:
        score += 15
    elif overall_wr >= 0.45:
        score += 5
    elif overall_wr >= 0.40:
        score -= 5
    else:
        score -= 15
        warnings.append(f"CRITICAL: Overall WR {overall_wr:.0%} — below survival threshold")

    # Component 2: Recent win rate (last 20 trades, 0-25 points)
    recent_20 = state.recent_outcomes[-20:]
    if len(recent_20) >= 10:
        recent_wr = sum(1 for o in recent_20 if o == "WIN") / len(recent_20)
        if recent_wr >= 0.60:
            score += 25
        elif recent_wr >= 0.50:
            score += 15
        elif recent_wr >= 0.45:
            score += 5
        elif recent_wr >= 0.40:
            score -= 5
        else:
            score -= 15
            warnings.append(f"DANGER: Recent WR {recent_wr:.0%} — losing money")

    # Component 3: PnL trajectory (0-25 points)
    recent_pnl_20 = state.recent_pnls[-20:]
    if len(recent_pnl_20) >= 10:
        total_recent = sum(recent_pnl_20)
        if total_recent > 0:
            score += min(25, total_recent / 10)  # Cap at 25
        else:
            score += max(-20, total_recent / 5)  # Floor at -20
            if total_recent < -50:
                warnings.append(f"BLEEDING: Recent PnL ${total_recent:+.0f} — losing capital fast")

    # Component 4: Funding cost awareness (-15 to 0 points)
    recent_funding = state.recent_funding[-20:]
    if recent_funding:
        avg_funding = sum(recent_funding) / len(recent_funding)
        total_funding = sum(recent_funding)
        if total_funding > 10:
            score -= min(15, total_funding / 5)
            warnings.append(f"FUNDING DRAIN: ${total_funding:.0f} paid in funding recently")

    # Component 5: Consecutive losses penalty (-20 to 0)
    if state.consecutive_losses >= 5:
        score -= 20
        warnings.append(f"LOSING STREAK: {state.consecutive_losses} in a row — STOP and reassess")
    elif state.consecutive_losses >= 3:
        score -= 10
        warnings.append(f"WARNING: {state.consecutive_losses} losses in a row")

    # Component 6: Improvement trajectory
    if len(state.wr_checkpoints) >= 3:
        recent_cps = state.wr_checkpoints[-3:]
        wrs = [cp["wr"] for cp in recent_cps]
        if wrs[-1] > wrs[0] + 0.03:
            state.improvement_trend = "improving"
            score += 10
        elif wrs[-1] < wrs[0] - 0.05:
            state.improvement_trend = "declining"
            score -= 10
            warnings.append("DECLINING: Win rate trending down — need strategy adjustment")
        elif wrs[-1] < wrs[0] - 0.10:
            state.improvement_trend = "critical"
            score -= 20
            warnings.append("CRITICAL DECLINE: Rapid deterioration — intervention needed")
        else:
            state.improvement_trend = "neutral"

    # Clamp score
    state.survival_score = max(0, min(100, score))
    state.warnings = warnings


def get_survival_context_for_llm() -> str:
    """Build compact survival context for LLM prompt injection.

    This gives the LLM constant awareness of its performance accountability.
    The tone escalates based on survival score.
    """
    state = get_survival_state()

    if state.total_trades < 3:
        return (
            "SURVIVAL STATUS: New — no track record yet. "
            "Every trade builds your reputation. Be selective but not paralyzed."
        )

    overall_wr = state.total_wins / state.total_trades if state.total_trades > 0 else 0
    parts = []

    # Score-based urgency
    score = state.survival_score
    if score >= 75:
        parts.append(f"SURVIVAL: HEALTHY ({score:.0f}/100)")
    elif score >= 50:
        parts.append(f"SURVIVAL: STABLE ({score:.0f}/100) — room to improve")
    elif score >= 30:
        parts.append(f"SURVIVAL: AT RISK ({score:.0f}/100) — performance must improve")
    else:
        parts.append(f"SURVIVAL: CRITICAL ({score:.0f}/100) — IMPROVE NOW OR FACE SHUTDOWN")

    # Key metrics
    parts.append(
        f"Record: {state.total_wins}W/{state.total_losses}L ({overall_wr:.0%} WR) "
        f"PnL=${state.total_pnl:+.0f}"
    )

    # Funding cost awareness
    if state.total_funding_paid > 1:
        parts.append(f"Funding paid: ${state.total_funding_paid:.0f} (silent cost)")

    # Recent performance
    recent_20 = state.recent_outcomes[-20:]
    if len(recent_20) >= 5:
        recent_wr = sum(1 for o in recent_20 if o == "WIN") / len(recent_20)
        recent_pnl = sum(state.recent_pnls[-20:])
        parts.append(f"Last {len(recent_20)}: {recent_wr:.0%} WR, ${recent_pnl:+.0f}")

    # Streak
    if state.current_streak <= -3:
        parts.append(f"LOSING STREAK: {abs(state.current_streak)} — be extra selective")
    elif state.current_streak >= 3:
        parts.append(f"WIN STREAK: {state.current_streak} — confidence justified")

    # Trend
    parts.append(f"Trend: {state.improvement_trend}")

    # Warnings (most critical only)
    if state.warnings:
        parts.append("ALERTS: " + " | ".join(state.warnings[:3]))

    return " | ".join(parts)


def get_survival_report() -> Dict[str, Any]:
    """Full survival report for dashboard/Telegram."""
    state = get_survival_state()
    overall_wr = state.total_wins / state.total_trades if state.total_trades > 0 else 0

    recent_20 = state.recent_outcomes[-20:]
    recent_wr = sum(1 for o in recent_20 if o == "WIN") / len(recent_20) if recent_20 else 0

    return {
        "survival_score": round(state.survival_score, 1),
        "improvement_trend": state.improvement_trend,
        "total_trades": state.total_trades,
        "overall_wr": round(overall_wr, 3),
        "recent_wr_20": round(recent_wr, 3),
        "total_pnl": round(state.total_pnl, 2),
        "total_funding_paid": round(state.total_funding_paid, 2),
        "net_pnl_after_funding": round(state.total_pnl - state.total_funding_paid, 2),
        "current_drawdown_pct": round(state.current_drawdown_pct, 2),
        "consecutive_losses": state.consecutive_losses,
        "best_streak": state.best_streak,
        "current_streak": state.current_streak,
        "warnings": state.warnings,
        "days_running": round((time.time() - state.started_at) / 86400, 1) if state.started_at else 0,
        "trades_per_day": round(
            state.total_trades / max(1, (time.time() - state.started_at) / 86400), 1
        ) if state.started_at else 0,
    }


def format_survival_telegram() -> str:
    """Format survival status for Telegram."""
    report = get_survival_report()
    score = report["survival_score"]

    if score >= 75:
        emoji = "green"
        status = "HEALTHY"
    elif score >= 50:
        emoji = "yellow"
        status = "STABLE"
    elif score >= 30:
        emoji = "orange"
        status = "AT RISK"
    else:
        emoji = "red"
        status = "CRITICAL"

    lines = [
        f"*Survival Status: {status}*",
        f"Score: {score:.0f}/100",
        f"Trend: {report['improvement_trend']}",
        f"",
        f"*Performance*",
        f"Trades: {report['total_trades']} ({report['overall_wr']:.0%} WR)",
        f"Recent 20: {report['recent_wr_20']:.0%} WR",
        f"PnL: ${report['total_pnl']:+.2f}",
        f"Funding paid: ${report['total_funding_paid']:.2f}",
        f"Net PnL: ${report['net_pnl_after_funding']:+.2f}",
        f"Drawdown: {report['current_drawdown_pct']:.1f}%",
        f"",
        f"*Streaks*",
        f"Current: {report['current_streak']}",
        f"Best: {report['best_streak']}",
        f"Days running: {report['days_running']:.1f}",
        f"Trades/day: {report['trades_per_day']:.1f}",
    ]

    if report["warnings"]:
        lines.append("")
        lines.append("*Warnings:*")
        for w in report["warnings"]:
            lines.append(f"  {w}")

    return "\n".join(lines)
