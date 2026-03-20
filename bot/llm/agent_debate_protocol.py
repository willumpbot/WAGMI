"""
TIER 2.4: Agent Debate Protocol

Agents argue with each other before reaching final decision.

Why debate matters:
- Sequential pipeline: each agent just reads scratchpad, no back-and-forth
- Debate: agents can challenge each other, change minds
- Result: Better decisions through adversarial reasoning

Example:
  Trade Agent: "Go long, 75% confidence"
  Critic Agent: "But regime is ranging - breakouts fail 60% of time"
  Trade Agent: "Good point, reducing to 55% confidence"
  Final: More calibrated decision

Design:
  1. Round 1: Each agent proposes position + reasoning
  2. Round 2: Critic reviews all proposals, raises objections
  3. Round 3: Trade agent responds to objections
  4. Final: Merged decision with recorded debate

Cost: +$0.002/decision (1 extra Sonnet call for debate)
Benefit: Better calibrated confidence, fewer bad decisions
Expected impact: +0.2-0.5% daily (fewer overconfident decisions)
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
import time

logger = logging.getLogger("bot.llm.agent_debate_protocol")


@dataclass
class DebatePosition:
    """One agent's position in the debate."""
    agent_name: str
    round: int
    position: str  # "go", "skip", "flip", etc.
    confidence: float  # 0-1
    reasoning: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class DebateObjection:
    """A challenge raised by one agent to another."""
    from_agent: str
    to_agent: str
    objection: str
    supporting_evidence: str
    severity: str  # "low", "medium", "high"


@dataclass
class DebateRecord:
    """Full record of a debate."""
    debate_id: str
    symbol: str
    timestamp: float

    # Round 1: Initial positions
    round1_positions: Dict[str, DebatePosition] = field(default_factory=dict)

    # Round 2: Objections
    objections: List[DebateObjection] = field(default_factory=list)

    # Round 3: Responses
    round3_responses: Dict[str, str] = field(default_factory=dict)  # agent -> response

    # Final outcome
    final_decision: str = ""
    final_confidence: float = 0.5
    consensus_reached: bool = False
    decision_quality: str = "medium"  # low, medium, high

    def to_dict(self) -> Dict:
        """Convert to dict for JSON."""
        return {
            "debate_id": self.debate_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "round1_positions": {
                k: asdict(v) for k, v in self.round1_positions.items()
            },
            "objections": [asdict(o) for o in self.objections],
            "round3_responses": self.round3_responses,
            "final_decision": self.final_decision,
            "final_confidence": self.final_confidence,
            "consensus_reached": self.consensus_reached,
            "decision_quality": self.decision_quality,
        }


