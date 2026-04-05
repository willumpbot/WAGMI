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
from llm.agents.prompt_enricher import enrich_prompt
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

# External data collectors (funding/OI, liquidation, shadow MR)
try:
    from llm.agents.external_data import (
        get_external_data_for_snapshot,
        format_for_agent as format_external_data,
    )
    _EXTERNAL_DATA_AVAILABLE = True
except ImportError:
    _EXTERNAL_DATA_AVAILABLE = False

# Strategic agents (Portfolio, Forecaster, Hypothesis, Correlator)
# These are optional Phase 3 agents
try:
    from llm.agents.strategic_agents import (
        build_portfolio_aggregator,
        build_regime_forecaster,
        build_hypothesis_generator,
        build_correlator,
    )
    _STRATEGIC_AGENTS_AVAILABLE = True
except ImportError:
    _STRATEGIC_AGENTS_AVAILABLE = False

# Phase 4 agents (Scalping + Conviction)
# These are optional Phase 4 agents
try:
    from llm.agents.phase_4_agents import (
        build_micro_trend_detector,
        build_scalper,
        build_conviction,
    )
    _PHASE_4_AGENTS_AVAILABLE = True
except ImportError:
    _PHASE_4_AGENTS_AVAILABLE = False

# Phase 4A agents (Core Trading System)
# These are optional Phase 4A agents
try:
    from llm.agents.phase_4a_trading_agents import (
        build_position_sizer,
        build_entry_optimizer,
        build_exit_advisor,
        build_risk_guard,
        build_agent_router,
        build_consensus_builder,
    )
    _PHASE_4A_AGENTS_AVAILABLE = True
except ImportError:
    _PHASE_4A_AGENTS_AVAILABLE = False

# Technical indicators for agent context
try:
    from llm.agents.technicals import compute_all_technicals, format_technicals_for_agent
    _TECHNICALS_AVAILABLE = True
except ImportError:
    _TECHNICALS_AVAILABLE = False

# Feedback loop states for agent awareness
try:
    from llm.agents.feedback_state import format_feedback_for_agent
    _FEEDBACK_STATE_AVAILABLE = True
except ImportError:
    _FEEDBACK_STATE_AVAILABLE = False

# Position enrichment for richer position context
try:
    from llm.agents.position_enrichment import format_positions_for_agent
    _POSITION_ENRICHMENT_AVAILABLE = True
except ImportError:
    _POSITION_ENRICHMENT_AVAILABLE = False

# Portfolio-level intelligence (exposure, correlation, risk budget)
try:
    from llm.agents.portfolio_intelligence import (
        compute_portfolio_state,
        format_portfolio_for_agent,
    )
    _PORTFOLIO_INTEL_AVAILABLE = True
except ImportError:
    _PORTFOLIO_INTEL_AVAILABLE = False

# Pipeline telemetry (recent gate decisions)
try:
    from core.pipeline_telemetry import get_telemetry
    _TELEMETRY_AVAILABLE = True
except ImportError:
    _TELEMETRY_AVAILABLE = False

# Agent self-performance tracker (per-agent accuracy, calibration, veto stats)
try:
    from llm.agents.agent_performance import get_tracker as get_perf_tracker
    _AGENT_PERF_AVAILABLE = True
except ImportError:
    _AGENT_PERF_AVAILABLE = False

# Background thinker journal (market observations, position reviews, patterns)
try:
    from llm.agents.background_thinker import BackgroundThinker
    _BACKGROUND_THINKER_AVAILABLE = True
except ImportError:
    _BACKGROUND_THINKER_AVAILABLE = False

# Pre-trade simulator (scenario analysis before Trade Agent)
try:
    from llm.agents.pre_trade_simulator import PreTradeSimulator
    _SIMULATOR_AVAILABLE = True
except ImportError:
    _SIMULATOR_AVAILABLE = False

# Pipeline extensions: quant engine, agent brains, debate, telemetry
# These are optional — gracefully degrade if modules not yet built
try:
    from llm.agents.pipeline_extensions import (
        get_brain_context_for_agent,
        record_agent_decision,
        run_debate_if_warranted,
        run_interactive_debate_if_enabled,
        apply_debate_to_confidence,
        log_pipeline_telemetry,
        format_quant_for_prompt,
        compute_quant_context,
    )
    _EXTENSIONS_AVAILABLE = True
