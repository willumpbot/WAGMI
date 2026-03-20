"""
TIER 1: Setup Profitability Analysis

Identifies which setup types (entry patterns) generate the most profit.
Uses: frequency × win_rate × avg_winner formula.

Key insight: 20% of setups often generate 80% of profit.
This enables: size up high-edge setups, reduce/avoid low-edge ones.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("bot.llm.setup_profitability")


@dataclass
class SetupMetrics:
    """Profitability metrics for a setup type."""
    setup_type: str
    frequency: int              # How many times did this setup occur?
    win_rate: float             # What % were winners?
    total_trades: int           # Total trades with this setup
    wins: int                   # Number of wins
    losses: int                 # Number of losses
    total_pnl: float           # Total PnL from this setup
    avg_winner: float          # Average PnL on winning trades
    avg_loser: float           # Average PnL on losing trades
    avg_pnl_per_trade: float   # Overall average PnL

    # Edge metrics
    edge_score: float          # frequency × win_rate × avg_winner (profit potential)
    confidence: float          # Statistical confidence (higher n = higher confidence)

    # Recommendation
    action: str                # "size_up" | "normal" | "size_down" | "avoid"
    reasoning: str             # Why this recommendation?


class SetupProfitabilityAnalyzer:
    """Analyze which setups are profitable."""

    def __init__(self, deep_memory):
        """
        Args:
            deep_memory: TradeDeNA manager with access to trades
        """
        self.deep_memory = deep_memory

    def analyze_all_setups(self, min_trades: int = 5) -> Dict[str, SetupMetrics]:
        """
        Analyze profitability of all setup types.

        Args:
            min_trades: Only analyze setups with at least this many trades

        Returns:
            Dict mapping setup_type → SetupMetrics
        """
        # Get win rates by entry_type from deep_memory
        entry_type_stats = self.deep_memory.get_win_rate_by("entry_type")

        # Load full trade DNA to calculate average winners/losers
        self.deep_memory._ensure_loaded()
        trades = self.deep_memory._trades

        # Build detailed setup analysis
        results = {}

        for setup_type, stats in entry_type_stats.items():
            if setup_type == "unknown":
                continue

            total = stats.get("total", 0)
            if total < min_trades:
                continue

            wins = stats.get("wins", 0)
            losses = total - wins
            win_rate = stats.get("win_rate", 0)
            total_pnl = stats.get("pnl", 0)

            # Get average winner and loser amounts
            setup_trades = [t for t in trades if t.get("entry_type") == setup_type]
            winners = [t.get("pnl", 0) for t in setup_trades if t.get("outcome") == "WIN"]
            losers = [t.get("pnl", 0) for t in setup_trades if t.get("outcome") == "LOSS"]

            avg_winner = sum(winners) / len(winners) if winners else 0
            avg_loser = sum(losers) / len(losers) if losers else 0
            avg_pnl = total_pnl / total if total > 0 else 0

            # Edge score: how much total profit does this setup generate?
            # Formula: frequency (as %) × win_rate × avg_winner
            frequency_pct = total / len(trades) if trades else 0
            edge_score = frequency_pct * win_rate * avg_winner if avg_winner > 0 else 0

            # Statistical confidence: more trades = higher confidence
            # Simple: min(trades / 50, 1.0)
            confidence = min(total / 50.0, 1.0)

            # Recommendation logic
            action, reasoning = self._get_recommendation(
                win_rate=win_rate,
                total=total,
                edge_score=edge_score,
                avg_winner=avg_winner,
                avg_loser=avg_loser
            )

            results[setup_type] = SetupMetrics(
                setup_type=setup_type,
                frequency=total,
                win_rate=win_rate,
                total_trades=total,
                wins=wins,
                losses=losses,
                total_pnl=total_pnl,
                avg_winner=avg_winner,
                avg_loser=avg_loser,
                avg_pnl_per_trade=avg_pnl,
                edge_score=edge_score,
                confidence=confidence,
                action=action,
                reasoning=reasoning,
            )

        return results

    def get_high_edge_setups(self, top_n: int = 5, min_confidence: float = 0.5) -> List[SetupMetrics]:
        """Get highest-edge setups (size up on these)."""
        all_setups = self.analyze_all_setups()
        high_edge = [
            s for s in all_setups.values()
            if s.confidence >= min_confidence and s.action == "size_up"
        ]
        high_edge.sort(key=lambda x: x.edge_score, reverse=True)
        return high_edge[:top_n]

    def get_low_edge_setups(self, top_n: int = 5, min_confidence: float = 0.5) -> List[SetupMetrics]:
        """Get lowest-edge or negative-edge setups (avoid these)."""
        all_setups = self.analyze_all_setups()
        low_edge = [
            s for s in all_setups.values()
            if s.confidence >= min_confidence and s.action in ["size_down", "avoid"]
        ]
        low_edge.sort(key=lambda x: x.edge_score)  # Ascending (worst first)
        return low_edge[:top_n]

    def get_setup_recommendation(self, setup_type: str) -> Optional[SetupMetrics]:
        """Get profitability metrics and recommendation for a specific setup."""
        all_setups = self.analyze_all_setups()
        return all_setups.get(setup_type)

    def get_summary_report(self) -> Dict[str, Any]:
        """Generate comprehensive summary report."""
        all_setups = self.analyze_all_setups()

        if not all_setups:
            return {"status": "insufficient_data", "message": "Not enough trades to analyze"}

        # Rank by edge score
        ranked = sorted(all_setups.values(), key=lambda x: x.edge_score, reverse=True)

        # Calculate total profit from top 20%
        top_20_count = max(1, len(ranked) // 5)
        top_20_pnl = sum(s.total_pnl for s in ranked[:top_20_count])
        total_pnl = sum(s.total_pnl for s in ranked)
        top_20_contribution = (top_20_pnl / total_pnl * 100) if total_pnl > 0 else 0

        return {
            "total_setup_types": len(all_setups),
            "total_trades_analyzed": sum(s.total_trades for s in ranked),
            "overall_win_rate": sum(s.wins for s in ranked) / sum(s.total_trades for s in ranked) if ranked else 0,
            "total_pnl": total_pnl,
            "top_edge_setups": [
                {
                    "setup": s.setup_type,
                    "frequency": s.frequency,
                    "win_rate": f"{s.win_rate:.1%}",
                    "avg_winner": f"${s.avg_winner:+.2f}",
                    "edge_score": f"{s.edge_score:.2f}",
                    "action": s.action,
                    "total_pnl": f"${s.total_pnl:+.2f}",
                }
                for s in ranked[:5]
            ],
            "worst_edge_setups": [
                {
                    "setup": s.setup_type,
                    "frequency": s.frequency,
                    "win_rate": f"{s.win_rate:.1%}",
                    "avg_loser": f"${s.avg_loser:.2f}",
                    "edge_score": f"{s.edge_score:.2f}",
                    "action": s.action,
                    "total_pnl": f"${s.total_pnl:+.2f}",
                }
                for s in ranked[-5:]
            ],
            "pareto_analysis": {
                "top_20_percent_of_setups": top_20_count,
                "top_20_percent_pnl": f"${top_20_pnl:+.2f}",
                "contribution_percent": f"{top_20_contribution:.1f}%",
                "message": f"Top {top_20_count} setups generate {top_20_contribution:.1f}% of profit"
            }
        }

    @staticmethod
    def _get_recommendation(
        win_rate: float,
        total: int,
        edge_score: float,
        avg_winner: float,
        avg_loser: float
    ) -> tuple[str, str]:
        """Determine action recommendation based on metrics."""

        # Avoid: win rate < 40% or negative expectation
        if win_rate < 0.40 or (win_rate * avg_winner + (1 - win_rate) * avg_loser) < 0:
            return "avoid", f"Low WR {win_rate:.1%} or negative expectation"

        # Size down: win rate 40-50% (marginal)
        if win_rate < 0.50:
            return "size_down", f"Marginal WR {win_rate:.1%}, reduce position size"

        # Normal: win rate 50-60%
        if win_rate < 0.60:
            return "normal", f"Solid WR {win_rate:.1%}, standard sizing"

        # Size up: win rate 60%+ with positive edge score
        if win_rate >= 0.60 and edge_score > 0:
            return "size_up", f"Strong WR {win_rate:.1%}, size up 1.3-1.5x"

        return "normal", "Standard setup"


# Integration with feedback loop
def integrate_setup_profitability_into_decision(
    setup_type: str,
    analyzer: SetupProfitabilityAnalyzer,
    base_size: float
) -> tuple[float, str]:
    """
    Apply setup profitability recommendation to position sizing.

    Args:
        setup_type: The entry_type/setup classification
        analyzer: SetupProfitabilityAnalyzer instance
        base_size: Base position size in USD

    Returns:
        (adjusted_size, recommendation)
    """
    metrics = analyzer.get_setup_recommendation(setup_type)

    if not metrics:
        return base_size, "unknown_setup"

    multipliers = {
        "avoid": 0.0,
        "size_down": 0.6,
        "normal": 1.0,
        "size_up": 1.4,
    }

    multiplier = multipliers.get(metrics.action, 1.0)
    adjusted_size = base_size * multiplier

    return adjusted_size, metrics.action
