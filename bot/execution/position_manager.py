"""
Position manager with state machine, progressive trailing stop, and dynamic TP1.

State machine: IDLE -> OPEN -> TP1_HIT -> TRAILING -> CLOSED
                        ↓                              ↑
                        └── CLOSED (SL, EARLY_EXIT) ───┘

Exit behavior is driven by TradeProfile (entry_type + regime + volatility):
- SCALP:  tight SL/TP, high TP1%, tight trailing, very short hold
- MEDIUM: balanced SL/TP, medium TP1%, medium trailing
- TREND:  wide SL/TP, low TP1%, loose trailing, let winners run
- REGIME: conservative defaults

Flow:
1. Open position (IDLE -> OPEN) with TradeProfile attached
2. Monitor price each tick
3. Early exit check (OPEN -> CLOSED if momentum reverses hard)
4. If TP1 hit: partial close (% from profile), SL -> breakeven
5. Trailing stop tightens per profile curve (tight/medium/loose)
6. Profit lock floor per profile (varies by entry_type)
7. If TP2 hit or trailing stop triggered (TRAILING -> CLOSED)
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from execution.position_state import (
    IDLE, OPEN, TP1_HIT, TRAILING, CLOSED, transition,
)
from execution.precision import round_price, round_qty
from execution.trade_profile import TradeProfile, ExitParams, MEDIUM, _BASE_PROFILES

# Mechanical bot instrumentation (TIER 4)
try:
    from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation
    _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE = True
except ImportError:
    _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE = False

logger = logging.getLogger("bot.execution.positions")


@dataclass
class Position:
    """Represents a trading position with full lifecycle state tracking."""
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

    atr: float = 0.0            # ATR at entry (for progressive trailing)
    tp1_close_pct: float = 0.5  # fraction to close at TP1 (matches MEDIUM profile default)

    # State machine
    state: str = IDLE
    state_path: List[str] = field(default_factory=lambda: [IDLE])
    original_qty: float = 0.0
    original_sl: float = 0.0

    # Entry reasons: WHY we opened this position (for EV analysis)
    entry_reasons: Dict[str, Any] = field(default_factory=dict)

    # Trade profile: drives exit behavior (TP1%, trailing, floors)
    trade_profile: Optional[TradeProfile] = None

    # Trailing stop
    trailing_distance: float = 0.0  # absolute distance from peak
    peak_price: float = 0.0         # best price since TP1

    # MFE/MAE tracking (max favorable / adverse excursion from entry)
    highest_price: float = 0.0      # highest price seen during position lifetime
    lowest_price: float = 0.0       # lowest price seen during position lifetime

    # Timestamps
    open_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    close_time: Optional[datetime] = None

    # PnL tracking
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    funding_costs: float = 0.0  # Cumulative funding payments (positive = cost paid)

    # Outcome classification (set on close)
    outcome: str = ""  # CLEAN_WIN, CLEAN_LOSS, TP1_ONLY, TP1_THEN_SL, etc.

    # LLM context: thesis and setup type for exit intelligence
    notes: str = ""          # LLM decision notes (THESIS:..., OUTLOOK:..., etc.)
    setup_type: str = ""     # Classified setup (trend_at_zone, zone_validated, etc.)

    def __post_init__(self):
        if self.original_qty == 0:
            self.original_qty = self.qty
        if self.original_sl == 0:
            self.original_sl = self.sl
        if self.peak_price == 0:
            self.peak_price = self.entry
        if self.highest_price == 0:
            self.highest_price = self.entry
        if self.lowest_price == 0:
            self.lowest_price = self.entry

    # ── Derived properties (backward compat) ──
    @property
    def status(self) -> str:
        return "closed" if self.state == CLOSED else "open"

    @property
    def filled_tp1(self) -> bool:
        return self.state in (TP1_HIT, TRAILING, CLOSED) and TP1_HIT in self.state_path

    @property
    def trailing_active(self) -> bool:
        return self.state == TRAILING

    @property
    def state_path_str(self) -> str:
        return "->".join(self.state_path)

    @property
    def mfe(self) -> float:
        """Max favorable excursion: best unrealized profit during position."""
        if self.side == "LONG":
            return self.highest_price - self.entry
        return self.entry - self.lowest_price

    @property
    def mae(self) -> float:
        """Max adverse excursion: worst unrealized loss during position."""
        if self.side == "LONG":
            return self.entry - self.lowest_price
        return self.highest_price - self.entry

    def _transition(self, target: str, reason: str = "") -> str:
        """Transition to a new state, updating state_path."""
        new = transition(self.symbol, self.state, target, reason)
        if new != self.state:
            self.state = new
            self.state_path.append(new)
        return new


@dataclass
class TradeEvent:
    """Record of a trade action (open, partial close, full close)."""
    symbol: str
    action: str         # "OPEN", "TP1", "TP2", "SL", "TRAILING_STOP", "EARLY_EXIT", etc.
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
    Manages all open positions with state-machine lifecycle.

    Bot-only mode: only manages positions it opened.
    One active position per symbol enforced.
    """

    def __init__(
        self,
        taker_fee_bps: int = 4,
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

    def accrue_funding(self, symbol: str, funding_rate: float, interval_hours: float = 8.0) -> None:
        """Accumulate funding cost on an open position.

        In paper trading, funding isn't deducted automatically like on exchange.
        Call this every tick to track the real cost of holding.

        Args:
            symbol: Position symbol
            funding_rate: Funding rate per interval (e.g., 0.0001 = 0.01% per 8h)
            interval_hours: Funding interval in hours (default 8h for Hyperliquid)
        """
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        if pos.state == CLOSED or pos.qty <= 0:
            return
        # Funding cost per tick: rate * notional * (tick_duration / interval)
        # For a 30s tick in an 8h interval: fraction = 30 / 28800 = 0.00104
        # We approximate: each call = 1 scan interval (~30s)
        scan_interval_s = 30.0
        fraction_of_interval = scan_interval_s / (interval_hours * 3600)
        notional = pos.entry * pos.qty * pos.leverage
        cost = abs(funding_rate) * notional * fraction_of_interval
        if cost > 0:
            pos.funding_costs += cost

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
        tp1_close_pct: float = 0.5,  # Match MEDIUM profile default
        entry_reasons: Optional[Dict[str, Any]] = None,
        trade_profile: Optional[TradeProfile] = None,
        notes: str = "",
        setup_type: str = "",
    ) -> Optional[Position]:
        """Open a new position. Enforces one position per symbol."""
        # Don't open if already have a position in this symbol
        existing = self.positions.get(symbol)
        if existing and existing.state != CLOSED:
            logger.debug(f"[{symbol}] Already have position in state {existing.state}, skipping")
            return None

        # Apply precision rounding
        entry = round_price(symbol, entry)
        sl = round_price(symbol, sl)
        tp1 = round_price(symbol, tp1)
        tp2 = round_price(symbol, tp2)
        qty = round_qty(symbol, qty)
        if qty <= 0:
            logger.warning(f"[{symbol}] Qty rounds to 0, skipping")
            return None

        # Profile-driven trailing distance: SCALP=tight, TREND=loose
        # Fallback: when ATR=0, use profile-aware % of entry instead of flat 1%.
        _style_fallback_pct = {"tight": 0.006, "medium": 0.01, "loose": 0.015}
        _fb_style = trade_profile.exit_params.trailing_style if trade_profile else "medium"
        _trail_fallback = entry * _style_fallback_pct.get(_fb_style, 0.01) if entry > 0 else abs(entry - sl)
        if trade_profile:
            # Use profile's trailing style to scale the ATR multiplier
            style_mult = {
                "tight": 0.8, "medium": 1.0, "loose": 1.5, "none": 1.0,
            }.get(trade_profile.exit_params.trailing_style, 1.0)
            trailing_distance = atr * self.trailing_atr_mult * style_mult if atr > 0 else _trail_fallback
            # Profile overrides tp1_close_pct
            tp1_close_pct = trade_profile.exit_params.tp1_close_pct
        else:
            trailing_distance = atr * self.trailing_atr_mult if atr > 0 else _trail_fallback

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
            atr=atr,
            tp1_close_pct=tp1_close_pct,
            trailing_distance=trailing_distance,
            entry_reasons=entry_reasons or {},
            trade_profile=trade_profile,
            notes=notes,
            setup_type=setup_type,
        )

        # State: IDLE -> OPEN
        pos._transition(OPEN, f"OPEN {side} @ {entry}")

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

        # ── TIER 4: Mechanical Bot Instrumentation (Position Opening Hook) ──
        # Record position opening with all context
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_opened(
                    symbol=symbol,
                    side=side,
                    entry_price=entry,
                    qty=qty,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    leverage=leverage,
                    confidence=confidence,
                    strategy=strategy,
                    entry_reasons=entry_reasons or {},
                    notes=notes,
                    setup_type=setup_type,
                )
            except Exception as e:
                logger.debug(f"[{symbol}] Mechanical bot instrumentation error (position opening): {e}")

        entry_type = trade_profile.entry_type if trade_profile else "UNKNOWN"
        logger.info(
            f"[{symbol}] OPEN {side} @ {entry} qty={qty} "
            f"SL={sl} TP1={tp1} TP2={tp2} "
            f"leverage={leverage}x tp1_close={tp1_close_pct:.0%} "
            f"type={entry_type}"
        )

        return pos

    def update_price(
        self, symbol: str, current_price: float, df_5m=None
    ) -> List[TradeEvent]:
        """
        Process a price update for a position.
        Checks SL, early exit, TP1, trailing stop, TP2 in order.
        SL is checked first to prevent early exit from closing at a worse price.
        df_5m: optional 5m DataFrame for momentum-based early exit.
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        if pos.state == CLOSED:
            return []

        events = []
        is_long = pos.side == "LONG"

        # Track MFE/MAE (max favorable/adverse excursion from entry)
        if current_price > pos.highest_price:
            pos.highest_price = current_price
        if current_price < pos.lowest_price:
            pos.lowest_price = current_price

        # 0. Check stop loss FIRST — on flash crashes, SL must fire before early exit
        # to prevent closing at a worse price than the SL level
        sl_hit = (current_price <= pos.sl) if is_long else (current_price >= pos.sl)
        if sl_hit:
            action = "TRAILING_STOP" if pos.state == TRAILING else "SL"
            event = self._close_position(pos, current_price, action)
            events.append(event)
            return events

        # 1a. Time stop: close positions that haven't hit TP1 after max hold hours.
        # 61.9% of trades exit at SL, most drift for hours then bleed out.
        # Avg hold: 15.5h. An 8h time stop converts slow bleeders into controlled exits.
        # Does NOT affect positions that hit TP1 — those trail profitably (100% WR).
        if pos.state == OPEN:
            hold_hours = (datetime.now(timezone.utc) - pos.open_time).total_seconds() / 3600
            time_stop_hours = getattr(self, '_time_stop_hours', 8)
            if hold_hours >= time_stop_hours:
                logger.info(
                    f"[{symbol}] TIME STOP: held {hold_hours:.1f}h >= {time_stop_hours}h "
                    f"without hitting TP1 — closing at market"
                )
                event = self._close_position(pos, current_price, "TIME_STOP")
                events.append(event)
                return events

        # 1b. Early exit: cut position if momentum accelerating toward SL
        # Only in OPEN state (after TP1, breakeven SL protects us)
        if pos.state == OPEN and df_5m is not None:
            early = self._check_early_exit(pos, current_price, df_5m)
            if early:
                event = self._close_position(pos, current_price, "EARLY_EXIT")
                events.append(event)
                return events

        # 2. Check TP1 (dynamic partial close -> TP1_HIT -> TRAILING)
        if pos.state == OPEN:
            tp1_hit = (current_price >= pos.tp1) if is_long else (current_price <= pos.tp1)
            if tp1_hit:
                event = self._partial_close_tp1(pos, current_price)
                events.append(event)

        # 3. Update trailing stop (if in TRAILING state)
        if pos.state == TRAILING and self.enable_trailing:
            self._update_trailing_stop(pos, current_price)

        # 4. Check TP2 (full close)
        tp2_hit = (current_price >= pos.tp2) if is_long else (current_price <= pos.tp2)
        if tp2_hit and pos.state != CLOSED:
            event = self._close_position(pos, current_price, "TP2")
            events.append(event)

        return events

    # Regime-adaptive early exit thresholds:
    # High-vol/range: cut losers earlier (price reverses fast)
    # Trending: let trades breathe longer (trend may resume)
    _EARLY_EXIT_THRESHOLDS = {
        "high_volatility": {"sl_progress": 0.40, "conditions": 1},
        "panic":           {"sl_progress": 0.35, "conditions": 1},
        "range":           {"sl_progress": 0.45, "conditions": 2},
        "consolidation":   {"sl_progress": 0.50, "conditions": 2},
        "trending_bull":   {"sl_progress": 0.70, "conditions": 3},
        "trending_bear":   {"sl_progress": 0.70, "conditions": 3},
        "trend":           {"sl_progress": 0.70, "conditions": 3},
    }
    _DEFAULT_EARLY_EXIT = {"sl_progress": 0.65, "conditions": 3}

    def _check_early_exit(self, pos: Position, price: float, df_5m) -> bool:
        """
        Detect momentum reversal heading toward SL and cut early.
        Regime-adaptive: high-vol/range cut faster (1-2 conditions at 35-45%),
        trending lets trades breathe (3 conditions at 70%).
        """
        if df_5m is None or df_5m.empty or len(df_5m) < 15:
            return False

        try:
            is_long = pos.side == "LONG"
            stop_dist = abs(pos.entry - pos.original_sl)
            if stop_dist == 0:
                return False

            if is_long:
                sl_progress = (pos.entry - price) / stop_dist
            else:
                sl_progress = (price - pos.entry) / stop_dist

            # If price already past SL (progress > 1.0), let the SL check handle it
            if sl_progress > 1.0:
                return False

            # Regime-adaptive thresholds
            _regime = (pos.entry_reasons or {}).get("regime", "unknown")
            _thresholds = self._EARLY_EXIT_THRESHOLDS.get(_regime, self._DEFAULT_EARLY_EXIT)
            _min_progress = _thresholds["sl_progress"]
            _min_conditions = _thresholds["conditions"]

            if sl_progress < _min_progress:
                return False

            # Count how many exit conditions are met
            _conditions_met = 0

            c = df_5m["close"].astype(float)
            last3 = c.iloc[-3:].values

            # Condition 1: 3 candles accelerating against position
            if is_long:
                accelerating = last3[2] < last3[1] < last3[0]
            else:
                accelerating = last3[2] > last3[1] > last3[0]
            if accelerating:
                _conditions_met += 1

            # Condition 2: EMA5 crossed against EMA13
            ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
            ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
            _ema_cross = (is_long and ema5 < ema13) or (not is_long and ema5 > ema13)
            if _ema_cross:
                _conditions_met += 1

            # Condition 3: SL progress is extreme (>80%)
            if sl_progress >= 0.80:
                _conditions_met += 1

            if _conditions_met >= _min_conditions:
                logger.info(
                    f"[{pos.symbol}] EARLY EXIT ({_regime}): {sl_progress:.0%} toward SL, "
                    f"{_conditions_met}/{_min_conditions} conditions met"
                )
                return True

        except Exception as e:
            logger.debug(f"[{pos.symbol}] Early exit check error: {e}")

        return False

    def _partial_close_tp1(self, pos: Position, price: float) -> TradeEvent:
        """Close tp1_close_pct at TP1, move SL above breakeven, activate trailing."""
        # State: OPEN -> TP1_HIT -> TRAILING
        pos._transition(TP1_HIT, f"TP1 @ {price}")

        # Dynamic TP scaling: adjust close % based on overshoot and move speed
        dynamic_close_pct = pos.tp1_close_pct
        if os.getenv("DYNAMIC_TP_SCALING", "true").lower() in ("1", "true", "yes"):
            # Overshoot: price past TP1 toward TP2 -> take more profit
            tp_range = abs(pos.tp2 - pos.tp1)
            if tp_range > 0:
                if pos.side == "LONG":
                    overshoot = (price - pos.tp1) / tp_range
                else:
                    overshoot = (pos.tp1 - price) / tp_range
                overshoot = max(0.0, overshoot)
                if overshoot > 0.5:
                    dynamic_close_pct = min(dynamic_close_pct * 1.20, 0.90)

            # Speed: fast move to TP1 -> let it run; slow grind -> take profits
            # Only apply speed scaling if position was open > 60s (avoids test artifacts)
            time_to_tp1_s = (datetime.now(timezone.utc) - pos.open_time).total_seconds()
            if time_to_tp1_s > 60:
                if time_to_tp1_s < 1800:  # < 30 min -- fast runner
                    dynamic_close_pct *= 0.85
                elif time_to_tp1_s > 14400:  # > 4 hours -- slow grind
                    # Only increase TP1% if not in a clean trend (let trends run)
                    regime = pos.entry_reasons.get("regime", "unknown")
                    if regime not in ("trending_bull", "trending_bear", "trend", "trending"):
                        dynamic_close_pct = min(dynamic_close_pct * 1.10, 0.85)

            if dynamic_close_pct != pos.tp1_close_pct:
                logger.info(
                    f"[{pos.symbol}] Dynamic TP: close_pct "
                    f"{pos.tp1_close_pct:.0%} -> {dynamic_close_pct:.0%}"
                )

        close_qty = round_qty(pos.symbol, pos.qty * dynamic_close_pct)
        # Guard: if close_qty rounds to full qty, keep minimum remainder for trailing
        remaining_after = round_qty(pos.symbol, pos.qty - close_qty)
        if remaining_after <= 0 and pos.qty > close_qty:
            # Rounding ate everything — reduce close_qty to preserve minimum remainder
            close_qty = round_qty(pos.symbol, pos.qty * 0.90)  # Close 90% max
        if close_qty <= 0 or close_qty >= pos.qty:
            # Degenerate case: close everything as a full TP1 close
            return self._close_position(pos, price, "TP1_FULL")
        fee = self._fee(price, close_qty)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * close_qty * pos.leverage
        else:
            pnl = (pos.entry - price) * close_qty * pos.leverage

        # Proportionally allocate funding costs to TP1 partial close
        # (prevents dumping all funding onto final close, distorting per-leg PnL)
        funding_share = pos.funding_costs * (close_qty / pos.qty) if pos.qty > 0 else 0.0
        pos.realized_pnl += (pnl - fee - funding_share)
        pos.funding_costs -= funding_share  # Reduce remaining balance for final close
        pos.qty = round_qty(pos.symbol, pos.qty - close_qty)

        # Move SL to breakeven accounting for locked-in TP1 profit.
        # The remaining position has a cost basis adjusted by the profit already banked.
        # This prevents premature SL hits by giving the remaining qty more room.
        # Formula: breakeven = entry - (locked_pnl / (remaining_qty * leverage)) for LONG
        remaining_qty = pos.qty
        fee_buffer = pos.entry * (self.taker_fee_bps * 2 / 10000.0 + 0.001)
        if remaining_qty > 0 and pos.leverage > 0:
            # How much room does the locked-in profit give us?
            profit_cushion = pos.realized_pnl / (remaining_qty * pos.leverage)
            if pos.side == "LONG":
                # Entry - cushion = adjusted breakeven (lower = more room)
                be_price = pos.entry - profit_cushion + fee_buffer
                pos.sl = round_price(pos.symbol, be_price)
            else:
                be_price = pos.entry + profit_cushion - fee_buffer
                pos.sl = round_price(pos.symbol, be_price)
        else:
            # Fallback to simple breakeven
            if pos.side == "LONG":
                pos.sl = round_price(pos.symbol, pos.entry + fee_buffer)
            else:
                pos.sl = round_price(pos.symbol, pos.entry - fee_buffer)

        pos.peak_price = price

        # TP1_HIT -> TRAILING
        pos._transition(TRAILING, "trailing activated")

        # ── TIER 4: Mechanical Bot Instrumentation (State Change Hook: TP1_HIT) ──
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_state_change(
                    symbol=pos.symbol,
                    from_state=TP1_HIT,
                    to_state=TRAILING,
                    trigger="TP1_HIT",
                    price=price,
                    context={
                        'partial_close_qty': close_qty,
                        'partial_close_pct': dynamic_close_pct,
                        'realized_pnl': pnl,
                        'new_sl': pos.sl,
                        'remaining_qty': pos.qty,
                    }
                )
            except Exception as e:
                logger.debug(f"[{pos.symbol}] Mechanical bot instrumentation error (state change): {e}")

        logger.info(
            f"[{pos.symbol}] TP1 @ {price} | Closed {close_qty} ({dynamic_close_pct:.0%}) | "
            f"PnL={pnl:.2f} | SL->BE+={pos.sl} | Trailing ON"
        )

        event = TradeEvent(
            symbol=pos.symbol,
            action="TP1",
            side=pos.side,
            price=price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            metadata={
                "remaining_qty": pos.qty,
                "new_sl": pos.sl,
                "tp1_close_pct": dynamic_close_pct,
                "entry_reasons": pos.entry_reasons,
                "num_agree": (pos.entry_reasons or {}).get("num_agree", 0),
                "strategies_agree": (pos.entry_reasons or {}).get("strategies_agree", []),
                "entry": pos.entry,
                "sl": pos.original_sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "confidence": pos.confidence,
            },
        )
        self.trade_log.append(event)
        return event

    def _update_trailing_stop(self, pos: Position, current_price: float):
        """
        Progressive trailing stop with profit lock floor.
        Tighten curve and floor are driven by TradeProfile when available:
        - SCALP:  fast tightening (0.80->0.50), early floor (20%)
        - MEDIUM: standard (0.67->0.33), floor at 30%
        - TREND:  slow tightening (0.50->0.25), late floor (35%)
        """
        is_long = pos.side == "LONG"

        if is_long:
            if current_price > pos.peak_price:
                pos.peak_price = current_price
        else:
            if current_price < pos.peak_price:
                pos.peak_price = current_price

        if is_long:
            total_range = pos.tp2 - pos.entry
            peak_move = pos.peak_price - pos.entry
        else:
            total_range = pos.entry - pos.tp2
            peak_move = pos.entry - pos.peak_price

        progress = min(peak_move / total_range, 1.0) if total_range > 0 else 0.0

        # Profile-driven tighten curve (falls back to MEDIUM defaults)
        ep = pos.trade_profile.exit_params if pos.trade_profile else _BASE_PROFILES[MEDIUM]
        tighten_start = ep.trailing_tighten_start
        tighten_end = ep.trailing_tighten_end
        tighten_range = tighten_start - tighten_end
        tighten_factor = max(tighten_start - progress * tighten_range, tighten_end)
        effective_distance = pos.trailing_distance * tighten_factor

        if is_long:
            trailing_sl = pos.peak_price - effective_distance
        else:
            trailing_sl = pos.peak_price + effective_distance

        # Profile-driven profit lock floor
        floor_start = ep.floor_progress_start
        floor_lock_start = ep.floor_lock_start
        floor_lock_max = ep.floor_lock_max

        floor_sl = None
        if progress > floor_start and peak_move > 0:
            lock_pct = min(
                floor_lock_start + (progress - floor_start) * 0.5,
                floor_lock_max,
            )
            if is_long:
                floor_sl = pos.entry + peak_move * lock_pct
            else:
                floor_sl = pos.entry - peak_move * lock_pct
        elif peak_move > 0:
            # Minimum post-TP1 floor: guarantee at least breakeven + fees.
            # Without this, a sharp reversal after TP1 can erase the entire gain.
            fee_buffer = pos.entry * self.taker_fee_bps * 2 / 10000.0
            if is_long:
                floor_sl = pos.entry + fee_buffer
            else:
                floor_sl = pos.entry - fee_buffer

        new_sl = trailing_sl
        if floor_sl is not None:
            if is_long:
                new_sl = max(trailing_sl, floor_sl)
            else:
                new_sl = min(trailing_sl, floor_sl)

        new_sl = round_price(pos.symbol, new_sl)

        # Only move SL in the protective direction
        if is_long and new_sl > pos.sl:
            old_sl = pos.sl
            pos.sl = new_sl
            logger.info(
                f"[{pos.symbol}] Trail SL: {old_sl} -> {new_sl} "
                f"(peak={pos.peak_price} prog={progress:.0%})"
            )
        elif not is_long and new_sl < pos.sl:
            old_sl = pos.sl
            pos.sl = new_sl
            logger.info(
                f"[{pos.symbol}] Trail SL: {old_sl} -> {new_sl} "
                f"(peak={pos.peak_price} prog={progress:.0%})"
            )

    def _classify_outcome(self, pos: Position, action: str) -> str:
        """Classify the trade outcome for learning hooks."""
        tp1_was_hit = TP1_HIT in pos.state_path
        win = pos.realized_pnl > 0

        if action == "TP2":
            return "CLEAN_WIN"
        elif action == "EARLY_EXIT":
            return "EARLY_EXIT_SAVE" if pos.realized_pnl > -(abs(pos.entry - pos.original_sl) * pos.original_qty * pos.leverage * 0.25) else "EARLY_EXIT_FAIL"
        elif action == "TRAILING_STOP":
            return "TRAILING_WIN" if win else "TRAILING_FAIL"
        elif action in ("ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE"):
            return "ROTATION_WIN" if win else "ROTATION_LOSS_AVOIDANCE"
        elif action == "SL":
            if tp1_was_hit:
                return "TP1_THEN_SL"
            return "CLEAN_LOSS"
        elif tp1_was_hit and not win:
            return "TP1_ONLY"
        else:
            return "CLEAN_LOSS" if not win else "CLEAN_WIN"

    def _close_position(self, pos: Position, price: float, action: str) -> TradeEvent:
        """Fully close a position with state transition."""
        qty = pos.qty
        fee = self._fee(price, qty)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * qty * pos.leverage
        else:
            pnl = (pos.entry - price) * qty * pos.leverage

        # Deduct accumulated funding costs at final close
        pos.realized_pnl += (pnl - fee - pos.funding_costs)
        pos.qty = 0
        pos.close_time = datetime.now(timezone.utc)

        # Classify outcome before closing state
        pos.outcome = self._classify_outcome(pos, action)

        # State -> CLOSED
        pos._transition(CLOSED, f"{action} @ {price}")

        # ── TIER 4: Mechanical Bot Instrumentation (Position Closing Hook) ──
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_closed(
                    symbol=pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    exit_action=action,  # "SL", "TP1", "TP2", "TRAILING", "EARLY_EXIT", etc.
                    exit_qty=qty,
                    entry_price=pos.entry,
                    pnl=pos.realized_pnl,
                    total_fees=pos.fees_paid,
                    funding_costs=pos.funding_costs,
                    outcome=pos.outcome,
                    hold_duration_seconds=(pos.close_time - pos.open_time).total_seconds(),
                    entry_reasons=pos.entry_reasons or {},
                    notes=pos.notes,
                    setup_type=pos.setup_type,
                )
            except Exception as e:
                logger.debug(f"[{pos.symbol}] Mechanical bot instrumentation error (position closing): {e}")

        logger.info(
            f"[{pos.symbol}] {action} @ {price} | PnL={pnl:.2f} | "
            f"Total={pos.realized_pnl:.2f} | Fees={pos.fees_paid:.2f} | "
            f"Funding={pos.funding_costs:.2f} | "
            f"Outcome={pos.outcome} | Path={pos.state_path_str}"
        )

        profile_data = pos.trade_profile.to_dict() if pos.trade_profile else {}

        event = TradeEvent(
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
                "funding_costs": pos.funding_costs,
                "hold_time_s": (pos.close_time - pos.open_time).total_seconds(),
                "peak_price": pos.peak_price,
                "outcome": pos.outcome,
                "state_path": pos.state_path_str,
                "entry_reasons": pos.entry_reasons,
                "num_agree": (pos.entry_reasons or {}).get("num_agree", 0),
                "strategies_agree": (pos.entry_reasons or {}).get("strategies_agree", []),
                "entry_type": profile_data.get("entry_type", "UNKNOWN"),
                "primary_driver": profile_data.get("primary_driver", ""),
                "regime": (pos.entry_reasons or {}).get("regime", "") or profile_data.get("regime", ""),
                "volatility_band": profile_data.get("volatility_band", ""),
                "trade_profile": profile_data,
                # Position context for CSV analysis
                "entry": pos.entry,
                "sl": pos.original_sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "confidence": pos.confidence,
            },
        )
        self.trade_log.append(event)
        return event

    def force_close(self, symbol: str, price: float, reason: str = "EMERGENCY") -> Optional[TradeEvent]:
        """Force close a position (circuit breaker, liquidation avoidance, etc.)."""
        pos = self.positions.get(symbol)
        if not pos or pos.state == CLOSED:
            return None
        return self._close_position(pos, price, reason)

    # Profile-specific max hold hours: prevents stale positions from lingering
    _PROFILE_MAX_HOLD_HOURS = {
        "SCALP": 4,
        "MEDIUM": 12,
        "TREND": 36,
        "REGIME": 48,
    }

    def check_hold_limits(
        self, symbol: str, price: float, max_hold_hours: float = 48, action: str = "tighten_sl"
    ) -> Optional[TradeEvent]:
        """Check if a position has exceeded its max hold time.

        At max_hold_hours: tighten SL to breakeven (or force close if action='force_close').
        At 1.5x max_hold_hours: force close regardless.

        Uses profile-specific hold limits if a trade profile is attached.
        Returns TradeEvent if position was force-closed, None otherwise.
        """
        pos = self.positions.get(symbol)
        if not pos or pos.state == CLOSED:
            return None

        if pos.open_time is None:
            return None

        # Use profile-specific hold limit (always apply, use min of config and profile)
        if pos.trade_profile:
            entry_type = pos.trade_profile.entry_type
            profile_max = self._PROFILE_MAX_HOLD_HOURS.get(entry_type)
            if profile_max is not None:
                max_hold_hours = min(max_hold_hours, profile_max)

        now = datetime.now(timezone.utc)
        if isinstance(pos.open_time, datetime):
            age_hours = (now - pos.open_time).total_seconds() / 3600
        else:
            age_hours = (now.timestamp() - pos.open_time) / 3600

        force_close_hours = max_hold_hours * 1.5

        if age_hours >= force_close_hours:
            # Hard limit: force close
            logger.warning(
                f"[HOLD_LIMIT] {symbol} {pos.side} open {age_hours:.1f}h "
                f">= {force_close_hours:.0f}h hard limit — FORCE CLOSING"
            )
            return self.force_close(symbol, price, reason="HOLD_LIMIT")

        if age_hours >= max_hold_hours:
            if action == "force_close":
                logger.warning(
                    f"[HOLD_LIMIT] {symbol} {pos.side} open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — FORCE CLOSING (action=force_close)"
                )
                return self.force_close(symbol, price, reason="HOLD_LIMIT")

            # Default: tighten SL to breakeven
            if pos.side == "LONG" and pos.sl < pos.entry:
                old_sl = pos.sl
                pos.sl = pos.entry
                logger.info(
                    f"[HOLD_LIMIT] {symbol} LONG open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — SL tightened {old_sl:.2f} -> {pos.entry:.2f} (breakeven)"
                )
            elif pos.side == "SHORT" and pos.sl > pos.entry:
                old_sl = pos.sl
                pos.sl = pos.entry
                logger.info(
                    f"[HOLD_LIMIT] {symbol} SHORT open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — SL tightened {old_sl:.2f} -> {pos.entry:.2f} (breakeven)"
                )

        return None

    def get_open_positions(self) -> Dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.state != CLOSED}

    def get_open_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.state != CLOSED)

    def get_total_open_notional(self) -> float:
        """Sum of all open position notional values (qty * entry * leverage)."""
        total = 0.0
        for pos in self.positions.values():
            if pos.state != CLOSED:
                total += pos.qty * pos.entry * pos.leverage
        return total

    def check_portfolio_notional_cap(
        self, new_notional: float, equity: float, max_portfolio_leverage: float = 5.0,
    ) -> bool:
        """Check if adding a new position would exceed aggregate portfolio leverage cap.

        Returns True if the new position is allowed, False if it would breach the cap.
        """
        current_notional = self.get_total_open_notional()
        cap = equity * max_portfolio_leverage
        if current_notional + new_notional > cap:
            logger.warning(
                f"[PORTFOLIO-CAP] Rejected: current_notional=${current_notional:.0f} + "
                f"new=${new_notional:.0f} > cap=${cap:.0f} "
                f"(equity=${equity:.0f} * {max_portfolio_leverage}x)"
            )
            return False
        return True

    def get_total_unrealized_pnl(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos.state == CLOSED or symbol not in prices:
                continue
            price = prices[symbol]
            if pos.side == "LONG":
                total += (price - pos.entry) * pos.qty * pos.leverage
            else:
                total += (pos.entry - price) * pos.qty * pos.leverage
        return total

    def get_trade_summary(self) -> Dict[str, Any]:
        """Summary of all trades taken."""
        closed = [e for e in self.trade_log if e.action in
                  ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT", "EMERGENCY",
                   "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE", "BACKTEST_END", "HOLD_LIMIT",
                   "CIRCUIT_BREAKER")]
        opens = [e for e in self.trade_log if e.action == "OPEN"]
        if not closed:
            return {"total_trades": 0, "positions_opened": len(opens), "close_events": 0}

        wins = [e for e in closed if e.pnl > 0]
        losses = [e for e in closed if e.pnl <= 0]
        total_pnl = sum(e.pnl for e in closed)
        # Include entry fees (OPEN events) + exit fees for accurate total
        total_fees = sum(e.fee for e in closed) + sum(e.fee for e in opens)

        gross_wins = sum(e.pnl for e in wins)
        gross_losses = abs(sum(e.pnl for e in losses))
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 99.0

        return {
            "positions_opened": len(opens),
            "close_events": len(closed),
            "total_trades": len(closed),  # backwards compat
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) if closed else 0,
            "total_pnl": total_pnl,
            "gross_pnl": total_pnl,
            "total_fees": total_fees,
            "net_pnl": total_pnl - total_fees,
            "profit_factor": profit_factor,
            "avg_win": sum(e.pnl for e in wins) / len(wins) if wins else 0,
            "avg_loss": sum(e.pnl for e in losses) / len(losses) if losses else 0,
            "by_action": {
                action: sum(1 for e in closed if e.action == action)
                for action in ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT", "EMERGENCY",
                               "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE", "BACKTEST_END", "HOLD_LIMIT",
                               "CIRCUIT_BREAKER")
            },
        }
