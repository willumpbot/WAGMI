"""
TIER 4.2: Mechanical Bot Memory Units

Stores and recalls patterns of mechanical bot behavior.

Why: The mechanical bot is a sophisticated black box generating signals.
To build complementary LLM signals, we must:
1. Record EVERY decision the mechanical bot makes
2. Extract PATTERNS from those decisions
3. Identify WHEN the bot acts, WHY it acts, and HOW OFTEN it wins
4. Learn the bot's EDGE and BLIND SPOTS
5. Synthesize complementary signals in gaps where bot doesn't trade

Memory units:
- Signal Memory: Every signal generated (winning/losing)
- Pattern Memory: Recurring mechanical bot behaviors
- Failure Memory: When bot fires incorrectly (false signals)
- Success Memory: Bot's most reliable setups (highest win rate)
- State Memory: Mechanical bot's internal state evolution during trade lifecycle
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict
import time

logger = logging.getLogger("bot.llm.mechanical_bot_memory")


@dataclass
class MechanicalBotSignal:
    """Complete record of one mechanical bot signal."""
    signal_id: str
    symbol: str
    timestamp: float

    # What did the bot see?
    regime: str
    volatility_percentile: float
    alignment_score: float
    btc_correlation: float
    time_of_day: int

    # What did the bot do?
    side: str  # BUY or SELL
    confidence: float  # 0-100
    num_strategies_voting: int
    strategy_names: List[str] = field(default_factory=list)

    # How did it execute?
    entry_price: float = 0.0
    leverage: float = 1.0
    position_size: float = 0.0

    # What was the outcome?
    executed: bool = False
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_time_minutes: Optional[float] = None

    # Classification
    outcome: Optional[str] = None  # WIN, LOSS, BREAKEVEN
    setup_type: str = ""  # (regime, volatility_level, alignment_level, time_of_day_period)


@dataclass
class MechanicalBotPattern:
    """Recurring pattern in mechanical bot behavior."""
    pattern_id: str
    regime: str
    volatility_level: str  # "low", "medium", "high", "extreme"
    alignment_threshold: float  # >= this alignment score
    btc_correlation_range: Tuple[float, float]  # correlation range when bot fires
    time_of_day_preference: List[int]  # hours when bot prefers to trade

    # Performance metrics
    occurrences: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0

    # Confidence metrics
    avg_signal_confidence: float = 0.0
    avg_strategy_agreement: int = 0

    # Recommendations
    llm_action: str = "normal"  # "boost" (size_up), "normal", "avoid", "sell_opposite"


@dataclass
class MechanicalBotFailure:
    """Record of when mechanical bot generated losing signals."""
    failure_id: str
    signal: MechanicalBotSignal

    # Why did it fail?
    failure_mode: str  # "early_entry", "wrong_direction", "whipsaw", "black_swan"
    contributing_factors: Dict[str, Any] = field(default_factory=dict)

    # What happened?
    max_drawdown: Optional[float] = None
    exit_reason: str = ""  # "sl_hit", "tp_hit", "manual_close"

    # How to prevent?
    prevention_signal: str = ""  # Counter-thesis that would have stopped this
    timestamp: float = field(default_factory=time.time)


@dataclass
class MechanicalBotSuccess:
    """Record of when mechanical bot excelled."""
    success_id: str
    signal: MechanicalBotSignal

    # What made it work?
    success_factors: Dict[str, Any] = field(default_factory=dict)

    # How exceptional was it?
    multiple_of_atr: float = 0.0  # Win size as multiple of ATR
    percentile_rank: float = 0.0  # Top X% of wins

    # Replicability
    is_repeatable: bool = False  # Can we see this pattern again?
    pattern_recurrence_freq: str = ""  # "daily", "hourly", "rare"

    timestamp: float = field(default_factory=time.time)


class MechanicalBotMemoryUnit:
    """
    Stores and recalls mechanical bot patterns.
    """

    def __init__(self, data_dir: str = "data/llm"):
        self.data_dir = data_dir
        self.memory_dir = os.path.join(data_dir, "mechanical_bot_memory")
        os.makedirs(self.memory_dir, exist_ok=True)

        # Signal memory
        self.signals: Dict[str, MechanicalBotSignal] = {}
        self.signals_file = os.path.join(self.memory_dir, "signals.jsonl")

        # Pattern memory
        self.patterns: Dict[str, MechanicalBotPattern] = {}
        self.patterns_file = os.path.join(self.memory_dir, "patterns.jsonl")

        # Failure memory
        self.failures: Dict[str, MechanicalBotFailure] = {}
        self.failures_file = os.path.join(self.memory_dir, "failures.jsonl")

        # Success memory
        self.successes: Dict[str, MechanicalBotSuccess] = {}
        self.successes_file = os.path.join(self.memory_dir, "successes.jsonl")

        # Statistics
        self.stats = {
            "total_signals": 0,
            "signals_executed": 0,
            "execution_rate": 0.0,
            "win_rate": 0.0,
            "total_wins": 0,
            "total_losses": 0,
            "total_pnl": 0.0,
            "patterns_discovered": 0,
            "failures_logged": 0,
            "successes_logged": 0,
        }

        # Load existing data
        self._load_memory()

    def record_signal(\n        self,
        signal_id: str,
        symbol: str,
        regime: str,
        volatility_percentile: float,
        alignment_score: float,
        btc_correlation: float,
        time_of_day: int,
        side: str,
        confidence: float,
        num_strategies: int,
        strategy_names: List[str],
        entry_price: float,
        leverage: float = 1.0,
        position_size: float = 0.0,
    ) -> MechanicalBotSignal:
        """Record a mechanical bot signal."""
        signal = MechanicalBotSignal(
            signal_id=signal_id,
            symbol=symbol,
            timestamp=time.time(),
            regime=regime,
            volatility_percentile=volatility_percentile,
            alignment_score=alignment_score,
            btc_correlation=btc_correlation,
            time_of_day=time_of_day,
            side=side,
            confidence=confidence,
            num_strategies_voting=num_strategies,
            strategy_names=strategy_names,
            entry_price=entry_price,
            leverage=leverage,
            position_size=position_size,
        )

        self.signals[signal_id] = signal
        self.stats["total_signals"] += 1

        # Classify setup
        signal.setup_type = self._classify_setup(signal)

        # Persist
        self._save_signal(signal)

        return signal

    def record_signal_outcome(
        self,
        signal_id: str,
        executed: bool,
        exit_price: Optional[float],
        pnl: Optional[float],
        pnl_pct: Optional[float],
        hold_time_minutes: Optional[float],
    ) -> None:
        """Record outcome of a signal."""
        if signal_id not in self.signals:
            logger.warning(f"Signal {signal_id} not found in memory")
            return

        signal = self.signals[signal_id]
        signal.executed = executed
        signal.exit_price = exit_price
        signal.pnl = pnl
        signal.pnl_pct = pnl_pct
        signal.hold_time_minutes = hold_time_minutes

        # Determine outcome
        if pnl is not None:
            if pnl > 0:
                signal.outcome = "WIN"
                self.stats["total_wins"] += 1
            elif pnl < 0:
                signal.outcome = "LOSS"
                self.stats["total_losses"] += 1
            else:
                signal.outcome = "BREAKEVEN"

            self.stats["total_pnl"] += pnl

        if executed:
            self.stats["signals_executed"] += 1

        # Update rates
        if self.stats["total_signals"] > 0:
            self.stats["execution_rate"] = self.stats["signals_executed"] / self.stats["total_signals"]
        if self.stats["signals_executed"] > 0:
            self.stats["win_rate"] = self.stats["total_wins"] / self.stats["signals_executed"]

        # Classify as success or failure
        if executed and signal.outcome == "WIN":
            self._record_success(signal)
        elif executed and signal.outcome == "LOSS":
            self._record_failure(signal)

        # Update patterns
        self._update_pattern_for_signal(signal)

        # Persist
        self._save_signal(signal)

    def get_signal(self, signal_id: str) -> Optional[MechanicalBotSignal]:
        """Retrieve signal from memory."""
        return self.signals.get(signal_id)

    def get_signals_by_symbol(self, symbol: str, limit: int = 100) -> List[MechanicalBotSignal]:
        """Get recent signals for a symbol."""
        relevant = [s for s in self.signals.values() if s.symbol == symbol]
        # Sort by timestamp descending, take most recent
        return sorted(relevant, key=lambda s: s.timestamp, reverse=True)[:limit]

    def get_signals_by_setup(self, setup_type: str) -> List[MechanicalBotSignal]:
        """Get all signals of a particular setup type."""
        return [s for s in self.signals.values() if s.setup_type == setup_type]

    def get_signals_by_regime(self, regime: str) -> List[MechanicalBotSignal]:
        """Get all signals in a regime."""
        return [s for s in self.signals.values() if s.regime == regime]

    def get_patterns(self) -> Dict[str, MechanicalBotPattern]:
        """Get all discovered patterns."""
        return self.patterns

    def get_pattern(self, pattern_id: str) -> Optional[MechanicalBotPattern]:
        """Get specific pattern."""
        return self.patterns.get(pattern_id)

    def get_top_patterns(self, top_n: int = 10) -> List[MechanicalBotPattern]:
        """Get patterns ranked by frequency and win rate."""
        patterns = list(self.patterns.values())
        # Score = win_rate * occurrences (frequency + accuracy)
        patterns.sort(
            key=lambda p: (p.win_rate * p.occurrences) if p.occurrences > 0 else 0,
            reverse=True
        )
        return patterns[:top_n]

    def get_failures(self) -> List[MechanicalBotFailure]:
        """Get all failure records."""
        return list(self.failures.values())

    def get_successes(self) -> List[MechanicalBotSuccess]:
        """Get all success records."""
        return list(self.successes.values())

    def get_memory_report(self) -> Dict[str, Any]:
        """Get comprehensive memory report."""
        win_list = [s for s in self.signals.values() if s.outcome == "WIN"]
        loss_list = [s for s in self.signals.values() if s.outcome == "LOSS"]

        avg_hold_time = None
        if win_list:
            hold_times = [s.hold_time_minutes for s in win_list if s.hold_time_minutes]
            if hold_times:
                avg_hold_time = sum(hold_times) / len(hold_times)

        return {
            "signal_metrics": {
                "total_signals": self.stats["total_signals"],
                "executed": self.stats["signals_executed"],
                "execution_rate": f"{self.stats['execution_rate']:.1%}",
                "wins": self.stats["total_wins"],
                "losses": self.stats["total_losses"],
                "win_rate": f"{self.stats['win_rate']:.1%}",
                "total_pnl": f"${self.stats['total_pnl']:.2f}",
                "avg_win": f"${sum(s.pnl for s in win_list if s.pnl) / len(win_list):.2f}" if win_list else "N/A",
                "avg_loss": f"${sum(s.pnl for s in loss_list if s.pnl) / len(loss_list):.2f}" if loss_list else "N/A",
                "avg_hold_time_min": f"{avg_hold_time:.0f}" if avg_hold_time else "N/A",
            },
            "pattern_metrics": {
                "patterns_discovered": len(self.patterns),
                "top_pattern": (
                    {
                        "regime": self.get_top_patterns(1)[0].regime,
                        "win_rate": f"{self.get_top_patterns(1)[0].win_rate:.1%}",
                        "occurrences": self.get_top_patterns(1)[0].occurrences,
                    }
                    if self.get_top_patterns(1)
                    else None
                ),
            },
            "failure_metrics": {
                "failures_logged": len(self.failures),
                "most_common_failure_mode": (
                    max(
                        set(f.failure_mode for f in self.failures.values()),
                        key=lambda x: sum(1 for f in self.failures.values() if f.failure_mode == x),
                    )
                    if self.failures
                    else None
                ),
            },
            "success_metrics": {
                "successes_logged": len(self.successes),
                "repeatable_patterns": sum(1 for s in self.successes.values() if s.is_repeatable),
            },
        }

    def _classify_setup(self, signal: MechanicalBotSignal) -> str:
        """Classify signal into setup type."""
        vol_level = (
            "extreme" if signal.volatility_percentile > 80
            else "high" if signal.volatility_percentile > 60
            else "medium" if signal.volatility_percentile > 30
            else "low"
        )

        align_level = (
            "strong" if signal.alignment_score > 0.7
            else "weak" if signal.alignment_score < 0.3
            else "medium"
        )

        hour_period = (
            "asia" if 0 <= signal.time_of_day < 8
            else "europe" if 8 <= signal.time_of_day < 16
            else "us"
        )

        return f"{signal.regime}_{vol_level}_{align_level}_{hour_period}"

    def _update_pattern_for_signal(self, signal: MechanicalBotSignal) -> None:
        """Update pattern statistics for this signal."""
        pattern_key = self._get_pattern_key(signal)

        if pattern_key not in self.patterns:
            self.patterns[pattern_key] = MechanicalBotPattern(
                pattern_id=pattern_key,
                regime=signal.regime,
                volatility_level=(
                    "extreme" if signal.volatility_percentile > 80
                    else "high" if signal.volatility_percentile > 60
                    else "medium" if signal.volatility_percentile > 30
                    else "low"
                ),
                alignment_threshold=max(0.0, signal.alignment_score - 0.1),
                btc_correlation_range=(signal.btc_correlation - 0.1, signal.btc_correlation + 0.1),
                time_of_day_preference=[signal.time_of_day],
            )
            self.stats["patterns_discovered"] += 1

        pattern = self.patterns[pattern_key]
        pattern.occurrences += 1

        if signal.outcome == "WIN":
            pattern.wins += 1
        elif signal.outcome == "LOSS":
            pattern.losses += 1

        # Update metrics
        if pattern.occurrences > 0:
            pattern.win_rate = pattern.wins / pattern.occurrences

        if signal.pnl is not None:
            pattern.total_pnl += signal.pnl
            pattern.avg_pnl = pattern.total_pnl / pattern.occurrences

        pattern.avg_signal_confidence = (
            pattern.avg_signal_confidence * (pattern.occurrences - 1) / pattern.occurrences
            + signal.confidence / pattern.occurrences
        )

        pattern.avg_strategy_agreement = int(
            pattern.avg_strategy_agreement * (pattern.occurrences - 1) / pattern.occurrences
            + signal.num_strategies_voting / pattern.occurrences
        )

        # Recommend action
        if pattern.win_rate > 0.65 and pattern.occurrences >= 5:
            pattern.llm_action = "boost"
        elif pattern.win_rate < 0.40 and pattern.occurrences >= 5:
            pattern.llm_action = "avoid"
        else:
            pattern.llm_action = "normal"

        # Save pattern
        self._save_pattern(pattern)

    def _record_success(self, signal: MechanicalBotSignal) -> None:
        """Record a successful signal."""
        success = MechanicalBotSuccess(
            success_id=f"success_{signal.signal_id}",
            signal=signal,
        )

        # Analyze what made it work
        success.success_factors = {
            "regime": signal.regime,
            "alignment_score": signal.alignment_score,
            "btc_correlation": signal.btc_correlation,
            "strategies_voting": signal.num_strategies_voting,
            "time_of_day": signal.time_of_day,
        }

        self.successes[success.success_id] = success
        self.stats["successes_logged"] += 1
        self._save_success(success)

    def _record_failure(self, signal: MechanicalBotSignal) -> None:
        """Record a failed signal."""
        # Classify failure mode
        failure_mode = "unknown"
        if signal.pnl_pct is not None:
            if signal.pnl_pct < -5:
                failure_mode = "black_swan"
            elif signal.hold_time_minutes and signal.hold_time_minutes < 2:
                failure_mode = "whipsaw"
            else:
                failure_mode = "wrong_direction"

        failure = MechanicalBotFailure(
            failure_id=f"failure_{signal.signal_id}",
            signal=signal,
            failure_mode=failure_mode,
            contributing_factors={
                "regime": signal.regime,
                "alignment_score": signal.alignment_score,
                "confidence": signal.confidence,
                "btc_correlation": signal.btc_correlation,
            },
        )

        self.failures[failure.failure_id] = failure
        self.stats["failures_logged"] += 1
        self._save_failure(failure)

    def _get_pattern_key(self, signal: MechanicalBotSignal) -> str:
        """Generate pattern key for grouping."""
        vol_level = (
            "extreme" if signal.volatility_percentile > 80
            else "high" if signal.volatility_percentile > 60
            else "medium" if signal.volatility_percentile > 30
            else "low"
        )

        align_level = (
            "strong" if signal.alignment_score > 0.7
            else "weak" if signal.alignment_score < 0.3
            else "medium"
        )

        return f"{signal.regime}_{vol_level}_{align_level}"

    def _save_signal(self, signal: MechanicalBotSignal) -> None:
        """Persist signal to disk."""
        try:
            with open(self.signals_file, "a") as f:
                data = asdict(signal)
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save signal: {e}")

    def _save_pattern(self, pattern: MechanicalBotPattern) -> None:
        """Persist pattern to disk."""
        try:
            with open(self.patterns_file, "a") as f:
                data = asdict(pattern)
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save pattern: {e}")

    def _save_failure(self, failure: MechanicalBotFailure) -> None:
        """Persist failure to disk."""
        try:
            with open(self.failures_file, "a") as f:
                data = {
                    "failure_id": failure.failure_id,
                    "signal_id": failure.signal.signal_id,
                    "symbol": failure.signal.symbol,
                    "failure_mode": failure.failure_mode,
                    "pnl": failure.signal.pnl,
                    "timestamp": failure.timestamp,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save failure: {e}")

    def _save_success(self, success: MechanicalBotSuccess) -> None:
        """Persist success to disk."""
        try:
            with open(self.successes_file, "a") as f:
                data = {
                    "success_id": success.success_id,
                    "signal_id": success.signal.signal_id,
                    "symbol": success.signal.symbol,
                    "pnl": success.signal.pnl,
                    "hold_time_minutes": success.signal.hold_time_minutes,
                    "timestamp": success.timestamp,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save success: {e}")

    def _load_memory(self) -> None:
        """Load existing memory from disk."""
        try:
            if os.path.exists(self.signals_file):
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            # Reconstruct signal
                            signal = MechanicalBotSignal(**data)
                            self.signals[signal.signal_id] = signal
                        except Exception as e:
                            logger.debug(f"Error loading signal: {e}")
        except Exception as e:
            logger.debug(f"Error loading signals: {e}")


# Global memory unit
_global_memory: Optional[MechanicalBotMemoryUnit] = None


def get_mechanical_bot_memory() -> MechanicalBotMemoryUnit:
    """Get or create global memory unit."""
    global _global_memory
    if _global_memory is None:
        _global_memory = MechanicalBotMemoryUnit()
    return _global_memory
