"""Opportunist Agent — discovers repeatable patterns and proposes new setups.

Scans historical trades to identify winning patterns, missed opportunities, and
regime-specific edges. Proposes new patterns for ensemble integration.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class OpportunityProposal:
    """A discovered trading pattern proposal."""

    pattern_name: str  # "post-liquidation-cascade-reversal"
    setup_description: str  # Clear explanation of the pattern
    backtest_wr: float  # Win rate from historical analysis (0-1)
    sample_size: int  # Number of trades matching this pattern
    confidence: float  # Robustness score (0-1)
    proposed_action: str  # "add_to_ensemble" or "alert_only"
    evidence: List[str]  # ["18 trades in trending_bull", "79% WR on BTC/ETH"]
    discovered_date: str  # ISO format timestamp
    regime_specific: bool  # Whether pattern is regime-dependent
    applicable_symbols: List[str]  # Which symbols does this work for?
    applicable_regimes: List[str]  # Which regimes does this work in?


class OpportunistAgent:
    """Discover and propose new trading patterns from historical data."""

    def __init__(
        self,
        decisions_path: str = "bot/data/llm/decisions.jsonl",
        proposals_path: str = "bot/data/llm/proposals.jsonl",
    ):
        self.decisions_path = Path(decisions_path)
        self.proposals_path = Path(proposals_path)
        self._decisions_cache = None
        self._proposals_cache = None

    def discover_patterns(
        self,
        lookback_trades: int = 100,
        min_confidence: float = 0.65,
    ) -> List[OpportunityProposal]:
        """Scan trade history for repeatable winning patterns.

        Args:
            lookback_trades: Number of recent trades to analyze
            min_confidence: Minimum confidence threshold for proposals

        Returns:
            List of OpportunityProposal objects meeting confidence threshold
        """
        decisions = self._load_decisions()
        if not decisions or len(decisions) < 10:
            return []

        # Take last N trades
        recent_trades = decisions[-lookback_trades:] if len(decisions) > lookback_trades else decisions

        proposals = []

        # Pattern 1: Regime + n_agree consistency
        patterns_by_setup = defaultdict(lambda: {"wins": 0, "losses": 0, "trades": []})
        for decision in recent_trades:
            regime = decision.get("regime", "unknown")
            n_agree = decision.get("n_agree", 0)
            symbol = decision.get("symbol", "unknown")
            action = decision.get("action", "")
            confidence = decision.get("confidence", 0.0)

            setup_key = f"{regime}+{n_agree}-agree"
            patterns_by_setup[setup_key]["trades"].append(
                {"symbol": symbol, "action": action, "confidence": confidence}
            )

            if action == "go":
                patterns_by_setup[setup_key]["wins"] += 1
            else:
                patterns_by_setup[setup_key]["losses"] += 1

        # Evaluate each pattern
        for setup_key, stats in patterns_by_setup.items():
            total = stats["wins"] + stats["losses"]
            if total < 5:  # Minimum sample size
                continue

            win_rate = stats["wins"] / total if total > 0 else 0.0
            if win_rate < 0.60:  # Below 60% WR, not interesting
                continue

            # Extract regime and n_agree
            parts = setup_key.split("+")
            regime = parts[0]
            n_agree = int(parts[1][0]) if len(parts) > 1 else 0

            # Analyze symbols and regimes
            symbols = set(t["symbol"] for t in stats["trades"])
            winning_symbols = [
                t["symbol"]
                for t in stats["trades"]
                if self._is_winning_trade(recent_trades, t)
            ]

            confidence_score = self._score_confidence(
                sample_size=total, win_rate=win_rate, pattern_variance=0.2
            )

            if confidence_score >= min_confidence:
                proposal = OpportunityProposal(
                    pattern_name=f"high_agreement_{regime}_{n_agree}way",
                    setup_description=f"{regime} regime with {n_agree}-strategy agreement: {win_rate:.1%} WR across {total} trades",
                    backtest_wr=win_rate,
                    sample_size=total,
                    confidence=confidence_score,
                    proposed_action="add_to_ensemble" if confidence_score > 0.80 else "alert_only",
                    evidence=[
                        f"{stats['wins']} wins, {stats['losses']} losses",
                        f"Works on: {', '.join(sorted(set(winning_symbols))[:3])}",
                        f"Regime consistency: {regime}",
                    ],
                    discovered_date=datetime.utcnow().isoformat(),
                    regime_specific=True,
                    applicable_symbols=list(symbols),
                    applicable_regimes=[regime],
                )
                proposals.append(proposal)

        # Pattern 2: Symbol + regime combination
        symbol_regime_patterns = defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0})
        for decision in recent_trades:
            symbol = decision.get("symbol", "unknown")
            regime = decision.get("regime", "unknown")
            action = decision.get("action", "")

            key = f"{symbol}_{regime}"
            symbol_regime_patterns[key]["count"] += 1

            if action == "go":
                symbol_regime_patterns[key]["wins"] += 1
            else:
                symbol_regime_patterns[key]["losses"] += 1

        for key, stats in symbol_regime_patterns.items():
            if stats["count"] < 8:
                continue

            win_rate = stats["wins"] / stats["count"]
            if win_rate < 0.65:
                continue

            symbol, regime = key.rsplit("_", 1)
            confidence_score = self._score_confidence(
                sample_size=stats["count"], win_rate=win_rate, pattern_variance=0.15
            )

            if confidence_score >= min_confidence:
                proposal = OpportunityProposal(
                    pattern_name=f"symbol_regime_{symbol}_{regime}",
                    setup_description=f"{symbol} consistently profitable in {regime}: {win_rate:.1%} WR",
                    backtest_wr=win_rate,
                    sample_size=stats["count"],
                    confidence=confidence_score,
                    proposed_action="alert_only",
                    evidence=[
                        f"{stats['wins']} wins, {stats['losses']} losses",
                        f"Symbol: {symbol}, Regime: {regime}",
                    ],
                    discovered_date=datetime.utcnow().isoformat(),
                    regime_specific=True,
                    applicable_symbols=[symbol],
                    applicable_regimes=[regime],
                )
                proposals.append(proposal)

        return proposals

    def backtest_proposal(
        self,
        proposal: OpportunityProposal,
        lookback_days: int = 30,
    ) -> OpportunityProposal:
        """Walk-forward backtest proposal on recent data.

        Args:
            proposal: The proposal to validate
            lookback_days: Days of data to use for backtest

        Returns:
            Updated proposal with backtest results
        """
        decisions = self._load_decisions()
        if not decisions:
            return proposal

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        matching_trades = []

        for decision in decisions:
            ts_str = decision.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            # Check if decision matches proposal criteria
            if self._matches_proposal(decision, proposal):
                matching_trades.append(decision)

        if not matching_trades:
            return proposal

        wins = sum(1 for t in matching_trades if t.get("action") == "go")
        total = len(matching_trades)

        # Update backtest results
        proposal.backtest_wr = wins / total if total > 0 else proposal.backtest_wr
        proposal.sample_size = total

        return proposal

    def score_confidence(self, proposal: OpportunityProposal) -> float:
        """Score robustness of proposal.

        Factors:
        - Sample size (more is better, but diminishing returns)
        - Win rate consistency (stable > volatile)
        - Out-of-sample validation

        Args:
            proposal: The proposal to score

        Returns:
            Confidence score (0-1)
        """
        return self._score_confidence(
            sample_size=proposal.sample_size,
            win_rate=proposal.backtest_wr,
            pattern_variance=0.2,
        )

    def save_proposals(self, proposals: List[OpportunityProposal]) -> None:
        """Save accepted proposals to proposals.jsonl.

        Args:
            proposals: List of proposals to save
        """
        if not proposals:
            return

        # Create parent directory if needed
        self.proposals_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.proposals_path, "a") as f:
                for proposal in proposals:
                    f.write(json.dumps(asdict(proposal)) + "\n")
            logger.info(f"Saved {len(proposals)} proposals to {self.proposals_path}")
        except Exception as e:
            logger.error(f"Failed to save proposals: {e}")

    # Private helper methods

    def _load_decisions(self) -> List[Dict[str, Any]]:
        """Load all decision entries from JSONL."""
        if self._decisions_cache is not None:
            return self._decisions_cache

        self._decisions_cache = []
        if not self.decisions_path.exists():
            logger.warning(f"Decisions file not found: {self.decisions_path}")
            return self._decisions_cache

        try:
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        self._decisions_cache.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to load decisions: {e}")

        return self._decisions_cache

    def _is_winning_trade(self, trades: List[Dict], trade: Dict) -> bool:
        """Check if a trade was winning."""
        return trade.get("action") == "go"

    def _matches_proposal(
        self, decision: Dict[str, Any], proposal: OpportunityProposal
    ) -> bool:
        """Check if a decision matches the proposal criteria."""
        symbol = decision.get("symbol", "unknown")
        regime = decision.get("regime", "unknown")

        return (
            symbol in proposal.applicable_symbols
            and regime in proposal.applicable_regimes
        )

    def _score_confidence(
        self,
        sample_size: int,
        win_rate: float,
        pattern_variance: float = 0.2,
    ) -> float:
        """Compute robustness confidence score.

        Args:
            sample_size: Number of trades in pattern
            win_rate: Win rate of pattern (0-1)
            pattern_variance: Variance in the pattern (lower = more stable)

        Returns:
            Confidence score (0-1)
        """
        # Base score from win rate (capped at 0.5)
        win_rate_score = min(win_rate * 0.5, 0.5)

        # Sample size bonus (diminishing returns, capped at 0.35)
        # 10 trades = 0.2, 30 trades = 0.3, 100+ trades = 0.35
        sample_score = min(0.2 + (sample_size - 10) / 100 * 0.15, 0.35)

        # Variance penalty (more variance = lower confidence)
        variance_penalty = pattern_variance * 0.1

        confidence = max(0.0, win_rate_score + sample_score - variance_penalty)
        return min(1.0, confidence)  # Clamp to 0-1


def get_opportunist_agent() -> OpportunistAgent:
    """Get or create an Opportunist Agent instance."""
    return OpportunistAgent()
