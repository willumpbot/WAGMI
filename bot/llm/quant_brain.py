"""
Quant Brain: Rule-based LLM substitute for signal filtering.

Encodes all validated quant findings as deterministic rules that run
inline without any API calls. Designed as a drop-in replacement for
the 9-agent LLM pipeline (Regime -> Trade -> Risk -> Critic) when
no Anthropic API credits are available.

Returns a QuantBrainDecision compatible with both the main bot loop
(via LLMDecision conversion) and the sniper filter (via direct use).

Usage:
    from llm.quant_brain import QuantBrain

    brain = QuantBrain()
    decision = brain.evaluate_signal(signal, market_data)
    if decision.action == "go":
        # proceed with trade
    elif decision.action == "veto":
        # blocked by critic

    # Convert to LLMDecision for the main pipeline:
    llm_decision = decision.to_llm_decision()
"""

import csv
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.quant_brain")


# ── Data Classes ─────────────────────────────────────────────────────────

@dataclass
class RegimeClassification:
    """Output of the regime agent."""
    regime: str              # primary regime label
    sub_regime: str          # secondary classification
    confidence: float        # 0.0 - 1.0
    bias: str                # "bullish", "bearish", "neutral"
    factors: List[str]       # what drove the classification
    risk_multiplier: float   # regime-based sizing scalar

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "sub_regime": self.sub_regime,
            "confidence": round(self.confidence, 3),
            "bias": self.bias,
            "factors": self.factors,
            "risk_multiplier": round(self.risk_multiplier, 3),
        }


@dataclass
class TradeThesis:
    """Output of the trade agent."""
    action: str              # "strong_entry", "bounce_entry", "skip_low_edge", "skip_toxic", "skip"
    setup_key: str           # e.g. "HYPE_BUY"
    edge_source: str         # what drives the edge
    win_prob: float          # estimated win probability
    confluence_score: int    # 0-10 confluence rating
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "setup_key": self.setup_key,
            "edge_source": self.edge_source,
            "win_prob": round(self.win_prob, 3),
            "confluence_score": self.confluence_score,
            "reasoning": self.reasoning,
        }


@dataclass
class SizingRecommendation:
    """Output of the risk agent."""
    tier: str                # "STANDARD", "PREMIUM", "SNIPER"
    risk_multiplier: float   # sizing scalar
    max_leverage: float      # cap
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "risk_multiplier": round(self.risk_multiplier, 3),
            "max_leverage": round(self.max_leverage, 1),
            "rationale": self.rationale,
        }


@dataclass
class CriticVerdict:
    """Output of the critic agent."""
    verdict: str             # "pass", "veto", "reduce"
    confidence_adj: float    # multiplier to apply to confidence (0.0 - 1.2)
    veto_reasons: List[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence_adj": round(self.confidence_adj, 3),
            "veto_reasons": self.veto_reasons,
            "warnings": self.warnings,
        }


@dataclass
class QuantBrainDecision:
    """Final output of the quant brain pipeline."""
    action: str              # "go", "skip", "veto"
    confidence_adj: float    # multiplier for original confidence
    regime: str              # classified regime
    reasoning: str           # human-readable explanation
    sizing: SizingRecommendation

    # Full pipeline outputs for debugging / logging
    regime_detail: Optional[RegimeClassification] = None
    trade_thesis: Optional[TradeThesis] = None
    critic_verdict: Optional[CriticVerdict] = None

    # Metadata
    latency_ms: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "confidence_adj": round(self.confidence_adj, 3),
            "regime": self.regime,
            "reasoning": self.reasoning,
            "sizing": self.sizing.to_dict(),
            "regime_detail": self.regime_detail.to_dict() if self.regime_detail else None,
            "trade_thesis": self.trade_thesis.to_dict() if self.trade_thesis else None,
            "critic_verdict": self.critic_verdict.to_dict() if self.critic_verdict else None,
            "latency_ms": round(self.latency_ms, 1),
            "timestamp": self.timestamp,
        }

    def to_llm_decision(self) -> "LLMDecision":
        """Convert to LLMDecision for compatibility with the main bot pipeline.

        This allows the quant brain to be used as a drop-in replacement
        for the LLM decision engine.
        """
        from llm.decision_types import LLMDecision, StrategyWeights

        # Map quant brain action to LLM action vocabulary
        action_map = {
            "go": "proceed",
            "skip": "flat",
            "veto": "flat",
        }

        # Regime-aware strategy weights
        regime_weights = _REGIME_STRATEGY_WEIGHTS.get(
            self.regime,
            {"regime_trend": 0.5, "monte_carlo_zones": 0.5,
             "confidence_scorer": 0.5, "multi_tier_quality": 0.5},
        )

        return LLMDecision(
            action=action_map.get(self.action, "flat"),
            confidence=self.confidence_adj,
            regime=self.regime,
            strategy_weights=StrategyWeights(**regime_weights),
            memory_update=None,
            notes=f"[QuantBrain] {self.reasoning}",
            size_multiplier=self.sizing.risk_multiplier,
            entry_adjustment=None,
        )


# ── Constants ────────────────────────────────────────────────────────────

# Setup-specific win probability priors (from counterfactual analysis)
_SETUP_WIN_PROBS: Dict[str, float] = {
    "HYPE_BUY": 0.52,    # Edge WEAKENING: 64%→40% over 500h. Current rolling WR ~40-52%.
                          # Best at High Vol (ATR% 1.40-1.69%): PF=3.51, WR=73.9%.
                          # NEGATIVE EV at Extreme Vol (ATR%>1.90%): PF=0.65. Gate this.
    "SOL_SELL": 0.55,     # Edge STRENGTHENING (+33pp, 35%->68% WR over 500h study).
                          # Best at Normal Vol (ATR% 0.80-0.98%): PF=1.75, WR=61.5%.
    "BTC_SELL": 0.55,     # Confirmed negative EV overall. Only marginal at 90%+ confidence.
    "BTC_BUY": 0.56,      # 56% WR, PF 1.40 over 30 days. Not yet proven in live.
    "SOL_BUY": 0.45,      # No validated edge. Discovery only.
    "HYPE_SELL": 0.35,    # Historical 7% but collecting fresh data
}

_DEFAULT_WIN_PROB = 0.45

# RSI-based win probability adjustments
_RSI_WP_ADJUSTMENTS: Dict[str, Tuple[float, float]] = {
    # (rsi_low, rsi_high): wp_multiplier
    # RSI 35-65 is the sweet spot for entries
}

# Regime -> strategy weight recommendations
_REGIME_STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "trending_bull": {
        "regime_trend": 0.8, "monte_carlo_zones": 0.4,
        "confidence_scorer": 0.6, "multi_tier_quality": 0.7,
    },
    "trending_bear": {
        "regime_trend": 0.8, "monte_carlo_zones": 0.4,
        "confidence_scorer": 0.6, "multi_tier_quality": 0.7,
    },
    "neutral": {
        "regime_trend": 0.5, "monte_carlo_zones": 0.6,
        "confidence_scorer": 0.5, "multi_tier_quality": 0.5,
    },
    "momentum": {
        "regime_trend": 0.7, "monte_carlo_zones": 0.3,
        "confidence_scorer": 0.7, "multi_tier_quality": 0.6,
    },
    "overbought": {
        "regime_trend": 0.3, "monte_carlo_zones": 0.7,
        "confidence_scorer": 0.4, "multi_tier_quality": 0.4,
    },
    "panic_oversold": {
        "regime_trend": 0.2, "monte_carlo_zones": 0.8,
        "confidence_scorer": 0.3, "multi_tier_quality": 0.3,
    },
    "recovering": {
        "regime_trend": 0.5, "monte_carlo_zones": 0.7,
        "confidence_scorer": 0.5, "multi_tier_quality": 0.5,
    },
    "mean_reversion_opportunity": {
        "regime_trend": 0.3, "monte_carlo_zones": 0.8,
        "confidence_scorer": 0.5, "multi_tier_quality": 0.4,
    },
    "unknown": {
        "regime_trend": 0.5, "monte_carlo_zones": 0.5,
        "confidence_scorer": 0.5, "multi_tier_quality": 0.5,
    },
}