except ImportError:
    _EXTENSIONS_AVAILABLE = False

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
        # Delta tracking: return per-pipeline usage, not cumulative
        self._last_reported_calls = 0
        self._last_reported_input = 0
        self._last_reported_output = 0
        self._last_reported_latency = 0
        # Preserve per-agent outputs from last pipeline run for external consumers
        self.last_pipeline_results: Dict[AgentRole, AgentOutput] = {}
        self.last_exit_output: Optional[AgentOutput] = None
        self.last_consistency_score: Optional[float] = None
        # Lazy-initialized enrichment modules
        self._background_thinker: Optional[Any] = None
        self._pre_trade_simulator: Optional[Any] = None

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

        # ── Inject external data (funding/OI, liq levels, shadow MR) ──
        if _EXTERNAL_DATA_AVAILABLE:
            try:
                ext = get_external_data_for_snapshot()
                if ext:
                    snapshot_data.update(ext)
                    logger.info("[MULTI-AGENT] External data injected: %s",
                                ", ".join(ext.keys()))
            except Exception as e:
                logger.warning("[MULTI-AGENT] External data injection failed: %s", e)

        # ── Build enriched context for all agents ──────────────
        enriched_parts = []

        # Extract symbol from snapshot for context
        _enrich_symbol = ""
        _markets = snapshot_data.get("m", [])
        if _markets and isinstance(_markets, list) and _markets:
            _enrich_symbol = _markets[0].get("s", _markets[0].get("sym", ""))

        # Technical indicators (needs ohlcv_1h in snapshot)
        if _TECHNICALS_AVAILABLE:
            try:
                # Prefer per-symbol OHLCV matching the enrichment symbol
                _ohlcv = None
                _ohlcv_all = snapshot_data.get("ohlcv_by_symbol_1h", {})
                if _enrich_symbol and _ohlcv_all.get(_enrich_symbol):
                    _ohlcv = _ohlcv_all[_enrich_symbol]
                if not _ohlcv:
                    _ohlcv = snapshot_data.get("ohlcv_1h")
                if _ohlcv:
                    techs = compute_all_technicals(_ohlcv)
                    if techs:
                        tech_text = format_technicals_for_agent(techs, _enrich_symbol)
                        if tech_text:
                            enriched_parts.append(tech_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] Technicals enrichment failed: %s", e)

            # 5m micro-structure technicals (shorter-term signals)
            try:
                _ohlcv_5m = None
                _ohlcv_5m_all = snapshot_data.get("ohlcv_by_symbol_5m", {})
                if _enrich_symbol and _ohlcv_5m_all.get(_enrich_symbol):
                    _ohlcv_5m = _ohlcv_5m_all[_enrich_symbol]
                if not _ohlcv_5m:
                    _ohlcv_5m = snapshot_data.get("ohlcv_5m")
                if _ohlcv_5m:
                    techs_5m = compute_all_technicals(_ohlcv_5m)
                    if techs_5m:
                        tech_text_5m = format_technicals_for_agent(
                            techs_5m, _enrich_symbol, timeframe="5m"
                        )
                        if tech_text_5m:
                            enriched_parts.append(tech_text_5m)
            except Exception as e:
                logger.debug("[MULTI-AGENT] 5m technicals enrichment failed: %s", e)

        # External data (funding, OI, liquidation) — formatted text
        if _EXTERNAL_DATA_AVAILABLE:
            try:
                ext_text = format_external_data(["BTC", "ETH", "SOL", "HYPE"])
                if ext_text:
                    enriched_parts.append(ext_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] External data text enrichment failed: %s", e)

        # Feedback loop states (strategy weights, Kelly, adaptive risk, tuner)
        if _FEEDBACK_STATE_AVAILABLE:
            try:
                fb_text = format_feedback_for_agent()
                if fb_text:
                    enriched_parts.append(fb_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] Feedback state enrichment failed: %s", e)

        # Pipeline telemetry (recent gate decisions)
        if _TELEMETRY_AVAILABLE:
            try:
                tel_text = get_telemetry().format_for_llm(
                    symbol=_enrich_symbol, last_n=5
                )
                if tel_text:
                    enriched_parts.append(f"PIPELINE:\n{tel_text}")
            except Exception as e:
                logger.debug("[MULTI-AGENT] Telemetry enrichment failed: %s", e)

        # Position enrichment (rich position state for agents)
        if _POSITION_ENRICHMENT_AVAILABLE:
            try:
                _positions = snapshot_data.get("pos", {})
                _prices = {}
                for _mk in _markets:
                    _mk_sym = _mk.get("s", _mk.get("sym", ""))
                    _mk_price = _mk.get("p", _mk.get("price", 0))
                    if _mk_sym and _mk_price:
                        _prices[_mk_sym] = _mk_price
                if _positions:
                    pos_text = format_positions_for_agent(_positions, _prices)
                    if pos_text:
                        enriched_parts.append(pos_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] Position enrichment failed: %s", e)

        # Portfolio-level intelligence (exposure, correlation, risk budget)
        if _PORTFOLIO_INTEL_AVAILABLE:
            try:
                _positions = snapshot_data.get("pos", {})
                _prices = {}
                for _mk in _markets:
                    _mk_sym = _mk.get("s", _mk.get("sym", ""))
                    _mk_price = _mk.get("p", _mk.get("price", 0))
                    if _mk_sym and _mk_price:
                        _prices[_mk_sym] = _mk_price
                _equity = float(snapshot_data.get("g", {}).get("equity",
                                snapshot_data.get("g", {}).get("eq", 0)))
                if _equity > 0:
                    _port_state = compute_portfolio_state(_positions, _prices, _equity)
                    snapshot_data["_portfolio_state"] = _port_state
                    _port_text = format_portfolio_for_agent(_port_state)
                    if _port_text:
                        enriched_parts.append(_port_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] Portfolio intelligence failed: %s", e)

        # Agent self-performance: network-wide health summary for all agents
        if _AGENT_PERF_AVAILABLE:
            try:
                _perf_tracker = get_perf_tracker()
                _net_summary = _perf_tracker.format_network_summary()
                if _net_summary:
                    enriched_parts.append(_net_summary)
                # Store tracker reference on self (not in snapshot_data which gets JSON-serialized)
                self._perf_tracker_ref = _perf_tracker
                snapshot_data["_perf_tracker_summary"] = _net_summary or ""
            except Exception as e:
                logger.debug("[MULTI-AGENT] Agent performance enrichment failed: %s", e)

        # Background thinker journal (market observations, patterns, opportunities)
        if _BACKGROUND_THINKER_AVAILABLE:
            try:
                if self._background_thinker is None:
                    self._background_thinker = BackgroundThinker()
                journal_text = self._background_thinker.get_journal_for_agents(last_n=5)
                if journal_text:
                    enriched_parts.append(journal_text)
            except Exception as e:
                logger.debug("[MULTI-AGENT] Background thinker enrichment failed: %s", e)

        # Network learning: inject accumulated lessons from past trades
        try:
            from llm.agents.network_learning import get_network_learning
            _nl = get_network_learning()
            # Inject per-agent lessons into snapshot for downstream builders
            _nl_trade = _nl.get_prompt_injection("trade")
            _nl_risk = _nl.get_prompt_injection("risk")
            _nl_regime = _nl.get_regime_intelligence()
            _nl_critic = _nl.get_prompt_injection("critic")
            if _nl_trade:
                snapshot_data["network_lessons_trade"] = _nl_trade
            if _nl_risk:
                snapshot_data["network_lessons_risk"] = _nl_risk
                snapshot_data["risk_constraints"] = _nl.get_risk_constraints()
            if _nl_regime:
                enriched_parts.append(_nl_regime)
            if _nl_critic:
                snapshot_data["network_lessons_critic"] = _nl_critic
            # Calibration adjustment for Quant Agent
            _cal_adj = _nl.get_calibration_adjustment()
            if _cal_adj != 0:
                snapshot_data["network_calibration_adj"] = round(_cal_adj, 4)
            # Edge decay alerts for Overseer
            _decaying = _nl.get_decaying_edges()
            if _decaying:
                snapshot_data["edge_decay_alerts"] = _decaying
        except Exception as e:
            logger.debug("[MULTI-AGENT] Network learning injection failed: %s", e)

        enriched_context = "\n\n".join(enriched_parts) if enriched_parts else ""
        if enriched_context:
            snapshot_data["enriched_context"] = enriched_context
            logger.info("[MULTI-AGENT] Enriched context: %d chars from %d sources",
                        len(enriched_context), len(enriched_parts))

        # ── Step 1: Regime Agent ────────────────────────────────
        regime_input = self._build_regime_input(snapshot_data)
        regime_out = self._call_agent(
            AgentRole.REGIME, regime_input, model_for_trigger
        )
        pipeline_results[AgentRole.REGIME] = regime_out

        if not regime_out.ok:
            if self.configs[AgentRole.REGIME].required:
                logger.warning("[MULTI-AGENT] Regime agent failed — aborting pipeline")
                self.last_pipeline_results = pipeline_results
                return None
            # Fallback: unknown regime
            regime_out = AgentOutput(
                role=AgentRole.REGIME,
                data={"rg": "unknown", "conf": 0.3, "factors": "regime agent failed",
                      "bias": "neutral", "transition": "uncertain"},
            )

        # Technical regime fallback: if LLM returns "unknown", classify from market data
        if regime_out.data.get("rg", "unknown") == "unknown":
            try:
                _fb_regime = self._compute_regime_fallback(snapshot_data)
                if _fb_regime and _fb_regime != "unknown":
                    regime_out.data["rg"] = _fb_regime
                    regime_out.data["factors"] = f"technical_fallback: {_fb_regime}"
                    regime_out.data["conf"] = max(regime_out.data.get("conf", 0.3), 0.5)
                    logger.info(f"[MULTI-AGENT] Regime fallback: unknown → {_fb_regime}")
            except Exception as e:
                logger.debug(f"[MULTI-AGENT] Regime fallback error: {e}")

        # Write regime output to scratchpad for downstream agents
        scratchpad.write("regime", "regime", regime_out.data.get("rg", "unknown"))
        scratchpad.write("regime", "regime_conf", regime_out.data.get("conf", 0.5))
        scratchpad.write("regime", "bias", regime_out.data.get("bias", "neutral"))
        if regime_out.data.get("outlook"):
            scratchpad.write("regime", "outlook", regime_out.data["outlook"])
        # Gap 3: Regime transition prediction fields
        if regime_out.data.get("regime_momentum"):
            scratchpad.write("regime", "regime_momentum", regime_out.data["regime_momentum"])
        if regime_out.data.get("expected_duration_h"):
            scratchpad.write("regime", "expected_duration_h", regime_out.data["expected_duration_h"])

        # ── Step 1.5: Quant Agent (optional) ─────────────────────
        quant_out = None
        if self.configs.get(AgentRole.QUANT, AgentConfig(role=AgentRole.QUANT)).enabled:
            quant_input = self._build_quant_input(snapshot_data, regime_out)
            quant_out = self._call_agent(
                AgentRole.QUANT, quant_input, model_for_trigger
            )
            pipeline_results[AgentRole.QUANT] = quant_out
            if quant_out and quant_out.ok:
                # Write quant analysis to scratchpad for Trade Agent
                scratchpad.write("quant", "ev", quant_out.data.get("ev", {}))
                if quant_out.data.get("conditional_edge"):
                    scratchpad.write("quant", "conditional_edge", quant_out.data["conditional_edge"])
                if quant_out.data.get("probability"):
                    scratchpad.write("quant", "probability", quant_out.data["probability"])
                if quant_out.data.get("kelly_fraction") is not None:
                    scratchpad.write("quant", "kelly_fraction", quant_out.data["kelly_fraction"])
                if quant_out.data.get("signal_quality"):
                    scratchpad.write("quant", "signal_quality", quant_out.data["signal_quality"])
                if quant_out.data.get("risk_profile"):
                    scratchpad.write("quant", "risk_profile", quant_out.data["risk_profile"])
            else:
                quant_out = None  # Degrade gracefully

        # ── Step 1.75: Pre-Trade Simulator (scenario analysis) ──
        if _SIMULATOR_AVAILABLE:
            try:
                if self._pre_trade_simulator is None:
                    self._pre_trade_simulator = PreTradeSimulator()
                # Extract signal data from snapshot to simulate
                _sim_signals = snapshot_data.get("signals", [])
                if not _sim_signals and _markets:
                    # Try extracting from market data
                    for _mk in (_markets if isinstance(_markets, list) else []):
                        _sigs = _mk.get("sg", _mk.get("sigs", []))
                        if _sigs:
                            _sim_signals = _sigs
                            break
                if _sim_signals and isinstance(_sim_signals, list) and _sim_signals:
                    _sig = _sim_signals[0] if isinstance(_sim_signals[0], dict) else {}
                    _sim_side = _sig.get("side", _sig.get("sd", ""))
                    _sim_entry = float(_sig.get("entry", _sig.get("e", 0)))
                    _sim_sl = float(_sig.get("sl", 0))
                    _sim_tp1 = float(_sig.get("tp1", 0))
                    _sim_lev = float(_sig.get("leverage", _sig.get("lev", 5)))
                    if _sim_side and _sim_entry > 0 and _sim_sl > 0 and _sim_tp1 > 0:
                        _sim_portfolio = snapshot_data.get("pos", {})
                        _sim_market = dict(snapshot_data.get("g", {}))
                        _sim_market["equity"] = float(
                            snapshot_data.get("g", {}).get("equity",
                            snapshot_data.get("g", {}).get("eq", 1000))
                        )
                        _sim_result = self._pre_trade_simulator.simulate(
                            symbol=_enrich_symbol or _sig.get("sym", _sig.get("s", "")),
                            side=_sim_side,
                            entry=_sim_entry,
                            sl=_sim_sl,
                            tp1=_sim_tp1,
                            leverage=_sim_lev,
                            current_portfolio=_sim_portfolio,
                            market_data=_sim_market,
                        )
                        if _sim_result:
                            _sim_text = self._pre_trade_simulator.format_for_agent(_sim_result)
                            if _sim_text:
                                snapshot_data["_simulation"] = _sim_text
                                logger.info("[MULTI-AGENT] Pre-trade simulation: EV=$%.2f rec=%s",
                                            _sim_result.get("expected_value", 0),
                                            _sim_result.get("recommendation", "?"))
            except Exception as e:
                logger.debug("[MULTI-AGENT] Pre-trade simulation failed: %s", e)

        # ── Step 2: Trade Agent ─────────────────────────────────
        trade_input = self._build_trade_input(snapshot_data, regime_out, quant_out)
        trade_out = self._call_agent(
            AgentRole.TRADE, trade_input, model_for_trigger
        )
        pipeline_results[AgentRole.TRADE] = trade_out

        if not trade_out.ok:
            if self.configs[AgentRole.TRADE].required:
                logger.warning("[MULTI-AGENT] Trade agent failed — aborting pipeline")
                self.last_pipeline_results = pipeline_results
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
            risk_input = self._build_risk_input(snapshot_data, regime_out, trade_out, quant_out)
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
            # On critical inconsistency: override action to skip but preserve
            # a fraction of the agent's confidence for downstream analysis.
            # Previously zeroed confidence, losing all signal information.
            critical_issues = [
                i for i in consistency_report.issues if i.severity == "critical"
            ]
            if critical_issues:
                original_conf = float(
                    trade_out.data.get("c", trade_out.data.get("confidence", 0.0))
                )
                logger.warning(
                    f"[MULTI-AGENT] Critical issues found — overriding to skip "
                    f"(original conf={original_conf:.2f}): "
                    f"{[i.description[:80] for i in critical_issues]}"
                )
                trade_out = AgentOutput(
                    role=AgentRole.TRADE,
                    data={
                        "a": "skip",
                        "c": original_conf * 0.5,  # halve instead of zero
                        "n": f"consistency_override: {critical_issues[0].description[:100]}",
                    },
                )

        # ── Quant Agent confidence adjustment ─────────────────
        # If Quant Agent flagged signal as noise or adjusted confidence, apply.
        # Skip if consistency already overrode to avoid cascading reductions.
        _consistency_overrode = "consistency_override" in trade_out.data.get("n", "")
        if quant_out and quant_out.ok and not _consistency_overrode:
            sq_raw = quant_out.data.get("signal_quality", {})
            sq = sq_raw if isinstance(sq_raw, dict) else {}
            quant_adj = sq.get("confidence_adjustment", 0)
            if quant_adj and isinstance(quant_adj, (int, float)):
                # Cap quant adjustment to prevent cascading reductions
                quant_adj = max(-0.15, min(0.15, quant_adj))
                td = trade_out.data
                old_c = float(td.get("c", td.get("confidence", 0.0)))
                new_c = max(0.0, min(1.0, old_c + quant_adj))
                # Update trade_out data in-place for downstream consensus
                trade_out = AgentOutput(
                    role=AgentRole.TRADE,
                    data={**trade_out.data, "c": new_c,
                          "n": (td.get("n", "") + f" | QUANT_ADJ: {quant_adj:+.2f}")},
                    raw_text=trade_out.raw_text,
                    model_used=trade_out.model_used,
                    input_tokens=trade_out.input_tokens,
                    output_tokens=trade_out.output_tokens,
                    latency_ms=trade_out.latency_ms,
                )
            # If quant says it's noise, apply graduated response:
            # - Very low confidence (<0.20): hard skip (genuinely garbage)
            # - Low confidence (0.20-0.40): reduce size 50% but let Critic review
            # - Above 0.40: leave alone (may have positive EV with good R:R)
            # NOTE: Thresholds relaxed from 0.35/0.50 to 0.20/0.40 — previous
            # values killed 88% of signals as quant_noise, far too aggressive.
            if sq.get("is_noise"):
                trade_conf = float(trade_out.data.get("c", 0))
                noise_reason = sq.get("reason", "statistical noise")
                if trade_conf < 0.20:
                    trade_out = AgentOutput(
                        role=AgentRole.TRADE,
                        data={**trade_out.data, "a": "skip", "c": 0.0,
                              "n": f"QUANT_NOISE: {noise_reason}"},
                        raw_text=trade_out.raw_text,
                        model_used=trade_out.model_used,
                    )
                elif trade_conf < 0.40:
                    # Reduce size but let trade proceed for Critic review
                    td = trade_out.data
                    old_sm = float(td.get("sm", td.get("size_multiplier", 1.0)))
                    trade_out = AgentOutput(
                        role=AgentRole.TRADE,
                        data={**td, "sm": round(old_sm * 0.5, 2),
                              "n": (td.get("n", "") + f" | QUANT_NOISE_REDUCE: {noise_reason}")},
                        raw_text=trade_out.raw_text,
                        model_used=trade_out.model_used,
                        input_tokens=trade_out.input_tokens,
                        output_tokens=trade_out.output_tokens,
                        latency_ms=trade_out.latency_ms,
                    )

        # ── Network Learning: apply calibration adjustment ────
        _net_cal = snapshot_data.get("network_calibration_adj", 0) if snapshot_data else 0
        if _net_cal and isinstance(_net_cal, (int, float)) and abs(_net_cal) >= 0.02:
            td = trade_out.data
            old_c = float(td.get("c", td.get("confidence", 0.0)))
            new_c = max(0.0, min(1.0, old_c + _net_cal))
            trade_out = AgentOutput(
                role=AgentRole.TRADE,
                data={**td, "c": new_c,
                      "n": (td.get("n", "") + f" | NET_CAL: {_net_cal:+.2f}")},
                raw_text=trade_out.raw_text,
                model_used=trade_out.model_used,
                input_tokens=trade_out.input_tokens,
                output_tokens=trade_out.output_tokens,
                latency_ms=trade_out.latency_ms,
            )

        # ── Agent Brain: Record decisions for learning ────────
        if _EXTENSIONS_AVAILABLE:
            try:
                _regime = regime_out.data.get("rg", "unknown") if regime_out.ok else "unknown"
                record_agent_decision("regime", regime_out.data, regime=_regime)
                record_agent_decision("trade", trade_out.data, regime=_regime)
                if risk_out and risk_out.ok:
                    record_agent_decision("risk", risk_out.data, regime=_regime)
                if critic_out and critic_out.ok:
                    record_agent_decision("critic", critic_out.data, regime=_regime)
            except Exception as e:
                logger.debug(f"[MULTI-AGENT] Brain recording error: {e}")

        # ── Debate: synthesize diverse agent viewpoints ───────
        debate_outcome = None
        interactive_debate_outcome = None
        if _EXTENSIONS_AVAILABLE:
            try:
                _agent_data = {
                    "regime": regime_out.data if regime_out.ok else {},
                    "trade": trade_out.data if trade_out.ok else {},
                    "critic": critic_out.data if critic_out and critic_out.ok else {},
                }
                _sym = ""
                _markets = snapshot_data.get("m", []) if snapshot_data else []
                if _markets and isinstance(_markets[0], dict):
                    _sym = _markets[0].get("s", _markets[0].get("sym", ""))

                # Try interactive debate first (2-round, real LLM calls)
                if trade_out.ok and critic_out and critic_out.ok:
                    _risk_data = risk_out.data if risk_out and risk_out.ok else {}
                    interactive_debate_outcome = run_interactive_debate_if_enabled(
                        trade_agent_output=trade_out.data,
                        critic_agent_output=critic_out.data,
                        market_context=snapshot_data or {},
                        risk_assessment=_risk_data,
                        position_size_pct=float(_risk_data.get(
                            "position_size_pct", _risk_data.get("sz_pct", 0)
                        )),
                    )
                    if interactive_debate_outcome:
                        scratchpad.write("debate", "interactive_outcome", interactive_debate_outcome)

                # Fall back to post-hoc debate if interactive not enabled
                if not interactive_debate_outcome:
                    debate_outcome = run_debate_if_warranted(
                        _agent_data,
                        regime=regime_out.data.get("rg", "unknown") if regime_out.ok else "unknown",
                        symbol=_sym,
                    )
                    if debate_outcome:
                        scratchpad.write("debate", "outcome", debate_outcome)
            except Exception as e:
                logger.debug(f"[MULTI-AGENT] Debate error: {e}")

        # ── Confidence Consensus & Consistency Scaling ─────────
        # Gap 1: Compound conviction across agents
        # Gap 7: Consistency score scales confidence
        consensus_conf = _compute_confidence_consensus(
            trade_out, regime_out, risk_out, critic_out, consistency_report.score,
        )
        if consensus_conf is not None:
            # Write to scratchpad for audit trail
            scratchpad.write("system", "consensus_confidence", round(consensus_conf, 3))

        # Apply debate adjustment to consensus confidence
        if _EXTENSIONS_AVAILABLE and consensus_conf is not None:
            # Interactive debate takes precedence if available
            if interactive_debate_outcome:
                # Use debate resolution's final confidence
                if "final_confidence" in interactive_debate_outcome:
                    consensus_conf = interactive_debate_outcome["final_confidence"]
            elif debate_outcome:
                consensus_conf = apply_debate_to_confidence(consensus_conf, debate_outcome)

        # ── Merge into LLMDecision ──────────────────────────────
        decision = self._merge_outputs(
            regime_out, trade_out, risk_out, critic_out, snapshot_data,
            consistency_score=consistency_report.score,
            consensus_confidence=consensus_conf,
        )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._total_latency_ms += elapsed_ms

        agents_called = sum(1 for r in pipeline_results.values() if r.ok)
        consistency_score = consistency_report.score
        self.last_consistency_score = consistency_score
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

        # ── Brain Wiring: thesis tracking + counterfactual + calibration ──
        try:
            from llm.brain_wiring import (
                record_thesis, record_skipped_trade, calibrate_confidence,
            )
            td = trade_out.data
            regime = regime_out.data.get("rg", "unknown") if regime_out.ok else "unknown"

            # Extract symbol from snapshot
            _sym = ""
            _markets = snapshot_data.get("m", []) if snapshot_data else []
            if _markets:
                _sym = _markets[0].get("s", _markets[0].get("sym", ""))

            if decision.action in ("go", "proceed"):
                # Record thesis for accuracy tracking
                _entry = 0.0
                if _markets and isinstance(_markets[0], dict):
                    _entry = _markets[0].get("price", _markets[0].get("p", 0.0))
                thesis_text = td.get("thesis", td.get("n", ""))
                setup_type = td.get("setup_type", td.get("st", ""))
                thesis_id = record_thesis(
                    symbol=_sym,
                    side=td.get("side", td.get("s", "BUY")),
                    thesis=thesis_text[:200] if thesis_text else "",
                    confidence=decision.confidence * 100 if decision.confidence <= 1 else decision.confidence,
                    regime=regime,
                    entry_price=_entry,
                    setup_type=setup_type,
                )
                if thesis_id:
                    decision = LLMDecision(
                        action=decision.action,
                        confidence=decision.confidence,
                        regime=decision.regime,
                        strategy_weights=decision.strategy_weights,
                        memory_update=decision.memory_update,
                        notes=f"{decision.notes} | thesis_id={thesis_id}",
                        size_multiplier=decision.size_multiplier,
                        entry_adjustment=decision.entry_adjustment,
                    )

            elif decision.action in ("flat", "skip"):
                # Record skipped trade for counterfactual analysis
                _signals = snapshot_data.get("signals", []) if snapshot_data else []
                if _signals and isinstance(_signals[0], dict):
                    _sig = _signals[0]
                    record_skipped_trade(
                        symbol=_sym or _sig.get("sym", ""),
                        side=_sig.get("side", "BUY"),
                        entry_price=_sig.get("entry", _sig.get("e", 0.0)),
                        sl=_sig.get("sl", 0.0),
                        tp1=_sig.get("tp1", 0.0),
                        tp2=_sig.get("tp2", 0.0),
                        confidence=_sig.get("confidence", _sig.get("c", 0.0)),
                        skip_reason=decision.notes[:100] if decision.notes else "llm_skip",
                        strategy=_sig.get("strategy", ""),
                        regime=regime,
                    )
        except Exception as e:
            logger.info(f"[MULTI-AGENT] Brain wiring error: {e}")

        # ── Pipeline Telemetry ─────────────────────────────────
        if _EXTENSIONS_AVAILABLE:
            try:
                log_pipeline_telemetry(
                    pipeline_results, elapsed_ms,
                    decision.action, decision.confidence,
                )
            except Exception:
                pass

        # ── Performance Tracker: record pipeline run for agent scoring ──
        try:
            import uuid as _uuid
            from llm.agents.performance_tracker import get_performance_tracker
            _tracker = get_performance_tracker()
            _sym = ""
            _markets = snapshot_data.get("m", []) if snapshot_data else []
            if _markets and isinstance(_markets[0], dict):
                _sym = _markets[0].get("s", _markets[0].get("sym", ""))
            _side = ""
            if trade_out.ok:
                _side = trade_out.data.get("side", trade_out.data.get("s", ""))
            _pipeline_id = str(_uuid.uuid4())[:12]
            _tracker.record_pipeline_run(
                pipeline_id=_pipeline_id,
                symbol=_sym,
                side=_side,
                agent_outputs=pipeline_results,
            )
            # Record veto counterfactual if critic vetoed
            if decision.action in ("flat", "skip") and critic_out and critic_out.ok:
                _critic_verdict = critic_out.data.get("verdict", critic_out.data.get("v", ""))
                if _critic_verdict in ("veto", "reject"):
                    _entry = 0.0
                    if _markets and isinstance(_markets[0], dict):
                        _entry = _markets[0].get("price", _markets[0].get("p", 0.0))
                    _tracker.record_veto(
                        pipeline_id=_pipeline_id,
                        symbol=_sym,
                        side=_side,
                        entry_price=_entry,
                        critic_output=critic_out,
                    )
        except Exception as e:
            logger.debug(f"[MULTI-AGENT] Performance tracker record error: {e}")

        # Store pipeline results for external consumers (backtest logging, etc.)
        self.last_pipeline_results = pipeline_results

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

            # ── Brain Wiring: close thesis + record regime trade ──
            try:
                from llm.brain_wiring import close_thesis, record_regime_trade
                # Close thesis if thesis_id is in the trade notes
                notes = trade_data.get("notes", "")
                if "thesis_id=" in notes:
                    tid = notes.split("thesis_id=")[1].split(" ")[0].split("|")[0].strip()
                    if tid:
                        close_thesis(
                            thesis_id=tid,
                            exit_price=trade_data.get("exit_price", 0.0),
                            pnl_pct=trade_data.get("pnl_pct", 0.0),
                            max_favorable=trade_data.get("max_favorable"),
                            max_adverse=trade_data.get("max_adverse"),
                            actual_hold_h=trade_data.get("hold_hours"),
                        )
                # Record trade for regime feedback
                record_regime_trade(
                    regime=trade_data.get("regime", "unknown"),
                    pnl=trade_data.get("pnl_pct", 0.0),
                    confidence=trade_data.get("confidence", 0.0),
                    strategy=trade_data.get("strategy", ""),
                    hold_hours=trade_data.get("hold_hours", 0.0),
                )
            except Exception as e:
                logger.info(f"[MULTI-AGENT] Brain post-trade wiring error: {e}")

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
        self.last_exit_output = out

        if out.ok:
            action = out.data.get("action", "hold")
            urgency = out.data.get("urgency", "low")
            logger.info(
                f"[MULTI-AGENT] Exit agent: {position_data.get('symbol', '?')} "
                f"action={action} urgency={urgency} "
                f"thesis_valid={out.data.get('thesis_still_valid', '?')} "
                f"reason={out.data.get('reason', '')[:60]}"
            )

            # Feed exit reasoning to learning systems when closing
            if action in ("full_close", "partial_close", "close"):
                try:
                    from llm.agents.learning_integration import process_exit_feedback
                    process_exit_feedback(out.data, position_data)
                except Exception as ef:
                    logger.debug(f"[MULTI-AGENT] Exit feedback error: {ef}")

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

        # Enriched context from market_data if available
        if market_data and market_data.get("enriched_context"):
            exit_data["enriched"] = market_data["enriched_context"]

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

    def run_overseer(
        self,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run the Overseer meta-optimizer agent.

        The Overseer runs periodically (every 30-60 min) to:
        - Analyze cross-trade patterns invisible to individual agents
        - Identify systematic drift and strategy degradation
        - Generate long-term theses for the system to learn from
        - Recommend strategy adjustments, model routing, parameter changes
        - Assess agent quality and calibration

        Results feed into the growth orchestrator as recommendations and
        are written to scratchpad for downstream agents to read.

        Returns:
            Parsed overseer output dict or None.
        """
        cfg = self.configs.get(
            AgentRole.OVERSEER,
            AgentConfig(role=AgentRole.OVERSEER),
        )
        if not cfg.enabled:
            return None

        # Build comprehensive system state for the Overseer
        overseer_input = self._build_overseer_input()
        out = self._call_agent(AgentRole.OVERSEER, overseer_input, model_for_trigger)

        if not out.ok:
            logger.warning("[MULTI-AGENT] Overseer call failed")
            return None

        data = out.data

        # Write Overseer findings to scratchpad for Trade/Risk/Critic to read
        scratchpad = get_pipeline_scratchpad()

        # Strategy adjustments become context for Trade Agent
        strat_adj = data.get("strategy_adjustments")
        if strat_adj:
            scratchpad.write("overseer", "strategy_adjustments", strat_adj)

        # Symbol focus becomes context for Trade Agent
        sym_focus = data.get("symbol_focus")
        if sym_focus:
            scratchpad.write("overseer", "symbol_focus", sym_focus)

        # Agent feedback becomes context for respective agents
        agent_fb = data.get("agent_feedback")
        if agent_fb:
            scratchpad.write("overseer", "agent_feedback", agent_fb)

        # System health for all agents to see
        health = data.get("system_health", "stable")
        diagnosis = data.get("diagnosis", "")
        scratchpad.write("overseer", "health", health)
        if diagnosis:
            scratchpad.write("overseer", "diagnosis", diagnosis[:200])

        # Feed recommendations into the growth orchestrator
        recs = data.get("recommendations", [])
        if recs:
            try:
                from llm.growth.orchestrator import get_growth_orchestrator
                growth = get_growth_orchestrator()
                for rec in recs[:5]:
                    growth.on_recommendation_from_llm(
                        rec_type=rec.get("type", "parameter"),
                        title=rec.get("title", "Overseer recommendation"),
                        description=rec.get("rationale", ""),
                        suggested_action=rec.get("action", ""),
                        confidence=0.7 if rec.get("priority") in ("critical", "high") else 0.5,
                    )
            except Exception as e:
                logger.debug(f"[OVERSEER] Failed to feed recommendations: {e}")

        # Feed theses into hypothesis tracker
        theses = data.get("theses", [])
        if theses:
            try:
                from llm.growth.hypothesis_tracker import get_hypothesis_tracker
                tracker = get_hypothesis_tracker()
                for th in theses[:3]:
                    tracker.propose(
                        hypothesis=th.get("thesis", ""),
                        source="overseer",
                        confidence=th.get("confidence", 0.5),
                    )
            except Exception as e:
                logger.debug(f"[OVERSEER] Failed to feed theses: {e}")

        logger.info(
            f"[MULTI-AGENT] Overseer: health={health}, "
            f"{len(recs)} recommendations, {len(theses)} theses, "
            f"diagnosis={diagnosis[:80]}"
        )
        return data

    # ── Phase 3 Strategic Agents ────────────────────────────────

    def get_portfolio_intelligence(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Portfolio Aggregator agent for holistic portfolio health analysis.
        Runs DAILY (not per-trade).

        Returns:
            Portfolio analysis dict or None on failure.
        """
        if not _STRATEGIC_AGENTS_AVAILABLE:
            return None
        return build_portfolio_aggregator(self, model_for_trigger)

    def get_regime_forecast(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Regime Forecaster agent to predict regime transitions.
        Runs DAILY.

        Returns:
            Regime forecast dict or None on failure.
        """
        if not _STRATEGIC_AGENTS_AVAILABLE:
            return None
        return build_regime_forecaster(self, model_for_trigger)

    def get_novel_hypotheses(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Hypothesis Generator agent to discover novel trading patterns.
        Runs WEEKLY.

        Returns:
            Novel hypotheses dict or None on failure.
        """
        if not _STRATEGIC_AGENTS_AVAILABLE:
            return None
        return build_hypothesis_generator(self, model_for_trigger)

    def get_correlator_analysis(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Correlator agent to analyze cross-asset relationships.
        Runs DAILY.

        Returns:
            Correlation analysis dict or None on failure.
        """
        if not _STRATEGIC_AGENTS_AVAILABLE:
            return None
        return build_correlator(self, model_for_trigger)

    # ── Phase 4 Scalping + Conviction Agents ────────────────────

    def get_micro_trend(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Micro-Trend Detector to classify 5m micro-trends.
        Feeds context into Scalper Agent.

        Returns:
            Micro-trend classification dict or None on failure.
        """
        if not _PHASE_4_AGENTS_AVAILABLE:
            return None
        return build_micro_trend_detector(self, model_for_trigger)

    def get_scalp_signal(
        self, model_for_trigger: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run Scalper Agent to find 1m-5m micro-trading opportunities.
        Runs very frequently (every 1m when enabled).

        Returns:
            Scalp signal dict or None on failure.
        """
        if not _PHASE_4_AGENTS_AVAILABLE:
            return None
        return build_scalper(self, model_for_trigger)

    def get_conviction_analysis(
        self,
        regime_out: AgentOutput,
        trade_out: AgentOutput,
        quant_out: Optional[AgentOutput] = None,
        critic_out: Optional[AgentOutput] = None,
        forecaster_out: Optional[AgentOutput] = None,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Conviction Agent to authorize high-leverage trades when all agents align.
        Runs per signal (rare, ~5-10/month).

        Returns:
            Conviction analysis dict or None on failure.
        """
        if not _PHASE_4_AGENTS_AVAILABLE:
            return None
        return build_conviction(
            self, regime_out, trade_out, quant_out, critic_out, forecaster_out, model_for_trigger
        )

    # ── Phase 4A Core Trading Agents ─────────────────────────────

    def get_position_size(
        self,
        capital: float,
        edge_confidence: float,
        kelly_fraction: Optional[float] = None,
        regime: str = "unknown",
        risk_per_trade: float = 1.0,
        leverage: float = 1.5,
        atr: float = 0.0,
        stop_distance: float = 0.0,
        consecutive_losses: int = 0,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Position Sizer Agent to calculate exact position size in USD.

        Returns:
            Position sizing dict with position_size_usd, leverage_applied, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_position_sizer(
            self,
            capital=capital,
            edge_confidence=edge_confidence,
            kelly_fraction=kelly_fraction,
            regime=regime,
            risk_per_trade=risk_per_trade,
            leverage=leverage,
            atr=atr,
            stop_distance=stop_distance,
            consecutive_losses=consecutive_losses,
            model_for_trigger=model_for_trigger,
        )

    def get_entry_method(
        self,
        signal_confidence: float,
        current_price: float,
        entry_price_from_signal: float,
        regime: str = "unknown",
        recent_momentum: str = "flat",
        order_book: Optional[Dict] = None,
        position_size_usd: float = 0.0,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Entry Optimizer Agent to determine entry method and timing.

        Returns:
            Entry optimization dict with entry_method, entry_price, urgency, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_entry_optimizer(
            self,
            signal_confidence=signal_confidence,
            current_price=current_price,
            entry_price_from_signal=entry_price_from_signal,
            regime=regime,
            recent_momentum=recent_momentum,
            order_book=order_book,
            position_size_usd=position_size_usd,
            model_for_trigger=model_for_trigger,
        )

    def get_exit_recommendation(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        pnl_usd: float,
        thesis: str = "",
        regime: str = "unknown",
        original_regime: str = "unknown",
        time_held_seconds: int = 0,
        funding_paid: float = 0.0,
        volume_trend: str = "stable",
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Exit Advisor Agent to recommend exit actions for open positions.

        Returns:
            Exit recommendation dict with action, thesis_still_valid, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_exit_advisor(
            self,
            position_id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            pnl_usd=pnl_usd,
            thesis=thesis,
            regime=regime,
            original_regime=original_regime,
            time_held_seconds=time_held_seconds,
            funding_paid=funding_paid,
            volume_trend=volume_trend,
            model_for_trigger=model_for_trigger,
        )

    def get_risk_check(
        self,
        proposed_trade: Dict[str, Any],
        portfolio_leverage: float,
        circuit_breaker_active: bool = False,
        daily_loss_pct: float = 0.0,
        consecutive_losses: int = 0,
        open_positions: Optional[list] = None,
        max_single_position_pct: float = 3.0,
        max_portfolio_leverage: float = 8.0,
        correlation_to_open: float = 0.0,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Risk Guard Agent to check safety gates and prevent catastrophic losses.

        Returns:
            Risk check dict with approved, risk_flags, max_size_allowed, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_risk_guard(
            self,
            proposed_trade=proposed_trade,
            portfolio_leverage=portfolio_leverage,
            circuit_breaker_active=circuit_breaker_active,
            daily_loss_pct=daily_loss_pct,
            consecutive_losses=consecutive_losses,
            open_positions=open_positions,
            max_single_position_pct=max_single_position_pct,
            max_portfolio_leverage=max_portfolio_leverage,
            correlation_to_open=correlation_to_open,
            model_for_trigger=model_for_trigger,
        )

    def get_routing_decision(
        self,
        signal: Dict[str, Any],
        market_state: Dict[str, Any],
        portfolio_state: Dict[str, Any],
        system_state: Optional[Dict[str, Any]] = None,
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Agent Router to determine which agents to call and how.

        Returns:
            Routing dict with route, agents_to_call, agent_configs, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_agent_router(
            self,
            signal=signal,
            market_state=market_state,
            portfolio_state=portfolio_state,
            system_state=system_state,
            model_for_trigger=model_for_trigger,
        )

    def get_final_decision(
        self,
        position_sizer_output: Dict[str, Any],
        entry_optimizer_output: Dict[str, Any],
        risk_guard_output: Dict[str, Any],
        exit_advisor_output: Dict[str, Any],
        original_signal: Dict[str, Any],
        route: str = "normal_pipeline",
        model_for_trigger: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run Consensus Builder Agent to merge all specialist outputs into final trade decision.

        Returns:
            Final decision dict with final_decision (execute|skip), trade parameters, etc or None on failure.
        """
        if not _PHASE_4A_AGENTS_AVAILABLE:
            return None
        return build_consensus_builder(
            self,
            position_sizer_output=position_sizer_output,
            entry_optimizer_output=entry_optimizer_output,
            risk_guard_output=risk_guard_output,
            exit_advisor_output=exit_advisor_output,
            original_signal=original_signal,
            route=route,
            model_for_trigger=model_for_trigger,
        )

    def _build_overseer_input(self) -> str:
        """Build comprehensive system state for the Overseer agent."""
        state: Dict[str, Any] = {}

        # 1. Self-performance stats
        try:
            from llm.self_performance import get_performance_stats
            perf = get_performance_stats()
            if perf:
                state["self_perf"] = {
                    "accuracy": round(perf.get("accuracy", 0.5), 2),
                    "veto_accuracy": round(perf.get("veto_accuracy", 0.5), 2),
                    "calibration": round(perf.get("calibration", 0), 2),
                    "streak": perf.get("streak", ""),
                    "total_decisions": perf.get("total_decisions", 0),
                    "regime_accuracy": perf.get("regime_accuracy", {}),
                    "symbol_accuracy": perf.get("symbol_accuracy", {}),
                    "go_count": perf.get("go_count", 0),
                    "skip_count": perf.get("skip_count", 0),
                    "flip_count": perf.get("flip_count", 0),
                }
        except Exception:
            pass

        # 2. Survival metrics
        try:
            from llm.survival_pressure import get_survival_state
            surv = get_survival_state()
            state["survival"] = {
                "score": round(surv.survival_score, 0),
                "trajectory": surv.trajectory,
                "total_trades": surv.total_trades,
                "total_wins": surv.total_wins,
                "total_pnl": round(surv.total_pnl, 1),
                "drawdown_pct": round(surv.current_drawdown_pct, 1),
                "funding_paid": round(surv.total_funding_paid, 1),
                "streak": surv.current_streak,
            }
        except Exception:
            pass

        # 3. Strategy performance (from deep memory)
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            strat_wr = dm.trade_dna.get_win_rate_by("strategy")
            if strat_wr:
                state["strategy_perf"] = {
                    k: {"wr": round(v.get("wins", 0) / max(v.get("total", 1), 1) * 100),
                        "n": v.get("total", 0),
                        "pnl": round(v.get("pnl", 0), 1)}
                    for k, v in strat_wr.items() if v.get("total", 0) >= 3
                }
            # Setup edge map
            setup_wr = dm.trade_dna.get_win_rate_by("setup_type")
            if setup_wr:
                state["setup_edge"] = {
                    k: {"wr": round(v.get("wins", 0) / max(v.get("total", 1), 1) * 100),
                        "n": v.get("total", 0)}
                    for k, v in setup_wr.items() if v.get("total", 0) >= 5
                }
        except Exception:
            pass

        # 4. Growth state (enriched with integrator context)
        try:
            from llm.learning_integrator import get_learning_integrator
            integrator = get_learning_integrator()
            # Get enriched context (includes growth + veto accuracy + session perf +
            # symbol patterns + feedback status + self-improvement)
            enriched = integrator.get_enriched_llm_context()
            if enriched:
                state["growth"] = enriched[:600]
        except Exception:
            # Fallback to basic growth context
            try:
                from llm.growth.orchestrator import get_growth_orchestrator
                growth = get_growth_orchestrator()
                ctx = growth.get_llm_context()
                if ctx:
                    state["growth"] = ctx[:400]
            except Exception:
                pass

        # 5. Cost tracking
        try:
            from llm.cost_tracker import get_daily_summary
            cost = get_daily_summary()
            if cost:
                state["cost"] = cost
        except Exception:
            pass

        # 6. Recent trade outcomes
        try:
            from llm.survival_pressure import get_survival_state
            surv = get_survival_state()
            recent = surv.recent_outcomes[-20:]
            recent_pnl = surv.recent_pnls[-20:]
            if recent:
                state["recent_trades"] = {
                    "outcomes": "".join("W" if o == "WIN" else "L" for o in recent),
                    "pnls": [round(p, 1) for p in recent_pnl[-10:]],
                }
        except Exception:
            pass

        # 7. Agent pipeline scratchpad (what other agents have written)
        try:
            scratchpad = get_pipeline_scratchpad()
            sp_data = scratchpad.read_all()
            if sp_data:
                state["agent_outputs"] = {
                    k: v for k, v in sp_data.items()
                    if k in ("regime", "trade", "risk", "critic", "scout")
                }
        except Exception:
            pass

        # 8. Historical patterns from replay engine (free — no API calls)
        try:
            from llm.replay_engine import get_historical_patterns
            patterns = get_historical_patterns(max_decisions=200)
            if patterns and "error" not in patterns:
                state["historical_patterns"] = patterns
        except Exception:
            pass

        # 9. Per-agent calibration ledger summaries
        try:
            from llm.agents.calibration_ledger import get_calibration_ledger
            ledger = get_calibration_ledger()
            agent_cals = {}
            for agent_name in ("trade", "critic", "regime"):
                summary = ledger.get_agent_summary(agent_name)
                if summary.get("total_decisions", 0) >= 5:
                    agent_cals[agent_name] = summary
            if agent_cals:
                state["agent_calibrations"] = agent_cals
        except Exception:
            pass

        # 10. Brain upgrades: thesis accuracy, calibration, counterfactual, regime feedback, drawdown
        try:
            from llm.brain_wiring import (
                get_thesis_tracker, get_confidence_calibrator,
                get_counterfactual_learner, get_regime_feedback, get_graduated_risk,
            )
            # Thesis accuracy
            tt = get_thesis_tracker()
            if tt:
                stats = tt.get_accuracy_stats(lookback_days=14, min_samples=3)
                if stats.get("sufficient_data"):
                    state["thesis_accuracy"] = {
                        "overall": round(stats["overall_accuracy"] * 100),
                        "total": stats["total_theses"],
                        "by_regime": {k: round(v["accuracy"] * 100) for k, v in
                                      stats.get("by_regime", {}).items() if v["total"] >= 3},
                    }
            # Confidence calibration
            cc = get_confidence_calibrator()
            if cc:
                cal_summary = cc.get_calibration_summary()
                if cal_summary.get("overall_bias"):
                    state["calibration"] = cal_summary["overall_bias"]
            # Counterfactual (missed opportunities)
            cf = get_counterfactual_learner()
            if cf:
                missed = cf.get_missed_opportunity_stats(lookback_days=7)
                if missed.get("sufficient_data"):
                    state["missed_opportunities"] = {
                        "skips": missed["total_skips"],
                        "would_win": missed["would_win"],
                        "skip_accuracy": round((1 - missed["win_rate_of_skips"]) * 100),
                        "problem_filters": list(missed.get("problem_filters", {}).keys()),
                    }
            # Regime feedback
            rf = get_regime_feedback()
            if rf:
                state["regime_feedback"] = {
                    name: {"wr": round(s.win_rate * 100), "n": s.total_trades,
                           "floor": s.confidence_floor, "risk_mult": s.risk_multiplier}
                    for name, s in rf.regimes.items() if s.total_trades >= 3
                }
            # Graduated risk
            grm = get_graduated_risk()
            if grm and grm.peak_equity > 0:
                state["drawdown_status"] = grm.get_status()
        except Exception as e:
            logger.info(f"[OVERSEER] Brain upgrade injection error: {e}")

        # 11. Network learning summary (edge decay, calibration drift, constraints)
        try:
            from llm.agents.network_learning import get_network_learning
            nl_summary = get_network_learning().format_for_overseer()
            if nl_summary:
                state["network_learning"] = nl_summary[:400]
        except Exception:
            pass

        # 12. Agent self-performance network summary (accuracy, calibration per agent)
        if _AGENT_PERF_AVAILABLE:
            try:
                _net_health = get_perf_tracker().format_network_summary()
                if _net_health:
                    state["agent_network_health"] = _net_health[:500]
            except Exception:
                pass

        return json.dumps(state, separators=(",", ":"), default=str)

    def get_stats(self) -> Dict[str, Any]:
        """Return coordinator statistics SINCE LAST CALL to get_stats().

        Returns delta (per-pipeline) usage, not cumulative. This prevents
        cost_tracker from double-counting tokens on each successive call.
        """
        delta_calls = self._call_count - self._last_reported_calls
        delta_input = self._total_input_tokens - self._last_reported_input
        delta_output = self._total_output_tokens - self._last_reported_output
        delta_latency = self._total_latency_ms - self._last_reported_latency

        # Update watermarks
        self._last_reported_calls = self._call_count
        self._last_reported_input = self._total_input_tokens
        self._last_reported_output = self._total_output_tokens
        self._last_reported_latency = self._total_latency_ms

        return {
            "total_calls": delta_calls,
            "total_input_tokens": delta_input,
            "total_output_tokens": delta_output,
            "total_latency_ms": delta_latency,
            "avg_latency_ms": (
                delta_latency // max(delta_calls, 1)
            ),
        }

    def get_last_pipeline_detail(self) -> Optional[Dict[str, Any]]:
        """Return serialized per-agent outputs from the last pipeline run.

        Returns None if no pipeline has run yet.
        """
        if not self.last_pipeline_results:
            return None

        detail = {}
        for role, output in self.last_pipeline_results.items():
            detail[role.value] = {
                "data": output.data,
                "model": output.model_used,
                "input_tokens": output.input_tokens,
                "output_tokens": output.output_tokens,
                "latency_ms": output.latency_ms,
                "ok": output.ok,
                "error": output.error,
            }
        if self.last_consistency_score is not None:
            detail["_meta"] = {"consistency_score": self.last_consistency_score}
        return detail

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

        # Enrich prompt with latest quant intelligence from deep memory
        try:
            prompt = enrich_prompt(role.value, prompt)
        except Exception as e:
            logger.debug(f"[COORD] Prompt enrichment failed for {role.value}: {e}")

        # Inject thought protocol and shared context into the prompt
        protocol_prefix = build_protocol_prefix(role.value)
        scratchpad = get_pipeline_scratchpad()
        # Extract symbol from input JSON for asset DNA injection
        _agent_sym = ""
        try:
            _inp = json.loads(input_json) if isinstance(input_json, str) else input_json
            _agent_sym = _inp.get("symbol", _inp.get("sym", ""))
        except Exception:
            pass
        shared_context = build_shared_context_block(
            agent_role=role.value,
            scratchpad=scratchpad,
            shared_lessons=get_shared_lessons(),
            include_axioms=(role in (AgentRole.TRADE, AgentRole.CRITIC, AgentRole.OVERSEER, AgentRole.QUANT)),
            include_regime_map=(role in (AgentRole.TRADE, AgentRole.CRITIC, AgentRole.OVERSEER)),
            include_strategy_theory=(role in (AgentRole.TRADE, AgentRole.CRITIC, AgentRole.OVERSEER, AgentRole.QUANT)),
            current_regime=scratchpad.read_by_key("regime") or "",
            symbol=_agent_sym,
        )

        # Dynamic calibration injection for Trade, Critic, and Regime agents
        calibration_prefix = ""
        if role in (AgentRole.TRADE, AgentRole.CRITIC, AgentRole.REGIME):
            try:
                from llm.agents.calibration_ledger import get_calibration_ledger
                ledger = get_calibration_ledger()
                current_regime = scratchpad.read_by_key("regime") or ""
                calibration_prefix = ledger.get_prompt_calibration(role.value, current_regime)
            except Exception:
                pass

        # Agent brain context injection (beliefs, performance, calibration)
        brain_prefix = ""
        if _EXTENSIONS_AVAILABLE:
            try:
                current_regime = scratchpad.read_by_key("regime") or ""
                brain_prefix = get_brain_context_for_agent(role.value, regime=current_regime)
            except Exception:
                pass

        # Prepend protocol, calibration, brain, and context to the agent's system prompt
        enhanced_prompt = prompt
        if calibration_prefix:
            enhanced_prompt = f"CALIBRATION: {calibration_prefix}\n\n{enhanced_prompt}"
        if brain_prefix:
            enhanced_prompt = f"BRAIN: {brain_prefix}\n\n{enhanced_prompt}"
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
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        self._total_input_tokens += in_tok
        self._total_output_tokens += out_tok

        # Feed cost tracker so daily budget enforcement stays accurate
        try:
            from llm.cost_tracker import get_cost_tracker
            get_cost_tracker().record_call(in_tok, out_tok, model)
        except Exception:
            pass

        if raw_text is None:
            api_error = usage.get("error", "unknown")
            logger.warning(
                f"[MULTI-AGENT] {role.value} agent API call FAILED: {api_error} "
                f"(model={model}, latency={usage.get('latency_ms', 0)}ms)"
            )
            return AgentOutput(
                role=role,
                data={},
                model_used=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                latency_ms=usage.get("latency_ms", 0),
                error=f"api_error: {api_error}",
            )

        # Parse JSON response
        parsed = _parse_agent_json(raw_text)
        if parsed is None:
            logger.warning(
                f"[MULTI-AGENT] {role.value} agent returned unparseable response "
                f"(model={model}, {len(raw_text)} chars). "
                f"First 200 chars: {raw_text[:200]}"
            )
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

    def _build_quant_input(self, snapshot: dict, regime_out: AgentOutput) -> str:
        """Build quant agent input: market data + regime + historical stats.

        The Quant Agent needs:
        - Raw market data (prices, volume, funding, signals) for statistical analysis
        - Regime classification for conditional probability computation
        - Historical win rates per setup type, strategy, regime, symbol
        - Recent trade outcomes for variance/drawdown analysis
        - Confluence quality for signal vs noise assessment
        """
        quant_data = {}

        # Market data
        if "m" in snapshot:
            quant_data["markets"] = snapshot["m"]
        if "g" in snapshot:
            quant_data["global"] = snapshot["g"]

        # Regime from Regime Agent
        quant_data["regime"] = regime_out.data

        # Compute confluence quality
        confluence = _compute_confluence_from_snapshot(
            snapshot, regime_out.data.get("rg", "unknown")
        )
        if confluence:
            quant_data["confluence"] = confluence

        # Historical stats for conditional probability computation
        # Setup edge: per-setup-type win rates
        if "g" in snapshot:
            g = snapshot["g"]
            if isinstance(g, dict):
                if "edge" in g:
                    quant_data["setup_edge"] = g["edge"]
                if "stperf" in g:
                    quant_data["strategy_perf"] = g["stperf"]

        # Self-performance for calibration/drawdown context
        if "self_perf" in snapshot:
            quant_data["self_perf"] = snapshot["self_perf"]

        # Recent outcomes for variance analysis
        if "autopsy" in snapshot:
            quant_data["autopsy"] = snapshot["autopsy"]

        # Funding data for cost computation
        for key in ("funding_cost_pct", "funding_alert", "port_lev"):
            if key in snapshot:
                quant_data[key] = snapshot[key]

        # Real quant data backbone: Kelly, conditional edge, fat-tail, priors
        try:
            from llm.quant_data import get_quant_provider
            qp = get_quant_provider()
            regime = regime_out.data.get("rg", "unknown") if regime_out.ok else "unknown"
            n_agree = 0
            setup_type = ""
            if "m" in snapshot:
                for mkt in (snapshot["m"] if isinstance(snapshot["m"], list) else []):
                    sigs = mkt.get("sg", mkt.get("sigs", []))
                    if sigs:
                        n_agree = max(n_agree, len(sigs))
                        if isinstance(sigs[0], dict):
                            setup_type = sigs[0].get("st", "")
            quant_package = qp.build_quant_package(regime=regime, num_agree=n_agree, setup_type=setup_type)
            if quant_package:
                quant_data["quant"] = quant_package
        except Exception as e:
            logger.debug(f"Quant data injection error: {e}")

        # Per-agent calibration for Bayesian updating
        try:
            from llm.agents.calibration_ledger import get_calibration_ledger
            ledger = get_calibration_ledger()
            regime = regime_out.data.get("rg", "unknown")
            cal = ledger.get_calibration("trade", regime)
            if cal.get("reliable"):
                quant_data["trade_calibration"] = cal
        except Exception:
            pass

        # Historical patterns from replay engine
        try:
            from llm.replay_engine import get_historical_patterns
            patterns = get_historical_patterns(max_decisions=100)
            if patterns and "error" not in patterns:
                # Only pass the most relevant stats
                compact = {}
                for k in ("regime_wr", "conf_low_wr", "conf_mid_wr", "conf_high_wr",
                           "conf_low_n", "conf_mid_n", "conf_high_n",
                           "max_win_streak", "max_loss_streak", "recent_outcomes"):
                    if k in patterns:
                        compact[k] = patterns[k]
                if compact:
                    quant_data["historical"] = compact
        except Exception:
            pass

        # Enriched context from technicals, feedback, telemetry, positions
        if snapshot.get("enriched_context"):
            quant_data["enriched"] = snapshot["enriched_context"]

        # Per-agent self-performance stats for the Quant Agent
        _pt = getattr(self, '_perf_tracker_ref', None)
        if _pt:
            try:
                _self_perf_text = _pt.format_for_agent("quant")
                if _self_perf_text:
                    quant_data["self_performance"] = _self_perf_text
            except Exception:
                pass

        return json.dumps(quant_data, separators=(",", ":"))

    def _compute_regime_fallback(self, snapshot: dict) -> str:
        """Technical regime classification when LLM returns 'unknown'.

        Uses price changes, volatility, and volume from snapshot to classify:
        - Large moves (>3% 24h) with volume → 'trend'
        - Large moves with extreme volatility → 'high_volatility'
        - Tight ranges (<1% 24h) → 'range'
        - Multiple symbols dropping hard → 'panic'
        - Default → 'consolidation' (safe neutral)
        """
        markets = snapshot.get("m", [])
        if not markets:
            return "consolidation"

        pct_changes = []
        vol_signals = []
        for mkt in (markets if isinstance(markets, list) else []):
            # Try to extract price change from various snapshot formats
            pct_24h = mkt.get("pct_24h", mkt.get("chg24h", 0))
            if isinstance(pct_24h, str):
                try:
                    pct_24h = float(pct_24h.replace("%", ""))
                except (ValueError, TypeError):
                    pct_24h = 0
            pct_changes.append(abs(float(pct_24h or 0)))

            # Volume clues
            vol_ratio = mkt.get("vol_ratio", mkt.get("vr", 1.0))
            if isinstance(vol_ratio, (int, float)) and vol_ratio > 2.0:
                vol_signals.append(True)

        if not pct_changes:
            return "consolidation"

        avg_move = sum(pct_changes) / len(pct_changes)
        max_move = max(pct_changes)
        drops = sum(1 for m in (markets if isinstance(markets, list) else [])
                     if float(m.get("pct_24h", m.get("chg24h", 0)) or 0) < -5)

        # Panic: multiple symbols dropping >5%
        if drops >= 2:
            return "panic"
        # High volatility: extreme moves
        if max_move > 8 or avg_move > 5:
            return "high_volatility"
        # Trend: clear directional move with decent volume
        if avg_move > 2.5 or (avg_move > 1.5 and len(vol_signals) >= 1):
            return "trend"
        # Range: very tight moves
        if avg_move < 1.0:
            return "range"
        # Default: consolidation
        return "consolidation"

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
        # External data: funding/OI + liquidation (critical for regime classification)
        if "ext_funding" in snapshot:
            regime_data["ext_funding"] = snapshot["ext_funding"]
        if "ext_liq" in snapshot:
            regime_data["ext_liq"] = snapshot["ext_liq"]
        if "ext_summary" in snapshot:
            regime_data["ext_data"] = snapshot["ext_summary"]
        # Enriched context from technicals, feedback, telemetry, positions
        if snapshot.get("enriched_context"):
            regime_data["enriched"] = snapshot["enriched_context"]

        # Per-agent self-performance stats for the Regime Agent
        _pt = getattr(self, '_perf_tracker_ref', None)
        if _pt:
            try:
                _self_perf_text = _pt.format_for_agent("regime")
                if _self_perf_text:
                    regime_data["self_performance"] = _self_perf_text
            except Exception:
                pass

        return json.dumps(regime_data, separators=(",", ":"))

    def _build_trade_input(self, snapshot: dict, regime_out: AgentOutput, quant_out: Optional[AgentOutput] = None) -> str:
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
        # External collector data: funding/OI, liq levels, shadow MR
        _ensure_field(trade_data, "ext_funding", snapshot)
        _ensure_field(trade_data, "ext_liq", snapshot)
        _ensure_field(trade_data, "ext_mr", snapshot)
        _ensure_field(trade_data, "ext_summary", snapshot)

        # Network learning: inject accumulated lessons for Trade Agent
        if "network_lessons_trade" in snapshot:
            trade_data["network_lessons"] = snapshot["network_lessons_trade"]
        if "network_calibration_adj" in snapshot:
            trade_data["calibration_adj"] = snapshot["network_calibration_adj"]

        # Inject filter annotations so Trade Agent sees what filters measured
        if "filt" in snapshot:
            trade_data["filter_assessment"] = snapshot["filt"]
        if "near" in snapshot:
            trade_data["near_miss_signals"] = snapshot["near"]

        # Inject Quant Agent's statistical analysis if available
        if quant_out and quant_out.ok:
            trade_data["quant_analysis"] = quant_out.data

        # Gap 4+5: Inject per-agent calibration data into trade input
        try:
            from llm.agents.calibration_ledger import get_calibration_ledger
            ledger = get_calibration_ledger()
            cal_data = ledger.get_compact_for_snapshot("trade")
            if cal_data:
                trade_data["agent_cal"] = cal_data
        except Exception:
            pass

        # Inject similar patterns + known failure modes from deep memory
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            regime = regime_out.data.get("rg", "unknown") if regime_out else "unknown"
            # Find signals that have patterns from this market context
            signals = snapshot.get("signals", [])
            symbol = ""
            if signals:
                symbol = signals[0].get("sym", "") if isinstance(signals[0], dict) else ""

            # PatternLibrary: find similar historical patterns for context
            similar = dm.patterns.find_similar(
                pattern_type="trade_setup",
                symbol=symbol,
                regime=regime,
                limit=3,
            )
            if similar:
                trade_data["similar_patterns"] = [
                    {k: v for k, v in p.items() if k in ("type", "symbol", "regime", "outcome", "lesson")}
                    for p in similar[:3]
                ]

            # TradeDNAStore: get recent failure patterns to avoid
            failures = dm.trade_dna.get_failures(limit=5)
            if failures:
                trade_data["recent_failures"] = [
                    {k: v for k, v in f.items() if k in ("symbol", "side", "regime", "strategy", "pnl", "lesson")}
                    for f in failures[:3]
                ]
        except Exception:
            pass

        # ── Brain Intelligence Injection ──
        # Inject thesis accuracy, calibration, counterfactual, regime feedback,
        # and drawdown context from the brain upgrade modules.
        try:
            from llm.brain_wiring import get_brain_context_for_trade
            regime = regime_out.data.get("rg", "unknown") if regime_out else "unknown"
            symbol = ""
            signals = snapshot.get("signals", [])
            if signals and isinstance(signals[0], dict):
                symbol = signals[0].get("sym", "")
            elif "m" in snapshot and snapshot["m"]:
                symbol = snapshot["m"][0].get("s", snapshot["m"][0].get("sym", ""))
            brain_ctx = get_brain_context_for_trade(symbol, regime)
            if brain_ctx:
                trade_data["brain"] = brain_ctx
        except Exception as e:
            logger.info(f"[MULTI-AGENT] Brain context injection error: {e}")

        # Inject Scout Agent findings (rename from agent_outputs.scout to scout_preparation
        # so Trade Agent prompt can find it by the documented key name)
        try:
            scratchpad = get_pipeline_scratchpad()
            scout_data = scratchpad.read("scout")
            if scout_data:
                trade_data["scout_preparation"] = scout_data
        except Exception:
            pass

        # Enriched context (already in trade_data via dict(snapshot), rename key)
        if "enriched_context" in trade_data:
            trade_data["enriched"] = trade_data.pop("enriched_context")

        # Per-agent self-performance stats for the Trade Agent
        _pt = getattr(self, '_perf_tracker_ref', None)
        if _pt:
            try:
                _self_perf_text = _pt.format_for_agent("trade")
                if _self_perf_text:
                    trade_data["self_performance"] = _self_perf_text
            except Exception:
                pass

        # Pre-trade simulation results (scenario analysis)
        if "_simulation" in snapshot:
            trade_data["simulation"] = snapshot["_simulation"]

        return json.dumps(trade_data, separators=(",", ":"))

    def _build_risk_input(
        self, snapshot: dict, regime_out: AgentOutput, trade_out: AgentOutput,
        quant_out: Optional[AgentOutput] = None,
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
        # Portfolio-level intelligence (computed earlier in pipeline)
        if "_portfolio_state" in snapshot:
            risk_data["portfolio"] = snapshot["_portfolio_state"]
        # Filter annotations for risk-aware sizing (fd, ev, cr matter for sizing)
        if "filt" in snapshot:
            risk_data["filter_assessment"] = snapshot["filt"]
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
        # Inject Quant Agent analysis for Kelly-informed sizing
        if quant_out and quant_out.ok:
            q = quant_out.data
            quant_compact = {}
            if "kelly_fraction" in q:
                quant_compact["kelly"] = q["kelly_fraction"]
            if "ev" in q:
                quant_compact["ev"] = q["ev"]
            if "risk_profile" in q:
                quant_compact["risk_profile"] = q["risk_profile"]
            if "signal_quality" in q:
                quant_compact["signal_quality"] = q["signal_quality"]
            if quant_compact:
                risk_data["quant"] = quant_compact

        # Confluence quality for informed sizing (convergent setups → size up)
        if "confluence" in snapshot:
            risk_data["confluence"] = snapshot["confluence"]
        else:
            # Compute confluence from market signals if available
            markets = snapshot.get("m", [])
            if markets:
                try:
                    confluence = score_confluence(markets[0].get("signals", []))
                    if confluence.get("count", 0) > 0:
                        risk_data["confluence"] = confluence
                except Exception:
                    pass

        # ── Brain Intelligence: regime feedback + graduated risk ──
        try:
            from llm.brain_wiring import get_brain_context_for_risk
            regime = regime_out.data.get("rg", "unknown") if regime_out else "unknown"
            brain_risk = get_brain_context_for_risk(regime)
            if brain_risk:
                risk_data["brain"] = brain_risk
        except Exception as e:
            logger.info(f"[MULTI-AGENT] Brain risk context error: {e}")

        # External data: liq levels critical for risk sizing
        _ensure_field(risk_data, "ext_liq", snapshot)
        _ensure_field(risk_data, "ext_funding", snapshot)

        # Network learning: inject risk constraints and lessons
        if "network_lessons_risk" in snapshot:
            risk_data["network_lessons"] = snapshot["network_lessons_risk"]
        if "risk_constraints" in snapshot:
            risk_data["hard_constraints"] = snapshot["risk_constraints"]

        # Enriched context from technicals, feedback, telemetry, positions
        if snapshot.get("enriched_context"):
            risk_data["enriched"] = snapshot["enriched_context"]

        # Per-agent self-performance stats for the Risk Agent
        _pt = getattr(self, '_perf_tracker_ref', None)
        if _pt:
            try:
                _self_perf_text = _pt.format_for_agent("risk")
                if _self_perf_text:
                    risk_data["self_performance"] = _self_perf_text
            except Exception:
                pass

        # Pre-trade simulation for risk-aware sizing
        if "_simulation" in snapshot:
            risk_data["simulation"] = snapshot["_simulation"]

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
        # Filter annotations for veto reasoning (weight warnings in decisions)
        if "filt" in snapshot:
            critic_data["filter_assessment"] = snapshot["filt"]
        if "near" in snapshot:
            critic_data["near_miss_signals"] = snapshot["near"]
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

        # External data: compact summary for critic cross-check
        _ensure_field(critic_data, "ext_summary", snapshot)
        _ensure_field(critic_data, "ext_liq", snapshot)

        # Gap 4+5: Inject calibration data for the critic
        try:
            from llm.agents.calibration_ledger import get_calibration_ledger
            ledger = get_calibration_ledger()
            cal_data = ledger.get_compact_for_snapshot("critic")
            if cal_data:
                critic_data["agent_cal"] = cal_data
        except Exception:
            pass

        # Network learning: inject past lessons for better veto decisions
        if "network_lessons_critic" in snapshot:
            critic_data["network_lessons"] = snapshot["network_lessons_critic"]

        # Enriched context from technicals, feedback, telemetry, positions
        if snapshot.get("enriched_context"):
            critic_data["enriched"] = snapshot["enriched_context"]

        # Per-agent self-performance stats for the Critic Agent
        _pt = getattr(self, '_perf_tracker_ref', None)
        if _pt:
            try:
                _self_perf_text = _pt.format_for_agent("critic")
                if _self_perf_text:
                    critic_data["self_performance"] = _self_perf_text
            except Exception:
                pass

        # Pre-trade simulation for stress-testing the thesis
        if "_simulation" in snapshot:
            critic_data["simulation"] = snapshot["_simulation"]

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
        # Inject exit agent reasoning if it was involved in closing this trade
        if self.last_exit_output and self.last_exit_output.ok:
            exit_data = self.last_exit_output.data
            exit_reason = exit_data.get("reason", "")
            exit_action = exit_data.get("action", "")
            if exit_reason and exit_action in ("full_close", "partial_close", "close"):
                relevant["exit_agent_reasoning"] = exit_reason[:200]
                relevant["exit_thesis_valid"] = exit_data.get("thesis_still_valid", True)

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
        consistency_score: float = 1.0,
        consensus_confidence: Optional[float] = None,
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

        # ── Confidence Calibration ──
        # Apply calibration curve to deflate/inflate confidence based on historical accuracy.
        try:
            from llm.brain_wiring import calibrate_confidence
            raw_conf = confidence
            # Calibrator works on 0-100 scale
            conf_pct = confidence * 100 if confidence <= 1.0 else confidence
            calibrated_pct = calibrate_confidence(conf_pct, agent="trade_agent")
            calibrated = calibrated_pct / 100.0 if confidence <= 1.0 else calibrated_pct
            if abs(calibrated - confidence) > 0.01:
                notes += f" | CAL: {raw_conf:.2f}→{calibrated:.2f}"
                confidence = calibrated
        except Exception:
            pass

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

            # Gate Risk Agent's skip power if its accuracy is poor
            if override == "skip":
                try:
                    from llm.agents.calibration_ledger import get_calibration_ledger
                    risk_cal = get_calibration_ledger().get_calibration(
                        "risk", regime_out.data.get("rg", "unknown") if regime_out else "unknown"
                    )
                    if risk_cal.get("reliable") and risk_cal["accuracy"] < 0.45:
                        # Risk Agent is wrong >55% of the time — downgrade skip to reduce
                        override = "reduce"
                        notes += f" | RISK: skip→reduce (risk_vacc={risk_cal['accuracy']:.0%})"
                except Exception:
                    pass

            if override == "skip":
                action = "flat"
                risk_reason = rk.get("reason", rk.get("n", "unspecified"))
                notes += f" | RISK: override to skip ({risk_reason})"
            elif override == "reduce":
                old_mult = size_mult
                size_mult = min(size_mult, 0.7)
                risk_reason = rk.get("reason", rk.get("n", ""))
                notes += f" | RISK: sizing {old_mult:.1f}x→{size_mult:.1f}x ({risk_reason})"

        # Kelly Criterion modulation from Quant Agent
        # If Quant Agent computed a half-Kelly fraction, use it to modulate size.
        # Kelly fraction ~0.15 is our "normal" baseline. Scale around it:
        #   kelly=0.30 → 1.5x size (strong edge), kelly=0.05 → 0.5x (weak edge)
        # Clamped to [0.5, 1.5] to prevent extreme swings.
        scratchpad = get_pipeline_scratchpad()
        kelly_frac = scratchpad.read_by_key("kelly_fraction")
        if kelly_frac is not None and isinstance(kelly_frac, (int, float)) and kelly_frac > 0:
            kelly_baseline = 0.15  # normalized baseline
            kelly_mult = max(0.5, min(1.5, kelly_frac / kelly_baseline))
            old_size = size_mult
            size_mult = max(0.0, min(2.0, size_mult * kelly_mult))
            if abs(kelly_mult - 1.0) > 0.05:
                notes += f" | KELLY: f={kelly_frac:.3f} mult={kelly_mult:.2f} sz={old_size:.2f}→{size_mult:.2f}"

        # ── Graduated Risk: apply drawdown-proportional size reduction ──
        try:
            from llm.brain_wiring import get_graduated_risk
            grm = get_graduated_risk()
            if grm is not None:
                old_size = size_mult
                size_mult = grm.apply_to_risk_multiplier(size_mult)
                if abs(size_mult - old_size) > 0.01:
                    status = grm.get_status()
                    notes += (f" | DD: {status['drawdown_pct']:.1f}% "
                              f"band={status['band']} sz={old_size:.2f}→{size_mult:.2f}")
        except Exception:
            pass

        # Critic Agent: can adjust or override
        # Treat any non-"approve" verdict as a challenge (defensive normalization)
        # PROFITABILITY GATE: if Critic's veto accuracy is poor, limit its power
        counter_thesis = ""
        _critic_vacc = 0.5  # default assumption
        if snapshot_data:
            _sp = snapshot_data.get("self_perf", {})
            if isinstance(_sp, dict):
                _critic_vacc = _sp.get("vacc", 0.5)

        if critic_out and critic_out.ok:
            cd = critic_out.data
            verdict = cd.get("verdict", "approve").lower().strip()
            counter_thesis = cd.get("counter_thesis", "")

            # If Critic veto accuracy < 0.45, block full vetoes — only allow
            # confidence adjustment. Bad vetoes lose more money than bad trades.
            if verdict != "approve" and _critic_vacc < 0.45:
                adj_conf = cd.get("adjusted_confidence")
                if adj_conf is not None:
                    old_conf = confidence
                    confidence = max(confidence * 0.85, float(adj_conf))
                    confidence = max(0.0, min(1.0, confidence))
                    notes += (f" | CRITIC: challenge blocked (vacc={_critic_vacc:.2f}<0.45), "
                              f"conf {old_conf:.2f}→{confidence:.2f}")
                else:
                    notes += f" | CRITIC: challenge blocked (vacc={_critic_vacc:.2f}<0.45)"
                logger.info(
                    f"[COORDINATOR] Critic veto blocked: vacc={_critic_vacc:.2f} < 0.45 "
                    f"— vetoes are losing money, allowing trade with adjusted confidence"
                )
            elif verdict != "approve":
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

        # Gap 7: Scale confidence by consistency score (soft circuit breaker)
        if consistency_score < 0.7 and action != "flat":
            old_conf = confidence
            # Scale: consistency 0.5 → reduce 15%, consistency 0.3 → reduce 35%
            scale = 0.5 + consistency_score * 0.5  # maps [0, 1] → [0.5, 1.0]
            confidence = round(confidence * scale, 3)
            confidence = max(0.0, min(1.0, confidence))
            notes += (f" | CONSISTENCY_ADJ: {old_conf:.2f}→{confidence:.2f} "
                      f"(agents disagreeing, score={consistency_score:.2f})")

        # Gap 1: Apply consensus confidence if it significantly differs
        if consensus_confidence is not None and action != "flat":
            # If consensus is much lower than trade agent's confidence, reduce
            if consensus_confidence < confidence - 0.1:
                old_conf = confidence
                # Blend: 60% trade agent, 40% consensus
                confidence = round(confidence * 0.6 + consensus_confidence * 0.4, 3)
                confidence = max(0.0, min(1.0, confidence))
                notes += (f" | CONSENSUS_ADJ: {old_conf:.2f}→{confidence:.2f} "
                          f"(agents not fully aligned)")

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

        # Default memory note from thesis if Trade Agent didn't provide mu
        if not memory_update and trade_thesis and action in ("go", "proceed"):
            memory_update = trade_thesis[:100]

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

def _compute_confidence_consensus(
    trade_out: AgentOutput,
    regime_out: AgentOutput,
    risk_out: Optional[AgentOutput],
    critic_out: Optional[AgentOutput],
    consistency_score: float,
) -> Optional[float]:
    """Bayesian confidence consensus: sequential probability updating.

    Instead of heuristic multiplicative factors, this computes a posterior
    probability using Bayes' rule. Each agent contributes a likelihood ratio
    (how much their analysis shifts the probability), and the prior is
    updated sequentially:

        posterior = prior × LR_regime × LR_risk × LR_critic × LR_consistency

    Likelihood ratios > 1.0 increase confidence, < 1.0 decrease it.
    The posterior is then converted back to a probability via normalization.

    Returns consensus confidence [0, 1] or None for skip decisions.
    """
    trade_conf = float(trade_out.data.get("c", trade_out.data.get("confidence", 0.0)))
    if trade_conf == 0.0:
        return None  # Skip decisions don't need consensus

    # Prior: Trade Agent's confidence as the starting probability
    prior_odds = trade_conf / max(1.0 - trade_conf, 0.01)  # convert to odds

    # Regime Agent likelihood ratio:
    # High regime confidence in a clear regime → supports the trade
    # Low regime confidence or "unknown" → uncertainty weakens it
    regime_conf = float(regime_out.data.get("conf", regime_out.data.get("confidence", 0.5)))
    regime = regime_out.data.get("rg", regime_out.data.get("regime", "unknown"))
    regime_bias = regime_out.data.get("bias", "neutral")

    # Regime clarity: clear regimes are informative, unknown is not
    if regime == "unknown":
        lr_regime = 0.85  # slight negative: uncertainty
    elif regime_conf >= 0.7:
        # High-confidence regime: does the trade agree with regime bias?
        # If bias aligns with trade direction, boost; if not, reduce
        trade_action = trade_out.data.get("a", trade_out.data.get("action", ""))
        if regime_bias in ("bullish", "risk_on") and trade_action in ("go", "proceed"):
            lr_regime = 1.0 + (regime_conf - 0.5) * 0.4  # 0.7→1.08, 0.9→1.16
        elif regime_bias in ("bearish", "risk_off") and trade_action in ("go", "proceed"):
            lr_regime = 1.0 - (regime_conf - 0.5) * 0.3  # mild headwind
        else:
            lr_regime = 0.9 + regime_conf * 0.1
    else:
        lr_regime = 0.9 + regime_conf * 0.1  # low conf → ~neutral

    # Risk Agent likelihood ratio:
    # Override=skip is strong negative evidence, reduce is moderate, normal sizing is neutral
    lr_risk = 1.0
    if risk_out and risk_out.ok:
        override = risk_out.data.get("override")
        if override == "skip":
            lr_risk = 0.2  # Risk Agent sees major problems
        elif override == "reduce":
            lr_risk = 0.6  # Moderate concern
        else:
            size_mult = float(risk_out.data.get("sz", risk_out.data.get("size_multiplier", 1.0)))
            # Large size = bullish, small = bearish on this trade
            lr_risk = 0.7 + min(size_mult, 2.0) * 0.3  # 0.5→0.85, 1.0→1.0, 1.5→1.15

    # Critic Agent likelihood ratio:
    # Approval is confirmatory evidence, veto is disconfirming
    lr_critic = 1.0
    if critic_out and critic_out.ok:
        verdict = critic_out.data.get("verdict", "approve").lower().strip()
        if verdict == "approve":
            lr_critic = 1.1  # Confirmed by independent review
        else:
            adj_conf = critic_out.data.get("adjusted_confidence")
            if adj_conf is not None:
                # Critic's adjusted confidence implies their belief about the true probability
                # LR = P(critic_says_challenge | trade_is_good) / P(critic_says_challenge | trade_is_bad)
                # Approximate: if critic says conf=0.3, it's strong disconfirmation
                lr_critic = max(0.3, 0.5 + float(adj_conf))
            else:
                lr_critic = 0.5  # Challenge without specifics = moderate disconfirmation

    # Consistency score as likelihood ratio:
    # Agents agreeing is evidence the analysis is sound
    lr_consistency = 0.6 + consistency_score * 0.5  # [0,1] → [0.6, 1.1]

    # Bayesian update: multiply all likelihood ratios with prior odds
    posterior_odds = prior_odds * lr_regime * lr_risk * lr_critic * lr_consistency

    # Convert back to probability
    posterior = posterior_odds / (1.0 + posterior_odds)

    # Clamp to [0.05, 0.95] — never be absolutely certain
    posterior = max(0.05, min(0.95, posterior))

    return round(posterior, 3)


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
    """Parse JSON from agent response, handling markdown fences and truncation."""
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
        # Try repairing truncated JSON by closing open braces/brackets
        repaired = _try_repair_truncated_json(text)
        if repaired:
            return repaired
    return None


def _try_repair_truncated_json(text: str) -> Optional[dict]:
    """Attempt to repair truncated JSON by closing open braces/brackets."""
    # Find the start of JSON
    start = text.find("{")
    if start < 0:
        return None
    fragment = text[start:]
    # Remove any trailing partial string (e.g., `"key": "some text` without closing quote)
    # by finding the last complete key-value pair
    # Strategy: progressively close open brackets/braces
    open_braces = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")
    if open_braces <= 0 and open_brackets <= 0:
        return None  # Not a truncation issue
    # Strip trailing partial values (e.g., incomplete strings)
    # Find last comma or colon, trim after that, then close
    last_complete = max(fragment.rfind(","), fragment.rfind(":"), fragment.rfind("}"), fragment.rfind("]"))
    if last_complete > 0:
        # If last char before our closing is a colon, drop the incomplete key-value pair
        trimmed = fragment[:last_complete]
        if trimmed.rstrip().endswith(":") or trimmed.rstrip().endswith(","):
            trimmed = trimmed.rstrip().rstrip(":,")
        suffix = "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        try:
            parsed = json.loads(trimmed + suffix)
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

    if role in (AgentRole.REGIME, AgentRole.RISK, AgentRole.LEARNING, AgentRole.EXIT, AgentRole.SCOUT, AgentRole.QUANT):
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
        AgentRole.OVERSEER: "AGENT_OVERSEER_MODEL",
        AgentRole.QUANT: "AGENT_QUANT_MODEL",
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
        AgentRole.OVERSEER: "AGENT_OVERSEER_ENABLED",
        AgentRole.QUANT: "AGENT_QUANT_ENABLED",
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
