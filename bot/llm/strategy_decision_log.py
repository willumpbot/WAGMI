"""
TIER 4.1b: Strategy Decision Log

Deep monitoring of each strategy's internal reasoning.

Instead of just logging final signals, log:
- What data each strategy saw
- What decision it made
- Why it made that decision
- How confident it was

This reveals:
- Regime_trend's regime classification logic
- Multi_tier_quality's multi-timeframe analysis
- Confidence_scorer's factor weighting
- Why a strategy sometimes fires, sometimes doesn't

With this, we can:
- Identify patterns in strategy behavior
- Learn what triggers high-confidence signals
- Understand failure modes
- Possibly improve or clone strategies in LLM
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import time

logger = logging.getLogger("bot.llm.strategy_decision_log")


@dataclass
class StrategyState:
    """Complete state of a strategy for one symbol at one time."""
    strategy_name: str
    symbol: str
    timestamp: float

    # Input data
    current_price: float = 0.0
    regime: Optional[str] = None  # Strategy's view of regime
    volatility: Optional[float] = None
    time_of_day: Optional[int] = None

    # Internal calculations (strategy-specific)
    internal_state: Dict[str, Any] = None  # Whatever the strategy calculates

    # Decision
    signal_generated: bool = False
    signal_side: Optional[str] = None  # BUY or SELL
    signal_confidence: float = 0.0
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None

    # Reasoning
    reasoning: str = ""  # Why did it fire?
    factors: Dict[str, float] = None  # Factor scores that contributed


class StrategyDecisionLog:
    """
    Logs detailed decision-making for each strategy.
    """

    def __init__(self, output_dir: str = "data/llm"):
        self.output_dir = output_dir
        self.log_file = os.path.join(output_dir, "strategy_decisions.jsonl")
        os.makedirs(output_dir, exist_ok=True)

        # In-memory recent decisions
        self.recent_decisions: List[StrategyState] = []

        # Per-strategy tracking
        self.strategy_stats = {}

    def log_strategy_decision(
        self,
        strategy_name: str,
        symbol: str,
        current_price: float,
        regime: Optional[str],
        volatility: Optional[float],
        time_of_day: Optional[int],
        internal_state: Dict[str, Any],
        signal_generated: bool,
        signal_side: Optional[str],
        signal_confidence: float,
        entry: Optional[float],
        sl: Optional[float],
        tp1: Optional[float],
        reasoning: str = "",
        factors: Optional[Dict[str, float]] = None,
    ) -> StrategyState:
        """
        Log a strategy's decision for a symbol.
        """
        state = StrategyState(
            strategy_name=strategy_name,
            symbol=symbol,
            timestamp=time.time(),
            current_price=current_price,
            regime=regime,
            volatility=volatility,
            time_of_day=time_of_day,
            internal_state=internal_state or {},
            signal_generated=signal_generated,
            signal_side=signal_side,
            signal_confidence=signal_confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            reasoning=reasoning,
            factors=factors or {},
        )

        self.recent_decisions.append(state)
        if len(self.recent_decisions) > 1000:
            self.recent_decisions = self.recent_decisions[-1000:]

        # Update stats
        if strategy_name not in self.strategy_stats:
            self.strategy_stats[strategy_name] = {
                "total_evaluations": 0,
                "signals_generated": 0,
                "avg_confidence": 0.0,
                "confidence_sum": 0.0,
            }

        stats = self.strategy_stats[strategy_name]
        stats["total_evaluations"] += 1
        if signal_generated:
            stats["signals_generated"] += 1
        stats["confidence_sum"] += signal_confidence
        stats["avg_confidence"] = stats["confidence_sum"] / stats["total_evaluations"]

        # Persist
        self._save_decision(state)

        return state

    def get_strategy_analysis(self, strategy_name: str) -> Dict[str, Any]:
        """
        Analyze a strategy's behavior from recent decisions.

        Returns patterns in its decision-making.
        """
        relevant = [d for d in self.recent_decisions[-500:] if d.strategy_name == strategy_name]

        if not relevant:
            return {"status": "no_data"}

        # Signal generation rate
        signal_rate = sum(1 for d in relevant if d.signal_generated) / len(relevant) if relevant else 0

        # Avg confidence when firing
        firing_decisions = [d for d in relevant if d.signal_generated]
        avg_firing_confidence = sum(d.signal_confidence for d in firing_decisions) / len(firing_decisions) if firing_decisions else 0

        # Regime preference (when does it fire?)
        regimes_when_firing = {}
        for d in firing_decisions:
            regime = d.regime or "unknown"
            regimes_when_firing[regime] = regimes_when_firing.get(regime, 0) + 1

        regime_preference = {
            regime: f"{count / len(firing_decisions):.0%}" if firing_decisions else "0%"
            for regime, count in regimes_when_firing.items()
        }

        # Common factors in decisions
        all_factors = {}
        for d in relevant:
            for factor, value in (d.factors or {}).items():
                if factor not in all_factors:
                    all_factors[factor] = []
                all_factors[factor].append(value)

        avg_factors = {
            factor: sum(values) / len(values)
            for factor, values in all_factors.items()
        }

        return {
            "strategy": strategy_name,
            "total_evaluations": len(relevant),
            "signal_generation_rate": f"{signal_rate:.0%}",
            "avg_confidence_when_firing": f"{avg_firing_confidence:.0%}",
            "regime_preference": regime_preference,
            "average_factors": {k: round(v, 2) for k, v in avg_factors.items()},
        }

    def compare_strategies(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Compare strategies' behavior.

        Which strategy fires most? Least confident? Most reliable?
        """
        if symbols:
            relevant = [d for d in self.recent_decisions[-500:] if d.symbol in symbols]
        else:
            relevant = self.recent_decisions[-500:]

        by_strategy = {}
        for decision in relevant:
            strategy = decision.strategy_name
            if strategy not in by_strategy:
                by_strategy[strategy] = {
                    "evaluations": 0,
                    "signals": 0,
                    "confidences": [],
                }

            by_strategy[strategy]["evaluations"] += 1
            if decision.signal_generated:
                by_strategy[strategy]["signals"] += 1
            by_strategy[strategy]["confidences"].append(decision.signal_confidence)

        # Summarize
        summary = {}
        for strategy, data in by_strategy.items():
            summary[strategy] = {
                "evaluation_rate": f"{data['evaluations'] / len(relevant):.0%}" if relevant else "0%",
                "signal_rate": f"{data['signals'] / data['evaluations']:.0%}" if data['evaluations'] > 0 else "0%",
                "avg_confidence": f"{sum(data['confidences']) / len(data['confidences']):.0%}" if data['confidences'] else "0%",
                "min_confidence": f"{min(data['confidences']):.0%}" if data['confidences'] else "0%",
                "max_confidence": f"{max(data['confidences']):.0%}" if data['confidences'] else "0%",
            }

        return summary

    def identify_high_confidence_patterns(self, min_confidence: float = 0.75) -> List[Dict]:
        """
        Identify patterns in high-confidence signals.

        When a strategy fires with 75%+ confidence, what's common?
        """
        high_conf = [d for d in self.recent_decisions[-500:] if d.signal_generated and d.signal_confidence >= min_confidence]

        if not high_conf:
            return []

        # Group by strategy
        by_strategy = {}
        for d in high_conf:
            strategy = d.strategy_name
            if strategy not in by_strategy:
                by_strategy[strategy] = []
            by_strategy[strategy].append(d)

        patterns = []
        for strategy, decisions in by_strategy.items():
            # Find common factors
            common_factors = {}
            for d in decisions:
                for factor, value in (d.factors or {}).items():
                    if factor not in common_factors:
                        common_factors[factor] = []
                    common_factors[factor].append(value)

            # Find factors that are consistently high/low
            strong_factors = {}
            for factor, values in common_factors.items():
                avg = sum(values) / len(values)
                if abs(avg) > 0.5:  # Strong signal
                    strong_factors[factor] = round(avg, 2)

            patterns.append({
                "strategy": strategy,
                "high_confidence_signals": len(decisions),
                "common_factors": strong_factors,
                "avg_regime": max(
                    set([d.regime for d in decisions]),
                    key=[d.regime for d in decisions].count
                ) if decisions else "unknown",
            })

        return patterns

    def _save_decision(self, state: StrategyState) -> None:
        """Persist decision to disk."""
        try:
            with open(self.log_file, "a") as f:
                data = {
                    "strategy": state.strategy_name,
                    "symbol": state.symbol,
                    "timestamp": state.timestamp,
                    "regime": state.regime,
                    "signal_generated": state.signal_generated,
                    "signal_side": state.signal_side,
                    "signal_confidence": state.signal_confidence,
                    "reasoning": state.reasoning,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save strategy decision: {e}")


# Global log
_global_log: Optional[StrategyDecisionLog] = None


def get_strategy_decision_log() -> StrategyDecisionLog:
    """Get or create global log."""
    global _global_log
    if _global_log is None:
        _global_log = StrategyDecisionLog()
    return _global_log
