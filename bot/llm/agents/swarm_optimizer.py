"""Swarm Optimizer Agent (W4-D) — Meta-learning agent parameter tuning.

Analyzes agent performance across regimes and setups, detects systematic biases,
and recommends prompt/threshold adjustments for improved accuracy.
"""

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class BiasType(str, Enum):
    """Types of systematic bias detected."""

    OVERCONFIDENT = "overconfident"
    UNDERCONFIDENT = "underconfident"
    REGIME_SPECIFIC = "regime_specific"
    SYMBOL_SPECIFIC = "symbol_specific"
    FAKEOUT_BLIND = "fakeout_blind"
    SUPPORT_BLIND = "support_blind"


@dataclass
class AgentTuningProposal:
    """Recommendation to tune an agent's prompts or thresholds."""

    agent_name: str
    bias_type: BiasType
    magnitude: float
    affected_regime: Optional[str] = None
    affected_symbol: Optional[str] = None
    recommendation: str = ""
    confidence: float = 0.0
    sample_size: int = 0
    detected_date: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


class SwarmOptimizer:
    """Meta-learning agent that optimizes other agents' parameters."""

    def __init__(
        self,
        thesis_tracker_path: str = "bot/data/llm/thesis_tracker.json",
        decisions_path: str = "bot/data/llm/decisions.jsonl",
        recommendations_path: str = "bot/data/llm/agent_tuning_recommendations.jsonl",
    ):
        self.thesis_tracker_path = Path(thesis_tracker_path)
        self.decisions_path = Path(decisions_path)
        self.recommendations_path = Path(recommendations_path)
        self._thesis_cache = None
        self._decisions_cache = None

    def analyze_agent_performance(self) -> Dict[str, List[AgentTuningProposal]]:
        """Analyze all agents' performance across regimes and propose tunings."""
        proposals_by_agent = {
            "regime": [],
            "trade": [],
            "risk": [],
            "critic": [],
        }

        trade_proposals = self._analyze_trade_agent()
        proposals_by_agent["trade"].extend(trade_proposals)

        risk_proposals = self._analyze_risk_agent()
        proposals_by_agent["risk"].extend(risk_proposals)

        critic_proposals = self._analyze_critic_agent()
        proposals_by_agent["critic"].extend(critic_proposals)

        regime_proposals = self._analyze_regime_agent()
        proposals_by_agent["regime"].extend(regime_proposals)

        logger.info(
            f"[SWARM] Analysis complete: "
            f"{len(trade_proposals)} trade, {len(risk_proposals)} risk, "
            f"{len(critic_proposals)} critic, {len(regime_proposals)} regime proposals"
        )

        return proposals_by_agent

    def detect_systematic_bias(
        self, agent_name: str, lookback_days: int = 7
    ) -> Optional[AgentTuningProposal]:
        """Detect if an agent has systematic bias over recent period."""
        if agent_name == "trade":
            return self._detect_trade_agent_bias(lookback_days)
        elif agent_name == "risk":
            return self._detect_risk_agent_bias(lookback_days)
        elif agent_name == "critic":
            return self._detect_critic_agent_bias(lookback_days)
        elif agent_name == "regime":
            return self._detect_regime_agent_bias(lookback_days)

        return None

    def a_b_test_proposal(
        self, proposal: AgentTuningProposal, test_days: int = 7
    ) -> Dict[str, Any]:
        """Design an A/B test to validate a tuning proposal."""
        if proposal.agent_name == "trade":
            return {
                "type": "trade_confidence_deflation",
                "control_variant": "original_trade_agent",
                "test_variant": f"trade_agent_deflate_{proposal.magnitude:.0%}",
                "affected_regime": proposal.affected_regime,
                "metrics": ["win_rate", "avg_confidence_error", "veto_prevention"],
                "hold_back_pct": 0.1,
                "test_duration_days": test_days,
                "success_criteria": {
                    "win_rate_improvement": 0.05,
                    "confidence_calibration": 0.1,
                },
            }
        elif proposal.agent_name == "risk":
            return {
                "type": "risk_sizing_adjustment",
                "control_variant": "original_risk_agent",
                "test_variant": f"risk_agent_adjust_{proposal.magnitude:.0%}",
                "affected_regime": proposal.affected_regime,
                "metrics": ["position_drawdown", "leverage_appropriateness"],
                "hold_back_pct": 0.2,
                "test_duration_days": test_days,
                "success_criteria": {
                    "max_drawdown_reduction": 0.02,
                    "leverage_calibration": 0.05,
                },
            }
        elif proposal.agent_name == "critic":
            return {
                "type": "critic_veto_threshold",
                "control_variant": "original_critic_agent",
                "test_variant": f"critic_agent_adjust_{proposal.magnitude:.0%}",
                "metrics": ["false_veto_rate", "missed_veto_rate"],
                "hold_back_pct": 0.15,
                "test_duration_days": test_days,
                "success_criteria": {
                    "veto_accuracy": 0.85,
                    "pnl_impact": 0.02,
                },
            }

        return {}

    def save_recommendations(
        self, proposals_by_agent: Dict[str, List[AgentTuningProposal]]
    ) -> None:
        """Save all recommendations to JSONL file."""
        self.recommendations_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.recommendations_path, "a") as f:
            for agent_name, proposals in proposals_by_agent.items():
                for proposal in proposals:
                    f.write(json.dumps(proposal.to_dict()) + "\n")

        total = sum(len(p) for p in proposals_by_agent.values())
        logger.info(f"[SWARM] Saved {total} recommendations to {self.recommendations_path}")

    def _analyze_trade_agent(self) -> List[AgentTuningProposal]:
        """Analyze Trade Agent accuracy by regime and confidence."""
        proposals = []
        thesis_data = self._load_thesis_tracker()
        if not thesis_data:
            return proposals

        by_regime = {}
        for entry in thesis_data:
            regime = entry.get("regime", "unknown")
            if regime not in by_regime:
                by_regime[regime] = []
            by_regime[regime].append(entry)

        for regime, entries in by_regime.items():
            if len(entries) < 5:
                continue

            avg_confidence = sum(e.get("confidence", 50) for e in entries) / len(entries)
            actual_wr = sum(1 for e in entries if e.get("won", False)) / len(entries)

            if avg_confidence > 75 and actual_wr < avg_confidence / 100:
                magnitude = (avg_confidence / 100 - actual_wr) * 0.8
                proposals.append(
                    AgentTuningProposal(
                        agent_name="trade",
                        bias_type=BiasType.OVERCONFIDENT,
                        magnitude=magnitude,
                        affected_regime=regime,
                        recommendation=f"Trade Agent confidence {avg_confidence:.0f}% but actual WR {actual_wr:.1%} in {regime}. "
                        f"Recommend deflating confidence by {magnitude:.0%} for {regime} setups.",
                        confidence=0.75,
                        sample_size=len(entries),
                    )
                )

        return proposals

    def _analyze_risk_agent(self) -> List[AgentTuningProposal]:
        """Analyze Risk Agent sizing accuracy."""
        proposals = []
        decisions = self._load_decisions()
        if not decisions:
            return proposals

        by_regime = {}
        for decision in decisions:
            regime = decision.get("regime", "unknown")
            if regime not in by_regime:
                by_regime[regime] = []
            by_regime[regime].append(decision)

        for regime, decisions_list in by_regime.items():
            if len(decisions_list) < 5:
                continue

            avg_size_won = (
                sum(d.get("size", 1) for d in decisions_list if d.get("action") == "go")
                / len([d for d in decisions_list if d.get("action") == "go"])
                if any(d.get("action") == "go" for d in decisions_list)
                else 0
            )

            if avg_size_won == 0:
                continue

            win_rate = sum(1 for d in decisions_list if d.get("action") == "go") / len(
                decisions_list
            )

            if win_rate < 0.50 and avg_size_won > 1.0:
                magnitude = (1.0 - win_rate) * 0.5
                proposals.append(
                    AgentTuningProposal(
                        agent_name="risk",
                        bias_type=BiasType.UNDERCONFIDENT,
                        magnitude=magnitude,
                        affected_regime=regime,
                        recommendation=f"Risk Agent oversizing in {regime} (WR={win_rate:.1%}, avg size={avg_size_won:.2f}). "
                        f"Recommend reducing position size by {magnitude:.0%}.",
                        confidence=0.65,
                        sample_size=len(decisions_list),
                    )
                )

        return proposals

    def _analyze_critic_agent(self) -> List[AgentTuningProposal]:
        """Analyze Critic Agent veto accuracy."""
        proposals = []
        thesis_data = self._load_thesis_tracker()
        if not thesis_data:
            return proposals

        vetoed = [e for e in thesis_data if e.get("vetoed", False)]
        not_vetoed = [e for e in thesis_data if not e.get("vetoed", False)]

        if not vetoed or not not_vetoed:
            return proposals

        false_veto_rate = (
            sum(1 for e in vetoed if e.get("won", False)) / len(vetoed) if vetoed else 0
        )

        false_negative_rate = (
            sum(1 for e in not_vetoed if not e.get("won", False)) / len(not_vetoed)
            if not_vetoed
            else 0
        )

        if false_veto_rate > 0.20:
            proposals.append(
                AgentTuningProposal(
                    agent_name="critic",
                    bias_type=BiasType.OVERCONFIDENT,
                    magnitude=0.15,
                    recommendation=f"Critic Agent too aggressive: {false_veto_rate:.1%} of vetoes were correct "
                    f"(>20% false positive rate). Recommend relaxing veto threshold by 15%.",
                    confidence=0.70,
                    sample_size=len(vetoed),
                )
            )

        if false_negative_rate > 0.40:
            proposals.append(
                AgentTuningProposal(
                    agent_name="critic",
                    bias_type=BiasType.UNDERCONFIDENT,
                    magnitude=0.10,
                    recommendation=f"Critic Agent missing bad trades: {false_negative_rate:.1%} of non-vetoed trades lost "
                    f"(>40% false negative rate). Recommend tightening veto criteria by 10%.",
                    confidence=0.65,
                    sample_size=len(not_vetoed),
                )
            )

        return proposals

    def _analyze_regime_agent(self) -> List[AgentTuningProposal]:
        """Analyze Regime Agent classification accuracy."""
        proposals = []
        decisions = self._load_decisions()
        if not decisions:
            return proposals

        regime_counts = {}
        for decision in decisions:
            regime = decision.get("regime", "unknown")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        total = len(decisions)
        for regime, count in regime_counts.items():
            pct = count / total
            if pct > 0.60:
                proposals.append(
                    AgentTuningProposal(
                        agent_name="regime",
                        bias_type=BiasType.REGIME_SPECIFIC,
                        magnitude=0.0,
                        recommendation=f"Regime Agent classification: {regime} = {pct:.1%} of observations. "
                        f"Unusual skew—verify regime classification logic is not overfitting.",
                        confidence=0.50,
                        sample_size=total,
                    )
                )

        return proposals

    def _detect_trade_agent_bias(self, lookback_days: int) -> Optional[AgentTuningProposal]:
        """Detect Trade Agent overconfidence over recent trades."""
        thesis_data = self._load_thesis_tracker()
        if not thesis_data:
            return None

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent = [
            e
            for e in thesis_data
            if datetime.fromisoformat(e.get("timestamp", "")) > cutoff
        ]

        if len(recent) < 10:
            return None

        avg_confidence = sum(e.get("confidence", 50) for e in recent) / len(recent)
        actual_wr = sum(1 for e in recent if e.get("won", False)) / len(recent)

        if avg_confidence > 75 and actual_wr < avg_confidence / 100 - 0.10:
            magnitude = (avg_confidence / 100 - actual_wr) * 0.5
            return AgentTuningProposal(
                agent_name="trade",
                bias_type=BiasType.OVERCONFIDENT,
                magnitude=magnitude,
                recommendation=f"Trade Agent is {avg_confidence - actual_wr * 100:.0f}% overconfident recently. "
                f"WR {actual_wr:.1%} vs confidence {avg_confidence:.0f}%. Recommend deflating by {magnitude:.0%}.",
                confidence=0.80,
                sample_size=len(recent),
            )

        return None

    def _detect_risk_agent_bias(self, lookback_days: int) -> Optional[AgentTuningProposal]:
        """Detect Risk Agent sizing issues over recent trades."""
        decisions = self._load_decisions()
        if not decisions:
            return None

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent = [
            d
            for d in decisions
            if datetime.fromisoformat(d.get("timestamp", "")) > cutoff
        ]

        if len(recent) < 10:
            return None

        loss_rate = sum(1 for d in recent if d.get("action") == "skip") / len(recent)

        if loss_rate > 0.60:
            return AgentTuningProposal(
                agent_name="risk",
                bias_type=BiasType.UNDERCONFIDENT,
                magnitude=0.20,
                recommendation=f"Risk Agent recent loss rate {loss_rate:.1%} > 60%. "
                f"Suggest reviewing position sizing and risk parameters.",
                confidence=0.60,
                sample_size=len(recent),
            )

        return None

    def _detect_critic_agent_bias(self, lookback_days: int) -> Optional[AgentTuningProposal]:
        """Detect Critic Agent false veto rate over recent trades."""
        thesis_data = self._load_thesis_tracker()
        if not thesis_data:
            return None

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent = [
            e
            for e in thesis_data
            if datetime.fromisoformat(e.get("timestamp", "")) > cutoff
        ]

        if len(recent) < 10:
            return None

        vetoed = [e for e in recent if e.get("vetoed", False)]
        if not vetoed:
            return None

        false_veto_rate = sum(1 for e in vetoed if e.get("won", False)) / len(vetoed)

        if false_veto_rate > 0.25:
            return AgentTuningProposal(
                agent_name="critic",
                bias_type=BiasType.OVERCONFIDENT,
                magnitude=0.20,
                recommendation=f"Critic Agent false veto rate {false_veto_rate:.1%} > 25% recently. "
                f"Relax veto criteria by 20%.",
                confidence=0.70,
                sample_size=len(vetoed),
            )

        return None

    def _detect_regime_agent_bias(self, lookback_days: int) -> Optional[AgentTuningProposal]:
        """Detect Regime Agent classification drift over recent period."""
        decisions = self._load_decisions()
        if not decisions:
            return None

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent = [
            d
            for d in decisions
            if datetime.fromisoformat(d.get("timestamp", "")) > cutoff
        ]

        if len(recent) < 10:
            return None

        regime_counts = {}
        for d in recent:
            regime = d.get("regime", "unknown")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        dominant_regime = max(regime_counts.items(), key=lambda x: x[1])
        dominance = dominant_regime[1] / len(recent)

        if dominance > 0.70:
            return AgentTuningProposal(
                agent_name="regime",
                bias_type=BiasType.REGIME_SPECIFIC,
                magnitude=0.0,
                recommendation=f"Regime Agent recent drift: {dominant_regime[0]} = {dominance:.1%} of recent classifications. "
                f"Verify no overfitting.",
                confidence=0.55,
                sample_size=len(recent),
            )

        return None

    def _load_thesis_tracker(self) -> List[Dict[str, Any]]:
        """Load thesis tracker data."""
        if not self.thesis_tracker_path.exists():
            return []

        try:
            with open(self.thesis_tracker_path) as f:
                data = json.load(f)
                return data.get("theses", [])
        except Exception as e:
            logger.error(f"Failed to load thesis tracker: {e}")
            return []

    def _load_decisions(self) -> List[Dict[str, Any]]:
        """Load all decision entries from JSONL."""
        decisions = []
        if not self.decisions_path.exists():
            return decisions

        try:
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        decisions.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to load decisions: {e}")

        return decisions


def get_swarm_optimizer() -> SwarmOptimizer:
    """Get or create a SwarmOptimizer instance."""
    return SwarmOptimizer()