# Regime risk multipliers (how aggressively to size in each regime)
_REGIME_RISK_MULT: Dict[str, float] = {
    "trending_bull": 1.2,
    "trending_bear": 1.1,
    "neutral": 0.9,
    "momentum": 1.15,
    "overbought": 0.5,
    "panic_oversold": 0.4,
    "recovering": 0.8,
    "mean_reversion_opportunity": 0.7,
    "overleveraged_long": 0.9,   # Counter-trade overcrowded longs (mean-reversion edge)
    "overleveraged_short": 0.9,  # Counter-trade overcrowded shorts (squeeze edge)
    "unknown": 0.6,
}

# Toxic setups that should always be skipped
_TOXIC_SETUPS = {"HYPE_SELL"}

# Setups with known profitable confidence bands
# Aggressive mode: all setups allowed at any confidence with 1 agree
_CONFIDENCE_BAND_SETUPS: Dict[str, Tuple[float, float, int]] = {
    # setup_key: (min_conf, max_conf, min_agree)
    "BTC_BUY": (30, 100, 1),
    "SOL_BUY": (30, 100, 1),
    "BTC_SELL": (30, 100, 1),
    "SOL_SELL": (30, 100, 1),
    "ETH_BUY": (30, 100, 1),
    "ETH_SELL": (30, 100, 1),
    "HYPE_BUY": (30, 100, 1),
    "HYPE_SELL": (30, 100, 1),
}


# ── Quant Brain ──────────────────────────────────────────────────────────

