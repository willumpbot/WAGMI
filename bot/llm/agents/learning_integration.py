"""
Learning Integration: connects multi-agent outputs to the growth/feedback pipeline.

When multi-agent mode is active, the agents produce richer, more structured
feedback than the monolithic pipeline. This module bridges agent outputs to:
  1. Growth Orchestrator (on_trade_closed, on_veto, hypothesis proposals)
  2. Deep Memory (trade DNA, pattern library, insight journal)
  3. Post-Trade Learner (immediate lesson injection)
  4. Self-Teaching Engine (knowledge base updates)
  5. Hypothesis Tracker (testable predictions from Learning Agent)

The key improvement: the Learning Agent runs a dedicated LLM call focused
solely on extracting lessons, producing deeper insights than the deterministic
post_trade_learner alone.
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.llm.agents.learning_integration")


def process_agent_lesson(
    lesson_data: Dict[str, Any],
    trade_data: Dict[str, Any],
) -> None:
    """Process a lesson from the Learning Agent and feed it to all learning systems.

    Args:
        lesson_data: Parsed output from the Learning Agent containing:
            lesson, category, strength, applies_to, hypothesis
        trade_data: The original closed trade data.
    """
    lesson_text = lesson_data.get("lesson", "")
    category = lesson_data.get("category", "")
    strength = lesson_data.get("strength", "weak")
    applies_to = lesson_data.get("applies_to", {}) or {}
    hypothesis = lesson_data.get("hypothesis")

    if not lesson_text:
        return

    symbol = applies_to.get("symbol") or trade_data.get("symbol", "")
    regime = applies_to.get("regime") or trade_data.get("regime", "")
    side = applies_to.get("side") or trade_data.get("side", "")

    logger.info(
        f"[AGENT-LEARN] Processing lesson: [{category}] {lesson_text[:80]}... "
        f"(strength={strength}, symbol={symbol}, regime={regime})"
    )

    # 1. Inject into post-trade learner's ring buffer (immediate feedback)
    _inject_into_post_trade_learner(lesson_text, symbol, trade_data)

    # 2. Feed into deep memory systems
    _inject_into_deep_memory(lesson_text, category, strength, trade_data)

    # 3. Propose hypothesis to hypothesis tracker if the agent generated one
    if hypothesis:
        _propose_hypothesis(hypothesis, category, lesson_text)

    # 4. Feed into self-teaching knowledge base
    _inject_into_knowledge_base(lesson_text, category, strength, symbol, regime)

    # 5. Create improvement proposal if lesson is strong
    if strength == "strong" and category in ("pattern_loss", "regime_mismatch", "funding_cost"):
        _propose_improvement(lesson_text, category, trade_data)


def process_agent_decision_for_learning(
    decision_notes: str,
    regime_data: Dict[str, Any],
    critic_data: Optional[Dict[str, Any]],
    trade_context: str = "",
) -> None:
    """Extract learning signals from the multi-agent decision pipeline itself.

    The decision process generates learning even before the trade closes:
    - Regime Agent's classification feeds regime history
    - Critic Agent's challenges are self-improvement signals
    - Decision consistency tracking feeds memory quality
    """
    # Record regime classification in deep memory
    if regime_data:
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            rg = regime_data.get("rg", "unknown")
            bias = regime_data.get("bias", "neutral")
            transition = regime_data.get("transition", "stable")

            if transition != "stable" and transition != "uncertain":
                # Record regime transition — these are high-alpha
                dm.regime_history.record_transition(
                    from_regime="previous",
                    to_regime=rg,
                    trigger=f"agent_classified: {transition}",
                    context=trade_context[:100],
                )
                logger.debug(f"[AGENT-LEARN] Regime transition recorded: {transition} → {rg}")
        except Exception as e:
            logger.debug(f"[AGENT-LEARN] Regime history error: {e}")

    # Record critic challenges as self-awareness events
    if critic_data and critic_data.get("verdict") == "challenge":
        cal_note = critic_data.get("calibration_note")
        reason = critic_data.get("reason", "")

        if cal_note:
            try:
                from llm.deep_memory import get_deep_memory
                dm = get_deep_memory()
                dm.insights.add_insight(
                    category="meta",
                    insight=f"Self-critique: {cal_note[:150]}",
                    confidence=0.7,
                    evidence=f"Critic challenged: {reason[:100]}",
                    source="critic_agent",
                )
            except Exception:
                pass


# ── Internal helpers ────────────────────────────────────────────

def _inject_into_post_trade_learner(lesson: str, symbol: str, trade_data: Dict):
    """Add the agent-generated lesson to the post-trade learner's ring buffer."""
    try:
        from llm.post_trade_learner import _recent_lessons
        _recent_lessons.append({
            "ts": time.time(),
            "lesson": lesson[:200],
            "symbol": symbol,
            "outcome": trade_data.get("outcome", ""),
            "source": "learning_agent",
        })
    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Post-trade injection error: {e}")


