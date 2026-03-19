"""
Multi-strategy ensemble / voting system with quality gates.
Combines signals from all 4 strategies into consensus decisions.

Quality gates (applied to ALL modes):
1. Volume chop filter: skip if volume < 50% of 20-bar avg
2. Require 2+ strategies agreeing on same direction (weighted_veto)
3. Minimum 65% confidence after merge
4. Multi-TF trend consensus (5m+1h+6h+daily): aligned +3..+8, counter -8..-15

Modes:
- "voting": Require min_votes strategies to agree on side before trading.
  Confidence = average of agreeing strategies.
- "weighted_veto": Weight-aware voting with graduated veto.
  Chosen side must have veto_ratio × opposition strength.
- "weighted": Weight each strategy by historical performance.
  Combined confidence = weighted average.
- "best": Take the highest-confidence signal.
"""

import logging
from copy import deepcopy
from dataclasses import replace
from typing import Optional, Dict, Any, List

import pandas as pd

from .base import BaseStrategy, Signal
from core.filter_annotations import FilterAnnotation, AnnotatedSignal

logger = logging.getLogger("bot.strategy.ensemble")


class EnsembleStrategy:
    """
    Combines multiple strategies into a consensus signal.
    Not a BaseStrategy itself - it wraps multiple strategies.
    """

    def __init__(
        self,
        strategies: List[BaseStrategy],
        mode: str = "voting",
        min_votes: int = 2,
        weights: Optional[Dict[str, float]] = None,
        weight_manager=None,
        veto_ratio: float = 1.2,  # Lowered from 1.5: fee-drag + EV gates handle quality
        chop_detector=None,
        confidence_floor: float = 75.0,  # Raised from 65: minimum viable signal quality
        ranging_confidence_floor: float = 80.0,  # Lowered from 88: 88% was nearly impossible
        ic_tracker=None,
    ):
        self.strategies = strategies
        self.mode = mode
        self.min_votes = min_votes
        self.weights = weights or {s.name: 1.0 for s in strategies}
        self.weight_manager = weight_manager  # StrategyWeightManager instance
        self.ic_tracker = ic_tracker  # ICTracker: factor inversion protection
        self.veto_ratio = veto_ratio
        self.chop_detector = chop_detector  # ChopDetector instance (Wave 1)
        self.confidence_floor = confidence_floor
        self.ranging_confidence_floor = ranging_confidence_floor
        self._disabled_strategies: set = set()  # Strategy names to skip
        self._regime_profitability: Dict[str, Dict] = {}  # Push 3: regime WR data
        self._last_signals: Dict[str, Dict[str, Signal]] = {}  # symbol -> {strategy -> Signal}
        # Hysteresis: EMA-smoothed chop scores prevent floor oscillation on noise
        self._smoothed_chop: Dict[str, float] = {}  # symbol -> smoothed chop_score
        self._chop_ema_alpha: float = 0.3  # Smoothing factor (higher = more reactive)
        self._quality_scorer = None  # Optional: SignalQualityScorer for pre-floor adjustment
        self._shadow_ledger = None  # Optional: ShadowLedger for dormant strategy tracking
        # Rejection tracking: why signals were rejected (for LLM brain learning)
        self._last_rejections: Dict[str, Dict] = {}  # symbol -> {reason, confidence, side, ...}
        self._missed_trade_tracker = None  # Optional: MissedTradeTracker for feedback
        # Regime-aware min_votes: current regime per symbol (set externally by engine)
        self._current_regime: Dict[str, str] = {}  # symbol -> regime string (1h)
        self._current_regime_4h: Dict[str, str] = {}  # symbol -> regime string (4h)
        self._volatility_profiles: Dict[str, str] = {}  # symbol -> "low"/"medium"/"high"

    def set_quality_scorer(self, scorer):
        """Inject SignalQualityScorer so quality feedback affects ensemble confidence."""
        self._quality_scorer = scorer

    def set_shadow_ledger(self, ledger):
        """Inject ShadowLedger for tracking disabled strategy predictions."""
        self._shadow_ledger = ledger

    def set_missed_trade_tracker(self, tracker):
        """Inject MissedTradeTracker for comprehensive rejection feedback."""
        self._missed_trade_tracker = tracker

    def set_regime(self, symbol: str, regime: str):
        """Set the current 1h market regime for a symbol.

        Used for regime-aware min_votes: trending markets allow min_votes-1
        since trend direction provides strong confirmation.
        Regime values: 'trend', 'range', 'high_volatility', 'consolidation', 'unknown'
        """
        self._current_regime[symbol] = regime

    def set_regime_4h(self, symbol: str, regime_4h: str):
        """Set the 4h regime for multi-timeframe confirmation.

        When 1h regime disagrees with 4h, 2-agree signals require both to align.
        This prevents counter-trend entries where 1h calls 'bull' but 4h is still 'bear'.
        """
        self._current_regime_4h[symbol] = regime_4h

    # Compatible 1h/4h regime pairs: these mismatches are acceptable.
    _COMPATIBLE_REGIME_PAIRS = {
        ('consolidation', 'trending_bull'),
        ('trending_bull', 'consolidation'),
        ('consolidation', 'trend'),
        ('trend', 'consolidation'),
    }

    def _check_timeframe_alignment(self, symbol: str, agreement_level: int) -> bool:
        """Check if 1h and 4h regimes are aligned for trade entry.

        For 2-agree signals: require 1h AND 4h regime agreement (or compatible pair).
        For 3+ agree signals: 1h alone suffices — high conviction overrides.
        """
        if agreement_level >= 3:
            return True  # 3-agree: 1h alone suffices

        regime_1h = self._current_regime.get(symbol, "unknown")
        regime_4h = self._current_regime_4h.get(symbol)

        if regime_4h is None:
            return True  # No 4h data available — don't block

        if regime_1h == regime_4h:
            return True  # Perfect alignment

        if (regime_1h, regime_4h) in self._COMPATIBLE_REGIME_PAIRS:
            return True  # Acceptable mismatch

        logger.info(
            f"[{symbol}] 4h regime filter: 1h={regime_1h} vs 4h={regime_4h} — "
            f"blocking 2-agree entry (timeframe conflict)"
        )
        return False

    # Regime-gated min_votes: data-driven from 75-day backtest results.
    # trending_bear at 2-agree = -$25/trade × 96 trades = largest performance drag.
    # consolidation 2-agree = 80-89% WR = best regime.
    # Quant philosophy: trade more often with smaller size. Single high-conviction
    # strategy trades allowed in trending regimes (risk_mult=0.5 for 1-agree).
    # In backtest, funding_rate/oi_delta/liquidation_cascade return None (need live data).
    # Effective pool per regime is 3-5 strategies, not 9. Requiring 3/5 = 60% agreement
    # kills almost all signals. Lowered to 2 for regimes with 4+ active strategies.
    # High-risk regimes (panic, low_liquidity, news_dislocation) stay at 3.
    REGIME_MIN_VOTES = {
        'trending_bear':   2,
        'trending_bull':   2,
        'trend':           2,
        'consolidation':   2,
        'range':           2,
        'high_volatility': 2,
        'panic':           3,   # extreme regime: require conviction
        'low_liquidity':   3,   # thin book: require conviction
        'news_dislocation': 3,  # event-driven: require conviction
        'unknown':         2,
    }

    # Regime-specific strategy allowlist: only strategies with proven edge
    # in each regime are allowed to vote.
    # Regime-specific strategy allowlist: 9 active strategies, regime-gated.
    # New additions: liquidation_cascade, monte_carlo_zones, funding_rate, oi_delta
    STRATEGY_REGIME_ALLOWLIST = {
        'trending_bear':    {'confidence_scorer', 'regime_trend', 'bollinger_squeeze', 'vmc_cipher', 'probability_engine', 'oi_delta', 'liquidation_cascade'},
        'trending_bull':    {'confidence_scorer', 'regime_trend', 'bollinger_squeeze', 'vmc_cipher', 'probability_engine', 'oi_delta'},
        'trend':            {'confidence_scorer', 'regime_trend', 'bollinger_squeeze', 'vmc_cipher', 'probability_engine', 'oi_delta'},
        'consolidation':    {'confidence_scorer', 'multi_tier_quality', 'bollinger_squeeze', 'vmc_cipher', 'probability_engine', 'monte_carlo_zones', 'funding_rate'},
        'range':            {'confidence_scorer', 'multi_tier_quality', 'bollinger_squeeze', 'vmc_cipher', 'probability_engine', 'monte_carlo_zones', 'funding_rate'},
        'high_volatility':  {'confidence_scorer', 'probability_engine', 'bollinger_squeeze', 'liquidation_cascade', 'oi_delta'},
        'panic':            {'confidence_scorer', 'liquidation_cascade'},
        'low_liquidity':    {'confidence_scorer'},
        'news_dislocation': {'confidence_scorer'},
        'unknown':          {'confidence_scorer', 'probability_engine', 'monte_carlo_zones'},
    }

    def _get_effective_min_votes(self, symbol: str) -> int:
        """Get regime-aware min_votes for a symbol.

        Uses data-driven lookup table instead of blanket trending→min_votes-1.
        Bear regime at 2-agree was -$25/trade across 96 trades.
        Only regimes with proven positive EV at 2-agree get the reduction.
        """
        regime = self._current_regime.get(symbol, "unknown")
        return self.REGIME_MIN_VOTES.get(regime, 3)  # default to 3 — when in doubt, require conviction

    def set_symbol_volatility_profiles(self, profiles: Dict[str, str]):
        """Set volatility profiles for symbols (e.g., {"HYPE": "high", "BTC": "low"}).

        Used for per-symbol confidence floor capping: high-vol assets get lower
        max floors because their natural price action is inherently choppy.
        """
        self._volatility_profiles = profiles

    def set_disabled_strategies(self, names: set):
        """Temporarily disable specific strategies (e.g., for regime filtering)."""
        self._disabled_strategies = set(names)

    def get_last_signal(self, symbol: str, strategy_name: str) -> Optional[Signal]:
        """Get the last signal from a specific strategy for a symbol."""
        return self._last_signals.get(symbol, {}).get(strategy_name)

    # Map driving strategy → likely trade duration for TF weight selection.
    # Short-term strategies shouldn't get vetoed by daily bearish signals.
    STRATEGY_DURATION_MAP = {
        "multi_tier_quality": "MEDIUM",    # Uses 1h+6h → medium-term trades
        "confidence_scorer": "MEDIUM",     # ADX/MACD/squeeze momentum → medium-term
        "regime_trend": "TREND",           # Uses 1h+6h → trend following
        "monte_carlo_zones": "TREND",      # Uses daily → longer-term levels
        "bollinger_squeeze": "MEDIUM",     # BB squeeze/expansion → medium-term breakouts
        "funding_rate": "SCALP",           # Counter-trade extreme funding → short-term
        "lead_lag": "MEDIUM",              # BTC→alt catch-up → medium-term
        "liquidation_cascade": "SCALP",    # Post-cascade reversal → short-term
        "oi_delta": "MEDIUM",              # OI+price regime → medium-term
        "probability_engine": "TREND",     # Monte Carlo probability cones → trend
        "vmc_cipher": "MEDIUM",            # Multi-oscillator confluence → medium-term
    }

    # Strategy primary timeframe — used for duration-aware opposition penalty.
    # Daily-timeframe strategies penalize intraday signals less (and vice versa).
    STRATEGY_TIMEFRAME = {
        "multi_tier_quality": "intraday",   # 5m + 1h
        "confidence_scorer": "intraday",    # multi-factor, mostly 1h
        "regime_trend": "swing",            # 1h + 6h
        "monte_carlo_zones": "daily",       # daily zones
        "bollinger_squeeze": "intraday",    # BB on 1h candles
        "funding_rate": "intraday",         # Funding rate scalps
        "lead_lag": "intraday",             # BTC→alt lag on 1h
        "liquidation_cascade": "intraday",  # Cascade events on 1h
        "oi_delta": "intraday",             # OI changes on 1h
        "probability_engine": "swing",      # MC paths on 1h, forward-looking
        "vmc_cipher": "intraday",           # Multi-oscillator on 1h
    }

    # Max effective weight for any single strategy's opposition penalty.
    # Prevents a single bad strategy from swinging outcomes too much.
    MAX_OPPOSITION_WEIGHT = 0.8

    def _infer_duration(self, strategy_name: str) -> str:
        """Infer trade duration from the driving strategy."""
        return self.STRATEGY_DURATION_MAP.get(strategy_name, "")

    def _refresh_dynamic_weights(self):
        """Refresh ensemble weights using rolling strategy performance."""
        if self.weight_manager is not None:
            try:
                dynamic = self.weight_manager.get_rolling_weights()
                if dynamic:
                    self.weights = dynamic
                    # Log strategies that have been auto-muted
                    for name, w in dynamic.items():
                        if w <= 0.05:
                            logger.warning(
                                f"[ENSEMBLE] {name} effectively muted (weight={w}) "
                                f"-- sustained poor performance"
                            )
                else:
                    # Weights empty — likely no trade history yet.
                    # Try loading persisted weights from file as fallback.
                    # get_all_weights() reads from persisted file (smoothed, not rolling)
                    fallback = self.weight_manager.get_all_weights()
                    if fallback:
                        self.weights = fallback
                        logger.info(
                            "[ENSEMBLE] Loaded persisted strategy weights as fallback "
                            f"(no rolling data yet): {fallback}"
                        )
                        return
                    logger.warning(
                        "[ENSEMBLE] Dynamic strategy weights empty — using default equal weights. "
                        "Run a backtest with learning bridge to seed performance data."
                    )
            except Exception as e:
                logger.debug(f"Dynamic weight refresh failed: {e}")

    def get_all_required_timeframes(self) -> List[str]:
        """Get the union of all timeframes needed by all strategies."""
        tfs = set()
        for s in self.strategies:
            tfs.update(s.get_required_timeframes())
        return list(tfs)

    def apply_config_disables(self, config):
        """Apply strategy disable flags from TradingConfig.

        Strategies with proven negative edge are disabled via config flags
        but continue to generate shadow signals for IC tracking.
        """
        if hasattr(config, 'strategy_lead_lag_enabled') and not config.strategy_lead_lag_enabled:
            self._disabled_strategies.add('lead_lag')
        if hasattr(config, 'strategy_multi_tier_quality_enabled') and not config.strategy_multi_tier_quality_enabled:
            self._disabled_strategies.add('multi_tier_quality')

    def _get_regime_allowed_strategies(self, symbol: str) -> Optional[set]:
        """Get the set of strategies allowed in the current regime for this symbol.

        Returns None if no regime filter should be applied:
        - No regime has been set for this symbol
        - Regime is not in the allowlist lookup
        This ensures the filter only activates when we have explicit regime data.
        """
        if symbol not in self._current_regime:
            return None  # No regime set — don't filter
        regime = self._current_regime[symbol]
        allowed = self.STRATEGY_REGIME_ALLOWLIST.get(regime)
        # For 'unknown' regime, only filter if we actually have an empty set
        # (which means "block all"). If the regime isn't in the lookup, don't filter.
        if allowed is not None and len(allowed) == 0:
            # Only block all if regime was explicitly set (not just defaulting to unknown)
            return allowed
        return allowed

    def evaluate(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> Optional[Signal]:
        """
        Run all strategies and combine their signals.
        Returns a single consensus Signal or None.
        """
        # Dynamic weight refresh: pull rolling weights before each evaluation
        self._refresh_dynamic_weights()

        # Get regime-allowed strategies for this symbol
        regime_allowed = self._get_regime_allowed_strategies(symbol)

        signals: List[Signal] = []
        shadow_signals: List[Signal] = []  # Disabled strategy signals for IC tracking
        active_count = 0  # Strategies that ran (didn't error or get disabled)
        error_count = 0

        for strategy in self.strategies:
            # Config-disabled strategies: still generate shadow signals for IC tracking
            if strategy.name in self._disabled_strategies:
                try:
                    sig = strategy.evaluate(symbol, data)
                    if sig is not None:
                        shadow_signals.append(deepcopy(sig))
                        # Persist shadow signal for dormant strategy tracking
                        if self._shadow_ledger:
                            try:
                                self._shadow_ledger.record_shadow_signal(
                                    factor=sig.strategy,
                                    symbol=symbol,
                                    side=sig.side,
                                    confidence=sig.confidence,
                                    entry_price=sig.entry,
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
                continue

            # Regime-based strategy filter
            if regime_allowed is not None and strategy.name not in regime_allowed:
                continue
            active_count += 1
            try:
                sig = strategy.evaluate(symbol, data)
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                error_count += 1
                logger.warning(f"[{symbol}] {strategy.name} error: {e}")

        # Deep copy signals FIRST, then cache copies — prevents mutation between
        # cache write and copy if any code path modifies signals in-place.
        signals = [deepcopy(s) for s in signals]

        # Cache copies for context extraction (these won't be mutated further)
        self._last_signals[symbol] = {s.strategy: deepcopy(s) for s in signals}

        if not signals:
            return None

        # ── Regime-aware min_votes + graceful degradation ──
        # In trending regimes, reduce min_votes by 1 since trend confirmation is strong.
        effective_min_votes = self._get_effective_min_votes(symbol)
        if effective_min_votes != self.min_votes:
            logger.info(
                f"[{symbol}] Regime-aware min_votes: {self.min_votes} → {effective_min_votes} "
                f"(regime={self._current_regime.get(symbol, 'unknown')})"
            )
        # If strategies errored, lower min_votes so the system doesn't deadlock.
        if error_count > 0 and active_count > 0:
            degraded = max(2, min(effective_min_votes, active_count - error_count))
            if degraded != effective_min_votes:
                logger.info(
                    f"[{symbol}] Strategy degradation: {error_count} errors, "
                    f"min_votes {effective_min_votes} → {degraded}"
                )
                effective_min_votes = degraded

        # Chop detector: graduated choppy market filter
        # Instead of binary kill, attach chop_score and let the confidence floor
        # handle rejection. This allows high-conviction setups through even in chop.
        if self.chop_detector:
            is_chop, chop_score, chop_detail = self.chop_detector.is_choppy(symbol, data)
            # Attach chop score to metadata — graduated floor below will handle filtering
            for sig in signals:
                sig.metadata["chop_score"] = round(chop_score, 3)
            if is_chop:
                logger.info(
                    f"[{symbol}] Chop detected (score={chop_score:.2f}), "
                    f"applying graduated confidence floor"
                )
        elif self._is_low_volume(symbol, data):
            # Fallback to simple volume filter if no chop detector
            logger.info(f"[{symbol}] Signal skipped: low volume (chop filter)")
            if self._missed_trade_tracker is not None:
                self._missed_trade_tracker.record_ensemble_rejection(
                    symbol=symbol, signals=signals, reason="low_volume_chop"
                )
            return None

        if self.mode == "voting":
            result = self._voting(symbol, signals, effective_min_votes)
        elif self.mode == "weighted_veto":
            result = self._weighted_veto(symbol, signals, effective_min_votes)
        elif self.mode == "weighted":
            result = self._weighted(symbol, signals)
        elif self.mode == "best":
            result = self._best(symbol, signals)
        else:
            result = self._voting(symbol, signals, effective_min_votes)

        if result is None:
            return None

        # ── 4h regime confirmation filter (B2) ──
        # For 2-agree signals, require 1h and 4h regime alignment.
        # Prevents counter-trend entries where 1h calls 'bull' but 4h is still 'bear'.
        agreement_level = result.metadata.get("num_agree", 1) if result.metadata else 1
        if not self._check_timeframe_alignment(symbol, agreement_level):
            self._last_rejections[symbol] = {
                "reason": "4h_regime_conflict",
                "regime_1h": self._current_regime.get(symbol, "unknown"),
                "regime_4h": self._current_regime_4h.get(symbol, "unknown"),
                "agreement_level": agreement_level,
            }
            if self._missed_trade_tracker is not None:
                try:
                    self._missed_trade_tracker.record_rejection(
                        signal=result, reason="4h_regime_conflict", gate="ensemble"
                    )
                except Exception:
                    pass
            return None

        # ── Pre-floor quality adjustment ──
        # Apply signal quality feedback to ensemble confidence BEFORE the floor check.
        # This lets historically bad setups get rejected even with high raw confidence.
        if self._quality_scorer is not None:
            try:
                from feedback.signal_quality import QualityFeatures
                features = QualityFeatures(
                    confidence=result.confidence,
                    num_strategies_agree=result.metadata.get("num_agree", 1),
                    total_strategies=len(self.strategies),
                    symbol=symbol,
                    side=result.side,
                )
                _adj, _mult, _breakdown = self._quality_scorer.adjust_confidence(
                    result.confidence, features
                )
                # Bound multiplier to 0.5-1.3 (same as SignalQualityScorer range)
                _mult = max(0.5, min(1.3, _mult))
                if abs(_mult - 1.0) > 0.01:
                    result.confidence = max(0, min(100, result.confidence * _mult))
                    result.metadata["quality_multiplier"] = round(_mult, 3)
                    logger.info(
                        f"[{symbol}] Quality adjustment: *{_mult:.2f} -> "
                        f"conf={result.confidence:.1f}%"
                    )
            except Exception as e:
                logger.debug(f"Quality scorer error: {e}")

        # ── Post-merge quality gates ──

        # 0. Graduated rules: apply learned rules from validated hypotheses
        try:
            from llm.graduated_rules import get_graduated_rules_engine
            _gre = get_graduated_rules_engine()
            _regime = result.metadata.get("regime", "")
            _setup = result.metadata.get("entry_type", "")
            _n_agree = result.metadata.get("num_agree", 1)
            _vetoed, _adj_conf, _rule_summary = _gre.evaluate_signal(
                symbol=symbol, regime=_regime, side=result.side,
                strategy=result.strategy or "", setup_type=_setup,
                num_agree=_n_agree, confidence=result.confidence,
            )
            if _vetoed:
                logger.info(f"[{symbol}] Signal VETOED by graduated rule: {_rule_summary}")
                self._record_counterfactual(result, "graduated_rule_veto")
                return None
            if _adj_conf != result.confidence:
                logger.info(f"[{symbol}] Graduated rules: {result.confidence:.0f}% → {_adj_conf:.0f}% ({_rule_summary})")
                result.confidence = _adj_conf
                result.metadata["graduated_rule_adj"] = _rule_summary
        except Exception:
            pass

        # 1. Minimum confidence floor — regime-aware
        # In choppy markets, require much higher confidence to trade.
        # 100d backtest: ranging regime = 24% WR, trending = 100% WR.
        effective_floor = self.confidence_floor
        raw_chop = result.metadata.get("chop_score", 0)
        # Apply EMA smoothing to prevent floor oscillation on noise
        prev = self._smoothed_chop.get(symbol, raw_chop)
        chop_score = self._chop_ema_alpha * raw_chop + (1 - self._chop_ema_alpha) * prev
        self._smoothed_chop[symbol] = chop_score
        result.metadata["chop_score_smoothed"] = round(chop_score, 3)
        if chop_score > 0.35:
            if chop_score >= 0.65:
                # Extreme chop: floor rises from ranging toward max.
                # High-vol assets get lower max: their natural price action is choppy.
                _vol_profile = getattr(self, '_volatility_profiles', {}).get(symbol, "medium")
                _max_chop_floor = {"low": 90.0, "medium": 87.0, "high": 83.0}.get(_vol_profile, 90.0)
                chop_intensity = min(1.0, (chop_score - 0.65) / 0.20)  # 0→1 over 0.65→0.85
                effective_floor = self.ranging_confidence_floor + chop_intensity * (
                    _max_chop_floor - self.ranging_confidence_floor
                )
            else:
                # Moderate chop: interpolate between normal and ranging floor
                chop_intensity = (chop_score - 0.35) / 0.30  # 0→1 over 0.35→0.65
                effective_floor = self.confidence_floor + chop_intensity * (
                    self.ranging_confidence_floor - self.confidence_floor
                )
            result.metadata["effective_confidence_floor"] = round(effective_floor, 1)

        if result.confidence < effective_floor:
            logger.info(
                f"[{symbol}] Signal rejected: confidence {result.confidence:.0f}% "
                f"< {effective_floor:.0f}% floor (chop={chop_score:.2f})"
            )
            self._record_counterfactual(result, f"confidence_floor_{effective_floor:.0f}")
            return None

        # 2. Trend alignment: FLIP counter-trend signals to ride the trend
        # Use duration-aware weights: short-term strategies don't get killed
        # by daily bearish signals, and long-term strategies don't flip on 5m noise.
        _driver = result.strategy or ""
        _duration_hint = self._infer_duration(_driver)
        result = self._trend_alignment_adjust(symbol, data, result, _duration_hint)

        if result is None:
            logger.info(f"[{symbol}] Signal rejected by trend alignment (counter-trend)")
            return None

        # Re-check floor after adjustment (should rarely fail now since we flip instead of crush)
        if result.confidence < effective_floor:
            logger.info(
                f"[{symbol}] Signal rejected: confidence {result.confidence:.0f}% "
                f"< {effective_floor:.0f}% after trend adjustment"
            )
            self._record_counterfactual(result, f"trend_adj_floor_{effective_floor:.0f}")
            return None

        return result

    def evaluate_with_annotations(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> Optional[AnnotatedSignal]:
        """Run ensemble evaluation with soft-filter annotations instead of hard rejections.

        Returns an AnnotatedSignal with filter assessments attached, or None if
        no strategies produced any signal at all (nothing to annotate).

        Filters converted to annotations:
        - Confidence floor (normal, chop, ranging)
        - Trend alignment rejection
        - Volume/chop gating

        Hard rejects (min_votes not met) still return None since there's no
        meaningful signal to annotate.
        """
        # Dynamic weight refresh
        self._refresh_dynamic_weights()

        signals: List[Signal] = []
        active_count = 0
        error_count = 0

        for strategy in self.strategies:
            if strategy.name in self._disabled_strategies:
                continue
            active_count += 1
            try:
                sig = strategy.evaluate(symbol, data)
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                error_count += 1
                logger.warning(f"[{symbol}] {strategy.name} error: {e}")

        signals = [deepcopy(s) for s in signals]
        self._last_signals[symbol] = {s.strategy: deepcopy(s) for s in signals}

        if not signals:
            return None

        # Regime-aware min_votes + degradation
        effective_min_votes = self._get_effective_min_votes(symbol)
        if error_count > 0 and active_count > 0:
            effective_min_votes = max(2, min(effective_min_votes, active_count - error_count))

        # Chop detection — attach scores but don't reject
        annotations: List[FilterAnnotation] = []
        chop_score = 0.0

        if self.chop_detector:
            is_chop, chop_score, chop_detail = self.chop_detector.is_choppy(symbol, data)
            for sig in signals:
                sig.metadata["chop_score"] = round(chop_score, 3)
            if is_chop:
                annotations.append(FilterAnnotation(
                    gate="chop_floor",
                    passed=False,
                    severity="warning" if chop_score < 0.65 else "reject",
                    value=round(chop_score, 3),
                    threshold=0.65,
                    detail=f"chop={chop_score:.2f}",
                ))
        elif self._is_low_volume(symbol, data):
            annotations.append(FilterAnnotation(
                gate="volume_chop",
                passed=False,
                severity="reject",
                value=0.0,
                threshold=0.5,
                detail="low volume",
            ))

        # Run voting/merge — if min_votes not met, no signal to annotate
        if self.mode == "voting":
            result = self._voting(symbol, signals, effective_min_votes)
        elif self.mode == "weighted_veto":
            result = self._weighted_veto(symbol, signals, effective_min_votes)
        elif self.mode == "weighted":
            result = self._weighted(symbol, signals)
        elif self.mode == "best":
            result = self._best(symbol, signals)
        else:
            result = self._voting(symbol, signals, effective_min_votes)

        if result is None:
            # Not enough votes — nothing meaningful to annotate
            return None

        # Quality adjustment (same as evaluate())
        if self._quality_scorer is not None:
            try:
                from feedback.signal_quality import QualityFeatures
                features = QualityFeatures(
                    confidence=result.confidence,
                    num_strategies_agree=result.metadata.get("num_agree", 1),
                    total_strategies=len(self.strategies),
                    symbol=symbol,
                    side=result.side,
                )
                _adj, _mult, _breakdown = self._quality_scorer.adjust_confidence(
                    result.confidence, features
                )
                _mult = max(0.5, min(1.3, _mult))
                if abs(_mult - 1.0) > 0.01:
                    result.confidence = max(0, min(100, result.confidence * _mult))
                    result.metadata["quality_multiplier"] = round(_mult, 3)
            except Exception as e:
                logger.debug(f"Quality scorer error: {e}")

        # ── Soft-annotated confidence floor ──
        effective_floor = self.confidence_floor
        raw_chop = result.metadata.get("chop_score", 0)
        prev = self._smoothed_chop.get(symbol, raw_chop)
        smoothed_chop = self._chop_ema_alpha * raw_chop + (1 - self._chop_ema_alpha) * prev
        self._smoothed_chop[symbol] = smoothed_chop
        result.metadata["chop_score_smoothed"] = round(smoothed_chop, 3)

        if smoothed_chop > 0.35:
            if smoothed_chop >= 0.65:
                _vol_profile = getattr(self, '_volatility_profiles', {}).get(symbol, "medium")
                _max_chop_floor = {"low": 90.0, "medium": 87.0, "high": 83.0}.get(_vol_profile, 90.0)
                chop_intensity = min(1.0, (smoothed_chop - 0.65) / 0.20)
                effective_floor = self.ranging_confidence_floor + chop_intensity * (
                    _max_chop_floor - self.ranging_confidence_floor
                )
            else:
                chop_intensity = (smoothed_chop - 0.35) / 0.30
                effective_floor = self.confidence_floor + chop_intensity * (
                    self.ranging_confidence_floor - self.confidence_floor
                )
            result.metadata["effective_confidence_floor"] = round(effective_floor, 1)

        conf_passed = result.confidence >= effective_floor
        annotations.append(FilterAnnotation(
            gate="confidence_floor",
            passed=conf_passed,
            severity="reject" if not conf_passed else "ok",
            value=round(result.confidence, 1),
            threshold=round(effective_floor, 1),
            detail=f"conf={result.confidence:.0f} vs floor={effective_floor:.0f} (chop={smoothed_chop:.2f})",
        ))

        # ── Soft-annotated trend alignment ──
        _driver = result.strategy or ""
        _duration_hint = self._infer_duration(_driver)
        trend_result = self._trend_alignment_adjust(symbol, data, deepcopy(result), _duration_hint)

        if trend_result is None:
            annotations.append(FilterAnnotation(
                gate="trend_alignment",
                passed=False,
                severity="reject",
                value=0.0,
                threshold=0.0,
                detail="counter-trend rejected",
            ))
            # Use original result (not None) so LLM can see the signal
            result.metadata["trend_rejected"] = True
        else:
            # Trend may have adjusted confidence
            trend_score = trend_result.metadata.get("trend_score", 0)
            result = trend_result
            annotations.append(FilterAnnotation(
                gate="trend_alignment",
                passed=True,
                severity="ok" if trend_score >= 0 else "warning",
                value=round(trend_score, 1) if trend_score else 0.0,
                threshold=0.0,
                detail=f"trend={trend_score:+.1f}" if trend_score else "trend=ok",
            ))
            # Re-check confidence after trend adjustment
            if result.confidence < effective_floor:
                # Don't kill — already annotated above
                result.metadata["post_trend_below_floor"] = True

        # Build filter metadata from result
        filter_meta = dict(result.metadata) if result.metadata else {}
        filter_meta["num_strategies_signaled"] = len(signals)
        filter_meta["num_strategies_active"] = active_count

        return AnnotatedSignal(
            signal=result,
            annotations=annotations,
            hard_rejected=False,
            filter_metadata=filter_meta,
        )

    def _record_counterfactual(self, signal, skip_reason: str):
        """Record a rejected signal for counterfactual analysis (missed opportunity tracking)."""
        # Store for LLM brain visibility via signal digest
        self._last_rejections[signal.symbol] = {
            "reason": skip_reason,
            "side": signal.side,
            "confidence": round(signal.confidence, 1),
            "strategy": signal.strategy or "",
            "regime": signal.metadata.get("regime", ""),
        }
        # MissedTradeTracker: comprehensive rejection feedback (backtest + live)
        if self._missed_trade_tracker is not None:
            try:
                self._missed_trade_tracker.record_rejection(
                    signal=signal,
                    reason=skip_reason,
                    gate="ensemble",
                )
            except Exception:
                pass
        try:
            from llm.brain_wiring import record_skipped_trade
            record_skipped_trade(
                symbol=signal.symbol,
                side=signal.side,
                entry_price=signal.entry,
                sl=signal.sl,
                tp1=signal.tp1,
                tp2=signal.tp2,
                confidence=signal.confidence,
                skip_reason=skip_reason,
                strategy=signal.strategy or "",
                regime=signal.metadata.get("regime", ""),
            )
        except Exception:
            pass  # Non-critical — don't let tracking break trading

    def _is_low_volume(self, symbol: str, data: Dict[str, pd.DataFrame]) -> bool:
        """Check if current volume is too low for reliable signals.
        Returns True if volume < 50% of 20-bar average (choppy market)."""
        df_1h = data.get("1h")
        if df_1h is None or df_1h.empty or len(df_1h) < 20:
            return False  # can't determine, allow trading
        vol = df_1h["volume"]
        avg_vol = float(vol.tail(20).mean())
        if avg_vol <= 0:
            return False
        current_vol = float(vol.iloc[-1])
        ratio = current_vol / avg_vol
        if ratio < 0.5:
            logger.info(f"[{symbol}] Volume ratio {ratio:.2f} (current={current_vol:.0f}, avg={avg_vol:.0f})")
            return True
        return False

    # Default timeframe weights: higher TFs matter more for trend determination.
    # 5m noise should NOT cancel out a confirmed daily trend.
    TIMEFRAME_WEIGHTS = {"5m": 0.5, "1h": 1.0, "6h": 1.5, "daily": 2.0}

    # Trade-duration-aware weights: short trades care about short TFs,
    # long trades care about long TFs. A daily bearish signal shouldn't
    # kill a clean 5m scalp setup.
    DURATION_WEIGHTS = {
        "SCALP":  {"5m": 2.0, "1h": 1.0, "6h": 0.3, "daily": 0.1},
        "MEDIUM": {"5m": 0.8, "1h": 1.5, "6h": 1.0, "daily": 0.5},
        "TREND":  {"5m": 0.3, "1h": 0.8, "6h": 1.5, "daily": 2.0},
        "REGIME": {"5m": 0.2, "1h": 0.5, "6h": 1.5, "daily": 2.0},
    }

    def _compute_trend_scores(self, symbol: str, data: Dict[str, pd.DataFrame],
                              entry_type: str = ""):
        """Compute weighted multi-timeframe trend scores.
        Returns (total_score, num_timeframes, detail_string).
        Score range varies by weight set.

        Each timeframe's raw score (±1) is multiplied by its weight.
        If entry_type is provided, uses duration-aware weights so that
        short trades prioritize short TFs and long trades prioritize long TFs.
        """
        # Use duration-aware weights if entry_type matches, else default
        tf_weights = self.DURATION_WEIGHTS.get(entry_type, self.TIMEFRAME_WEIGHTS)
        scores = []
        weights = []
        details = []

        # ── 5m: fast momentum (weight: 0.5) ──
        df_5m = data.get("5m")
        if df_5m is not None and not df_5m.empty and len(df_5m) >= 50:
            c = df_5m["close"].astype(float)
            e20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
            e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            s = 1 if e20 > e50 else -1
            scores.append(s)
            weights.append(tf_weights["5m"])
            details.append(f"5m={'B' if s > 0 else 'S'}")

        # ── 1h: core trend + MACD momentum (weight: 1.0) ──
        df_1h = data.get("1h")
        if df_1h is not None and not df_1h.empty and len(df_1h) >= 50:
            c = df_1h["close"].astype(float)
            e20 = c.ewm(span=20, adjust=False).mean()
            e50 = c.ewm(span=50, adjust=False).mean()
            ema_bull = float(e20.iloc[-1]) > float(e50.iloc[-1])

            # MACD direction (12/26/9)
            e12 = c.ewm(span=12, adjust=False).mean()
            e26 = c.ewm(span=26, adjust=False).mean()
            macd_line = e12 - e26
            macd_signal = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = float((macd_line - macd_signal).iloc[-1])
            macd_bull = macd_hist > 0

            if ema_bull and macd_bull:
                s = 1
            elif not ema_bull and not macd_bull:
                s = -1
            else:
                s = 0
            scores.append(s)
            weights.append(tf_weights["1h"])
            details.append(f"1h={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        # ── 6h: higher timeframe structure (weight: 1.5) ──
        df_6h = data.get("6h")
        if df_6h is not None and not df_6h.empty and len(df_6h) >= 20:
            c = df_6h["close"].astype(float)
            e20 = c.ewm(span=20, adjust=False).mean()
            e50 = c.ewm(span=50, min_periods=10, adjust=False).mean()
            price = float(c.iloc[-1])
            ema50_val = float(e50.iloc[-1])
            ema_bull = float(e20.iloc[-1]) > ema50_val
            price_above = price > ema50_val
            s = 1 if (ema_bull and price_above) else (-1 if (not ema_bull and not price_above) else 0)
            scores.append(s)
            weights.append(tf_weights["6h"])
            details.append(f"6h={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        # ── Daily: macro trend + RSI (weight: 2.0) ──
        df_d = data.get("daily")
        if df_d is not None and not df_d.empty and len(df_d) >= 50:
            c = df_d["close"].astype(float)
            sma50 = float(c.rolling(50).mean().iloc[-1])
            price = float(c.iloc[-1])

            delta = c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = float((100 - 100 / (1 + rs)).iloc[-1])

            price_bull = price > sma50
            rsi_bull = rsi > 50
            if price_bull and rsi_bull:
                s = 1
            elif not price_bull and not rsi_bull:
                s = -1
            else:
                s = 0
            scores.append(s)
            weights.append(tf_weights["daily"])
            details.append(f"D={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        # Weighted total: weights vary by trade duration (entry_type)
        total = sum(s * w for s, w in zip(scores, weights)) if scores else 0
        n = len(scores)
        detail_str = " ".join(details)
        return total, n, detail_str

    def _trend_alignment_adjust(
        self, symbol: str, data: Dict[str, pd.DataFrame], result: "Signal",
        entry_type: str = ""
    ) -> "Signal":
        """Multi-timeframe trend alignment: flip or boost signals.

        Uses duration-aware WEIGHTED scores so trade-relevant timeframes dominate.
        For SCALP: 5m (2.0) + 1h (1.0) dominate, daily (0.1) barely matters.
        For TREND: daily (2.0) + 6h (1.5) dominate, 5m (0.3) barely matters.
        Default (no entry_type): daily (2.0) dominates per original behavior.

        Strong trend (score >= 2.5):
          - Counter-trend → FLIP side, recalculate levels, +5 bonus
          - Aligned → +8 bonus
        Moderate trend (score >= 1.0):
          - Counter-trend → FLIP side, recalculate levels, +0 (neutral)
          - Aligned → +3 bonus
        Neutral (< 1.0): no adjustment
        """
        total, n, detail_str = self._compute_trend_scores(symbol, data, entry_type)

        if n == 0:
            return result

        side = result.side
        is_buy = side == "BUY"

        # Thresholds adjusted for weighted scoring (max ±5.0 instead of ±4)
        # Trend bonuses are MULTIPLICATIVE to prevent confidence inflation.
        # Strong alignment: 1.06x (70→74.2)  Mild alignment: 1.03x (70→72.1)
        if abs(total) >= 2.5:
            trend_bullish = total > 0
            if is_buy == trend_bullish:
                # Aligned with strong trend — multiplicative bonus
                old_conf = result.confidence
                result.confidence = min(100, result.confidence * 1.06)
                adj = round(result.confidence - old_conf, 1)
                result.metadata["trend_adjustment"] = adj
                logger.info(
                    f"[{symbol}] Strong trend aligned {side}: "
                    f"score={total:.1f}/{n} [{detail_str}] *1.06 (+{adj:.1f})"
                )
            else:
                # Strong counter-trend — FLIP the signal (returns new object)
                # No confidence bonus: flipped signals have zero original strategy
                # conviction in the new direction. Let them prove themselves.
                result = self._flip_signal(symbol, result, data)
                result.metadata["trend_adjustment"] = 0
                result.metadata["trend_flipped"] = True
                logger.info(
                    f"[{symbol}] FLIP {side}->{result.side}: strong trend "
                    f"score={total:.1f}/{n} [{detail_str}] -- sniper mode"
                )
        elif abs(total) >= 1.5:
            # Raised threshold from 1.0 to 1.5 — moderate trend
            trend_bullish = total > 0
            if is_buy == trend_bullish:
                # Mild alignment — small multiplicative bonus
                old_conf = result.confidence
                result.confidence = min(100, result.confidence * 1.03)
                adj = round(result.confidence - old_conf, 1)
                result.metadata["trend_adjustment"] = adj
                logger.info(
                    f"[{symbol}] Trend aligned {side}: "
                    f"score={total:.1f}/{n} [{detail_str}] *1.03 (+{adj:.1f})"
                )
            else:
                # Moderate counter-trend — penalize but don't reject.
                # Rejection kills valid shorts during bear market bounces.
                old_conf = result.confidence
                result.confidence = max(0, result.confidence * 0.90)  # 10% penalty
                adj = round(result.confidence - old_conf, 1)
                result.metadata["trend_adjustment"] = adj
                result.metadata["trend_counter"] = True
                logger.info(
                    f"[{symbol}] Counter-trend {side} penalized: moderate trend "
                    f"score={total:.1f}/{n} [{detail_str}] *0.90 ({adj:.1f})"
                )
        else:
            result.metadata["trend_adjustment"] = 0
            logger.info(f"[{symbol}] Neutral trend: score={total:.1f}/{n} [{detail_str}]")

        return result

    def _flip_signal(
        self, symbol: str, signal: "Signal", data: Dict[str, pd.DataFrame]
    ) -> "Signal":
        """Flip a signal's direction: BUY→SELL or SELL→BUY.
        Returns a NEW Signal object — never mutates the original.
        Uses asymmetric ATR multiples for minimum 1.5:1 R:R on TP1."""
        entry = signal.entry
        atr = signal.atr

        if atr <= 0:
            # Estimate ATR from 1h data if not available
            df_1h = data.get("1h")
            if df_1h is not None and not df_1h.empty and len(df_1h) >= 14:
                prev = df_1h["close"].shift(1)
                tr = pd.concat([
                    df_1h["high"] - df_1h["low"],
                    (df_1h["high"] - prev).abs(),
                    (df_1h["low"] - prev).abs(),
                ], axis=1).max(axis=1)
                atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
            else:
                atr = entry * 0.02  # fallback: 2% of price

        # Asymmetric levels: SL tight (1.2 ATR), TP1 wide (2.4 ATR) = 2:1 R:R
        # This ensures flipped signals are worth taking after fees.
        if signal.side == "BUY":
            new_side = "SELL"
            sl = entry + 1.2 * atr
            tp1 = entry - 2.4 * atr
            tp2 = entry - 4.8 * atr
        else:
            new_side = "BUY"
            sl = entry - 1.2 * atr
            tp1 = entry + 2.4 * atr
            tp2 = entry + 4.8 * atr

        # Return a NEW Signal — never mutate the original (downstream may reference it)
        return replace(
            signal,
            side=new_side,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={**signal.metadata, "flipped_from": signal.side},
        )

    def _voting(self, symbol: str, signals: List[Signal],
                effective_min_votes: int = 0) -> Optional[Signal]:
        """Require min_votes strategies to agree on direction.
        Opposition veto: if any strategy actively votes the opposite side,
        require min_votes + len(opposition) to override."""
        min_v = effective_min_votes or self.min_votes
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        # Determine which side has enough base votes
        buy_enough = len(buy_signals) >= min_v
        sell_enough = len(sell_signals) >= min_v

        if buy_enough and sell_enough:
            # Both sides have min_votes - break tie using weighted confidence
            buy_w = self._weighted_confidence_sum(buy_signals)
            sell_w = self._weighted_confidence_sum(sell_signals)
            if buy_w > sell_w:
                chosen, opposition = buy_signals, sell_signals
            elif sell_w > buy_w:
                chosen, opposition = sell_signals, buy_signals
            else:
                return None  # tied
        elif buy_enough:
            chosen, opposition = buy_signals, sell_signals
        elif sell_enough:
            chosen, opposition = sell_signals, buy_signals
        else:
            return None

        # Opposition veto: if strategies actively disagree, raise the bar
        if opposition:
            required = min_v + len(opposition)
            if len(chosen) < required:
                logger.info(
                    f"[{symbol}] Signal vetoed: {len(chosen)} {chosen[0].side} vs "
                    f"{len(opposition)} {opposition[0].side} (need {required} votes)"
                )
                return None

        merged = self._merge_signals(symbol, chosen)
        if merged is None:
            return None

        # Confidence penalty for opposition, weighted by opposer's confidence.
        # Previously flat 10pts per opposer regardless of their conviction.
        if opposition:
            penalty = sum(s.confidence / 100 * 8 for s in opposition)
            merged.confidence = max(0, merged.confidence - penalty)
            merged.metadata["opposition_penalty"] = round(penalty, 1)
            logger.info(
                f"[{symbol}] Opposition penalty: -{penalty} confidence "
                f"(opposed by {[s.strategy for s in opposition]})"
            )

        return merged

    def _weighted_veto(self, symbol: str, signals: List[Signal],
                       effective_min_votes: int = 0) -> Optional[Signal]:
        """Weight-aware voting with graduated veto.
        Uses strategy accuracy weights * confidence to determine direction.
        Requires chosen side to have veto_ratio times the opposition's strength.
        Minimum min_votes strategies must agree on the same side for a trade."""
        min_v = effective_min_votes or self.min_votes
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        # Require at least min_votes strategies agreeing on the same direction.
        # Single-strategy trades (1-agree) require 80%+ confidence from a proven strategy.
        if len(buy_signals) < min_v and len(sell_signals) < min_v:
            # Check for single-strategy high-conviction trade (quant cherry-pick mode)
            single_conf_threshold = 80.0
            lone_signals = buy_signals or sell_signals
            if min_v <= 1 and len(lone_signals) == 1 and lone_signals[0].confidence >= single_conf_threshold:
                logger.info(
                    f"[{symbol}] Single-strategy high-conviction {lone_signals[0].side}: "
                    f"{lone_signals[0].strategy} conf={lone_signals[0].confidence:.0f}% (quant cherry-pick)"
                )
                # Allow it through — EV gate + half-size risk_mult will handle safety
            else:
                if buy_signals:
                    logger.info(f"[{symbol}] Only {len(buy_signals)} BUY signal(s), need {min_v}+ same-side")
                elif sell_signals:
                    logger.info(f"[{symbol}] Only {len(sell_signals)} SELL signal(s), need {min_v}+ same-side")
                if self._missed_trade_tracker is not None:
                    self._missed_trade_tracker.record_ensemble_rejection(
                        symbol=symbol, signals=signals, reason="insufficient_votes"
                    )
                return None

        # Block known-losing combos (backtest-validated toxic combinations).
        # Only block when 3+ strategies agree and the toxic pair is a subset —
        # if the toxic pair are the ONLY voters, blocking guarantees zero trades.
        _LOSING_COMBOS = {
            frozenset({"confidence_scorer", "multi_tier_quality"}),              # PF 0.08 — genuinely toxic
        }
        for side_signals in [buy_signals, sell_signals]:
            if len(side_signals) >= 2:
                signal_names = frozenset(s.strategy for s in side_signals)
                for blocked in _LOSING_COMBOS:
                    # Only block when a 3rd strategy also voted — exact-match
                    # means these were the only option, so let them through.
                    if blocked.issubset(signal_names) and signal_names != blocked:
                        logger.info(
                            f"[{symbol}] Blocked losing combo {sorted(blocked)} "
                            f"in {sorted(signal_names)}"
                        )
                        if self._missed_trade_tracker is not None:
                            self._missed_trade_tracker.record_ensemble_rejection(
                                symbol=symbol, signals=signals, reason="losing_combo"
                            )
                        return None

        buy_strength = self._weighted_confidence_sum(buy_signals) if buy_signals else 0
        sell_strength = self._weighted_confidence_sum(sell_signals) if sell_signals else 0

        if buy_strength > sell_strength and buy_signals:
            chosen, opposition = buy_signals, sell_signals
            chosen_strength, oppose_strength = buy_strength, sell_strength
        elif sell_strength > buy_strength and sell_signals:
            chosen, opposition = sell_signals, buy_signals
            chosen_strength, oppose_strength = sell_strength, buy_strength
        else:
            return None  # tied or empty

        # Weighted veto: chosen side must be meaningfully stronger
        if opposition and chosen_strength < oppose_strength * self.veto_ratio:
            logger.info(
                f"[{symbol}] Weighted veto: {chosen[0].side} strength={chosen_strength:.1f} "
                f"< {opposition[0].side} strength={oppose_strength:.1f} * {self.veto_ratio} "
                f"= {oppose_strength * self.veto_ratio:.1f}"
            )
            if self._missed_trade_tracker is not None:
                self._missed_trade_tracker.record_ensemble_rejection(
                    symbol=symbol, signals=signals, reason="opposition_veto"
                )
            return None

        merged = self._merge_signals(symbol, chosen)
        if merged is None:
            return None

        # Duration-aware opposition penalty: daily strategies penalize
        # intraday signals less (different timeframe = weaker opposition).
        # Also cap per-strategy weight to prevent one bad strategy from
        # dominating the penalty.
        if opposition:
            # Infer the chosen side's dominant timeframe from the strongest signal
            chosen_tf = self.STRATEGY_TIMEFRAME.get(
                max(chosen, key=lambda s: s.confidence).strategy, "swing"
            )
            # Opposition penalty proportional to how close the veto was to firing.
            # A signal that barely passed the veto gets a bigger penalty than one
            # that dominated. The old 15x arbitrary multiplier was crushing
            # legitimate signals by 10-30 points regardless of veto margin.
            if oppose_strength > 0:
                safety_margin = chosen_strength / (oppose_strength * self.veto_ratio) - 1.0
                safety_margin = max(0.0, min(safety_margin, 1.0))  # Clamp 0-1
            else:
                safety_margin = 1.0  # No opposition strength = no penalty
            penalty_intensity = max(0.0, 1.0 - safety_margin)  # 0 = safe, 1 = barely passed

            penalty = 0.0
            for s in opposition:
                raw_weight = self._get_strategy_weight(s.strategy)
                capped_weight = min(raw_weight, self.MAX_OPPOSITION_WEIGHT)
                # Duration mismatch discount: daily opposing intraday = 40% penalty
                opp_tf = self.STRATEGY_TIMEFRAME.get(s.strategy, "swing")
                if chosen_tf != opp_tf:
                    tf_discount = 0.4  # Cross-timeframe = much weaker opposition
                else:
                    tf_discount = 1.0  # Same timeframe = full penalty
                # Scale by opposition strength: weak opposition (<55% confidence) = minimal penalty
                opp_strength_scale = s.confidence / 100.0
                if opp_strength_scale < 0.55:
                    opp_strength_scale *= 0.3  # Weak opposition: 70% penalty reduction
                penalty += capped_weight * 5 * (s.confidence / 100) * tf_discount * penalty_intensity * min(1.0, opp_strength_scale / 0.55)
            merged.confidence = max(0, merged.confidence - penalty)
            merged.metadata["opposition_penalty"] = round(penalty, 1)
            opp_names = [s.strategy for s in opposition]
            logger.info(
                f"[{symbol}] {chosen[0].side} passes weighted veto "
                f"({chosen_strength:.1f} vs {oppose_strength:.1f}), "
                f"penalty -{penalty:.1f} from {opp_names}"
            )

        return merged

    def _weighted(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Weight strategies by performance and combine."""
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        buy_weight = sum(self.weights.get(s.strategy, 1.0) * s.confidence for s in buy_signals)
        sell_weight = sum(self.weights.get(s.strategy, 1.0) * s.confidence for s in sell_signals)

        if buy_weight > sell_weight and len(buy_signals) >= 1:
            chosen = buy_signals
        elif sell_weight > buy_weight and len(sell_signals) >= 1:
            chosen = sell_signals
        else:
            return None

        return self._merge_signals(symbol, chosen)

    def _best(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Take the single highest-confidence signal."""
        best = max(signals, key=lambda s: s.confidence)
        return best

    def _get_strategy_weight(self, strategy_name: str) -> float:
        """Get weight for a strategy from weight manager, falling back to static weights.
        Applies IC tracker weight to penalize inverted/decaying factors.
        Caps daily-timeframe strategies (monte_carlo_zones) at MAX_OPPOSITION_WEIGHT
        to prevent a single high-timeframe strategy from dominating voting."""
        if self.weight_manager is not None:
            w = self.weight_manager.get_weight(strategy_name)
        else:
            w = self.weights.get(strategy_name, 1.0)
        # IC tracker: penalize inverted/decaying factors (0.0 = inverted, 0.5 = unknown, 1.0 = healthy)
        if self.ic_tracker is not None:
            try:
                ic_weight = self.ic_tracker.get_ic_weight(strategy_name)
                if ic_weight < 1.0:
                    logger.info(
                        f"[IC] {strategy_name} weight adjusted by IC: {w:.3f} * {ic_weight:.2f} = {w * ic_weight:.3f}"
                    )
                w *= ic_weight
            except Exception:
                pass  # IC tracker error shouldn't break voting
        # Cap daily-TF strategies so they can't overpower intraday consensus
        if self.STRATEGY_TIMEFRAME.get(strategy_name) == "daily":
            w = min(w, self.MAX_OPPOSITION_WEIGHT)
        return w

    def _weighted_confidence_sum(self, signals: List[Signal]) -> float:
        """Compute sum of weight * confidence for a list of signals."""
        return sum(self._get_strategy_weight(s.strategy) * s.confidence for s in signals)

    def _merge_signals(self, symbol: str, signals: List[Signal]) -> Signal:
        """Merge multiple agreeing signals into one consensus signal.
        Uses strategy accuracy weights for weighted-average confidence."""
        side = signals[0].side

        # Weighted average confidence using strategy accuracy weights
        total_weight = sum(self._get_strategy_weight(s.strategy) for s in signals)
        if total_weight > 0:
            weighted_conf = sum(
                self._get_strategy_weight(s.strategy) * s.confidence for s in signals
            ) / total_weight
        else:
            weighted_conf = sum(s.confidence for s in signals) / len(signals)

        # Consensus bonus: reward genuine multi-strategy agreement.
        # Regime-aware: trending regimes justify higher consensus bonus (WR jumps
        # from 40% at 2-agree to 86% at 3-agree in consolidation).
        # Exponential instead of flat 3% per strategy.
        n_agree = len(signals)
        _regime = self._current_regime.get(symbol, "unknown")
        _CONSENSUS_MULT = {
            "trending_bull":    {2: 1.06, 3: 1.14, 4: 1.20},
            "trending_bear":    {2: 1.04, 3: 1.10, 4: 1.15},
            "consolidation":    {2: 1.08, 3: 1.18, 4: 1.28},
            "range":            {2: 1.03, 3: 1.06, 4: 1.10},
            "high_volatility":  {2: 1.02, 3: 1.04, 4: 1.06},
            "panic":            {2: 1.01, 3: 1.02, 4: 1.03},
        }
        _default_mult = {2: 1.04, 3: 1.08, 4: 1.12}
        _regime_mults = _CONSENSUS_MULT.get(_regime, _default_mult)
        consensus_mult = _regime_mults.get(n_agree, 1.0) if n_agree >= 2 else 1.0
        # Cap ensemble confidence — raised to 92% so genuine unanimous signals pass
        try:
            from trading_config import TradingConfig
            max_conf = TradingConfig().max_ensemble_confidence
        except Exception:
            max_conf = 85.0
        if max_conf < 85.0:
            logger.warning(f"[ENSEMBLE] MAX_ENSEMBLE_CONFIDENCE={max_conf} is very low, may suppress valid signals")
        # Respect user's configured cap (don't silently override to 92)
        combined_conf = min(max_conf, weighted_conf * consensus_mult)

        # Weighted-average SL (preserves R:R), average TP1 (balanced), widest TP2 (aggressive).
        # Old policy: "widest SL" destroyed R:R when strategies disagreed on stops.
        # New: weight SL by strategy accuracy, so trusted strategies get more say.
        # Average TP1 prevents zone-based strategies from pulling targets too close.
        # Consistent accuracy-weighted averaging for SL, entry, TP1, ATR.
        # Using the same weighting for all levels preserves R:R geometry.
        # TP2 stays aggressive (widest) since it's the trailing target.
        if total_weight > 0:
            weighted_sl = sum(
                self._get_strategy_weight(s.strategy) * s.sl for s in signals
            ) / total_weight
            weighted_entry = sum(
                self._get_strategy_weight(s.strategy) * s.entry for s in signals
            ) / total_weight
            weighted_tp1 = sum(
                self._get_strategy_weight(s.strategy) * s.tp1 for s in signals
            ) / total_weight
            weighted_atr = sum(
                self._get_strategy_weight(s.strategy) * s.atr for s in signals
            ) / total_weight
        else:
            weighted_sl = sum(s.sl for s in signals) / len(signals)
            weighted_entry = sum(s.entry for s in signals) / len(signals)
            weighted_tp1 = sum(s.tp1 for s in signals) / len(signals)
            weighted_atr = sum(s.atr for s in signals) / len(signals)
        # Bear-market shorts: widen SL to survive bounce wicks.
        # 1.5x ATR is too tight for SELL in volatile bear markets — bounces
        # trigger stops before the move continues. Widen by 30% in trending regimes.
        regime = self._current_regime.get(symbol, "unknown")
        if side == "SELL" and regime == "trend":
            sl_widen = 1.3  # 30% wider stop for bear-market shorts
            old_sl = weighted_sl
            # For SELL, SL is above entry — widen means push it higher
            sl_dist = abs(weighted_sl - weighted_entry)
            weighted_sl = weighted_entry + sl_dist * sl_widen
            # Proportionally widen TP to maintain R:R geometry
            weighted_tp1 = weighted_entry - abs(weighted_entry - weighted_tp1) * sl_widen
            logger.info(
                f"[ENSEMBLE] {symbol} SELL SL widened {sl_widen}x for bear regime: "
                f"SL {old_sl:.2f} → {weighted_sl:.2f}"
            )

        if side == "BUY":
            best_sl = weighted_sl
            best_tp1 = weighted_tp1
            best_tp2 = max(s.tp2 for s in signals)
            entry = weighted_entry
        else:
            best_sl = weighted_sl
            best_tp1 = weighted_tp1
            best_tp2 = min(s.tp2 for s in signals)
            entry = weighted_entry

        atr = weighted_atr

        # Preserve per-signal ATR and SL for profile classification
        per_signal_atr = {s.strategy: s.atr for s in signals}
        per_signal_sl = {s.strategy: s.sl for s in signals}
        per_signal_tp1 = {s.strategy: s.tp1 for s in signals}

        # Fee-aware Expected Value per $1 risked:
        #   EV = win_prob × (R:R - fee_drag) - loss_prob × (1.0 + fee_drag)
        # Fee drag = round-trip fees as fraction of stop width.
        # A 1.5 R:R trade with 10% fee drag: win nets 1.4R, loss costs 1.1R.
        #
        # CRITICAL: confidence ≠ win probability. 70% confidence historically
        # produces ~45% WR (overconfident). Apply conservative deflator to
        # prevent EV overestimation from uncalibrated confidence scores.
        # Deflator: assume confidence is ~1.4x actual win rate (empirical).
        # This makes EV a LOWER BOUND rather than an optimistic estimate.
        stop_width = abs(entry - best_sl)
        rr_tp1 = abs(entry - best_tp1) / stop_width if stop_width > 0 else 0
        rr_tp2 = abs(entry - best_tp2) / stop_width if stop_width > 0 else 0
        raw_win_prob = combined_conf / 100.0
        # Win probability deflation: regime-aware calibration.
        # Trending regimes have empirically higher WR (58-86%), so deflate less.
        # High-vol/range regimes have lower WR, so deflate more.
        # Format: {n_agree: {regime: deflation_factor}}
        _WP_DEFLATION = {
            4: {"trending_bull": 0.93, "trending_bear": 0.90, "consolidation": 0.92,
                "range": 0.85, "high_volatility": 0.80, "panic": 0.75},
            3: {"trending_bull": 0.85, "trending_bear": 0.82, "consolidation": 0.88,
                "range": 0.78, "high_volatility": 0.72, "panic": 0.68},
            2: {"trending_bull": 0.75, "trending_bear": 0.72, "consolidation": 0.70,
                "range": 0.65, "high_volatility": 0.60, "panic": 0.55},
            1: {"trending_bull": 0.55, "trending_bear": 0.52, "consolidation": 0.50,
                "range": 0.45, "high_volatility": 0.40, "panic": 0.35},
        }
        _DEFAULT_DEFLATION = {4: 0.88, 3: 0.80, 2: 0.65, 1: 0.50}
        _regime_ev = self._current_regime.get(symbol, "unknown")
        _agree_key = min(n_agree, 4)
        _deflation = _WP_DEFLATION.get(_agree_key, {}).get(
            _regime_ev, _DEFAULT_DEFLATION.get(_agree_key, 0.65)
        )
        win_prob = raw_win_prob * _deflation
        try:
            from trading_config import TradingConfig as _TConf
            _fee_bps = _TConf().taker_fee_bps
        except Exception:
            _fee_bps = 4
        # Regime-specific slippage: high-vol/panic markets have wider spreads
        # and worse fills. Add slippage as additional cost beyond fees.
        _REGIME_SLIPPAGE_BPS = {
            "trending_bull": 1, "trending_bear": 2, "trend": 1,
            "consolidation": 1, "range": 1,
            "high_volatility": 4, "panic": 6,
            "low_liquidity": 5, "news_dislocation": 5,
        }
        _slippage_bps = _REGIME_SLIPPAGE_BPS.get(_regime_ev, 2)
        _total_cost_bps = _fee_bps * 2 + _slippage_bps  # round-trip fees + slippage
        fee_drag = (entry * _total_cost_bps / 10000.0) / stop_width if stop_width > 0 else 0
        # Partial-close-aware EV: model TP1 partial close + TP2 continuation
        # After TP1 hit, SL moves to breakeven → remaining position is risk-free
        # but only ~50% chance of reaching TP2 (conservative estimate)
        _tp1_close_pct = 0.60  # Default: MEDIUM profile closes 60% at TP1
        _p_tp2_given_tp1 = 0.45  # Conservative: once TP1 hit and SL at BE, 45% reach TP2
        # Blended win payoff: tp1_pct gets rr_tp1, remainder gets expected rr_tp2
        _win_payoff = (
            _tp1_close_pct * (rr_tp1 - fee_drag)
            + (1 - _tp1_close_pct) * _p_tp2_given_tp1 * (rr_tp2 - fee_drag)
            # remaining position that doesn't reach TP2: exits at ~breakeven (0 gain, pay exit fee)
            + (1 - _tp1_close_pct) * (1 - _p_tp2_given_tp1) * (-fee_drag * 0.5)
        )
        ev_per_dollar = round(win_prob * _win_payoff - (1.0 - win_prob) * (1.0 + fee_drag), 4)

        # Defense-in-depth: reject negative-EV signals at ensemble level.
        # The signal pipeline also checks EV, but this prevents wasted computation
        # on signals that are mathematically unprofitable.
        if ev_per_dollar < 0:
            logger.info(
                f"[ENSEMBLE] {symbol} {side} rejected: negative EV ({ev_per_dollar:.4f}) "
                f"R:R={rr_tp1:.2f} fee_drag={fee_drag:.3f} win_prob={win_prob:.2f}"
            )
            return None

        # Propagate chop_score from input signals (attached by chop detector pre-merge)
        _chop_score = max(
            (s.metadata.get("chop_score", 0) for s in signals), default=0
        )

        return Signal(
            strategy="ensemble",
            symbol=symbol,
            side=side,
            confidence=combined_conf,
            entry=entry,
            sl=best_sl,
            tp1=best_tp1,
            tp2=best_tp2,
            atr=atr,
            metadata={
                "strategies_agree": [s.strategy for s in signals],
                "num_agree": len(signals),
                "total_strategies": len(self.strategies),
                "individual_confidences": {s.strategy: s.confidence for s in signals},
                "raw_weighted_conf": round(weighted_conf, 2),
                "consensus_mult": round(consensus_mult, 3),
                "combined_conf": round(combined_conf, 2),
                "strategy_weights": {s.strategy: round(self._get_strategy_weight(s.strategy), 3) for s in signals},
                "per_signal_atr": per_signal_atr,
                "per_signal_sl": per_signal_sl,
                "per_signal_tp1": per_signal_tp1,
                "mode": self.mode,
                "ev_per_dollar": ev_per_dollar,
                "win_prob": round(win_prob, 4),
                "rr_tp1": round(rr_tp1, 3),
                "rr_tp2": round(rr_tp2, 3),
                "fee_drag_pct": round(fee_drag * 100, 1) if stop_width > 0 else 0.0,
                "stop_width_pct": round(stop_width / entry * 100, 3) if entry > 0 else 0.0,
                "chop_score": _chop_score,
            },
        )

    def get_all_status(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> List[Dict[str, Any]]:
        """Get status from all strategies for display."""
        statuses = []
        for strategy in self.strategies:
            try:
                status = strategy.get_status(symbol, data)
                statuses.append(status)
            except Exception as e:
                statuses.append({
                    "symbol": symbol,
                    "strategy": strategy.name,
                    "status": f"error: {e}",
                })
        return statuses

    def get_signal_digest(self, symbol: str) -> Dict[str, Any]:
        """Build comprehensive signal digest for LLM brain visibility.

        Returns ALL strategy readings for a symbol — not just passing ones.
        This gives the LLM full visibility into what every strategy is detecting,
        the ensemble decision, and why signals passed or were rejected.
        """
        cached = self._last_signals.get(symbol, {})
        if not cached:
            return {}

        readings = []
        sides = {"BUY": 0, "SELL": 0}
        total_conf = 0.0
        n_signals = 0

        for strat_name, sig in cached.items():
            reading = {
                "strategy": strat_name,
                "side": sig.side,
                "confidence": round(sig.confidence, 1),
                "entry": round(sig.entry, 2) if sig.entry else 0,
                "weight": round(self.weights.get(strat_name, 1.0), 2),
                "duration": self.STRATEGY_DURATION_MAP.get(strat_name, "unknown"),
                "timeframe": self.STRATEGY_TIMEFRAME.get(strat_name, "swing"),
            }
            # Include key metadata that strategies computed
            for key in ("regime_score", "chop_score", "quality_score", "signal_flags",
                        "entry_type", "setup_type", "atr_pct", "vol_ratio"):
                if key in sig.metadata:
                    reading[key] = sig.metadata[key]
            readings.append(reading)
            sides[sig.side] = sides.get(sig.side, 0) + 1
            total_conf += sig.confidence
            n_signals += 1

        # Compute agreement and consensus
        dominant_side = max(sides, key=sides.get) if sides else "NONE"
        agreement = sides.get(dominant_side, 0)
        dissent = n_signals - agreement

        digest = {
            "symbol": symbol,
            "n_strategies": n_signals,
            "readings": readings,
            "consensus": {
                "dominant_side": dominant_side,
                "agreement": agreement,
                "dissent": dissent,
                "avg_confidence": round(total_conf / n_signals, 1) if n_signals else 0,
                "min_votes_needed": self.min_votes,
                "would_pass_votes": agreement >= self.min_votes,
            },
        }

        # Add rejection history if available
        chop = self._smoothed_chop.get(symbol, 0)
        if chop > 0:
            digest["chop_score"] = round(chop, 3)

        # Include last rejection reason so LLM knows WHY signals were blocked
        rejection = self._last_rejections.get(symbol)
        if rejection:
            digest["last_rejection"] = rejection

        return digest

    def get_all_signal_digests(self) -> Dict[str, Dict]:
        """Get signal digests for ALL symbols with cached readings."""
        return {sym: self.get_signal_digest(sym) for sym in self._last_signals}

    def update_weights(self, performance: Dict[str, float]):
        """Update strategy weights based on observed performance."""
        for name, perf in performance.items():
            if name in self.weights:
                # Simple: weight = 0.5 + performance (bounded 0.1 to 2.0)
                self.weights[name] = max(0.1, min(2.0, 0.5 + perf))
        logger.info(f"Updated ensemble weights: {self.weights}")
