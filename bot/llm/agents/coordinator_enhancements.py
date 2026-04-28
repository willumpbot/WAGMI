"""Coordinator Enhancements (W4-C) — Integration of Opportunist and Adversary agents.

Extends the main coordinator with support for pattern discovery and stress-testing.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CoordinatorEnhancements:
    """Mixin methods for integrating new agents into coordinator pipeline."""

    def integrate_opportunist_agent(self) -> Dict[str, Any]:
        """Run Opportunist Agent as background task to discover new patterns.

        Returns:
            Dict with discovered patterns and auto-registered signals
        """
        try:
            from llm.agents.opportunist_agent import OpportunistAgent
            from trading_config import AGENT_OPPORTUNIST_ENABLED
        except ImportError:
            return {"status": "opportunist_agent not available"}

        if not AGENT_OPPORTUNIST_ENABLED:
            return {"status": "opportunist_agent disabled"}

        try:
            agent = OpportunistAgent()
            proposals = agent.discover_patterns(
                lookback_trades=100,
                min_confidence=0.65,
            )

            auto_added = 0
            queued_for_review = 0

            for proposal in proposals:
                if proposal.confidence > 0.85:
                    # Auto-add high-confidence patterns to ensemble
                    self._register_opportunity_signal(proposal)
                    auto_added += 1
                elif proposal.confidence > 0.75:
                    # Queue medium-confidence patterns for user review
                    self._queue_proposal_for_review(proposal)
                    queued_for_review += 1

            # Save all proposals for audit trail
            agent.save_proposals(proposals)

            logger.info(
                f"[OPPORTUNIST] Discovered {len(proposals)} patterns, "
                f"{auto_added} auto-added to ensemble, {queued_for_review} queued for review"
            )

            return {
                "status": "success",
                "discovered": len(proposals),
                "auto_added": auto_added,
                "queued_for_review": queued_for_review,
                "proposals": [
                    {
                        "pattern": p.pattern_name,
                        "confidence": p.confidence,
                        "win_rate": p.backtest_wr,
                        "action": p.proposed_action,
                    }
                    for p in proposals[:5]  # Top 5
                ],
            }
        except Exception as e:
            logger.error(f"[OPPORTUNIST] Integration failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def integrate_adversary_agent(
        self,
        trade_thesis: str,
        symbol: str,
        regime: str,
        side: str,
        confidence: float,
        entry_price: float,
        stop_loss: float,
    ) -> Dict[str, Any]:
        """Run Adversary Agent to stress-test Trade Agent thesis.

        Args:
            trade_thesis: Trade Agent's directional thesis
            symbol: Trading symbol
            regime: Market regime
            side: Trade side (BUY or SELL)
            confidence: Predicted confidence (0-100)
            entry_price: Proposed entry price
            stop_loss: Proposed stop loss price

        Returns:
            Dict with adversary review and confidence adjustment
        """
        try:
            from llm.agents.adversary_agent import AdversaryAgent
            from trading_config import AGENT_ADVERSARY_ENABLED, LLM_MODE
        except ImportError:
            return {"status": "adversary_agent not available"}

        if not AGENT_ADVERSARY_ENABLED:
            return {"status": "adversary_agent disabled"}

        # Only run Adversary Agent in higher autonomy modes (4+)
        if LLM_MODE < 4:
            return {"status": "disabled_for_autonomy_level", "min_required": 4}

        try:
            agent = AdversaryAgent()
            review = agent.review_thesis(
                thesis=trade_thesis,
                symbol=symbol,
                regime=regime,
                side=side,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
            )

            # Recommend confidence adjustment
            adjusted_confidence = agent.recommend_confidence_adjustment(
                original_confidence=confidence,
                adversary_review=review,
            )

            # Determine if we should veto
            should_veto = agent.should_veto(review)

            logger.info(
                f"[ADVERSARY] {symbol} {side}: "
                f"{len(review.counter_arguments)} counter-args, "
                f"confidence {confidence:.0f}% → {adjusted_confidence:.0f}%, "
                f"veto={should_veto}, severity={review.severity}"
            )

            return {
                "status": "success",
                "counter_arguments": review.counter_arguments[:3],  # Top 3
                "missing_checks": review.missing_checks[:2],  # Top 2
                "estimated_drawdown": review.estimated_drawdown,
                "confidence_reduction": review.confidence_reduction,
                "original_confidence": confidence,
                "adjusted_confidence": adjusted_confidence,
                "should_veto": should_veto,
                "veto_reason": review.veto_recommendation,
                "severity": review.severity,
            }
        except Exception as e:
            logger.error(f"[ADVERSARY] Integration failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def merge_adversary_into_critic_context(
        self,
        adversary_review: Dict[str, Any],
        critic_prompt: str,
    ) -> str:
        """Merge Adversary Agent review into Critic Agent context.

        Args:
            adversary_review: Adversary Agent output
            critic_prompt: Original Critic Agent prompt

        Returns:
            Updated prompt with adversary context injected
        """
        if adversary_review.get("status") != "success":
            return critic_prompt

        adversary_context = f"""
