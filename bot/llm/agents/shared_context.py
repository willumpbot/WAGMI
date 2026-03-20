"""
Shared Context: unified reasoning framework for all specialist agents.

Every agent in the multi-agent pipeline shares:
  1. Vocabulary — identical terms for regimes, actions, confidence scales
  2. Market axioms — hard rules that every agent must respect
  3. Regime-action mapping — what actions are acceptable in each regime
  4. Knowledge base — shared lessons that apply to ALL agents
  5. Setup types — high-edge patterns with historical performance
  6. Funding impact table — cost reference for hold decisions

This module builds a compact shared context block that gets prepended to every
agent's input, ensuring they all reason from the same foundation.

NOTE: This is the SINGLE source of truth for shared context. All agents import
from here. unified_context.py is deprecated — its data has been merged here.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.shared_context")


# ── Shared Vocabulary ────────────────────────────────────────────

REGIME_VOCABULARY = {
    "trend": "Directional move with volume confirmation (OI expanding, funding aligned, pullbacks <30%)",
    "range": "Choppy <2% band, low volume, flat OI, ADX<20",
    "panic": "Crash >5%/1h, volume spike >3x, OI contracting, deep negative funding",
    "high_volatility": "Big swings both ways, ATR>2x avg, unstable correlations",
    "low_liquidity": "Dead market, volume <0.3x avg, wide wicks, off-hours",
    "news_dislocation": "External catalyst >3% in <30min, no prior setup, OI unchanged",
    "unknown": "Conflicting signals, insufficient data",
}

# Extended regime metadata with historical performance (from unified_context.py merge)
REGIME_METADATA = {
    "trend": {"avg_win_rate": 0.68, "avg_duration_h": (6, 18), "edge": "Highest profitability regime"},
    "range": {"avg_win_rate": 0.52, "avg_duration_h": (4, 12), "edge": "Mean reversion only"},
    "panic": {"avg_win_rate": 0.45, "avg_duration_h": (1, 4), "edge": "High variance, catches create reversals"},
    "high_volatility": {"avg_win_rate": 0.48, "avg_duration_h": (2, 8), "edge": "Tight SL, better entry timing"},
    "low_liquidity": {"avg_win_rate": 0.22, "avg_duration_h": (0, 0), "edge": "NO EDGE — always skip"},
    "news_dislocation": {"avg_win_rate": 0.40, "avg_duration_h": (0.5, 2), "edge": "Unpredictable — wait"},
    "unknown": {"avg_win_rate": 0.33, "avg_duration_h": (0, 0), "edge": "NO EDGE — always skip"},
}

# High-edge setup types with historical performance
SETUP_TYPES = {
    "trend_at_zone": {"confidence_boost": 0.15, "historical_wr": 0.72, "sample_size": 45},
    "zone_validated": {"confidence_boost": 0.10, "historical_wr": 0.68, "sample_size": 32},
    "convergent_confluence": {"confidence_boost": 0.12, "historical_wr": 0.70, "sample_size": 52},
    "timeframe_confirmed": {"confidence_boost": 0.08, "historical_wr": 0.65, "sample_size": 28},
    "lead_lag_catch": {"confidence_boost": 0.09, "historical_wr": 0.63, "sample_size": 35},
    "post_cascade_reversal": {"confidence_boost": 0.14, "historical_wr": 0.71, "sample_size": 22},
    "solo_high_conviction": {"confidence_boost": 0.0, "historical_wr": 0.52, "sample_size": 18},
}

# Funding impact reference (8h rate → impact assessment)
FUNDING_IMPACT = {
    "0-0.01": "Negligible",
    "0.01-0.03": "Slight — 4h+ holds, favor quick exits",
    "0.03-0.05": "Moderate — reduce size 20%, prefer SCALP",
    "0.05-0.08": "High — reduce size 40%, require 2%+ move to justify",
    "0.08+": "Critical — skip unless edge > 3%, or trade opposite side",
}

ACTION_VOCABULARY = {
    "go": "Proceed with the trade (aliases: proceed, long, short, buy, sell, enter, trade)",
    "skip": "Do not trade (aliases: flat, hold, pass, wait, no, none)",
    "flip": "Reverse the proposed direction (aliases: reverse)",
}

CONFIDENCE_SCALE = {
    "0.0-0.3": "No edge — must skip",
    "0.3-0.5": "Weak — only proceed if absolutely everything aligns",
    "0.5-0.6": "Marginal — proceed only with 3+ strategy agreement AND regime alignment",
    "0.6-0.7": "Moderate conviction — acceptable for normal sizing",
    "0.7-0.85": "Strong — regime + signals + cross-market all align, size up",
    "0.85-1.0": "Exceptional — everything perfect, rare, maximum conviction",
}


# ── Market Axioms (hard rules every agent must respect) ──────────

MARKET_AXIOMS = [
    "Never long alts into a BTC nuke (BTC dropping >3% in 1h)",
    "Circuit breaker active → always skip, confidence = 0.0",
    "Low liquidity regime → always skip (no edge, wide spreads eat PnL)",
    "Portfolio leverage >= 8.0 → skip (system auto-blocks, don't waste the call)",
    "Funding > 0.05% per 8h → factor as a real cost, not just a signal",
    "3+ consecutive losses → raise selectivity bar, reduce sizing",
    "Regime transition in progress → reduce confidence 15%, wait for confirmation",
    "Cross-market divergence (BTC up, target down) → strong caution signal",
    "Hold time > 4h with funding > 0.03% → funding drag destroys edge",
    "Near-zero stop width → infinite leverage risk, must reject",
]


# ── Regime-Action Mapping ────────────────────────────────────────

REGIME_ACTION_MAP = {
    "trend": {
        "preferred_actions": ["go"],
        "acceptable_actions": ["go", "skip"],
        "forbidden_actions": [],
        "sizing_range": "0.8-2.0",
        "notes": "Trend is the highest-edge regime. Align with direction, size up.",
    },
    "range": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": ["flip"],
        "sizing_range": "0.3-0.8",
        "notes": "Range trades need tight SL and quick exits. Mean-reversion only.",
    },
    "panic": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": [],
        "sizing_range": "0.0-0.5",
        "notes": "Panic has big moves = big opportunity IF thesis is strong. "
                 "Require conf >= 0.70 and clear reversal/continuation thesis. Small size.",
    },
    "high_volatility": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": [],
        "sizing_range": "0.3-0.7",
        "notes": "Reduce sizing. Only high-conviction setups. ATR-based stops must be wider.",
    },
    "low_liquidity": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip"],
        "forbidden_actions": ["go", "flip"],
        "sizing_range": "0.0",
        "notes": "Never trade in low liquidity. Wicks will stop you out.",
    },
    "news_dislocation": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip", "go"],
        "forbidden_actions": [],
        "sizing_range": "0.3-0.5",
        "notes": "Wait for dust to settle. If entering, use wide stops and small size.",
    },
    "unknown": {
        "preferred_actions": ["skip"],
        "acceptable_actions": ["skip"],
        "forbidden_actions": ["go", "flip"],
        "sizing_range": "0.0",
        "notes": "Unknown = no edge. Wait for clarity.",
    },
}


# ── Strategy Theory (HOW and WHY each strategy works) ────────────

STRATEGY_THEORY = {
    "regime_trend": {
        "how": "WaveTrend cross on 1h + MACD/MFI regime filter on 6h/16h. align=0-4 (cross+MFI+6h_regime+16h_regime).",
        "trust": "Best in trend. 4/4 align=strong conviction. Momentum entry (recent cross, not this-bar)=slightly weaker.",
        "fail": "Ranges produce false WT crosses. MFI<40 in bull regime=divergence, caution.",
    },
    "monte_carlo_zones": {
        "how": "SMA20±k*stdev zones + 1000 MC sims projecting 12h fwd. Buys in buy zone when MC>60% up.",
        "trust": "Best in range/mean-reversion. Stronger when RSI14 confirms (oversold for buys, overbought for sells).",
        "fail": "Trends blow through zones without reverting. News dislocations make historical distribution useless.",
    },
    "confidence_scorer": {
        "how": "Multi-factor momentum: ADX+DI direction, MACD histogram acceleration, BB/KC squeeze detection, RSI divergence. 1h data. Historical win rate tracking per (symbol, action).",
        "trust": "Best in trending markets (ADX>25). Squeeze signals catch breakouts. Historical WR tracking improves over time.",
        "fail": "Choppy markets (ADX<20) produce no signals. Cold start (<10 trades)=no historical adjustment. Squeeze can false-fire.",
    },
    "multi_tier_quality": {
        "how": "1h EMA20/50 crossover + VWAP alignment + 6h EMA trend. 3 tiers: PRIORITY(75%+), REGULAR(65%+), MANUAL(<65%).",
        "trust": "Best for confirmed multi-TF entries. When EMA+VWAP+6h all align=high conviction entry.",
        "fail": "Noisy in ranges (EMA whipsaw). Must confirm with slower strategy. MANUAL tier=low conviction.",
    },
    "bollinger_squeeze": {
        "how": "BB/KC squeeze detection. When BB contracts inside KC=compression. Breakout direction from MACD histogram. Bandwalk continuation signals.",
        "trust": "Best for volatility expansion plays. Squeeze breakout with 5+ bars compression=strong. HYPE's dominant pattern.",
        "fail": "False squeezes in low-vol sideways. Squeeze can resolve without directional breakout.",
    },
    "vmc_cipher": {
        "how": "5 oscillators: WaveTrend, RSI, StochRSI, MACD, MFI. Requires >=3 agreement. Divergence detection for reversals.",
        "trust": "Best when multiple oscillators align. Divergence signals=high probability reversals. Cross-validation reduces false signals.",
        "fail": "Ranging markets=oscillator noise. All oscillators lag. WT zones relaxed for high-vol assets (±55 vs ±60).",
    },
    "probability_engine": {
        "how": "Monte Carlo simulation with antithetic variates. Computes prob(TP1), prob(TP2), prob(SL) for proposed trade. EV filtering.",
        "trust": "Best for statistical edge validation. High prob_tp1 + positive EV = high quality. Tighter thresholds for high-vol assets.",
        "fail": "Assumes log-normal returns. Fat-tail events (HYPE crashes) not captured. MC sims are forward estimates, not guarantees.",
    },
    "funding_rate": {
        "how": "Counter-trade extreme funding rates. Positive funding → SELL (longs overpaying), negative → BUY. ADX trend guard prevents fading strong trends.",
        "trust": "Best in ranging/high-vol markets. HYPE funding spikes 10x normal. Mean-reversion from crowded positioning.",
        "fail": "Funding can stay extreme in strong trends. ADX guard silences signals when they'd work best. Needs live data (no backtest).",
    },
    "oi_delta": {
        "how": "OI expansion/contraction + price direction. OI↑+Price↑=accumulation, OI↓+Price↓=liquidation reversal. 5% threshold filters noise.",
        "trust": "Best for conviction measurement. Works across all regimes. HYPE OI swings 30-50% daily=frequent signals.",
        "fail": "Needs live exchange data. 5% threshold may miss early moves. OI data can be delayed.",
    },
    "liquidation_cascade": {
        "how": "Detects cascade events via volume spikes (3x avg) + large wicks (>60% of range). Signals reversal after forced selling/buying.",
        "trust": "Best for HYPE/high-leverage tokens. Weekly 20-30% cascades are tradeable. Proxy detection works with OHLCV only.",
        "fail": "Cascades can continue (no immediate reversal 30-40% of time). Conflicts with trend-following strategies.",
    },
}

# When two strategies agree, the QUALITY of that agreement varies:
# Convergent = different methodologies reaching same conclusion (highest value)
# Timeframe = fast + slow confirming each other (high value)
# Redundant = similar inputs/methodology (moderate value — less independent)
STRATEGY_CONFLUENCE = {
    ("regime_trend", "monte_carlo_zones"): "convergent — trend momentum + statistical zone agree. If both BUY: macro trend AND price at statistical buy level. Very strong.",
    ("regime_trend", "multi_tier_quality"): "timeframe — 6h/16h macro direction + 5m micro entry. If both BUY: regime confirms + exact entry bar found. Best timing.",
    ("regime_trend", "confidence_scorer"): "convergent — WT regime + ADX/MACD momentum. If both BUY: macro trend AND momentum acceleration both confirm. Very strong.",
    ("monte_carlo_zones", "confidence_scorer"): "convergent — statistical zones + momentum indicators. Different methodologies (mean-reversion vs trend-following). High-value agreement.",
    ("monte_carlo_zones", "multi_tier_quality"): "convergent — statistical zone + EMA multi-TF trend. If both BUY: mean-reversion level confirmed by 1h+6h momentum shift.",
    ("confidence_scorer", "multi_tier_quality"): "convergent — ADX/MACD momentum + EMA multi-TF quality. If both BUY: momentum + multi-timeframe structure both confirm entry.",
    ("funding_rate", "oi_delta"): "convergent — positioning (funding) + conviction (OI). Complementary signals: both measure market participants' behavior, not just price.",
    ("liquidation_cascade", "funding_rate"): "convergent — both fade crowded positions. Cascade = forced exit, funding = overpay. If both signal: crowded trade is unwinding.",
    ("oi_delta", "regime_trend"): "convergent — OI conviction + trend momentum. OI↑ + trend BUY = genuine accumulation. Very strong in trending regimes.",
    ("bollinger_squeeze", "vmc_cipher"): "convergent — volatility compression (BB) + multi-oscillator momentum (VMC). If both BUY: squeeze breakout confirmed by oscillator consensus.",
    ("probability_engine", "monte_carlo_zones"): "redundant — both use Monte Carlo simulation (different implementations). Agreement is expected; disagreement is more informative.",
    ("liquidation_cascade", "oi_delta"): "convergent — cascade event + OI drop confirms forced position closure. Post-cascade reversal with OI contraction = high quality.",
}

# Confluence quality weights: convergent > timeframe > redundant
_CONFLUENCE_TYPE_SCORES = {
    "convergent": 1.0,
    "timeframe": 0.8,
    "redundant": 0.5,
}


def score_confluence(agreeing_strategies: List[str], regime: str = "") -> Dict[str, Any]:
    """Score the quality of strategy agreement — not just count, but type.

    Returns:
        {
            "count": int,
            "quality": float (0-1, quality-weighted),
            "best_pair": str (best confluence type found),
            "pairs": [{"s1": x, "s2": y, "type": t}],
            "regime_fit": float (0-1, how well agreeing strategies fit current regime),
            "setup_type": str (classified setup pattern),
        }
    """
    count = len(agreeing_strategies)
    if count < 2:
        setup_type = agreeing_strategies[0] if agreeing_strategies else "none"
        regime_fit_score = 0.5
        if regime and agreeing_strategies:
            fit = STRATEGY_REGIME_FIT.get(regime, {})
            fit_val = fit.get(agreeing_strategies[0], "moderate")
            regime_fit_score = {"strong": 1.0, "moderate": 0.6, "weak": 0.3, "avoid": 0.0}.get(fit_val, 0.5)
        return {
            "count": count,
            "quality": 0.3 if count == 1 else 0.0,
            "best_pair": "none",
            "pairs": [],
            "regime_fit": regime_fit_score,
            "setup_type": f"solo_{setup_type}",
        }

    pairs = []
    best_type = "redundant"
    best_score = 0.0

    for i, s1 in enumerate(agreeing_strategies):
        for s2 in agreeing_strategies[i + 1:]:
            key = (s1, s2) if (s1, s2) in STRATEGY_CONFLUENCE else (s2, s1)
            desc = STRATEGY_CONFLUENCE.get(key, "redundant — unknown pair")
            confl_type = desc.split(" — ")[0].strip()
            score = _CONFLUENCE_TYPE_SCORES.get(confl_type, 0.4)
            pairs.append({"s1": s1, "s2": s2, "type": confl_type})
            if score > best_score:
                best_score = score
                best_type = confl_type

    # Quality = average pair quality, boosted by count
    avg_pair_score = sum(_CONFLUENCE_TYPE_SCORES.get(p["type"], 0.4) for p in pairs) / max(len(pairs), 1)
    count_boost = min(count / 4.0, 1.0)  # 4 strategies = max boost
    quality = avg_pair_score * 0.7 + count_boost * 0.3

    # Regime fit: average fit of agreeing strategies
    regime_fit_score = 0.5
    if regime:
        fit = STRATEGY_REGIME_FIT.get(regime, {})
        fit_scores = []
        for s in agreeing_strategies:
            fit_val = fit.get(s, "moderate")
            fit_scores.append({"strong": 1.0, "moderate": 0.6, "weak": 0.3, "avoid": 0.0}.get(fit_val, 0.5))
        regime_fit_score = sum(fit_scores) / len(fit_scores) if fit_scores else 0.5

    # Classify setup type
    setup_type = _classify_setup(agreeing_strategies, best_type, regime)

    return {
        "count": count,
        "quality": round(quality, 2),
        "best_pair": best_type,
        "pairs": pairs,
        "regime_fit": round(regime_fit_score, 2),
        "setup_type": setup_type,
    }


def _classify_setup(strategies: List[str], best_confluence: str, regime: str) -> str:
    """Classify the trade setup into a named pattern for tracking.

    Setup types become the DNA of the trading system — the Learning Agent
    tracks which setups win and which lose, building a statistical edge map.
    """
    strats = set(strategies)
    n = len(strats)

    # 4-strategy full agreement
    if n >= 4:
        return f"full_confluence_{regime}" if regime else "full_confluence"

    # Named 3-strategy setup patterns (check before 2-strategy to capture specifics)
    if n >= 3:
        if {"regime_trend", "monte_carlo_zones", "multi_tier_quality"}.issubset(strats):
            return "trend_zone_micro"  # Macro trend + statistical zone + micro entry
        if {"regime_trend", "monte_carlo_zones", "confidence_scorer"}.issubset(strats):
            return "trend_zone_validated"  # Macro trend + zone + historical validation
        if {"regime_trend", "multi_tier_quality", "confidence_scorer"}.issubset(strats):
            return "trend_micro_validated"  # Macro trend + micro + validated
        if {"monte_carlo_zones", "multi_tier_quality", "confidence_scorer"}.issubset(strats):
            return "zone_micro_validated"  # Mean-reversion zone + micro + validated

    # Named 2-strategy setup patterns
    if {"regime_trend", "monte_carlo_zones"}.issubset(strats):
        return "trend_at_zone"  # Trending + at statistical buy/sell zone
    if {"regime_trend", "multi_tier_quality"}.issubset(strats):
        return "trend_micro_entry"  # Macro trend + micro timing
    if {"monte_carlo_zones", "confidence_scorer"}.issubset(strats):
        return "zone_validated"  # Zone + historical validation
    if {"monte_carlo_zones", "multi_tier_quality"}.issubset(strats):
        return "zone_momentum"  # Zone level + EMA momentum shift
    if {"confidence_scorer", "multi_tier_quality"}.issubset(strats):
        return "validated_scalp"  # Historical edge + scalp entry
    if {"regime_trend", "confidence_scorer"}.issubset(strats):
        return "trend_validated"  # Trend + historically validated

    # Fallback: generic
    return f"pair_{best_confluence}" if n >= 2 else f"solo_{best_confluence}"


STRATEGY_REGIME_FIT = {
    "trend": {
        "regime_trend": "strong", "monte_carlo_zones": "weak", "confidence_scorer": "strong", "multi_tier_quality": "moderate",
        "bollinger_squeeze": "weak", "funding_rate": "strong", "lead_lag": "moderate", "liquidation_cascade": "moderate",
        "oi_delta": "strong", "probability_engine": "strong", "vmc_cipher": "moderate",
    },
    "range": {
        "regime_trend": "avoid", "monte_carlo_zones": "strong", "confidence_scorer": "weak", "multi_tier_quality": "weak",
        "bollinger_squeeze": "strong", "funding_rate": "moderate", "lead_lag": "weak", "liquidation_cascade": "weak",
        "oi_delta": "moderate", "probability_engine": "moderate", "vmc_cipher": "strong",
    },
    "panic": {
        "regime_trend": "avoid", "monte_carlo_zones": "avoid", "confidence_scorer": "weak", "multi_tier_quality": "avoid",
        "bollinger_squeeze": "avoid", "funding_rate": "weak", "lead_lag": "avoid", "liquidation_cascade": "strong",
        "oi_delta": "strong", "probability_engine": "weak", "vmc_cipher": "avoid",
    },
    "high_volatility": {
        "regime_trend": "weak", "monte_carlo_zones": "moderate", "confidence_scorer": "moderate", "multi_tier_quality": "moderate",
        "bollinger_squeeze": "moderate", "funding_rate": "moderate", "lead_lag": "strong", "liquidation_cascade": "strong",
        "oi_delta": "strong", "probability_engine": "moderate", "vmc_cipher": "moderate",
    },
    "low_liquidity": {
        "regime_trend": "avoid", "monte_carlo_zones": "avoid", "confidence_scorer": "avoid", "multi_tier_quality": "avoid",
        "bollinger_squeeze": "avoid", "funding_rate": "avoid", "lead_lag": "avoid", "liquidation_cascade": "moderate",
        "oi_delta": "weak", "probability_engine": "avoid", "vmc_cipher": "avoid",
    },
    "news_dislocation": {
        "regime_trend": "avoid", "monte_carlo_zones": "weak", "confidence_scorer": "weak", "multi_tier_quality": "avoid",
        "bollinger_squeeze": "avoid", "funding_rate": "weak", "lead_lag": "moderate", "liquidation_cascade": "moderate",
        "oi_delta": "moderate", "probability_engine": "weak", "vmc_cipher": "avoid",
    },
    "consolidation": {
        "regime_trend": "weak", "monte_carlo_zones": "moderate", "confidence_scorer": "moderate", "multi_tier_quality": "moderate",
        "bollinger_squeeze": "strong", "funding_rate": "moderate", "lead_lag": "weak", "liquidation_cascade": "weak",
        "oi_delta": "moderate", "probability_engine": "moderate", "vmc_cipher": "strong",
    },
    "unknown": {
        "regime_trend": "weak", "monte_carlo_zones": "weak", "confidence_scorer": "moderate", "multi_tier_quality": "weak",
        "bollinger_squeeze": "moderate", "funding_rate": "moderate", "lead_lag": "moderate", "liquidation_cascade": "moderate",
        "oi_delta": "moderate", "probability_engine": "moderate", "vmc_cipher": "moderate",
    },
}


# ── Shared Memory Bus ────────────────────────────────────────────
# Pipeline scratchpad: upstream agents write, downstream agents read.
# Reset at the start of each pipeline run.

class PipelineScratchpad:
    """Per-pipeline-run shared memory between agents.

    The Regime Agent writes regime insights. The Trade Agent reads them.
    The Trade Agent writes decision rationale. The Risk/Critic Agent reads it.
    This creates a coherent chain of reasoning across agents.
    """

    def __init__(self):
        self._entries: List[Dict[str, Any]] = []
        self._created_at = time.time()

    def write(self, agent_role: str, key: str, value: Any) -> None:
        """Write a named value from an agent."""
        self._entries.append({
            "agent": agent_role,
            "key": key,
            "value": value,
            "ts": time.time(),
        })

    def read_all(self) -> List[Dict[str, Any]]:
        """Read all scratchpad entries (for downstream agents)."""
        return list(self._entries)

    def read_by_agent(self, agent_role: str) -> List[Dict[str, Any]]:
        """Read entries written by a specific agent."""
        return [e for e in self._entries if e["agent"] == agent_role]

    def read_by_key(self, key: str) -> Optional[Any]:
        """Read the most recent value for a key."""
        for entry in reversed(self._entries):
            if entry["key"] == key:
                return entry["value"]
        return None

    def to_compact_json(self, max_entries: int = 10) -> str:
        """Serialize recent entries for injection into agent prompts."""
        recent = self._entries[-max_entries:]
        compact = []
        for e in recent:
            compact.append(f"{e['agent']}: {e['key']}={json.dumps(e['value'], separators=(',', ':'))}")
        return " | ".join(compact) if compact else ""

    def clear(self) -> None:
        """Reset for next pipeline run."""
        self._entries.clear()
        self._created_at = time.time()


# ── Shared Lessons Store ─────────────────────────────────────────
# Cross-agent lessons that persist across pipeline runs.

class SharedLessons:
    """Lessons that apply to ALL agents, not just one specialist.

    Examples:
      - "SOL is highly correlated with BTC in trend regime" (Regime + Trade + Risk)
      - "Funding >0.04% ate 60% of edge on 4h holds" (Trade + Risk)
      - "Our confidence calibration is +0.12 overconfident" (Trade + Critic)
    """

    def __init__(self, max_lessons: int = 30):
        self._lessons: List[Dict[str, Any]] = []
        self._max = max_lessons

    def add(
        self,
        lesson: str,
        source_agent: str,
        applies_to: List[str],
        strength: str = "moderate",
    ) -> None:
        """Add a shared lesson.

        Args:
            lesson: The lesson text (max 200 chars).
            source_agent: Which agent discovered this.
            applies_to: Which agent roles should see it (e.g., ["trade", "risk"]).
            strength: "strong", "moderate", or "weak".
        """
        self._lessons.append({
            "lesson": lesson[:200],
            "source": source_agent,
            "applies_to": applies_to,
            "strength": strength,
            "ts": time.time(),
            "validation_count": 0,
        })
        # Keep within limit, removing oldest weak lessons first
        if len(self._lessons) > self._max:
            self._prune()

    def contradict(self, lesson_substring: str) -> None:
        """Record that a lesson was contradicted by an outcome.

        Decrements validation_count. Lessons with count < -3 are purged.
        """
        for l in self._lessons:
            if lesson_substring.lower() in l["lesson"].lower():
                l["validation_count"] = l.get("validation_count", 0) - 1
        # Purge lessons contradicted too many times
        self._lessons = [
            l for l in self._lessons
            if l.get("validation_count", 0) >= -3
        ]

    def validate(self, lesson_substring: str) -> None:
        """Record that a lesson was confirmed by an outcome."""
        for l in self._lessons:
            if lesson_substring.lower() in l["lesson"].lower():
                l["validation_count"] = l.get("validation_count", 0) + 1

    def get_for_agent(self, agent_role: str, max_lessons: int = 5) -> List[str]:
        """Get lessons relevant to a specific agent role."""
        relevant = [
            l for l in self._lessons
            if agent_role in l["applies_to"] or "all" in l["applies_to"]
        ]
        # Sort by strength (strong first), validation count, then recency
        strength_order = {"strong": 0, "moderate": 1, "weak": 2}
        relevant.sort(key=lambda l: (
            strength_order.get(l["strength"], 2),
            -l.get("validation_count", 0),
            -l["ts"],
        ))
        return [l["lesson"] for l in relevant[:max_lessons]]

    def _prune(self) -> None:
        """Remove invalidated and oldest weak lessons to stay within limit."""
        # First purge heavily contradicted lessons
        self._lessons = [
            l for l in self._lessons
            if l.get("validation_count", 0) >= -3
        ]
        if len(self._lessons) <= self._max:
            return
        # Keep all strong, trim weak/moderate by age
        strong = [l for l in self._lessons if l["strength"] == "strong"]
        others = [l for l in self._lessons if l["strength"] != "strong"]
        others.sort(key=lambda l: -l["ts"])  # Most recent first
        remaining_slots = self._max - len(strong)
        self._lessons = strong + others[:max(0, remaining_slots)]


# ── Context Builder ──────────────────────────────────────────────

def build_shared_context_block(
    agent_role: str,
    scratchpad: Optional[PipelineScratchpad] = None,
    shared_lessons: Optional[SharedLessons] = None,
    include_axioms: bool = True,
    include_regime_map: bool = False,
    include_strategy_theory: bool = False,
    current_regime: str = "",
) -> str:
    """Build a compact shared context block for an agent.

    This block is prepended to the agent's input JSON, giving it:
    - Market axioms (hard rules)
    - Upstream agent scratchpad entries
    - Shared lessons relevant to this agent
    - Regime-action mapping (if requested)
    - Strategy theory + regime fit (if requested)

    Returns a compact string to minimize token usage.
    """
    parts = []

    # Market axioms (compact)
    if include_axioms:
        axiom_block = "AXIOMS: " + " | ".join(MARKET_AXIOMS[:5])
        parts.append(axiom_block)

    # Upstream scratchpad
    if scratchpad:
        scratch_text = scratchpad.to_compact_json(max_entries=6)
        if scratch_text:
            parts.append(f"UPSTREAM: {scratch_text}")

    # Shared lessons for this agent
    if shared_lessons:
        lessons = shared_lessons.get_for_agent(agent_role, max_lessons=3)
        if lessons:
            parts.append("LESSONS: " + " | ".join(lessons))

    # Regime-action map (only for Trade and Critic agents who make action decisions)
    if include_regime_map:
        compact_map = {}
        for regime, mapping in REGIME_ACTION_MAP.items():
            compact_map[regime] = {
                "ok": mapping["acceptable_actions"],
                "no": mapping["forbidden_actions"],
                "sz": mapping["sizing_range"],
            }
        parts.append(f"REGIME_RULES: {json.dumps(compact_map, separators=(',', ':'))}")

    # Strategy theory: HOW/TRUST/FAIL + regime fit for current regime
    if include_strategy_theory:
        theory_lines = []
        for strat, info in STRATEGY_THEORY.items():
            short_name = strat.replace("_", "")[:8]
            theory_lines.append(f"{short_name}: {info['how']} Trust: {info['trust']} Fail: {info['fail']}")
        parts.append("STRAT_THEORY: " + " | ".join(theory_lines))

        # Regime-specific strategy trust mapping
        regime_key = current_regime.lower().strip() if current_regime else ""
        fit = STRATEGY_REGIME_FIT.get(regime_key)
        if fit:
            fit_str = ", ".join(f"{k}={v}" for k, v in fit.items())
            parts.append(f"REGIME_FIT({regime_key}): {fit_str}")

        # Confluence quality guide (compact)
        confl_lines = []
        for (s1, s2), desc in STRATEGY_CONFLUENCE.items():
            label = desc.split(" — ")[0]  # Just "convergent", "timeframe", "redundant"
            confl_lines.append(f"{s1[:5]}+{s2[:5]}={label}")
        parts.append("CONFLUENCE: " + ", ".join(confl_lines))

    return " || ".join(parts) if parts else ""


# ── Singleton instances ──────────────────────────────────────────

_shared_lessons: Optional[SharedLessons] = None
_pipeline_scratchpad: Optional[PipelineScratchpad] = None


def get_shared_lessons() -> SharedLessons:
    """Get or create the singleton SharedLessons store."""
    global _shared_lessons
    if _shared_lessons is None:
        _shared_lessons = SharedLessons(max_lessons=30)
    return _shared_lessons


def get_pipeline_scratchpad() -> PipelineScratchpad:
    """Get or create the pipeline scratchpad."""
    global _pipeline_scratchpad
    if _pipeline_scratchpad is None:
        _pipeline_scratchpad = PipelineScratchpad()
    return _pipeline_scratchpad


def reset_pipeline_scratchpad() -> PipelineScratchpad:
    """Reset the scratchpad for a new pipeline run."""
    global _pipeline_scratchpad
    _pipeline_scratchpad = PipelineScratchpad()
    return _pipeline_scratchpad


# ── Setup Type Helpers ──────────────────────────────────────────

def get_setup_confidence_boost(setup_type: str) -> float:
    """Get confidence boost for a recognized setup type.

    Returns 0.0 for unknown setup types.
    """
    st = SETUP_TYPES.get(setup_type)
    return st["confidence_boost"] if st else 0.0


def get_setup_historical_wr(setup_type: str) -> Optional[float]:
    """Get historical win rate for a setup type, or None if unknown."""
    st = SETUP_TYPES.get(setup_type)
    return st["historical_wr"] if st else None


def get_regime_metadata(regime: str) -> Dict[str, Any]:
    """Get extended metadata for a regime (win rate, duration, edge)."""
    return REGIME_METADATA.get(regime, {})


def get_funding_impact_level(rate_8h: float) -> str:
    """Classify funding rate impact.

    Args:
        rate_8h: 8-hour funding rate as decimal (e.g., 0.03 = 3%)

    Returns: Impact level string
    """
    abs_rate = abs(rate_8h)
    if abs_rate >= 0.08:
        return FUNDING_IMPACT["0.08+"]
    elif abs_rate >= 0.05:
        return FUNDING_IMPACT["0.05-0.08"]
    elif abs_rate >= 0.03:
        return FUNDING_IMPACT["0.03-0.05"]
    elif abs_rate >= 0.01:
        return FUNDING_IMPACT["0.01-0.03"]
    else:
        return FUNDING_IMPACT["0-0.01"]
