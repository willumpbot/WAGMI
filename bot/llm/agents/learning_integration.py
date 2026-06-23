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

    # 6. Record thesis accuracy into per-agent calibration ledger
    thesis_correct = lesson_data.get("thesis_correct")
    if thesis_correct is not None:
        _record_agent_calibration(trade_data, thesis_correct)

    # 7. Feed into network learning loop (routes lessons to other agents)
    try:
        from llm.agents.network_learning import get_network_learning
        get_network_learning().process_lesson(lesson_data, trade_data)
    except Exception as e:
        logger.debug(f"[AGENT-LEARN] Network learning feed error: {e}")


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

            if transition not in ("stable", "uncertain"):
                # Record regime transition — these are high-alpha
                dm.regime_history.record_transition(
                    from_regime="unknown",
                    to_regime=rg,
                    symbol="market",
                    trigger=f"agent_classified: {transition}",
                    context={"trade_context": trade_context[:100], "bias": bias},
                )
                logger.debug(f"[AGENT-LEARN] Regime transition recorded: {transition} → {rg}")
            else:
                # Record stable regime confirmations too (less frequently)
                dm.regime_history.record_transition(
                    from_regime=rg,
                    to_regime=rg,
                    symbol="market",
                    trigger=f"agent_confirmed: {transition}",
                    context={"bias": bias},
                )
        except Exception as e:
            logger.debug(f"[AGENT-LEARN] Regime history error: {e}")

    # Record critic challenges as self-awareness events (rate-limited to avoid churn)
    if critic_data and critic_data.get("verdict") == "challenge":
        cal_note = critic_data.get("calibration_note")
        reason = critic_data.get("reason", "")
        counter_thesis = critic_data.get("counter_thesis", "")

        # Only record substantive challenges — skip trivial or empty ones
        # to avoid churning the insight journal (capped at 500 entries)
        has_substantive_critique = cal_note and len(cal_note) > 20
        has_substantive_counter = counter_thesis and len(counter_thesis) > 20

        if has_substantive_critique or has_substantive_counter:
            try:
                from llm.deep_memory import get_deep_memory
                dm = get_deep_memory()
                if has_substantive_critique:
                    dm.insights.add_insight(
                        category="meta",
                        insight=f"Self-critique: {cal_note[:150]}",
                        confidence=0.7,
                        evidence=f"Critic challenged: {reason[:100]}",
                        source="critic_agent",
                    )
                if has_substantive_counter:
                    dm.insights.add_insight(
                        category="prediction",
                        insight=f"Counter-thesis: {counter_thesis[:150]}",
                        confidence=0.5,
                        evidence=f"Critic predicted opposite: {reason[:100]}",
                        source="critic_agent",
                    )
            except Exception:
                pass


def process_exit_feedback(
    exit_data: Dict[str, Any],
    position_data: Dict[str, Any],
) -> None:
    """Feed Exit Agent reasoning into learning systems when it triggers a close.

    When the Exit Agent closes a position (thesis invalidated, urgency close, etc.),
    its reasoning contains high-alpha learning signals that should persist:
    - Why the thesis broke (e.g., "regime shifted from trend to range")
    - What the agent would do differently
    - Pattern: "exit on funding flip when in range regime"

    Args:
        exit_data: Parsed exit agent output (action, reason, thesis_still_valid, etc.)
        position_data: The position that was closed (symbol, side, entry, pnl, etc.)
    """
    action = exit_data.get("action", "hold")
    if action not in ("full_close", "partial_close", "close"):
        return  # Only learn from close actions

    reason = exit_data.get("reason", "")
    if not reason or len(reason) < 10:
        return  # Skip empty/trivial reasons

    symbol = position_data.get("symbol", "")
    thesis_valid = exit_data.get("thesis_still_valid", True)

    # 1. Feed to deep memory insights
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        category = "exit_pattern" if not thesis_valid else "trade_management"
        dm.insights.add_insight(
            category=category,
            insight=f"Exit [{symbol}]: {reason[:150]}",
            confidence=0.75 if not thesis_valid else 0.5,
            evidence=f"action={action}, thesis_valid={thesis_valid}",
            source="exit_agent",
        )
    except Exception as e:
        logger.debug(f"[EXIT-LEARN] Deep memory insight error: {e}")

    # 2. Feed to post-trade learner ring buffer
    try:
        lesson = f"Exit agent closed {symbol}: {reason[:120]}"
        _inject_into_post_trade_learner(lesson, symbol, position_data)
    except Exception as e:
        logger.debug(f"[EXIT-LEARN] Post-trade learner error: {e}")

    logger.info(
        f"[EXIT-LEARN] Exit feedback recorded: {symbol} action={action} "
        f"thesis_valid={thesis_valid} reason={reason[:60]}"
    )


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

        knowledge_type = "principle"  # Only strong lessons reach here (guarded above)
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
            evidence=f"{symbol} in {regime}" if symbol or regime else "",
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