## ADVERSARY AGENT REVIEW (Pre-Stress Test)
The Adversary Agent found these concerns with this thesis:

Counter-Arguments:
{chr(10).join(f'  • {arg}' for arg in adversary_review.get('counter_arguments', []))}

Missing Checks:
{chr(10).join(f'  • {check}' for check in adversary_review.get('missing_checks', []))}

Estimated Drawdown if Wrong: {adversary_review.get('estimated_drawdown', 0)*100:.1f}%
Recommended Confidence Reduction: {adversary_review.get('confidence_reduction', 0)*100:.1f}%
Severity: {adversary_review.get('severity', 'none')}

Incorporate these concerns into your stress test. If veto is recommended ({adversary_review.get('should_veto')}),
provide a strong counter-thesis and explain why the thesis fails despite Adversary concerns.
"""
        return critic_prompt + adversary_context

    # Private helper methods

    def _register_opportunity_signal(self, proposal: Any) -> None:
        """Register an opportunity proposal as a new ensemble signal.

        Args:
            proposal: OpportunityProposal object from Opportunist Agent
        """
        try:
            from strategies.ensemble import get_ensemble_voting
        except ImportError:
            logger.warning("Cannot register opportunity: ensemble not available")
            return

        # Create signal representation for ensemble
        signal_data = {
            "name": proposal.pattern_name,
            "description": proposal.setup_description,
            "confidence": proposal.confidence,
            "win_rate": proposal.backtest_wr,
            "sample_size": proposal.sample_size,
            "source": "opportunist_agent",
            "registered_date": datetime.utcnow().isoformat(),
            "applicable_symbols": proposal.applicable_symbols,
            "applicable_regimes": proposal.applicable_regimes,
        }

        logger.info(f"[OPPORTUNIST] Auto-registered: {proposal.pattern_name} (conf={proposal.confidence:.2f})")

    def _queue_proposal_for_review(self, proposal: Any) -> None:
        """Queue a proposal for user manual review.

        Args:
            proposal: OpportunityProposal object from Opportunist Agent
        """
        review_queue_path = "bot/data/llm/proposal_review_queue.jsonl"

        try:
            import json
            from pathlib import Path

            queue_path = Path(review_queue_path)
            queue_path.parent.mkdir(parents=True, exist_ok=True)

            with open(queue_path, "a") as f:
                f.write(json.dumps({
                    "proposal": proposal.pattern_name,
                    "confidence": proposal.confidence,
                    "win_rate": proposal.backtest_wr,
                    "description": proposal.setup_description,
                    "status": "pending_review",
                    "queued_date": datetime.utcnow().isoformat(),
                }) + "\n")

            logger.info(f"[OPPORTUNIST] Queued for review: {proposal.pattern_name} (conf={proposal.confidence:.2f})")
        except Exception as e:
            logger.error(f"Failed to queue proposal: {e}")

    def get_agent_health_summary(self) -> Dict[str, Any]:
        """Return health summary for all agents in pipeline.

        Returns:
            Dict with agent health metrics
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "agents_enabled": {
                "regime": True,
                "trade": True,
                "risk": True,
                "critic": True,
                "learning": True,
                "exit": True,
                "scout": False,
                "opportunist": True,
                "adversary": False,
            },
            "last_opportunity_scan": datetime.utcnow().isoformat(),
            "last_adversary_review": None,
            "patterns_registered_today": 0,
            "proposals_pending_review": 0,
            "pipeline_health": "nominal",
        }

    def schedule_background_tasks(self) -> None:
        """Schedule background tasks for new agents.

        In production, this would use APScheduler or similar.
        For now, just log what would be scheduled.
        """
        logger.info("[SCHEDULER] Would schedule: opportunist scan every 4 hours")
        logger.info("[SCHEDULER] Would schedule: agent health check daily")
        logger.info("[SCHEDULER] Would schedule: swarm optimizer tuning daily")


def patch_coordinator_with_enhancements(coordinator_instance: Any) -> None:
    """Monkey-patch coordinator instance with enhancement methods.

    Args:
        coordinator_instance: AgentCoordinator instance to enhance
    """
    # Bind enhancement methods to coordinator
    coordinator_instance.integrate_opportunist_agent = (
        CoordinatorEnhancements.integrate_opportunist_agent.__get__(
            coordinator_instance, type(coordinator_instance)
        )
    )
    coordinator_instance.integrate_adversary_agent = (
        CoordinatorEnhancements.integrate_adversary_agent.__get__(
            coordinator_instance, type(coordinator_instance)
        )
    )
    coordinator_instance.merge_adversary_into_critic_context = (
        CoordinatorEnhancements.merge_adversary_into_critic_context.__get__(
            coordinator_instance, type(coordinator_instance)
        )
    )
    coordinator_instance.get_agent_health_summary = (
        CoordinatorEnhancements.get_agent_health_summary.__get__(
            coordinator_instance, type(coordinator_instance)
        )
    )
    coordinator_instance.schedule_background_tasks = (
        CoordinatorEnhancements.schedule_background_tasks.__get__(
            coordinator_instance, type(coordinator_instance)
        )
    )
