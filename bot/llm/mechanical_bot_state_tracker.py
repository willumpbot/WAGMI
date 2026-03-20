"""
TIER 4.4: Mechanical Bot State Tracker

Tracks mechanical bot's internal state evolution during trade lifecycle.

Why: Understanding HOW the mechanical bot thinks during a trade is as important
as understanding its initial decision. This enables:
- Real-time monitoring of bot's confidence in open positions
- Detection of when bot realizes a trade is wrong
- Understanding of exit timing and decision-making
- Identification of "should have exited earlier" moments
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import time
from enum import Enum

logger = logging.getLogger("bot.llm.mechanical_bot_state_tracker")


class TradePhase(str, Enum):
    """Phases of a trade lifecycle."""
    SIGNAL_GENERATION = "signal_generation"  # Bot generates signal
    ENTRY_EVALUATION = "entry_evaluation"  # Bot evaluating entry
    POSITION_OPEN = "position_open"  # Position open, no events
    TP1_APPROACHED = "tp1_approached"  # Price within 50% of TP1
    TP1_HIT = "tp1_hit"  # TP1 hit, partial close
    SL_APPROACHED = "sl_approached"  # Price within 50% of SL
    SL_HIT = "sl_hit"  # Stop loss hit
    TRAILING = "trailing"  # In trailing stop mode
    DECISION_POINT = "decision_point"  # Bot reconsidering position
    EXIT_EVALUATION = "exit_evaluation"  # Bot considering exit
    CLOSED = "closed"  # Trade closed


@dataclass
class BotStateSnapshot:
    """Snapshot of mechanical bot's state at a moment in time."""
    state_id: str
    trade_id: str
    phase: TradePhase
    timestamp: float

    # Market state
    current_price: float
    price_change_since_entry_pct: float
    current_regime: str
    current_volatility_pct: float
    current_alignment_score: float

    # Position state
    position_pnl: Optional[float] = None
    position_pnl_pct: Optional[float] = None
    distance_to_tp1_pct: Optional[float] = None
    distance_to_sl_pct: Optional[float] = None

    # Bot's decision state
    bot_confidence_in_position: float = 0.0  # 0-100
    bot_reasoning: str = ""
    signals_still_agreeing: bool = False
    num_strategies_still_voting: int = 0

    # Events that occurred
    events: List[str] = field(default_factory=list)

    # Any special notes
    notes: str = ""


@dataclass
class TradeStateHistory:
    """Complete history of bot's state during a trade."""
    trade_id: str
    symbol: str
    side: str  # BUY or SELL

    # Timeline
    entry_time: float
    entry_price: float
    initial_state: Optional[BotStateSnapshot] = None

    # State evolution
    state_snapshots: List[BotStateSnapshot] = field(default_factory=list)

    # Exit
    exit_time: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # "tp1_hit", "sl_hit", "manual", "trailing"
    final_state: Optional[BotStateSnapshot] = None

    # Analysis
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_time_minutes: Optional[float] = None


