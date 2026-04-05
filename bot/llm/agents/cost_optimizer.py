"""
Agent Cost Optimizer: Ensures the LLM network generates more profit than it costs.

Key principles:
1. Not every signal deserves a full 5-agent pipeline call
2. Obvious decisions (very high or very low confidence) can use Haiku-only fast path
3. Only borderline decisions need the full Sonnet Trade+Critic pipeline
4. Track ROI per agent -- disable agents that cost more than they add
5. Never exceed daily budget
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("bot.llm.agents.cost_optimizer")

# Model IDs (import-safe duplicates from usage_tiers)
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-5-20250929"

# Cost per call estimates by model (avg input+output tokens)
MODEL_COST_PER_CALL = {
    MODEL_HAIKU: 0.0002,   # ~400 in + 300 out tokens
    MODEL_SONNET: 0.003,   # ~600 in + 400 out tokens
}

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm" / "agent_costs.json"

# Pipeline definitions: agents + their default models + estimated cost
PIPELINE_CONFIGS = {
    "fast_path": {
        "agents": ["regime", "trade"],
        "models": {"regime": MODEL_HAIKU, "trade": MODEL_HAIKU},
        "enable_debate": False,
        "estimated_cost": 0.0004,
        "timeout_s": 5,
    },
    "standard": {
        "agents": ["regime", "quant", "trade", "risk"],
        "models": {
            "regime": MODEL_HAIKU, "quant": MODEL_HAIKU,
            "trade": MODEL_SONNET, "risk": MODEL_HAIKU,
        },
        "enable_debate": False,
        "estimated_cost": 0.004,
        "timeout_s": 12,
    },
    "full_pipeline": {
        "agents": ["regime", "quant", "trade", "risk", "critic"],
        "models": {
            "regime": MODEL_HAIKU, "quant": MODEL_HAIKU,
            "trade": MODEL_SONNET, "risk": MODEL_HAIKU,
            "critic": MODEL_SONNET,
        },
        "enable_debate": False,
        "estimated_cost": 0.007,
        "timeout_s": 18,
    },
    "deep_analysis": {
        "agents": ["regime", "quant", "trade", "risk", "critic"],
        "models": {
            "regime": MODEL_HAIKU, "quant": MODEL_SONNET,
            "trade": MODEL_SONNET, "risk": MODEL_SONNET,
            "critic": MODEL_SONNET,
        },
        "enable_debate": True,
        "estimated_cost": 0.019,
        "timeout_s": 30,
    },
}


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class AgentCostOptimizer:
    """Optimizes when and how to call LLM agents for maximum ROI."""

    def __init__(self, daily_budget_usd: float = 0.50,
                 min_roi_threshold: float = 2.0):
        self.daily_budget = daily_budget_usd
        self.min_roi = min_roi_threshold
        self.state = self._load_state()
        self._ensure_today()

    # ── Persistence ─────────────────────────────────────────────

    def _load_state(self) -> Dict:
        if DATA_PATH.exists():
            try:
                return json.loads(DATA_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt agent_costs.json -- resetting")
        return self._empty_state()

    def _empty_state(self) -> Dict:
        return {
            "current_date": _today_str(),
            "today_spend": 0.0,
            "today_calls": 0,
            "lifetime": {
                "total_spend": 0.0,
                "total_profit": 0.0,
                "total_calls": 0,
            },
            "per_pipeline": {},
            "per_agent": {},
        }

    def _ensure_today(self):
        """Reset daily counters if date rolled over."""
        today = _today_str()
        if self.state.get("current_date") != today:
            # Archive yesterday into lifetime, reset daily
            self.state["current_date"] = today
            self.state["today_spend"] = 0.0
            self.state["today_calls"] = 0
            self._save()

    def _save(self):
        try:
            DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            DATA_PATH.write_text(json.dumps(self.state, indent=2))
        except OSError as e:
            logger.error(f"Failed to save agent costs: {e}")

    # ── Core Decision: Should We Call Agents? ───────────────────

    def should_call_agents(self, signal_confidence: float,
                           num_strategies_agree: int,
                           regime: str) -> Tuple[bool, str]:
        """Decide whether this signal warrants an LLM call at all.

        Returns (should_call, reason):
        - (False, "below_threshold") --signal too weak, save the money
        - (False, "budget_exhausted") --daily limit hit
        - (True, "full_pipeline") --borderline, needs full reasoning
        - (True, "fast_path") --obvious signal, cheap confirmation only
        - (True, "deep_analysis") --panic regime, spend extra for safety
        """
        self._ensure_today()

        # Budget gate --hard stop
        remaining = self.daily_budget - self.state["today_spend"]
        if remaining < 0.0002:  # Can't even afford a Haiku call
            return (False, "budget_exhausted")

        # Garbage filter --don't spend money on junk
        if signal_confidence < 40 and num_strategies_agree < 1:
            return (False, "below_threshold")

        # Panic/dislocation regime --always call full pipeline for safety
        if regime in ("panic", "news_dislocation"):
            if remaining >= PIPELINE_CONFIGS["deep_analysis"]["estimated_cost"]:
                return (True, "deep_analysis")
            return (True, "full_pipeline")

        # Very high confidence + strong agreement -> cheap confirmation only
        if signal_confidence >= 80 and num_strategies_agree >= 3:
            return (True, "fast_path")

        # High confidence OR decent agreement -> standard pipeline
        if signal_confidence >= 65 or num_strategies_agree >= 2:
            if remaining >= PIPELINE_CONFIGS["standard"]["estimated_cost"]:
                return (True, "standard")
            return (True, "fast_path")

        # Borderline zone (40-65 confidence, 1 agree) -> full pipeline
        # This is where LLM reasoning adds the most value
        if remaining >= PIPELINE_CONFIGS["full_pipeline"]["estimated_cost"]:
            return (True, "full_pipeline")
        if remaining >= PIPELINE_CONFIGS["standard"]["estimated_cost"]:
            return (True, "standard")
        return (True, "fast_path")

    # ── Pipeline Configuration ──────────────────────────────────

    def get_pipeline_config(self, call_type: str) -> Dict:
        """Get which agents to call and which models to use."""
        config = PIPELINE_CONFIGS.get(call_type, PIPELINE_CONFIGS["standard"])
        # Deep copy so callers can mutate
        return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                for k, v in config.items()}

    # ── Cost & Outcome Recording ────────────────────────────────

    def record_cost(self, pipeline_type: str, actual_cost: float):
        """Record API spending for a pipeline call."""
        self._ensure_today()
        self.state["today_spend"] += actual_cost
        self.state["today_calls"] += 1
        self.state["lifetime"]["total_spend"] += actual_cost
        self.state["lifetime"]["total_calls"] += 1

        pp = self.state.setdefault("per_pipeline", {})
        entry = pp.setdefault(pipeline_type, {"calls": 0, "cost": 0.0, "profit": 0.0})
        entry["calls"] += 1
        entry["cost"] += actual_cost
        self._save()

    def record_agent_cost(self, agent_name: str, cost: float):
        """Record cost for an individual agent call."""
        pa = self.state.setdefault("per_agent", {})
        entry = pa.setdefault(agent_name, {"calls": 0, "cost": 0.0, "profit": 0.0})
        entry["calls"] += 1
        entry["cost"] += cost
        # Don't save per-call for agents --save happens in record_cost

    def record_outcome(self, pipeline_type: str, pnl: float):
        """Record trade outcome to track ROI per pipeline type."""
        self.state["lifetime"]["total_profit"] += pnl

        pp = self.state.setdefault("per_pipeline", {})
        if pipeline_type in pp:
            pp[pipeline_type]["profit"] += pnl
        self._save()

    # ── ROI Analytics ───────────────────────────────────────────

    def get_roi_stats(self) -> Dict:
        """Get ROI statistics per pipeline type and per agent."""
        lt = self.state.get("lifetime", {})
        total_spend = lt.get("total_spend", 0.0)
        total_profit = lt.get("total_profit", 0.0)
        overall_roi = (total_profit / total_spend) if total_spend > 0.001 else 0.0

        remaining = max(0, self.daily_budget - self.state.get("today_spend", 0))
        avg_cost = (total_spend / lt.get("total_calls", 1)) if lt.get("total_calls") else 0.004
        calls_remaining = int(remaining / avg_cost) if avg_cost > 0 else 0

        # Per-pipeline ROI
        per_pipeline = {}
        for name, data in self.state.get("per_pipeline", {}).items():
            cost = data.get("cost", 0)
            profit = data.get("profit", 0)
            roi = (profit / cost) if cost > 0.0001 else 0.0
            per_pipeline[name] = {
                "calls": data.get("calls", 0),
                "cost": round(cost, 4),
                "profit": round(profit, 2),
                "roi": round(roi, 1),
            }

        # Per-agent value assessment
        agent_roi = {}
        for name, data in self.state.get("per_agent", {}).items():
            cost = data.get("cost", 0)
            profit = data.get("profit", 0)
            if cost > 0.01 and profit < 0:
                value = "NEGATIVE --consider disabling"
            elif cost > 0 and profit / max(cost, 0.0001) > self.min_roi:
                value = "positive"
            else:
                value = "neutral --insufficient data"
            agent_roi[name] = {"cost": round(cost, 4), "value_add": value}

        return {
            "daily_spend": round(self.state.get("today_spend", 0), 4),
            "daily_budget_remaining": round(remaining, 4),
            "total_spend": round(total_spend, 4),
            "total_profit_attributed": round(total_profit, 2),
            "overall_roi": round(overall_roi, 1),
            "calls_remaining_today": calls_remaining,
            "per_pipeline": per_pipeline,
            "agent_roi": agent_roi,
        }

    def get_budget_status(self) -> str:
        """Quick budget status for logging."""
        self._ensure_today()
        spend = self.state.get("today_spend", 0)
        pct = (spend / self.daily_budget * 100) if self.daily_budget > 0 else 0
        lt = self.state.get("lifetime", {})
        total_spend = lt.get("total_spend", 0)
        roi = (lt.get("total_profit", 0) / total_spend) if total_spend > 0.001 else 0
        avg_cost = (total_spend / lt.get("total_calls", 1)) if lt.get("total_calls") else 0.004
        remaining = max(0, self.daily_budget - spend)
        calls_left = int(remaining / avg_cost) if avg_cost > 0 else 0
        return f"API: ${spend:.2f}/${self.daily_budget:.2f} today ({pct:.0f}%) | ROI: {roi:.1f}x | ~{calls_left} calls remaining"

    def format_for_overseer(self) -> str:
        """Cost report for Overseer agent."""
        stats = self.get_roi_stats()
        lines = [
            "=== COST OPTIMIZER REPORT ===",
            f"Daily: ${stats['daily_spend']:.3f} / ${self.daily_budget:.2f} "
            f"({stats['calls_remaining_today']} calls left)",
            f"Lifetime: ${stats['total_spend']:.3f} spent -> "
            f"${stats['total_profit_attributed']:.2f} attributed profit "
            f"(ROI: {stats['overall_roi']:.1f}x)",
        ]
        if stats["per_pipeline"]:
            lines.append("\nPipeline ROI:")
            for name, d in sorted(stats["per_pipeline"].items(),
                                   key=lambda x: x[1]["roi"], reverse=True):
                lines.append(f"  {name}: {d['calls']} calls, "
                             f"${d['cost']:.3f} cost, "
                             f"${d['profit']:.2f} profit, "
                             f"ROI={d['roi']:.1f}x")
        if stats["agent_roi"]:
            neg = [n for n, d in stats["agent_roi"].items()
                   if "NEGATIVE" in d["value_add"]]
            if neg:
                lines.append(f"\nWARNING: Negative-ROI agents: {', '.join(neg)}")
        return "\n".join(lines)


# ── Smart Model Routing ─────────────────────────────────────────

def get_optimal_model(agent_name: str, signal_importance: str,
                      agent_recent_accuracy: float) -> str:
    """Choose the cheapest model that maintains quality for this agent.

    Logic:
    - Regime/Quant/Risk: always Haiku (classification/math tasks)
    - Trade: Sonnet for borderline, Haiku for clear signals
    - Critic: Sonnet for high-stakes, skip-worthy for obvious approvals
    - If accuracy > 70% on current model, stay cheap
    - If accuracy < 50%, try upgrading before disabling
    """
    # Always-cheap agents (structured/numeric output, not deep reasoning)
    if agent_name in ("regime", "quant", "risk", "exit", "scout",
                      "learning", "position_sizer", "risk_guard"):
        return MODEL_HAIKU

    # Trade agent: the core reasoning engine
    if agent_name == "trade":
        if signal_importance == "high":
            return MODEL_SONNET
        # If Haiku accuracy is good enough, save money
        if agent_recent_accuracy >= 0.70:
            return MODEL_HAIKU
        # Borderline accuracy --upgrade to Sonnet
        return MODEL_SONNET

    # Critic agent: only needs Sonnet for genuine ambiguity
    if agent_name == "critic":
        if signal_importance in ("high", "borderline"):
            # Low accuracy on critic -> might need upgrade
            if agent_recent_accuracy < 0.50:
                return MODEL_SONNET
            return MODEL_SONNET
        # Clear signals: Haiku critic is fine (mostly rubber-stamping)
        if agent_recent_accuracy >= 0.70:
            return MODEL_HAIKU
        return MODEL_SONNET

    # Overseer: periodic, can be cheap
    if agent_name == "overseer":
        return MODEL_HAIKU

    # Default: Haiku (save money, upgrade only if proven necessary)
    return MODEL_HAIKU


def classify_signal_importance(confidence: float,
                               num_agree: int,
                               regime: str) -> str:
    """Classify a signal's importance for model routing decisions.

    Returns: "low", "borderline", or "high"
    """
    if regime in ("panic", "news_dislocation"):
        return "high"
    if confidence >= 80 and num_agree >= 3:
        return "low"  # Clear signal, cheap processing
    if confidence < 50 or num_agree < 1:
        return "low"  # Garbage signal, cheap rejection
    if 50 <= confidence < 70 and num_agree in (1, 2):
        return "borderline"  # This is where reasoning earns its keep
    return "high" if confidence >= 70 and num_agree >= 2 else "borderline"


# ── Module-level singleton ──────────────────────────────────────

_optimizer: Optional[AgentCostOptimizer] = None


def get_cost_optimizer(daily_budget: float = 0.50) -> AgentCostOptimizer:
    """Get or create the singleton cost optimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = AgentCostOptimizer(daily_budget_usd=daily_budget)
    return _optimizer
