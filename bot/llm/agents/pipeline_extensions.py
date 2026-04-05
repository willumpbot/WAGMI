"""
Pipeline Extensions: bridges new infrastructure modules into the coordinator.

This module provides clean integration points for:
1. Quant Engine — inject deterministic math into agent prompts
2. Agent Brains — inject per-agent beliefs and calibration
3. Debate System — post-pipeline consensus synthesis

The coordinator imports these hooks and calls them at the right points
in the pipeline without bloating coordinator.py itself.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.pipeline_extensions")


# ── Quant Engine Integration ────────────────────────────────────────

def compute_quant_context(
    snapshot: dict,
    regime: str = "unknown",
    side: str = "",
    entry: float = 0.0,
    sl: float = 0.0,
    tp1: float = 0.0,
) -> Dict[str, Any]:
    """Compute deterministic quant metrics for agent prompts.

    Called before Trade Agent to provide math it should NOT compute itself.
    Returns a dict of pre-computed metrics.
    """
    try:
        from llm.agents.quant_engine import QuantEngine
    except ImportError:
        logger.debug("[PIPELINE_EXT] quant_engine not available yet")
        return {}

    try:
        # Extract relevant data from snapshot
        markets = snapshot.get("m", [])
        if not markets:
            return {}

        market = markets[0] if isinstance(markets, list) else markets
        price = market.get("price", market.get("p", 0.0))
        funding_rate = market.get("funding", market.get("fr", 0.0))

        # Get portfolio equity if available
        port = snapshot.get("portfolio", snapshot.get("port", {}))
        equity = port.get("equity", port.get("eq", 1000.0))

        engine = QuantEngine(equity=equity)

        result = {}

        # If we have entry/sl/tp, compute full trade metrics
        if entry > 0 and sl > 0 and tp1 > 0:
            # Estimate win rate from regime metadata
            from llm.agents.shared_context import get_regime_metadata
            meta = get_regime_metadata(regime)
            est_wr = meta.get("avg_win_rate", 0.50) if meta else 0.50

            # Estimate avg win/loss from R:R
            if side.upper() in ("BUY", "LONG"):
                risk = abs(entry - sl)
                reward = abs(tp1 - entry)
            else:
                risk = abs(sl - entry)
                reward = abs(entry - tp1)

            if risk > 0:
                rr = reward / risk
                avg_win_pct = (reward / entry) * 100
                avg_loss_pct = (risk / entry) * 100

                result["risk_reward"] = round(rr, 2)
                result["kelly_fraction"] = engine.half_kelly(est_wr, avg_win_pct, avg_loss_pct)
                result["expected_value_pct"] = engine.expected_value_pct(est_wr, avg_win_pct, avg_loss_pct)
                result["breakeven_wr"] = engine.breakeven_win_rate(avg_win_pct, avg_loss_pct)
                result["position_size"] = engine.optimal_position_size(
                    equity, result["kelly_fraction"]
                )

        # Funding projection
        if funding_rate and abs(funding_rate) > 0:
            result["funding_4h"] = engine.funding_projection(funding_rate, equity * 0.1, 4)
            result["funding_8h"] = engine.funding_projection(funding_rate, equity * 0.1, 8)

        return result

    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] quant_context error: {e}")
        return {}


def format_quant_for_prompt(quant_data: dict) -> str:
    """Format quant metrics as a compact string for agent prompts."""
    if not quant_data:
        return ""

    parts = []
    if "risk_reward" in quant_data:
        parts.append(f"R:R={quant_data['risk_reward']:.1f}")
    if "kelly_fraction" in quant_data:
        parts.append(f"½Kelly={quant_data['kelly_fraction']:.3f}")
    if "expected_value_pct" in quant_data:
        ev = quant_data["expected_value_pct"]
        parts.append(f"EV={ev:+.2f}%")
    if "breakeven_wr" in quant_data:
        parts.append(f"BE_WR={quant_data['breakeven_wr']:.0%}")
    if "funding_4h" in quant_data:
        parts.append(f"funding_4h=${quant_data['funding_4h']:.2f}")

    return "QUANT: " + " | ".join(parts) if parts else ""


# ── Agent Brain Integration ─────────────────────────────────────────

def get_brain_context_for_agent(agent_role: str, regime: str = "", symbol: str = "") -> str:
    """Get brain-derived context to inject into an agent's prompt.

    Returns compact string with:
    - Top beliefs relevant to current context
    - Performance summary
    - Calibration adjustment recommendation
    """
    try:
        from llm.agents.agent_brain import get_brain_manager
    except ImportError:
        return ""

    try:
        manager = get_brain_manager()
        brain = manager.get_brain(agent_role)

        parts = []

        # Top beliefs for this context
        beliefs = brain.get_beliefs_for_context(regime, symbol, top_k=3)
        if beliefs:
            belief_strs = [f"'{b.statement}' ({b.confidence:.0%})" for b in beliefs]
            parts.append("BELIEFS: " + " | ".join(belief_strs))

        # Performance summary
        perf_summary = brain.get_performance_summary()
        if perf_summary:
            parts.append(f"SELF: {perf_summary}")

        # Calibration note
        cal_err = brain.calibration_error()
        if cal_err > 0.15:
            parts.append(f"⚠️ CALIBRATION: You are {cal_err:.0%} overconfident. Reduce confidence.")
        elif cal_err < -0.15:
            parts.append(f"CALIBRATION: You are {abs(cal_err):.0%} underconfident. Trust your analysis more.")

        return " || ".join(parts) if parts else ""

    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] brain_context error for {agent_role}: {e}")
        return ""


def record_agent_decision(
    agent_role: str,
    decision: dict,
    regime: str = "",
) -> None:
    """Record an agent's decision in its brain for learning.

    Called after each agent produces output in the pipeline.
    """
    try:
        from llm.agents.agent_brain import get_brain_manager
        manager = get_brain_manager()
        brain = manager.get_brain(agent_role)
        brain.record_decision({
            "regime": regime,
            **decision,
        })
    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] record_decision error for {agent_role}: {e}")


def record_agent_outcome(
    agent_role: str,
    decision_id: str,
    was_correct: bool,
    details: dict,
) -> None:
    """Record outcome for brain learning after trade closes."""
    try:
        from llm.agents.agent_brain import get_brain_manager
        manager = get_brain_manager()
        brain = manager.get_brain(agent_role)
        brain.record_outcome(decision_id, was_correct, details)
        brain.save()
    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] record_outcome error for {agent_role}: {e}")


# ── Debate Integration ──────────────────────────────────────────────

def run_debate_if_warranted(
    agent_outputs: Dict[str, Any],
    regime: str = "unknown",
    symbol: str = "",
) -> Optional[Dict[str, Any]]:
    """Run debate mechanism if there's disagreement between agents.

    Called after all agents have produced output, before _merge_outputs.
    Returns debate outcome dict or None if debate wasn't needed.
    """
    try:
        from llm.agents.debate import DebateManager, Position
    except ImportError:
        return None

    try:
        # Extract positions from agent outputs
        positions = []

        # Regime Agent position
        regime_data = agent_outputs.get("regime", {})
        if regime_data:
            bias = regime_data.get("bias", "neutral")
            conf = float(regime_data.get("conf", 0.5))
            positions.append(Position(
                agent="regime",
                stance=bias if bias in ("bullish", "bearish") else "neutral",
                confidence=conf,
                reasoning=regime_data.get("factors", ""),
                evidence=[],
                counter_arguments=[],
            ))

        # Trade Agent position
        trade_data = agent_outputs.get("trade", {})
        if trade_data:
            action = trade_data.get("a", trade_data.get("action", "skip"))
            conf = float(trade_data.get("c", trade_data.get("confidence", 0.0)))
            side = trade_data.get("side", trade_data.get("s", ""))

            if action in ("go", "proceed"):
                stance = "bullish" if side.upper() in ("BUY", "LONG") else "bearish"
            elif action == "flip":
                stance = "bearish" if side.upper() in ("BUY", "LONG") else "bullish"
            else:
                stance = "neutral"

            positions.append(Position(
                agent="trade",
                stance=stance,
                confidence=conf,
                reasoning=trade_data.get("thesis", trade_data.get("n", "")),
                evidence=[],
                counter_arguments=[],
            ))

        # Critic Agent position
        critic_data = agent_outputs.get("critic", {})
        if critic_data:
            verdict = critic_data.get("verdict", "approve")
            counter = critic_data.get("counter_thesis", "")
            adj_conf = critic_data.get("adjusted_confidence")

            if verdict == "approve":
                # Critic agrees with trade
                stance = positions[-1].stance if positions else "neutral"
                conf = float(adj_conf or positions[-1].confidence if positions else 0.5)
            else:
                # Critic disagrees
                stance = "neutral" if verdict == "challenge" else "skip"
                conf = 0.3

            positions.append(Position(
                agent="critic",
                stance=stance,
                confidence=conf,
                reasoning=counter or verdict,
                evidence=critic_data.get("red_flags", []),
                counter_arguments=[],
            ))

        if len(positions) < 2:
            return None

        # Run debate
        manager = DebateManager()
        disagreements = manager.detect_disagreements(positions)

        # Only debate if there's actual disagreement
        if not disagreements:
            return None

        outcome = manager.weighted_consensus(positions)
        logger.info(
            f"[DEBATE] {symbol} consensus={outcome.consensus_direction} "
            f"conf={outcome.consensus_confidence:.2f} "
            f"agreement={outcome.agreement_score:.2f}"
        )

        return {
            "consensus_direction": outcome.consensus_direction,
            "consensus_confidence": outcome.consensus_confidence,
            "agreement_score": outcome.agreement_score,
            "dissenting_agents": outcome.dissenting_agents,
            "key_arguments_for": outcome.key_arguments_for,
            "key_arguments_against": outcome.key_arguments_against,
            "risk_flags": outcome.risk_flags,
            "debate_rounds": outcome.debate_rounds,
        }

    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] debate error: {e}")
        return None


def apply_debate_to_confidence(
    base_confidence: float,
    debate_outcome: Optional[Dict[str, Any]],
) -> float:
    """Adjust confidence based on debate outcome.

    High agreement → confidence preserved or boosted
    Low agreement → confidence reduced
    """
    if not debate_outcome:
        return base_confidence

    agreement = debate_outcome.get("agreement_score", 1.0)

    if agreement >= 0.8:
        # Strong agreement — slight boost
        return min(1.0, base_confidence * 1.05)
    elif agreement >= 0.6:
        # Moderate agreement — no change
        return base_confidence
    elif agreement >= 0.4:
        # Low agreement — reduce 10%
        return base_confidence * 0.90
    else:
        # Very low agreement — reduce 20%
        return base_confidence * 0.80


# ── Interactive Debate Integration ──────────────────────────────

def run_interactive_debate_if_enabled(
    trade_agent_output: Dict[str, Any],
    critic_agent_output: Optional[Dict[str, Any]],
    market_context: Dict[str, Any],
    risk_assessment: Optional[Dict[str, Any]] = None,
    position_size_pct: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Run real 2-round Trade-Critic debate if enabled and warranted.

    Uses DebateProtocol for actual LLM calls (Trade rebuttal + Critic final).
    Falls back to simulated scoring if LLM calls fail.

    Args:
        trade_agent_output: Trade Agent's decision output
        critic_agent_output: Critic Agent's response (already generated in main pipeline)
        market_context: Market data for context
        risk_assessment: Risk Agent's output (for trigger evaluation)
        position_size_pct: Estimated position size as % of equity

    Returns:
        Debate resolution dict or None if debate not triggered/run
    """
    # Check if interactive debate is enabled
    if not os.getenv("LLM_INTERACTIVE_DEBATE", "false").lower() in ("1", "true", "yes"):
        return None

    if not critic_agent_output or not trade_agent_output:
        return None

    try:
        from llm.agents.debate_protocol import DebateProtocol

        protocol = DebateProtocol()

        # Check if debate is warranted based on trigger criteria
        if not protocol.should_debate(
            trade_decision=trade_agent_output,
            risk_assessment=risk_assessment or {},
            critic_response=critic_agent_output,
            position_size_pct=position_size_pct,
        ):
            logger.debug("[PIPELINE_EXT] Debate not triggered (below thresholds)")
            return None

        # Run real 2-round debate with LLM calls
        result = protocol.run_debate(
            trade_decision=trade_agent_output,
            critic_response=critic_agent_output,
            snapshot_data=market_context,
        )

        if result.get("debate_occurred"):
            logger.info(
                f"[DEBATE_PROTOCOL] winner={result['winner']} "
                f"adj={result['confidence_adjustment']:+d}% "
                f"final_conf={result['final_confidence']:.2f} "
                f"tokens={result.get('cost_tokens', 0)}"
            )

        return {
            "debate_type": "interactive",
            "final_action": result.get("winner", "draw"),
            "final_confidence": result.get("final_confidence", 0.5),
            "winner": result.get("winner", "draw"),
            "confidence_adjustment": result.get("confidence_adjustment", 0),
            "key_turning_points": result.get("key_turning_points", []),
            "risk_flags": result.get("risk_flags", []),
            "recommendation": result.get("recommendation", "proceed"),
            "rounds_used": result.get("rounds", 0),
            "debate_occurred": result.get("debate_occurred", False),
            "reasoning": result.get("reasoning", ""),
        }

    except ImportError:
        logger.debug("[PIPELINE_EXT] debate_protocol module not available")
        return None
    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] debate_protocol error: {e}")
        return None