class AgentDebateProtocol:
    """
    Orchestrates debate between agents before reaching final decision.

    Flow:
      1. All agents state position + reasoning (Round 1)
      2. Critic reviews and raises objections (Round 2)
      3. Trade agent responds to objections (Round 3)
      4. Final decision with consensus record
    """

    def __init__(self):
        """Initialize debate protocol."""
        self.debate_history: List[DebateRecord] = []

    async def run_debate(
        self,
        symbol: str,
        round1_outputs: Dict[str, Dict],  # agent_name -> agent output
        critic_evaluation_fn: callable,    # async fn to get critic's evaluation
        trade_response_fn: callable,       # async fn to get trade agent's response
    ) -> DebateRecord:
        """
        Run full debate protocol.

        Args:
            symbol: Trading symbol
            round1_outputs: Initial positions from all agents
            critic_evaluation_fn: Async function to get critic's objections
            trade_response_fn: Async function to get trade agent's responses

        Returns:
            DebateRecord with full debate transcript
        """
        debate_id = f"{symbol}_{int(time.time() * 1000) % 100000}"
        debate = DebateRecord(
            debate_id=debate_id,
            symbol=symbol,
            timestamp=time.time(),
        )

        # ── Round 1: Collect initial positions ──
        logger.info(f"[DEBATE] {debate_id} Round 1: Collecting positions")
        for agent_name, output in round1_outputs.items():
            debate.round1_positions[agent_name] = DebatePosition(
                agent_name=agent_name,
                round=1,
                position=output.get("action", "skip"),
                confidence=output.get("confidence", 0.5),
                reasoning=output.get("reasoning", ""),
            )

        # ── Round 2: Critic raises objections ──
        logger.info(f"[DEBATE] {debate_id} Round 2: Critic review")
        try:
            # Build context for critic
            positions_text = "\n".join([
                f"- {name}: {pos.position} ({pos.confidence:.0%}) - {pos.reasoning}"
                for name, pos in debate.round1_positions.items()
            ])

            critic_input = {
                "positions": positions_text,
                "symbol": symbol,
            }

            critic_output = await critic_evaluation_fn(critic_input)

            # Parse objections
            if critic_output.get("objections"):
                for obj in critic_output["objections"]:
                    objection = DebateObjection(
                        from_agent="critic",
                        to_agent=obj.get("target_agent", "trade"),
                        objection=obj.get("objection", ""),
                        supporting_evidence=obj.get("evidence", ""),
                        severity=obj.get("severity", "medium"),
                    )
                    debate.objections.append(objection)

            logger.info(f"[DEBATE] {debate_id} Critic raised {len(debate.objections)} objections")

        except Exception as e:
            logger.error(f"[DEBATE] {debate_id} Critic failed: {e}")
            # Continue without critic input

        # ── Round 3: Trade agent responds ──
        logger.info(f"[DEBATE] {debate_id} Round 3: Trade response")
        if debate.objections:
            try:
                objections_text = "\n".join([
                    f"- {obj.from_agent} → {obj.to_agent}: {obj.objection}"
                    for obj in debate.objections
                ])

                trade_input = {
                    "original_position": debate.round1_positions.get("trade", DebatePosition(
                        "trade", 1, "skip", 0.5, ""
                    )).__dict__,
                    "objections": objections_text,
                    "symbol": symbol,
                }

                trade_response = await trade_response_fn(trade_input)

                # Update confidence based on response
                if "confidence_adjustment" in trade_response:
                    original_conf = debate.round1_positions["trade"].confidence
                    adjusted_conf = original_conf * (1 + trade_response["confidence_adjustment"])
                    debate.round1_positions["trade"].confidence = max(0, min(1, adjusted_conf))

                # Record response
                debate.round3_responses["trade"] = trade_response.get("response", "")

                logger.info(f"[DEBATE] {debate_id} Trade agent adjusted confidence")

            except Exception as e:
                logger.error(f"[DEBATE] {debate_id} Trade response failed: {e}")

        # ── Final: Merge results ──
        debate.final_decision, debate.final_confidence, debate.decision_quality = self._merge_debate_results(
            debate
        )
        debate.consensus_reached = self._check_consensus(debate)

        # Store
        self.debate_history.append(debate)
        if len(self.debate_history) > 100:
            self.debate_history = self.debate_history[-100:]

        logger.info(
            f"[DEBATE] {debate_id} complete: "
            f"decision={debate.final_decision}, "
            f"confidence={debate.final_confidence:.0%}, "
            f"consensus={debate.consensus_reached}"
        )

        return debate

    def _merge_debate_results(self, debate: DebateRecord) -> tuple:
        """
        Merge debate results into final decision.

        Returns:
            (final_action, final_confidence, decision_quality)
        """
        # Start with trade agent position (usually highest quality)
        trade_pos = debate.round1_positions.get("trade")
        if not trade_pos:
            return "skip", 0.5, "low"

        action = trade_pos.position
        confidence = trade_pos.confidence

        # Adjust if trade agent responded to objections
        if "trade" in debate.round3_responses:
            # Confidence may have been adjusted
            pass

        # Check if any high-severity objections should block the trade
        high_severity = [o for o in debate.objections if o.severity == "high"]
        if high_severity and action != "skip":
            # Consider vetoing
            confidence = max(0.3, confidence * 0.7)

        # Decision quality: higher confidence + consensus = higher quality
        decision_quality = "low" if confidence < 0.5 else "medium" if confidence < 0.7 else "high"

        return action, confidence, decision_quality

    def _check_consensus(self, debate: DebateRecord) -> bool:
        """
        Check if agents reached consensus.

        Consensus = all agents agree on action (or within margin).
        """
        positions = list(debate.round1_positions.values())
        if not positions:
            return False

        # All same action?
        actions = [p.position for p in positions]
        if len(set(actions)) == 1:
            return True

        # Most agree?
        action_counts = {}
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1

        max_count = max(action_counts.values())
        if max_count / len(actions) >= 0.75:
            return True

        return False

    def get_debate_summary(self) -> Dict[str, Any]:
        """Get summary of recent debates."""
        if not self.debate_history:
            return {"status": "no_data"}

        recent = self.debate_history[-50:]

        consensus_count = sum(1 for d in recent if d.consensus_reached)
        high_quality_count = sum(1 for d in recent if d.decision_quality == "high")
        avg_confidence = sum(d.final_confidence for d in recent) / len(recent) if recent else 0

        return {
            "debates_recorded": len(recent),
            "consensus_reached_pct": f"{consensus_count / len(recent) * 100:.0f}%" if recent else "0%",
            "high_quality_decisions_pct": f"{high_quality_count / len(recent) * 100:.0f}%" if recent else "0%",
            "avg_final_confidence": f"{avg_confidence:.0%}",
            "objections_raised": sum(len(d.objections) for d in recent),
            "avg_objections_per_debate": f"{sum(len(d.objections) for d in recent) / len(recent):.1f}" if recent else "0",
        }

    def export_debate_log(self, output_file: str = "data/llm/debates.jsonl") -> None:
        """Export all debates to JSON log."""
        import os
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        try:
            with open(output_file, "w") as f:
                for debate in self.debate_history:
                    f.write(json.dumps(debate.to_dict()) + "\n")
            logger.info(f"Exported {len(self.debate_history)} debates to {output_file}")
        except Exception as e:
            logger.error(f"Failed to export debates: {e}")


# Global debate protocol
_global_protocol: Optional[AgentDebateProtocol] = None


def get_agent_debate_protocol() -> AgentDebateProtocol:
    """Get or create global debate protocol."""
    global _global_protocol
    if _global_protocol is None:
        _global_protocol = AgentDebateProtocol()
    return _global_protocol
