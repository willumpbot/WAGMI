"""
Agent Coordinator: orchestrates the multi-agent LLM decision pipeline.

Instead of one big LLM call that does everything (regime + decision + sizing
+ learning + self-critique), the coordinator runs focused specialist agents
in a logical chain:

  1. Regime Agent   → classify regime (Haiku — fast, cheap)
  2. Trade Agent    → decide action (Sonnet — main brain)
  3. Risk Agent     → size position + strategy weights (Haiku)
  4. Critic Agent   → review & adjust before execution (Sonnet)
  5. Learning Agent → extract lesson from closed trade (Haiku, async)

Benefits over monolithic:
  - Each agent gets a focused prompt → better at its domain
  - Smaller max_tokens per call → faster response, lower cost
  - Critic can veto overconfident decisions the trade agent wouldn't catch
  - Learning agent runs *after* trade closes, not mixed into pre-trade call
  - Easy to A/B test or swap individual agents

Enable: LLM_MULTI_AGENT=true
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from llm.agents.base import (
    AgentConfig,
    AgentOutput,
    AgentRole,
    DEFAULT_AGENT_CONFIGS,
)
from llm.agents.prompts import AGENT_PROMPTS
from llm.agents.shared_context import (
    build_shared_context_block,
    get_pipeline_scratchpad,
    get_shared_lessons,
    reset_pipeline_scratchpad,
    score_confluence,
)
from llm.agents.thought_protocol import build_protocol_prefix
from llm.agents.consistency_checker import (
    check_pipeline_consistency,
    get_consistency_tracker,
)
from llm.client import call_llm
from llm.decision_types import LLMDecision, StrategyWeights

logger = logging.getLogger("bot.llm.agents.coordinator")


def is_multi_agent_enabled() -> bool:
    """Check if multi-agent mode is enabled."""
    return os.getenv("LLM_MULTI_AGENT", "").lower() in ("1", "true", "yes")


class AgentCoordinator:
    """Orchestrates specialist agents for trading decisions.

    The coordinator manages:
      - Agent sequencing (regime → trade → risk → critic)
      - Context passing between agents (each sees prior agents' output)
      - Model routing per agent (uses tier system or per-agent override)
      - Failure handling (required agents abort pipeline, optional degrade)
      - Token budget tracking
    """

    def __init__(self, agent_configs: Optional[Dict[AgentRole, AgentConfig]] = None):
        self.configs = agent_configs or dict(DEFAULT_AGENT_CONFIGS)
        self._call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_latency_ms = 0

    # ── Public API ──────────────────────────────────────────────

    def get_trading_decision(
        self,
        snapshot_data: dict,
        trigger_reason: str = "",
        model_for_trigger: Optional[str] = None,
    ) -> Optional[LLMDecision]:
        """Run the multi-agent pipeline and return a merged LLMDecision.

        Args:
            snapshot_data: The compact snapshot dict (same format as monolithic).
            trigger_reason: Why the LLM was called.
            model_for_trigger: Tier-routed model (fallback for agents without override).

        Returns:
            Merged LLMDecision or None on failure.
        """
        start = time.monotonic()
        pipeline_results: Dict[AgentRole, AgentOutput] = {}

        # Reset per-pipeline shared state
        scratchpad = reset_pipeline_scratchpad()
        shared_lessons = get_shared_lessons()

        # ── Step 1: Regime Agent ────────────────────────────────
        regime_input = self._build_regime_input(snapshot_data)
        regime_out = self._call_agent(
            AgentRole.REGIME, regime_input, model_for_trigger
        )
        pipeline_results[AgentRole.REGIME] = regime_out

        if not regime_out.ok:
            if self.configs[AgentRole.REGIME].required:
                logger.warning("[MULTI-AGENT] Regime agent failed — aborting pipeline")
                return None
            # Fallback: unknown regime
            regime_out = AgentOutput(
                role=AgentRole.REGIME,
                data={"rg": "unknown", "conf": 0.3, "factors": "regime agent failed",
                      "bias": "neutral", "transition": "uncertain"},
            )

        # Write regime output to scratchpad for downstream agents
        scratchpad.write("regime", "regime", regime_out.data.get("rg", "unknown"))
        scratchpad.write("regime", "regime_conf", regime_out.data.get("conf", 0.5))
        scratchpad.write("regime", "bias", regime_out.data.get("bias", "neutral"))
        if regime_out.data.get("outlook"):
            scratchpad.write("regime", "outlook", regime_out.data["outlook"])

        # ── Step 2: Trade Agent ─────────────────────────────────
        trade_input = self._build_trade_input(snapshot_data, regime_out)
        trade_out = self._call_agent(
            AgentRole.TRADE, trade_input, model_for_trigger
        )
        pipeline_results[AgentRole.TRADE] = trade_out

        if not trade_out.ok:
            if self.configs[AgentRole.TRADE].required:
                logger.warning("[MULTI-AGENT] Trade agent failed — aborting pipeline")
                return None
            # Fallback: skip
            trade_out = AgentOutput(
                role=AgentRole.TRADE,
                data={"a": "skip", "c": 0.0, "n": "trade agent failed"},
            )

        # Write trade output to scratchpad for downstream agents
        scratchpad.write("trade", "action", trade_out.data.get("a", "skip"))
        scratchpad.write("trade", "confidence", trade_out.data.get("c", 0.0))
        if trade_out.data.get("thesis"):
            scratchpad.write("trade", "thesis", trade_out.data["thesis"])

        # ── Step 3: Risk Agent (optional) ───────────────────────
        risk_out = None
        if self.configs.get(AgentRole.RISK, AgentConfig(role=AgentRole.RISK)).enabled:
            risk_input = self._build_risk_input(snapshot_data, regime_out, trade_out)
            risk_out = self._call_agent(
                AgentRole.RISK, risk_input, model_for_trigger
            )
            pipeline_results[AgentRole.RISK] = risk_out
            if not risk_out.ok:
                risk_out = None  # Degrade gracefully

        # ── Step 4: Critic Agent (optional) ─────────────────────
        critic_out = None
        if self.configs.get(AgentRole.CRITIC, AgentConfig(role=AgentRole.CRITIC)).enabled:
            critic_input = self._build_critic_input(
                snapshot_data, regime_out, trade_out, risk_out
            )
            critic_out = self._call_agent(
                AgentRole.CRITIC, critic_input, model_for_trigger
            )
            pipeline_results[AgentRole.CRITIC] = critic_out
            if not critic_out.ok:
                critic_out = None

        # ── Consistency Check ──────────────────────────────────────
        consistency_report = check_pipeline_consistency(
            regime_data=regime_out.data if regime_out.ok else {},
            trade_data=trade_out.data if trade_out.ok else {},
            risk_data=risk_out.data if risk_out and risk_out.ok else None,
            critic_data=critic_out.data if critic_out and critic_out.ok else None,
        )
        get_consistency_tracker().record(consistency_report)

        if not consistency_report.is_consistent:
            logger.warning(
                f"[MULTI-AGENT] Pipeline inconsistency detected: "
                f"{consistency_report.summary()}"
            )
            # On critical inconsistency: override to skip for safety
            critical_issues = [
                i for i in consistency_report.issues if i.severity == "critical"
            ]
            if critical_issues:
                logger.warning(
                    f"[MULTI-AGENT] Critical issues found — overriding to skip: "
                    f"{[i.description[:80] for i in critical_issues]}"
                )
                trade_out = AgentOutput(
                    role=AgentRole.TRADE,
                    data={
                        "a": "skip",
                        "c": 0.0,
                        "n": f"consistency_override: {critical_issues[0].description[:100]}",
                    },
                )

        # ── Merge into LLMDecision ──────────────────────────────
        decision = self._merge_outputs(regime_out, trade_out, risk_out, critic_out, snapshot_data)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._total_latency_ms += elapsed_ms

        agents_called = sum(1 for r in pipeline_results.values() if r.ok)
        consistency_score = consistency_report.score
        logger.info(
            f"[MULTI-AGENT] Pipeline done: {agents_called} agents, "
            f"{elapsed_ms}ms total, action={decision.action} "
            f"conf={decision.confidence:.2f} regime={decision.regime} "
            f"consistency={consistency_score:.2f}"
        )

        # Append consistency score to decision notes for audit trail
        if decision.notes and consistency_score < 1.0:
            decision = LLMDecision(
                action=decision.action,
                confidence=decision.confidence,
                regime=decision.regime,
                strategy_weights=decision.strategy_weights,
                memory_update=decision.memory_update,
                notes=f"{decision.notes} | CONSISTENCY={consistency_score:.2f}",
                size_multiplier=decision.size_multiplier,
                entry_adjustment=decision.entry_adjustment,
            )

        # ── Feed decision pipeline into learning systems ────────
        try:
            from llm.agents.learning_integration import process_agent_decision_for_learning
            process_agent_decision_for_learning(
                decision_notes=decision.notes,
                regime_data=regime_out.data if regime_out.ok else {},
                critic_data=critic_out.data if critic_out and critic_out.ok else None,
                trade_context=trigger_reason,
            )
        except Exception as e:
            logger.debug(f"[MULTI-AGENT] Decision learning error: {e}")

        return decision

    def get_post_trade_lesson(
        self,
        trade_data: Dict[str, Any],
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run the Learning Agent on a closed trade.

        Returns parsed lesson dict or None.
        """
        if not self.configs.get(AgentRole.LEARNING, AgentConfig(role=AgentRole.LEARNING)).enabled:
            return None

        learning_input = self._build_learning_input(trade_data)
        out = self._call_agent(AgentRole.LEARNING, learning_input, model_for_trigger)

        if out.ok:
            logger.info(
                f"[MULTI-AGENT] Learning agent lesson: "
                f"{out.data.get('lesson', '')[:80]}"
            )
            return out.data
        return None

    def get_exit_intelligence(
        self,
        position_data: Dict[str, Any],
        market_data: Optional[dict] = None,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run the Exit Intelligence Agent on an open position.

        Args:
            position_data: Open position state (symbol, side, entry, sl, tp1, tp2,
                           unrealized_pnl, hold_time_s, state, thesis, setup_type)
            market_data: Current market snapshot (regime, BTC direction, funding, signals)
            model_for_trigger: Model override (defaults to Haiku for cost efficiency)

        Returns:
            Parsed exit recommendation dict or None.
        """
        if not self.configs.get(AgentRole.EXIT, AgentConfig(role=AgentRole.EXIT)).enabled:
            return None

        exit_input = self._build_exit_input(position_data, market_data)
        out = self._call_agent(AgentRole.EXIT, exit_input, model_for_trigger)

        if out.ok:
            action = out.data.get("action", "hold")
            urgency = out.data.get("urgency", "low")
            logger.info(
                f"[MULTI-AGENT] Exit agent: {position_data.get('symbol', '?')} "
                f"action={action} urgency={urgency} "
                f"thesis_valid={out.data.get('thesis_still_valid', '?')} "
                f"reason={out.data.get('reason', '')[:60]}"
            )
            return out.data
        return None

    def _build_exit_input(
        self, position_data: Dict[str, Any], market_data: Optional[dict] = None
    ) -> str:
        """Build exit agent input: position state + current market + thesis context."""
        exit_data = dict(position_data)

        # Inject current market context if available
        if market_data:
            if "m" in market_data:
                # Extract just the relevant market for this symbol
                symbol = position_data.get("symbol", "")
                for m in market_data.get("m", []):
                    if m.get("s") == symbol or m.get("sym") == symbol:
                        exit_data["current_market"] = m
                        break
            if "g" in market_data:
                exit_data["global"] = market_data["g"]

            # Run a quick regime classification from scratchpad if available
            scratchpad = get_pipeline_scratchpad()
            regime = scratchpad.read_by_key("regime")
            if regime:
                exit_data["current_regime"] = regime
                exit_data["regime_bias"] = scratchpad.read_by_key("bias") or "neutral"
                exit_data["regime_outlook"] = scratchpad.read_by_key("outlook") or ""

        # Add deep memory context for this symbol's exit patterns
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            symbol = position_data.get("symbol", "")
            regime = position_data.get("regime", "")
            summary = dm.build_llm_knowledge_summary(
                symbol=symbol, regime=regime, max_tokens=300
            )
            if summary:
                exit_data["exit_history"] = summary[:300]
        except Exception:
            pass

        return json.dumps(exit_data, separators=(",", ":"))

    def run_scout(
        self,
        scout_data: Dict[str, Any],
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run the Scout/Preparation Agent during idle time.

        The Scout Agent runs between signal evaluations to:
        - Identify setups forming (approaching key levels)
        - Pre-form directional theses for likely trades
        - Forecast regime transitions
        - Surface lead-lag opportunities
        - Calculate risk budget and correlation warnings

        Results are written to the pipeline scratchpad so downstream
        agents (Trade, Risk) can read preparation data.

        Args:
            scout_data: Market overview (all symbols, prices, levels, regime, positions)
            model_for_trigger: Model override (defaults to Haiku)

        Returns:
            Parsed scout output dict or None.
        """
        if not self.configs.get(AgentRole.SCOUT, AgentConfig(role=AgentRole.SCOUT)).enabled:
            return None

        scout_input = json.dumps(scout_data, separators=(",", ":"))
        out = self._call_agent(AgentRole.SCOUT, scout_input, model_for_trigger)

        if out.ok:
            # Write scout findings to scratchpad for Trade Agent to consume
            scratchpad = get_pipeline_scratchpad()

            watchlist = out.data.get("watchlist", [])
            if watchlist:
                scratchpad.write("scout", "watchlist", watchlist)
                high_priority = [w for w in watchlist if w.get("priority") == "high"]
                if high_priority:
                    scratchpad.write("scout", "high_priority_setups", high_priority)

            regime_forecast = out.data.get("regime_forecast")
            if regime_forecast:
                scratchpad.write("scout", "regime_forecast", regime_forecast)

            lead_lag = out.data.get("lead_lag_alerts", [])
            if lead_lag:
                scratchpad.write("scout", "lead_lag_alerts", lead_lag)

            corr_warning = out.data.get("correlation_warning")
            if corr_warning:
                scratchpad.write("scout", "correlation_warning", corr_warning)

            risk_budget = out.data.get("risk_budget")
            if risk_budget:
                scratchpad.write("scout", "risk_budget", risk_budget)

            logger.info(
                f"[MULTI-AGENT] Scout: {len(watchlist)} watchlist items, "
                f"regime_forecast={regime_forecast.get('direction', '?') if regime_forecast else 'none'}, "
                f"lead_lag={len(lead_lag)} alerts"
            )
            return out.data
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Return coordinator statistics."""
        return {
            "total_calls": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": (
                self._total_latency_ms // max(self._call_count, 1)
            ),
        }

    # ── Agent calling ───────────────────────────────────────────

    def _call_agent(
        self,
        role: AgentRole,
        input_json: str,
        fallback_model: Optional[str] = None,
    ) -> AgentOutput:
        """Call a single specialist agent."""
        config = self.configs.get(role, DEFAULT_AGENT_CONFIGS.get(role))
        if config is None or not config.enabled:
            return AgentOutput(role=role, data={}, error="disabled")

        prompt = AGENT_PROMPTS.get(role.value)
        if not prompt:
            return AgentOutput(role=role, data={}, error="no_prompt")

        # Inject thought protocol and shared context into the prompt
        protocol_prefix = build_protocol_prefix(role.value)
        scratchpad = get_pipeline_scratchpad()
        shared_context = build_shared_context_block(
            agent_role=role.value,
            scratchpad=scratchpad,
            shared_lessons=get_shared_lessons(),
            include_axioms=(role in (AgentRole.TRADE, AgentRole.CRITIC)),
            include_regime_map=(role in (AgentRole.TRADE, AgentRole.CRITIC)),
            include_strategy_theory=(role in (AgentRole.TRADE, AgentRole.CRITIC)),
            current_regime=scratchpad.read_by_key("regime") or "",
        )

        # Prepend protocol and context to the agent's system prompt
        enhanced_prompt = prompt
        if protocol_prefix:
            enhanced_prompt = f"{protocol_prefix}\n\n{enhanced_prompt}"
        if shared_context:
            enhanced_prompt = f"{enhanced_prompt}\n\nSHARED CONTEXT: {shared_context}"

        model = config.model_override or fallback_model or _get_default_model(role)

        raw_text, usage = call_llm(
            system_prompt=enhanced_prompt,
            snapshot_json=input_json,
            model=model,
            max_tokens=config.max_tokens,
            max_retries=1,  # Agents get 1 retry (speed > reliability)
            timeout=config.timeout_s,
        )

        self._call_count += 1
        self._total_input_tokens += usage.get("input_tokens", 0)
        self._total_output_tokens += usage.get("output_tokens", 0)

        if raw_text is None:
            return AgentOutput(
                role=role,
                data={},
                model_used=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                latency_ms=usage.get("latency_ms", 0),
                error=f"api_error: {usage.get('error', 'unknown')}",
            )

        # Parse JSON response
        parsed = _parse_agent_json(raw_text)
        if parsed is None:
            return AgentOutput(
                role=role,
                data={},
                raw_text=raw_text[:500],
                model_used=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                latency_ms=usage.get("latency_ms", 0),
                error=f"json_parse_failed",
            )

        return AgentOutput(
            role=role,
            data=parsed,
            raw_text=raw_text[:500],
            model_used=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=usage.get("latency_ms", 0),
        )

    # ── Input builders ──────────────────────────────────────────
    # Each agent gets the FULL context relevant to its domain.
    # The snapshot dict contains these rich knowledge fields:
    #   knowledge      — axioms, principles, anti-patterns from self-teaching curriculum
    #   deep_memory    — trade DNA, strategy fingerprints, pattern library, regime history
    #   examples       — few-shot examples of similar past trades
    #   growth         — growth intelligence (hypotheses, recommendations, recent outcomes)
    #   survival       — accountability/survival pressure context
    #   self_perf      — LLM's own track record (accuracy, calibration, regime WR)
    #   recent_dec     — last 3 decisions for consistency
    #   recent_lessons — immediate feedback from closed trades
    #   autopsy        — structured analysis of last 5 trades
    #   mem            — short-term memory notes
    #   session_perf   — win rates by trading session
    #   regime_shifts  — symbols with regime transitions
    #   cross_sym      — cross-symbol lead-lag signals
    #   cross_pat      — validated cross-symbol patterns

    def _build_regime_input(self, snapshot: dict) -> str:
        """Build regime agent input: markets + global + regime history.

        The Regime Agent needs:
        - Raw market data (prices, volume, funding, OI) to classify regime
        - Regime transition history to detect shifts
        - Cross-symbol data for correlation analysis
        - Deep memory regime history for pattern matching
        """
        regime_data = {}
        if "m" in snapshot:
            regime_data["markets"] = snapshot["m"]
        if "g" in snapshot:
            regime_data["global"] = snapshot["g"]
        # Regime-specific knowledge
        if "regime_shifts" in snapshot:
            regime_data["regime_shifts"] = snapshot["regime_shifts"]
        if "cross_sym" in snapshot:
            regime_data["cross_symbol_signals"] = snapshot["cross_sym"]
        if "cross_pat" in snapshot:
            regime_data["cross_patterns"] = snapshot["cross_pat"]
        # Deep memory regime section (extract just regime history if available)
        if "deep_memory" in snapshot:
            dm = str(snapshot["deep_memory"])
            # Find regime-relevant sections
            regime_section = _extract_section(dm, "REGIME", 300)
            if regime_section:
                regime_data["regime_history"] = regime_section
        return json.dumps(regime_data, separators=(",", ":"))

    def _build_trade_input(self, snapshot: dict, regime_out: AgentOutput) -> str:
        """Build trade agent input: FULL context for the main decision-maker.

        The Trade Agent is the primary brain — it gets EVERYTHING:
        - Full market snapshot (prices, signals, volume, funding, OI)
        - Regime classification from the Regime Agent
        - Knowledge base (axioms, principles from self-teaching curriculum)
        - Deep memory (trade DNA, strategy fingerprints, pattern library)
        - Few-shot examples of similar past trades
        - Growth intelligence (hypotheses, recommendations, learning progress)
        - Recent decisions (for consistency)
        - Recent lessons (immediate feedback from closed trades)
        - Trade autopsy (structured analysis of last batch)
        - Memory notes (short-term observations)
        - Session performance (time-of-day edge)
        - Survival pressure (accountability context)
        """
        trade_data = dict(snapshot)
        # Inject regime agent's output so trade agent knows the classified regime
        trade_data["regime_analysis"] = regime_out.data

        # Compute and inject confluence quality scoring
        confluence = _compute_confluence_from_snapshot(
            snapshot, regime_out.data.get("rg", "unknown")
        )
        if confluence:
            trade_data["confluence"] = confluence

        # Ensure all knowledge/learning fields are present with generous limits
        # (the Trade Agent is the decision-maker — don't starve it of context)
        _ensure_field(trade_data, "knowledge", snapshot, max_len=1000)
        _ensure_field(trade_data, "deep_memory", snapshot, max_len=1000)
        _ensure_field(trade_data, "examples", snapshot, max_len=600)
        _ensure_field(trade_data, "growth", snapshot, max_len=500)
        _ensure_field(trade_data, "survival", snapshot, max_len=300)
        _ensure_field(trade_data, "self_perf", snapshot)
        _ensure_field(trade_data, "recent_dec", snapshot)
        _ensure_field(trade_data, "recent_lessons", snapshot)
        _ensure_field(trade_data, "autopsy", snapshot)
        _ensure_field(trade_data, "mem", snapshot, max_len=800)
        _ensure_field(trade_data, "session_perf", snapshot)
        _ensure_field(trade_data, "cross_sym", snapshot)
        _ensure_field(trade_data, "cross_pat", snapshot)
        _ensure_field(trade_data, "corr_risk", snapshot)
        _ensure_field(trade_data, "port_lev", snapshot)
        _ensure_field(trade_data, "funding_cost_pct", snapshot)
        _ensure_field(trade_data, "funding_alert", snapshot)

        return json.dumps(trade_data, separators=(",", ":"))

    def _build_risk_input(
        self, snapshot: dict, regime_out: AgentOutput, trade_out: AgentOutput
    ) -> str:
        """Build risk agent input: portfolio state + trade decision + regime + risk knowledge.

        The Risk Agent needs:
        - The trade decision (to size it)
        - Regime classification (sizing depends on regime)
        - Full portfolio state (positions, leverage, correlation, funding)
        - Session performance (time-of-day risk)
        - Self-performance (are we on a losing streak?)
        - Recent autopsy (are we declining?)
        - Deep memory risk insights
        """
        risk_data = {
            "regime": regime_out.data,
            "trade_decision": trade_out.data,
        }
        # Portfolio data
        for key in ("g", "pos", "corr_risk", "port_lev", "funding_cost_pct",
                     "funding_alert", "session_perf"):
            if key in snapshot:
                risk_data[key] = snapshot[key]
        # Self-awareness for risk decisions (losing streak → reduce size)
        if "self_perf" in snapshot:
            risk_data["self_perf"] = snapshot["self_perf"]
        if "autopsy" in snapshot:
            risk_data["autopsy"] = snapshot["autopsy"]
        # Deep memory risk-relevant sections
        if "deep_memory" in snapshot:
            dm = str(snapshot["deep_memory"])
            risk_section = _extract_section(dm, "RISK", 200)
            strat_section = _extract_section(dm, "STRATEGY", 200)
            if risk_section:
                risk_data["risk_history"] = risk_section
            if strat_section:
                risk_data["strategy_history"] = strat_section
        # Recent lessons about sizing/risk
        if "recent_lessons" in snapshot:
            risk_data["recent_lessons"] = snapshot["recent_lessons"]
        return json.dumps(risk_data, separators=(",", ":"))

    def _build_critic_input(
        self,
        snapshot: dict,
        regime_out: AgentOutput,
        trade_out: AgentOutput,
        risk_out: Optional[AgentOutput],
    ) -> str:
        """Build critic input: all prior agent outputs + full self-awareness context.

        The Critic Agent is the quality gate — it needs:
        - All prior agent outputs (to check consistency)
        - Self-performance stats (to detect overconfidence/underconfidence)
        - Recent decisions (to check for flip-flopping)
        - Recent lessons (to check if similar setups failed)
        - Trade autopsy (to check for declining performance)
        - Knowledge base (axioms to verify against)
        - Growth intelligence (hypotheses to validate)
        """
        critic_data = {
            "regime_analysis": regime_out.data,
            "trade_decision": trade_out.data,
        }
        if risk_out and risk_out.ok:
            critic_data["risk_assessment"] = risk_out.data

        # Inject confluence quality so Critic can assess agreement type
        confluence = _compute_confluence_from_snapshot(
            snapshot, regime_out.data.get("rg", "unknown")
        )
        if confluence:
            critic_data["confluence"] = confluence
        # Full self-awareness context — the critic's primary tool
        for key in ("self_perf", "recent_dec", "recent_lessons", "autopsy"):
            if key in snapshot:
                critic_data[key] = snapshot[key]
        # Knowledge for verifying the decision against learned principles
        _ensure_field(critic_data, "knowledge", snapshot, max_len=500)
        # Growth context (hypotheses, recommendations)
        _ensure_field(critic_data, "growth", snapshot, max_len=300)
        # Portfolio state for risk validation
        for key in ("corr_risk", "port_lev", "funding_cost_pct"):
            if key in snapshot:
                critic_data[key] = snapshot[key]
        # Memory notes for pattern checking
        _ensure_field(critic_data, "mem", snapshot, max_len=400)
        return json.dumps(critic_data, separators=(",", ":"))

    def _build_learning_input(self, trade_data: Dict[str, Any]) -> str:
        """Build learning agent input from closed trade data + context.

        The Learning Agent needs:
        - Full trade outcome data (symbol, side, pnl, regime, timing, exit)
        - Prior knowledge context (what did we know going in?)
        - Self-performance (what's our track record for this type of trade?)
        """
        relevant = {}
        for key in (
            "symbol", "side", "outcome", "pnl", "regime", "strategy",
            "confidence", "hold_time_s", "exit_action", "exit_reason",
            "funding_rate", "entry_price", "exit_price",
            "llm_action", "llm_confidence", "num_strategies_agreed",
            "ensemble_confidence", "chop_score", "entry_type",
            "funding_paid", "leverage", "size_multiplier",
            "thesis", "counter_thesis", "setup_type", "confluence_quality",
        ):
            if key in trade_data:
                relevant[key] = trade_data[key]
        # Add any recent lessons for context (what have we learned before?)
        try:
            from llm.post_trade_learner import get_recent_lessons
            lessons = get_recent_lessons(3)
            if lessons:
                relevant["prior_lessons"] = " | ".join(lessons)
        except Exception:
            pass
        # Add deep memory context for this symbol/regime
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            sym = trade_data.get("symbol", "")
            regime = trade_data.get("regime", "")
            summary = dm.build_llm_knowledge_summary(
                symbol=sym, regime=regime, max_tokens=400
            )
            if summary:
                relevant["prior_knowledge"] = summary[:400]
        except Exception:
            pass
        return json.dumps(relevant, separators=(",", ":"))

    # ── Output merger ───────────────────────────────────────────

    def _merge_outputs(
        self,
        regime_out: AgentOutput,
        trade_out: AgentOutput,
        risk_out: Optional[AgentOutput],
        critic_out: Optional[AgentOutput],
        snapshot_data: Optional[dict] = None,
    ) -> LLMDecision:
        """Merge all agent outputs into a single LLMDecision.

        Priority chain:
          1. Critic can override action + adjust confidence
          2. Risk agent provides sizing + strategy weights
          3. Trade agent provides base action + confidence + reasoning
          4. Regime agent provides regime classification
        """
        # Start with Trade Agent's core decision
        td = trade_out.data
        action = _normalize_action(td.get("a", td.get("action", "flat")))
        confidence = float(td.get("c", td.get("confidence", 0.0)))
        notes = td.get("n", td.get("notes", ""))
        memory_update = td.get("mu", td.get("memory_update"))
        entry_adj = td.get("ea", td.get("entry_adjustment"))

        # Regime from Regime Agent
        rd = regime_out.data
        regime = rd.get("rg", rd.get("regime", "unknown"))
        regime_conf = float(rd.get("conf", rd.get("confidence", 0.5)))
        regime_bias = rd.get("bias", "neutral")
        regime_transition = rd.get("transition", "stable")

        # Enrich notes with regime info
        regime_note = f"regime={regime}({regime_conf:.0%})"
        if regime_bias != "neutral":
            regime_note += f" bias={regime_bias}"
        if regime_transition != "stable":
            regime_note += f" {regime_transition}"
        regime_outlook = rd.get("outlook", "")

        # Trade thesis
        trade_thesis = td.get("thesis", "")

        # Risk Agent: sizing + strategy weights
        size_mult = 1.0
        strategy_weights = StrategyWeights()
        risk_flags = []

        if risk_out and risk_out.ok:
            rk = risk_out.data
            size_mult = float(rk.get("sz", rk.get("size_multiplier", 1.0)))
            size_mult = max(0.0, min(2.0, size_mult))

            # Parse strategy weights
            sw_raw = rk.get("sw", rk.get("strategy_weights", {}))
            if isinstance(sw_raw, dict):
                strategy_weights = _parse_strategy_weights(sw_raw)

            risk_flags = rk.get("risks", [])
            override = rk.get("override")
            if override == "skip":
                action = "flat"
                notes += " | RISK: override to skip"
            elif override == "reduce" and size_mult > 0.7:
                size_mult = min(size_mult, 0.7)
                notes += " | RISK: reduced sizing"

        # Critic Agent: can adjust or override
        # Treat any non-"approve" verdict as a challenge (defensive normalization)
        counter_thesis = ""
        if critic_out and critic_out.ok:
            cd = critic_out.data
            verdict = cd.get("verdict", "approve").lower().strip()
            counter_thesis = cd.get("counter_thesis", "")

            if verdict != "approve":
                adj_action = cd.get("adjusted_action")
                adj_conf = cd.get("adjusted_confidence")
                reason = cd.get("reason", "")

                if adj_action:
                    old_action = action
                    action = _normalize_action(adj_action)
                    notes += f" | CRITIC: {old_action}→{action} ({reason[:60]})"

                if adj_conf is not None:
                    old_conf = confidence
                    confidence = float(adj_conf)
                    confidence = max(0.0, min(1.0, confidence))
                    notes += f" | CRITIC: conf {old_conf:.2f}→{confidence:.2f}"

                if counter_thesis:
                    notes += f" | COUNTER: {counter_thesis[:80]}"

            cal_note = cd.get("calibration_note")
            if cal_note:
                # Store as memory update if we don't already have one
                if not memory_update:
                    memory_update = cal_note[:100]

        # Add risk flags to notes
        if risk_flags:
            notes += f" | RISKS: {', '.join(str(f) for f in risk_flags[:3])}"

        # Confluence quality for notes
        confluence_info = _compute_confluence_from_snapshot(
            snapshot_data or {}, regime,
        )
        confl_note = ""
        setup_type = ""
        if confluence_info:
            setup_type = confluence_info.get("setup_type", "")
            confl_note = (
                f"CONFLUENCE: {confluence_info['count']}strat "
                f"q={confluence_info['quality']:.0%} "
                f"type={confluence_info['best_pair']} "
                f"setup={setup_type}"
            )

        # Build the final notes: regime + thesis + confluence + trade + risk + critic
        thesis_parts = []
        if regime_outlook:
            thesis_parts.append(f"OUTLOOK: {regime_outlook[:80]}")
        if trade_thesis:
            thesis_parts.append(f"THESIS: {trade_thesis[:80]}")
        thesis_block = " | ".join(thesis_parts)
        combined_notes = f"[MA] {regime_note}"
        if thesis_block:
            combined_notes += f" | {thesis_block}"
        if confl_note:
            combined_notes += f" | {confl_note}"
        combined_notes = f"{combined_notes} | {notes}"[:1500]

        return LLMDecision(
            action=action,
            confidence=confidence,
            regime=regime,
            strategy_weights=strategy_weights,
            memory_update=memory_update[:200] if memory_update else None,
            notes=combined_notes,
            size_multiplier=size_mult,
            entry_adjustment=entry_adj,
        )


# ── Module-level helpers ────────────────────────────────────────

_ACTION_MAP = {
    "go": "proceed", "proceed": "proceed", "long": "proceed", "short": "proceed",
    "buy": "proceed", "sell": "proceed", "enter": "proceed", "trade": "proceed",
    "skip": "flat", "flat": "flat", "hold": "flat", "pass": "flat",
    "wait": "flat", "no": "flat", "none": "flat",
    "flip": "flip", "reverse": "flip",
}


def _normalize_action(raw: str) -> str:
    """Normalize agent action output to canonical form."""
    return _ACTION_MAP.get(str(raw).lower().strip(), "flat")


def _parse_agent_json(raw_text: str) -> Optional[dict]:
    """Parse JSON from agent response, handling markdown fences."""
    import re
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        # Try extracting JSON from mixed text
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return None


_WEIGHT_KEY_MAP = {
    "rt": "regime_trend", "mc": "monte_carlo_zones",
    "cs": "confidence_scorer", "mq": "multi_tier_quality",
    "fr": "funding_rate", "oi": "open_interest",
    "vm": "volume_momentum", "ca": "cross_asset",
}


def _parse_strategy_weights(raw: dict) -> StrategyWeights:
    """Parse compact or full strategy weight keys."""
    expanded = {}
    for k, v in raw.items():
        full_key = _WEIGHT_KEY_MAP.get(k, k)
        try:
            expanded[full_key] = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            pass
    return StrategyWeights.from_dict(expanded)


def _ensure_field(
    target: dict, key: str, source: dict, max_len: Optional[int] = None
):
    """Copy a field from source to target if present, with optional truncation."""
    if key in source:
        val = source[key]
        if max_len and isinstance(val, str) and len(val) > max_len:
            val = val[:max_len]
        target[key] = val


def _extract_section(text: str, keyword: str, max_len: int = 300) -> Optional[str]:
    """Extract a section from deep memory text by keyword.

    Looks for lines containing the keyword and returns surrounding context.
    Stops at the next blank line after the keyword section to prevent bleeding.
    """
    lines = text.split("\n")
    result_lines = []
    capturing = False
    chars = 0
    for line in lines:
        if not capturing and keyword.upper() in line.upper():
            capturing = True
            result_lines.append(line)
            chars += len(line)
        elif capturing:
            if not line.strip():
                break  # End of section (blank line)
            result_lines.append(line)
            chars += len(line)
            if chars >= max_len:
                break
    return "\n".join(result_lines) if result_lines else None


def _compute_confluence_from_snapshot(
    snapshot: dict, regime: str
) -> Optional[Dict[str, Any]]:
    """Extract agreeing strategies from the snapshot and compute confluence quality."""
    try:
        markets = snapshot.get("m", [])
        if not markets:
            return None

        # Find the primary market (first one with signals)
        for market in markets:
            sigs = market.get("sg", [])
            if not sigs:
                continue

            # Find the consensus side
            side_counts: Dict[str, list] = {}
            for sig in sigs:
                sd = sig.get("sd", "neutral")
                if sd in ("neutral",):
                    continue
                side_counts.setdefault(sd, []).append(sig.get("st", ""))

            if not side_counts:
                continue

            # Get the majority side
            majority_side = max(side_counts, key=lambda s: len(side_counts[s]))
            agreeing = side_counts[majority_side]

            if agreeing:
                return score_confluence(agreeing, regime)

    except Exception:
        pass
    return None


def _get_default_model(role: AgentRole) -> str:
    """Default model per agent role when no tier routing is available."""
    # Regime + Risk + Learning use cheaper Haiku; Trade + Critic use Sonnet
    try:
        from llm.usage_tiers import MODEL_HAIKU, MODEL_SONNET
    except ImportError:
        return "claude-sonnet-4-5-20250929"

    if role in (AgentRole.REGIME, AgentRole.RISK, AgentRole.LEARNING, AgentRole.EXIT, AgentRole.SCOUT):
        return MODEL_HAIKU
    return MODEL_SONNET


# ── Singleton ───────────────────────────────────────────────────

_coordinator: Optional[AgentCoordinator] = None


def _build_configs_from_env() -> Dict[AgentRole, AgentConfig]:
    """Build agent configs from environment variables."""
    configs = dict(DEFAULT_AGENT_CONFIGS)

    # Per-agent model overrides
    env_model_map = {
        AgentRole.REGIME: "AGENT_REGIME_MODEL",
        AgentRole.TRADE: "AGENT_TRADE_MODEL",
        AgentRole.RISK: "AGENT_RISK_MODEL",
        AgentRole.LEARNING: "AGENT_LEARNING_MODEL",
        AgentRole.CRITIC: "AGENT_CRITIC_MODEL",
        AgentRole.EXIT: "AGENT_EXIT_MODEL",
        AgentRole.SCOUT: "AGENT_SCOUT_MODEL",
    }
    for role, env_key in env_model_map.items():
        model = os.getenv(env_key, "").strip()
        if model and role in configs:
            configs[role].model_override = model
            logger.info(f"[MULTI-AGENT] {role.value} model override: {model}")

    # Per-agent enable/disable
    env_enabled_map = {
        AgentRole.RISK: "AGENT_RISK_ENABLED",
        AgentRole.LEARNING: "AGENT_LEARNING_ENABLED",
        AgentRole.CRITIC: "AGENT_CRITIC_ENABLED",
        AgentRole.EXIT: "AGENT_EXIT_ENABLED",
        AgentRole.SCOUT: "AGENT_SCOUT_ENABLED",
    }
    for role, env_key in env_enabled_map.items():
        val = os.getenv(env_key, "true").lower()
        if val in ("0", "false", "no") and role in configs:
            configs[role].enabled = False
            logger.info(f"[MULTI-AGENT] {role.value} agent disabled via {env_key}")

    return configs


def get_coordinator() -> AgentCoordinator:
    """Get or create the singleton AgentCoordinator."""
    global _coordinator
    if _coordinator is None:
        configs = _build_configs_from_env()
        _coordinator = AgentCoordinator(agent_configs=configs)
        logger.info("[MULTI-AGENT] Coordinator initialized")
    return _coordinator
