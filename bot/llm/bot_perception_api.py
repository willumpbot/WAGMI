"""
TIER 5.1: Bot Perception API Client

Complete API integration to query everything the bot reads and understands.
Queries all endpoints on localhost:3000 to build comprehensive bot perception.

Why: The API exposes:
- Summary state (complete bot snapshot)
- Strategy performance & logs
- LLM decisions and market views
- Agent reasoning, beliefs, calibration
- Debate history (agent disagreements)
- Pipeline telemetry (system health)

This is everything the bot PERCEIVES + THINKS + DECIDES
Combined with mechanical instrumentation = complete system understanding
"""

import asyncio
import httpx
import logging
import json
from typing import Dict, List, Optional, Any, AsyncIterator
from dataclasses import dataclass, field, asdict
from datetime import datetime
import time
from functools import wraps

logger = logging.getLogger("bot.llm.bot_perception_api")


def retry_on_network_error(max_retries: int = 3, backoff_base: float = 2.0):
    """Decorator for retrying on network errors with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (httpx.RequestError, httpx.TimeoutException) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_base ** attempt
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            raise last_error
        return async_wrapper
    return decorator


@dataclass
class BotSummarySnapshot:
    """Complete bot state snapshot."""
    timestamp: float
    version: str

    # System state
    is_running: bool
    mode: str  # paper/live
    environment: str

    # Portfolio metrics
    equity: float
    balance: float
    available_balance: float
    unrealized_pnl: float
    total_pnl: float
    win_rate: float

    # Risk metrics
    portfolio_heat: float  # Leverage/exposure
    max_drawdown_pct: float
    daily_loss_pct: float

    # Strategy state
    active_strategies: List[str] = field(default_factory=list)
    num_open_positions: int = 0
    num_closed_today: int = 0

    # Health
    last_trade_timestamp: Optional[float] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class StrategySnapshot:
    """Complete strategy state snapshot."""
    strategy_id: str
    name: str
    timestamp: float

    # Performance
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float

    # Current state
    is_active: bool
    num_open_positions: int

    # Recent activity
    last_trade_time: Optional[float] = None
    last_trade_pnl: Optional[float] = None

    # Logs (recent)
    recent_logs: List[Dict] = field(default_factory=list)

    # KPIs
    kpis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMDecisionSnapshot:
    """LLM's latest decision."""
    timestamp: float
    decision_type: str  # trade/hold/exit

    # Decision context
    regime: str
    confidence: float
    reasoning: str

    # Resulting action
    action: str  # go/skip/flip
    symbol: Optional[str] = None
    side: Optional[str] = None

    # Market view
    market_outlook: Optional[str] = None
    risk_assessment: Optional[str] = None


@dataclass
class AgentBrainSnapshot:
    """Agent's reasoning and state."""
    agent_role: str  # regime/trade/risk/critic/learning/exit
    timestamp: float

    # Current state
    is_active: bool
    last_decision_time: Optional[float] = None

    # Reasoning
    current_reasoning: str = ""
    thought_process: Dict[str, Any] = field(default_factory=dict)

    # Output
    latest_output: Optional[str] = None
    confidence: float = 0.0

    # Performance
    accuracy: float = 0.0
    num_decisions: int = 0
    num_correct: int = 0


@dataclass
class AgentDebate:
    """Record of agent debate."""
    timestamp: float
    round_num: int

    # Positions
    positions: Dict[str, str] = field(default_factory=dict)  # agent -> position

    # Objections
    objections: List[Dict[str, Any]] = field(default_factory=list)

    # Resolution
    final_decision: Optional[str] = None
    consensus_reached: bool = False

    # Confidence
    team_confidence: float = 0.0