class MechanicalBotStateTracker:
    """
    Tracks mechanical bot's state evolution during trades.
    """

    def __init__(self, data_dir: str = "data/llm"):
        self.data_dir = data_dir
        self.state_dir = os.path.join(data_dir, "mechanical_bot_state")
        os.makedirs(self.state_dir, exist_ok=True)

        # State history by trade
        self.trade_states: Dict[str, TradeStateHistory] = {}
        self.state_file = os.path.join(self.state_dir, "state_history.jsonl")

        # Real-time state (current snapshot per trade)
        self.current_states: Dict[str, BotStateSnapshot] = {}

    def start_tracking_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        regime: str,
        volatility: float,
        alignment_score: float,
        initial_confidence: float,
        strategy_votes: int,
    ) -> TradeStateHistory:
        """Start tracking state for a new trade."""
        now = time.time()

        # Create initial state snapshot
        initial_state = BotStateSnapshot(
            state_id=f"{trade_id}_initial",
            trade_id=trade_id,
            phase=TradePhase.SIGNAL_GENERATION,
            timestamp=now,
            current_price=current_price,
            price_change_since_entry_pct=0.0,
            current_regime=regime,
            current_volatility_pct=volatility,
            current_alignment_score=alignment_score,
            bot_confidence_in_position=initial_confidence,
            signals_still_agreeing=True,
            num_strategies_still_voting=strategy_votes,
            events=["trade_started"],
        )

        # Create trade state history
        history = TradeStateHistory(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_time=now,
            entry_price=entry_price,
            initial_state=initial_state,
        )

        self.trade_states[trade_id] = history
        self.current_states[trade_id] = initial_state

        # Persist initial state
        self._save_state_snapshot(initial_state)

        logger.debug(f"Started tracking trade {trade_id} {symbol} {side}")
        return history

    def record_state_change(
        self,
        trade_id: str,
        phase: TradePhase,
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
    ) -> Optional[BotStateSnapshot]:
        """Record a state change for an open trade."""
        if trade_id not in self.trade_states:
            logger.warning(f"Trade {trade_id} not found in state tracking")
            return None

        history = self.trade_states[trade_id]
        now = time.time()

        # Calculate price change
        price_change_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        # Create state snapshot
        snapshot = BotStateSnapshot(
            state_id=f"{trade_id}_{int(now * 1000) % 100000}",
            trade_id=trade_id,
            phase=phase,
            timestamp=now,
            current_price=current_price,
            price_change_since_entry_pct=price_change_pct,
            current_regime=regime,
            current_volatility_pct=volatility,
            current_alignment_score=alignment_score,
            position_pnl=position_pnl,
            position_pnl_pct=position_pnl_pct,
            distance_to_tp1_pct=distance_to_tp1_pct,
            distance_to_sl_pct=distance_to_sl_pct,
            bot_confidence_in_position=bot_confidence or 0.0,
            bot_reasoning=reasoning,
            signals_still_agreeing=signals_still_agreeing,
            num_strategies_still_voting=num_strategies_voting,
            events=events or [],
            notes=notes,
        )

        # Append to history
        history.state_snapshots.append(snapshot)

        # Update current state
        self.current_states[trade_id] = snapshot

        # Persist
        self._save_state_snapshot(snapshot)

        logger.debug(f"Recorded state {phase} for trade {trade_id}")
        return snapshot

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        final_pnl: Optional[float] = None,
        final_pnl_pct: Optional[float] = None,
    ) -> Optional[TradeStateHistory]:
        """Close a trade and finalize state history."""
        if trade_id not in self.trade_states:
            logger.warning(f"Trade {trade_id} not found")
            return None

        history = self.trade_states[trade_id]
        now = time.time()

        # Record final state
        final_state = BotStateSnapshot(
            state_id=f"{trade_id}_final",
            trade_id=trade_id,
            phase=TradePhase.CLOSED,
            timestamp=now,
            current_price=exit_price,
            price_change_since_entry_pct=((exit_price - history.entry_price) / history.entry_price * 100) if history.entry_price > 0 else 0,
            current_regime="",
            current_volatility_pct=0.0,
            current_alignment_score=0.0,
            position_pnl=final_pnl,
            position_pnl_pct=final_pnl_pct,
            bot_confidence_in_position=0.0,
            events=["trade_closed"],
        )

        # Update history
        history.exit_time = now
        history.exit_price = exit_price
        history.exit_reason = exit_reason
        history.final_state = final_state
        history.pnl = final_pnl
        history.pnl_pct = final_pnl_pct

        if history.entry_time:
            history.hold_time_minutes = (now - history.entry_time) / 60

        # Persist final state
        self._save_state_snapshot(final_state)
        self._save_trade_history(history)

        # Remove from current states
        if trade_id in self.current_states:
            del self.current_states[trade_id]

        logger.debug(f"Closed trade {trade_id} with exit reason {exit_reason}")
        return history

    def get_trade_state_history(self, trade_id: str) -> Optional[TradeStateHistory]:
        """Get complete state history for a trade."""
        return self.trade_states.get(trade_id)

    def get_current_state(self, trade_id: str) -> Optional[BotStateSnapshot]:
        """Get current state snapshot for a trade."""
        return self.current_states.get(trade_id)

    def get_all_open_trades_states(self) -> Dict[str, BotStateSnapshot]:
        """Get current states of all open trades."""
        return dict(self.current_states)

    def analyze_state_evolution(self, trade_id: str) -> Dict[str, Any]:
        """Analyze how bot's state evolved during a trade."""
        history = self.trade_states.get(trade_id)
        if not history or not history.state_snapshots:
            return {"status": "no_data"}

        snapshots = history.state_snapshots

        # Analyze confidence evolution
        confidences = [s.bot_confidence_in_position for s in snapshots]
        confidence_trend = "stable"
        if len(confidences) > 1:
            trend_direction = confidences[-1] - confidences[0]
            if trend_direction > 5:
                confidence_trend = "increasing"
            elif trend_direction < -5:
                confidence_trend = "decreasing"

        # Identify key moments
        key_moments = []
        for snapshot in snapshots:
            if snapshot.events:
                key_moments.append({
                    "timestamp": snapshot.timestamp,
                    "phase": snapshot.phase,
                    "events": snapshot.events,
                    "pnl_pct": snapshot.position_pnl_pct,
                })

        # Analyze when bot lost/gained confidence
        confidence_drops = []
        for i in range(1, len(snapshots)):
            drop = snapshots[i-1].bot_confidence_in_position - snapshots[i].bot_confidence_in_position
            if drop > 10:
                confidence_drops.append({
                    "timestamp": snapshots[i].timestamp,
                    "drop_magnitude": drop,
                    "phase": snapshots[i].phase,
                    "reason": snapshots[i].bot_reasoning,
                })

        return {
            "trade_id": trade_id,
            "total_state_changes": len(snapshots),
            "initial_confidence": confidences[0] if confidences else 0,
            "final_confidence": confidences[-1] if confidences else 0,
            "confidence_trend": confidence_trend,
            "max_confidence": max(confidences) if confidences else 0,
            "min_confidence": min(confidences) if confidences else 0,
            "key_moments": key_moments,
            "major_confidence_drops": confidence_drops,
            "hold_time_minutes": history.hold_time_minutes,
            "exit_reason": history.exit_reason,
            "final_pnl": history.pnl,
        }

    def get_phase_statistics(self) -> Dict[TradePhase, Dict]:
        """Analyze which phases occur most frequently."""
        phase_counts = defaultdict(int)
        phase_pnl = defaultdict(float)
        phase_trade_count = defaultdict(int)

        for history in self.trade_states.values():
            for snapshot in history.state_snapshots:
                phase_counts[snapshot.phase] += 1

            # Assign trade outcome to phases
            for snapshot in history.state_snapshots:
                if history.pnl:
                    phase_pnl[snapshot.phase] += history.pnl
                    phase_trade_count[snapshot.phase] += 1

        # Calculate statistics
        stats = {}
        for phase in TradePhase:
            if phase_counts[phase] > 0:
                avg_pnl = phase_pnl[phase] / phase_trade_count[phase] if phase_trade_count[phase] > 0 else 0
                stats[phase] = {
                    "occurrences": phase_counts[phase],
                    "trades_passing_through": phase_trade_count[phase],
                    "avg_pnl": avg_pnl,
                }

        return stats

    def _save_state_snapshot(self, snapshot: BotStateSnapshot) -> None:
        """Persist state snapshot to disk."""
        try:
            with open(self.state_file, "a") as f:
                data = {
                    "state_id": snapshot.state_id,
                    "trade_id": snapshot.trade_id,
                    "phase": snapshot.phase,
                    "timestamp": snapshot.timestamp,
                    "current_price": snapshot.current_price,
                    "price_change_since_entry_pct": snapshot.price_change_since_entry_pct,
                    "current_regime": snapshot.current_regime,
                    "position_pnl_pct": snapshot.position_pnl_pct,
                    "bot_confidence_in_position": snapshot.bot_confidence_in_position,
                    "events": snapshot.events,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save state snapshot: {e}")

    def _save_trade_history(self, history: TradeStateHistory) -> None:
        """Persist complete trade history."""
        history_file = os.path.join(self.state_dir, f"trade_{history.trade_id}.json")
        try:
            with open(history_file, "w") as f:
                data = {
                    "trade_id": history.trade_id,
                    "symbol": history.symbol,
                    "side": history.side,
                    "entry_time": history.entry_time,
                    "entry_price": history.entry_price,
                    "exit_time": history.exit_time,
                    "exit_price": history.exit_price,
                    "exit_reason": history.exit_reason,
                    "pnl": history.pnl,
                    "pnl_pct": history.pnl_pct,
                    "hold_time_minutes": history.hold_time_minutes,
                    "num_state_changes": len(history.state_snapshots),
                }
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")


from collections import defaultdict

# Global tracker
_global_tracker: Optional[MechanicalBotStateTracker] = None


def get_mechanical_bot_state_tracker() -> MechanicalBotStateTracker:
    """Get or create global state tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = MechanicalBotStateTracker()
    return _global_tracker
