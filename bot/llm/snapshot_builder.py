"""
Snapshot builder: converts bot state into the compact JSON the LLM receives.

Design principles:
  - Only send markets with active signals (reduces tokens ~60%)
  - Cap at top N markets by signal strength (5-8 markets, not 18)
  - Compress: short keys, strip nulls/zeros, aggressive rounding
  - Include active positions for context
  - Throttle: skip LLM call if market hasn't changed meaningfully

The LLM sees ONLY what this module produces. Nothing else.
"""

import json
import logging
import os
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

# Default 8 markets max (was 10). Env-overridable.
MAX_MARKETS_IN_SNAPSHOT = int(os.getenv("LLM_MAX_MARKETS", "8"))

# Minimum signal confidence to include a market (was 0.4, now 0.3 to catch more)
MIN_SIGNAL_CONFIDENCE = float(os.getenv("LLM_MIN_SIGNAL_CONF", "0.3"))


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
      1. Only include markets where at least one strategy has confidence > MIN_SIGNAL_CONFIDENCE
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
        has_signal = any(s.confidence > MIN_SIGNAL_CONFIDENCE for s in m.signals)
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


def snapshot_to_json(snapshot: LLMInputSnapshot, compact: bool = True) -> str:
    """Serialize snapshot to JSON for the LLM.

    compact=True: Uses short keys, strips nulls/zeros, aggressive rounding.
                  Saves ~30-40% tokens vs verbose mode.
    compact=False: Full verbose format (for debugging).
    """
    if compact:
        return json.dumps(_to_compact_dict(snapshot), separators=(",", ":"))
    return json.dumps(snapshot.to_dict(), separators=(",", ":"))


def _to_compact_dict(snapshot: LLMInputSnapshot) -> dict:
    """Compact snapshot serialization.

    Short keys, stripped nulls/zeros, aggressive rounding.
    Saves ~30-40% tokens compared to verbose to_dict().

    Key mapping:
      markets -> m, symbol -> s, price -> p, signals -> sg
      price_change_1h_pct -> d1h, price_change_24h_pct -> d24h
      volume_ratio -> vr, volatility -> vol
      funding_rate -> fr, oi_change_pct -> oi
      strategy -> st, side -> sd, confidence -> c, regime -> rg
      global -> g, trigger -> t, memory -> mem
      positions -> pos, equity -> eq, daily_pnl -> pnl
    """
    result = {}

    # Markets (compact)
    compact_markets = []
    for m in snapshot.markets:
        cm = {"s": m.symbol, "p": _round_price(m.price)}

        # Only include non-zero changes
        if abs(m.price_change_1h_pct) >= 0.01:
            cm["d1h"] = round(m.price_change_1h_pct, 1)
        if abs(m.price_change_24h_pct) >= 0.01:
            cm["d24h"] = round(m.price_change_24h_pct, 1)
        if abs(m.volume_ratio - 1.0) >= 0.05:
            cm["vr"] = round(m.volume_ratio, 1)
        if m.volatility >= 0.01:
            cm["vol"] = round(m.volatility, 2)
        if m.funding_rate is not None and abs(m.funding_rate) >= 0.0001:
            cm["fr"] = round(m.funding_rate, 4)
        if m.open_interest_change_pct is not None and abs(m.open_interest_change_pct) >= 0.1:
            cm["oi"] = round(m.open_interest_change_pct, 1)

        # Signals (compact, skip neutral/low-confidence)
        sigs = []
        for s in m.signals:
            if s.confidence < 0.2 and s.side == "neutral":
                continue  # Skip noise
            sig = {"st": s.strategy, "sd": s.side, "c": round(s.confidence, 2)}
            if s.regime_score and s.regime_score >= 0.1:
                sig["rg"] = round(s.regime_score, 2)
            sigs.append(sig)
        if sigs:
            cm["sg"] = sigs

        compact_markets.append(cm)

    result["m"] = compact_markets

    # Global context (compact)
    g = snapshot.global_context
    result["g"] = {
        "btc": _round_price(g.btc_price),
        "b1h": round(g.btc_change_1h_pct, 1),
        "b24h": round(g.btc_change_24h_pct, 1),
        "eb": round(g.eth_btc_ratio, 4),
        "pos": g.total_open_positions,
        "pnl": round(g.daily_pnl, 1),
        "eq": round(g.equity, 0),
    }
    if g.circuit_breaker_active:
        result["g"]["cb"] = True

    # Trigger
    if snapshot.trigger_reason:
        result["t"] = snapshot.trigger_reason
        if snapshot.trigger_context:
            result["tc"] = snapshot.trigger_context[:200]

    # Memory (compact)
    if snapshot.memory_summary:
        result["mem"] = snapshot.memory_summary

    # Active positions (compact)
    if snapshot.active_positions:
        result["pos"] = [
            {
                "s": p.get("symbol", ""),
                "sd": p.get("side", ""),
                "e": p.get("entry", 0),
                "lv": p.get("leverage", 1),
                "pnl": round(p.get("unrealized_pnl", 0), 1),
            }
            for p in snapshot.active_positions
        ]

    # Growth intelligence context (knowledge, hypotheses, recent outcomes)
    try:
        from llm.growth.orchestrator import get_growth_orchestrator
        growth_ctx = get_growth_orchestrator().get_llm_context()
        if growth_ctx:
            # Truncate to save tokens (max ~400 chars)
            result["growth"] = growth_ctx[:400]
    except Exception:
        pass  # Growth system not available — no problem

    # Survival pressure context — constant accountability awareness
    try:
        from llm.survival_pressure import get_survival_context_for_llm
        survival_ctx = get_survival_context_for_llm()
        if survival_ctx:
            result["survival"] = survival_ctx[:500]
    except Exception:
        pass

    # Knowledge base injection — axioms, principles, anti-patterns
    try:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()
        # Extract current symbol/regime from trigger context
        symbol = ""
        regime = ""
        if snapshot.trigger_context:
            parts = snapshot.trigger_context.split()
            if parts:
                symbol = parts[0]
        knowledge_ctx = engine.get_knowledge_for_prompt(symbol=symbol, regime=regime)
        if knowledge_ctx:
            result["knowledge"] = knowledge_ctx[:600]
    except Exception:
        pass

    # Funding cost reminder — injected when positions are open
    if snapshot.active_positions:
        funding_notes = []
        for p in snapshot.active_positions:
            fr = p.get("funding_rate", 0)
            side = p.get("side", "").lower()
            sym = p.get("symbol", "")
            lev = p.get("leverage", 1)
            if fr and abs(fr) >= 0.0001:
                daily_cost = abs(fr) * 3 * lev * 100  # 3 payments/day, as % of position
                if (side in ("long", "buy") and fr > 0) or (side in ("short", "sell") and fr < 0):
                    funding_notes.append(
                        f"{sym}: PAYING {abs(fr)*100:.3f}%/8h funding ({daily_cost:.2f}%/day at {lev}x)"
                    )
                else:
                    funding_notes.append(
                        f"{sym}: EARNING {abs(fr)*100:.3f}%/8h funding"
                    )
        if funding_notes:
            result["funding_alert"] = " | ".join(funding_notes)

    return result


def _round_price(price: float) -> float:
    """Round price to appropriate precision based on magnitude."""
    if price == 0:
        return 0
    if price >= 1000:
        return round(price, 1)
    if price >= 1:
        return round(price, 2)
    if price >= 0.001:
        return round(price, 4)
    return round(price, 8)
