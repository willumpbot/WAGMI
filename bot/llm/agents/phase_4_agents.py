"""
Phase 4 Agent Methods: Scalping + Conviction Trading

These methods implement the 3 new Phase 4 agents:
1. Micro-Trend Detector - 5m micro-trend classification (frequent)
2. Scalper - 1m/5m micro-scalp opportunities (very frequent)
3. Conviction - Ultra-high confidence trade authorization (rare)

These agents run at different frequencies:
- Micro-Trend: Every 5m
- Scalper: Every 1m (when enabled)
- Conviction: Per signal (when alignment > 0.85)
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from llm.agents.base import AgentConfig, AgentOutput, AgentRole
from llm.agents.shared_context import get_pipeline_scratchpad

logger = logging.getLogger("bot.llm.agents.phase_4_agents")


def build_micro_trend_detector(
    coordinator: Any,
    model_for_trigger: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run Micro-Trend Detector agent to classify 5m micro-trends.
    Used to feed context into Scalper Agent.

    Returns:
        Parsed micro-trend dict or None on failure.
    """
    cfg = coordinator.configs.get(
        AgentRole.MICRO_TREND,
        AgentConfig(role=AgentRole.MICRO_TREND),
    )
    if not cfg.enabled:
        return None

    micro_trend_input = _build_micro_trend_input(coordinator)
    out = coordinator._call_agent(AgentRole.MICRO_TREND, micro_trend_input, model_for_trigger)

    if not out.ok:
        logger.warning("[MICRO_TREND] Agent call failed")
        return None

    data = out.data
    scratchpad = get_pipeline_scratchpad()

    # Write micro-trend to scratchpad for Scalper to read
    scratchpad.write("micro_trend", "classification", data.get("micro_trend"))
    scratchpad.write("micro_trend", "strength", data.get("trend_strength", 0.5))
    scratchpad.write("micro_trend", "continuation", data.get("expected_continuation"))
    scratchpad.write("micro_trend", "key_level", data.get("key_level"))

    logger.debug(
        f"[MICRO_TREND] {data.get('micro_trend')} "
        f"(strength={data.get('trend_strength', 0.5):.2f}, "
        f"continuation={data.get('expected_continuation')})"
    )
    return data


