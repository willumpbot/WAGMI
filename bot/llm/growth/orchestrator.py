"""
Growth Orchestrator — Unified integration layer for all growth subsystems.

This is the SINGLE ENTRY POINT the main bot loop calls for all growth
intelligence. It coordinates:

1. Recommendation Engine  — Structured suggestion generation
2. Hypothesis Tracker     — Hypothesis lifecycle management
3. Explainability Engine  — Parameter change audit trail
4. Veto Feedback Tracker  — Veto accuracy and learning
5. Self-Improvement Engine — System improvement proposals
6. Growth Reporter        — Periodic intelligence reports
7. Self-Teaching Engine   — Curriculum-based learning

Usage in main loop:
    growth = get_growth_orchestrator()

    # On every trade close:
    growth.on_trade_closed(trade_data)

    # On every veto:
    growth.on_veto(symbol, side, ...)

    # On parameter change:
    growth.on_parameter_change(parameter, old, new, reason, source)

    # Periodic tick (every main loop iteration):
    growth.tick(recent_trades, market_state)

    # Get LLM prompt context:
    context = growth.get_llm_context(symbol, regime)
"""

import logging
import os
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.llm.growth.orchestrator")


class GrowthOrchestrator:
    """Unified orchestration layer for all growth intelligence systems."""

    def __init__(self):
        self._initialized = False
        self._last_tick_time: float = 0
        self._tick_interval_s: float = 60  # Check subsystems every 60s
        self._last_learning_cycle: float = 0
        self._learning_cycle_interval_s: float = 1800  # 30 min
        self._trade_buffer: List[Dict[str, Any]] = []  # Buffer trades for batch learning
        self._backtest_mode: bool = False  # When True, skip LLM API calls

        # Lazy-initialized subsystem references
        self._rec_engine = None
        self._hypo_tracker = None
        self._explainer = None
        self._veto_tracker = None
        self._improvement_engine = None
        self._reporter = None
        self._teaching_engine = None

    def _ensure_init(self):
        """Lazy-initialize all subsystems."""
        if self._initialized:
            return
        self._initialized = True

        try:
            from llm.growth.recommendation_engine import get_recommendation_engine
            self._rec_engine = get_recommendation_engine()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init recommendation engine: {e}")

        try:
            from llm.growth.hypothesis_tracker import get_hypothesis_tracker
            self._hypo_tracker = get_hypothesis_tracker()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init hypothesis tracker: {e}")

        try:
            from llm.growth.explainability import get_explainer
            self._explainer = get_explainer()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init explainability: {e}")

        try:
            from llm.growth.veto_feedback import get_veto_tracker
            self._veto_tracker = get_veto_tracker()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init veto tracker: {e}")

        try:
            from llm.growth.self_improvement import get_self_improvement_engine
            self._improvement_engine = get_self_improvement_engine()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init self-improvement: {e}")

        try:
            from llm.growth.growth_report import get_growth_reporter
            self._reporter = get_growth_reporter()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init reporter: {e}")

        try:
            from llm.self_teaching import get_teaching_engine
            self._teaching_engine = get_teaching_engine()
        except Exception as e:
            logger.warning(f"[GROWTH] Failed to init teaching engine: {e}")

        logger.info("[GROWTH] Orchestrator initialized")

    # ── Event Handlers ────────────────────────────────────────

    def on_trade_closed(self, trade_data: Dict[str, Any]):
        """Called when a trade closes. Feeds data to all relevant systems.

        trade_data should include:
            symbol, side, outcome ("WIN"/"LOSS"), pnl, confidence,
            regime, strategy, num_agree, hold_time_s, leverage, hour
        """
        self._ensure_init()

        # Buffer for batch learning
        self._trade_buffer.append(trade_data)

        # Hypothesis tracker: auto-add evidence
        if self._hypo_tracker:
            try:
                self._hypo_tracker.add_evidence_by_trade(trade_data)
            except Exception as e:
                logger.debug(f"[GROWTH] Hypothesis evidence error: {e}")

        # Explainability: track parameter change impact
        if self._explainer:
            try:
                win = trade_data.get("outcome") == "WIN"
                pnl = trade_data.get("pnl", 0)
                self._explainer.record_trade_outcome(win, pnl)
            except Exception as e:
                logger.debug(f"[GROWTH] Explainability outcome error: {e}")

        # Self-teaching: record for learning cycle
        if self._teaching_engine:
            try:
                self._teaching_engine.record_trade_for_learning(trade_data)
            except Exception as e:
                logger.debug(f"[GROWTH] Teaching record error: {e}")

        # Multi-Agent Learning Agent: run dedicated LLM analysis on closed trade
        # This produces deeper insights than the deterministic post_trade_learner
        # Skip in backtest mode to avoid burning LLM credits
        if not self._backtest_mode:
            try:
                from llm.agents.coordinator import is_multi_agent_enabled, get_coordinator
                if is_multi_agent_enabled():
                    coordinator = get_coordinator()
                    lesson_data = coordinator.get_post_trade_lesson(trade_data)
                    if lesson_data:
                        from llm.agents.learning_integration import process_agent_lesson
                        process_agent_lesson(lesson_data, trade_data)
            except Exception as e:
                logger.debug(f"[GROWTH] Multi-agent learning error: {e}")

        logger.debug(
            f"[GROWTH] Trade closed: {trade_data.get('symbol')} "
            f"{trade_data.get('outcome')} ${trade_data.get('pnl', 0):+.2f}"
        )

    def on_veto(
        self,
        symbol: str,
        side: str,
        confidence: float,
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        tp2_price: float = 0.0,
        llm_reason: str = "",
        regime: str = "",
        trigger: str = "",
        strategies_agreed: int = 0,
    ) -> Optional[str]:
        """Called when the LLM vetoes a trade. Returns veto_id."""
        self._ensure_init()

        veto_id = None
        if self._veto_tracker:
            try:
                veto_id = self._veto_tracker.record_veto(
                    symbol=symbol,
                    side=side,
                    confidence=confidence,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    llm_reason=llm_reason,
                    regime=regime,
                    trigger=trigger,
                    strategies_agreed=strategies_agreed,
                )
            except Exception as e:
                logger.warning(f"[GROWTH] Veto record error: {e}")

        # Also create a recommendation about the veto pattern
        if self._rec_engine and confidence >= 70:
            try:
                self._rec_engine.add_recommendation(
                    rec_type="avoidance",
                    title=f"Vetoed high-conf {symbol} {side} ({confidence:.0f}%)",
                    description=f"LLM vetoed: {llm_reason[:100]}",
                    suggested_action=f"Monitor {symbol} {side} outcome to validate veto",
                    source="veto_feedback",
                    confidence=0.5,
                    auto_applicable=False,
                )
            except Exception:
                pass

        return veto_id

    def on_parameter_change(
        self,
        parameter: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        source: str,
        context: Dict = None,
    ):
        """Called when any system parameter changes."""
        self._ensure_init()

        if self._explainer:
            try:
                self._explainer.record_change(
                    parameter=parameter,
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason,
                    source=source,
                    context=context,
                )
            except Exception as e:
                logger.debug(f"[GROWTH] Parameter change record error: {e}")

    def on_recommendation_from_llm(
        self,
        rec_type: str,
        title: str,
        description: str,
        suggested_action: str,
        confidence: float = 0.5,
    ):
        """Called when the LLM generates a recommendation in its response."""
        self._ensure_init()

        if self._rec_engine:
            try:
                self._rec_engine.add_recommendation(
                    rec_type=rec_type,
                    title=title,
                    description=description,
                    suggested_action=suggested_action,
                    source="llm_decision",
                    confidence=confidence,
                )
            except Exception as e:
                logger.debug(f"[GROWTH] LLM recommendation error: {e}")

    # ── Periodic Tick ─────────────────────────────────────────

    def tick(
        self,
        current_prices: Dict[str, Dict[str, float]] = None,
        market_state: Dict[str, Any] = None,
    ):
        """Called every main loop iteration. Runs periodic growth tasks.

        current_prices: {"BTC": {"high": X, "low": Y, "close": Z}} for veto resolution
        """
        self._ensure_init()

        now = time.time()
        if (now - self._last_tick_time) < self._tick_interval_s:
            return
        self._last_tick_time = now

        # 1. Resolve pending vetoes using current prices
        if self._veto_tracker and current_prices:
            try:
                self._veto_tracker.check_unresolved(current_prices)
            except Exception as e:
                logger.debug(f"[GROWTH] Veto resolution error: {e}")

        # 2. Check hypothesis graduation
        if self._hypo_tracker:
            try:
                graduated = self._hypo_tracker.check_graduation()
                if graduated:
                    logger.info(
                        f"[GROWTH] {len(graduated)} hypotheses graduated"
                    )
                    # Convert graduated hypotheses to recommendations
                    if self._rec_engine:
                        for h in graduated:
                            rec_type = "rule" if h.stage == "validated" else "avoidance"
                            # Auto-apply validated hypotheses with strong evidence
                            # (70%+ ratio, 15+ trades) — these are proven patterns
                            _auto = (
                                h.stage == "validated"
                                and h.total_evidence >= 15
                                and h.evidence_ratio >= 0.70
                            )
                            self._rec_engine.add_recommendation(
                                rec_type=rec_type,
                                title=f"Graduated: {h.statement[:80]}",
                                description=(
                                    f"{'VALIDATED' if h.stage == 'validated' else 'INVALIDATED'}: "
                                    f"{h.supporting_count} for, {h.contradicting_count} against"
                                ),
                                suggested_action=f"Codify as {h.graduated_to}",
                                source="hypothesis_tracker",
                                confidence=h.confidence,
                                auto_applicable=_auto,
                            )
                            if _auto:
                                logger.info(
                                    f"[GROWTH] Auto-applicable: {h.statement[:60]} "
                                    f"({h.supporting_count}/{h.total_evidence} = {h.evidence_ratio:.0%})"
                                )
            except Exception as e:
                logger.debug(f"[GROWTH] Hypothesis graduation error: {e}")

        # 3. Run learning cycle if due
        if (now - self._last_learning_cycle) >= self._learning_cycle_interval_s:
            self._run_learning_cycle(market_state)
            self._last_learning_cycle = now

        # 4. Apply auto-safe improvement proposals (with real dispatch)
        if self._improvement_engine:
            try:
                auto = self._improvement_engine.get_auto_applicable()
                for proposal in auto[:5]:  # Max 5 auto-applications per tick
                    logger.info(
                        f"[GROWTH] Auto-applying: {proposal.title}"
                    )
                    # Actually dispatch the proposal action (not just mark as applied)
                    dispatched = False
                    try:
                        from llm.learning_integrator import get_learning_integrator
                        dispatched = get_learning_integrator().dispatch_proposal(proposal)
                    except Exception as de:
                        logger.debug(f"[GROWTH] Dispatch error: {de}")

                    self._improvement_engine.apply_proposal(
                        proposal.proposal_id,
                        outcome_notes=(
                            "Auto-applied and dispatched" if dispatched
                            else "Auto-applied (display-only, no dispatcher)"
                        ),
                    )
            except Exception as e:
                logger.debug(f"[GROWTH] Auto-apply error: {e}")

        # 5. Generate growth report if due
        if self._reporter:
            try:
                if self._reporter.should_generate():
                    self._reporter.generate_report()
            except Exception as e:
                logger.debug(f"[GROWTH] Report generation error: {e}")

        # 6. Run Overseer meta-optimizer (every 30 min)
        if not hasattr(self, "_last_overseer_time"):
            self._last_overseer_time = 0.0
        if (now - self._last_overseer_time) >= 1800:  # 30 minutes
            try:
                from llm.agents.coordinator import is_multi_agent_enabled, get_coordinator
                overseer_enabled = os.environ.get("AGENT_OVERSEER_ENABLED", "true").lower()
                if is_multi_agent_enabled() and overseer_enabled not in ("0", "false", "no"):
                    coordinator = get_coordinator()
                    result = coordinator.run_overseer()
                    if result:
                        logger.info(
                            f"[GROWTH] Overseer analysis complete: "
                            f"health={result.get('system_health', '?')}, "
                            f"{len(result.get('recommendations', []))} recommendations"
                        )
                    self._last_overseer_time = now
            except Exception as e:
                logger.debug(f"[GROWTH] Overseer error: {e}")
                self._last_overseer_time = now  # Don't retry immediately

    def _run_learning_cycle(self, market_state: Dict[str, Any] = None):
        """Run a self-teaching learning cycle on buffered trades."""
        if not self._teaching_engine:
            return

        if not self._trade_buffer:
            return

        try:
            report = self._teaching_engine.run_learning_cycle(
                recent_trades=self._trade_buffer,
                market_state=market_state,
            )

            # Generate improvement proposals from performance
            if self._improvement_engine and len(self._trade_buffer) >= 10:
                self._improvement_engine.generate_proposals_from_performance(
                    self._trade_buffer
                )

            # Propose hypotheses from patterns found
            if self._hypo_tracker:
                for pattern in report.get("hypotheses_generated", []):
                    self._hypo_tracker.propose(
                        statement=pattern.get("hypothesis", ""),
                        test_criteria=f"Validate over next 20+ trades",
                        category=pattern.get("category", "general"),
                        tags=pattern.get("tags", []),
                        proposed_by="self_teaching",
                    )

            logger.info(
                f"[GROWTH] Learning cycle: {len(self._trade_buffer)} trades, "
                f"{len(report.get('patterns_found', []))} patterns, "
                f"{len(report.get('hypotheses_generated', []))} hypotheses"
            )

            # Clear buffer after processing (keep last 5 for continuity)
            self._trade_buffer = self._trade_buffer[-5:]

        except Exception as e:
            logger.warning(f"[GROWTH] Learning cycle error: {e}")

    # ── LLM Context Generation ────────────────────────────────

    def get_llm_context(self, symbol: str = "", regime: str = "") -> str:
        """Get compact growth intelligence for LLM prompt injection.

        Returns a multi-line string containing:
        - Knowledge base summary (axioms, principles, anti-patterns)
        - Active hypotheses
        - Recent recommendation outcomes
        - Parameter change trail
        - Veto feedback
        - Self-improvement status
        """
        self._ensure_init()
        parts = []

        # Knowledge base from self-teaching
        if self._teaching_engine:
            try:
                knowledge = self._teaching_engine.get_knowledge_for_prompt(
                    symbol=symbol, regime=regime
                )
                if knowledge:
                    parts.append(knowledge)
            except Exception:
                pass

        # Growth report (combines all subsystems)
        if self._reporter:
            try:
                llm_str = self._reporter.format_for_llm_prompt()
                if llm_str:
                    parts.append(llm_str)
            except Exception:
                pass

        return "\n\n".join(parts) if parts else ""

    # ── Telegram Display ──────────────────────────────────────

    def format_telegram_dashboard(self) -> str:
        """Format a comprehensive Telegram dashboard of all growth systems."""
        self._ensure_init()
        sections = []

        if self._reporter:
            try:
                sections.append(self._reporter.format_telegram())
            except Exception:
                pass

        if self._veto_tracker:
            try:
                veto_msg = self._veto_tracker.format_telegram()
                if veto_msg and "No vetoes" not in veto_msg:
                    sections.append(veto_msg)
            except Exception:
                pass

        if self._improvement_engine:
            try:
                imp_msg = self._improvement_engine.format_telegram()
                if imp_msg and "No pending" not in imp_msg:
                    sections.append(imp_msg)
            except Exception:
                pass

        return "\n\n".join(sections) if sections else "Growth intelligence: initializing..."

    # ── Stats ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics from all subsystems."""
        self._ensure_init()
        stats = {"trade_buffer_size": len(self._trade_buffer)}

        if self._rec_engine:
            try:
                stats["recommendations"] = self._rec_engine.get_stats()
            except Exception:
                pass

        if self._hypo_tracker:
            try:
                stats["hypotheses"] = self._hypo_tracker.get_stats()
            except Exception:
                pass

        if self._veto_tracker:
            try:
                stats["veto_feedback"] = self._veto_tracker.get_stats()
            except Exception:
                pass

        if self._improvement_engine:
            try:
                stats["self_improvement"] = self._improvement_engine.get_stats()
            except Exception:
                pass

        if self._teaching_engine:
            try:
                stats["curriculum"] = self._teaching_engine.get_curriculum_report()
            except Exception:
                pass

        return stats


# ── Singleton ─────────────────────────────────────────────

_orchestrator: Optional[GrowthOrchestrator] = None


def get_growth_orchestrator() -> GrowthOrchestrator:
    """Get the singleton GrowthOrchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GrowthOrchestrator()
    return _orchestrator
