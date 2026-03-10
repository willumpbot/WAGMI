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
        veto_ratio: float = 1.5,  # Match trading_config.py default
        chop_detector=None,
        confidence_floor: float = 65.0,
        ranging_confidence_floor: float = 88.0,
    ):
        self.strategies = strategies
        self.mode = mode
        self.min_votes = min_votes
        self.weights = weights or {s.name: 1.0 for s in strategies}
        self.weight_manager = weight_manager  # StrategyWeightManager instance
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
    }

    # Strategy primary timeframe — used for duration-aware opposition penalty.
    # Daily-timeframe strategies penalize intraday signals less (and vice versa).
    STRATEGY_TIMEFRAME = {
        "multi_tier_quality": "intraday",   # 5m + 1h
        "confidence_scorer": "intraday",    # multi-factor, mostly 1h
        "regime_trend": "swing",            # 1h + 6h
        "monte_carlo_zones": "daily",       # daily zones
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

    def evaluate(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> Optional[Signal]:
        """
        Run all strategies and combine their signals.
        Returns a single consensus Signal or None.
        """
        # Dynamic weight refresh: pull rolling weights before each evaluation
        self._refresh_dynamic_weights()

        signals: List[Signal] = []
        active_count = 0  # Strategies that ran (didn't error or get disabled)
        error_count = 0

        for strategy in self.strategies:
            # Regime-based strategy filter: skip disabled strategies
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

        # Deep copy signals FIRST, then cache copies — prevents mutation between
        # cache write and copy if any code path modifies signals in-place.
        signals = [deepcopy(s) for s in signals]

        # Cache copies for context extraction (these won't be mutated further)
        self._last_signals[symbol] = {s.strategy: deepcopy(s) for s in signals}

        if not signals:
            return None

        # ── Graceful strategy degradation ──
        # If strategies errored, lower min_votes so the system doesn't deadlock.
        # With 4 strategies and MIN_VOTES=3, a single error means max 3 signals.
        # If one of those 3 abstains, we'd have 2 signals and can never trade.
        effective_min_votes = self.min_votes
        if error_count > 0 and active_count > 0:
            # Lower min_votes proportionally, but never below 2
            effective_min_votes = max(2, min(self.min_votes, active_count - error_count))
            if effective_min_votes != self.min_votes:
                logger.info(
                    f"[{symbol}] Strategy degradation: {error_count} errors, "
                    f"min_votes {self.min_votes} → {effective_min_votes}"
                )

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

        # ── Post-merge quality gates ──

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
                # Extreme chop: floor rises to 88% (high bar but not impossible)
                chop_intensity = min(1.0, (chop_score - 0.65) / 0.20)  # 0→1 over 0.65→0.85
                effective_floor = self.ranging_confidence_floor + chop_intensity * (
                    88.0 - self.ranging_confidence_floor
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
            return None

        return result

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
                # Moderate counter-trend — REJECT instead of flip.
                # Flipped signals have zero original conviction in the new direction.
                # Better to skip entirely than enter with no thesis.
                result.metadata["trend_adjustment"] = 0
                result.metadata["trend_rejected"] = True
                logger.info(
                    f"[{symbol}] Counter-trend {side} REJECTED: moderate trend "
                    f"score={total:.1f}/{n} [{detail_str}] -- no flip, skip trade"
                )
                return None
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

        # Require at least min_votes strategies agreeing on the same direction
        if len(buy_signals) < min_v and len(sell_signals) < min_v:
            if buy_signals:
                logger.info(f"[{symbol}] Only {len(buy_signals)} BUY signal(s), need {min_v}+ same-side")
            elif sell_signals:
                logger.info(f"[{symbol}] Only {len(sell_signals)} SELL signal(s), need {min_v}+ same-side")
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
            return None

        merged = self._merge_signals(symbol, chosen)

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
        Caps daily-timeframe strategies (monte_carlo_zones) at MAX_OPPOSITION_WEIGHT
        to prevent a single high-timeframe strategy from dominating voting."""
        if self.weight_manager is not None:
            w = self.weight_manager.get_weight(strategy_name)
        else:
            w = self.weights.get(strategy_name, 1.0)
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
        # 10d backtest: 3_agree PF=4.05, 86% WR — genuine confluence has edge.
        #   2 agree: 1.03x    3 agree: 1.06x    4 agree: 1.10x
        n_agree = len(signals)
        consensus_mult = 1.0
        if n_agree >= 2:
            consensus_mult = 1.0 + 0.03 * (n_agree - 1)
        # Cap ensemble confidence — raised to 92% so genuine unanimous signals pass
        try:
            from trading_config import TradingConfig
            max_conf = TradingConfig().max_ensemble_confidence
        except Exception:
            max_conf = 85.0
        max_conf = max(max_conf, 92.0)  # Ensure cap is at least 92%
        combined_conf = min(max_conf, weighted_conf * consensus_mult)

        # Widest SL (most conservative), average TP1 (balanced), widest TP2 (aggressive)
        # Using average TP1 prevents zone-based strategies from pulling targets too close
        if side == "BUY":
            best_sl = min(s.sl for s in signals)
            best_tp1 = sum(s.tp1 for s in signals) / len(signals)
            best_tp2 = max(s.tp2 for s in signals)
            entry = sum(s.entry for s in signals) / len(signals)
        else:
            best_sl = max(s.sl for s in signals)
            best_tp1 = sum(s.tp1 for s in signals) / len(signals)
            best_tp2 = min(s.tp2 for s in signals)
            entry = sum(s.entry for s in signals) / len(signals)

        atr = max((s.atr for s in signals), default=0)

        # Preserve per-signal ATR and SL for profile classification
        per_signal_atr = {s.strategy: s.atr for s in signals}
        per_signal_sl = {s.strategy: s.sl for s in signals}
        per_signal_tp1 = {s.strategy: s.tp1 for s in signals}

        # Expected Value per $1 risked:
        #   EV = (win_prob × avg_R:R) - (loss_prob × 1.0)
        # Positive EV means the trade has a statistical edge.
        # This enables EV-based filtering: a 72% conf trade with 1.5 R:R
        # (EV=0.80) beats a 78% conf trade with 0.9 R:R (EV=0.48).
        stop_width = abs(entry - best_sl)
        rr_tp1 = abs(entry - best_tp1) / stop_width if stop_width > 0 else 0
        win_prob = combined_conf / 100.0
        ev_per_dollar = round(win_prob * rr_tp1 - (1.0 - win_prob), 4)

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
                "rr_tp1": round(rr_tp1, 3),
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

    def update_weights(self, performance: Dict[str, float]):
        """Update strategy weights based on observed performance."""
        for name, perf in performance.items():
            if name in self.weights:
                # Simple: weight = 0.5 + performance (bounded 0.1 to 2.0)
                self.weights[name] = max(0.1, min(2.0, 0.5 + perf))
        logger.info(f"Updated ensemble weights: {self.weights}")
