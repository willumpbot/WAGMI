"""
Phase 3 Strategic Filters — Volatility-aware signal quality optimization.

Composed filters applied AFTER ensemble consensus but BEFORE risk/execution gates:
1. Strategy-specific confidence floors (not global)
2. Signal clustering detection (multi-strategy convergence)
3. Regime stability check (don't trade during transitions)
4. Volatility-dependent confidence scaling

These filters unlock trades in choppy markets while maintaining edge in trending markets.
Designed for May 6 market (70% hostile/choppy) → Phase 3 target: 30-50% WR (vs Phase 2 baseline 0% in choppy).
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

import pandas as pd

from .base import Signal

logger = logging.getLogger("bot.strategy.phase3_filters")


@dataclass
class Phase3FilterContext:
    """Context for all Phase 3 filter decisions."""
    symbol: str
    signal: Signal
    adx: float
    regime: str
    recent_signals: List[Signal]  # Last 30-min signals (for clustering)
    data: Dict[str, pd.DataFrame]

    @property
    def is_trending(self) -> bool:
        return self.adx > 25

    @property
    def is_medium_vol(self) -> bool:
        return 15 <= self.adx <= 25

    @property
    def is_choppy(self) -> bool:
        return self.adx < 15


class Phase3StrategySpecificFloors:
    """Filter 1: Strategy-specific confidence floors.

    Global confidence floors kill high-edge strategies in choppy markets.
    Phase 3 uses per-strategy thresholds validated from backtest:

    - bollinger_squeeze: 40% (80% WR in backtest, 67.6% shadow)
    - vmc_cipher: 35% (82% solo WR, highest edge)
    - monte_carlo_zones: 40% (74% WR at 60% confidence)
    - regime_trend: 45% (enabled Phase 3, low volume improvement)
    - confidence_scorer: 55% (foundational, conservative)
    """

    # Per-strategy minimum confidence thresholds (Phase 3 validated)
    STRATEGY_FLOORS = {
        "bollinger_squeeze": 40.0,
        "vmc_cipher": 35.0,
        "monte_carlo_zones": 40.0,
        "regime_trend": 45.0,
        "confidence_scorer": 55.0,
        "trend_breakout": 50.0,
        "multi_tier_quality": 50.0,
        "probability_engine": 45.0,
    }

    def evaluate(self, ctx: Phase3FilterContext) -> Tuple[bool, str]:
        """Check if signal passes strategy-specific confidence floor.

        Returns (passes, reason).
        """
        strategy = ctx.signal.strategy or ""
        floor = self.STRATEGY_FLOORS.get(strategy, 50.0)

        # Volatile assets: lower floors (natural price action is choppy)
        if ctx.symbol in ("HYPE",) and ctx.is_choppy:
            floor = floor - 5.0  # -5% floor in choppy, high-vol markets

        passes = ctx.signal.confidence >= floor
        reason = f"strategy_floor({strategy}={floor:.0f}%)" if passes else f"strategy_floor({strategy}={floor:.0f}%) FAILED"

        return passes, reason


class Phase3SignalClustering:
    """Filter 2: Detect multi-strategy signal convergence.

    In choppy markets, single high-confidence signals are valid ONLY if
    they align with recent signals (same direction, same symbol, <30min apart).

    Clustering = 2+ signals of same direction within 30min window.
    Reduces false entries in whipsaw regimes while allowing valid reversals.
    """

    CLUSTERING_WINDOW_S = 1800  # 30 minutes

    def detect_clustering(self, symbol: str, signal: Signal, recent: List[Signal]) -> Tuple[int, List[str]]:
        """Detect if recent signals cluster with this signal.

        Returns (num_aligned_signals, list_of_strategies).
        """
        aligned = []
        for prev in recent:
            if prev.symbol == symbol and prev.side == signal.side:
                # Recent signal in same direction → potential cluster
                aligned.append(prev.strategy or "unknown")

        return len(aligned), aligned

    def evaluate(self, ctx: Phase3FilterContext) -> Tuple[bool, str]:
        """Check if solo signal has clustering support.

        Rules:
        - 2+ strategies agree (consensus): PASS (already passed ensemble)
        - 1 strategy (solo) in trending (ADX > 25): PASS (trend is confirmation)
        - 1 strategy (solo) in medium vol (ADX 15-25): CHECK clustering
        - 1 strategy (solo) in choppy (ADX < 15): REQUIRE clustering
        """
        num_strategies = ctx.signal.metadata.get("num_agree", 1) if ctx.signal.metadata else 1

        if num_strategies >= 2:
            return True, "clustering_consensus(2+ strategies)"

        # Solo signal from trending market
        if ctx.is_trending:
            return True, "clustering_trend(ADX > 25)"

        # Solo signal: check recent clustering
        num_aligned, aligned_strats = self.detect_clustering(
            ctx.symbol, ctx.signal, ctx.recent_signals
        )

        if ctx.is_choppy:
            # Choppy: require clustering for confidence
            if num_aligned >= 1:
                return True, f"clustering_aligned({num_aligned} in {', '.join(set(aligned_strats))})"
            else:
                return False, "clustering_failed(solo in choppy, no recent alignment)"
        elif ctx.is_medium_vol:
            # Medium vol: clustering is a boost, not requirement
            if num_aligned >= 1:
                return True, f"clustering_supported({num_aligned} aligned)"
            else:
                # Solo in medium vol without clustering: still OK at high confidence
                if ctx.signal.confidence >= 65.0:
                    return True, "clustering_solo_high_confidence(65%+)"
                else:
                    return False, "clustering_solo_low_confidence(<65%)"

        return True, "clustering_default_pass"


class Phase3RegimeStabilityCheck:
    """Filter 3: Don't trade during uncertain regime transitions.

    Regime transitions create whipsaws. Wait for dominance > 60% confirmation
    before trading in newly-detected regimes.
    """

    DOMINANCE_THRESHOLD = 0.60

    def evaluate(self, ctx: Phase3FilterContext) -> Tuple[bool, str]:
        """Check if regime is stable enough to trade.

        Returns (passes, reason).
        """
        # Metadata should contain regime_dominance from regime detector
        dominance = ctx.signal.metadata.get("regime_dominance", 1.0) if ctx.signal.metadata else 1.0

        if dominance >= self.DOMINANCE_THRESHOLD:
            return True, f"regime_stable(dominance={dominance:.0%})"
        else:
            # Low dominance = uncertain regime transition
            # Only allow high-conviction signals through
            if ctx.signal.confidence >= 75.0:
                # Reduce sizing via metadata
                ctx.signal.metadata = ctx.signal.metadata or {}
                ctx.signal.metadata["regime_transition_penalty"] = 0.5
                return True, f"regime_transition_high_conviction(75%+, size=50%)"
            else:
                return False, f"regime_uncertain(dominance={dominance:.0%}, need {self.DOMINANCE_THRESHOLD:.0%})"


class Phase3VolatilityScaling:
    """Filter 4: Volatility-dependent confidence scaling.

    High-confidence signals in low-vol markets are more reliable than
    same confidence in high-vol markets (noise level varies).

    Scale floors inversely with ATR percentile to adapt to market conditions.
    """

    def evaluate(self, ctx: Phase3FilterContext) -> Tuple[float, str]:
        """Adjust confidence floor based on volatility.

        Returns (adjusted_floor, reason).

        Base floor from context. If high volatility, raise floor.
        If low volatility, lower floor (signals are higher quality).
        """
        # ATR percentile should be in metadata (0-100)
        atr_pctl = ctx.signal.metadata.get("atr_percentile", 50) if ctx.signal.metadata else 50

        # Adjust floor inversely with ATR
        # High ATR (e.g., 80th percentile) = raise floor 5-10%
        # Low ATR (e.g., 20th percentile) = lower floor 5-10%
        floor_adjustment = (atr_pctl - 50) * 0.20  # 0.2% adjustment per percentile point

        # Clamp adjustment to -10...+10%
        floor_adjustment = max(-10.0, min(10.0, floor_adjustment))

        reason = f"vol_scaling(ATR_pctl={atr_pctl:.0f}, adj={floor_adjustment:+.1f}%)"
        return floor_adjustment, reason


class Phase3FilterPipeline:
    """Compose all Phase 3 filters into a single decision point."""

    def __init__(self):
        self.strategy_floors = Phase3StrategySpecificFloors()
        self.clustering = Phase3SignalClustering()
        self.regime_stability = Phase3RegimeStabilityCheck()
        self.vol_scaling = Phase3VolatilityScaling()

    def evaluate(self, ctx: Phase3FilterContext) -> Tuple[bool, Dict[str, str]]:
        """Run all Phase 3 filters. Return (passes, breakdown).

        All filters must pass for signal to continue.
        """
        results = {}

        # Filter 1: Strategy-specific floors
        passes_floor, floor_reason = self.strategy_floors.evaluate(ctx)
        results["strategy_floor"] = floor_reason
        if not passes_floor:
            return False, results

        # Filter 2: Signal clustering
        passes_clustering, clustering_reason = self.clustering.evaluate(ctx)
        results["clustering"] = clustering_reason
        if not passes_clustering:
            return False, results

        # Filter 3: Regime stability
        passes_regime, regime_reason = self.regime_stability.evaluate(ctx)
        results["regime_stability"] = regime_reason
        if not passes_regime:
            return False, results

        # Filter 4: Volatility scaling (advisory, adjusts floor not blocks)
        vol_adjustment, vol_reason = self.vol_scaling.evaluate(ctx)
        results["vol_scaling"] = vol_reason

        # All filters passed
        return True, results


def apply_phase3_filters(
    signal: Optional[Signal],
    symbol: str,
    adx: float,
    regime: str,
    recent_signals: List[Signal],
    data: Dict[str, pd.DataFrame],
) -> Tuple[Optional[Signal], Dict[str, str]]:
    """Apply all Phase 3 filters to a consensus signal.

    Returns (filtered_signal or None, breakdown of filter decisions).

    Call this AFTER ensemble consensus but BEFORE risk/execution gates.
    """
    if signal is None:
        return None, {}

    ctx = Phase3FilterContext(
        symbol=symbol,
        signal=signal,
        adx=adx,
        regime=regime,
        recent_signals=recent_signals,
        data=data,
    )

    pipeline = Phase3FilterPipeline()
    passes, breakdown = pipeline.evaluate(ctx)

    if not passes:
        logger.info(
            f"[{symbol}] Signal REJECTED by Phase 3 filters: {breakdown}"
        )
        return None, breakdown

    # Attach filter metadata for debugging
    signal.metadata = signal.metadata or {}
    signal.metadata["phase3_filters"] = breakdown

    logger.info(
        f"[{symbol}] Signal PASSED Phase 3 filters: {breakdown}"
    )
    return signal, breakdown
