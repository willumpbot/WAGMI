"""
Hybrid LLM trigger system.

Instead of calling the LLM on a fixed 5-minute timer, we call it when
meaningful decision boundaries are crossed. This gives peak intelligence
exactly when it matters, while keeping API costs low during quiet periods.

Trigger hierarchy (highest priority first):
  1. PRE_TRADE      - Signal passed all filters, about to open position
  2. POSITION_CLOSED - Position just closed (SL/TP/trailing), learn from it
  3. REGIME_SHIFT    - Market structure changed on any symbol
  4. HIGH_CONFIDENCE - A signal with >= 75% confidence appeared
  5. STRATEGY_CONSENSUS - 3+ strategies agree on direction
  6. CROSS_MARKET_DIVERGENCE - BTC diverging from alts
  7. PERIODIC        - 5-minute heartbeat fallback
"""

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional

logger = logging.getLogger("bot.llm.triggers")


class LLMTrigger(IntEnum):
    """Trigger types, ordered by priority (lower = higher priority)."""
    PRE_TRADE = 1
    POSITION_CLOSED = 2
    REGIME_SHIFT = 3
    HIGH_CONFIDENCE = 4
    STRATEGY_CONSENSUS = 5
    CROSS_MARKET_DIVERGENCE = 6
    PERIODIC = 7


# Minimum seconds between LLM calls for each trigger type.
# Higher-priority triggers have shorter cooldowns.
TRIGGER_COOLDOWNS: Dict[LLMTrigger, int] = {
    LLMTrigger.PRE_TRADE: 30,
    LLMTrigger.POSITION_CLOSED: 30,
    LLMTrigger.REGIME_SHIFT: 60,
    LLMTrigger.HIGH_CONFIDENCE: 60,
    LLMTrigger.STRATEGY_CONSENSUS: 60,
    LLMTrigger.CROSS_MARKET_DIVERGENCE: 120,
    LLMTrigger.PERIODIC: 300,
}

# Human-readable trigger descriptions
TRIGGER_LABELS: Dict[LLMTrigger, str] = {
    LLMTrigger.PRE_TRADE: "pre-trade validation",
    LLMTrigger.POSITION_CLOSED: "position closed",
    LLMTrigger.REGIME_SHIFT: "regime shift",
    LLMTrigger.HIGH_CONFIDENCE: "high-confidence signal",
    LLMTrigger.STRATEGY_CONSENSUS: "strategy consensus",
    LLMTrigger.CROSS_MARKET_DIVERGENCE: "cross-market divergence",
    LLMTrigger.PERIODIC: "periodic update",
}


@dataclass
class TriggerEvent:
    """A single trigger event with context."""
    trigger: LLMTrigger
    symbol: str = ""
    context: str = ""  # Human-readable context for the LLM
    timestamp: float = field(default_factory=time.time)


