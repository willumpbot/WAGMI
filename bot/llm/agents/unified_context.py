"""
DEPRECATED: This module has been merged into shared_context.py.

All data (REGIME_DEFINITIONS, STRATEGY_THEORY, SETUP_TYPES, FUNDING_IMPACT,
MARKET_AXIOMS, CONFIDENCE_SCALE) now lives in shared_context.py which is the
SINGLE source of truth imported by the coordinator.

This file is kept for reference only. Do NOT import from here.
Use: from llm.agents.shared_context import (REGIME_METADATA, SETUP_TYPES, ...)
"""

import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("bot.llm.agents.unified_context")


# ─────────────────────────────────────────────────────────────────────────────
# REGIME VOCABULARY (source of truth)
# ─────────────────────────────────────────────────────────────────────────────

REGIME_DEFINITIONS = {
    "trend": {
        "description": "Directional move with volume confirmation",
        "key_indicators": [
            "OI expanding > +5%/1h",
            "Volume >= 1.2x average",
            "Pullbacks < 30% of impulse",
            "Funding aligned with direction",
            "ADX > 20"
        ],
        "edge": "Highest profitability regime. Most money made here.",
        "avg_duration_h": [6, 18],
        "avg_win_rate": 0.68,
    },
    "range": {
        "description": "Choppy, sideways movement in tight band",
        "key_indicators": [
            "< 2% band over 4h",
            "Volume < 0.7x average",
            "OI flat ±2%",
            "ADX < 20",
            "Funding neutral"
        ],
        "edge": "Mean reversion only. Requires tight SL and quick exits.",
        "avg_duration_h": [4, 12],
        "avg_win_rate": 0.52,
    },
    "panic": {
        "description": "Crash regime, rapid downside, liquidations",
        "key_indicators": [
            "Price drop > 5%/1h OR > 8%/4h",
            "Volume spike > 3x average",
            "OI contracting rapidly",
            "Deep negative funding (< -0.03%)",
            "High volatility"
        ],
        "edge": "Big moves = big opportunity IF thesis strong. Catches create reversals.",
        "avg_duration_h": [1, 4],
        "avg_win_rate": 0.45,  # High variance
    },
    "high_volatility": {
        "description": "Large swings both ways, unstable",
        "key_indicators": [
            "ATR > 2x average",
            "Volume 1.5-2.5x average",
            "Unstable correlations",
            "Wider wicks"
        ],
        "edge": "Requires tight SL and better entry timing. Noise is higher.",
        "avg_duration_h": [2, 8],
        "avg_win_rate": 0.48,
    },
    "low_liquidity": {
        "description": "Dead market, wide spreads, wick traps",
        "key_indicators": [
            "Volume < 0.3x average",
            "Wide wicks > 60% of range",
            "Weekend/off-hours",
            "Bid-ask spread wide"
        ],
        "edge": "NO EDGE. Wicks will stop you out. ALWAYS SKIP.",
        "avg_duration_h": [0, 0],
        "avg_win_rate": 0.22,
    },
    "news_dislocation": {
        "description": "External catalyst, price move without setup",
        "key_indicators": [
            "> 3% move in < 30 minutes",
            "No prior technical setup",
            "OI unchanged",
            "Isolated move (not BTC-led)"
        ],
        "edge": "Unpredictable. Wait for dust to settle.",
        "avg_duration_h": [0.5, 2],
        "avg_win_rate": 0.40,
    },
    "unknown": {
        "description": "Conflicting signals, insufficient data",
        "key_indicators": ["Mixed indicators", "Unclear direction"],
        "edge": "NO EDGE. Always skip until clarity returns.",
        "avg_duration_h": [0, 0],
        "avg_win_rate": 0.33,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY THEORY (Why each strategy works in each regime)
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_THEORY = {
    "regime_trend": {
        "how": "WaveTrend cross on 1h + MACD/MFI regime filter on 6h/16h. align=0-4 confidence.",
        "when_strong": ["trend", "high_volatility"],
        "when_weak": ["range", "low_liquidity"],
        "success_rate": {"trend": 0.72, "range": 0.32, "panic": 0.48, "high_volatility": 0.61},
        "fail_mode": "Ranges produce false WT crosses. MFI divergence = watch out.",
    },
    "monte_carlo_zones": {
        "how": "SMA20±k*stdev zones + 1000 MC sims projecting 12h forward. Buys in buy zone when MC>60% up.",
        "when_strong": ["range", "high_volatility"],
        "when_weak": ["trend", "panic"],
        "success_rate": {"trend": 0.45, "range": 0.68, "panic": 0.38, "high_volatility": 0.55},
        "fail_mode": "Trends blow through zones. News dislocations break distributions.",
    },
    "confidence_scorer": {
        "how": "Multi-factor momentum: ADX+DI, MACD hist, BB/KC squeeze, RSI divergence. 1h data.",
        "when_strong": ["trend"],
        "when_weak": ["range", "low_liquidity"],
        "success_rate": {"trend": 0.70, "range": 0.40, "panic": 0.50, "high_volatility": 0.58},
        "fail_mode": "Choppy markets produce no signals. Squeeze can false-fire.",
    },
    "multi_tier_quality": {
        "how": "1h EMA20/50 crossover + VWAP alignment + 6h EMA trend. 3 tiers by strength.",
        "when_strong": ["trend"],
        "when_weak": ["range"],
        "success_rate": {"trend": 0.71, "range": 0.35, "panic": 0.52, "high_volatility": 0.59},
        "fail_mode": "Noisy in ranges (EMA whipsaw). Must confirm with slower strategy.",
    },
    "bollinger_squeeze": {
        "how": "BB/KC squeeze detection. Breakout direction from MACD. Bandwalk continuation.",
        "when_strong": ["high_volatility"],
        "when_weak": ["range"],
        "success_rate": {"trend": 0.65, "range": 0.42, "panic": 0.55, "high_volatility": 0.75},
        "fail_mode": "False squeezes in low-vol. Squeeze can resolve without breakout.",
    },
    "vmc_cipher": {
        "how": "5-oscillator confluence: WaveTrend, RSI, StochRSI, MACD, MFI + divergence.",
        "when_strong": ["trend", "high_volatility"],
        "when_weak": ["low_liquidity"],
        "success_rate": {"trend": 0.69, "range": 0.45, "panic": 0.48, "high_volatility": 0.68},
        "fail_mode": "Oscillators lag in quick moves. Divergences can persist.",
    },
    "lead_lag": {
        "how": "BTC→alt catch-up trades. Relative strength scoring. Historical lag times.",
        "when_strong": ["trend"],
        "when_weak": ["range", "low_liquidity"],
        "success_rate": {"trend": 0.71, "range": 0.38, "panic": 0.55, "high_volatility": 0.62},
        "fail_mode": "Lag can invert in quick reversals. Correlation breaks in panic.",
    },
    "oi_delta": {
        "how": "Open interest expansion/contraction vs price. Positioning signals.",
        "when_strong": ["trend", "panic"],
        "when_weak": ["range"],
        "success_rate": {"trend": 0.68, "range": 0.40, "panic": 0.62, "high_volatility": 0.65},
        "fail_mode": "OI lag behind price in quick moves. Late signal.",
    },
    "liquidation_cascade": {
        "how": "Post-cascade reversal after volume spikes + wick detection.",
        "when_strong": ["panic"],
        "when_weak": ["range"],
        "success_rate": {"trend": 0.52, "range": 0.35, "panic": 0.78, "high_volatility": 0.61},
        "fail_mode": "Cascades can re-trigger. Reversal timing uncertain.",
    },
    "probability_engine": {
        "how": "Regime-conditional Monte Carlo sims. EV gating.",
        "when_strong": ["trend"],
        "when_weak": ["news_dislocation"],
        "success_rate": {"trend": 0.67, "range": 0.42, "panic": 0.48, "high_volatility": 0.59},
        "fail_mode": "Models based on historical distribution. Breaks in regime shifts.",
    },
    "funding_rate": {
        "how": "Counter-trades extreme funding rates. Mean reversion.",
        "when_strong": ["range"],
        "when_weak": ["trend"],
        "success_rate": {"trend": 0.42, "range": 0.65, "panic": 0.38, "high_volatility": 0.48},
        "fail_mode": "Funding can spike further. Requires patience.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ACTION VOCABULARY (shared decision language)
# ─────────────────────────────────────────────────────────────────────────────

ACTION_DEFINITIONS = {
    "go": "Proceed with the trade (aliases: proceed, long, short, buy, sell, enter, trade)",
    "skip": "Do not trade (aliases: flat, hold, pass, wait, no, none, reject)",
    "flip": "Reverse the proposed direction (aliases: reverse)",
}


# ─────────────────────────────────────────────────────────────────────────────
# MARKET AXIOMS (hard rules every agent must respect)
# ─────────────────────────────────────────────────────────────────────────────

MARKET_AXIOMS = [
    "Never long alts into a BTC nuke (BTC dropping >3% in 1h)",
    "Circuit breaker active → always skip, confidence = 0.0",
    "Low liquidity regime → always skip (no edge, wicks eat PnL)",
    "Portfolio leverage >= 8.0 → skip (system auto-blocks)",
    "Funding > 0.05% per 8h → factor as a real cost",
    "3+ consecutive losses → raise selectivity bar",
    "Regime transition in progress → reduce confidence 15%",
    "Cross-market divergence (BTC up, target down) → strong caution",
    "Hold time > 4h with funding > 0.03% → funding drag destroys edge",
    "Near-zero stop width → infinite leverage risk, must reject",
]


# ─────────────────────────────────────────────────────────────────────────────
# SETUP TYPES (high-edge patterns)
# ─────────────────────────────────────────────────────────────────────────────

SETUP_TYPES = {
    "trend_at_zone": {
        "description": "Trend regime + signal at MC support/resistance zone",
        "confidence_boost": 0.15,
        "historical_wr": 0.72,
        "sample_size": 45,
    },
    "zone_validated": {
        "description": "MC zone confirmed by oscillator divergence + regime support",
        "confidence_boost": 0.10,
        "historical_wr": 0.68,
        "sample_size": 32,
    },
    "convergent_confluence": {
        "description": "3+ strategies agree from DIFFERENT methodologies (not redundant)",
        "confidence_boost": 0.12,
        "historical_wr": 0.70,
        "sample_size": 52,
    },
    "timeframe_confirmed": {
        "description": "Fast TF + slow TF align (5m/1h agree with 6h/16h)",
        "confidence_boost": 0.08,
        "historical_wr": 0.65,
        "sample_size": 28,
    },
    "lead_lag_catch": {
        "description": "Leader moved, follower hasn't caught up yet",
        "confidence_boost": 0.09,
        "historical_wr": 0.63,
        "sample_size": 35,
    },
    "post_cascade_reversal": {
        "description": "Liquidation cascade, now reversal forming",
        "confidence_boost": 0.14,
        "historical_wr": 0.71,
        "sample_size": 22,
    },
    "solo_high_conviction": {
        "description": "Only 1 strategy, but extremely high conviction + regime support",
        "confidence_boost": 0.0,  # No boost, base confidence only
        "historical_wr": 0.52,
        "sample_size": 18,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE SCALE (shared interpretation)
# ─────────────────────────────────────────────────────────────────────────────

CONFIDENCE_SCALE = {
    "0.0-0.3": "No edge — MUST skip",
    "0.3-0.5": "Weak — only proceed if regime crystal clear",
    "0.5-0.6": "Marginal — need 2+ strategy agreement AND regime support",
    "0.6-0.7": "Moderate — acceptable for normal sizing",
    "0.7-0.85": "Strong — regime + signals + convergence all align",
    "0.85-1.0": "Exceptional — everything perfect, maximum conviction",
}


# ─────────────────────────────────────────────────────────────────────────────
# FUNDING IMPACT TABLE (token-efficient reference)
# ─────────────────────────────────────────────────────────────────────────────

FUNDING_IMPACT = {
    "0-0.01": "Negligible",
    "0.01-0.03": "Slight — 4h+ holds, favor quick exits",
    "0.03-0.05": "Moderate — reduce size 20%, prefer SCALP",
    "0.05-0.08": "High — reduce size 40%, require 2%+ move to justify",
    "0.08+": "Critical — skip unless edge > 3%, or trade opposite side",
}


# ─────────────────────────────────────────────────────────────────────────────
# BUILD UNIFIED CONTEXT STRING (injected into all prompts)
# ─────────────────────────────────────────────────────────────────────────────

def build_unified_context_preamble() -> str:
    """Build the unified context that prefixes every agent prompt.

    This is the 'operating system' all agents run within. It's token-efficient
    and captures all shared knowledge so agents don't re-explain.

    Returns: Markdown-formatted context string (target: 800-1000 tokens)
    """
    preamble = """# UNIFIED AGENT CONTEXT
## The Shared Reality All Minds Operate Within

### REGIME VOCABULARY
- **trend** (edge: +68% WR): OI+5%/1h, vol 1.2x, pullbacks <30%, ADX>20. HIGHEST profits.
- **range** (edge: +52% WR): <2% band, vol 0.7x, ADX<20. Mean-reversion only.
- **panic** (edge: +45% WR, high variance): >5%/1h drop, vol spike 3x, OI contracting.
- **high_volatility** (edge: +48% WR): ATR 2x, unstable. Tight SL required.
- **low_liquidity** (edge: SKIP): Vol <0.3x, wide wicks. NO EDGE EXISTS.
- **news_dislocation** (edge: SKIP): Unpredictable external catalyst.
- **unknown** (edge: SKIP): Conflicting signals.

### STRATEGY TRUST MATRIX (regime → strategy success rate)
Highest-trust strategy per regime:
- trend: regime_trend(0.72), confidence_scorer(0.70)
- range: monte_carlo_zones(0.68), bollinger_squeeze(0.42)
- panic: liquidation_cascade(0.78), oi_delta(0.62)
- high_volatility: bollinger_squeeze(0.75), vmc_cipher(0.68)

### HIGH-EDGE SETUPS (confidence boost)
- **trend_at_zone**: +15% confidence, historical 72% WR (45 trades)
- **convergent_confluence**: +12% confidence, 70% WR (52 trades) — different strategies agree
- **post_cascade_reversal**: +14% confidence, 71% WR (22 trades)

### MARKET AXIOMS (non-negotiable rules)
1. BTC dropping >3%/1h → NEVER long alts (circuit breaker)
2. Low_liquidity regime → ALWAYS skip (wicks kill you)
3. Portfolio leverage ≥ 8.0 → ALWAYS skip (auto-blocked)
4. 3+ losses in a row → raise selectivity (skip more)
5. Funding >0.05% → real cost, reduce hold time or size

### CONFIDENCE INTERPRETATION
- < 0.40: MUST skip (consistency checker enforces)
- 0.40-0.55: Marginal (need regime + 2+ strategies)
- 0.55-0.70: Moderate (acceptable sizing)
- 0.70-0.85: Strong (regime + signals align)
- 0.85+: Exceptional (rare, size aggressively)

### FUNDING COST QUICK REFERENCE
- 0.01-0.03%: Slight impact, prefer quick exits on 4h+ holds
- 0.03-0.05%: Moderate, reduce size 20%, favor SCALP profile
- 0.05%+: High impact, skip unless edge >2%, or trade opposite

### YOUR ROLE IN THE SUPERINTELLIGENCE
You are ONE MIND in a 7-mind system. You see:
- Regime Agent's classification (source of truth on market regime)
- Trade Agent's thesis + confidence (what we think will happen)
- Risk Agent's sizing + portfolio state (how much we're risking)
- Critic's objections + counter-thesis (what could go wrong)
- Learning Agent's recent lessons (what we learned from closed trades)
- Scout's pre-theses (what's forming while we're idle)
- Deep memory + patterns (how similar setups resolved before)

THINK LIKE A UNIT, NOT IN ISOLATION."""

    return preamble


def build_agent_data_context(
    agent_role: str,
    snapshot: Dict[str, Any],
    performance_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Build runtime context for a specific agent.

    Args:
        agent_role: Which agent ("regime", "trade", "risk", etc.)
        snapshot: The market snapshot data
        performance_data: Agent calibration, recent outcomes, etc.

    Returns: Formatted context string specific to this agent
    """
    lines = []

    # Universal context
    lines.append("## YOUR CURRENT CONTEXT\n")

    # Recent regime
    if "regime" in snapshot:
        regime = snapshot["regime"]
        lines.append(f"**Market Regime**: {regime.get('rg', 'unknown')} (confidence: {regime.get('conf', 0.5):.1%})")
        if regime.get('momentum'):
            lines.append(f"**Momentum**: {regime.get('momentum')} — {'strengthening' if regime.get('momentum')=='strengthening' else 'weakening or stable'}")
        lines.append("")

    # Portfolio state
    if "portfolio" in snapshot:
        port = snapshot["portfolio"]
        lines.append(f"**Portfolio Leverage**: {port.get('leverage', 0):.1f}x (max 8.0)")
        lines.append(f"**Open Positions**: {len(port.get('positions', []))} trades")
        lines.append("")

    # Agent-specific context
    if agent_role == "trade" and "self_perf" in snapshot:
        perf = snapshot["self_perf"]
        lines.append(f"**Your Accuracy**: Trend={perf.get('trend_acc', 0):.1%}, Range={perf.get('range_acc', 0):.1%}")
        if perf.get('calibration_drift'):
            lines.append(f"**Calibration Note**: {perf['calibration_drift']}")
        lines.append("")

    if agent_role == "critic" and "self_perf" in snapshot:
        perf = snapshot["self_perf"]
        veto_acc = perf.get('veto_accuracy', 0.5)
        lines.append(f"**Your Veto Accuracy**: {veto_acc:.1%}")
        if veto_acc < 0.5:
            lines.append("⚠️ **WARNING**: You block winners. Require 5 red flags to veto, approve by default.")
        elif veto_acc > 0.75:
            lines.append("✓ **STRONG**: Your vetoes save money. Can veto with high confidence.")
        lines.append("")

    return "\n".join(lines)


def get_regime_context(regime_name: str) -> str:
    """Get detailed context for a specific regime."""
    if regime_name not in REGIME_DEFINITIONS:
        return f"Unknown regime: {regime_name}"

    rg = REGIME_DEFINITIONS[regime_name]
    lines = [
        f"## REGIME: {regime_name.upper()}",
        f"{rg.get('description')}",
        f"",
        f"**Key Indicators**:",
    ]
    for ind in rg.get("key_indicators", []):
        lines.append(f"- {ind}")

    lines.extend([
        f"",
        f"**Edge**: {rg.get('edge')}",
        f"**Typical Duration**: {rg['avg_duration_h'][0]}-{rg['avg_duration_h'][1]}h",
        f"**Historical Win Rate**: {rg['avg_win_rate']:.0%}",
    ])

    return "\n".join(lines)


def get_setup_context(setup_type: str) -> str:
    """Get context for a specific setup type."""
    if setup_type not in SETUP_TYPES:
        return f"Unknown setup: {setup_type}"

    st = SETUP_TYPES[setup_type]
    return f"""## SETUP: {setup_type.upper()}
{st['description']}

**Confidence Boost**: +{st['confidence_boost']:.0%}
**Historical Win Rate**: {st['historical_win_rate']:.0%} (n={st['sample_size']} trades)"""


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT FOR USE
# ─────────────────────────────────────────────────────────────────────────────

UNIFIED_PREAMBLE = build_unified_context_preamble()

__all__ = [
    "REGIME_DEFINITIONS",
    "STRATEGY_THEORY",
    "ACTION_DEFINITIONS",
    "MARKET_AXIOMS",
    "SETUP_TYPES",
    "CONFIDENCE_SCALE",
    "FUNDING_IMPACT",
    "UNIFIED_PREAMBLE",
    "build_unified_context_preamble",
    "build_agent_data_context",
    "get_regime_context",
    "get_setup_context",
]
