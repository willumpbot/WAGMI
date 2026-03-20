"""
TIER 1.4: Hypothesis Auto-Ranking

Ranks active trading hypotheses by estimated profit potential.

Insight: Not all hypotheses are equally valuable. By ranking them by profit
impact (frequency × edge × sample_size), we can:
  1. Focus LLM attention on high-impact ideas
  2. Allocate testing resources to promising leads
  3. Identify and kill low-potential ideas early

Formula for profit impact score:
  score = frequency_pct × estimated_edge × min(sample_size, 100) / 100

Expected impact: +0.2-0.3% by optimizing which ideas get tested and refined.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time

logger = logging.getLogger("bot.llm.hypothesis_ranker")


@dataclass
class HypothesisMetrics:
    """Metrics for ranking a hypothesis."""
    hypothesis_id: str              # Unique ID for this hypothesis
    name: str                       # Human-readable name
    description: str                # What is this idea testing?

    # Performance metrics
    sample_size: int                # Number of times tested
    wins: int                       # Successful tests
    losses: int                     # Failed tests
    total_pnl: float               # Total PnL from tests
    win_rate: float                # wins / sample_size
    avg_pnl_per_test: float        # total_pnl / sample_size

    # Ranking metrics
    estimated_edge: float           # Estimated edge per test (%)
    frequency_pct: float            # How often does opportunity occur? (%)
    confidence: float               # How confident in estimate? (0-1)
    profit_impact_score: float     # Ranking metric (higher = better)

    # Lifecycle
    created_at: float              # When was hypothesis created?
    last_tested: float             # When was it last evaluated?
    status: str                    # "active" | "graduated" | "killed" | "pending"
    reasoning: str                 # Why this ranking?


class HypothesisRanker:
    """
    Ranks active hypotheses by estimated profit potential.

    Integrates with self_teaching.py to get hypothesis metrics,
    then scores and ranks them for resource allocation.
    """

    def __init__(self):
        """Initialize the ranker."""
        self.hypotheses: Dict[str, HypothesisMetrics] = {}
        self.ranking_history: List[List[HypothesisMetrics]] = []

    def add_hypothesis(
        self,
        hypothesis_id: str,
        name: str,
        description: str,
        estimated_edge: float = 1.0,
        frequency_pct: float = 10.0,
    ) -> HypothesisMetrics:
        """
        Add a new hypothesis to track.

        Args:
            hypothesis_id: Unique identifier
            name: Human-readable name
            description: What is this testing?
            estimated_edge: Expected profit per test (%)
            frequency_pct: How often does opportunity occur? (%)

        Returns:
            HypothesisMetrics object
        """
        now = time.time()
        metrics = HypothesisMetrics(
            hypothesis_id=hypothesis_id,
            name=name,
            description=description,
            sample_size=0,
            wins=0,
            losses=0,
            total_pnl=0.0,
            win_rate=0.0,
            avg_pnl_per_test=0.0,
            estimated_edge=estimated_edge,
            frequency_pct=frequency_pct,
            confidence=0.5,  # Initial confidence
            profit_impact_score=0.0,
            created_at=now,
            last_tested=now,
            status="pending",  # Pending first test
            reasoning="Newly created hypothesis",
        )
        self.hypotheses[hypothesis_id] = metrics
        logger.info(f"[HYPOTHESIS] Added '{name}': {description}")
        return metrics

    def record_test_result(
        self,
        hypothesis_id: str,
        outcome: bool,  # True = win, False = loss
        pnl: float = 0.0,
    ) -> None:
        """
        Record a test result for a hypothesis.

        Args:
            hypothesis_id: Which hypothesis was tested
            outcome: True (win) or False (loss)
            pnl: Profit/loss from this test
        """
        if hypothesis_id not in self.hypotheses:
            logger.warning(f"[HYPOTHESIS] Unknown hypothesis: {hypothesis_id}")
            return

        m = self.hypotheses[hypothesis_id]
        m.sample_size += 1
        m.last_tested = time.time()
        m.total_pnl += pnl

        if outcome:
            m.wins += 1
        else:
            m.losses += 1

        # Update derived metrics
        m.win_rate = m.wins / m.sample_size if m.sample_size > 0 else 0.0
        m.avg_pnl_per_test = m.total_pnl / m.sample_size if m.sample_size > 0 else 0.0

        # Update confidence: more samples = higher confidence
        m.confidence = min(
            0.95,
            (m.sample_size / 10.0) * 0.5  # Cap at 0.95
        )

        # Update status
        if m.sample_size >= 20 and m.win_rate < 0.40:
            m.status = "killed"  # Kill low-performing hypotheses
        elif m.sample_size >= 10 and m.win_rate > 0.60:
            m.status = "graduated"  # Promote high-performing ones
        elif m.sample_size < 5:
            m.status = "pending"  # Still gathering data
        else:
            m.status = "active"  # Under active testing

    def _calculate_profit_impact_score(
        self,
        win_rate: float,
        frequency_pct: float,
        sample_size: int,
        avg_pnl: float,
    ) -> float:
        """
        Calculate profit impact score for ranking.

        Formula:
          - Base: frequency_pct × (win_rate - 0.5) × avg_pnl
          - Normalized by sample size (more data = higher confidence)
          - Capped at -1 to 1 for comparability

        Returns:
            Score from -1 (worst) to +1 (best)
        """
        if sample_size == 0:
            return 0.0

        # Edge: win_rate relative to 50% baseline
        edge = win_rate - 0.5  # -0.5 to +0.5

        # Frequency: opportunities per 100 signals
        freq_factor = frequency_pct / 100.0  # 0 to 1

        # PnL magnitude: how much does each test win/lose?
        # Cap to ±5% to prevent outliers dominating
        pnl_capped = min(5.0, max(-5.0, avg_pnl))

        # Confidence boost: more samples = trust the metrics more
        confidence_factor = min(1.0, sample_size / 20.0)

        # Score: edge × frequency × pnl × confidence
        score = edge * freq_factor * pnl_capped * (0.5 + confidence_factor * 0.5)

        return float(min(1.0, max(-1.0, score)))

    def rank_hypotheses(self) -> List[HypothesisMetrics]:
        """
        Rank all hypotheses by profit impact score.

        Returns:
            Sorted list (best first)
        """
        # Calculate profit impact score for each
        for hyp in self.hypotheses.values():
            hyp.profit_impact_score = self._calculate_profit_impact_score(
                win_rate=hyp.win_rate,
                frequency_pct=hyp.frequency_pct,
                sample_size=hyp.sample_size,
                avg_pnl=hyp.avg_pnl_per_test,
            )

            # Update reasoning
            if hyp.sample_size == 0:
                hyp.reasoning = "No test data yet"
            elif hyp.status == "graduated":
                hyp.reasoning = f"Graduated: {hyp.win_rate:.0%} WR, {hyp.total_pnl:+.2f} PnL"
            elif hyp.status == "killed":
                hyp.reasoning = f"Low edge: {hyp.win_rate:.0%} WR over {hyp.sample_size} tests"
            else:
                hyp.reasoning = f"{hyp.win_rate:.0%} WR on {hyp.sample_size} tests, edge={hyp.profit_impact_score:.3f}"

        # Sort by score
        ranked = sorted(
            self.hypotheses.values(),
            key=lambda x: x.profit_impact_score,
            reverse=True
        )

        # Record ranking in history
        self.ranking_history.append(ranked)
        if len(self.ranking_history) > 100:
            self.ranking_history = self.ranking_history[-100:]

        return ranked

    def get_top_hypotheses(self, top_n: int = 5) -> List[HypothesisMetrics]:
        """Get the top N hypotheses by profit impact."""
        ranked = self.rank_hypotheses()
        return ranked[:top_n]

    def get_low_potential_hypotheses(self, bottom_n: int = 3) -> List[HypothesisMetrics]:
        """Get the lowest-potential hypotheses (candidates for killing)."""
        ranked = self.rank_hypotheses()
        # Only consider hypotheses with sufficient data
        with_data = [h for h in ranked if h.sample_size >= 10]
        return list(reversed(with_data))[:bottom_n]

    def get_hypothesis(self, hypothesis_id: str) -> Optional[HypothesisMetrics]:
        """Get metrics for a specific hypothesis."""
        return self.hypotheses.get(hypothesis_id)

    def get_summary_report(self) -> Dict[str, Any]:
        """Get human-readable summary of all hypotheses."""
        ranked = self.rank_hypotheses()

        active = [h for h in ranked if h.status == "active"]
        graduated = [h for h in ranked if h.status == "graduated"]
        killed = [h for h in ranked if h.status == "killed"]
        pending = [h for h in ranked if h.status == "pending"]

        return {
            "total_hypotheses": len(self.hypotheses),
            "active_count": len(active),
            "graduated_count": len(graduated),
            "killed_count": len(killed),
            "pending_count": len(pending),
            "top_hypotheses": [
                {
                    "id": h.hypothesis_id,
                    "name": h.name,
                    "status": h.status,
                    "score": round(h.profit_impact_score, 3),
                    "win_rate": f"{h.win_rate:.0%}",
                    "sample_size": h.sample_size,
                    "avg_pnl": f"${h.avg_pnl_per_test:+.2f}",
                    "reasoning": h.reasoning,
                }
                for h in ranked[:10]
            ],
        }


# Global ranker instance
_global_ranker: Optional[HypothesisRanker] = None


def get_hypothesis_ranker() -> HypothesisRanker:
    """Get or create the global hypothesis ranker."""
    global _global_ranker
    if _global_ranker is None:
        _global_ranker = HypothesisRanker()
    return _global_ranker
