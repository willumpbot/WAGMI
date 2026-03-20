"""
TIER 4.5: Mechanical Bot Instrumentation Integration

Wires mechanical bot memory, analyzer, and state tracker into the trading pipeline.

This module provides hooks that integrate with:
1. Signal generation → records in memory
2. Position open → starts state tracking
3. Position state changes → records state snapshots
4. Position close → finalizes history and logs outcome

Purpose: Enable comprehensive instrumentation without modifying mechanical bot logic.
All hooks are additive (don't change behavior, only observe).
"""

import logging
from typing import Optional, List
from datetime import datetime
import time

from mechanical_bot_memory import get_mechanical_bot_memory, MechanicalBotSignal
from mechanical_bot_state_tracker import get_mechanical_bot_state_tracker, TradePhase
from mechanical_bot_data_stream import get_mechanical_data_stream_capture

logger = logging.getLogger("bot.llm.mechanical_bot_instrumentation")


class MechanicalBotInstrumentation:
    """
    Integration hooks for comprehensive mechanical bot instrumentation.
    """

    def __init__(self):
        self.memory = get_mechanical_bot_memory()
        self.state_tracker = get_mechanical_bot_state_tracker()
        self.data_stream = get_mechanical_data_stream_capture()

        # Track signal-to-trade mapping
        self.signal_to_trade_map = {}  # signal_id -> trade_id

    def on_signal_generated(
        self,
        signal_id: str,
        symbol: str,
        regime: str,
        volatility_percentile: float,
        alignment_score: float,
        btc_correlation: float,
        time_of_day: int,
        side: str,
        confidence: float,
        num_strategies: int,
        strategy_names: List[str],
        entry_price: float,
        leverage: float = 1.0,
    ) -> None:
        """
        Hook called when mechanical bot generates a signal.

        This is called after ensemble voting, before risk gates.
        """
        try:
            signal = self.memory.record_signal(
                signal_id=signal_id,
                symbol=symbol,
                regime=regime,
                volatility_percentile=volatility_percentile,
                alignment_score=alignment_score,
                btc_correlation=btc_correlation,
                time_of_day=time_of_day,
                side=side,
                confidence=confidence,
                num_strategies=num_strategies,
                strategy_names=strategy_names,
                entry_price=entry_price,
                leverage=leverage,
            )
            logger.debug(f"Recorded signal {signal_id} for {symbol} {side} at {entry_price}")
        except Exception as e:
            logger.error(f"Error recording signal {signal_id}: {e}")

    def on_position_opened(
        self,
        trade_id: str,
        signal_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        regime: str,
        volatility: float,
        alignment_score: float,
        initial_confidence: float,
        strategy_votes: int,
    ) -> None:
        """
        Hook called when mechanical bot opens a position.

        Maps signal to trade and starts state tracking.
        """
        try:
            # Map signal to trade
            self.signal_to_trade_map[signal_id] = trade_id

            # Record signal as executed
            self.memory.record_signal_outcome(
                signal_id=signal_id,
                executed=True,
                exit_price=None,
                pnl=None,
                pnl_pct=None,
                hold_time_minutes=None,
            )

            # Start tracking state
            self.state_tracker.start_tracking_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                current_price=current_price,
                regime=regime,
                volatility=volatility,
                alignment_score=alignment_score,
                initial_confidence=initial_confidence,
                strategy_votes=strategy_votes,
            )

            logger.debug(f"Started tracking trade {trade_id} from signal {signal_id}")
        except Exception as e:
            logger.error(f"Error on position open for {trade_id}: {e}")

    def on_position_state_change(
        self,
        trade_id: str,
        phase: str,  # Will convert to TradePhase enum
        current_price: float,
        entry_price: float,
        regime: str,
        volatility: float,
        alignment_score: float,
        position_pnl: Optional[float] = None,
        position_pnl_pct: Optional[float] = None,
        distance_to_tp1_pct: Optional[float] = None,
        distance_to_sl_pct: Optional[float] = None,
        bot_confidence: Optional[float] = None,
        reasoning: str = "",
        signals_still_agreeing: bool = False,
        num_strategies_voting: int = 0,
        events: Optional[List[str]] = None,
        notes: str = "",
    ) -> None:
        """
        Hook called when mechanical bot's position state changes.

        Called on every significant event during trade lifecycle.
        """
        try:
            # Convert phase string to enum
            try:
                phase_enum = TradePhase(phase)
            except ValueError:
                phase_enum = TradePhase.POSITION_OPEN

            # Record state change
            self.state_tracker.record_state_change(
                trade_id=trade_id,
                phase=phase_enum,
                current_price=current_price,
                entry_price=entry_price,
                regime=regime,
                volatility=volatility,
                alignment_score=alignment_score,
                position_pnl=position_pnl,
                position_pnl_pct=position_pnl_pct,
                distance_to_tp1_pct=distance_to_tp1_pct,
                distance_to_sl_pct=distance_to_sl_pct,
                bot_confidence=bot_confidence,
                reasoning=reasoning,
                signals_still_agreeing=signals_still_agreeing,
                num_strategies_voting=num_strategies_voting,
                events=events,
                notes=notes,
            )

            logger.debug(f"Recorded state change {phase} for trade {trade_id}")
        except Exception as e:
            logger.error(f"Error recording state change for {trade_id}: {e}")

    def on_position_closed(
        self,
        trade_id: str,
        signal_id: str,
        exit_price: float,
        exit_reason: str,
        pnl: Optional[float] = None,
        pnl_pct: Optional[float] = None,
    ) -> None:
        """
        Hook called when mechanical bot closes a position.

        Finalizes state tracking and records outcome in memory.
        """
        try:
            # Record outcome in state tracker
            self.state_tracker.close_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_reason=exit_reason,
                final_pnl=pnl,
                final_pnl_pct=pnl_pct,
            )

            # Record outcome in memory
            if signal_id in self.memory.signals:
                self.memory.record_signal_outcome(
                    signal_id=signal_id,
                    executed=True,
                    exit_price=exit_price,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    hold_time_minutes=None,  # Will be calculated in memory
                )

            logger.debug(f"Closed trade {trade_id} with exit reason {exit_reason}, PnL: {pnl}")
        except Exception as e:
            logger.error(f"Error closing trade {trade_id}: {e}")

    def on_signal_rejected(
        self,
        signal_id: str,
        rejection_reason: str,
    ) -> None:
        """
        Hook called when mechanical bot signal is rejected.

        Records non-execution for statistical analysis.
        """
        try:
            if signal_id in self.memory.signals:
                signal = self.memory.signals[signal_id]
                self.memory.record_signal_outcome(
                    signal_id=signal_id,
                    executed=False,
                    exit_price=None,
                    pnl=None,
                    pnl_pct=None,
                    hold_time_minutes=None,
                )
                logger.debug(f"Signal {signal_id} rejected: {rejection_reason}")
        except Exception as e:
            logger.error(f"Error recording rejection for {signal_id}: {e}")

    def capture_market_snapshot(
        self,
        symbol: str,
        current_price: float,
        price_change_1h_pct: float,
        price_change_24h_pct: float,
        atr: float,
        volatility_percentile: float,
        regime: str,
        regime_confidence: float,
        regime_momentum: Optional[str],
        alignment_5m_1h: float,
        alignment_1h_6h: float,
        alignment_6h_1d: float,
        support_level: Optional[float],
        resistance_level: Optional[float],
        btc_price: Optional[float],
        btc_change_1h_pct: float,
        correlation_with_btc_1h: float,
        correlation_with_btc_6h: float,
        time_of_day: int,
        day_of_week: int,
        trading_session: str,
        rsi_14: Optional[float] = None,
        macd_histogram: Optional[float] = None,
        momentum_direction: Optional[str] = None,
        volume_profile: Optional[str] = None,
        liquidity_rating: float = 0.0,
    ):
        """
        Hook to capture complete market snapshot the mechanical bot sees.

        Called continuously or on-demand to build market context history.
        """
        try:
            self.data_stream.capture_snapshot(
                symbol=symbol,
                current_price=current_price,
                price_change_1h_pct=price_change_1h_pct,
                price_change_24h_pct=price_change_24h_pct,
                atr=atr,
                volatility_percentile=volatility_percentile,
                regime=regime,
                regime_confidence=regime_confidence,
                regime_momentum=regime_momentum,
                alignment_5m_1h=alignment_5m_1h,
                alignment_1h_6h=alignment_1h_6h,
                alignment_6h_1d=alignment_6h_1d,
                support_level=support_level,
                resistance_level=resistance_level,
                btc_price=btc_price,
                btc_change_1h_pct=btc_change_1h_pct,
                correlation_with_btc_1h=correlation_with_btc_1h,
                correlation_with_btc_6h=correlation_with_btc_6h,
                time_of_day=time_of_day,
                day_of_week=day_of_week,
                trading_session=trading_session,
                rsi_14=rsi_14,
                macd_histogram=macd_histogram,
                momentum_direction=momentum_direction,
                volume_profile=volume_profile,
                liquidity_rating=liquidity_rating,
            )
        except Exception as e:
            logger.error(f"Error capturing market snapshot for {symbol}: {e}")

    def get_memory_report(self):
        """Get comprehensive memory report of mechanical bot behavior."""
        return self.memory.get_memory_report()

    def get_current_open_trades(self):
        """Get current state of all open trades."""
        return self.state_tracker.get_all_open_trades_states()

    def get_bot_edge_analysis(self):
        """Get analysis of mechanical bot's edges."""
        from mechanical_bot_analyzer import get_mechanical_bot_analyzer
        analyzer = get_mechanical_bot_analyzer()
        return analyzer.get_comprehensive_analysis()


# Global instrumentation
_global_instrumentation: Optional[MechanicalBotInstrumentation] = None


def get_mechanical_bot_instrumentation() -> MechanicalBotInstrumentation:
    """Get or create global instrumentation."""
    global _global_instrumentation
    if _global_instrumentation is None:
        _global_instrumentation = MechanicalBotInstrumentation()
    return _global_instrumentation
