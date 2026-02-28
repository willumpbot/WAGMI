"""
Signal Flagger: Auto-detect and flag high-quality signals for LLM attention.

Not every signal deserves LLM evaluation (that's expensive). This module
runs cheap heuristic checks on every signal and flags the ones that are
"good enough" to warrant deeper LLM analysis.

Flagging criteria (any of these triggers a flag):

1. SNIPER CANDIDATE: High confidence + high consensus + regime aligned
   → These are potential perfect-entry opportunities

2. ANOMALY: Unusual market conditions (volume spike, funding extreme, etc.)
   → The LLM should evaluate if this is opportunity or danger

3. PATTERN MATCH: Signal matches a historically profitable pattern
   → The LLM should confirm and potentially size up

4. REVERSAL SIGNAL: Strong counter-trend signal with confirmation
   → These are rare but extremely profitable if correct

5. DIVERGENCE: Strategies strongly disagree (some bullish, some bearish)
   → The LLM should break the tie with cross-market analysis

Flags are lightweight (no LLM call). The main loop checks flags and
decides whether to trigger a full LLM evaluation.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Set

logger = logging.getLogger("bot.llm.signal_flagger")


class FlagType(Enum):
    """Types of signal flags."""
    SNIPER_CANDIDATE = "sniper_candidate"
    ANOMALY = "anomaly"
    PATTERN_MATCH = "pattern_match"
    REVERSAL_SIGNAL = "reversal"
    STRATEGY_DIVERGENCE = "divergence"
    BREAKOUT = "breakout"
    MOMENTUM_SURGE = "momentum_surge"
    SQUEEZE_SETUP = "squeeze_setup"


@dataclass
class SignalFlag:
    """A flag attached to a signal."""
    flag_type: FlagType
    priority: int  # 1=low, 2=medium, 3=high, 4=critical
    reason: str
    extra: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def should_trigger_llm(self) -> bool:
        """Should this flag trigger an LLM evaluation?"""
        return self.priority >= 3


@dataclass
class FlaggedSignal:
    """A signal with attached flags."""
    symbol: str
    side: str
    confidence: float
    regime: str
    flags: List[SignalFlag] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def max_priority(self) -> int:
        return max((f.priority for f in self.flags), default=0)

    @property
    def should_trigger_llm(self) -> bool:
        return any(f.should_trigger_llm for f in self.flags)

    @property
    def flag_summary(self) -> str:
        if not self.flags:
            return "no flags"
        return ", ".join(f"{f.flag_type.value}(P{f.priority})" for f in self.flags)


class SignalFlagger:
    """Evaluates signals and attaches quality/attention flags."""

    def __init__(self):
        self._flag_history: List[Dict] = []
        self._flag_counts: Dict[str, int] = {}

    def evaluate_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        regime: str,
        num_agree: int,
        total_strategies: int,
        strategy_signals: Dict[str, str] = None,
        volume_ratio: float = 1.0,
        funding_rate: float = 0.0,
        oi_change_pct: float = 0.0,
        atr_ratio: float = 1.0,
        btc_trend: str = "",
        price_change_1h: float = 0.0,
        price_change_4h: float = 0.0,
        historical_pattern: str = "",
        historical_win_rate: float = 0.0,
    ) -> FlaggedSignal:
        """Evaluate a signal and attach relevant flags.

        This is CHEAP (no LLM call). Runs on every signal.
        Returns a FlaggedSignal with zero or more flags attached.
        """
        flagged = FlaggedSignal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            regime=regime,
        )

        # 1. SNIPER CANDIDATE
        self._check_sniper(flagged, confidence, num_agree, total_strategies, regime, volume_ratio)

        # 2. ANOMALY
        self._check_anomaly(flagged, volume_ratio, funding_rate, oi_change_pct, atr_ratio, price_change_1h)

        # 3. PATTERN MATCH
        self._check_pattern(flagged, historical_pattern, historical_win_rate)

        # 4. REVERSAL SIGNAL
        self._check_reversal(flagged, side, regime, price_change_1h, price_change_4h, btc_trend)

        # 5. STRATEGY DIVERGENCE
        self._check_divergence(flagged, strategy_signals or {}, num_agree, total_strategies)

        # 6. BREAKOUT
        self._check_breakout(flagged, volume_ratio, price_change_1h, atr_ratio)

        # 7. MOMENTUM SURGE
        self._check_momentum(flagged, volume_ratio, price_change_1h, oi_change_pct)

        # 8. SQUEEZE SETUP
        self._check_squeeze(flagged, funding_rate, oi_change_pct, price_change_1h)

        # Record if any flags
        if flagged.flags:
            self._record_flags(flagged)

        return flagged

    def _check_sniper(
        self,
        flagged: FlaggedSignal,
        confidence: float,
        num_agree: int,
        total: int,
        regime: str,
        volume_ratio: float,
    ):
        """Flag potential sniper-quality setups."""
        # Perfect alignment: high conf + high consensus + good regime + volume
        if (confidence >= 80
            and num_agree >= 3
            and regime in ("trend", "trending")
            and volume_ratio >= 1.2):
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.SNIPER_CANDIDATE,
                priority=4,
                reason=(
                    f"Sniper setup: {confidence:.0f}% conf, "
                    f"{num_agree}/{total} agree, {regime} regime, "
                    f"{volume_ratio:.1f}x volume"
                ),
            ))
        elif confidence >= 85 and num_agree >= 3:
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.SNIPER_CANDIDATE,
                priority=3,
                reason=f"High-conviction: {confidence:.0f}% conf, {num_agree}/{total} agree",
            ))

    def _check_anomaly(
        self,
        flagged: FlaggedSignal,
        volume_ratio: float,
        funding_rate: float,
        oi_change_pct: float,
        atr_ratio: float,
        price_change_1h: float,
    ):
        """Flag unusual market conditions."""
        anomalies = []

        if volume_ratio >= 3.0:
            anomalies.append(f"volume spike {volume_ratio:.1f}x")

        if abs(funding_rate) >= 0.05:
            anomalies.append(f"extreme funding {funding_rate:+.4f}")

        if abs(oi_change_pct) >= 10:
            anomalies.append(f"OI change {oi_change_pct:+.1f}%")

        if atr_ratio >= 2.5:
            anomalies.append(f"volatility spike {atr_ratio:.1f}x ATR")

        if abs(price_change_1h) >= 5.0:
            anomalies.append(f"price move {price_change_1h:+.1f}% in 1h")

        if anomalies:
            priority = 3 if len(anomalies) >= 2 else 2
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.ANOMALY,
                priority=priority,
                reason=f"Market anomaly: {', '.join(anomalies)}",
                extra={"anomalies": anomalies},
            ))

    def _check_pattern(
        self,
        flagged: FlaggedSignal,
        pattern: str,
        win_rate: float,
    ):
        """Flag signals matching historically profitable patterns."""
        if pattern and win_rate >= 0.65:
            priority = 4 if win_rate >= 0.75 else 3
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.PATTERN_MATCH,
                priority=priority,
                reason=f"Pattern '{pattern}' has {win_rate:.0%} historical win rate",
                extra={"pattern": pattern, "win_rate": win_rate},
            ))

    def _check_reversal(
        self,
        flagged: FlaggedSignal,
        side: str,
        regime: str,
        change_1h: float,
        change_4h: float,
        btc_trend: str,
    ):
        """Flag strong reversal signals."""
        # Buying after a significant dip
        is_buy_reversal = (
            side.upper() in ("BUY", "LONG")
            and change_1h <= -3.0
            and change_4h <= -5.0
        )
        # Selling after a significant pump
        is_sell_reversal = (
            side.upper() in ("SELL", "SHORT")
            and change_1h >= 3.0
            and change_4h >= 5.0
        )

        if is_buy_reversal or is_sell_reversal:
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.REVERSAL_SIGNAL,
                priority=3,
                reason=(
                    f"Counter-trend {side}: 1h={change_1h:+.1f}%, "
                    f"4h={change_4h:+.1f}%, BTC={btc_trend}"
                ),
            ))

    def _check_divergence(
        self,
        flagged: FlaggedSignal,
        strategy_signals: Dict[str, str],
        num_agree: int,
        total: int,
    ):
        """Flag when strategies strongly disagree."""
        if not strategy_signals:
            return

        sides = set(v.upper() for v in strategy_signals.values() if v)
        # If we have both BUY and SELL signals
        if len(sides) >= 2 and "BUY" in sides and "SELL" in sides:
            buy_count = sum(1 for v in strategy_signals.values() if v.upper() in ("BUY", "LONG"))
            sell_count = sum(1 for v in strategy_signals.values() if v.upper() in ("SELL", "SHORT"))

            if buy_count >= 2 and sell_count >= 2:
                flagged.flags.append(SignalFlag(
                    flag_type=FlagType.STRATEGY_DIVERGENCE,
                    priority=3,
                    reason=(
                        f"Strong divergence: {buy_count} bullish vs {sell_count} bearish "
                        f"({', '.join(f'{k}={v}' for k, v in strategy_signals.items())})"
                    ),
                    extra={"strategy_signals": strategy_signals},
                ))

    def _check_breakout(
        self,
        flagged: FlaggedSignal,
        volume_ratio: float,
        price_change_1h: float,
        atr_ratio: float,
    ):
        """Flag breakout setups (volume + price movement + volatility expansion)."""
        if volume_ratio >= 2.0 and abs(price_change_1h) >= 2.0 and atr_ratio >= 1.5:
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.BREAKOUT,
                priority=3,
                reason=(
                    f"Breakout: {volume_ratio:.1f}x volume, "
                    f"{price_change_1h:+.1f}% move, "
                    f"{atr_ratio:.1f}x ATR expansion"
                ),
            ))

    def _check_momentum(
        self,
        flagged: FlaggedSignal,
        volume_ratio: float,
        price_change_1h: float,
        oi_change_pct: float,
    ):
        """Flag strong momentum setups (price + volume + OI all aligned)."""
        if (abs(price_change_1h) >= 1.5
            and volume_ratio >= 1.5
            and oi_change_pct > 3.0):
            direction = "bullish" if price_change_1h > 0 else "bearish"
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.MOMENTUM_SURGE,
                priority=2,
                reason=(
                    f"Momentum surge ({direction}): price {price_change_1h:+.1f}%, "
                    f"vol {volume_ratio:.1f}x, OI +{oi_change_pct:.1f}%"
                ),
            ))

    def _check_squeeze(
        self,
        flagged: FlaggedSignal,
        funding_rate: float,
        oi_change_pct: float,
        price_change_1h: float,
    ):
        """Flag potential short/long squeeze setups."""
        # Short squeeze: deeply negative funding + price starting to rise + OI declining
        is_short_squeeze = (
            funding_rate < -0.02
            and price_change_1h > 0.5
            and oi_change_pct < -2.0
        )
        # Long squeeze: deeply positive funding + price starting to fall + OI declining
        is_long_squeeze = (
            funding_rate > 0.02
            and price_change_1h < -0.5
            and oi_change_pct < -2.0
        )

        if is_short_squeeze:
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.SQUEEZE_SETUP,
                priority=3,
                reason=(
                    f"Short squeeze: funding {funding_rate:+.4f}, "
                    f"price +{price_change_1h:.1f}%, OI {oi_change_pct:+.1f}%"
                ),
            ))
        elif is_long_squeeze:
            flagged.flags.append(SignalFlag(
                flag_type=FlagType.SQUEEZE_SETUP,
                priority=3,
                reason=(
                    f"Long squeeze: funding {funding_rate:+.4f}, "
                    f"price {price_change_1h:.1f}%, OI {oi_change_pct:+.1f}%"
                ),
            ))

    def _record_flags(self, flagged: FlaggedSignal):
        """Record flagging event for statistics."""
        for f in flagged.flags:
            ft = f.flag_type.value
            self._flag_counts[ft] = self._flag_counts.get(ft, 0) + 1

        self._flag_history.append({
            "ts": time.time(),
            "symbol": flagged.symbol,
            "side": flagged.side,
            "confidence": flagged.confidence,
            "flags": [f.flag_type.value for f in flagged.flags],
            "max_priority": flagged.max_priority,
            "trigger_llm": flagged.should_trigger_llm,
        })

        # Cap history
        if len(self._flag_history) > 500:
            self._flag_history = self._flag_history[-500:]

        if flagged.should_trigger_llm:
            logger.info(
                f"[FLAGGER] {flagged.symbol} {flagged.side}: "
                f"{flagged.flag_summary} -> TRIGGER LLM"
            )
        else:
            logger.debug(
                f"[FLAGGER] {flagged.symbol} {flagged.side}: "
                f"{flagged.flag_summary}"
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get flagging statistics."""
        return {
            "total_flagged": len(self._flag_history),
            "flag_counts": self._flag_counts,
            "llm_triggered": sum(1 for h in self._flag_history if h.get("trigger_llm")),
            "recent": self._flag_history[-10:],
        }


# Module-level singleton
_flagger: Optional[SignalFlagger] = None


def get_signal_flagger() -> SignalFlagger:
    """Get the singleton SignalFlagger."""
    global _flagger
    if _flagger is None:
        _flagger = SignalFlagger()
    return _flagger