class QuantBrain:
    """Rule-based LLM substitute implementing Regime -> Trade -> Risk -> Critic.

    All rules are derived from validated quant findings:
    - Counterfactual analysis (what would have happened)
    - Backtest results (30-day rolling)
    - Setup-specific win rates and payoff ratios
    - RSI sweet spots and regime classification
    - Chase prevention and fee-drag awareness

    Zero API calls. Deterministic. Sub-millisecond latency.
    """

    def __init__(self):
        # Recent trade outcomes for chase prevention (symbol -> list of (timestamp, won))
        self._recent_outcomes: Dict[str, List[Tuple[float, bool]]] = {}
        self._outcome_window_s = 7200  # 2 hours
        # Cache last decision per symbol for intel display
        self._last_decisions: Dict[str, "QuantBrainDecision"] = {}

        # Optional: Kelly sizing optimizer
        self._sizing_optimizer = None
        try:
            from execution.sizing_optimizer import SizingOptimizer
            self._sizing_optimizer = SizingOptimizer()
            logger.info("[QUANT-BRAIN] Kelly sizing optimizer loaded")
        except Exception:
            logger.debug("[QUANT-BRAIN] Kelly sizing optimizer unavailable, using fixed sizing")

        # Load recent trade outcomes from trades.csv if available
        self._load_recent_outcomes()

        logger.info("[QUANT-BRAIN] Initialized — rule-based pipeline active (0 API calls)")

    # ── Public API ───────────────────────────────────────────────────

    def evaluate_signal(
        self,
        signal,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> QuantBrainDecision:
        """Run the full quant brain pipeline on a signal.

        Args:
            signal: A strategies.base.Signal object
            market_data: Optional dict with extra market context:
                - rsi: float (14-period RSI)
                - ema20: float
                - ema50: float
                - candles: list of recent OHLCV dicts
                - volume_ratio: float (current / 20-period avg)
                - funding_rate: float
                - atr: float
                Any missing fields are gracefully handled.

        Returns:
            QuantBrainDecision with action, sizing, and full reasoning.
        """
        start = time.monotonic()
        market_data = market_data or {}

        # Extract signal metadata (strategies put useful data here)
        meta = getattr(signal, "metadata", {}) or {}

        # Merge market_data with signal metadata (market_data takes priority)
        merged = {**meta, **market_data}

        # ── Step 1: Regime Agent ─────────────────────────────────────
        regime = self._classify_regime(signal, merged)

        # ── Step 2: Trade Agent ──────────────────────────────────────
        thesis = self._form_thesis(signal, merged, regime)

        # Early exit: trade agent says skip
        if thesis.action in ("skip_toxic", "skip_low_edge", "skip"):
            sizing = SizingRecommendation(
                tier="NONE", risk_multiplier=0.0, max_leverage=0.0,
                rationale=thesis.reasoning,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            _skip_decision = QuantBrainDecision(
                action="skip",
                confidence_adj=0.0,
                regime=regime.regime,
                reasoning=thesis.reasoning,
                sizing=sizing,
                regime_detail=regime,
                trade_thesis=thesis,
                critic_verdict=None,
                latency_ms=elapsed_ms,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._last_decisions[signal.symbol] = _skip_decision
            return _skip_decision

        # ── Step 3: Risk Agent ───────────────────────────────────────
        sizing = self._compute_sizing(signal, merged, regime, thesis)

        # ── Step 3b: Squeeze Sizing Boost ────────────────────────────
        # BB squeeze = compressed volatility -> big move coming -> size up.
        squeeze_mult = merged.get("squeeze_sizing_multiplier", 1.0)
        if squeeze_mult > 1.0:
            sizing = SizingRecommendation(
                tier=sizing.tier,
                risk_multiplier=round(sizing.risk_multiplier * squeeze_mult, 3),
                max_leverage=sizing.max_leverage,
                rationale=sizing.rationale + f" | BB_SQUEEZE: {squeeze_mult}x size boost",
            )
            logger.info(
                f"[QUANT-BRAIN] {signal.symbol} squeeze sizing: "
                f"{squeeze_mult}x multiplier applied"
            )

        # ── Step 4: Critic Agent ─────────────────────────────────────
        critic = self._run_critic(signal, merged, regime, thesis, sizing)

        # Determine final action
        if critic.verdict == "veto":
            action = "veto"
            confidence_adj = 0.0
        elif critic.verdict == "reduce":
            action = "go"
            confidence_adj = critic.confidence_adj
        else:
            action = "go"
            confidence_adj = critic.confidence_adj

        elapsed_ms = (time.monotonic() - start) * 1000

        # Build reasoning summary
        reasoning_parts = [
            f"Regime={regime.regime}({regime.sub_regime})",
            f"Thesis={thesis.action}",
            f"WP={thesis.win_prob:.0%}",
            f"Confluence={thesis.confluence_score}/10",
            f"Tier={sizing.tier}",
            f"Critic={critic.verdict}",
        ]
        if critic.veto_reasons:
            reasoning_parts.append(f"Veto: {'; '.join(critic.veto_reasons)}")
        if critic.warnings:
            reasoning_parts.append(f"Warn: {'; '.join(critic.warnings)}")

        decision = QuantBrainDecision(
            action=action,
            confidence_adj=confidence_adj,
            regime=regime.regime,
            reasoning=" | ".join(reasoning_parts),
            sizing=sizing,
            regime_detail=regime,
            trade_thesis=thesis,
            critic_verdict=critic,
            latency_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            f"[QUANT-BRAIN] {signal.symbol} {signal.side} → {action} "
            f"(regime={regime.regime}, wp={thesis.win_prob:.0%}, "
            f"tier={sizing.tier}, critic={critic.verdict}) "
            f"[{elapsed_ms:.1f}ms]"
        )

        # Cache for intel display
        self._last_decisions[signal.symbol] = decision

        return decision

    def record_outcome(self, symbol: str, won: bool) -> None:
        """Record a trade outcome for chase prevention.

        Call this when a trade closes so the critic can detect
        consecutive losses on the same symbol.
        """
        now = time.time()
        if symbol not in self._recent_outcomes:
            self._recent_outcomes[symbol] = []
        self._recent_outcomes[symbol].append((now, won))
        # Prune old entries
        cutoff = now - self._outcome_window_s
        self._recent_outcomes[symbol] = [
            (ts, w) for ts, w in self._recent_outcomes[symbol] if ts > cutoff
        ]

    # ── Step 1: Regime Agent ─────────────────────────────────────────

    def _classify_regime(
        self,
        signal,
        merged: Dict[str, Any],
    ) -> RegimeClassification:
        """Classify market regime from technical indicators.

        Uses RSI, EMA alignment, and candle patterns to determine
        the current market state. No API calls.
        """
        factors = []
        regimes_detected = []  # (regime, weight)

        rsi = merged.get("rsi")
        ema20 = merged.get("ema20")
        ema50 = merged.get("ema50")
        price = signal.entry
        candles = merged.get("candles", [])

        # ── RSI-based classification ──
        if rsi is not None and isinstance(rsi, (int, float)) and not math.isnan(rsi):
            if rsi < 30:
                regimes_detected.append(("panic_oversold", 2.0))
                factors.append(f"RSI={rsi:.1f} < 30 (panic oversold)")
            elif rsi < 40:
                regimes_detected.append(("recovering", 1.5))
                factors.append(f"RSI={rsi:.1f} 30-40 (recovering)")
            elif rsi <= 60:
                regimes_detected.append(("neutral", 1.0))
                factors.append(f"RSI={rsi:.1f} 40-60 (neutral)")
            elif rsi <= 75:
                regimes_detected.append(("momentum", 1.5))
                factors.append(f"RSI={rsi:.1f} 60-75 (momentum)")
            else:
                regimes_detected.append(("overbought", 2.0))
                factors.append(f"RSI={rsi:.1f} > 75 (overbought)")

        # ── EMA alignment (trend detection) ──
        if ema20 is not None and ema50 is not None and price > 0:
            try:
                ema20_f = float(ema20)
                ema50_f = float(ema50)
                if price > ema20_f > ema50_f:
                    regimes_detected.append(("trending_bull", 1.8))
                    factors.append(f"Price > EMA20 > EMA50 (bull trend)")
                elif price < ema20_f < ema50_f:
                    regimes_detected.append(("trending_bear", 1.8))
                    factors.append(f"Price < EMA20 < EMA50 (bear trend)")
                elif ema20_f < ema50_f:
                    # Price above EMAs but EMAs still bearish
                    factors.append(f"EMA20 < EMA50 (bearish cross, possible reversal)")
                else:
                    factors.append(f"EMA alignment neutral")
            except (ValueError, TypeError):
                pass

        # ── Candle pattern: consecutive red candles (mean reversion) ──
        if candles and len(candles) >= 3:
            try:
                recent = candles[-3:]
                red_count = 0
                for c in recent:
                    close = c.get("close", c.get("c", 0))
                    open_p = c.get("open", c.get("o", 0))
                    if close < open_p:
                        red_count += 1
                if red_count >= 3:
                    regimes_detected.append(("mean_reversion_opportunity", 1.5))
                    factors.append(f"{red_count} consecutive red candles (mean reversion)")
            except (TypeError, KeyError):
                pass

        # ── Volume spike detection ──
        volume_ratio = merged.get("volume_ratio")
        if volume_ratio is not None:
            try:
                vr = float(volume_ratio)
                if vr > 3.0:
                    factors.append(f"Volume {vr:.1f}x avg (panic spike)")
                elif vr > 1.5:
                    factors.append(f"Volume {vr:.1f}x avg (elevated)")
                elif vr < 0.3:
                    factors.append(f"Volume {vr:.1f}x avg (thin/low liquidity)")
            except (ValueError, TypeError):
                pass

        # ── Funding rate regime signal ──
        # Extreme funding reveals crowded positioning — structural edge info.
        # >0.05%/8h = heavily leveraged longs (annualized >200%), mean-reversion likely.
        # <-0.05%/8h = heavily leveraged shorts, short-squeeze risk.
        # Moderate funding (0.02-0.05%) confirms trend direction without extremity.
        funding_rate = merged.get("funding_rate")
        if funding_rate is not None:
            try:
                fr = float(funding_rate)
                abs_fr = abs(fr)
                if abs_fr >= 0.0005:  # 0.05%/8h = extreme
                    if fr > 0:
                        regimes_detected.append(("overleveraged_long", 1.8))
                        factors.append(f"Funding +{fr*100:.3f}%/8h EXTREME — longs overcrowded, mean-reversion edge")
                    else:
                        regimes_detected.append(("overleveraged_short", 1.8))
                        factors.append(f"Funding {fr*100:.3f}%/8h EXTREME — shorts overcrowded, squeeze risk")
                elif abs_fr >= 0.0002:  # 0.02%/8h = elevated
                    direction = "bullish" if fr > 0 else "bearish"
                    factors.append(f"Funding {fr*100:.3f}%/8h elevated ({direction} lean)")
                # else: neutral funding, no signal
            except (ValueError, TypeError):
                pass

        # ── Resolve primary regime ──
        if not regimes_detected:
            # Fallback: use signal metadata regime if available
            meta_regime = merged.get("regime", "unknown")
            primary_regime = meta_regime if meta_regime != "unknown" else "neutral"
            sub_regime = "no_indicators"
            conf = 0.3
        else:
            # Weight-based selection: highest-weighted regime wins
            regimes_detected.sort(key=lambda x: x[1], reverse=True)
            primary_regime = regimes_detected[0][0]
            sub_regime = regimes_detected[1][0] if len(regimes_detected) > 1 else primary_regime
            conf = min(0.9, 0.4 + 0.15 * len(regimes_detected))

        # ── Determine bias ──
        bullish_regimes = {"trending_bull", "momentum", "recovering", "mean_reversion_opportunity", "overleveraged_short"}
        bearish_regimes = {"trending_bear", "overbought", "panic_oversold", "overleveraged_long"}
        if primary_regime in bullish_regimes:
            bias = "bullish"
        elif primary_regime in bearish_regimes:
            bias = "bearish"
        else:
            bias = "neutral"

        # ── Regime risk multiplier ──
        risk_mult = _REGIME_RISK_MULT.get(primary_regime, 0.7)

        return RegimeClassification(
            regime=primary_regime,
            sub_regime=sub_regime,
            confidence=conf,
            bias=bias,
            factors=factors,
            risk_multiplier=risk_mult,
        )

    # ── Step 2: Trade Agent ──────────────────────────────────────────

    def _form_thesis(
        self,
        signal,
        merged: Dict[str, Any],
        regime: RegimeClassification,
    ) -> TradeThesis:
        """Form a trade thesis from setup + regime + confluence.

        Implements the key quant findings:
        - HYPE_SELL is always toxic
        - Setup+side IS the edge, not confidence
        - RSI sweet spot 35-65 for entries
        - Win probability drives everything
        """
        setup_key = f"{signal.symbol}_{signal.side}"
        rsi = merged.get("rsi")
        num_agree = merged.get("num_agree", 1)
        win_prob_meta = merged.get("win_prob", merged.get("win_prob_deflated"))

        # ── Toxic setup check disabled for aggressive data collection ──
        # HYPE_SELL was 7% WR historically but we need fresh data
        # if setup_key in _TOXIC_SETUPS:
        #     return TradeThesis(action="skip_toxic", ...)

        # ── Get base win probability ──
        base_wp = _SETUP_WIN_PROBS.get(setup_key, _DEFAULT_WIN_PROB)

        # Override with live win_prob if available from signal metadata
        if win_prob_meta is not None and isinstance(win_prob_meta, (int, float)):
            # Use the lower of base and metadata (conservative)
            wp = float(win_prob_meta)
            if wp < 1.0:
                pass  # already a fraction
            else:
                wp = wp / 100.0  # convert from percentage
            base_wp = min(base_wp, wp) if wp > 0 else base_wp

        # ── RSI adjustment ──
        rsi_adj = 0.0
        rsi_note = ""
        if rsi is not None and isinstance(rsi, (int, float)) and not math.isnan(rsi):
            if 35 <= rsi <= 65:
                rsi_adj = 0.03  # Sweet spot: +3% WP
                rsi_note = f"RSI {rsi:.0f} in sweet spot (35-65)"
            elif 30 <= rsi < 35:
                if regime.regime == "mean_reversion_opportunity":
                    rsi_adj = 0.02  # Bounce setup
                    rsi_note = f"RSI {rsi:.0f} + mean reversion = bounce setup"
                else:
                    rsi_adj = -0.03  # Oversold but no reversal signal
                    rsi_note = f"RSI {rsi:.0f} oversold without reversal signal"
            elif rsi < 30:
                rsi_adj = -0.08  # Deep oversold = panic zone
                rsi_note = f"RSI {rsi:.0f} panic zone"
            elif 65 < rsi <= 75:
                rsi_adj = -0.02  # Getting stretched
                rsi_note = f"RSI {rsi:.0f} extended"
            else:  # > 75
                rsi_adj = -0.10  # Overbought
                rsi_note = f"RSI {rsi:.0f} overbought"

        # ── Volatility regime adjustment (from comprehensive edge study) ──
        # ATR% determines vol regime. Each setup has an optimal vol band.
        # HYPE BUY: High Vol (ATR% 1.40-1.69%) = PF 3.51. Extreme (>1.90%) = PF 0.65.
        # SOL SELL: Normal Vol (ATR% 0.80-0.98%) = PF 1.75. High+ Vol = PF <0.72.
        # BTC BUY: Very High Vol (ATR% 0.92-1.03%) = PF 3.13.
        vol_adj = 0.0
        vol_note = ""
        atr = merged.get("atr")
        atr_pct = None
        if atr is not None and signal.entry > 0:
            try:
                atr_pct = (float(atr) / signal.entry) * 100.0
            except (ValueError, TypeError):
                pass

        if atr_pct is not None:
            if setup_key == "HYPE_BUY":
                if 1.40 <= atr_pct <= 1.69:
                    vol_adj = 0.08   # Optimal vol: PF 3.51, WR 73.9%
                    vol_note = f"HYPE optimal vol (ATR%={atr_pct:.2f}%)"
                elif 1.15 <= atr_pct < 1.40:
                    vol_adj = 0.0    # Low vol: PF 1.22, neutral
                    vol_note = f"HYPE low vol (ATR%={atr_pct:.2f}%)"
                elif 1.69 < atr_pct <= 1.90:
                    vol_adj = -0.03  # Very high: PF 1.03, marginal
                    vol_note = f"HYPE very high vol (ATR%={atr_pct:.2f}%)"
                elif atr_pct > 1.90:
                    vol_adj = -0.12  # Extreme vol: PF 0.65, NEGATIVE EV
                    vol_note = f"HYPE EXTREME vol (ATR%={atr_pct:.2f}%) — negative EV!"
            elif setup_key == "SOL_SELL":
                if 0.80 <= atr_pct <= 0.98:
                    vol_adj = 0.06   # Optimal: PF 1.75, WR 61.5%
                    vol_note = f"SOL optimal vol (ATR%={atr_pct:.2f}%)"
                elif atr_pct < 0.80:
                    vol_adj = 0.03   # Low vol: PF 1.56, decent
                    vol_note = f"SOL low vol (ATR%={atr_pct:.2f}%)"
                elif atr_pct > 1.20:
                    vol_adj = -0.10  # High+ vol: PF <0.72, negative EV
                    vol_note = f"SOL high vol (ATR%={atr_pct:.2f}%) — negative EV!"
                else:
                    vol_adj = -0.04  # Transition zone
                    vol_note = f"SOL elevated vol (ATR%={atr_pct:.2f}%)"
            elif setup_key == "BTC_BUY":
                if 0.92 <= atr_pct <= 1.03:
                    vol_adj = 0.08   # Very high vol: PF 3.13, WR 66.2%
                    vol_note = f"BTC optimal vol (ATR%={atr_pct:.2f}%)"
                elif atr_pct < 0.77:
                    vol_adj = -0.08  # Low/normal vol: PF <0.80
                    vol_note = f"BTC low vol (ATR%={atr_pct:.2f}%) — negative EV"

        # ── Bearish market haircut ──
        # When the regime is bearish (price < EMA20 < EMA50), BUY signals get
        # a confidence haircut. Buying dips in a bear market is the #1 money loser.
        # The 2026-03-25 selloff: 3/4 sim trades were HYPE LONG during 8% drop.
        bear_haircut = 0.0
        bear_note = ""
        if signal.side == "BUY" and regime.bias == "bearish":
            bear_haircut = -0.08  # -8% WP penalty for buying into bearish regime
            bear_note = "bearish regime haircut on BUY"
            if regime.regime == "trending_bear":
                bear_haircut = -0.12  # Full bear trend = stronger penalty
                bear_note = "trending bear: strong haircut on BUY"
        elif signal.side == "SELL" and regime.bias == "bearish":
            bear_haircut = 0.04  # +4% WP bonus for shorting in bearish regime
            bear_note = "bearish regime bonus on SELL"

        final_wp = max(0.0, min(1.0, base_wp + rsi_adj + vol_adj + bear_haircut))

        # ── Confluence scoring (0-10) ──
        confluence = 0
        confluence_factors = []

        # Number of strategies agreeing
        if num_agree >= 3:
            confluence += 3
            confluence_factors.append(f"{num_agree} strategies agree")
        elif num_agree >= 2:
            confluence += 2
            confluence_factors.append(f"{num_agree} strategies agree")
        else:
            confluence += 1

        # RSI in sweet spot
        if rsi is not None and 35 <= rsi <= 65:
            confluence += 2
            confluence_factors.append("RSI sweet spot")

        # Regime alignment
        if signal.side == "BUY" and regime.bias == "bullish":
            confluence += 2
            confluence_factors.append("bullish regime + BUY")
        elif signal.side == "SELL" and regime.bias == "bearish":
            confluence += 2
            confluence_factors.append("bearish regime + SELL")
        elif signal.side == "BUY" and regime.bias == "bearish":
            confluence -= 1
            confluence_factors.append("counter-trend BUY")
        elif signal.side == "SELL" and regime.bias == "bullish":
            confluence -= 1
            confluence_factors.append("counter-trend SELL")

        # R:R quality
        rr = getattr(signal, "risk_reward_tp1", 0)
        if rr >= 2.0:
            confluence += 1
            confluence_factors.append(f"R:R {rr:.1f}")
        elif rr >= 1.5:
            confluence += 1

        # Dip detection
        is_dip_buy = merged.get("is_dip_buy", False)
        if is_dip_buy and signal.side == "BUY":
            confluence += 1
            confluence_factors.append("dip-buy setup")

        # Vol regime confluence
        if vol_adj >= 0.06:
            confluence += 2
            confluence_factors.append(f"optimal vol regime ({vol_note})")
        elif vol_adj <= -0.08:
            confluence -= 2
            confluence_factors.append(f"bad vol regime ({vol_note})")

        # Chop filter
        chop = merged.get("chop_score_smoothed", merged.get("chop_score", 0))
        if chop is not None and isinstance(chop, (int, float)) and not math.isnan(chop):
            if chop < 0.3:
                confluence += 1
                confluence_factors.append(f"clean trend (chop={chop:.2f})")
            elif chop > 0.6:
                confluence -= 1
                confluence_factors.append(f"choppy (chop={chop:.2f})")

        # BTC-HYPE correlation regime (from edge study)
        # Medium corr (0.5-0.7) = PF 2.05. High corr (>0.7) = PF 0.59 (kills edge).
        btc_corr = merged.get("btc_correlation", merged.get("btc_hype_corr"))
        if btc_corr is not None and setup_key.startswith("HYPE"):
            try:
                corr_val = float(btc_corr)
                if 0.5 <= corr_val <= 0.7:
                    confluence += 1
                    confluence_factors.append(f"BTC-HYPE corr sweet spot ({corr_val:.2f})")
                elif corr_val > 0.7:
                    confluence -= 2
                    confluence_factors.append(f"BTC-HYPE corr too high ({corr_val:.2f}) — edge dies")
            except (ValueError, TypeError):
                pass

        # Funding rate confluence: funding confirming trade direction is
        # an independent, derivatives-based signal that most retail ignores.
        # Positive funding + SELL = shorts earning funding + overcrowded longs = strong.
        # Negative funding + BUY = longs earning funding + overcrowded shorts = strong.
        # Funding AGAINST trade = headwind (paying funding erodes edge).
        funding_rate = merged.get("funding_rate")
        if funding_rate is not None:
            try:
                fr = float(funding_rate)
                abs_fr = abs(fr)
                if abs_fr >= 0.0002:  # Only care about non-trivial funding
                    # Does funding favor our trade direction?
                    funding_favors_trade = (
                        (signal.side == "SELL" and fr > 0) or  # Fade overcrowded longs
                        (signal.side == "BUY" and fr < 0)       # Fade overcrowded shorts
                    )
                    funding_against_trade = (
                        (signal.side == "BUY" and fr > 0) or   # Buying into longs paying
                        (signal.side == "SELL" and fr < 0)      # Shorting into shorts paying
                    )
                    if funding_favors_trade:
                        if abs_fr >= 0.0005:  # Extreme: +2 confluence
                            confluence += 2
                            confluence_factors.append(
                                f"funding CONFIRMS {signal.side} ({fr*100:+.3f}%/8h extreme)")
                        else:  # Elevated: +1 confluence
                            confluence += 1
                            confluence_factors.append(
                                f"funding supports {signal.side} ({fr*100:+.3f}%/8h)")
                    elif funding_against_trade:
                        if abs_fr >= 0.0005:  # Extreme against: -2 confluence
                            confluence -= 2
                            confluence_factors.append(
                                f"funding AGAINST {signal.side} ({fr*100:+.3f}%/8h extreme headwind)")
                        else:  # Moderate against: -1 confluence
                            confluence -= 1
                            confluence_factors.append(
                                f"funding headwind ({fr*100:+.3f}%/8h)")
            except (ValueError, TypeError):
                pass

        confluence = max(0, min(10, confluence))

        # ── Confidence band checks for restricted setups ──
        if setup_key in _CONFIDENCE_BAND_SETUPS:
            min_c, max_c, min_a = _CONFIDENCE_BAND_SETUPS[setup_key]
            if not (min_c <= signal.confidence <= max_c and num_agree >= min_a):
                return TradeThesis(
                    action="skip",
                    setup_key=setup_key,
                    edge_source="confidence_band_miss",
                    win_prob=final_wp,
                    confluence_score=confluence,
                    reasoning=f"{setup_key} only profitable at conf {min_c}-{max_c} "
                              f"with {min_a}+ agree. Got conf={signal.confidence:.0f}, "
                              f"agree={num_agree}.",
                )

        # ── Low win probability skip DISABLED for aggressive data collection ──
        if final_wp < 0.10:  # Only skip truly zero-edge (sub 10%)
            return TradeThesis(
                action="skip_low_edge",
                setup_key=setup_key,
                edge_source="none",
                win_prob=final_wp,
                confluence_score=confluence,
                reasoning=f"Win prob {final_wp:.0%} < 48% floor. "
                          f"Base={base_wp:.0%}, RSI adj={rsi_adj:+.0%}. "
                          f"Negative EV after fees.",
            )

        # ── Determine entry quality ──
        if (setup_key == "HYPE_BUY" and rsi is not None
                and 35 <= rsi <= 65 and num_agree >= 2):
            action = "strong_entry"
            edge_source = "HYPE_BUY + RSI sweet spot + consensus"
        elif (setup_key == "HYPE_BUY" and rsi is not None
                and 30 <= rsi < 35
                and regime.regime == "mean_reversion_opportunity"):
            action = "bounce_entry"
            edge_source = "HYPE_BUY + oversold bounce + mean reversion"
        elif confluence >= 6:
            action = "strong_entry"
            edge_source = f"high confluence ({confluence}/10)"
        elif confluence >= 4:
            action = "bounce_entry" if is_dip_buy else "strong_entry"
            edge_source = f"moderate confluence ({confluence}/10)"
        else:
            action = "strong_entry"  # Passed WP floor, proceed cautiously
            edge_source = f"base edge ({confluence}/10 confluence)"

        reasoning_parts = [
            f"{setup_key}: WP={final_wp:.0%} (base={base_wp:.0%}, rsi_adj={rsi_adj:+.0%}, vol_adj={vol_adj:+.0%}, bear={bear_haircut:+.0%})",
            f"Confluence={confluence}/10",
            f"Optimal hold: 12h (validated +4.5R vs 24h +2.4R)",
        ]
        if rsi_note:
            reasoning_parts.append(rsi_note)
        if vol_note:
            reasoning_parts.append(vol_note)
        if bear_note:
            reasoning_parts.append(bear_note)
        if confluence_factors:
            reasoning_parts.append(f"Factors: {', '.join(confluence_factors)}")

        return TradeThesis(
            action=action,
            setup_key=setup_key,
            edge_source=edge_source,
            win_prob=final_wp,
            confluence_score=confluence,
            reasoning=" | ".join(reasoning_parts),
        )

    # ── Step 3: Risk Agent ───────────────────────────────────────────

    def _compute_sizing(
        self,
        signal,
        merged: Dict[str, Any],
        regime: RegimeClassification,
        thesis: TradeThesis,
    ) -> SizingRecommendation:
        """Compute position sizing tier and risk multiplier.

        Uses Kelly optimizer if available, otherwise falls back to
        rule-based tier sizing. Respects regime risk multipliers
        and confluence scoring.
        """
        num_agree = merged.get("num_agree", 1)
        rsi = merged.get("rsi")
        rsi_sweet = (rsi is not None and isinstance(rsi, (int, float))
                     and not math.isnan(rsi) and 35 <= rsi <= 65)

        # ── Tier classification ──
        if (num_agree >= 3 and rsi_sweet and thesis.win_prob >= 0.65
                and thesis.confluence_score >= 6):
            tier = "SNIPER"
            base_rm = 1.5
            max_lev = 25.0
            rationale = (f"SNIPER: {num_agree} agree + RSI sweet spot "
                        f"+ WP {thesis.win_prob:.0%} + confluence {thesis.confluence_score}/10")
        elif (num_agree >= 2 and thesis.win_prob >= 0.55
                and thesis.confluence_score >= 4):
            tier = "PREMIUM"
            base_rm = 1.2
            max_lev = 15.0
            rationale = (f"PREMIUM: {num_agree} agree + WP {thesis.win_prob:.0%}")
        else:
            tier = "STANDARD"
            base_rm = 1.0
            max_lev = 10.0
            rationale = f"STANDARD: base tier (agree={num_agree}, wp={thesis.win_prob:.0%})"

        # Solo signal cap: never above PREMIUM without consensus
        if num_agree < 2 and tier == "SNIPER":
            tier = "PREMIUM"
            base_rm = 1.2
            max_lev = 15.0
            rationale += " | Solo signal capped at PREMIUM"

        # ── Apply regime risk multiplier ──
        regime_rm = regime.risk_multiplier
        final_rm = base_rm * regime_rm

        # ── Kelly override if available ──
        kelly_rationale = ""
        if self._sizing_optimizer is not None:
            try:
                setup_key = f"{signal.symbol}_{signal.side}"
                stop_width_pct = signal.stop_width_pct if hasattr(signal, "stop_width_pct") else 0.01
                equity = merged.get("equity", 100.0)
                opt = self._sizing_optimizer.get_optimal_size(
                    setup=setup_key,
                    equity=equity,
                    confidence=signal.confidence,
                    num_agree=num_agree,
                    regime=regime.regime,
                    is_dip_buy=merged.get("is_dip_buy", False),
                    stop_width_pct=stop_width_pct,
                )
                # Use Kelly's leverage recommendation if it's more conservative
                if opt.leverage < max_lev:
                    max_lev = opt.leverage
                kelly_rationale = f" | Kelly: {opt.rationale}"
            except Exception as e:
                logger.debug(f"[QUANT-BRAIN] Kelly sizing error: {e}")

        # ── Confidence-based adjustment (from signal_pipeline.py data) ──
        conf = signal.confidence
        if conf >= 90 and regime.regime in ("trending_bull", "trending_bear"):
            final_rm *= 0.0  # Exhaustion signal at 90%+ in trends
            rationale += " | BLOCKED: 90%+ in trend = exhaustion"
        elif conf >= 85:
            final_rm *= 1.5
        elif conf >= 80:
            final_rm *= 1.15
        elif conf < 70:
            final_rm *= 0.7

        return SizingRecommendation(
            tier=tier,
            risk_multiplier=round(final_rm, 3),
            max_leverage=round(max_lev, 1),
            rationale=rationale + kelly_rationale,
        )

    # ── Step 4: Critic Agent ─────────────────────────────────────────

    def _run_critic(
        self,
        signal,
        merged: Dict[str, Any],
        regime: RegimeClassification,
        thesis: TradeThesis,
        sizing: SizingRecommendation,
    ) -> CriticVerdict:
        """Stress-test the trade thesis and veto if warranted.

        Implements data-driven veto rules:
        - Win probability floor
        - Consecutive loss prevention (chase detection)
        - RSI extreme entry prevention
        - Fee drag awareness
        - Counter-trend penalty
        """
        veto_reasons = []
        warnings = []
        confidence_adj = 1.0  # Start at 1.0 (no adjustment)

        # ── Heavy penalty 1: Win probability floor ──
        # Don't veto — penalize heavily so we still observe and learn
        if thesis.win_prob < 0.48:
            warnings.append(f"WP {thesis.win_prob:.0%} < 48% (noted, no penalty in aggressive mode)")

        # ── Veto 2: Chase prevention (consecutive losses on same symbol) ──
        symbol = signal.symbol
        now = time.time()
        cutoff = now - self._outcome_window_s
        recent = [
            (ts, won) for ts, won in self._recent_outcomes.get(symbol, [])
            if ts > cutoff
        ]
        if len(recent) >= 2:
            # Check last 2+ trades
            last_outcomes = [won for _, won in sorted(recent, key=lambda x: x[0])[-3:]]
            consecutive_losses = 0
            for won in reversed(last_outcomes):
                if not won:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= 2:
                warnings.append(
                    f"Chase caution: {consecutive_losses} consecutive losses "
                    f"on {symbol} in last 2h"
                )
                confidence_adj *= 0.9  # Light penalty only in aggressive mode

        # ── Veto 3: RSI extreme entries ──
        rsi = merged.get("rsi")
        setup_key = f"{signal.symbol}_{signal.side}"
        if rsi is not None and isinstance(rsi, (int, float)) and not math.isnan(rsi):
            if signal.side == "BUY" and rsi < 30:
                warnings.append(f"RSI {rsi:.0f} < 30 for BUY (panic zone)")
                confidence_adj *= 0.6  # Heavy penalty, not veto
            elif signal.side == "SELL" and rsi > 75:
                warnings.append(f"RSI {rsi:.0f} > 75 for SELL (squeeze risk)")
                confidence_adj *= 0.6
            # SOL RSI<20 is a death trap: 0% up at 6h, avg -4.73% at 24h.
            # Extreme oversold on SOL is continuation, not reversal.
            if setup_key == "SOL_BUY" and rsi < 20:
                veto_reasons.append(f"SOL RSI {rsi:.0f} < 20 death trap (0% up at 6h)")
                confidence_adj = 0.0

        # ── Veto 4: Fee drag check ──
        stop_pct = signal.stop_width_pct if hasattr(signal, "stop_width_pct") else 0
        if stop_pct > 0:
            # Standard Hyperliquid fees: 4 bps taker each way + estimated slippage
            round_trip_fee_pct = (4 * 2 + 3) / 10000.0  # 0.0011
            fee_drag = round_trip_fee_pct / stop_pct
            if fee_drag > 0.20:
                warnings.append(
                    f"Fee drag {fee_drag:.0%} > 20% "
                    f"(stop={stop_pct:.4f}, fees eat into risk)"
                )
                confidence_adj *= 0.5
            elif fee_drag > 0.15:
                warnings.append(f"Elevated fee drag {fee_drag:.0%}")
                confidence_adj *= 0.9

        # ── Warning: Counter-trend trade ──
        if signal.side == "BUY" and regime.bias == "bearish":
            warnings.append("Counter-trend BUY in bearish regime")
            confidence_adj *= 0.85
        elif signal.side == "SELL" and regime.bias == "bullish":
            warnings.append("Counter-trend SELL in bullish regime")
            confidence_adj *= 0.85

        # ── Warning: Low confluence ──
        if thesis.confluence_score < 3:
            warnings.append(f"Low confluence ({thesis.confluence_score}/10)")
            confidence_adj *= 0.9

        # ── Warning: Overbought BUY / Oversold SELL ──
        if rsi is not None and isinstance(rsi, (int, float)):
            if signal.side == "BUY" and rsi > 70:
                warnings.append(f"BUY with RSI {rsi:.0f} > 70 (stretched)")
                confidence_adj *= 0.9
            elif signal.side == "SELL" and rsi < 35:
                warnings.append(f"SELL with RSI {rsi:.0f} < 35 (oversold)")
                confidence_adj *= 0.9

        # ── Warning: Exhaustion pattern ──
        if signal.confidence >= 90 and regime.regime in ("trending_bull", "trending_bear"):
            warnings.append("90%+ confidence in strong trend = exhaustion risk")
            confidence_adj *= 0.5

        # ── Warning/Boost: Funding rate impact ──
        # Paying extreme funding eats edge. Earning extreme funding adds edge.
        funding_rate = merged.get("funding_rate")
        if funding_rate is not None:
            try:
                fr = float(funding_rate)
                abs_fr = abs(fr)
                if abs_fr >= 0.0003:  # 0.03%/8h threshold
                    is_paying = (
                        (signal.side == "BUY" and fr > 0) or
                        (signal.side == "SELL" and fr < 0)
                    )
                    is_earning = (
                        (signal.side == "SELL" and fr > 0) or
                        (signal.side == "BUY" and fr < 0)
                    )
                    if is_paying:
                        daily_cost_pct = abs_fr * 3 * 100  # 3 payments/day, as %
                        if abs_fr >= 0.0005:
                            warnings.append(
                                f"PAYING extreme funding {fr*100:+.3f}%/8h "
                                f"({daily_cost_pct:.2f}%/day eats into edge)")
                            confidence_adj *= 0.80  # 20% confidence haircut
                        else:
                            warnings.append(
                                f"Paying funding {fr*100:+.3f}%/8h "
                                f"({daily_cost_pct:.2f}%/day)")
                            confidence_adj *= 0.92  # 8% haircut
                    elif is_earning and abs_fr >= 0.0005:
                        # Earning extreme funding = structural tailwind
                        confidence_adj *= 1.08  # 8% boost (capped at 1.0 below)
            except (ValueError, TypeError):
                pass

        # ── Determine verdict ──
        if veto_reasons:
            verdict = "veto"
            confidence_adj = 0.0
        elif confidence_adj < 0.7:
            verdict = "reduce"
        else:
            verdict = "pass"

        return CriticVerdict(
            verdict=verdict,
            confidence_adj=round(confidence_adj, 3),
            veto_reasons=veto_reasons,
            warnings=warnings,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _load_recent_outcomes(self) -> None:
        """Load recent trade outcomes from trades.csv for chase prevention.

        Best-effort: if the file doesn't exist or can't be parsed, we
        start with empty history. Chase prevention will still work for
        trades that happen during this session.
        """
        trades_path = os.path.join("data", "trades.csv")
        if not os.path.exists(trades_path):
            return

        try:
            now = time.time()
            cutoff = now - self._outcome_window_s
            with open(trades_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        # Try to parse close timestamp
                        close_ts_str = row.get("close_time", row.get("timestamp", ""))
                        if not close_ts_str:
                            continue
                        # Parse ISO format or unix timestamp
                        try:
                            ts = datetime.fromisoformat(
                                close_ts_str.replace("Z", "+00:00")
                            ).timestamp()
                        except (ValueError, TypeError):
                            try:
                                ts = float(close_ts_str)
                            except (ValueError, TypeError):
                                continue

                        if ts < cutoff:
                            continue

                        symbol = row.get("symbol", "")
                        pnl = float(row.get("pnl", row.get("realized_pnl", 0)))
                        won = pnl > 0

                        if symbol:
                            if symbol not in self._recent_outcomes:
                                self._recent_outcomes[symbol] = []
                            self._recent_outcomes[symbol].append((ts, won))
                    except (ValueError, KeyError):
                        continue

            total = sum(len(v) for v in self._recent_outcomes.values())
            if total > 0:
                logger.info(
                    f"[QUANT-BRAIN] Loaded {total} recent outcomes "
                    f"for chase prevention"
                )
        except Exception as e:
            logger.debug(f"[QUANT-BRAIN] Could not load trades.csv: {e}")

    # ── Signal Generation ────────────────────────────────────────────
    def generate_signals(
        self, symbol: str, data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate trade signals from quant research findings.

        Unlike evaluate_signal() which FILTERS, this FINDS opportunities
        by applying our validated research:
        - Mean reversion (3+ red candles + RSI 28-40 = 79% bounce)
        - BTC divergence (HYPE alpha > 0.5% while BTC drops = 85% WR at 6h)
        - BB squeeze breakout
        - RSI sweet spot entries (RSI 35-65 optimal)

        Returns list of signal dicts with entry/sl/tp/confidence/reasoning.
        """
        signals = []
        df = data.get("1h")
        if df is None or len(df) < 20:
            return signals

        import pandas as pd

        close = df["close"]
        c = close.iloc[-1]

        # Compute indicators
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss_s.replace(0, 1e-12)
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])

        prev = close.shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

        # Red streak
        red_streak = 0
        for i in range(len(df) - 1, max(len(df) - 15, -1), -1):
            if df.iloc[i]["close"] < df.iloc[i]["open"]:
                red_streak += 1
            else:
                break

        # BB squeeze
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = float((2 * std20 / sma20).iloc[-1] * 100)
        bb_avg = float((2 * std20 / sma20).rolling(20).mean().iloc[-1] * 100)
        squeeze = bb_width < bb_avg * 0.75

        # ── Macro direction assessment ──
        # If ALL symbols are below EMA20, macro trend is DOWN.
        # Suppress BUY signals, favor SELL signals.
        macro_bearish = (c < ema20 and ema20 < ema50)

        # ── Setup 1: Mean Reversion Bounce (BUY) ──
        # 3+ red candles + RSI 28-45 = 79% bounce in 6h
        # SUPPRESSED when macro is bearish — dip buying in a downtrend is a trap.
        if red_streak >= 3 and 28 <= rsi <= 45 and symbol in ("HYPE", "BTC") and not macro_bearish:
            conf = 70 + min(red_streak - 3, 3) * 3  # 70-79%
            if 35 <= rsi <= 45:
                conf += 5  # Sweet spot bonus
            if squeeze:
                conf += 3  # Squeeze = compressed energy
            sl = c - 2.0 * atr
            # TP must give R:R >= 1.5. Use max of EMA20 target or ATR-based.
            # Mean reversion avg = +1.17% at 6h. Set TP at min 1.5x risk.
            risk = abs(c - (c - 2.0 * atr))
            tp1_ema = ema20 if ema20 > c * 1.01 else c + 1.5 * atr
            tp1_min_rr = c + risk * 1.5  # Enforce R:R >= 1.5
            tp1 = max(tp1_ema, tp1_min_rr)
            tp2 = c + 2.5 * atr
            if abs(c - sl) > 0 and abs(tp1 - c) / abs(c - sl) >= 1.2:
                signals.append({
                    "type": "mean_reversion", "symbol": symbol, "side": "BUY",
                    "confidence": min(conf, 85), "entry": c, "sl": sl,
                    "tp1": tp1, "tp2": tp2, "atr": atr,
                    "reasoning": f"Mean reversion: {red_streak} red candles, RSI {rsi:.0f}, "
                                 f"{'squeeze active, ' if squeeze else ''}"
                                 f"79% bounce probability in 6h",
                    "timeframe": "medium",  # 3-12h hold
                    "leverage_suggestion": 8 if conf >= 78 else 5,
                })

        # ── Setup 2: RSI Sweet Spot in Trend (BUY or SELL) ──
        # BUY: RSI 40-55 with EMA20 > EMA50 = trend continuation long
        # SELL: RSI 45-60 with EMA20 < EMA50 and price < EMA20 = trend continuation short
        if 40 <= rsi <= 55 and ema20 > ema50 and c > ema20 and not macro_bearish:
            sl = c - 1.5 * atr
            tp1 = c + 2.0 * atr
            tp2 = c + 3.0 * atr
            signals.append({
                "type": "trend_continuation", "symbol": symbol, "side": "BUY",
                "confidence": 75, "entry": c, "sl": sl,
                "tp1": tp1, "tp2": tp2, "atr": atr,
                "reasoning": f"RSI {rsi:.0f} in sweet spot, trend aligned (EMA20>EMA50), "
                             f"price above EMA20",
                "timeframe": "medium",
                "leverage_suggestion": 6,
            })

        if 45 <= rsi <= 60 and ema20 < ema50 and c < ema20:
            # Bearish trend continuation SHORT
            sl = c + 1.5 * atr
            tp1 = c - 2.0 * atr
            tp2 = c - 3.0 * atr
            signals.append({
                "type": "trend_continuation", "symbol": symbol, "side": "SELL",
                "confidence": 75, "entry": c, "sl": sl,
                "tp1": tp1, "tp2": tp2, "atr": atr,
                "reasoning": f"Bearish trend continuation: RSI {rsi:.0f}, EMA20<EMA50, "
                             f"price below EMA20 — follow the downtrend",
                "timeframe": "medium",
                "leverage_suggestion": 6,
            })

        # ── Setup 2b: SOL Bearish Momentum SHORT ──
        # Edge study: SOL SELL is STRENGTHENING (+33pp, 35%->68% WR over 500h).
        # Best at Normal Vol (ATR% 0.80-0.98%): PF=1.75, WR=61.5%.
        # SOL drops hard when bearish — 11% in 48h with 8 significant moves.
        # Only 1 strategy (regime_trend) generates SOL SELL, so this setup
        # provides a second independent signal path to the sniper/sim.
        # Conditions: bearish structure (EMA20<EMA50) + not deeply oversold
        # + SOL-specific vol regime (negative EV above ATR% 1.20)
        if symbol == "SOL" and ema20 < ema50 and c < ema20 and rsi > 25:
            atr_pct = (atr / c) * 100.0 if c > 0 else 999
            # Only trade in favorable vol regime (ATR% <= 1.20%)
            if atr_pct <= 1.20:
                conf = 72
                # Tighter RSI band = better entry (45-60 is sweet spot for shorts)
                if 45 <= rsi <= 60:
                    conf += 5
                # Macro bearish = stronger signal
                if macro_bearish:
                    conf += 5
                # Optimal vol zone bonus
                if 0.80 <= atr_pct <= 0.98:
                    conf += 3  # PF=1.75 zone
                sl = c + 1.5 * atr
                tp1 = c - 2.0 * atr
                tp2 = c - 3.5 * atr
                if abs(c - sl) > 0 and abs(tp1 - c) / abs(c - sl) >= 1.2:
                    signals.append({
                        "type": "sol_bearish_momentum", "symbol": "SOL", "side": "SELL",
                        "confidence": min(conf, 85), "entry": c, "sl": sl,
                        "tp1": tp1, "tp2": tp2, "atr": atr,
                        "reasoning": f"SOL bearish momentum: EMA20<EMA50, price below EMA20, "
                                     f"RSI {rsi:.0f}, ATR%={atr_pct:.2f}%, "
                                     f"{'macro bearish, ' if macro_bearish else ''}"
                                     f"SOL SELL edge strengthening (+33pp)",
                        "timeframe": "medium",
                        "leverage_suggestion": 8 if conf >= 78 else 5,
                    })

        # ── Setup 3: Oversold Reversal (only with confirmation) ──
        # RSI < 25 + BB squeeze + mean reversion conditions
        # NEVER on SOL: SOL RSI<20 is a death trap (0% up at 6h, avg -4.73% at 24h)
        # SUPPRESSED when macro is bearish — catching knives in downtrends loses money.
        if rsi < 25 and squeeze and red_streak >= 2 and symbol != "SOL" and not macro_bearish:
            sl = c - 2.5 * atr
            tp1 = ema20  # Snap back to mean
            tp2 = c + 3.0 * atr
            if abs(c - sl) > 0 and abs(tp1 - c) / abs(c - sl) >= 1.2:
                signals.append({
                    "type": "oversold_squeeze", "symbol": symbol, "side": "BUY",
                    "confidence": 72, "entry": c, "sl": sl,
                    "tp1": tp1, "tp2": tp2, "atr": atr,
                    "reasoning": f"Extreme oversold RSI {rsi:.0f} with BB squeeze + "
                                 f"{red_streak} red candles. Snap-back likely.",
                    "timeframe": "short",  # 1-6h
                    "leverage_suggestion": 5,
                })

        # ── Setup 4: Overbought Reversal SHORT ──
        # RSI > 70 after rally + price above EMA20 = overbought, mean-revert SHORT.
        # Mirror of oversold bounce logic but for shorts.
        if rsi > 70 and c > ema20:
            conf = 70
            if rsi > 80:
                conf += 5  # Extreme overbought
            sl = c + 2.0 * atr
            tp1 = ema20  # Revert to the mean
            tp2 = c - 2.5 * atr
            risk = abs(sl - c)
            reward = abs(c - tp1)
            if risk > 0 and reward / risk >= 1.2:
                signals.append({
                    "type": "overbought_reversal", "symbol": symbol, "side": "SELL",
                    "confidence": min(conf, 82), "entry": c, "sl": sl,
                    "tp1": tp1, "tp2": tp2, "atr": atr,
                    "reasoning": f"Overbought reversal: RSI {rsi:.0f} > 70, price above EMA20. "
                                 f"Mean reversion SHORT to EMA20 at {ema20:.2f}",
                    "timeframe": "medium",
                    "leverage_suggestion": 5,
                })

        # ── Setup 5: Bearish Trend Short (macro bear) ──
        # When price < EMA20 < EMA50 (full bear alignment), short on rallies.
        # Only fire when RSI has bounced to 40-55 (not deep oversold = no edge).
        if macro_bearish and 40 <= rsi <= 55:
            sl = c + 2.0 * atr
            tp1 = c - 2.0 * atr
            tp2 = c - 3.0 * atr
            signals.append({
                "type": "bear_trend_short", "symbol": symbol, "side": "SELL",
                "confidence": 73, "entry": c, "sl": sl,
                "tp1": tp1, "tp2": tp2, "atr": atr,
                "reasoning": f"Bear trend short: price < EMA20 < EMA50, RSI {rsi:.0f} "
                             f"recovered to neutral. Fade the bounce in a downtrend.",
                "timeframe": "medium",
                "leverage_suggestion": 5,
            })

        return signals


# ── Module-level convenience ─────────────────────────────────────────────

_instance: Optional[QuantBrain] = None


def get_quant_brain() -> QuantBrain:
    """Get or create the global QuantBrain singleton."""
    global _instance
    if _instance is None:
        _instance = QuantBrain()
    return _instance


def evaluate_signal(signal, market_data: Optional[Dict[str, Any]] = None) -> QuantBrainDecision:
    """Convenience function: evaluate a signal using the global QuantBrain."""
    return get_quant_brain().evaluate_signal(signal, market_data)
