"""
Phase 4A Agent Methods: Core Trading System (Position Sizer, Entry Optimizer, Exit Advisor, Risk Guard, Router, Consensus Builder)

These methods implement the 6 Phase 4A specialist agents:
1. Position Sizer - Calculate exact position size in USD based on edge and capital
2. Entry Optimizer - Determine entry method (market/limit/scaled/wait) and timing
3. Exit Advisor - Recommend exit actions for open positions
4. Risk Guard - Safety gate that prevents catastrophic losses
5. Agent Router - Orchestration logic for which agents to call
6. Consensus Builder - Final decision merger
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from llm.agents.base import AgentConfig, AgentOutput, AgentRole
from llm.agents.shared_context import get_pipeline_scratchpad

logger = logging.getLogger("bot.llm.agents.phase_4a_trading_agents")


def build_position_sizer(
    coordinator: Any,
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
    Position Sizer Agent: Calculate exact position size in USD.

    Args:
        coordinator: The coordinator instance
        capital: Current account equity in USD
        edge_confidence: Confidence 0.0-1.0 of trade profitability
        kelly_fraction: Pre-calculated Kelly fraction from Quant Agent
        regime: Current market regime
        risk_per_trade: Max % of capital at risk per trade
        leverage: Authorized leverage multiplier
        atr: Current ATR in dollars
        stop_distance: Stop loss distance from entry in dollars
        consecutive_losses: Number of consecutive losses
        model_for_trigger: Optional model override

    Returns:
        Dict with position_size_usd, leverage_applied, kelly_applied, rationale, conservative_due_to flags
    """
    cfg = coordinator.configs.get(
        AgentRole.POSITION_SIZER,
        AgentConfig(role=AgentRole.POSITION_SIZER),
    )
    if not cfg.enabled:
        return None

    position_sizer_input = _build_position_sizer_input(
        capital=capital,
        edge_confidence=edge_confidence,
        kelly_fraction=kelly_fraction,
        regime=regime,
        risk_per_trade=risk_per_trade,
        leverage=leverage,
        atr=atr,
        stop_distance=stop_distance,
        consecutive_losses=consecutive_losses,
    )

    out = coordinator._call_agent(AgentRole.POSITION_SIZER, position_sizer_input, model_for_trigger)

    if not out.ok:
        logger.warning("[POSITION_SIZER] Agent call failed")
        return None

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["position_sizer_output"] = out.data

    return out.data