def build_scalper(
    coordinator: Any,
    model_for_trigger: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run Scalper agent to find 1m-5m micro-trading opportunities.
    Runs very frequently (every 1m when enabled).

    Returns:
        Parsed scalp signal dict or None on failure.
    """
    cfg = coordinator.configs.get(
        AgentRole.SCALPER,
        AgentConfig(role=AgentRole.SCALPER),
    )
    if not cfg.enabled:
        return None

    scalper_input = _build_scalper_input(coordinator)
    out = coordinator._call_agent(AgentRole.SCALPER, scalper_input, model_for_trigger)

    if not out.ok:
        logger.warning("[SCALPER] Agent call failed")
        return None

    data = out.data
    scratchpad = get_pipeline_scratchpad()

    # Write scalp signal to scratchpad
    if data.get("action") == "scalp_now":
        scratchpad.write("scalper", "signal", "scalp_now")
        scratchpad.write("scalper", "target_ticks", data.get("target_ticks"))
        scratchpad.write("scalper", "risk_ticks", data.get("risk_ticks"))
        scratchpad.write("scalper", "confidence", data.get("confidence"))
        scratchpad.write("scalper", "hold_time_seconds", data.get("hold_time_seconds"))

        logger.info(
            f"[SCALPER] SCALP_NOW: thesis='{data.get('thesis')}' "
            f"(conf={data.get('confidence', 0.0):.2f}, target={data.get('target_ticks')} ticks)"
        )

    return data


def build_conviction(
    coordinator: Any,
    regime_out: AgentOutput,
    trade_out: AgentOutput,
    quant_out: Optional[AgentOutput],
    critic_out: Optional[AgentOutput],
    forecaster_out: Optional[AgentOutput],
    model_for_trigger: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run Conviction Agent to authorize high-leverage trades when all agents align.
    Runs per signal (rare, ~5-10/month if lucky).

    Args:
        regime_out, trade_out, quant_out, critic_out, forecaster_out: Agent outputs

    Returns:
        Parsed conviction analysis dict or None on failure.
    """
    cfg = coordinator.configs.get(
        AgentRole.CONVICTION,
        AgentConfig(role=AgentRole.CONVICTION),
    )
    if not cfg.enabled:
        return None

    conviction_input = _build_conviction_input(
        coordinator, regime_out, trade_out, quant_out, critic_out, forecaster_out
    )
    out = coordinator._call_agent(AgentRole.CONVICTION, conviction_input, model_for_trigger)

    if not out.ok:
        logger.warning("[CONVICTION] Agent call failed")
        return None

    data = out.data
    scratchpad = get_pipeline_scratchpad()

    # Write conviction to scratchpad
    conviction_level = data.get("conviction_level", 0)
    scratchpad.write("conviction", "level", conviction_level)
    scratchpad.write("conviction", "alignment_score", data.get("alignment_score"))
    scratchpad.write("conviction", "leverage_multiplier", data.get("position_size_multiplier", 1.5))
    scratchpad.write("conviction", "risk_override", data.get("risk_override", False))

    if conviction_level >= 3:
        logger.info(
            f"[CONVICTION] LEVEL {conviction_level} AUTHORIZED "
            f"(alignment={data.get('alignment_score', 0.0):.2f}, "
            f"leverage={data.get('position_size_multiplier', 1.5)}x, "
            f"thesis='{data.get('thesis', '')[:60]}...')"
        )

    return data


# ─── Input Builders ─────────────────────────────────────────────────

def _build_micro_trend_input(coordinator: Any) -> str:
    """Build input context for Micro-Trend Detector agent."""
    # This would include:
    # - Last 5 × 1m candles (OHLCV)
    # - Last 3 × 5m candles with RSI, MACD, volume
    # - Key support/resistance levels

    context = {
        "note": "Micro-trend classification request",
        "timestamp": "NOW",
        "recent_1m_candles": "TODO: inject last 5 × 1m candles from OHLCV",
        "recent_5m_candles": "TODO: inject last 3 × 5m candles with indicators",
        "support_resistance": "TODO: inject key levels from technical analysis",
    }
    return json.dumps(context, indent=2)


def _build_scalper_input(coordinator: Any) -> str:
    """Build input context for Scalper agent."""
    # This would include:
    # - Current price + latest 1m candle (OHLCV)
    # - Last 5 × 5m candles with RSI, MACD, volume
    # - Micro-trend classification (from Micro-Trend Detector)
    # - Current bid-ask spread, order book depth
    # - Recent fill latency and success rate

    context = {
        "note": "Micro-scalp opportunity detection",
        "timestamp": "NOW",
        "current_candle": "TODO: inject latest 1m candle",
        "recent_5m_candles": "TODO: inject last 5 × 5m candles with indicators",
        "micro_trend": "TODO: inject from Micro-Trend Detector output",
        "bid_ask_spread": "TODO: inject from orderbook snapshot",
        "fill_metrics": "TODO: inject recent execution stats",
    }
    return json.dumps(context, indent=2)


def _build_conviction_input(
    coordinator: Any,
    regime_out: AgentOutput,
    trade_out: AgentOutput,
    quant_out: Optional[AgentOutput],
    critic_out: Optional[AgentOutput],
    forecaster_out: Optional[AgentOutput],
) -> str:
    """Build input context for Conviction Agent."""
    # Aggregate alignment signals from all agents

    conviction_input = {
        "regime_analysis": regime_out.data if regime_out.ok else {"confidence": 0.0},
        "trade_decision": trade_out.data if trade_out.ok else {"confidence": 0.0},
        "quant_analysis": quant_out.data if (quant_out and quant_out.ok) else {"ev": 0.0, "signal_quality": {"noise_probability": 1.0}},
        "critic_analysis": critic_out.data if (critic_out and critic_out.ok) else {"concern_level": "high"},
        "forecaster_analysis": forecaster_out.data if (forecaster_out and forecaster_out.ok) else {"transition_probability": 1.0},
    }

    # Compute alignment score (quick estimation)
    regime_conf = conviction_input["regime_analysis"].get("confidence", 0.0)
    trade_conf = conviction_input["trade_decision"].get("confidence", 0.0)
    _sq = conviction_input["quant_analysis"].get("signal_quality", {})
    _np = _sq.get("noise_probability", 1.0 if _sq.get("is_noise", True) else 0.0)
    quant_quality = max(0.0, 1.0 - _np)
    critic_concern_map = {"none": 1.0, "low": 0.8, "medium": 0.5, "high": 0.0}
    critic_score = critic_concern_map.get(
        str(conviction_input["critic_analysis"].get("concern_level", "high")).lower(), 0.0
    )
    forecast_stability = 1.0 - conviction_input["forecaster_analysis"].get("transition_probability", 0.5)

    alignment = (regime_conf + trade_conf + quant_quality + critic_score + forecast_stability) / 5.0

    conviction_input["computed_alignment_score"] = round(alignment, 3)

    return json.dumps(conviction_input, indent=2)
