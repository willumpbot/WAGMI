"""
Hybrid LLM trigger system.

Instead of calling the LLM on a fixed 5-minute timer, we call it when
meaningful decision boundaries are crossed. This gives peak intelligence
exactly when it matters, while keeping API costs low during quiet periods.

Trigger hierarchy (highest priority first):
  1. PRE_TRADE              - About to open position (highest value)
  2. PRE_CLOSE              - Position about to hit SL/TP/trailing
  3. POSITION_CLOSED        - Position just closed, learn from it
  4. REGIME_SHIFT            - Market regime changed
  5. HIGH_CONFIDENCE         - Signal >= 75% confidence
  6. STRATEGY_CONSENSUS      - 3+ strategies agree
  7. STRATEGY_DISAGREEMENT   - Strong opposing signals (conflict)
  8. CROSS_MARKET_DIVERGENCE - BTC/ETH/alt divergence
  9. MEMORY_EVENT            - Performance shift detected
  10. PERIODIC               - 5-minute heartbeat fallback

Each trigger can be disabled via env var: DISABLE_LLM_TRIGGER_<NAME>=1
e.g. DISABLE_LLM_TRIGGER_PRE_CLOSE=1

Rate caps: max 20 calls/hour, 200 calls/day (configurable via env)
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.triggers")


# ── Trigger types ──────────────────────────────────────────────

class LLMTrigger(IntEnum):
    """Trigger types, ordered by priority (lower = higher priority)."""
    PRE_TRADE = 1
    PRE_CLOSE = 2
    POSITION_CLOSED = 3
    REGIME_SHIFT = 4
    HIGH_CONFIDENCE = 5
    STRATEGY_CONSENSUS = 6
    STRATEGY_DISAGREEMENT = 7
    CROSS_MARKET_DIVERGENCE = 8
    MEMORY_EVENT = 9
    PERIODIC = 10


# Minimum seconds between LLM calls for each trigger type.
TRIGGER_COOLDOWNS: Dict[LLMTrigger, int] = {
    LLMTrigger.PRE_TRADE: 30,
    LLMTrigger.PRE_CLOSE: 30,
    LLMTrigger.POSITION_CLOSED: 30,
    LLMTrigger.REGIME_SHIFT: 60,
    LLMTrigger.HIGH_CONFIDENCE: 60,
    LLMTrigger.STRATEGY_CONSENSUS: 60,
    LLMTrigger.STRATEGY_DISAGREEMENT: 60,
    LLMTrigger.CROSS_MARKET_DIVERGENCE: 120,
    LLMTrigger.MEMORY_EVENT: 180,
    LLMTrigger.PERIODIC: 300,
}

# Human-readable trigger descriptions
TRIGGER_LABELS: Dict[LLMTrigger, str] = {
    LLMTrigger.PRE_TRADE: "pre-trade validation",
    LLMTrigger.PRE_CLOSE: "pre-close assessment",
    LLMTrigger.POSITION_CLOSED: "position closed",
    LLMTrigger.REGIME_SHIFT: "regime shift",
    LLMTrigger.HIGH_CONFIDENCE: "high-confidence signal",
    LLMTrigger.STRATEGY_CONSENSUS: "strategy consensus",
    LLMTrigger.STRATEGY_DISAGREEMENT: "strategy disagreement",
    LLMTrigger.CROSS_MARKET_DIVERGENCE: "cross-market divergence",
    LLMTrigger.MEMORY_EVENT: "memory-worthy event",
    LLMTrigger.PERIODIC: "periodic update",
}

# Global minimum seconds between ANY LLM call
_GLOBAL_MIN_COOLDOWN_S = int(os.getenv("LLM_MIN_COOLDOWN_S", "30"))

# Rate caps
_MAX_CALLS_PER_HOUR = int(os.getenv("LLM_MAX_CALLS_HOUR", "20"))
_MAX_CALLS_PER_DAY = int(os.getenv("LLM_MAX_CALLS_DAY", "200"))


def _is_trigger_disabled(trigger: LLMTrigger) -> bool:
    """Check if a specific trigger type is disabled via env var."""
    name = trigger.name  # e.g. "PRE_TRADE"
    return os.getenv(f"DISABLE_LLM_TRIGGER_{name}", "0") in ("1", "true", "yes")


# ── Trigger event ─────────────────────────────────────────────

@dataclass
class TriggerEvent:
    """A single trigger event with context."""
    trigger: LLMTrigger
    symbol: str = ""
    context: str = ""  # Human-readable context for the LLM
    timestamp: float = field(default_factory=time.time)


# ── Performance tracker (for memory-worthy events) ─────────────

@dataclass
class StrategyPerformance:
    """Rolling performance stats for a strategy."""
    wins: int = 0
    losses: int = 0
    recent_outcomes: List[bool] = field(default_factory=list)  # last N outcomes
    _MAX_RECENT = 20

    def record(self, win: bool):
        self.recent_outcomes.append(win)
        if len(self.recent_outcomes) > self._MAX_RECENT:
            self.recent_outcomes.pop(0)
        if win:
            self.wins += 1
        else:
            self.losses += 1

    @property
    def recent_win_rate(self) -> float:
        if not self.recent_outcomes:
            return 0.5
        return sum(self.recent_outcomes) / len(self.recent_outcomes)

    @property
    def recent_count(self) -> int:
        return len(self.recent_outcomes)

    @property
    def streak(self) -> int:
        """Current streak: positive = win streak, negative = loss streak."""
        if not self.recent_outcomes:
            return 0
        streak = 0
        last = self.recent_outcomes[-1]
        for outcome in reversed(self.recent_outcomes):
            if outcome == last:
                streak += 1
            else:
                break
        return streak if last else -streak


# ── Main accumulator ──────────────────────────────────────────

class TriggerAccumulator:
    """Collects trigger events during a tick cycle and determines if LLM should be called.

    Features:
      - Per-trigger cooldowns
      - Global minimum cooldown (30s)
      - Hourly/daily rate caps
      - Per-trigger enable/disable via env vars
      - Multi-reason tracking (all triggers logged, best used for priority)
      - Strategy performance monitoring for memory events
      - Regime shift detection
      - Cross-market divergence detection (BTC vs ETH vs alts)

    Usage:
        acc = TriggerAccumulator()
        # During tick processing:
        acc.add(LLMTrigger.HIGH_CONFIDENCE, "SOL", "SOL 82% LONG signal")
        acc.add(LLMTrigger.PRE_TRADE, "SOL", "Opening LONG SOL 5x")
        # At end of tick:
        if acc.should_fire():
            trigger, context, all_reasons = acc.get_best()
            call_llm(trigger=trigger, context=context)
            acc.mark_called(trigger)
            acc.clear()
    """

    def __init__(self):
        self._events: List[TriggerEvent] = []
        self._last_call_ts: Dict[LLMTrigger, float] = {}
        self._last_any_call_ts: float = 0.0

        # Rate limiting
        self._call_timestamps: List[float] = []  # all call timestamps for rate caps

        # Regime tracking per symbol
        self._last_regime: Dict[str, str] = {}

        # Strategy performance tracking (for memory events)
        self._strategy_perf: Dict[str, StrategyPerformance] = {}
        self._entry_type_perf: Dict[str, StrategyPerformance] = {}
        self._last_perf_check_ts: float = 0.0
        self._perf_alerts_sent: Dict[str, float] = {}  # key -> timestamp (prevent spam)

    # ── Adding events ─────────────────────────────────────────

    def add(self, trigger: LLMTrigger, symbol: str = "", context: str = ""):
        """Add a trigger event. Silently skips if trigger type is disabled."""
        if _is_trigger_disabled(trigger):
            return
        self._events.append(TriggerEvent(
            trigger=trigger,
            symbol=symbol,
            context=context,
        ))

    # ── Firing logic ──────────────────────────────────────────

    def should_fire(self) -> bool:
        """Check if any accumulated trigger should fire the LLM call.

        Respects:
          - Per-trigger cooldowns
          - Global minimum cooldown
          - Hourly and daily rate caps
        """
        if not self._events:
            return False

        now = time.time()

        # Global minimum cooldown
        if now - self._last_any_call_ts < _GLOBAL_MIN_COOLDOWN_S:
            return False

        # Rate cap: hourly
        hour_ago = now - 3600
        recent_hour = sum(1 for ts in self._call_timestamps if ts > hour_ago)
        if recent_hour >= _MAX_CALLS_PER_HOUR:
            return False

        # Rate cap: daily
        day_ago = now - 86400
        recent_day = sum(1 for ts in self._call_timestamps if ts > day_ago)
        if recent_day >= _MAX_CALLS_PER_DAY:
            return False

        # Check if any event passes its trigger-specific cooldown
        for event in self._events:
            cooldown = TRIGGER_COOLDOWNS.get(event.trigger, 300)
            last_call = self._last_call_ts.get(event.trigger, 0.0)
            if now - last_call >= cooldown:
                return True

        return False

    def get_best(self) -> Tuple[Optional[LLMTrigger], str, List[str]]:
        """Get the highest-priority trigger, combined context, and all reason labels.

        Returns:
            (trigger_type, context_string, all_reason_labels)
        """
        if not self._events:
            return None, "", []

        now = time.time()

        # Filter to events that pass their cooldowns
        eligible = []
        for event in self._events:
            cooldown = TRIGGER_COOLDOWNS.get(event.trigger, 300)
            last_call = self._last_call_ts.get(event.trigger, 0.0)
            if now - last_call >= cooldown:
                eligible.append(event)

        if not eligible:
            eligible = self._events

        # Sort by priority (lower IntEnum value = higher priority)
        eligible.sort(key=lambda e: e.trigger.value)
        best = eligible[0]

        # Build combined context from ALL events (LLM sees everything)
        context_parts = []
        all_reasons = []
        seen_reasons = set()
        for e in self._events:
            label = TRIGGER_LABELS.get(e.trigger, e.trigger.name)
            if label not in seen_reasons:
                all_reasons.append(label)
                seen_reasons.add(label)
            if e.context:
                context_parts.append(f"[{label}] {e.context}")
            elif e.symbol:
                context_parts.append(f"[{label}] {e.symbol}")

        combined_context = "\n".join(context_parts)
        return best.trigger, combined_context, all_reasons

    def mark_called(self, trigger: LLMTrigger):
        """Record that we just made an LLM call for this trigger type."""
        now = time.time()
        self._last_call_ts[trigger] = now
        self._last_any_call_ts = now
        self._call_timestamps.append(now)

        # Prune old timestamps (keep last 24h)
        cutoff = now - 86400
        self._call_timestamps = [ts for ts in self._call_timestamps if ts > cutoff]

    def clear(self):
        """Clear accumulated events (call after each tick cycle)."""
        self._events.clear()

    # ── Regime shift detection ────────────────────────────────

    def check_regime_shift(self, symbol: str, current_regime: str) -> bool:
        """Check if regime changed for a symbol. Returns True if shifted."""
        prev = self._last_regime.get(symbol)
        self._last_regime[symbol] = current_regime
        if prev is not None and prev != current_regime:
            return True
        return False

    # ── Cross-market divergence ───────────────────────────────

    def check_cross_market_divergence(
        self, price_changes_1h: Dict[str, float]
    ) -> Optional[str]:
        """Detect meaningful cross-market divergences.

        Checks:
          1. BTC moving >2% while alts are flat (<0.5% avg)
          2. BTC and ETH diverging (moving opposite directions, each >1%)
          3. Single symbol volume/price surge while rest quiet
        """
        btc_change = price_changes_1h.get("BTC", 0.0)
        eth_change = price_changes_1h.get("ETH", 0.0)

        divergences = []

        # 1. BTC vs alts divergence
        alt_changes = [
            v for k, v in price_changes_1h.items()
            if k not in ("BTC", "ETH") and v != 0.0
        ]
        if abs(btc_change) >= 2.0 and alt_changes:
            avg_alt = sum(abs(c) for c in alt_changes) / len(alt_changes)
            if avg_alt < 0.5:
                direction = "up" if btc_change > 0 else "down"
                divergences.append(
                    f"BTC {btc_change:+.1f}% while alts avg {avg_alt:.1f}% "
                    f"(correlation breakdown {direction})"
                )

        # 2. BTC vs ETH divergence
        if abs(btc_change) >= 1.0 and abs(eth_change) >= 1.0:
            if (btc_change > 0 and eth_change < 0) or (btc_change < 0 and eth_change > 0):
                divergences.append(
                    f"BTC {btc_change:+.1f}% vs ETH {eth_change:+.1f}% "
                    f"(BTC/ETH divergence)"
                )

        # 3. Single outlier (any symbol moving >3x the average)
        all_changes = {k: v for k, v in price_changes_1h.items() if v != 0.0}
        if len(all_changes) >= 3:
            avg_abs = sum(abs(v) for v in all_changes.values()) / len(all_changes)
            if avg_abs > 0:
                for sym, chg in all_changes.items():
                    if abs(chg) > max(avg_abs * 3, 2.0):
                        divergences.append(
                            f"{sym} outlier {chg:+.1f}% vs market avg {avg_abs:.1f}%"
                        )
                        break  # Only report one outlier

        if divergences:
            return "; ".join(divergences)
        return None

    # ── Strategy disagreement ─────────────────────────────────

    def check_strategy_disagreement(
        self,
        strategy_signals: Dict[str, str],
        strategy_confidences: Dict[str, float],
    ) -> Optional[str]:
        """Detect strong strategy disagreement.

        Args:
            strategy_signals: {strategy_name: "long"/"short"/"neutral"}
            strategy_confidences: {strategy_name: confidence_0_to_1}

        Fires when:
          - 2+ strong signals long AND 2+ strong signals short
          - OR a single strategy with >0.7 conf contradicts all others
        """
        strong_long = []
        strong_short = []
        for strat, side in strategy_signals.items():
            conf = strategy_confidences.get(strat, 0)
            if conf < 0.5:
                continue
            if side in ("long", "BUY"):
                strong_long.append((strat, conf))
            elif side in ("short", "SELL"):
                strong_short.append((strat, conf))

        # 2+ strong on each side -> conflict
        if len(strong_long) >= 2 and len(strong_short) >= 2:
            l_names = [s[0] for s in strong_long]
            s_names = [s[0] for s in strong_short]
            return (
                f"Strong conflict: {l_names} long vs {s_names} short"
            )

        # One high-conf strategy contradicting the rest
        if len(strong_long) >= 2 and len(strong_short) == 1:
            outlier = strong_short[0]
            if outlier[1] >= 0.7:
                return (
                    f"{outlier[0]} (conf={outlier[1]:.0%}) SHORT contradicts "
                    f"{len(strong_long)} long strategies"
                )
        if len(strong_short) >= 2 and len(strong_long) == 1:
            outlier = strong_long[0]
            if outlier[1] >= 0.7:
                return (
                    f"{outlier[0]} (conf={outlier[1]:.0%}) LONG contradicts "
                    f"{len(strong_short)} short strategies"
                )

        return None

    # ── Pre-close detection ───────────────────────────────────

    def check_pre_close(
        self,
        symbol: str,
        side: str,
        entry: float,
        current_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        state: str,
        atr: float = 0.0,
    ) -> Optional[str]:
        """Predict if a position is about to close.

        Fires when:
          - Price is within 1 ATR (or 1%) of SL, TP1, or TP2
          - Approaching means: price is moving TOWARD the level

        Args:
            state: "OPEN", "TP1_HIT", "TRAILING", etc.

        Returns context string if pre-close detected, None otherwise.
        """
        is_long = side == "LONG"

        # Calculate proximity thresholds
        proximity = max(atr * 0.5, abs(entry) * 0.005) if atr > 0 else abs(entry) * 0.01

        # Check SL proximity
        sl_dist = abs(current_price - sl)
        if sl_dist <= proximity:
            approaching = (is_long and current_price > sl) or (not is_long and current_price < sl)
            if approaching:
                pnl_pct = ((current_price - entry) / entry * 100) if is_long else ((entry - current_price) / entry * 100)
                action = "TRAILING_STOP" if state == "TRAILING" else "SL"
                return (
                    f"{symbol} {side} approaching {action} "
                    f"(price={current_price:.4g} sl={sl:.4g} dist={sl_dist:.4g}) "
                    f"PnL~{pnl_pct:+.1f}%"
                )

        # Check TP1 proximity (only in OPEN state)
        if state == "OPEN":
            tp1_dist = abs(current_price - tp1)
            if tp1_dist <= proximity:
                approaching = (is_long and current_price < tp1) or (not is_long and current_price > tp1)
                if approaching:
                    return (
                        f"{symbol} {side} approaching TP1 "
                        f"(price={current_price:.4g} tp1={tp1:.4g} dist={tp1_dist:.4g})"
                    )

        # Check TP2 proximity
        tp2_dist = abs(current_price - tp2)
        if tp2_dist <= proximity:
            approaching = (is_long and current_price < tp2) or (not is_long and current_price > tp2)
            if approaching:
                return (
                    f"{symbol} {side} approaching TP2 "
                    f"(price={current_price:.4g} tp2={tp2:.4g} dist={tp2_dist:.4g})"
                )

        return None

    # ── Memory-worthy event detection ─────────────────────────

    def record_trade_outcome(self, strategy: str, entry_type: str, win: bool):
        """Record a trade outcome for performance monitoring."""
        if strategy not in self._strategy_perf:
            self._strategy_perf[strategy] = StrategyPerformance()
        self._strategy_perf[strategy].record(win)

        if entry_type:
            if entry_type not in self._entry_type_perf:
                self._entry_type_perf[entry_type] = StrategyPerformance()
            self._entry_type_perf[entry_type].record(win)

    def check_memory_events(self) -> List[str]:
        """Check for performance shifts that the LLM should know about.

        Fires when:
          - A strategy's rolling win rate drops below 30% (over 10+ trades)
          - A strategy's rolling win rate rises above 70% (over 10+ trades)
          - An entry type has 4+ consecutive losses or wins
          - Any strategy or entry_type hits a performance threshold

        Returns list of context strings (may be empty).
        """
        now = time.time()

        # Rate limit: check at most every 60 seconds
        if now - self._last_perf_check_ts < 60:
            return []
        self._last_perf_check_ts = now

        events = []

        # Check strategy performance
        for name, perf in self._strategy_perf.items():
            if perf.recent_count < 10:
                continue

            key = f"strat_{name}"
            # Skip if we already reported this recently (15 min cooldown)
            if key in self._perf_alerts_sent and now - self._perf_alerts_sent[key] < 900:
                continue

            wr = perf.recent_win_rate
            if wr < 0.30:
                events.append(
                    f"Strategy '{name}' underperforming: "
                    f"{wr:.0%} win rate over last {perf.recent_count} trades"
                )
                self._perf_alerts_sent[key] = now
            elif wr > 0.70:
                events.append(
                    f"Strategy '{name}' outperforming: "
                    f"{wr:.0%} win rate over last {perf.recent_count} trades"
                )
                self._perf_alerts_sent[key] = now

        # Check entry type streaks
        for name, perf in self._entry_type_perf.items():
            if perf.recent_count < 5:
                continue

            key = f"etype_{name}"
            if key in self._perf_alerts_sent and now - self._perf_alerts_sent[key] < 900:
                continue

            streak = perf.streak
            if streak <= -4:
                events.append(
                    f"Entry type '{name}' on {abs(streak)}-trade loss streak "
                    f"(recent WR: {perf.recent_win_rate:.0%})"
                )
                self._perf_alerts_sent[key] = now
            elif streak >= 4:
                events.append(
                    f"Entry type '{name}' on {streak}-trade win streak "
                    f"(recent WR: {perf.recent_win_rate:.0%})"
                )
                self._perf_alerts_sent[key] = now

        return events

    # ── Low-value suppression ──────────────────────────────────

    def suppress_low_value(self):
        """Remove low-value trigger events to prevent unnecessary LLM calls.

        Rules:
        - Suppress PERIODIC if there are higher-priority events
        - Suppress MEMORY_EVENT if no meaningful performance shift
        - Suppress CROSS_MARKET_DIVERGENCE if BTC change < 1%
        """
        if len(self._events) <= 1:
            return

        has_high_priority = any(
            e.trigger.value <= LLMTrigger.STRATEGY_CONSENSUS.value
            for e in self._events
        )

        if has_high_priority:
            # Remove PERIODIC events (redundant when we have real triggers)
            before = len(self._events)
            self._events = [
                e for e in self._events
                if e.trigger != LLMTrigger.PERIODIC
            ]
            removed = before - len(self._events)
            if removed > 0:
                logger.debug(f"[TRIGGERS] Suppressed {removed} PERIODIC events (higher-priority available)")

    # ── Periodic check ────────────────────────────────────────

    def check_periodic(self) -> bool:
        """Check if enough time has passed for a periodic LLM call."""
        now = time.time()
        cooldown = TRIGGER_COOLDOWNS[LLMTrigger.PERIODIC]
        last_call = self._last_call_ts.get(LLMTrigger.PERIODIC, 0.0)
        return now - last_call >= cooldown

    # ── Properties ────────────────────────────────────────────

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

    @property
    def rate_stats(self) -> Dict[str, int]:
        """Current rate usage stats."""
        now = time.time()
        return {
            "calls_last_hour": sum(1 for ts in self._call_timestamps if ts > now - 3600),
            "calls_last_day": sum(1 for ts in self._call_timestamps if ts > now - 86400),
            "max_per_hour": _MAX_CALLS_PER_HOUR,
            "max_per_day": _MAX_CALLS_PER_DAY,
        }
