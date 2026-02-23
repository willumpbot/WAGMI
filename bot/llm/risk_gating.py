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
    6. Panic regime requires >= 0.8 confidence
    7. Unknown regime with non-flat action -> reject
    8. Low liquidity regime with non-flat action -> reject
    9. Consecutive losses > 4 requires >= 0.75 confidence
    10. Strategy weight sanity check
    11. Flip requires higher confidence (>= 0.7)

    Actions: "proceed" (go with ensemble), "flat" (skip), "flip" (reverse)

    Returns GatedResult(allowed=True, decision=...) if all checks pass.
    """

    action = decision.action

    # Rule 0: flat is always allowed (it's a non-action)
    if action == "flat":
        return GatedResult(allowed=True, decision=decision, reason="flat_passthrough")

    # Rule 1: Circuit breaker
    if risk.circuit_breaker_active:
        return _reject("circuit_breaker_active", decision)

    # Rule 2: Confidence floor
    if decision.confidence < 0.6:
        return _reject(
            f"confidence_too_low ({decision.confidence:.2f} < 0.60)",
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
    if decision.regime == Regime.PANIC.value and decision.confidence < 0.80:
        return _reject(
            f"panic_regime_low_conf ({decision.confidence:.2f} < 0.80)",
            decision,
        )

    # Rule 7: Unknown regime -> reject directional trades
    if decision.regime == Regime.UNKNOWN.value:
        return _reject("unknown_regime_directional", decision)

    # Rule 8: Low liquidity -> reject directional trades
    if decision.regime == Regime.LOW_LIQUIDITY.value:
        return _reject("low_liquidity_directional", decision)

    # Rule 9: Consecutive losses streak
    if risk.consecutive_losses > 4 and decision.confidence < 0.75:
        return _reject(
            f"loss_streak ({risk.consecutive_losses} losses, conf {decision.confidence:.2f} < 0.75)",
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
    if action == "flip" and decision.confidence < 0.70:
        return _reject(
            f"flip_confidence_too_low ({decision.confidence:.2f} < 0.70)",
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