# ── Pipeline Telemetry ──────────────────────────────────────────────

def log_pipeline_telemetry(
    pipeline_results: dict,
    total_latency_ms: int,
    decision_action: str,
    decision_confidence: float,
) -> None:
    """Log pipeline telemetry for the API to read."""
    import time

    telemetry = {
        "ts": time.time(),
        "total_latency_ms": total_latency_ms,
        "decision_action": decision_action,
        "decision_confidence": round(decision_confidence, 3),
        "agents": {},
        "total_tokens": 0,
        "estimated_cost": 0.0,
    }

    # Cost estimates per model
    cost_per_1k = {
        "haiku": 0.001,
        "sonnet": 0.003,
        "opus": 0.015,
    }

    for role, output in pipeline_results.items():
        role_name = role.value if hasattr(role, "value") else str(role)
        agent_data = {
            "ok": output.ok if hasattr(output, "ok") else bool(output),
            "latency_ms": getattr(output, "latency_ms", 0),
            "input_tokens": getattr(output, "input_tokens", 0),
            "output_tokens": getattr(output, "output_tokens", 0),
            "model": getattr(output, "model_used", ""),
        }
        total_tok = agent_data["input_tokens"] + agent_data["output_tokens"]
        telemetry["total_tokens"] += total_tok

        # Estimate cost
        model = agent_data["model"].lower()
        for model_key, rate in cost_per_1k.items():
            if model_key in model:
                agent_data["estimated_cost"] = round(total_tok / 1000 * rate, 5)
                telemetry["estimated_cost"] += agent_data["estimated_cost"]
                break

        telemetry["agents"][role_name] = agent_data

    telemetry["estimated_cost"] = round(telemetry["estimated_cost"], 5)

    # Append to telemetry file
    try:
        import os
        telemetry_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "llm", "pipeline_telemetry.jsonl"
        )
        os.makedirs(os.path.dirname(telemetry_path), exist_ok=True)
        with open(telemetry_path, "a") as f:
            f.write(json.dumps(telemetry) + "\n")
    except Exception as e:
        logger.debug(f"[PIPELINE_EXT] telemetry write error: {e}")


__all__ = [
    "compute_quant_context",
    "format_quant_for_prompt",
    "get_brain_context_for_agent",
    "record_agent_decision",
    "record_agent_outcome",
    "run_debate_if_warranted",
    "apply_debate_to_confidence",
    "run_interactive_debate_if_enabled",
    "log_pipeline_telemetry",
]