@dataclass
class PipelineTelemetry:
    """Pipeline health and metrics."""
    timestamp: float

    # Performance
    total_time_ms: float
    agent_times: Dict[str, float] = field(default_factory=dict)  # agent -> time_ms

    # Health
    all_agents_healthy: bool = True
    failed_agents: List[str] = field(default_factory=list)
    slow_agents: List[str] = field(default_factory=list)

    # Throughput
    decisions_per_minute: float = 0.0
    avg_decision_latency_ms: float = 0.0

    # Errors
    errors: List[Dict[str, Any]] = field(default_factory=list)


class BotPerceptionAPIClient:
    """
    Client to query all bot API endpoints and build comprehensive perception.
    """

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

        # Cache for last snapshots
        self.last_summary: Optional[BotSummarySnapshot] = None
        self.last_strategies: Dict[str, StrategySnapshot] = {}
        self.last_llm_decision: Optional[LLMDecisionSnapshot] = None
        self.agent_brains: Dict[str, AgentBrainSnapshot] = {}
        self.last_debate: Optional[AgentDebate] = None
        self.last_telemetry: Optional[PipelineTelemetry] = None

    @retry_on_network_error(max_retries=3)
    async def fetch_summary(self) -> Optional[BotSummarySnapshot]:
        """Fetch complete bot summary."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/summary")
            response.raise_for_status()
            data = response.json()

            snapshot = BotSummarySnapshot(
                timestamp=time.time(),
                version=data.get("version", "unknown"),
                is_running=data.get("is_running", False),
                mode=data.get("mode", "paper"),
                environment=data.get("environment", "unknown"),
                equity=data.get("equity", 0.0),
                balance=data.get("balance", 0.0),
                available_balance=data.get("available_balance", 0.0),
                unrealized_pnl=data.get("unrealized_pnl", 0.0),
                total_pnl=data.get("total_pnl", 0.0),
                win_rate=data.get("win_rate", 0.0),
                portfolio_heat=data.get("portfolio_heat", 0.0),
                max_drawdown_pct=data.get("max_drawdown_pct", 0.0),
                daily_loss_pct=data.get("daily_loss_pct", 0.0),
                active_strategies=data.get("active_strategies", []),
                num_open_positions=data.get("num_open_positions", 0),
                num_closed_today=data.get("num_closed_today", 0),
                last_trade_timestamp=data.get("last_trade_timestamp"),
                errors=data.get("errors", []),
                warnings=data.get("warnings", []),
            )

            self.last_summary = snapshot
            logger.debug(f"Fetched summary: {snapshot.equity:.2f} equity, {snapshot.num_open_positions} positions")
            return snapshot

        except Exception as e:
            logger.error(f"Error fetching summary: {e}")
            return None

    async def fetch_all_strategies(self) -> Dict[str, StrategySnapshot]:
        """Fetch all strategies and their state."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/strategies")
            response.raise_for_status()
            data = response.json()

            strategies = {}
            for strat_data in data.get("strategies", []):
                strat = StrategySnapshot(
                    strategy_id=strat_data.get("id", "unknown"),
                    name=strat_data.get("name", ""),
                    timestamp=time.time(),
                    total_trades=strat_data.get("total_trades", 0),
                    winning_trades=strat_data.get("winning_trades", 0),
                    losing_trades=strat_data.get("losing_trades", 0),
                    win_rate=strat_data.get("win_rate", 0.0),
                    total_pnl=strat_data.get("total_pnl", 0.0),
                    avg_win=strat_data.get("avg_win", 0.0),
                    avg_loss=strat_data.get("avg_loss", 0.0),
                    profit_factor=strat_data.get("profit_factor", 0.0),
                    is_active=strat_data.get("is_active", False),
                    num_open_positions=strat_data.get("num_open_positions", 0),
                    last_trade_time=strat_data.get("last_trade_time"),
                    last_trade_pnl=strat_data.get("last_trade_pnl"),
                    recent_logs=strat_data.get("recent_logs", []),
                    kpis=strat_data.get("kpis", {}),
                )
                strategies[strat.strategy_id] = strat

            self.last_strategies = strategies
            logger.debug(f"Fetched {len(strategies)} strategies")
            return strategies

        except Exception as e:
            logger.error(f"Error fetching strategies: {e}")
            return {}

    async def fetch_llm_latest_decision(self) -> Optional[LLMDecisionSnapshot]:
        """Fetch latest LLM decision."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/llm/latest")
            response.raise_for_status()
            data = response.json()

            snapshot = LLMDecisionSnapshot(
                timestamp=time.time(),
                decision_type=data.get("decision_type", "unknown"),
                regime=data.get("regime", "unknown"),
                confidence=data.get("confidence", 0.0),
                reasoning=data.get("reasoning", ""),
                action=data.get("action", ""),
                symbol=data.get("symbol"),
                side=data.get("side"),
                market_outlook=data.get("market_outlook"),
                risk_assessment=data.get("risk_assessment"),
            )

            self.last_llm_decision = snapshot
            logger.debug(f"Fetched LLM decision: {snapshot.action} {snapshot.symbol}")
            return snapshot

        except Exception as e:
            logger.error(f"Error fetching LLM decision: {e}")
            return None

    async def fetch_llm_market_view(self) -> Optional[Dict[str, Any]]:
        """Fetch LLM's market view."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/llm/market-view")
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Fetched LLM market view")
            return data
        except Exception as e:
            logger.error(f"Error fetching market view: {e}")
            return None

    async def fetch_agent_brain(self, agent_role: str) -> Optional[AgentBrainSnapshot]:
        """Fetch agent's brain (reasoning)."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/agents/{agent_role}/brain")
            response.raise_for_status()
            data = response.json()

            snapshot = AgentBrainSnapshot(
                agent_role=agent_role,
                timestamp=time.time(),
                is_active=data.get("is_active", False),
                last_decision_time=data.get("last_decision_time"),
                current_reasoning=data.get("current_reasoning", ""),
                thought_process=data.get("thought_process", {}),
                latest_output=data.get("latest_output"),
                confidence=data.get("confidence", 0.0),
                accuracy=data.get("accuracy", 0.0),
                num_decisions=data.get("num_decisions", 0),
                num_correct=data.get("num_correct", 0),
            )

            self.agent_brains[agent_role] = snapshot
            logger.debug(f"Fetched brain for {agent_role}: {snapshot.confidence:.0f}% confidence")
            return snapshot

        except Exception as e:
            logger.error(f"Error fetching agent brain {agent_role}: {e}")
            return None

    async def fetch_all_agent_brains(self) -> Dict[str, AgentBrainSnapshot]:
        """Fetch brains for all agents."""
        agent_roles = ["regime", "trade", "risk", "critic", "learning", "exit", "scout"]

        brains = {}
        for role in agent_roles:
            brain = await self.fetch_agent_brain(role)
            if brain:
                brains[role] = brain

        logger.debug(f"Fetched brains for {len(brains)} agents")
        return brains

    async def fetch_agent_calibration(self, agent_role: str) -> Optional[Dict[str, Any]]:
        """Fetch agent's calibration metrics."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/agents/{agent_role}/calibration")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching calibration for {agent_role}: {e}")
            return None

    async def fetch_latest_debate(self) -> Optional[AgentDebate]:
        """Fetch latest agent debate."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/agents/debate/latest")
            response.raise_for_status()
            data = response.json()

            snapshot = AgentDebate(
                timestamp=time.time(),
                round_num=data.get("round_num", 0),
                positions=data.get("positions", {}),
                objections=data.get("objections", []),
                final_decision=data.get("final_decision"),
                consensus_reached=data.get("consensus_reached", False),
                team_confidence=data.get("team_confidence", 0.0),
            )

            self.last_debate = snapshot
            logger.debug(f"Fetched debate: consensus={snapshot.consensus_reached}, confidence={snapshot.team_confidence:.0f}%")
            return snapshot

        except Exception as e:
            logger.error(f"Error fetching debate: {e}")
            return None

    async def fetch_debate_history(self, limit: int = 100) -> List[AgentDebate]:
        """Fetch debate history."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/agents/debate/history", params={"limit": limit})
            response.raise_for_status()
            data = response.json()

            debates = []
            for debate_data in data.get("debates", []):
                debate = AgentDebate(
                    timestamp=debate_data.get("timestamp", time.time()),
                    round_num=debate_data.get("round_num", 0),
                    positions=debate_data.get("positions", {}),
                    objections=debate_data.get("objections", []),
                    final_decision=debate_data.get("final_decision"),
                    consensus_reached=debate_data.get("consensus_reached", False),
                    team_confidence=debate_data.get("team_confidence", 0.0),
                )
                debates.append(debate)

            logger.debug(f"Fetched {len(debates)} debates")
            return debates

        except Exception as e:
            logger.error(f"Error fetching debate history: {e}")
            return []

    async def fetch_pipeline_telemetry(self) -> Optional[PipelineTelemetry]:
        """Fetch pipeline health and metrics."""
        try:
            response = await self.client.get(f"{self.base_url}/v1/agents/pipeline/telemetry")
            response.raise_for_status()
            data = response.json()

            snapshot = PipelineTelemetry(
                timestamp=time.time(),
                total_time_ms=data.get("total_time_ms", 0.0),
                agent_times=data.get("agent_times", {}),
                all_agents_healthy=data.get("all_agents_healthy", True),
                failed_agents=data.get("failed_agents", []),
                slow_agents=data.get("slow_agents", []),
                decisions_per_minute=data.get("decisions_per_minute", 0.0),
                avg_decision_latency_ms=data.get("avg_decision_latency_ms", 0.0),
                errors=data.get("errors", []),
            )

            self.last_telemetry = snapshot
            logger.debug(f"Fetched telemetry: {snapshot.total_time_ms:.0f}ms, {len(snapshot.failed_agents)} failures")
            return snapshot

        except Exception as e:
            logger.error(f"Error fetching telemetry: {e}")
            return None

    @retry_on_network_error(max_retries=3)
    async def fetch_complete_perception(self) -> Dict[str, Any]:
        """
        Fetch EVERYTHING in parallel.
        Complete bot perception in one call.
        """
        logger.info("Fetching complete bot perception...")

        # Parallel requests
        summary, strategies, llm_decision, agent_brains, debate, telemetry, market_view = await asyncio.gather(
            self.fetch_summary(),
            self.fetch_all_strategies(),
            self.fetch_llm_latest_decision(),
            self.fetch_all_agent_brains(),
            self.fetch_latest_debate(),
            self.fetch_pipeline_telemetry(),
            self.fetch_llm_market_view(),
            return_exceptions=True,
        )

        perception = {
            "timestamp": time.time(),
            "summary": summary,
            "strategies": strategies,
            "llm": {
                "latest_decision": llm_decision,
                "market_view": market_view,
            },
            "agents": agent_brains,
            "debate": debate,
            "pipeline": telemetry,
        }

        logger.info(f"Complete perception fetched: {len(agent_brains)} agents, {len(strategies)} strategies")
        return perception

    async def stream_perception(self, interval_seconds: float = 5.0) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream perception updates continuously.
        """
        while True:
            try:
                perception = await self.fetch_complete_perception()
                yield perception
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Error in perception stream: {e}")
                await asyncio.sleep(interval_seconds)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    def get_cached_perception(self) -> Dict[str, Any]:
        """Get last cached perception without making new request."""
        return {
            "summary": self.last_summary,
            "strategies": self.last_strategies,
            "llm_decision": self.last_llm_decision,
            "agent_brains": self.agent_brains,
            "debate": self.last_debate,
            "telemetry": self.last_telemetry,
        }


# Global API client
_global_api_client: Optional[BotPerceptionAPIClient] = None


def get_bot_perception_api_client() -> BotPerceptionAPIClient:
    """Get or create global API client."""
    global _global_api_client
    if _global_api_client is None:
        _global_api_client = BotPerceptionAPIClient()
    return _global_api_client
