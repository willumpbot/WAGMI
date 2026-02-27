"""
Research Corpus: Structured knowledge base for strategy discovery.

Stores:
- Known strategy patterns (what works, what doesn't)
- Market regime observations
- Trade outcome summaries
- Pattern templates the LLM can reference

The corpus is a JSONL file that grows over time as the bot learns.
It feeds into the research agent for pattern recognition.
"""

import json
import logging
import os
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.llm.strategy_discovery.corpus")

_CORPUS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "strategy_corpus"
)
_OBSERVATIONS_FILE = os.path.join(_CORPUS_DIR, "observations.jsonl")
_PATTERNS_FILE = os.path.join(_CORPUS_DIR, "known_patterns.json")


# ── Known Strategy Pattern Templates ────────────────────────

PATTERN_TEMPLATES = {
    "momentum_breakout": {
        "description": "Price breaks key level with volume confirmation",
        "entry_conditions": [
            "price > resistance (1h+ timeframe)",
            "volume > 1.5x 20-period avg",
            "OI expanding",
        ],
        "exit_conditions": [
            "trailing SL below breakout level",
            "volume declining for 3+ candles",
        ],
        "best_regimes": ["trend"],
        "avoid_regimes": ["range", "low_liquidity"],
        "typical_rr": 2.5,
    },
    "mean_reversion": {
        "description": "Fade extended moves in range-bound markets",
        "entry_conditions": [
            "RSI divergence (price new high/low, RSI lower)",
            "price at range boundary",
            "funding rate extreme (> 0.03% or < -0.03%)",
        ],
        "exit_conditions": [
            "price reaches range midpoint",
            "momentum reversal confirmed",
        ],
        "best_regimes": ["range"],
        "avoid_regimes": ["trend", "panic"],
        "typical_rr": 1.5,
    },
    "funding_rate_arb": {
        "description": "Trade against extreme funding rates",
        "entry_conditions": [
            "funding rate > 0.05% or < -0.05% per 8h",
            "OI elevated (positions building on wrong side)",
            "no strong trend to justify funding",
        ],
        "exit_conditions": [
            "funding normalizes (< 0.02%)",
            "time-based exit (8-24h max hold)",
        ],
        "best_regimes": ["range", "high_volatility"],
        "avoid_regimes": ["trend"],
        "typical_rr": 1.0,
    },
    "liquidation_cascade": {
        "description": "Enter after mass liquidation events",
        "entry_conditions": [
            "OI drops > 10% in 4h (liquidation event)",
            "funding flips direction",
            "volume spike > 3x average",
        ],
        "exit_conditions": [
            "quick bounce target (50% retrace of drop)",
            "tight SL below new low",
        ],
        "best_regimes": ["panic", "high_volatility"],
        "avoid_regimes": ["range"],
        "typical_rr": 2.0,
    },
    "correlated_divergence": {
        "description": "Trade lagging assets when correlations temporarily break",
        "entry_conditions": [
            "BTC makes new move, alt hasn't followed yet",
            "historical correlation > 0.7 but current divergence > 2%",
            "volume on alt is normal (not deliberately decoupling)",
        ],
        "exit_conditions": [
            "convergence to expected level",
            "time stop if no convergence in 4h",
        ],
        "best_regimes": ["trend", "range"],
        "avoid_regimes": ["panic", "news_dislocation"],
        "typical_rr": 1.5,
    },
}


def ensure_corpus_dir():
    """Create corpus directory if needed."""
    os.makedirs(_CORPUS_DIR, exist_ok=True)


def add_observation(
    category: str,
    symbol: str,
    regime: str,
    observation: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Add a market observation to the corpus.

    Categories: trade_outcome, regime_shift, pattern_match, anomaly, insight
    """
    ensure_corpus_dir()
    entry = {
        "ts": int(time.time()),
        "category": category,
        "symbol": symbol,
        "regime": regime,
        "observation": observation,
        "data": data or {},
    }
    try:
        with open(_OBSERVATIONS_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"[CORPUS] Failed to write observation: {e}")


def load_observations(
    max_age_days: int = 30,
    category: Optional[str] = None,
    symbol: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load recent observations, optionally filtered."""
    if not os.path.exists(_OBSERVATIONS_FILE):
        return []

    cutoff = int(time.time()) - (max_age_days * 86400)
    results = []
    try:
        with open(_OBSERVATIONS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("ts", 0) < cutoff:
                    continue
                if category and entry.get("category") != category:
                    continue
                if symbol and entry.get("symbol") != symbol:
                    continue
                results.append(entry)
    except Exception as e:
        logger.warning(f"[CORPUS] Failed to load observations: {e}")

    return results


def get_corpus_summary(max_observations: int = 50) -> Dict[str, Any]:
    """Build a compact corpus summary for the LLM research agent."""
    observations = load_observations(max_age_days=14)

    # Group by category
    by_category: Dict[str, int] = {}
    by_regime: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    for obs in observations:
        cat = obs.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        reg = obs.get("regime", "unknown")
        by_regime[reg] = by_regime.get(reg, 0) + 1
        sym = obs.get("symbol", "?")
        by_symbol[sym] = by_symbol.get(sym, 0) + 1

    # Take most recent observations for the LLM
    recent = observations[-max_observations:] if observations else []

    return {
        "total_observations": len(observations),
        "by_category": by_category,
        "by_regime": by_regime,
        "by_symbol": by_symbol,
        "known_patterns": list(PATTERN_TEMPLATES.keys()),
        "recent_observations": [
            {
                "category": o["category"],
                "symbol": o["symbol"],
                "regime": o["regime"],
                "observation": o["observation"][:200],
            }
            for o in recent
        ],
    }


def trim_corpus(max_entries: int = 5000) -> int:
    """Keep only the most recent entries in the observations file."""
    if not os.path.exists(_OBSERVATIONS_FILE):
        return 0

    lines = []
    try:
        with open(_OBSERVATIONS_FILE, "r") as f:
            lines = f.readlines()
    except Exception:
        return 0

    if len(lines) <= max_entries:
        return 0

    trimmed = len(lines) - max_entries
    try:
        with open(_OBSERVATIONS_FILE, "w") as f:
            f.writelines(lines[trimmed:])
    except Exception:
        return 0

    logger.info(f"[CORPUS] Trimmed {trimmed} old observations")
    return trimmed
