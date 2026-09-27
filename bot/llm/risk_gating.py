"""
Risk gating layer: the final safety check before an LLM decision reaches the bot.

This wraps the existing Python risk engine and adds LLM-specific checks.
The bot's own risk engine (CircuitBreaker, RiskManager) still runs independently.
This layer is ADDITIONAL safety on top of that.

Rejection reasons are logged for post-analysis.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Union

from llm.decision_types import LLMDecision, Regime
from llm import living_conf_floor

logger = logging.getLogger("bot.llm.risk_gate")


@dataclass
class RiskContext:
    """Current risk state from the Python bot."""
    daily_pnl: float            # Today's realized PnL
    max_daily_loss: float       # Absolute max daily loss allowed (e.g. 500)
    equity: float               # Current equity
    max_leverage: float         # Global max leverage
    current_leverage: float     # Total leverage exposure across all positions
    volatility: float           # Current market volatility (ATR/price %)
    max_volatility: float       # Max volatility threshold for trading
    open_positions: int         # Number of open positions
    max_positions: int          # Max allowed positions
    circuit_breaker_active: bool = False
    consecutive_losses: int = 0


@dataclass
class GatedResult:
    """Result of risk gating."""
    allowed: bool
    decision: Optional[LLMDecision] = None
    reason: str = ""


def gate_decision(decision: LLMDecision, risk: RiskContext) -> GatedResult:
    """Apply risk rules to an LLM decision.

    Rules (in priority order):
    1. Circuit breaker active -> reject everything except flat
    2. Confidence floor (< 0.6 for non-flat actions)
    3. Daily loss limit hit
    4. Max positions reached (for non-flat actions)
    5. Volatility cap exceeded
    6. Panic regime requires >= 0.7 confidence
    7. Unknown regime with non-flat action -> reject
    8. Low liquidity regime with non-flat action -> reject
    9. Consecutive losses > 4 requires >= 0.68 confidence
    10. Strategy weight sanity check
    11. Flip requires higher confidence (>= 0.65)

    Actions: "proceed" (go with ensemble), "flat" (skip), "flip" (reverse)

    Returns GatedResult(allowed=True, decision=...) if all checks pass.
    """

    action = decision.action

    # Rule 0: flat is always allowed (it's a non-action)
    if action == "flat":
        return GatedResult(allowed=True, decision=decision, reason="flat_passthrough")

    # Every non-flat decision that reaches the gate is evidence of where the
    # ensemble's confidence scale currently sits (see llm/living_conf_floor.py).
    # Recorded before any rejection so the distribution is not survivor-biased.
    living_conf_floor.record(decision.confidence, action)

    # Rule 1: Circuit breaker
    if risk.circuit_breaker_active:
        return _reject("circuit_breaker_active", decision)

    # Rule 2: Confidence floor — LIVING VALUE when LIVING_CONF_FLOOR is on
    # (a percentile of the confidences the ensemble actually emits), else the
    # legacy hardcoded 0.60. The 0.60 constant silently became an absolute wall
    # once the DEFABRICATE_* flags removed confidence inflation: zero trades
    # 2026-07-29 -> 2026-09-12 against a scale that now tops out near 0.55.
    conf_floor = living_conf_floor.base_floor(0.60)
    if decision.confidence < conf_floor:
        return _reject(
            f"confidence_too_low ({decision.confidence:.2f} < {conf_floor:.2f})",
            decision,
        )

    # Rule 3: Daily loss limit
    if risk.daily_pnl < -risk.max_daily_loss:
        return _reject(
            f"daily_loss_limit (PnL={risk.daily_pnl:.2f} < -{risk.max_daily_loss:.2f})",
            decision,
        )

    # Rule 4: Max positions
    if risk.open_positions >= risk.max_positions:
        return _reject(
            f"max_positions ({risk.open_positions}/{risk.max_positions})",
            decision,
        )

    # Rule 5: Volatility cap
    if risk.volatility > risk.max_volatility > 0:
        return _reject(
            f"volatility_too_high ({risk.volatility:.2f}% > {risk.max_volatility:.2f}%)",
            decision,
        )

    # Rule 6: Panic regime requires high confidence
    # Lowered from 0.80 to 0.70 — panic regime has big moves, 0.80 was blocking
    # legitimate crash/bounce trades where edge is real but certainty is moderate
    panic_floor = living_conf_floor.scaled(0.70)
    if decision.regime == Regime.PANIC.value and decision.confidence < panic_floor:
        return _reject(
            f"panic_regime_low_conf ({decision.confidence:.2f} < {panic_floor:.2f})",
            decision,
        )

    # Rule 7: Unknown regime -> reject directional trades
    if decision.regime == Regime.UNKNOWN.value:
        return _reject("unknown_regime_directional", decision)

    # Rule 8: Low liquidity -> reject directional trades
    if decision.regime == Regime.LOW_LIQUIDITY.value:
        return _reject("low_liquidity_directional", decision)

    # Rule 9: Consecutive losses streak
    # Lowered from 0.75 to 0.68 — after losses, the bot needs to recover.
    # 0.75 was too strict, blocking legitimate recovery trades with real edge.
    streak_floor = living_conf_floor.scaled(0.68)
    if risk.consecutive_losses > 4 and decision.confidence < streak_floor:
        return _reject(
            f"loss_streak ({risk.consecutive_losses} losses, "
            f"conf {decision.confidence:.2f} < {streak_floor:.2f})",
            decision,
        )

    # Rule 10: Strategy weight sanity
    sw = decision.strategy_weights
    total_weight = sum(sw.to_dict().values())
    if total_weight < 0.5:
        return _reject(
            f"strategy_weights_too_low (sum={total_weight:.2f})",
            decision,
        )

    # Rule 11: Flip requires higher confidence (contradicting ensemble is risky)
    # Lowered from 0.70 to 0.65 — legitimate reversals (BTC structure shift,
    # regime transition) often come at 0.65-0.70 confidence. Blocking them
    # means missing directional edge during transitions.
    flip_floor = living_conf_floor.scaled(0.65)
    if action == "flip" and decision.confidence < flip_floor:
        return _reject(
            f"flip_confidence_too_low ({decision.confidence:.2f} < {flip_floor:.2f})",
            decision,
        )

    # All checks passed
    logger.info(
        f"[LLM-GATE] ALLOWED: {action} conf={decision.confidence:.2f} "
        f"regime={decision.regime} size_mult={decision.size_multiplier:.2f}"
    )
    return GatedResult(allowed=True, decision=decision, reason="all_checks_passed")


def _reject(reason: str, decision: LLMDecision) -> GatedResult:
    """Log and return a rejection."""
    logger.info(
        f"[LLM-GATE] REJECTED: {decision.action} conf={decision.confidence:.2f} "
        f"regime={decision.regime} reason={reason}"
    )
    return GatedResult(allowed=False, decision=None, reason=reason)
