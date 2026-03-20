"""
TIER 4.7: Synthetic Signal Generation from Mechanical Bot Analysis

Generates complementary LLM signals in identified gaps where mechanical bot doesn't trade.

Why: Mechanical bot may be:
- Overly conservative (missing high-probability opportunities)
- Blind to certain market regimes/times
- Overly dependent on specific conditions

LLM can synthesize complementary signals by:
- Trading in identified gaps with similar setups
- Using different entry criteria to catch early movers
- Trading time windows mechanical bot avoids
- Providing counter-thesis to increase portfolio diversification
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

from mechanical_bot_analyzer import get_mechanical_bot_analyzer
from mechanical_bot_memory import get_mechanical_bot_memory
from strategies.base import Signal

logger = logging.getLogger("bot.llm.mechanical_bot_synthesis")


@dataclass
class SyntheticSignalIdea:
    """LLM signal idea based on gap analysis."""
    idea_id: str
    symbol: str
    side: str  # BUY or SELL

    # Why this signal?
    gap_description: str  # What gap does it fill?
    confidence: float  # 0-100
    rationale: str  # Why should we trade here?

    # How to execute?
    suggested_entry_price: float
    suggested_sl: float
    suggested_tp1: float
    suggested_leverage: float = 1.0

    # Risk/reward
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float = 0.0

    # How similar to mechanical bot's patterns?
    similarity_to_bot_patterns: float  # 0-1 (higher = more similar to what bot trades)
    diversification_value: float  # 0-1 (higher = more uncorrelated from bot)

    # Based on what analysis?
    source_gap_id: str = ""  # Which gap identified this?
    based_on_pattern: Optional[str] = None  # Which mechanical bot pattern inspired this?


@dataclass
class SyntheticSignalPlan:
    """Plan for synthetic signal generation."""
    plan_id: str
    timestamp: float

    # Strategy
    strategy_type: str  # "fill_gap", "diversify", "boost_edge", "contra_trade"
    target_gap: str  # Which gap are we filling?

    # Signal ideas
    signal_ideas: List[SyntheticSignalIdea] = None

    # Expected outcome
    expected_coverage: str  # What % of gap does this cover?
    expected_additional_trades_per_day: float = 0.0
    expected_win_rate: float = 0.0  # Estimated based on similar bot patterns

    # Tracking
    signals_generated: int = 0
    signals_executed: int = 0


class MechanicalBotSynthesizer:
    """
    Generates synthetic LLM signals based on mechanical bot gap analysis.
    """

    def __init__(self):
        self.analyzer = get_mechanical_bot_analyzer()
        self.memory = get_mechanical_bot_memory()

        # Track generated ideas
        self.synthetic_ideas: Dict[str, SyntheticSignalIdea] = {}

    def generate_gap_filling_signals(self, symbol: str, max_ideas: int = 5) -> List[SyntheticSignalIdea]:
        """
        Generate synthetic signals to fill identified gaps.

        Identifies gaps where mechanical bot doesn't trade but could.
        """
        gaps = self.analyzer.identify_gaps(top_n=max_ideas)

        if not gaps:
            logger.info("No identified gaps to fill")
            return []

        ideas = []

        for gap in gaps:
            # Create synthetic signal idea for this gap
            idea = self._synthesize_gap_filling_signal(symbol, gap)
            if idea:
                ideas.append(idea)
                self.synthetic_ideas[idea.idea_id] = idea

        return ideas

    def generate_diversification_signals(self, symbol: str) -> List[SyntheticSignalIdea]:
        """
        Generate signals that diversify away from mechanical bot's patterns.

        Finds patterns mechanical bot doesn't exploit and generates counter signals.
        """
        # Get mechanical bot's typical patterns
        patterns = self.memory.get_patterns()

        if not patterns:
            return []

        # Find opposite conditions
        ideas = []
        for pattern in list(patterns.values())[:5]:  # Top 5 patterns
            # Generate opposite signal
            opposite_side = "SELL" if pattern.regime == "trend" else "BUY"

            idea = SyntheticSignalIdea(
                idea_id=f"diversify_{pattern.pattern_id}",
                symbol=symbol,
                side=opposite_side,
                gap_description=f"Counter to mechanical bot's {pattern.regime} trend pattern",
                confidence=45.0,  # Lower confidence for counter signals
                rationale=f"Diversify by trading opposite of bot's {pattern.regime} bias",
                suggested_entry_price=0.0,  # Will be calculated per symbol
                suggested_sl=0.0,
                suggested_tp1=0.0,
                suggested_leverage=1.0,
                risk_amount=0.0,
                reward_amount=0.0,
                similarity_to_bot_patterns=0.3,  # Different from bot patterns
                diversification_value=0.8,  # High diversification
                source_gap_id=f"diversity_gap_{pattern.pattern_id}",
                based_on_pattern=pattern.pattern_id,
            )
            ideas.append(idea)
            self.synthetic_ideas[idea.idea_id] = idea

        return ideas

    def generate_edge_boosting_signals(self, symbol: str) -> List[SyntheticSignalIdea]:
        """
        Generate signals that amplify mechanical bot's identified edges.

        Adds size when conditions are very similar to high-win-rate patterns.
        """
        edges = self.analyzer.identify_mechanical_bot_edges(top_n=3)

        if not edges:
            return []

        ideas = []

        for edge in edges:
            # Create boosting signal based on edge
            idea = SyntheticSignalIdea(
                idea_id=f"boost_{edge.edge_name}",
                symbol=symbol,
                side="NEUTRAL",  # Will take same side as mechanical bot
                gap_description=f"Amplify mechanical bot's {edge.edge_name}",
                confidence=edge.win_rate * 100,  # Inherit bot's edge confidence
                rationale=f"Bot has {edge.win_rate:.0%} win rate in {edge.condition}. Amplify with additional sizing.",
                suggested_entry_price=0.0,
                suggested_sl=0.0,
                suggested_tp1=0.0,
                suggested_leverage=1.5,  # Slightly more aggressive than mechanical
                risk_amount=0.0,
                reward_amount=0.0,
                similarity_to_bot_patterns=0.95,  # Very similar to bot's edge
                diversification_value=0.1,  # Low diversification (very similar to bot)
                source_gap_id="edge_amplification",
                based_on_pattern=None,
            )
            ideas.append(idea)
            self.synthetic_ideas[idea.idea_id] = idea

        return ideas

    def generate_time_based_signals(self, symbol: str) -> List[SyntheticSignalIdea]:
        """
        Generate signals for time windows mechanical bot underexploits.

        Finds hours/sessions where bot trades infrequently but has good win rate.
        """
        time_perf = self.analyzer.get_time_of_day_performance()

        if not time_perf:
            return []

        ideas = []

        # Find underexploited high-win-rate times
        for hour, perf in time_perf.items():
            if perf["count"] < 2 and perf["win_rate"] > 0.55:  # Few trades but good win rate
                hour_period = (
                    "Asia" if 0 <= hour < 8
                    else "Europe" if 8 <= hour < 16
                    else "US" if 14 <= hour < 22
                    else "Off-Hours"
                )

                idea = SyntheticSignalIdea(
                    idea_id=f"time_based_{hour}h",
                    symbol=symbol,
                    side="NEUTRAL",  # Depends on market
                    gap_description=f"{hour_period} hours underexploited by bot (only {perf['count']} trades, {perf['win_rate']:.0%} WR)",
                    confidence=perf["win_rate"] * 100,
                    rationale=f"Bot rarely trades at {hour:02d}:00 but has {perf['win_rate']:.0%} win rate when it does.",
                    suggested_entry_price=0.0,
                    suggested_sl=0.0,
                    suggested_tp1=0.0,
                    suggested_leverage=1.0,
                    risk_amount=0.0,
                    reward_amount=0.0,
                    similarity_to_bot_patterns=0.6,
                    diversification_value=0.4,  # Moderate diversification (different time)
                    source_gap_id=f"time_gap_{hour}",
                    based_on_pattern=None,
                )
                ideas.append(idea)
                self.synthetic_ideas[idea.idea_id] = idea

        return ideas

    def generate_regime_specific_signals(self, symbol: str, current_regime: str) -> List[SyntheticSignalIdea]:
        """
        Generate signals optimized for current regime.

        If mechanical bot performs poorly in this regime, generate complementary signals.
        """
        regime_perf = self.analyzer.get_regime_performance()

        if current_regime not in regime_perf:
            return []

        perf = regime_perf[current_regime]

        # If bot struggles in this regime, generate different signals
        if perf["win_rate"] < 0.50 and perf["count"] > 2:
            idea = SyntheticSignalIdea(
                idea_id=f"regime_specific_{current_regime}",
                symbol=symbol,
                side="NEUTRAL",
                gap_description=f"Mechanical bot struggles in {current_regime} regime (only {perf['win_rate']:.0%} WR)",
                confidence=40.0,  # Lower confidence but different approach
                rationale=f"Bot underperforms in {current_regime}. Generate alternative signals with different criteria.",
                suggested_entry_price=0.0,
                suggested_sl=0.0,
                suggested_tp1=0.0,
                suggested_leverage=1.0,
                risk_amount=0.0,
                reward_amount=0.0,
                similarity_to_bot_patterns=0.2,  # Different approach
                diversification_value=0.9,  # High diversification
                source_gap_id=f"regime_gap_{current_regime}",
                based_on_pattern=None,
            )
            return [idea]

        return []

    def convert_idea_to_signal(self, idea: SyntheticSignalIdea, current_price: float) -> Optional[Signal]:
        """
        Convert synthetic signal idea to executable Signal object.
        """
        try:
            from strategies.base import Signal

            # Calculate entry/SL/TP1 based on current price
            if idea.suggested_entry_price == 0.0:
                # Auto-calculate based on current price + some offset
                if idea.side == "BUY":
                    entry = current_price * 0.999  # Slightly below
                    sl = entry * 0.97  # 3% below entry
                    tp1 = entry * 1.02  # 2% above entry
                else:
                    entry = current_price * 1.001  # Slightly above
                    sl = entry * 1.03  # 3% above entry
                    tp1 = entry * 0.98  # 2% below entry
            else:
                entry = idea.suggested_entry_price
                sl = idea.suggested_sl
                tp1 = idea.suggested_tp1

            # Calculate ATR-based TP2 (not provided by idea)
            atr_estimate = abs(entry - sl) * 0.5
            tp2 = entry + atr_estimate * 2 if idea.side == "BUY" else entry - atr_estimate * 2

            signal = Signal(
                strategy="llm_synthesis",
                symbol=idea.symbol,
                side=idea.side,
                confidence=idea.confidence,
                entry=entry,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                atr=abs(entry - sl),
            )

            # Add metadata
            signal.metadata = {
                "synthetic_idea_id": idea.idea_id,
                "gap_description": idea.gap_description,
                "rationale": idea.rationale,
                "based_on_gap": idea.source_gap_id,
                "bot_similarity": idea.similarity_to_bot_patterns,
                "diversification_value": idea.diversification_value,
            }

            return signal

        except Exception as e:
            logger.error(f"Error converting idea {idea.idea_id} to signal: {e}")
            return None

    def _synthesize_gap_filling_signal(self, symbol: str, gap) -> Optional[SyntheticSignalIdea]:
        """
        Synthesize a specific signal idea to fill a gap.
        """
        try:
            # Determine suggested side based on gap
            suggested_side = "BUY" if "high" in gap.description.lower() else "SELL"

            idea = SyntheticSignalIdea(
                idea_id=f"gap_fill_{gap.gap_id}",
                symbol=symbol,
                side=suggested_side,
                gap_description=gap.description,
                confidence=65.0,  # Moderate confidence for gap-filling signals
                rationale=f"Gap identified: {gap.description}. Trade with setup: {gap.suggested_setup}",
                suggested_entry_price=0.0,  # Will be calculated per symbol
                suggested_sl=0.0,
                suggested_tp1=0.0,
                suggested_leverage=1.0,
                risk_amount=0.0,
                reward_amount=0.0,
                similarity_to_bot_patterns=gap.similarity_to_bot_patterns,
                diversification_value=1.0 - gap.similarity_to_bot_patterns,
                source_gap_id=gap.gap_id,
                based_on_pattern=None,
            )

            return idea
        except Exception as e:
            logger.error(f"Error synthesizing gap signal: {e}")
            return None

    def get_synthesis_plan(self, symbol: str) -> SyntheticSignalPlan:
        """
        Generate comprehensive synthesis plan for a symbol.
        """
        from time import time

        plan = SyntheticSignalPlan(
            plan_id=f"plan_{symbol}_{int(time())}",
            timestamp=time(),
            strategy_type="comprehensive",
            target_gap="all_identified_gaps",
        )

        # Generate all types of synthetic signals
        all_ideas = []
        all_ideas.extend(self.generate_gap_filling_signals(symbol, max_ideas=3))
        all_ideas.extend(self.generate_edge_boosting_signals(symbol))
        all_ideas.extend(self.generate_time_based_signals(symbol))

        plan.signal_ideas = all_ideas
        plan.expected_additional_trades_per_day = len(all_ideas) * 0.5  # Rough estimate

        # Estimate win rate based on similarity to bot patterns
        if all_ideas:
            avg_similarity = sum(i.similarity_to_bot_patterns for i in all_ideas) / len(all_ideas)
            # Win rate inversely proportional to difference from bot
            plan.expected_win_rate = 0.50 + (avg_similarity * 0.15)

        return plan

    def get_synthesis_report(self) -> Dict[str, Any]:
        """
        Get report on all synthetic signals generated.
        """
        return {
            "total_ideas_generated": len(self.synthetic_ideas),
            "ideas_by_type": {
                "gap_filling": len([i for i in self.synthetic_ideas.values() if "gap_fill" in i.idea_id]),
                "boosting": len([i for i in self.synthetic_ideas.values() if "boost" in i.idea_id]),
                "time_based": len([i for i in self.synthetic_ideas.values() if "time_based" in i.idea_id]),
                "diversification": len([i for i in self.synthetic_ideas.values() if "diversify" in i.idea_id]),
            },
            "avg_confidence": sum(i.confidence for i in self.synthetic_ideas.values()) / len(self.synthetic_ideas) if self.synthetic_ideas else 0,
            "avg_bot_similarity": sum(i.similarity_to_bot_patterns for i in self.synthetic_ideas.values()) / len(self.synthetic_ideas) if self.synthetic_ideas else 0,
            "avg_diversification_value": sum(i.diversification_value for i in self.synthetic_ideas.values()) / len(self.synthetic_ideas) if self.synthetic_ideas else 0,
        }


# Global synthesizer
_global_synthesizer: Optional[MechanicalBotSynthesizer] = None


def get_mechanical_bot_synthesizer() -> MechanicalBotSynthesizer:
    """Get or create global synthesizer."""
    global _global_synthesizer
    if _global_synthesizer is None:
        _global_synthesizer = MechanicalBotSynthesizer()
    return _global_synthesizer