class TriggerAccumulator:
    """Collects trigger events during a tick cycle and determines if LLM should be called.

    Usage:
        acc = TriggerAccumulator()
        # During tick processing:
        acc.add(LLMTrigger.HIGH_CONFIDENCE, "SOL", "SOL 82% LONG signal")
        acc.add(LLMTrigger.PRE_TRADE, "SOL", "Opening LONG SOL 5x")
        # At end of tick:
        if acc.should_fire():
            trigger, context = acc.get_best()
            call_llm(trigger=trigger, context=context)
            acc.clear()
    """

    def __init__(self):
        self._events: List[TriggerEvent] = []
        self._last_call_ts: Dict[LLMTrigger, float] = {}
        self._last_any_call_ts: float = 0.0
        # Track regime per symbol for shift detection
        self._last_regime: Dict[str, str] = {}

    def add(self, trigger: LLMTrigger, symbol: str = "", context: str = ""):
        """Add a trigger event."""
        self._events.append(TriggerEvent(
            trigger=trigger,
            symbol=symbol,
            context=context,
        ))

    def should_fire(self) -> bool:
        """Check if any accumulated trigger should fire the LLM call.

        Respects per-trigger cooldowns and a global minimum cooldown of 30s.
        """
        if not self._events:
            return False

        now = time.time()

        # Global minimum cooldown: never call more than once per 30 seconds
        if now - self._last_any_call_ts < 30:
            return False

        # Check if any event passes its trigger-specific cooldown
        for event in self._events:
            cooldown = TRIGGER_COOLDOWNS.get(event.trigger, 300)
            last_call = self._last_call_ts.get(event.trigger, 0.0)
            if now - last_call >= cooldown:
                return True

        return False

    def get_best(self) -> tuple:
        """Get the highest-priority trigger and its combined context.

        Returns:
            (trigger_type, context_string) or (None, "") if empty.
        """
        if not self._events:
            return None, ""

        now = time.time()

        # Filter to events that pass their cooldowns
        eligible = []
        for event in self._events:
            cooldown = TRIGGER_COOLDOWNS.get(event.trigger, 300)
            last_call = self._last_call_ts.get(event.trigger, 0.0)
            if now - last_call >= cooldown:
                eligible.append(event)

        if not eligible:
            # Fallback: return highest-priority event regardless
            eligible = self._events

        # Sort by priority (lower IntEnum value = higher priority)
        eligible.sort(key=lambda e: e.trigger.value)
        best = eligible[0]

        # Build combined context from ALL events (LLM sees everything)
        context_parts = []
        for e in self._events:
            label = TRIGGER_LABELS.get(e.trigger, e.trigger.name)
            if e.context:
                context_parts.append(f"[{label}] {e.context}")
            elif e.symbol:
                context_parts.append(f"[{label}] {e.symbol}")

        combined_context = "\n".join(context_parts)
        return best.trigger, combined_context

    def mark_called(self, trigger: LLMTrigger):
        """Record that we just made an LLM call for this trigger type."""
        now = time.time()
        self._last_call_ts[trigger] = now
        self._last_any_call_ts = now

    def clear(self):
        """Clear accumulated events (call after LLM call)."""
        self._events.clear()

    def check_regime_shift(self, symbol: str, current_regime: str) -> bool:
        """Check if regime changed for a symbol. Returns True if shifted."""
        prev = self._last_regime.get(symbol)
        self._last_regime[symbol] = current_regime

        if prev is not None and prev != current_regime:
            return True
        return False

    def check_cross_market_divergence(
        self, price_changes_1h: Dict[str, float]
    ) -> Optional[str]:
        """Detect BTC/alt divergence.

        Fires when BTC moved >2% in 1h while average alt moved <0.5%.
        Returns context string if divergence detected, None otherwise.
        """
        btc_change = price_changes_1h.get("BTC", 0.0)
        if abs(btc_change) < 2.0:
            return None

        # Calculate average alt change (excluding BTC)
        alt_changes = [
            v for k, v in price_changes_1h.items()
            if k != "BTC" and v != 0.0
        ]
        if not alt_changes:
            return None

        avg_alt = sum(abs(c) for c in alt_changes) / len(alt_changes)
        if avg_alt < 0.5:
            direction = "up" if btc_change > 0 else "down"
            return (
                f"BTC moved {btc_change:+.1f}% in 1h while alts avg "
                f"{avg_alt:.1f}% - correlation breakdown ({direction})"
            )

        return None

    def check_periodic(self) -> bool:
        """Check if enough time has passed for a periodic LLM call."""
        now = time.time()
        cooldown = TRIGGER_COOLDOWNS[LLMTrigger.PERIODIC]
        last_call = self._last_call_ts.get(LLMTrigger.PERIODIC, 0.0)
        return now - last_call >= cooldown

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def event_summary(self) -> str:
        """One-line summary of pending events."""
        if not self._events:
            return "none"
        counts: Dict[str, int] = {}
        for e in self._events:
            name = e.trigger.name.lower()
            counts[name] = counts.get(name, 0) + 1
        return " ".join(f"{k}={v}" for k, v in counts.items())