def _regime_was_correct(regime: str, move_pct: float) -> bool:
    """Was the regime classification right, judged vs ACTUAL price behavior — NOT
    whether our trade won. move_pct is the signed raw entry->exit price move %.
    (Mirrors performance_tracker._regime_matches_outcome; decouples regime accuracy
    from trade outcome — fixes the 2026-06-19 mismeasurement that made regime
    'accuracy' == trade win-rate and drove the bot's self-distrust death-spiral.)"""
    r = (regime or "").lower()
    up = move_pct >= 0
    am = abs(move_pct)
    if r in ("trend", "trending"):
        return am > 0.5                      # trend = a real directional move happened
    if r == "trending_bull":
        return up and am > 0.3
    if r == "trending_bear":
        return (not up) and am > 0.3
    if r in ("range", "consolidation"):
        return am < 1.5                      # range/consol correct if move stayed contained
    if r in ("high_volatility", "high_vol"):
        return am > 1.0
    if r in ("low_liquidity", "low_liq", "illiquid"):
        return am < 1.0
    if r == "panic":
        return (not up) and am > 2.0
    if r == "unknown":
        return False
    return True


def _record_agent_calibration(trade_data: Dict, thesis_correct: bool) -> None:
    """Record trade outcome into the per-agent calibration ledger.

    Each agent is recorded with ITS OWN stated confidence (captured at decision
    time in trade_data['agent_confidences']), NOT the blended consensus. The
    `correct` boolean is directional/thesis correctness (thesis_correct for
    trade/critic/risk, _regime_was_correct vs realized move for regime) — never
    raw PnL win/loss, which folds in sizing/fees in a 35%-WR-by-design system.
    """
    try:
        from llm.agents.calibration_ledger import get_calibration_ledger
        ledger = get_calibration_ledger()
        regime = trade_data.get("regime", "unknown")
        # Blended consensus confidence (0-1). Used only as a fallback when an
        # agent-specific stated confidence is unavailable. Normalize 0-100 -> 0-1.
        _blended = trade_data.get("confidence", 0.5)
        try:
            _blended = float(_blended)
            if _blended > 1.0:
                _blended = _blended / 100.0
            _blended = max(0.0, min(1.0, _blended))
        except (TypeError, ValueError):
            _blended = 0.5
        confidence = _blended
        # Per-agent stated confidences captured at decision time.
        _agent_confs = trade_data.get("agent_confidences", {}) or {}

        def _conf_for(agent: str, default: float) -> float:
            v = _agent_confs.get(agent)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return default
            if v > 1.0:
                v = v / 100.0
            return max(0.0, min(1.0, v))

        # Trade Agent's directional prediction — scored vs thesis_correct,
        # recorded with the Trade Agent's OWN stated confidence.
        trade_conf = _conf_for("trade", confidence)
        ledger.record_outcome("trade", regime, thesis_correct, trade_conf)

        # If critic challenged and was wrong (trade won despite veto), record.
        # Critic is scored on the OPPOSITE proposition (was the veto right), so
        # its recorded confidence is its confidence the trade was BAD.
        critic_challenged = trade_data.get("critic_challenged", False)
        if critic_challenged:
            critic_conf = _conf_for("critic", 1.0 - trade_conf)
            ledger.record_outcome("critic", regime, not thesis_correct, 1.0 - critic_conf)

        # Regime Agent calibration: score the classified regime vs ACTUAL price
        # behavior (NOT trade win), recorded with the Regime Agent's OWN conf.
        if regime and regime != "unknown":
            move_pct = trade_data.get("price_move_pct")
            if move_pct is None:
                side = (trade_data.get("side") or "").upper()
                pnl = trade_data.get("pnl", 0) or 0
                is_long = side in ("BUY", "LONG")
                price_up = (is_long and pnl > 0) or ((not is_long) and pnl < 0)
                move_pct = 0.6 if price_up else -0.6
            regime_correct = _regime_was_correct(regime, float(move_pct))
            regime_conf = _conf_for("regime", 0.5)
            ledger.record_outcome("regime", regime, regime_correct, regime_conf)

        # Risk Agent override tracking: scored on whether the override was right.
        notes = trade_data.get("notes", "")
        risk_conf = _conf_for("risk", 0.8)
        if "RISK: override to skip" in notes:
            ledger.record_outcome("risk", regime, not thesis_correct, risk_conf)
        elif "RISK: sizing" in notes and "→" in notes:
            ledger.record_outcome("risk", regime, not thesis_correct, _conf_for("risk", 0.6))

        logger.debug(
            f"[CALIBRATION] Recorded: trade_agent {regime} "
            f"correct={thesis_correct} conf={trade_conf:.2f} "
            f"(per-agent={'yes' if _agent_confs else 'fallback'})"
        )
    except Exception as e:
        logger.debug(f"[CALIBRATION] Recording error: {e}")


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
