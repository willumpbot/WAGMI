"""
Feedback Loop Orchestrator: Wires all feedback components together.

This is the single entry point for the main trading loop to interact
with the feedback system. It coordinates:
  - AdaptiveConfidenceFloor: Dynamic confidence thresholds
  - ContinuousBacktester: Rolling mini-backtests
  - ParameterTuner: Trust-gated parameter adjustments
  - SignalQualityScorer: Per-signal quality multiplier

Usage in main loop:
    feedback = FeedbackLoop()

    # Before trading: check if signal should pass
    should_trade, floor, reason = feedback.evaluate_signal(
        confidence=signal.confidence,
        strategy="ensemble",
        symbol="BTC",
        regime="trending",
        features=QualityFeatures(...)
    )

    # After trade closes: record outcome
    feedback.record_outcome(
        confidence=pos.confidence,
        win=pnl > 0,
        pnl=pnl,
        strategy=pos.strategy,
        symbol=pos.symbol,
        regime=pos.regime,
    )

    # Periodic: run backtest cycle
    feedback.tick()  # Call every main loop iteration
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from feedback.adaptive_confidence import AdaptiveConfidenceFloor
from feedback.continuous_backtest import ContinuousBacktester
from feedback.parameter_tuner import ParameterTuner
from feedback.signal_quality import SignalQualityScorer, QualityFeatures

logger = logging.getLogger("bot.feedback.loop")


class FeedbackLoop:
    """
    Main orchestrator for all feedback loop components.

    Provides a unified interface for the trading bot to interact with
    the self-improving system.
    """

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = data_dir

        # Core components
        self.confidence = AdaptiveConfidenceFloor(data_dir=data_dir)
        self.backtester = ContinuousBacktester(data_dir=data_dir)
        self.tuner = ParameterTuner(data_dir=data_dir)
        self.quality = SignalQualityScorer(data_dir=data_dir)

        # Tick counter for periodic operations
        self._tick_count = 0
        self._last_tuner_update = 0

        logger.info(
            f"[FEEDBACK] Initialized: "
            f"floor={self.confidence.current_floor:.1f}%, "
            f"trust={self.tuner.params.trust_score:.2f}"
        )

    def evaluate_signal(
        self,
        confidence: float,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
        side: str = "",
        entry_type: str = "",
        num_agree: int = 1,
        total_strategies: int = 4,
        volume_ratio: float = 1.0,
        volatility: float = 0.0,
        rr1: float = 1.0,
        trend_alignment: float = 0.0,
    ) -> Tuple[bool, float, float, str]:
        """Evaluate whether a signal should be traded.

        Applies:
        1. Signal quality scoring (adjusts confidence)
        2. Adaptive confidence floor (dynamic threshold)
        3. Parameter tuner adjustments

        Returns:
            (should_trade, adjusted_confidence, floor, reason)
        """
        now = datetime.now(timezone.utc)

        # Build quality features
        features = QualityFeatures(
            confidence=confidence,
            num_strategies_agree=num_agree,
            total_strategies=total_strategies,
            symbol=symbol,
            side=side,
            regime=regime,
            entry_type=entry_type,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            volume_ratio=volume_ratio,
            volatility=volatility,
            rr1=rr1,
            trend_alignment=trend_alignment,
        )

        # Step 1: Quality-adjust confidence
        adjusted_conf, quality_mult, _ = self.quality.adjust_confidence(
            confidence, features
        )

        # Step 2: Apply tuner calibration offset
        cal_offset = self.tuner.get_calibration_offset()
        adjusted_conf = max(0, min(100, adjusted_conf + cal_offset))

        # Step 3: Get adaptive floor
        adaptive_floor = self.confidence.get_floor(strategy, symbol, regime)

        # Step 4: Also consider tuner's floor (blend both)
        tuner_floor = self.tuner.get_confidence_floor(strategy, symbol, regime)

        # Blend: 60% adaptive (data-driven) + 40% tuner (backtest-driven)
        effective_floor = adaptive_floor * 0.6 + tuner_floor * 0.4

        # Check
        if adjusted_conf >= effective_floor:
            margin = adjusted_conf - effective_floor
            reason = (
                f"PASS: conf {confidence:.0f}% -> {adjusted_conf:.0f}% "
                f"(quality={quality_mult:.2f}) >= floor {effective_floor:.0f}% "
                f"(margin +{margin:.0f})"
            )
            return True, adjusted_conf, effective_floor, reason
        else:
            deficit = effective_floor - adjusted_conf
            reason = (
                f"REJECT: conf {confidence:.0f}% -> {adjusted_conf:.0f}% "
                f"(quality={quality_mult:.2f}) < floor {effective_floor:.0f}% "
                f"(deficit -{deficit:.0f})"
            )
            return False, adjusted_conf, effective_floor, reason

    def record_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        strategy: str,
        entry: float,
        sl: float,
        tp1: float,
        regime: str = "",
        num_agree: int = 1,
        leverage: float = 1.0,
    ):
        """Record a signal for backtest tracking (called for all signals, traded or not)."""
        self.backtester.record_signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            strategy=strategy,
            entry=entry,
            sl=sl,
            tp1=tp1,
            regime=regime,
            num_agree=num_agree,
            leverage=leverage,
        )

    def record_outcome(
        self,
        confidence: float,
        win: bool,
        pnl: float,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
        side: str = "",
        entry_type: str = "",
        num_agree: int = 1,
        hold_time_s: float = 0,
        exit_action: str = "",
        leverage: float = 1.0,
        llm_action: str = "",
        llm_confidence: float = 0.0,
        llm_agreed: bool = True,
    ):
        """Record a trade outcome. Updates all feedback components."""
        now = datetime.now(timezone.utc)

        # 1. Update adaptive confidence floor
        self.confidence.record_outcome(
            confidence=confidence,
            win=win,
            pnl=pnl,
            strategy=strategy,
            symbol=symbol,
            regime=regime,
        )

        # 2. Update continuous backtester
        self.backtester.record_outcome(
            symbol=symbol,
            win=win,
            pnl=pnl,
            confidence_at_entry=confidence,
            strategy=strategy,
            regime=regime,
            hold_time_s=hold_time_s,
            exit_action=exit_action,
            leverage=leverage,
        )

        # 3. Update signal quality scorer (with LLM decision data)
        features = QualityFeatures(
            confidence=confidence,
            num_strategies_agree=num_agree,
            symbol=symbol,
            side=side,
            regime=regime,
            entry_type=entry_type,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            llm_action=llm_action,
            llm_confidence=llm_confidence,
            llm_agreed_with_ensemble=llm_agreed,
        )
        self.quality.record_outcome(features, win, pnl)

        logger.info(
            f"[FEEDBACK] Outcome recorded: {symbol} {side} "
            f"conf={confidence:.0f}% {'WIN' if win else 'LOSS'} "
            f"PnL=${pnl:+.2f} (floor={self.confidence.current_floor:.1f}%)"
        )

    def tick(self):
        """Called every main loop iteration. Runs periodic maintenance."""
        self._tick_count += 1

        # Run continuous backtests (self-manages timing internally)
        suggestions = self.backtester.tick()

        # Apply backtest suggestions to tuner (every 5 minutes)
        now = time.time()
        if now - self._last_tuner_update >= 300:
            self._apply_suggestions(suggestions)
            self._last_tuner_update = now

    def _apply_suggestions(self, suggestions=None):
        """Apply accumulated suggestions from backtest to tuner."""
        if suggestions is None:
            suggestions_dict = self.backtester.get_aggregated_suggestions()
        else:
            # Convert list to dict
            suggestions_dict = {}
            for s in suggestions:
                suggestions_dict[s.parameter] = s

        if not suggestions_dict:
            return

        # Extract relevant suggestions
        conf_floor = None
        lev_cap = None
        strat_weights = {}
        cal_offset = None

        for param, sug in suggestions_dict.items():
            if hasattr(sug, 'suggested_value'):
                val = sug.suggested_value
                conf = sug.confidence_in_suggestion
            else:
                val = sug.get("suggested_value", None)
                conf = sug.get("confidence_in_suggestion", 0.5)

            if param == "confidence_floor" and conf > 0.3:
                conf_floor = val
            elif param == "max_leverage" and conf > 0.3:
                lev_cap = val
            elif param.startswith("strategy_weight_") and conf > 0.3:
                strat_name = param.replace("strategy_weight_", "")
                strat_weights[strat_name] = val
            elif param == "calibration_offset" and conf > 0.3:
                cal_offset = val

        if any(v is not None for v in [conf_floor, lev_cap, cal_offset]) or strat_weights:
            self.tuner.update(
                confidence_floor_suggestion=conf_floor,
                leverage_suggestion=lev_cap,
                strategy_weight_suggestions=strat_weights if strat_weights else None,
                calibration_offset=cal_offset,
            )

            logger.info(
                f"[FEEDBACK] Applied tuner update: "
                f"floor={self.tuner.params.confidence_floor:.1f}%, "
                f"trust={self.tuner.params.trust_score:.2f}"
            )

    def get_leverage_cap(self, symbol: str = "", regime: str = "") -> float:
        """Get the feedback-adjusted leverage cap."""
        return self.tuner.get_leverage_cap(symbol, regime)

    def get_strategy_weight(self, strategy: str) -> float:
        """Get the feedback-adjusted strategy weight."""
        return self.tuner.get_strategy_weight(strategy)

    def get_report(self) -> Dict[str, Any]:
        """Get comprehensive feedback loop status report."""
        return {
            "confidence_floor": self.confidence.get_report(),
            "backtester": self.backtester.get_report(),
            "tuner": self.tuner.get_report(),
            "quality": self.quality.get_report(),
            "tick_count": self._tick_count,
        }

    def format_status(self) -> str:
        """Format a concise status string for Telegram/logs."""
        conf = self.confidence
        tuner = self.tuner.params
        quality_total = sum(
            d["total"] for d in self.quality.by_symbol.values()
        )

        lines = [
            f"*Feedback Loop*",
            f"Floor: {conf.current_floor:.1f}% (last change: {conf.last_floor_change:+.1f})",
            f"Trust: {tuner.trust_score:.2f}",
            f"Calibration: {tuner.calibration_offset:+.1f}",
            f"Quality data: {quality_total} outcomes",
        ]

        # Strategy weights if customized
        if tuner.strategy_weights:
            weight_str = ", ".join(
                f"{k}={v:.2f}" for k, v in tuner.strategy_weights.items()
            )
            lines.append(f"Weights: {weight_str}")

        # Recent overall win rate
        if self.quality.overall_recent:
            wr = sum(self.quality.overall_recent) / len(self.quality.overall_recent)
            lines.append(f"Recent WR: {wr:.0%} ({len(self.quality.overall_recent)} trades)")

        return "\n".join(lines)
