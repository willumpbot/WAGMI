"""
Input/Output Normalizers: Ensure consistent schema on both sides of LLM boundary.

Input normalizer: Convert bot state -> LLM input snapshot (normalized ranges, consistent types)
Output normalizer: Convert raw LLM output -> typed LLMDecision (enums, clamps, defaults)

This prevents schema drift and token waste.
"""

import logging
from typing import Dict, Any, Optional

from llm.decision_types import (
    LLMDecision,
    StrategyWeights,
    Regime,
)

logger = logging.getLogger("bot.llm.normalizers")


# ── Input Normalizer (Bot -> LLM) ─────────────────────────────


def normalize_market_snapshot(market_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize market snapshot for LLM input.

    Ensures:
    - All numeric types are float
    - All prices have consistent decimal places
    - All percentages are in [0, 100]
    - Volatility is in reasonable range
    - Volume is normalized
    """
    normalized = market_dict.copy()

    # Price: round to 2-8 decimals based on magnitude
    if "price" in normalized:
        p = normalized["price"]
        if p >= 1000:
            normalized["price"] = round(float(p), 1)
        elif p >= 1:
            normalized["price"] = round(float(p), 2)
        elif p >= 0.001:
            normalized["price"] = round(float(p), 4)
        else:
            normalized["price"] = round(float(p), 8)

    # Percentages: ensure in reasonable range
    for key in ["price_change_1h_pct", "price_change_24h_pct", "volatility"]:
        if key in normalized:
            normalized[key] = float(max(-100, min(100, normalized[key])))

    # Volume ratio: clamp to [0.1, 10]
    if "volume_ratio" in normalized:
        normalized["volume_ratio"] = float(max(0.1, min(10.0, normalized["volume_ratio"])))

    # Funding rate: keep as-is but ensure float
    if "funding_rate" in normalized:
        normalized["funding_rate"] = float(normalized["funding_rate"])

    # OI change: clamp to [-100, 100]
    if "open_interest_change_pct" in normalized:
        normalized["open_interest_change_pct"] = float(
            max(-100, min(100, normalized["open_interest_change_pct"]))
        )

    return normalized


def normalize_global_context(global_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize global market context for LLM input.

    Ensures consistent types and ranges.
    """
    normalized = global_dict.copy()

    # BTC price
    if "btc_price" in normalized:
        normalized["btc_price"] = round(float(normalized["btc_price"]), 0)

    # BTC changes: clamp to [-100, 100]
    for key in ["btc_change_1h_pct", "btc_change_24h_pct"]:
        if key in normalized:
            normalized[key] = float(max(-100, min(100, normalized[key])))

    # ETH/BTC ratio
    if "eth_btc_ratio" in normalized:
        normalized["eth_btc_ratio"] = round(float(normalized["eth_btc_ratio"]), 4)

    # PnL / equity
    for key in ["daily_pnl", "equity"]:
        if key in normalized:
            normalized[key] = round(float(normalized[key]), 1)

    # Positions: ensure int
    if "total_open_positions" in normalized:
        normalized["total_open_positions"] = int(normalized["total_open_positions"])

    # Circuit breaker: ensure bool
    if "circuit_breaker_active" in normalized:
        normalized["circuit_breaker_active"] = bool(normalized["circuit_breaker_active"])

    return normalized


# ── Output Normalizer (LLM -> Bot) ───────────────────────────


def normalize_llm_output(raw_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM raw output for typed conversion.

    Ensures:
    - action is lowercase
    - confidence is float [0, 1]
    - size_multiplier is float [0, 2]
    - regime is valid
    - entry_adjustment is known or null
    - strategy_weights are normalized
    """
    normalized = raw_dict.copy()

    # Normalize action: lowercase, strip whitespace
    if "action" in normalized:
        action = str(normalized["action"]).strip().lower()
        normalized["action"] = action

    # Normalize confidence: ensure float, clamp to [0, 1]
    if "confidence" in normalized:
        try:
            conf = float(normalized["confidence"])
            normalized["confidence"] = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            normalized["confidence"] = 0.5
            logger.warning(f"[LLM-NORM] Invalid confidence, defaulting to 0.5")

    # Normalize size_multiplier: ensure float, clamp to [0, 2]
    if "size_multiplier" in normalized:
        try:
            mult = float(normalized["size_multiplier"])
            normalized["size_multiplier"] = max(0.0, min(2.0, mult))
        except (ValueError, TypeError):
            normalized["size_multiplier"] = 1.0
    else:
        normalized["size_multiplier"] = 1.0

    # Normalize regime: ensure valid or fallback to unknown
    if "regime" in normalized:
        regime = str(normalized["regime"]).strip().lower()
        valid_regimes = {r.value for r in Regime}
        if regime not in valid_regimes:
            logger.warning(f"[LLM-NORM] Invalid regime {regime!r}, using 'unknown'")
            normalized["regime"] = "unknown"
        else:
            normalized["regime"] = regime
    else:
        normalized["regime"] = "unknown"

    # Normalize entry_adjustment: strip whitespace, validate or set null
    if "entry_adjustment" in normalized and normalized["entry_adjustment"]:
        adj = str(normalized["entry_adjustment"]).strip()
        valid_adjs = {
            "market now",
            "wait for pullback",
            "enter only if reclaim",
            "enter only if sweep of liquidity",
            "enter only if btc confirms",
            "scale in",
        }
        if adj.lower() not in valid_adjs:
            logger.warning(f"[LLM-NORM] Unknown entry_adjustment {adj!r}, clearing")
            normalized["entry_adjustment"] = None
        else:
            normalized["entry_adjustment"] = adj.lower()
    else:
        normalized["entry_adjustment"] = None

    # Normalize strategy_weights: ensure all values are float [0, 1]
    if "strategy_weights" in normalized and isinstance(normalized["strategy_weights"], dict):
        sw = normalized["strategy_weights"]
        norm_sw = {}
        for key in [
            "regime_trend", "monte_carlo_zones", "confidence_scorer", "multi_tier_quality",
            "funding_rate", "open_interest", "volume_momentum", "cross_asset"
        ]:
            val = sw.get(key, 0.5)
            try:
                norm_sw[key] = max(0.0, min(1.0, float(val)))
            except (ValueError, TypeError):
                norm_sw[key] = 0.5
        normalized["strategy_weights"] = norm_sw
    else:
        # Default strategy weights
        normalized["strategy_weights"] = {
            "regime_trend": 0.5,
            "monte_carlo_zones": 0.5,
            "confidence_scorer": 0.5,
            "multi_tier_quality": 0.5,
            "funding_rate": 0.0,
            "open_interest": 0.0,
            "volume_momentum": 0.0,
            "cross_asset": 0.0,
        }

    # Normalize memory_update: truncate if too long
    if "memory_update" in normalized and normalized["memory_update"]:
        mu = str(normalized["memory_update"]).strip()
        if len(mu) > 200:
            mu = mu[:197] + "..."
        normalized["memory_update"] = mu
    else:
        normalized["memory_update"] = None

    # Normalize notes: ensure string, truncate if needed
    if "notes" in normalized:
        notes = str(normalized["notes"]).strip()
        if len(notes) > 1000:
            notes = notes[:997] + "..."
        normalized["notes"] = notes
    else:
        normalized["notes"] = ""

    return normalized


def decision_from_normalized_dict(normalized_dict: Dict[str, Any]) -> LLMDecision:
    """Convert normalized dict to typed LLMDecision.

    Assumes input has been through normalize_llm_output().
    """
    sw_dict = normalized_dict.get("strategy_weights", {})
    strategy_weights = StrategyWeights.from_dict(sw_dict)

    decision = LLMDecision(
        action=normalized_dict.get("action", "flat"),
        confidence=normalized_dict.get("confidence", 0.5),
        regime=normalized_dict.get("regime", "unknown"),
        strategy_weights=strategy_weights,
        memory_update=normalized_dict.get("memory_update"),
        notes=normalized_dict.get("notes", ""),
        size_multiplier=normalized_dict.get("size_multiplier", 1.0),
        entry_adjustment=normalized_dict.get("entry_adjustment"),
    )

    logger.info(
        f"[LLM-NORM] Normalized decision: {decision.action} "
        f"conf={decision.confidence:.2f} size_mult={decision.size_multiplier:.2f}"
    )

    return decision