def _inject_into_deep_memory(
    lesson: str, category: str, strength: str, trade_data: Dict
):
    """Feed the lesson into deep memory's pattern library and insight journal."""
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()

        symbol = trade_data.get("symbol", "")
        regime = trade_data.get("regime", "")
        pnl = trade_data.get("pnl", 0)
        outcome = trade_data.get("outcome", "")

        # Add to pattern library
        pattern_type = _category_to_pattern_type(category)
        dm.pattern_library.record_pattern(
            pattern_type=pattern_type,
            symbol=symbol,
            description=lesson[:200],
            regime=regime,
            outcome=outcome,
            pnl=pnl,
        )

        # Add strong/moderate lessons to insight journal
        if strength in ("strong", "moderate"):
            insight_category = _category_to_insight_category(category)
            confidence = 0.85 if strength == "strong" else 0.65
            dm.insights.add_insight(
                category=insight_category,
                insight=lesson[:200],
                confidence=confidence,
                evidence=f"{symbol} {outcome} ${pnl:+.2f} in {regime}",
                source="learning_agent",
            )

    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Deep memory injection error: {e}")


def _propose_hypothesis(hypothesis: str, category: str, evidence_lesson: str):
    """Submit a testable hypothesis to the hypothesis tracker."""
    try:
        from llm.growth.hypothesis_tracker import get_hypothesis_tracker
        tracker = get_hypothesis_tracker()

        # Map category to hypothesis category
        hypo_category = {
            "entry_timing": "entry",
            "regime_mismatch": "regime",
            "sizing": "risk",
            "exit_timing": "exit",
            "funding_cost": "cost",
            "pattern_win": "pattern",
            "pattern_loss": "pattern",
            "strategy_edge": "strategy",
            "correlation": "correlation",
            "psychology": "behavior",
        }.get(category, "general")

        tracker.propose(
            statement=hypothesis[:200],
            test_criteria=f"Validate over next 10+ trades matching conditions",
            category=hypo_category,
            tags=[category],
            proposed_by="learning_agent",
        )
        logger.info(f"[AGENT-LEARN] Hypothesis proposed: {hypothesis[:80]}")

    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Hypothesis proposal error: {e}")


def _inject_into_knowledge_base(
    lesson: str, category: str, strength: str, symbol: str, regime: str
):
    """Feed strong lessons into the self-teaching knowledge base."""
    if strength != "strong":
        return  # Only strong lessons become knowledge

    try:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()

        knowledge_type = "observation" if strength == "moderate" else "principle"
        tags = [category]
        if symbol:
            tags.append(symbol.lower())
        if regime:
            tags.append(regime.lower())

        engine.knowledge.add(
            knowledge_type=knowledge_type,
            content=lesson[:200],
            confidence=0.80,
            category=category,
            tags=tags,
            source="learning_agent",
        )
        logger.debug(f"[AGENT-LEARN] Knowledge added: [{category}] {lesson[:60]}")

    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Knowledge injection error: {e}")


def _propose_improvement(lesson: str, category: str, trade_data: Dict):
    """Create an improvement proposal from a strong loss pattern."""
    try:
        from llm.growth.self_improvement import get_self_improvement_engine
        engine = get_self_improvement_engine()

        symbol = trade_data.get("symbol", "")
        regime = trade_data.get("regime", "")

        title = f"Agent learning: {category}"
        description = f"Pattern detected by Learning Agent: {lesson[:150]}"

        engine.propose(
            proposal_type="RULE_PROPOSAL",
            title=title,
            description=description,
            evidence=[f"{symbol} {trade_data.get('outcome', '')} "
                      f"${trade_data.get('pnl', 0):+.2f} in {regime}"],
            suggested_action={"type": "add_rule", "rule": lesson[:100]},
            safety_level="REVIEW_NEEDED",
            confidence=0.7,
            expected_impact=0.3,
        )
    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Improvement proposal error: {e}")


def _category_to_pattern_type(category: str) -> str:
    """Map lesson category to deep memory pattern type."""
    return {
        "entry_timing": "entry_pattern",
        "regime_mismatch": "regime_pattern",
        "sizing": "sizing_pattern",
        "exit_timing": "exit_pattern",
        "funding_cost": "cost_pattern",
        "pattern_win": "winning_setup",
        "pattern_loss": "losing_setup",
        "strategy_edge": "strategy_pattern",
        "correlation": "correlation_pattern",
        "psychology": "behavioral_pattern",
    }.get(category, "observation")


def _category_to_insight_category(category: str) -> str:
    """Map lesson category to deep memory insight category."""
    return {
        "entry_timing": "execution",
        "regime_mismatch": "regime",
        "sizing": "risk",
        "exit_timing": "execution",
        "funding_cost": "risk",
        "pattern_win": "strategy",
        "pattern_loss": "strategy",
        "strategy_edge": "strategy",
        "correlation": "correlation",
        "psychology": "meta",
    }.get(category, "meta")
