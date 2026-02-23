"""
Global Market Meta-Brain: Holistic market reasoning.

Enables the LLM to reason about the entire market:
- BTC/ETH dominance trends
- Sector rotations (large/mid/meme)
- Volatility clustering
- Funding regime classification
- Liquidity conditions

Global actions:
- risk_on: Allow larger sizes, more positions
- risk_off: Reduce sizes, reduce number of positions
- neutral: Normal operation
- symbol_blacklist: Block trades in specific symbols
- symbol_whitelist: Prioritize specific symbols

This context is added to the LLM snapshot to enable
cross-market reasoning that individual strategies can't do.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

logger = logging.getLogger("bot.llm.global_brain")


VALID_GLOBAL_BIASES = {"risk_on", "risk_off", "neutral"}

# Default sector classification
SECTOR_MAP = {
    "large_cap": ["BTC", "ETH"],
    "mid_cap": ["SOL", "HYPE", "XRP", "AVAX", "LINK", "SUI", "NEAR", "ARB"],
    "meme": ["DOGE", "WIF", "PEPE", "FARTCOIN"],
    "defi": ["TIA", "SEI", "JUP", "ONDO"],
}


def build_global_context(
    btc_price: float,
    btc_1h_change: float,
    btc_24h_change: float,
    eth_price: float,
    last_prices: Dict[str, float],
    funding_rates: Dict[str, float] = None,
) -> Dict[str, Any]:
    """Build global market context for LLM input.

    Analyzes cross-market conditions to classify the global regime.
    """
    # BTC dominance proxy: BTC move vs alt move
    alt_avg_1h = 0.0
    alt_count = 0
    for sector, symbols in SECTOR_MAP.items():
        if sector == "large_cap":
            continue
        for sym in symbols:
            if sym in last_prices:
                alt_count += 1

    # Sector performance (approximate from price presence)
    sectors_active = {}
    for sector, symbols in SECTOR_MAP.items():
        active = sum(1 for s in symbols if s in last_prices and last_prices[s] > 0)
        sectors_active[sector] = active

    # Funding regime: net funding across symbols
    net_funding = 0.0
    if funding_rates:
        vals = [v for v in funding_rates.values() if isinstance(v, (int, float))]
        net_funding = sum(vals) / len(vals) if vals else 0.0

    # Classify global bias
    bias = _classify_bias(btc_24h_change, net_funding)

    return {
        "btc_price": btc_price,
        "btc_1h": btc_1h_change,
        "btc_24h": btc_24h_change,
        "eth_price": eth_price,
        "eth_btc": eth_price / btc_price if btc_price > 0 else 0,
        "net_funding": round(net_funding, 6),
        "sectors_active": sectors_active,
        "classified_bias": bias,
        "symbols_with_data": len(last_prices),
    }


def _classify_bias(btc_24h: float, net_funding: float) -> str:
    """Classify the global market bias from BTC trend + funding.

    Simple heuristic (LLM can override in FULL mode):
    - BTC up > 3% and funding positive -> risk_on
    - BTC down > 3% and funding negative -> risk_off
    - Otherwise -> neutral
    """
    if btc_24h > 3.0 and net_funding >= 0:
        return "risk_on"
    elif btc_24h < -3.0 and net_funding <= 0:
        return "risk_off"
    return "neutral"


def apply_global_bias(
    bias: str,
    base_size_multiplier: float = 1.0,
    max_positions: int = 6,
) -> Dict[str, Any]:
    """Apply global bias to trading parameters.

    Returns adjusted parameters (multiplicative).
    """
    if bias == "risk_on":
        return {
            "size_multiplier": base_size_multiplier * 1.2,
            "max_positions": max_positions,  # Full capacity
            "description": "Risk on: slightly larger sizes",
        }
    elif bias == "risk_off":
        return {
            "size_multiplier": base_size_multiplier * 0.6,
            "max_positions": max(max_positions - 2, 2),  # Reduce capacity
            "description": "Risk off: reduced sizes and positions",
        }
    else:
        return {
            "size_multiplier": base_size_multiplier,
            "max_positions": max_positions,
            "description": "Neutral: normal operation",
        }


def apply_symbol_filters(
    symbols: List[str],
    blacklist: Optional[Set[str]] = None,
    whitelist: Optional[Set[str]] = None,
) -> List[str]:
    """Filter symbols based on blacklist/whitelist.

    - Blacklisted symbols are removed entirely
    - Whitelisted symbols are prioritized (moved to front)
    - If no whitelist, order preserved
    """
    # Remove blacklisted
    if blacklist:
        symbols = [s for s in symbols if s not in blacklist]

    # Prioritize whitelisted
    if whitelist:
        prioritized = [s for s in symbols if s in whitelist]
        remaining = [s for s in symbols if s not in whitelist]
        symbols = prioritized + remaining

    return symbols
