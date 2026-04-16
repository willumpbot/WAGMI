"""
LLM Cost Tracker: Budget-aware model selection.

Tracks daily LLM API spend and auto-downgrades model selection when
approaching the daily budget. Prevents runaway API costs while ensuring
critical decisions still get the best model.

Features:
  - Track per-call costs (input/output tokens × model pricing)
  - Daily budget with soft (70%) and hard (90%) limits
  - Auto-downgrade: Opus→Sonnet→Haiku for non-critical triggers at soft limit
  - Emergency Haiku-only at hard limit
  - Persists daily state to data/llm/cost_tracker.json

Integration:
  - decision_engine.py: record_call() after API call, get_safe_model() before
  - usage_tiers.py: wraps get_model_for_trigger()
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.llm.cost_tracker")

_COST_DIR = os.path.join("data", "llm")
_COST_PATH = os.path.join(_COST_DIR, "cost_tracker.json")

# Model pricing per 1M tokens — must match usage_tiers.py
# Tuple order: (uncached_input, output, cache_write_5m, cache_read)
# Anthropic prompt caching multipliers: write=1.25x uncached, read=0.10x uncached.
_MODEL_PRICING = {
    # Actual Anthropic pricing as of 2026-04
    "claude-haiku-4-5-20251001": (0.80, 4.0, 1.00, 0.08),
    "claude-sonnet-4-5-20250929": (3.0, 15.0, 3.75, 0.30),
    "claude-opus-4-20250115": (15.0, 75.0, 18.75, 1.50),
}

# Model IDs for downgrade chain
_MODEL_HAIKU = "claude-haiku-4-5-20251001"
_MODEL_SONNET = "claude-sonnet-4-5-20250929"
_MODEL_OPUS = "claude-opus-4-20250115"

# High-value triggers that resist downgrade (match usage_tiers.py)
_HIGH_VALUE_TRIGGERS = {
    "PRE_TRADE", "pre-trade validation",
    "REGIME_SHIFT", "regime shift",
    "STRATEGY_DISAGREEMENT", "strategy disagreement",
    "PRE_CLOSE", "pre-close assessment",
}

# Budget thresholds
_SOFT_LIMIT_PCT = 0.70   # Start downgrading non-critical at 70%
_HARD_LIMIT_PCT = 0.90   # Emergency Haiku-only at 90%


class CostTracker:
    """Track daily LLM API costs and auto-downgrade when approaching budget."""

    def __init__(self, daily_budget: float = None):
        self.daily_budget = daily_budget or float(
            os.getenv("LLM_DAILY_BUDGET_USD", "25.0")
        )
        self._today_spend: float = 0.0
        self._today_date: str = ""
        self._calls_today: int = 0
        self._calls_by_model: Dict[str, int] = {}
        self._spend_by_model: Dict[str, float] = {}
        self._load_state()
        self._maybe_reset_daily()

    def record_call(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
        cache_read_tokens: int = 0,
        cache_create_tokens: int = 0,
    ):
        """Record an API call and its cost.

        Args:
            input_tokens: Uncached input tokens (Anthropic API semantics:
                this does NOT include cache_read or cache_create)
            output_tokens: Output tokens generated
            model: Model ID used for the call
            cache_read_tokens: Tokens served from prompt cache (0.10x price)
            cache_create_tokens: Tokens written to prompt cache (1.25x price)
        """
        self._maybe_reset_daily()

        # Pricing: (uncached_in, out, cache_write, cache_read)
        pricing = _MODEL_PRICING.get(model, (3.0, 15.0, 3.75, 0.30))
        uncached_in_cost = (input_tokens / 1_000_000) * pricing[0]
        output_cost = (output_tokens / 1_000_000) * pricing[1]
        cache_write_cost = (cache_create_tokens / 1_000_000) * pricing[2]
        cache_read_cost = (cache_read_tokens / 1_000_000) * pricing[3]
        total_cost = uncached_in_cost + output_cost + cache_write_cost + cache_read_cost

        self._today_spend += total_cost
        self._calls_today += 1
        self._calls_by_model[model] = self._calls_by_model.get(model, 0) + 1
        self._spend_by_model[model] = self._spend_by_model.get(model, 0.0) + total_cost
        # Track cache hit/write stats for visibility
        if cache_read_tokens > 0:
            self._cache_read_tokens_today = getattr(self, "_cache_read_tokens_today", 0) + cache_read_tokens
            self._cache_hits_today = getattr(self, "_cache_hits_today", 0) + 1
        if cache_create_tokens > 0:
            self._cache_create_tokens_today = getattr(self, "_cache_create_tokens_today", 0) + cache_create_tokens

        # Save every 5 calls
        if self._calls_today % 5 == 0:
            self._save_state()

        if total_cost > 0.01:
            logger.debug(
                f"[COST] {model.split('-')[1]}: ${total_cost:.4f} "
                f"(in={input_tokens}, out={output_tokens}) — "
                f"daily total: ${self._today_spend:.2f}/{self.daily_budget:.2f}"
            )

        # Log warnings at thresholds
        budget_pct = self._today_spend / self.daily_budget if self.daily_budget > 0 else 0
        if budget_pct >= _HARD_LIMIT_PCT and (self._calls_today % 10 == 0 or budget_pct >= 0.95):
            logger.warning(
                f"[COST] Budget {budget_pct:.0%} used "
                f"(${self._today_spend:.2f}/${self.daily_budget:.2f}) — "
                f"EMERGENCY: Haiku-only mode"
            )
        elif budget_pct >= _SOFT_LIMIT_PCT and self._calls_today % 10 == 0:
            logger.info(
                f"[COST] Budget {budget_pct:.0%} used — downgrading non-critical calls"
            )

    def get_safe_model(self, preferred_model: str, trigger: str = "") -> str:
        """Return preferred model or downgrade if over budget.

        Args:
            preferred_model: The model the tier system wants to use
            trigger: Trigger reason (high-value triggers resist downgrade)

        Returns:
            Model ID to actually use (may be downgraded)
        """
        self._maybe_reset_daily()

        if self.daily_budget <= 0:
            return preferred_model  # No budget set = unlimited

        budget_pct = self._today_spend / self.daily_budget

        # TRUE HARD STOP: no more API calls once budget exceeded
        if budget_pct >= 1.0:
            logger.warning(
                f"[COST] BUDGET EXCEEDED (${self._today_spend:.2f}/${self.daily_budget:.2f}). "
                f"ALL LLM calls blocked until tomorrow."
            )
            return "__BUDGET_EXCEEDED__"  # Caller must check and skip

        # Hard limit: everything goes to Haiku
        if budget_pct >= _HARD_LIMIT_PCT:
            if preferred_model != _MODEL_HAIKU:
                logger.info(
                    f"[COST] Hard limit ({budget_pct:.0%}): "
                    f"{preferred_model.split('-')[1]} → Haiku"
                )
            return _MODEL_HAIKU

        # Soft limit: downgrade non-critical triggers
        if budget_pct >= _SOFT_LIMIT_PCT:
            if trigger in _HIGH_VALUE_TRIGGERS:
                return preferred_model  # Critical triggers keep their model

            downgraded = _downgrade_model(preferred_model)
            if downgraded != preferred_model:
                logger.debug(
                    f"[COST] Soft limit ({budget_pct:.0%}): "
                    f"{preferred_model.split('-')[1]} → {downgraded.split('-')[1]} "
                    f"for trigger={trigger}"
                )
            return downgraded

        return preferred_model

    def get_stats(self) -> Dict[str, Any]:
        """Get current cost tracking stats, including cache hit rate."""
        self._maybe_reset_daily()
        cache_hits = getattr(self, "_cache_hits_today", 0)
        cache_hit_rate = (cache_hits / self._calls_today) if self._calls_today > 0 else 0.0
        return {
            "today_spend": round(self._today_spend, 4),
            "budget": self.daily_budget,
            "budget_used_pct": round(
                self._today_spend / self.daily_budget if self.daily_budget > 0 else 0, 3
            ),
            "calls_today": self._calls_today,
            "calls_by_model": dict(self._calls_by_model),
            "spend_by_model": {
                k: round(v, 4) for k, v in self._spend_by_model.items()
            },
            "cache_hit_rate": round(cache_hit_rate, 3),
            "cache_read_tokens": getattr(self, "_cache_read_tokens_today", 0),
            "cache_create_tokens": getattr(self, "_cache_create_tokens_today", 0),
            "date": self._today_date,
        }

    def get_budget_used_pct(self) -> float:
        """Quick accessor for budget percentage used."""
        self._maybe_reset_daily()
        if self.daily_budget <= 0:
            return 0.0
        return self._today_spend / self.daily_budget

    def _maybe_reset_daily(self):
        """Reset counters at the start of a new day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._today_date != today:
            if self._today_date and self._today_spend > 0:
                logger.info(
                    f"[COST] Day {self._today_date} final: "
                    f"${self._today_spend:.2f} across {self._calls_today} calls"
                )
            self._today_spend = 0.0
            self._calls_today = 0
            self._calls_by_model = {}
            self._spend_by_model = {}
            self._today_date = today

    def _save_state(self):
        """Persist state to disk, including prompt-cache metrics."""
        os.makedirs(_COST_DIR, exist_ok=True)
        try:
            state = {
                "date": self._today_date,
                "spend": self._today_spend,
                "calls": self._calls_today,
                "calls_by_model": self._calls_by_model,
                "spend_by_model": self._spend_by_model,
                "budget": self.daily_budget,
                # Prompt caching metrics — persisted so cache hit rate can
                # be tracked across restarts.
                "cache_read_tokens": getattr(self, "_cache_read_tokens_today", 0),
                "cache_create_tokens": getattr(self, "_cache_create_tokens_today", 0),
                "cache_hits": getattr(self, "_cache_hits_today", 0),
            }
            with open(_COST_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"[COST] Failed to save state: {e}")

    def _load_state(self):
        """Load state from disk, including prompt-cache metrics."""
        if not os.path.exists(_COST_PATH):
            return
        try:
            with open(_COST_PATH, "r") as f:
                state = json.load(f)

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if state.get("date") == today:
                self._today_date = state["date"]
                self._today_spend = state.get("spend", 0.0)
                self._calls_today = state.get("calls", 0)
                self._calls_by_model = state.get("calls_by_model", {})
                self._spend_by_model = state.get("spend_by_model", {})
                # Cache metrics (backward-compatible: older state files lack these)
                self._cache_read_tokens_today = state.get("cache_read_tokens", 0)
                self._cache_create_tokens_today = state.get("cache_create_tokens", 0)
                self._cache_hits_today = state.get("cache_hits", 0)
                _cache_tag = ""
                if self._cache_hits_today > 0:
                    _cache_tag = f", cache_hits={self._cache_hits_today}"
                logger.info(
                    f"[COST] Resumed: ${self._today_spend:.2f} "
                    f"across {self._calls_today} calls today{_cache_tag}"
                )
        except Exception as e:
            logger.warning(f"[COST] Failed to load state: {e}")


def _downgrade_model(model: str) -> str:
    """Downgrade a model one tier: Opus→Sonnet, Sonnet→Haiku, Haiku→Haiku."""
    if model == _MODEL_OPUS:
        return _MODEL_SONNET
    if model == _MODEL_SONNET:
        return _MODEL_HAIKU
    return model  # Already Haiku


# Module-level singleton
_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get or create the singleton CostTracker."""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
