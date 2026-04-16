"""
Regime canonicalization — single source of truth for regime name translation.

The codebase uses several regime vocabularies in parallel:

  1. Execution-internal (trade_profile.py, dynamic_tp.py, probability_engine.py):
     "trending", "ranging", "volatile", "illiquid"
     These are legacy but stable — accumulated PnL data is keyed by these names
     in shared_context.py, trading_config.py, regime_optimization.py. Renaming
     would orphan the data.

  2. LLM canonical (Regime enum in decision_types.py):
     "trend", "range", "panic", "high_volatility", "low_liquidity",
     "news_dislocation", "unknown"
     This is the set validation.py/validator.py enforce on LLM outputs.

  3. LLM prompt-offered variants (prompts.py REGIME_AGENT_PROMPT):
     "trending_bull", "trending_bear", "consolidation"
     The Regime agent's system prompt offers these as valid outputs, but they
     don't live in the enum. Without translation they trip validation and
     abort the multi-agent pipeline.

  4. Quant brain micro-regimes (quant_brain.py):
     "panic_oversold", "recovering"
     Internal sub-classifications used by the rule-based pre-filter.

This module bridges all of them to the canonical (enum) set. It is imported
by the three validation entry points (validation.py, validator.py,
normalizers.py) so translation happens exactly once, at the LLM I/O boundary.
Execution-internal code keeps its legacy names and doesn't import this.

Adding a new synonym: append to REGIME_SYNONYMS and both validation paths
pick it up automatically.
"""

from typing import Optional


# Map non-canonical regime names to the canonical Regime enum values.
# Keys are lowercase; callers should lowercase before lookup.
REGIME_SYNONYMS: dict[str, str] = {
    # Execution-internal legacy vocab (trade_profile.py et al.)
    "illiquid": "low_liquidity",
    "trending": "trend",
    "ranging": "range",
    "volatile": "high_volatility",
    # LLM prompt-offered variants (REGIME_AGENT_PROMPT in prompts.py)
    "trending_bull": "trend",
    "trending_bear": "trend",
    "consolidation": "range",
    # Quant brain micro-regimes (quant_brain.py)
    "panic_oversold": "panic",
    "recovering": "trend",
}


def canonicalize_regime(regime: Optional[str]) -> Optional[str]:
    """Translate any known regime synonym to its canonical enum value.

    Returns the input unchanged (lowercased, stripped) if it's already
    canonical or unrecognized. Callers should still validate against the
    Regime enum after calling this — this function only maps synonyms,
    it does not reject invalid input.
    """
    if not isinstance(regime, str):
        return regime
    normalized = regime.strip().lower()
    return REGIME_SYNONYMS.get(normalized, normalized)
