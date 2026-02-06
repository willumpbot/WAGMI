"""
Position manager with trailing stop loss.
Handles position lifecycle: open -> TP1 partial -> trailing stop -> TP2/close.

Flow:
1. Open position with entry, SL, TP1, TP2
2. Monitor price each tick
3. If TP1 hit: close 40%, move SL to breakeven, activate trailing stop
4. Trailing stop follows price by ATR*multiplier
5. If TP2 hit or trailing stop triggered: close remaining
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

logger = logging.getLogger("bot.execution.positions")


@dataclass
class Position:
    """Represents an open trading position."""
    symbol: str
    side: str               # "LONG" or "SHORT"
    entry: float
    qty: float
    sl: float               # current stop loss (may move with trailing)
    tp1: float
    tp2: float
    leverage: float = 1.0
    mode: str = "spot"      # "spot" or "leverage"
    strategy: str = ""
    confidence: float = 0.0

    # State
    status: str = "open"    # "open", "closed"
    filled_tp1: bool = False
    original_qty: float = 0.0
    original_sl: float = 0.0

    # Trailing stop
    trailing_active: bool = False
    trailing_distance: float = 0.0  # absolute distance from peak
    peak_price: float = 0.0         # best price since TP1

    # Timestamps
    open_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    close_time: Optional[datetime] = None

    # PnL tracking
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def __post_init__(self):
        if self.original_qty == 0:
            self.original_qty = self.qty
        if self.original_sl == 0:
            self.original_sl = self.sl
        if self.peak_price == 0:
            self.peak_price = self.entry


@dataclass
class TradeEvent:
    """Record of a trade action (open, partial close, full close)."""
    symbol: str
    action: str         # "OPEN", "TP1", "TP2", "SL", "TRAILING_STOP", "EMERGENCY"
    side: str
    price: float
    qty: float
    pnl: float = 0.0
    fee: float = 0.0
    leverage: float = 1.0
    strategy: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


class PositionManager:
    """
    Manages all open positions with TP/SL/trailing stop logic.

    Trailing stop behavior:
    - Activates after TP1 is hit
    - Trails price by trailing_stop_distance (ATR * multiplier)
    - Updates each tick to lock in profits as price moves favorably
    - Closes position when price retraces to trailing stop level
    """

    def __init__(
        self,
        taker_fee_bps: int = 5,
        enable_trailing: bool = True,
        trailing_atr_mult: float = 1.5,
    ):
        self.positions: Dict[str, Position] = {}
        self.trade_log: List[TradeEvent] = []
        self.taker_fee_bps = taker_fee_bps
        self.enable_trailing = enable_trailing
        self.trailing_atr_mult = trailing_atr_mult

    def _fee(self, price: float, qty: float) -> float:
        return price * qty * (self.taker_fee_bps / 10000.0)

    def open_position(
        self,
        symbol: str,
        side: str,
        entry: float,
        qty: float,
        sl: float,
        tp1: float,
        tp2: float,
        atr: float = 0.0,
        leverage: float = 1.0,
        mode: str = "spot",
        strategy: str = "",
        confidence: float = 0.0,
    ) -> Optional[Position]:
        """Open a new position."""
        # Don't open if already have a position in this symbol
        if symbol in self.positions and self.positions[symbol].status == "open":
            logger.warning(f"[{symbol}] Already have open position, skipping")
            return None

        trailing_distance = atr * self.trailing_atr_mult if atr > 0 else abs(entry - sl)

        pos = Position(
            symbol=symbol,
            side=side,
            entry=entry,
            qty=qty,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            leverage=leverage,
            mode=mode,
            strategy=strategy,
            confidence=confidence,
            trailing_distance=trailing_distance,
        )

        self.positions[symbol] = pos

        fee = self._fee(entry, qty)
        pos.fees_paid += fee

        event = TradeEvent(
            symbol=symbol,
            action="OPEN",
            side=side,
            price=entry,
            qty=qty,
            fee=fee,
            leverage=leverage,
            strategy=strategy,
        )
        self.trade_log.append(event)

        logger.info(
            f"[{symbol}] OPEN {side} @ {entry:.4f} qty={qty:.6f} "
            f"SL={sl:.4f} TP1={tp1:.4f} TP2={tp2:.4f} "
            f"leverage={leverage}x trail_dist={trailing_distance:.4f}"
        )

        return pos

    def update_price(self, symbol: str, current_price: float) -> List[TradeEvent]:
        """
        Process a price update for a position.
        Checks SL, TP1, trailing stop, TP2 in order.
        Returns list of trade events that occurred.
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        if pos.status != "open":
            return []

        events = []
        is_long = pos.side == "LONG"

        # 1. Check stop loss (including trailing stop)
        sl_hit = (current_price <= pos.sl) if is_long else (current_price >= pos.sl)
        if sl_hit:
            action = "TRAILING_STOP" if pos.trailing_active else "SL"
            event = self._close_position(pos, current_price, action)
            events.append(event)
            return events

        # 2. Check TP1 (40% partial close + move SL to breakeven + activate trailing)
        if not pos.filled_tp1:
            tp1_hit = (current_price >= pos.tp1) if is_long else (current_price <= pos.tp1)
            if tp1_hit:
                event = self._partial_close_tp1(pos, current_price)
                events.append(event)

        # 3. Update trailing stop (if active)
        if pos.trailing_active and self.enable_trailing:
            self._update_trailing_stop(pos, current_price)

        # 4. Check TP2 (full close)
        tp2_hit = (current_price >= pos.tp2) if is_long else (current_price <= pos.tp2)
        if tp2_hit:
            event = self._close_position(pos, current_price, "TP2")
            events.append(event)

        return events

    def _partial_close_tp1(self, pos: Position, price: float) -> TradeEvent:
        """Close 40% at TP1, move SL to breakeven, activate trailing stop."""
        close_qty = pos.qty * 0.4
        fee = self._fee(price, close_qty)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * close_qty * pos.leverage
        else:
            pnl = (pos.entry - price) * close_qty * pos.leverage

        pos.realized_pnl += (pnl - fee)
        pos.qty -= close_qty
        pos.filled_tp1 = True
        pos.sl = pos.entry  # Move SL to breakeven
        pos.trailing_active = True
        pos.peak_price = price

        logger.info(
            f"[{pos.symbol}] TP1 @ {price:.4f} | Closed {close_qty:.6f} | "
            f"PnL={pnl:.2f} | SL->BE={pos.entry:.4f} | Trailing ON"
        )

        return TradeEvent(
            symbol=pos.symbol,
            action="TP1",
            side=pos.side,
            price=price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            metadata={"remaining_qty": pos.qty, "new_sl": pos.sl},
        )

    def _update_trailing_stop(self, pos: Position, current_price: float):
        """Update the trailing stop based on current price."""
        is_long = pos.side == "LONG"

        # Update peak price
        if is_long:
            if current_price > pos.peak_price:
                pos.peak_price = current_price
                new_sl = pos.peak_price - pos.trailing_distance
                # Only move SL up (for longs), never down
                if new_sl > pos.sl:
                    old_sl = pos.sl
                    pos.sl = new_sl
                    logger.info(
                        f"[{pos.symbol}] Trailing SL: {old_sl:.4f} -> {new_sl:.4f} "
                        f"(peak={pos.peak_price:.4f})"
                    )
        else:
            if current_price < pos.peak_price:
                pos.peak_price = current_price
                new_sl = pos.peak_price + pos.trailing_distance
                # Only move SL down (for shorts), never up
                if new_sl < pos.sl:
                    old_sl = pos.sl
                    pos.sl = new_sl
                    logger.info(
                        f"[{pos.symbol}] Trailing SL: {old_sl:.4f} -> {new_sl:.4f} "
                        f"(peak={pos.peak_price:.4f})"
                    )

    def _close_position(self, pos: Position, price: float, action: str) -> TradeEvent:
        """Fully close a position."""
        qty = pos.qty
        fee = self._fee(price, qty)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * qty * pos.leverage
        else:
            pnl = (pos.entry - price) * qty * pos.leverage

        pos.realized_pnl += (pnl - fee)
        pos.qty = 0
        pos.status = "closed"
        pos.close_time = datetime.now(timezone.utc)

        logger.info(
            f"[{pos.symbol}] {action} @ {price:.4f} | PnL={pnl:.2f} | "
            f"Total PnL={pos.realized_pnl:.2f} | Fees={pos.fees_paid:.2f}"
        )

        return TradeEvent(
            symbol=pos.symbol,
            action=action,
            side=pos.side,
            price=price,
            qty=qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            metadata={
                "total_pnl": pos.realized_pnl,
                "total_fees": pos.fees_paid,
                "hold_time_s": (pos.close_time - pos.open_time).total_seconds(),
                "trailing_was_active": pos.trailing_active,
                "peak_price": pos.peak_price,
            },
        )

    def force_close(self, symbol: str, price: float, reason: str = "EMERGENCY") -> Optional[TradeEvent]:
        """Force close a position (circuit breaker, liquidation avoidance, etc.)."""
        if symbol not in self.positions or self.positions[symbol].status != "open":
            return None
        return self._close_position(self.positions[symbol], price, reason)

    def get_open_positions(self) -> Dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.status == "open"}

    def get_open_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.status == "open")

    def get_total_unrealized_pnl(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos.status != "open" or symbol not in prices:
                continue
            price = prices[symbol]
            if pos.side == "LONG":
                total += (price - pos.entry) * pos.qty * pos.leverage
            else:
                total += (pos.entry - price) * pos.qty * pos.leverage
        return total

    def get_trade_summary(self) -> Dict[str, Any]:
        """Summary of all trades taken."""
        closed = [e for e in self.trade_log if e.action in ("SL", "TP1", "TP2", "TRAILING_STOP", "EMERGENCY")]
        if not closed:
            return {"total_trades": 0}

        wins = [e for e in closed if e.pnl > 0]
        losses = [e for e in closed if e.pnl <= 0]
        total_pnl = sum(e.pnl for e in closed)
        total_fees = sum(e.fee for e in closed)

        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) if closed else 0,
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "net_pnl": total_pnl - total_fees,
            "avg_win": sum(e.pnl for e in wins) / len(wins) if wins else 0,
            "avg_loss": sum(e.pnl for e in losses) / len(losses) if losses else 0,
            "by_action": {
                action: sum(1 for e in closed if e.action == action)
                for action in ("SL", "TP1", "TP2", "TRAILING_STOP", "EMERGENCY")
            },
        }
