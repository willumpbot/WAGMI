"""
Signal Override System: LLM-triggered bypass for powerful signals.

The LLM is NOT constantly evaluating signals (that's expensive).
Instead, it gets TRIGGERED to read a signal only when:

1. The signal passes a "power threshold" (high confidence + consensus)
2. A circuit breaker or other blocker is active
3. The LLM can then decide: "this signal is so powerful it overrides the block"

This is cost-efficient because:
- Only triggers on the INTERSECTION of (powerful signal + active blocker)
- Most signals either (a) aren't blocked, or (b) aren't powerful enough
- The LLM only gets called when its judgment actually matters

Override hierarchy:
  - Circuit breaker: LLM can override if signal conf >= CB_CONF_OVERRIDE_PCT
  - Consecutive loss cooldown: LLM can override if signal is exceptional
  - Regime mismatch: LLM can override if cross-market data supports
  - Daily loss limit: NEVER overrideable (hard safety limit)
  - Max positions: NEVER overrideable (hard safety limit)
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("bot.llm.signal_override")


class BlockerType(Enum):
    """Types of blockers that can be overridden."""
    CIRCUIT_BREAKER = "circuit_breaker"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    REGIME_MISMATCH = "regime_mismatch"
    CONFIDENCE_FLOOR = "confidence_floor"
    COOLDOWN_ACTIVE = "cooldown_active"
    # These are NEVER overrideable
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_POSITIONS = "max_positions"


# Blockers that CAN be overridden by the LLM
OVERRIDEABLE_BLOCKERS = {
    BlockerType.CIRCUIT_BREAKER,
    BlockerType.CONSECUTIVE_LOSSES,
    BlockerType.REGIME_MISMATCH,
    BlockerType.CONFIDENCE_FLOOR,
    BlockerType.COOLDOWN_ACTIVE,
}

# Blockers that can NEVER be overridden
HARD_BLOCKERS = {
    BlockerType.DAILY_LOSS_LIMIT,
    BlockerType.MAX_POSITIONS,
}


@dataclass
class SignalPowerScore:
    """Measures how "powerful" a signal is for override consideration."""
    confidence: float = 0.0
    num_strategies_agree: int = 0
    total_strategies: int = 4
    volume_confirmation: bool = False
    regime_aligned: bool = False
    trend_aligned: bool = False
    funding_confirms: bool = False
    oi_confirms: bool = False
    historical_win_rate: float = 0.0  # Win rate on similar signals

    @property
    def power_score(self) -> float:
        """Calculate composite power score (0-100)."""
        score = 0.0

        # Base: confidence (40% weight)
        score += self.confidence * 0.4

        # Strategy agreement (25% weight)
        if self.total_strategies > 0:
            agreement = self.num_strategies_agree / self.total_strategies
            score += agreement * 25

        # Confirmations (35% weight, 5% each)
        confirmations = sum([
            self.volume_confirmation,
            self.regime_aligned,
            self.trend_aligned,
            self.funding_confirms,
            self.oi_confirms,
        ])
        score += confirmations * 7

        return min(100, score)

    @property
    def is_powerful(self) -> bool:
        """Is this signal powerful enough to consider overriding?"""
        return self.power_score >= 75

    @property
    def is_exceptional(self) -> bool:
        """Is this signal truly exceptional? (very rare)"""
        return (
            self.power_score >= 85
            and self.num_strategies_agree >= 3
            and self.confidence >= 80
        )


@dataclass
class OverrideDecision:
    """Result of an override evaluation."""
    should_override: bool
    reason: str
    power_score: float
    blocker_type: str
    llm_triggered: bool = False  # Was the LLM actually called?
    llm_confidence: float = 0.0
    llm_reasoning: str = ""
    timestamp: float = field(default_factory=time.time)


class SignalOverrideEngine:
    """Evaluates whether a powerful signal should override active blockers."""

    def __init__(self):
        self._override_history: List[Dict] = []
        self._last_override_time: float = 0
        self._override_cooldown: float = 300  # 5 minutes between overrides
        self._daily_overrides: int = 0
        self._max_daily_overrides: int = 3  # Safety cap
        self._day_start: float = 0

    def evaluate_override(
        self,
        signal_power: SignalPowerScore,
        blocker: BlockerType,
        blocker_detail: str = "",
        current_equity: float = 0.0,
        daily_pnl: float = 0.0,
    ) -> OverrideDecision:
        """Evaluate if a signal should override an active blocker.

        This is the FIRST stage - quick check before calling the LLM.
        If the signal passes the power threshold, the LLM gets triggered
        for the final decision.

        Returns:
            OverrideDecision with should_override and reasoning
        """
        # Hard blockers are NEVER overridden
        if blocker in HARD_BLOCKERS:
            return OverrideDecision(
                should_override=False,
                reason=f"Hard blocker {blocker.value} is never overrideable",
                power_score=signal_power.power_score,
                blocker_type=blocker.value,
            )

        # Check override cooldown
        if time.time() - self._last_override_time < self._override_cooldown:
            return OverrideDecision(
                should_override=False,
                reason="Override cooldown active",
                power_score=signal_power.power_score,
                blocker_type=blocker.value,
            )

        # Reset daily counter at midnight
        self._maybe_reset_daily()

        # Check daily override cap
        if self._daily_overrides >= self._max_daily_overrides:
            return OverrideDecision(
                should_override=False,
                reason=f"Daily override cap ({self._max_daily_overrides}) reached",
                power_score=signal_power.power_score,
                blocker_type=blocker.value,
            )

        # Signal must be powerful enough to even consider
        if not signal_power.is_powerful:
            return OverrideDecision(
                should_override=False,
                reason=f"Signal power {signal_power.power_score:.0f} below override threshold (75)",
                power_score=signal_power.power_score,
                blocker_type=blocker.value,
            )

        # Per-blocker override rules
        decision = self._evaluate_blocker_specific(
            signal_power, blocker, blocker_detail, current_equity, daily_pnl
        )

        if decision.should_override:
            self._record_override(decision)

        return decision

    def _evaluate_blocker_specific(
        self,
        power: SignalPowerScore,
        blocker: BlockerType,
        detail: str,
        equity: float,
        daily_pnl: float,
    ) -> OverrideDecision:
        """Per-blocker override evaluation logic."""

        if blocker == BlockerType.CIRCUIT_BREAKER:
            # Circuit breaker: only override with exceptional signals
            if power.is_exceptional:
                return OverrideDecision(
                    should_override=True,
                    reason=(
                        f"EXCEPTIONAL signal (power={power.power_score:.0f}, "
                        f"conf={power.confidence:.0f}%, "
                        f"{power.num_strategies_agree}/{power.total_strategies} agree) "
                        f"overrides circuit breaker"
                    ),
                    power_score=power.power_score,
                    blocker_type=blocker.value,
                    llm_triggered=True,
                )
            return OverrideDecision(
                should_override=False,
                reason=f"Signal powerful but not exceptional enough for CB override",
                power_score=power.power_score,
                blocker_type=blocker.value,
            )

        elif blocker == BlockerType.CONSECUTIVE_LOSSES:
            # Less strict: powerful signals can break loss streaks
            if power.is_powerful and power.confidence >= 75:
                return OverrideDecision(
                    should_override=True,
                    reason=(
                        f"Powerful signal (power={power.power_score:.0f}) "
                        f"overrides loss streak cooldown"
                    ),
                    power_score=power.power_score,
                    blocker_type=blocker.value,
                    llm_triggered=True,
                )
            return OverrideDecision(
                should_override=False,
                reason="Not powerful enough to override loss streak",
                power_score=power.power_score,
                blocker_type=blocker.value,
            )

        elif blocker == BlockerType.REGIME_MISMATCH:
            # Regime mismatch: override if signal has strong cross-market confirmation
            if power.trend_aligned and power.funding_confirms and power.confidence >= 70:
                return OverrideDecision(
                    should_override=True,
                    reason=(
                        f"Cross-market confirmation overrides regime mismatch "
                        f"(trend+funding aligned, conf={power.confidence:.0f}%)"
                    ),
                    power_score=power.power_score,
                    blocker_type=blocker.value,
                    llm_triggered=True,
                )
            return OverrideDecision(
                should_override=False,
                reason="Insufficient cross-market support to override regime mismatch",
                power_score=power.power_score,
                blocker_type=blocker.value,
            )

        elif blocker == BlockerType.CONFIDENCE_FLOOR:
            # Confidence floor: LLM can override if it sees something the metrics miss
            if power.is_powerful:
                return OverrideDecision(
                    should_override=True,
                    reason=(
                        f"Powerful signal (power={power.power_score:.0f}) "
                        f"overrides confidence floor"
                    ),
                    power_score=power.power_score,
                    blocker_type=blocker.value,
                    llm_triggered=True,
                )
            return OverrideDecision(
                should_override=False,
                reason="Not powerful enough to override confidence floor",
                power_score=power.power_score,
                blocker_type=blocker.value,
            )

        elif blocker == BlockerType.COOLDOWN_ACTIVE:
            # Cooldown: exceptional signals only
            if power.is_exceptional:
                return OverrideDecision(
                    should_override=True,
                    reason="Exceptional signal overrides cooldown",
                    power_score=power.power_score,
                    blocker_type=blocker.value,
                    llm_triggered=True,
                )
            return OverrideDecision(
                should_override=False,
                reason="Not exceptional enough to override cooldown",
                power_score=power.power_score,
                blocker_type=blocker.value,
            )

        return OverrideDecision(
            should_override=False,
            reason=f"Unknown blocker type: {blocker.value}",
            power_score=power.power_score,
            blocker_type=blocker.value,
        )

    def _record_override(self, decision: OverrideDecision):
        """Record a successful override."""
        self._last_override_time = time.time()
        self._daily_overrides += 1

        self._override_history.append({
            "ts": time.time(),
            "blocker": decision.blocker_type,
            "power_score": decision.power_score,
            "reason": decision.reason,
        })

        # Cap history
        if len(self._override_history) > 100:
            self._override_history = self._override_history[-100:]

        logger.info(
            f"[OVERRIDE] Signal override APPROVED: {decision.reason} "
            f"(daily count: {self._daily_overrides}/{self._max_daily_overrides})"
        )

    def _maybe_reset_daily(self):
        """Reset daily override counter at midnight."""
        now = time.time()
        if self._day_start == 0 or (now - self._day_start) > 86400:
            self._day_start = now
            self._daily_overrides = 0

    def get_override_stats(self) -> Dict[str, Any]:
        """Get override statistics."""
        return {
            "total_overrides": len(self._override_history),
            "daily_overrides": self._daily_overrides,
            "max_daily": self._max_daily_overrides,
            "last_override_time": self._last_override_time,
            "recent_overrides": self._override_history[-10:],
        }


# Module-level singleton
_engine: Optional[SignalOverrideEngine] = None


def get_override_engine() -> SignalOverrideEngine:
    """Get the singleton override engine."""
    global _engine
    if _engine is None:
        _engine = SignalOverrideEngine()
    return _engine


def should_override_blocker(
    confidence: float,
    num_agree: int,
    total_strategies: int,
    blocker: BlockerType,
    blocker_detail: str = "",
    volume_confirms: bool = False,
    regime_aligned: bool = False,
    trend_aligned: bool = False,
    funding_confirms: bool = False,
    oi_confirms: bool = False,
    historical_wr: float = 0.0,
    current_equity: float = 0.0,
    daily_pnl: float = 0.0,
) -> OverrideDecision:
    """Convenience function: evaluate if a signal should override a blocker.

    Call this when a trade would normally be blocked by a safety mechanism.
    Returns whether the signal is powerful enough to bypass the block.
    """
    power = SignalPowerScore(
        confidence=confidence,
        num_strategies_agree=num_agree,
        total_strategies=total_strategies,
        volume_confirmation=volume_confirms,
        regime_aligned=regime_aligned,
        trend_aligned=trend_aligned,
        funding_confirms=funding_confirms,
        oi_confirms=oi_confirms,
        historical_win_rate=historical_wr,
    )

    engine = get_override_engine()
    return engine.evaluate_override(
        signal_power=power,
        blocker=blocker,
        blocker_detail=blocker_detail,
        current_equity=current_equity,
        daily_pnl=daily_pnl,
    )
