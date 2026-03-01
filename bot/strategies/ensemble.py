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
        veto_ratio: float = 1.1,
    ):
        self.strategies = strategies
        self.mode = mode
        self.min_votes = min_votes
        self.weights = weights or {s.name: 1.0 for s in strategies}
        self.weight_manager = weight_manager  # StrategyWeightManager instance
        self.veto_ratio = veto_ratio

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
        signals: List[Signal] = []

        for strategy in self.strategies:
            try:
                sig = strategy.evaluate(symbol, data)
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                logger.warning(f"[{symbol}] {strategy.name} error: {e}")

        if not signals:
            return None

        # Volume chop filter: reject signals during low-volume periods
        if self._is_low_volume(symbol, data):
            logger.info(f"[{symbol}] Signal skipped: low volume (chop filter)")
            return None

        if self.mode == "voting":
            result = self._voting(symbol, signals)
        elif self.mode == "weighted_veto":
            result = self._weighted_veto(symbol, signals)
        elif self.mode == "weighted":
            result = self._weighted(symbol, signals)
        elif self.mode == "best":
            result = self._best(symbol, signals)
        else:
            result = self._voting(symbol, signals)

        if result is None:
            return None

        # ── Post-merge quality gates ──

        # 1. Minimum confidence floor — reject weak consensus signals
        if result.confidence < 65:
            logger.info(
                f"[{symbol}] Signal rejected: confidence {result.confidence:.0f}% < 65% floor"
            )
            return None

        # 2. Trend alignment: FLIP counter-trend signals to ride the trend
        result = self._trend_alignment_adjust(symbol, data, result)

        # Re-check floor after adjustment (should rarely fail now since we flip instead of crush)
        if result.confidence < 65:
            logger.info(
                f"[{symbol}] Signal rejected: confidence {result.confidence:.0f}% "
                f"after trend adjustment"
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

    def _compute_trend_scores(self, symbol: str, data: Dict[str, pd.DataFrame]):
        """Compute multi-timeframe trend scores.
        Returns (total_score, num_timeframes, detail_string).
        Score range: -4 (strong bear) to +4 (strong bull).
        """
        scores = []
        details = []

        # ── 5m: fast momentum ──
        df_5m = data.get("5m")
        if df_5m is not None and not df_5m.empty and len(df_5m) >= 50:
            c = df_5m["close"].astype(float)
            e20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
            e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            s = 1 if e20 > e50 else -1
            scores.append(s)
            details.append(f"5m={'B' if s > 0 else 'S'}")

        # ── 1h: core trend + MACD momentum ──
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
            details.append(f"1h={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        # ── 6h: higher timeframe structure ──
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
            details.append(f"6h={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        # ── Daily: macro trend + RSI ──
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
            details.append(f"D={'B' if s > 0 else 'S' if s < 0 else 'N'}")

        total = sum(scores) if scores else 0
        n = len(scores)
        detail_str = " ".join(details)
        return total, n, detail_str

    def _trend_alignment_adjust(
        self, symbol: str, data: Dict[str, pd.DataFrame], result: "Signal"
    ) -> "Signal":
        """Multi-timeframe trend alignment: flip or boost signals.

        Instead of crushing confidence on counter-trend signals, this method
        FLIPS the signal direction when the trend strongly disagrees, turning
        weak counter-trend buys into trend-aligned shorts (and vice versa).

        Strong trend (±3..4):
          - Counter-trend → FLIP side, recalculate levels, +5 bonus
          - Aligned → +8 bonus
        Moderate trend (±1..2):
          - Counter-trend → FLIP side, recalculate levels, +0 (neutral)
          - Aligned → +3 bonus
        Neutral (0): no adjustment
        """
        total, n, detail_str = self._compute_trend_scores(symbol, data)

        if n == 0:
            return result

        side = result.side
        is_buy = side == "BUY"

        if abs(total) >= 3:
            trend_bullish = total > 0
            if is_buy == trend_bullish:
                # Aligned with strong trend — bonus
                result.confidence = min(100, result.confidence + 8)
                result.metadata["trend_adjustment"] = -8
                logger.info(
                    f"[{symbol}] Strong trend aligned {side}: "
                    f"score={total}/{n} [{detail_str}] +8 bonus"
                )
            else:
                # Strong counter-trend — FLIP the signal
                result = self._flip_signal(symbol, result, data)
                result.confidence = min(100, result.confidence + 5)
                result.metadata["trend_adjustment"] = -5
                result.metadata["trend_flipped"] = True
                logger.info(
                    f"[{symbol}] FLIP {side}->{result.side}: strong trend "
                    f"score={total}/{n} [{detail_str}] -- sniper mode"
                )
        elif abs(total) >= 1:
            trend_bullish = total > 0
            if is_buy == trend_bullish:
                # Mild alignment — small bonus
                result.confidence = min(100, result.confidence + 3)
                result.metadata["trend_adjustment"] = -3
                logger.info(
                    f"[{symbol}] Trend aligned {side}: "
                    f"score={total}/{n} [{detail_str}] +3 bonus"
                )
            else:
                # Moderate counter-trend — FLIP the signal
                result = self._flip_signal(symbol, result, data)
                result.metadata["trend_adjustment"] = 0
                result.metadata["trend_flipped"] = True
                logger.info(
                    f"[{symbol}] FLIP {side}->{result.side}: moderate trend "
                    f"score={total}/{n} [{detail_str}] -- sniper mode"
                )
        else:
            result.metadata["trend_adjustment"] = 0
            logger.info(f"[{symbol}] Neutral trend: score={total}/{n} [{detail_str}]")

        return result

    def _flip_signal(
        self, symbol: str, signal: "Signal", data: Dict[str, pd.DataFrame]
    ) -> "Signal":
        """Flip a signal's direction: BUY→SELL or SELL→BUY.
        Recalculates entry/SL/TP levels for the new direction using ATR."""
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

        if signal.side == "BUY":
            # Flip to SELL (short)
            new_side = "SELL"
            sl = entry + 1.5 * atr
            tp1 = entry - 1.5 * atr
            tp2 = entry - 3.0 * atr
        else:
            # Flip to BUY (long)
            new_side = "BUY"
            sl = entry - 1.5 * atr
            tp1 = entry + 1.5 * atr
            tp2 = entry + 3.0 * atr

        signal.side = new_side
        signal.sl = sl
        signal.tp1 = tp1
        signal.tp2 = tp2
        signal.atr = atr
        return signal

    def _voting(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Require min_votes strategies to agree on direction.
        Opposition veto: if any strategy actively votes the opposite side,
        require min_votes + len(opposition) to override."""
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        # Determine which side has enough base votes
        buy_enough = len(buy_signals) >= self.min_votes
        sell_enough = len(sell_signals) >= self.min_votes

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
            required = self.min_votes + len(opposition)
            if len(chosen) < required:
                logger.info(
                    f"[{symbol}] Signal vetoed: {len(chosen)} {chosen[0].side} vs "
                    f"{len(opposition)} {opposition[0].side} (need {required} votes)"
                )
                return None

        merged = self._merge_signals(symbol, chosen)

        # Confidence penalty for opposition (even when vote passes)
        if opposition:
            penalty = len(opposition) * 10
            merged.confidence = max(0, merged.confidence - penalty)
            merged.metadata["opposition_penalty"] = penalty
            logger.info(
                f"[{symbol}] Opposition penalty: -{penalty} confidence "
                f"(opposed by {[s.strategy for s in opposition]})"
            )

        return merged

    def _weighted_veto(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Weight-aware voting with graduated veto.
        Uses strategy accuracy weights * confidence to determine direction.
        Requires chosen side to have veto_ratio times the opposition's strength.
        Minimum 2 strategies must agree on the same side for a trade."""
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        # Require at least 2 strategies agreeing on the same direction
        if len(buy_signals) < 2 and len(sell_signals) < 2:
            if buy_signals:
                logger.info(f"[{symbol}] Only {len(buy_signals)} BUY signal(s), need 2+ same-side")
            elif sell_signals:
                logger.info(f"[{symbol}] Only {len(sell_signals)} SELL signal(s), need 2+ same-side")
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

        # Weighted opposition penalty (scaled by opposer's accuracy weight)
        if opposition:
            penalty = sum(self._get_strategy_weight(s.strategy) * 15 for s in opposition)
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
        """Get weight for a strategy from weight manager, falling back to static weights."""
        if self.weight_manager is not None:
            return self.weight_manager.get_weight(strategy_name)
        return self.weights.get(strategy_name, 1.0)

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

        # Consensus bonus: more strategies agree -> higher confidence
        consensus_bonus = (len(signals) - 1) * 3
        combined_conf = min(100, weighted_conf + consensus_bonus)

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
                "strategy_weights": {s.strategy: round(self._get_strategy_weight(s.strategy), 3) for s in signals},
                "per_signal_atr": per_signal_atr,
                "per_signal_sl": per_signal_sl,
                "per_signal_tp1": per_signal_tp1,
                "mode": self.mode,
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
