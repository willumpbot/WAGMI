"""
TIER 4.3: Mechanical Bot Analysis Engine

Analyzes mechanical bot memory to extract patterns, insights, and recommendations.

Purpose:
- Understand mechanical bot's edge (where it wins)
- Identify blind spots (where it loses or doesn't trade)
- Find gaps (market conditions where bot doesn't trade but should)
- Generate LLM complement signals to cover gaps
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict

from mechanical_bot_memory import get_mechanical_bot_memory, MechanicalBotSignal, MechanicalBotPattern

logger = logging.getLogger("bot.llm.mechanical_bot_analyzer")


@dataclass
class PatternQualityScore:
    """Quality assessment of a mechanical bot pattern."""
    pattern_id: str
    win_rate: float
    confidence: float  # How sure are we about this pattern?
    sample_size: int
    edge_score: float  # Frequency * win_rate * avg_pnl
    repeatability: float  # How often does this pattern recur?
    consistency: float  # How reliable is this pattern?
    recommendation: str  # "strong_edge", "mild_edge", "neutral", "weak_edge", "avoid"


@dataclass
class MechanicalBotEdge:
    """Mechanical bot's genuine alpha."""
    edge_name: str
    condition: str  # What market condition triggers this edge?
    patterns: List[str]  # Pattern IDs that express this edge
    total_pnl: float
    win_rate: float
    sample_size: int
    consistency_score: float  # How reliable?
    is_time_dependent: bool  # Does it vary by time of day?
    is_regime_dependent: bool  # Does it vary by regime?


@dataclass
class MechanicalBotGap:
    """Opportunity for LLM to generate complementary signals."""
    gap_id: str
    description: str  # What opportunity is being missed?
    condition: str  # When does this occur?
    expected_frequency: str  # How often does this happen?

    # What if we traded here?
    potential_pnl: float  # Estimated based on similar conditions
    confidence_in_estimate: float

    # How to fill the gap?
    suggested_setup: str
    suggested_side: str  # BUY or SELL
    similarity_to_bot_patterns: float  # 0-1, how similar to what bot already trades?


@dataclass
class BotBehaviorAnalysis:
    """Complete analysis of mechanical bot behavior."""
    total_signals: int
    execution_rate: float
    win_rate: float
    total_pnl: float

    # Breakdown by regime
    regime_performance: Dict[str, Dict]  # regime -> {win_rate, count, pnl}

    # Breakdown by time of day
    time_of_day_performance: Dict[int, Dict]  # hour -> {win_rate, count, pnl}

    # Top edges
    top_edges: List[MechanicalBotEdge]

    # Identified gaps
    identified_gaps: List[MechanicalBotGap]

    # Failure analysis
    most_common_failures: List[Tuple[str, int]]  # (failure_mode, count)

    # Recommendations
    recommendations: List[str]