def build_entry_optimizer(
    coordinator: Any,
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
    Entry Optimizer Agent: Decide how to enter (timing + method).

    Args:
        coordinator: The coordinator instance
        signal_confidence: Signal confidence 0.0-1.0
        current_price: Current market price
        entry_price_from_signal: Entry price recommended by signal
        regime: Current market regime
        recent_momentum: Recent momentum direction (up|down|flat)
        order_book: Optional order book context {bid, ask, bid_size, ask_size}
        position_size_usd: Position size we want to achieve
        model_for_trigger: Optional model override

    Returns:
        Dict with entry_method, entry_price, urgency, rationale
    """
    cfg = coordinator.configs.get(
        AgentRole.ENTRY_OPTIMIZER,
        AgentConfig(role=AgentRole.ENTRY_OPTIMIZER),
    )
    if not cfg.enabled:
        return None

    entry_optimizer_input = _build_entry_optimizer_input(
        signal_confidence=signal_confidence,
        current_price=current_price,
        entry_price_from_signal=entry_price_from_signal,
        regime=regime,
        recent_momentum=recent_momentum,
        order_book=order_book,
        position_size_usd=position_size_usd,
    )

    out = coordinator._call_agent(AgentRole.ENTRY_OPTIMIZER, entry_optimizer_input, model_for_trigger)

    if not out.ok:
        logger.warning("[ENTRY_OPTIMIZER] Agent call failed")
        return None

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["entry_optimizer_output"] = out.data

    return out.data


def build_exit_advisor(
    coordinator: Any,
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
    Exit Advisor Agent: Recommend exit actions for open positions.

    Args:
        coordinator: The coordinator instance
        position_id: Position ID
        symbol: Trading symbol
        side: long|short
        entry_price: Entry price
        current_price: Current price
        pnl_usd: Unrealized PnL in USD
        thesis: Original directional prediction
        regime: Current market regime
        original_regime: Regime when trade was entered
        time_held_seconds: How long position has been open
        funding_paid: Total funding paid
        volume_trend: Volume trend (increasing|stable|decreasing)
        model_for_trigger: Optional model override

    Returns:
        Dict with action, reasoning, thesis_still_valid, updated_stop_loss, updated_tp
    """
    cfg = coordinator.configs.get(
        AgentRole.EXIT_ADVISOR,
        AgentConfig(role=AgentRole.EXIT_ADVISOR),
    )
    if not cfg.enabled:
        return None

    exit_advisor_input = _build_exit_advisor_input(
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
    )

    out = coordinator._call_agent(AgentRole.EXIT_ADVISOR, exit_advisor_input, model_for_trigger)

    if not out.ok:
        logger.warning("[EXIT_ADVISOR] Agent call failed")
        return None

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["exit_advisor_output"] = out.data

    return out.data


def build_risk_guard(
    coordinator: Any,
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
    Risk Guard Agent: Safety gate to prevent catastrophic losses.

    Args:
        coordinator: The coordinator instance
        proposed_trade: The proposed trade dict
        portfolio_leverage: Current portfolio-wide leverage
        circuit_breaker_active: Is circuit breaker active?
        daily_loss_pct: % of capital lost today
        consecutive_losses: Number of consecutive losses
        open_positions: List of open positions
        max_single_position_pct: Max single position as % of capital
        max_portfolio_leverage: Max portfolio leverage allowed
        correlation_to_open: Correlation of proposed trade to existing positions
        model_for_trigger: Optional model override

    Returns:
        Dict with approved, risk_flags, max_size_allowed, reasoning
    """
    cfg = coordinator.configs.get(
        AgentRole.RISK_GUARD,
        AgentConfig(role=AgentRole.RISK_GUARD),
    )
    if not cfg.enabled:
        return None

    risk_guard_input = _build_risk_guard_input(
        proposed_trade=proposed_trade,
        portfolio_leverage=portfolio_leverage,
        circuit_breaker_active=circuit_breaker_active,
        daily_loss_pct=daily_loss_pct,
        consecutive_losses=consecutive_losses,
        open_positions=open_positions or [],
        max_single_position_pct=max_single_position_pct,
        max_portfolio_leverage=max_portfolio_leverage,
        correlation_to_open=correlation_to_open,
    )

    out = coordinator._call_agent(AgentRole.RISK_GUARD, risk_guard_input, model_for_trigger)

    if not out.ok:
        logger.warning("[RISK_GUARD] Agent call failed")
        return None

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["risk_guard_output"] = out.data

    return out.data


def build_agent_router(
    coordinator: Any,
    signal: Dict[str, Any],
    market_state: Dict[str, Any],
    portfolio_state: Dict[str, Any],
    system_state: Optional[Dict[str, Any]] = None,
    model_for_trigger: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Agent Router: Orchestration logic for which agents to call and how.

    Args:
        coordinator: The coordinator instance
        signal: Trade signal dict
        market_state: Market state dict (volatility, volume, funding, etc)
        portfolio_state: Portfolio state dict (leverage, positions, pnl, etc)
        system_state: System state dict (cache_fresh, latency, budget, etc)
        model_for_trigger: Optional model override

    Returns:
        Dict with route, agents_to_call, agent_configs, reasoning
    """
    cfg = coordinator.configs.get(
        AgentRole.AGENT_ROUTER,
        AgentConfig(role=AgentRole.AGENT_ROUTER),
    )
    if not cfg.enabled:
        # Default routing: call all agents
        return {
            "route": "normal_pipeline",
            "agents_to_call": ["position_sizer", "entry_optimizer", "risk_guard", "exit_advisor"],
            "agent_configs": {},
            "reasoning": "default routing"
        }

    agent_router_input = _build_agent_router_input(
        signal=signal,
        market_state=market_state,
        portfolio_state=portfolio_state,
        system_state=system_state or {},
    )

    out = coordinator._call_agent(AgentRole.AGENT_ROUTER, agent_router_input, model_for_trigger)

    if not out.ok:
        logger.warning("[AGENT_ROUTER] Agent call failed, using default routing")
        return {
            "route": "normal_pipeline",
            "agents_to_call": ["position_sizer", "entry_optimizer", "risk_guard", "exit_advisor"],
            "agent_configs": {},
            "reasoning": "agent_router failed, fallback to default"
        }

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["agent_router_output"] = out.data

    return out.data


def build_consensus_builder(
    coordinator: Any,
    position_sizer_output: Dict[str, Any],
    entry_optimizer_output: Dict[str, Any],
    risk_guard_output: Dict[str, Any],
    exit_advisor_output: Dict[str, Any],
    original_signal: Dict[str, Any],
    route: str = "normal_pipeline",
    model_for_trigger: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Consensus Builder Agent: Final decision merger.

    Synthesizes outputs from all specialist agents into one unified trade decision
    (execute with specific parameters, or skip).

    Args:
        coordinator: The coordinator instance
        position_sizer_output: Output from Position Sizer agent
        entry_optimizer_output: Output from Entry Optimizer agent
        risk_guard_output: Output from Risk Guard agent
        exit_advisor_output: Output from Exit Advisor agent
        original_signal: Original trade signal
        route: Routing strategy (normal_pipeline|fast_scalp|conviction_only)
        model_for_trigger: Optional model override

    Returns:
        Dict with final_decision (execute|skip), symbol, side, position_size, leverage, entry_method,
        stop_loss, take_profit_1, take_profit_2, thesis, confidence, agent_agreement, conflict_resolution
    """
    cfg = coordinator.configs.get(
        AgentRole.CONSENSUS_BUILDER,
        AgentConfig(role=AgentRole.CONSENSUS_BUILDER),
    )
    if not cfg.enabled:
        return None

    consensus_builder_input = _build_consensus_builder_input(
        position_sizer_output=position_sizer_output,
        entry_optimizer_output=entry_optimizer_output,
        risk_guard_output=risk_guard_output,
        exit_advisor_output=exit_advisor_output,
        original_signal=original_signal,
        route=route,
    )

    out = coordinator._call_agent(AgentRole.CONSENSUS_BUILDER, consensus_builder_input, model_for_trigger)

    if not out.ok:
        logger.warning("[CONSENSUS_BUILDER] Agent call failed")
        return None

    # Write to scratchpad
    scratchpad = get_pipeline_scratchpad()
    scratchpad["consensus_builder_output"] = out.data

    return out.data


# ── Input Builder Helpers ────────────────────────────────────────────────────

def _build_position_sizer_input(
    capital: float,
    edge_confidence: float,
    kelly_fraction: Optional[float],
    regime: str,
    risk_per_trade: float,
    leverage: float,
    atr: float,
    stop_distance: float,
    consecutive_losses: int,
) -> str:
    """Build input context for Position Sizer agent."""
    context = f"""POSITION SIZER INPUT:
Capital: ${capital:,.2f}
Edge Confidence: {edge_confidence:.2f}
Kelly Fraction: {kelly_fraction if kelly_fraction else "not calculated"}
Regime: {regime}
Risk Per Trade: {risk_per_trade}%
Authorized Leverage: {leverage}x
ATR: ${atr:,.2f}
Stop Distance: ${stop_distance:,.2f}
Consecutive Losses: {consecutive_losses}

Calculate exact position size in USD based on edge confidence, Kelly fraction if available, regime, and capital constraints."""
    return context


def _build_entry_optimizer_input(
    signal_confidence: float,
    current_price: float,
    entry_price_from_signal: float,
    regime: str,
    recent_momentum: str,
    order_book: Optional[Dict],
    position_size_usd: float,
) -> str:
    """Build input context for Entry Optimizer agent."""
    ob_str = ""
    if order_book:
        ob_str = f"\nOrder Book: Bid ${order_book.get('bid', 0):.2f} ({order_book.get('bid_size', 0)} units), Ask ${order_book.get('ask', 0):.2f} ({order_book.get('ask_size', 0)} units)"

    context = f"""ENTRY OPTIMIZER INPUT:
Signal Confidence: {signal_confidence:.2f}
Current Price: ${current_price:,.2f}
Entry Price from Signal: ${entry_price_from_signal:,.2f}
Regime: {regime}
Recent Momentum: {recent_momentum}
Position Size: ${position_size_usd:,.2f}{ob_str}

Determine best entry method (market_now, limit_1tick, scaled_entry, wait_for_pullback, wait_for_breakout) and execution urgency."""
    return context


def _build_exit_advisor_input(
    position_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    current_price: float,
    pnl_usd: float,
    thesis: str,
    regime: str,
    original_regime: str,
    time_held_seconds: int,
    funding_paid: float,
    volume_trend: str,
) -> str:
    """Build input context for Exit Advisor agent."""
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    if side == "short":
        pnl_pct = -pnl_pct

    time_held_str = f"{time_held_seconds // 3600}h {(time_held_seconds % 3600) // 60}m"

    context = f"""EXIT ADVISOR INPUT:
Position: {position_id} ({symbol} {side.upper()})
Entry Price: ${entry_price:,.2f}
Current Price: ${current_price:,.2f}
PnL: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%)
Time Held: {time_held_str}
Funding Paid: ${funding_paid:,.2f}
Original Thesis: {thesis}
Original Regime: {original_regime}
Current Regime: {regime}
Volume Trend: {volume_trend}

Recommend exit action (hold, scale_out, exit_now, adjust_stop) based on thesis validity and current market conditions."""
    return context


def _build_risk_guard_input(
    proposed_trade: Dict[str, Any],
    portfolio_leverage: float,
    circuit_breaker_active: bool,
    daily_loss_pct: float,
    consecutive_losses: int,
    open_positions: list,
    max_single_position_pct: float,
    max_portfolio_leverage: float,
    correlation_to_open: float,
) -> str:
    """Build input context for Risk Guard agent."""
    context = f"""RISK GUARD INPUT:
Proposed Trade: {proposed_trade.get('symbol', 'UNKNOWN')} {proposed_trade.get('side', 'UNKNOWN')} @ {proposed_trade.get('confidence', 0):.2f} conf
Position Size: ${proposed_trade.get('position_size_usd', 0):,.2f}
Leverage: {proposed_trade.get('leverage', 1.0):.1f}x

Portfolio State:
- Current Leverage: {portfolio_leverage:.1f}x
- Daily Loss: {daily_loss_pct:.2f}%
- Consecutive Losses: {consecutive_losses}
- Open Positions: {len(open_positions)}
- Circuit Breaker: {"ACTIVE" if circuit_breaker_active else "inactive"}

Risk Constraints:
- Max Single Position: {max_single_position_pct}% of capital
- Max Portfolio Leverage: {max_portfolio_leverage:.1f}x
- Correlation to Open Positions: {correlation_to_open:.2f}

Apply safety gates to APPROVE, REDUCE size, or REJECT this trade."""
    return context


def _build_agent_router_input(
    signal: Dict[str, Any],
    market_state: Dict[str, Any],
    portfolio_state: Dict[str, Any],
    system_state: Dict[str, Any],
) -> str:
    """Build input context for Agent Router."""
    context = f"""AGENT ROUTER INPUT:
Signal: {signal.get('symbol', 'UNKNOWN')} {signal.get('side', 'UNKNOWN')} (confidence {signal.get('confidence', 0):.2f})
Regime: {signal.get('regime', 'unknown')}

Market State:
- Volatility: {market_state.get('volatility', 'unknown')}
- Volume: {market_state.get('volume_trend', 'unknown')}
- Funding: {market_state.get('funding_rate', 0):.4f}%

Portfolio State:
- Leverage: {portfolio_state.get('leverage', 1.0):.1f}x
- Daily PnL: {portfolio_state.get('daily_pnl', 0):+.2f}%
- Losses: {portfolio_state.get('consecutive_losses', 0)} consecutive

System State:
- Cache Fresh: {system_state.get('cache_fresh', True)}
- Model Latency: {system_state.get('model_latency_ms', 0)}ms
- Cost Budget: ${system_state.get('cost_budget_remaining', 10):.2f}

Route this signal through appropriate agent pipeline (normal_pipeline, fast_scalp, conviction_only, or skip_trade)."""
    return context


def _build_consensus_builder_input(
    position_sizer_output: Dict[str, Any],
    entry_optimizer_output: Dict[str, Any],
    risk_guard_output: Dict[str, Any],
    exit_advisor_output: Dict[str, Any],
    original_signal: Dict[str, Any],
    route: str,
) -> str:
    """Build input context for Consensus Builder agent."""
    context = f"""CONSENSUS BUILDER INPUT:
Original Signal: {original_signal.get('symbol', 'UNKNOWN')} {original_signal.get('side', 'UNKNOWN')}
Signal Confidence: {original_signal.get('confidence', 0):.2f}
Route: {route}

Position Sizer Output:
- Size: ${position_sizer_output.get('position_size_usd', 0):,.2f}
- Leverage: {position_sizer_output.get('leverage_applied', 1.0):.1f}x
- Status: {"✓" if position_sizer_output.get('position_size_usd', 0) > 0 else "✗"}

Entry Optimizer Output:
- Method: {entry_optimizer_output.get('entry_method', 'unknown')}
- Price: ${entry_optimizer_output.get('entry_price', 0):,.2f}
- Urgency: {entry_optimizer_output.get('urgency', 'unknown')}

Risk Guard Output:
- Approved: {risk_guard_output.get('approved', False)}
- Max Size Allowed: ${risk_guard_output.get('max_size_allowed', 0):,.2f}
- Flags: {risk_guard_output.get('risk_flags', [])}

Merge all outputs into final execute/skip decision with specific trade parameters."""
    return context
