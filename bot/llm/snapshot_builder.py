"""
Snapshot builder: converts bot state into the compact JSON the LLM receives.

Design principles:
  - Only send markets with active signals (reduces tokens ~60%)
  - Cap at top N markets by signal strength
  - Compress numbers to minimal precision
  - Include active positions for context
  - Throttle: skip LLM call if market hasn't changed meaningfully

The LLM sees ONLY what this module produces. Nothing else.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any

from llm.decision_types import (
    StrategySignal,
    MarketSnapshot,
    GlobalContext,
    LLMInputSnapshot,
)

logger = logging.getLogger("bot.llm.snapshot")

# ── Throttling state ─────────────────────────────────────────────

_last_call_ts: float = 0.0
_last_snapshot_hash: str = ""
_MIN_CALL_INTERVAL_S = 300  # 5 minutes between LLM calls
_FORCE_CALL_INTERVAL_S = 900  # Force a call every 15 minutes regardless


def should_call_llm(snapshot: LLMInputSnapshot) -> bool:
    """Determine if we should call the LLM based on throttling rules.

    Returns True when:
      - At least 5 minutes since last call AND something changed
      - OR at least 15 minutes since last call (forced periodic update)
      - OR circuit breaker just activated/deactivated
    """
    global _last_call_ts, _last_snapshot_hash

    now = time.time()
    elapsed = now - _last_call_ts

    # Force call every 15 minutes
    if elapsed >= _FORCE_CALL_INTERVAL_S:
        return True

    # Minimum interval
    if elapsed < _MIN_CALL_INTERVAL_S:
        return False

    # Check if market state changed meaningfully
    current_hash = _compute_snapshot_hash(snapshot)
    if current_hash != _last_snapshot_hash:
        return True

    return False


def mark_called(snapshot: LLMInputSnapshot):
    """Mark that we just called the LLM."""
    global _last_call_ts, _last_snapshot_hash
    _last_call_ts = time.time()
    _last_snapshot_hash = _compute_snapshot_hash(snapshot)


def _compute_snapshot_hash(snapshot: LLMInputSnapshot) -> str:
    """Quick hash of the market state to detect meaningful changes.

    We don't need cryptographic hashing -- just detect if the top signal
    directions or regime indicators shifted.
    """
    parts = []
    for m in snapshot.markets:
        for s in m.signals:
            # Round confidence to nearest 0.1 so tiny jitter doesn't trigger
            parts.append(f"{s.symbol}:{s.side}:{round(s.confidence, 1)}")
    parts.append(f"cb:{snapshot.global_context.circuit_breaker_active}")
    parts.append(f"pos:{snapshot.global_context.total_open_positions}")
    return "|".join(sorted(parts))


# ── Snapshot building ────────────────────────────────────────────

MAX_MARKETS_IN_SNAPSHOT = 10  # Cap to control token cost


def build_snapshot(
    markets: List[MarketSnapshot],
    global_context: GlobalContext,
    memory_summary: Optional[str] = None,
    active_positions: Optional[List[Dict[str, Any]]] = None,
    trigger_reason: str = "",
    trigger_context: str = "",
) -> LLMInputSnapshot:
    """Build a token-efficient snapshot for the LLM.

    Filtering:
      1. Only include markets where at least one strategy has confidence > 0.4
      2. Sort by max signal confidence (strongest signals first)
      3. Cap at MAX_MARKETS_IN_SNAPSHOT
      4. Always include markets with active positions (the LLM needs context)
    """
    # Separate markets with positions (always include)
    position_symbols = set()
    if active_positions:
        position_symbols = {p.get("symbol", "") for p in active_positions}

    # Filter to markets with meaningful signals
    active_markets = []
    position_markets = []

    for m in markets:
        has_signal = any(s.confidence > 0.4 for s in m.signals)
        in_position = m.symbol in position_symbols

        if in_position:
            position_markets.append(m)
        elif has_signal:
            active_markets.append(m)

    # Sort by strongest signal
    active_markets.sort(
        key=lambda m: max((s.confidence for s in m.signals), default=0),
        reverse=True,
    )

    # Cap: position markets always included, fill remainder with top signals
    remaining_slots = MAX_MARKETS_IN_SNAPSHOT - len(position_markets)
    selected = position_markets + active_markets[:max(remaining_slots, 0)]

    # Truncate memory
    trimmed_memory = None
    if memory_summary:
        trimmed_memory = memory_summary[:500]  # Hard cap

    return LLMInputSnapshot(
        markets=selected,
        global_context=global_context,
        memory_summary=trimmed_memory,
        active_positions=active_positions or [],
        trigger_reason=trigger_reason,
        trigger_context=trigger_context,
    )


def snapshot_to_json(snapshot: LLMInputSnapshot) -> str:
    """Serialize snapshot to compact JSON for the LLM."""
    return json.dumps(snapshot.to_dict(), separators=(",", ":"))