class MechanicalBotAnalyzer:
    """
    Analyzes mechanical bot patterns and generates insights.
    """

    def __init__(self):
        self.memory = get_mechanical_bot_memory()
        self.min_pattern_samples = 5  # Minimum trades to consider pattern valid

    def analyze_all_patterns(self) -> List[PatternQualityScore]:
        """Analyze quality of all discovered patterns."""
        patterns = list(self.memory.patterns.values())

        if not patterns:
            return []

        scores = []
        for pattern in patterns:
            if pattern.occurrences < self.min_pattern_samples:
                continue  # Skip patterns with insufficient data

            # Calculate confidence in pattern
            confidence = min(1.0, pattern.occurrences / 20.0)

            # Edge score: frequency * win_rate * avg_pnl
            edge_score = (
                (pattern.occurrences / max(1, len(self.memory.signals)))
                * pattern.win_rate
                * abs(pattern.avg_pnl)
            )

            # Repeatability: how often does this pattern show up?
            repeatability = min(1.0, pattern.occurrences / 10.0)

            # Consistency: low standard deviation in outcomes
            # (simpler version: just win_rate closeness to extremes)
            consistency = (
                1.0 if pattern.win_rate > 0.65
                else 0.8 if pattern.win_rate > 0.55
                else 0.6 if pattern.win_rate > 0.45
                else 0.3
            )

            # Recommendation
            if pattern.win_rate > 0.65 and pattern.occurrences >= 5:
                recommendation = "strong_edge"
            elif pattern.win_rate > 0.55 and pattern.occurrences >= 5:
                recommendation = "mild_edge"
            elif pattern.win_rate > 0.45:
                recommendation = "neutral"
            elif pattern.win_rate < 0.35:
                recommendation = "avoid"
            else:
                recommendation = "weak_edge"

            score = PatternQualityScore(
                pattern_id=pattern.pattern_id,
                win_rate=pattern.win_rate,
                confidence=confidence,
                sample_size=pattern.occurrences,
                edge_score=edge_score,
                repeatability=repeatability,
                consistency=consistency,
                recommendation=recommendation,
            )
            scores.append(score)

        # Sort by edge score
        scores.sort(key=lambda s: s.edge_score, reverse=True)
        return scores

    def identify_mechanical_bot_edges(self, top_n: int = 5) -> List[MechanicalBotEdge]:
        """Identify mechanical bot's genuine alpha sources."""
        pattern_scores = self.analyze_all_patterns()

        if not pattern_scores:
            return []

        edges = []
        for score in pattern_scores[:top_n]:
            if score.recommendation in ["strong_edge", "mild_edge"]:
                pattern = self.memory.patterns.get(score.pattern_id)
                if not pattern:
                    continue

                # Determine if edge varies by time
                signals_for_pattern = self._get_signals_matching_pattern(pattern)
                hours = [s.time_of_day for s in signals_for_pattern]
                time_variance = len(set(hours)) / 24.0 if hours else 0.5
                is_time_dependent = time_variance > 0.5

                edge = MechanicalBotEdge(
                    edge_name=f"Edge_{score.pattern_id}",
                    condition=f"{pattern.regime} regime, {pattern.volatility_level} volatility, {pattern.alignment_threshold:.2f}+ alignment",
                    patterns=[score.pattern_id],
                    total_pnl=pattern.total_pnl,
                    win_rate=pattern.win_rate,
                    sample_size=pattern.occurrences,
                    consistency_score=score.consistency,
                    is_time_dependent=is_time_dependent,
                    is_regime_dependent=True,  # All patterns are regime-dependent by design
                )
                edges.append(edge)

        return edges

    def identify_gaps(self, top_n: int = 5) -> List[MechanicalBotGap]:
        """Identify market conditions where LLM should trade but bot doesn't."""
        # Get all market conditions that bot has seen
        all_signals = list(self.memory.signals.values())

        if not all_signals:
            return []

        # Group by regime/vol/alignment/time
        condition_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})

        for signal in all_signals:
            key = (signal.regime, self._classify_vol(signal.volatility_percentile))
            condition_stats[key]["count"] += 1
            if signal.outcome == "WIN":
                condition_stats[key]["wins"] += 1
            if signal.pnl:
                condition_stats[key]["pnl"] += signal.pnl

        gaps = []

        # Gap type 1: High-win-rate conditions with low trading frequency
        for (regime, vol_level), stats in condition_stats.items():
            if stats["count"] >= self.min_pattern_samples:
                win_rate = stats["wins"] / stats["count"]

                # If win rate is high but we don't trade often, that's a gap
                if win_rate > 0.60 and stats["count"] < 3:
                    gap = MechanicalBotGap(
                        gap_id=f"gap_low_freq_{regime}_{vol_level}",
                        description=f"High-probability {regime} regime with {vol_level} volatility: bot rarely trades here",
                        condition=f"{regime} regime, {vol_level} vol",
                        expected_frequency="rare",
                        potential_pnl=stats["pnl"],
                        confidence_in_estimate=0.6,
                        suggested_setup=f"{regime}_{vol_level}_trigger",
                        suggested_side="neutral",  # Will be determined by LLM
                        similarity_to_bot_patterns=0.7,
                    )
                    gaps.append(gap)

        # Gap type 2: Time-of-day gaps (bot trades mostly during US hours, miss other times)
        us_hour_signals = [s for s in all_signals if 14 <= s.time_of_day <= 21]  # EST market hours
        other_hour_signals = [s for s in all_signals if not (14 <= s.time_of_day <= 21)]

        if other_hour_signals and us_hour_signals:
            us_win_rate = len([s for s in us_hour_signals if s.outcome == "WIN"]) / len(us_hour_signals) if us_hour_signals else 0
            other_win_rate = len([s for s in other_hour_signals if s.outcome == "WIN"]) / len(other_hour_signals) if other_hour_signals else 0

            # If other hours have comparable or better win rate but less volume
            if other_win_rate >= us_win_rate * 0.9 and len(other_hour_signals) < len(us_hour_signals):
                gap = MechanicalBotGap(
                    gap_id="gap_time_of_day",
                    description=f"Off-peak hours (non-US): bot trades less but has {other_win_rate:.0%} win rate",
                    condition="Outside US market hours",
                    expected_frequency="continuous",
                    potential_pnl=sum(s.pnl for s in other_hour_signals if s.pnl),
                    confidence_in_estimate=0.7,
                    suggested_setup="time_aware_trigger",
                    suggested_side="neutral",
                    similarity_to_bot_patterns=0.8,
                )
                gaps.append(gap)

        return gaps[:top_n]

    def get_regime_performance(self) -> Dict[str, Dict]:
        """Analyze bot performance by regime."""
        signals_by_regime = defaultdict(list)

        for signal in self.memory.signals.values():
            signals_by_regime[signal.regime].append(signal)

        performance = {}
        for regime, signals in signals_by_regime.items():
            wins = len([s for s in signals if s.outcome == "WIN"])
            losses = len([s for s in signals if s.outcome == "LOSS"])
            pnl = sum(s.pnl for s in signals if s.pnl)

            performance[regime] = {
                "count": len(signals),
                "win_rate": wins / len(signals) if signals else 0.0,
                "wins": wins,
                "losses": losses,
                "total_pnl": pnl,
                "avg_pnl": pnl / len(signals) if signals else 0.0,
                "avg_confidence": sum(s.confidence for s in signals) / len(signals) if signals else 0.0,
            }

        return performance

    def get_time_of_day_performance(self) -> Dict[int, Dict]:
        """Analyze bot performance by time of day."""
        signals_by_hour = defaultdict(list)

        for signal in self.memory.signals.values():
            signals_by_hour[signal.time_of_day].append(signal)

        performance = {}
        for hour, signals in signals_by_hour.items():
            wins = len([s for s in signals if s.outcome == "WIN"])
            losses = len([s for s in signals if s.outcome == "LOSS"])
            pnl = sum(s.pnl for s in signals if s.pnl)

            performance[hour] = {
                "count": len(signals),
                "win_rate": wins / len(signals) if signals else 0.0,
                "total_pnl": pnl,
                "avg_confidence": sum(s.confidence for s in signals) / len(signals) if signals else 0.0,
            }

        return performance

    def get_failure_analysis(self) -> List[Tuple[str, int]]:
        """Analyze failure modes."""
        failures = self.memory.get_failures()

        failure_counts = defaultdict(int)
        for failure in failures:
            failure_counts[failure.failure_mode] += 1

        # Sort by frequency
        return sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)

    def get_comprehensive_analysis(self) -> BotBehaviorAnalysis:
        """Get complete analysis of bot behavior."""
        stats = self.memory.stats

        analysis = BotBehaviorAnalysis(
            total_signals=stats["total_signals"],
            execution_rate=stats["execution_rate"],
            win_rate=stats["win_rate"],
            total_pnl=stats["total_pnl"],
            regime_performance=self.get_regime_performance(),
            time_of_day_performance=self.get_time_of_day_performance(),
            top_edges=self.identify_mechanical_bot_edges(top_n=5),
            identified_gaps=self.identify_gaps(top_n=5),
            most_common_failures=self.get_failure_analysis(),
            recommendations=self._generate_recommendations(),
        )

        return analysis

    def _get_signals_matching_pattern(self, pattern) -> List[MechanicalBotSignal]:
        """Get signals that match a pattern."""
        matching = []
        for signal in self.memory.signals.values():
            if (
                signal.regime == pattern.regime
                and signal.alignment_score >= pattern.alignment_threshold
                and pattern.btc_correlation_range[0] <= signal.btc_correlation <= pattern.btc_correlation_range[1]
            ):
                matching.append(signal)
        return matching

    def _classify_vol(self, vol_pct: float) -> str:
        """Classify volatility level."""
        if vol_pct > 80:
            return "extreme"
        elif vol_pct > 60:
            return "high"
        elif vol_pct > 30:
            return "medium"
        else:
            return "low"

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations for LLM based on analysis."""
        recommendations = []

        # Analyze execution rate
        if self.memory.stats["execution_rate"] < 0.1:
            recommendations.append("Bot has very low execution rate - consider synthesizing additional signals")

        # Analyze win rate
        if self.memory.stats["win_rate"] < 0.4:
            recommendations.append("Win rate is below 50% - focus on quality over quantity")
        elif self.memory.stats["win_rate"] > 0.65:
            recommendations.append("Bot has strong win rate - focus on amplifying these setups")

        # Analyze regimes
        regime_perf = self.get_regime_performance()
        worst_regime = min(regime_perf.items(), key=lambda x: x[1]["win_rate"], default=None)
        if worst_regime and worst_regime[1]["win_rate"] < 0.35:
            recommendations.append(f"Consider extra caution in {worst_regime[0]} regime (only {worst_regime[1]['win_rate']:.0%} win rate)")

        return recommendations


# Global analyzer
_global_analyzer: Optional[MechanicalBotAnalyzer] = None


def get_mechanical_bot_analyzer() -> MechanicalBotAnalyzer:
    """Get or create global analyzer."""
    global _global_analyzer
    if _global_analyzer is None:
        _global_analyzer = MechanicalBotAnalyzer()
    return _global_analyzer
