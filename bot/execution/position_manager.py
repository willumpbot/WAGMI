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

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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


def _get_tel():
    """Lazy import to avoid circular dependency."""
    try:
        from core.structured_logging import get_trade_event_logger
        return get_trade_event_logger()
    except Exception:
        return None


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

    # Timestamp tracking
    opened_at: Optional[Any] = None  # datetime when position opened

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

    # Wallet attribution (dual-wallet system)
    wallet_id: str = ""      # "A", "B", or "" (single-wallet mode)

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
        time_stop_hours: int = 12,
    ):
        self.positions: Dict[str, Position] = {}
        self.trade_log: List[TradeEvent] = []
        self.taker_fee_bps = taker_fee_bps
        self.enable_trailing = enable_trailing
        self.trailing_atr_mult = trailing_atr_mult
        self._time_stop_hours = time_stop_hours
        # Setup-specific time stops from 2,172-signal analysis
        # Each setup has an optimal hold window where WR peaks.
        self._setup_time_stops = {
            "BTC_BUY_BB": 8,     # 4-8h optimal, 69% WR at 4h
            "BTC_SELL_BB": 8,    # peaks at 8h (63% WR), 12h drops to 54%
            "ETH_SELL_BB": 8,    # 4-8h optimal, 70% WR at 4h
            "ETH_BUY_BB": 8,    # 8h optimal (64% WR)
            "SOL_BUY_BB": 6,    # peaks at 4h (67%), decays fast
            "SOL_SELL_BB": 8,    # 8h reasonable
            "HYPE_BUY_BB": 6,   # shorter hold for volatile asset
        }
        # Post-close cooldown: prevent tilt re-entry after losses only
        self._last_close_time: Dict[str, datetime] = {}  # symbol -> close time
        self._last_close_won: Dict[str, bool] = {}  # symbol -> was it a win?
        self._reentry_cooldown_minutes: int = 10  # 10 min cooldown after losses only
        # Position backup directory for crash recovery
        self._backup_dir = Path("data") / "position_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _fee(self, price: float, qty: float) -> float:
        return price * qty * (self.taker_fee_bps / 10000.0)

    def _backup_position(self, pos: 'Position') -> None:
        """Persist position SL/TP to disk for crash recovery."""
        try:
            backup_file = self._backup_dir / f"{pos.symbol.replace('/', '_')}.json"
            backup_data = {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry": pos.entry,
                "qty": pos.qty,
                "sl": pos.sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "original_sl": pos.sl,
                "original_tp1": pos.tp1,
                "original_tp2": pos.tp2,
                "leverage": pos.leverage,
                "strategy": pos.strategy,
                "confidence": pos.confidence,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            }
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=2)
            logger.debug(f"[{pos.symbol}] Position backup saved")
        except Exception as e:
            logger.warning(f"[{pos.symbol}] Position backup failed: {e}")

    def _remove_backup(self, symbol: str) -> None:
        """Remove position backup after successful close."""
        try:
            backup_file = self._backup_dir / f"{symbol.replace('/', '_')}.json"
            if backup_file.exists():
                backup_file.unlink()
                logger.debug(f"[{symbol}] Position backup removed")
        except Exception as e:
            logger.warning(f"[{symbol}] Failed to remove position backup: {e}")

    def recover_from_backups(self) -> int:
        """Recover position data from disk backups after crash.

        Returns number of positions recovered.
        """
        recovered = 0
        for backup_file in self._backup_dir.glob("*.json"):
            try:
                with open(backup_file) as f:
                    data = json.load(f)
                symbol = data.get("symbol", "")
                if symbol and symbol not in self.positions:
                    logger.info(
                        f"[{symbol}] Found crash backup: "
                        f"SL={data.get('original_sl')} TP1={data.get('original_tp1')} "
                        f"TP2={data.get('original_tp2')}"
                    )
                    recovered += 1
                    # Note: actual position reconstruction requires exchange reconciliation.
                    # This backup provides the original SL/TP values that would otherwise be lost.
            except Exception as e:
                logger.warning(f"Failed to read position backup {backup_file}: {e}")
        if recovered > 0:
            logger.warning(f"Found {recovered} position backup(s) from previous session")
        return recovered

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

    def has_open_position(self, symbol: str) -> bool:
        """Check if there is an open (non-CLOSED) position for this symbol."""
        existing = self.positions.get(symbol)
        return existing is not None and existing.state != CLOSED

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
        """Open a new position. Enforces one position per symbol.

        Returns None if a position already exists for this symbol (any direction).
        This is the last line of defense against duplicate position opens.
        """
        # Don't open if already have a position in this symbol
        existing = self.positions.get(symbol)
        if existing and existing.state != CLOSED:
            logger.warning(
                f"[{symbol}] DUPLICATE BLOCKED in PositionManager: "
                f"already have {existing.side} position in state {existing.state} "
                f"(entry={existing.entry}, qty={existing.qty}, leverage={existing.leverage}x). "
                f"Attempted new {side} entry at {entry} with {leverage}x leverage."
            )
            return None

        # Post-close cooldown: only after losses (prevent tilt re-entry)
        # Winners can re-enter immediately — the thesis was right, re-entry is valid
        last_close = self._last_close_time.get(symbol)
        if last_close is not None and not self._last_close_won.get(symbol, True):
            _now = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            elapsed = (_now - last_close).total_seconds() / 60.0
            if elapsed < self._reentry_cooldown_minutes:
                logger.warning(
                    f"[{symbol}] COOLDOWN BLOCKED: only {elapsed:.0f}m since last LOSS "
                    f"(need {self._reentry_cooldown_minutes}m). Skipping {side} entry."
                )
                return None

        # HARD SAFETY: Never open a position without a stop loss.
        # Sniper trades with sl=0 caused -$330 in catastrophic losses (4 trades, no SL).
        if sl <= 0 or abs(entry - sl) / max(entry, 1) < 0.001:
            logger.error(
                f"[{symbol}] REJECTED: No valid stop loss (sl={sl}, entry={entry}). "
                f"Every trade MUST have a stop loss. This is non-negotiable."
            )
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

        # Persist SL/TP to disk BEFORE adding to in-memory tracking
        self._backup_position(pos)

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
            metadata={
                "entry_reasons": entry_reasons or {},
                "confidence": confidence,
            },
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

        # Log TRADE_OPENED event
        try:
            tel = _get_tel()
            if tel is not None:
                tel.log(
                    "TRADE_OPENED",
                    symbol,
                    side=side,
                    entry=entry,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    leverage=leverage,
                    position_size=qty,
                    strategy=strategy,
                    confidence=confidence,
                    atr=atr,
                    regime=(entry_reasons or {}).get("regime", ""),
                    entry_type=entry_type,
                )
        except Exception:
            pass

        return pos

    def update_price(
        self, symbol: str, current_price: float, df_5m=None, sim_now: datetime = None
    ) -> List[TradeEvent]:
        """
        Process a price update for a position.
        Checks SL, early exit, TP1, trailing stop, TP2 in order.
        SL is checked first to prevent early exit from closing at a worse price.
        df_5m: optional 5m DataFrame for momentum-based early exit.
        sim_now: simulated current time (for backtest; uses datetime.now(UTC) if None).
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        if pos.state == CLOSED:
            return []

        # Store sim_now for internal methods (time stop, TP1 speed calc)
        self._sim_now = sim_now

        events = []
        is_long = pos.side == "LONG"

        # Track MFE/MAE (max favorable/adverse excursion from entry)
        if current_price > pos.highest_price:
            pos.highest_price = current_price
        if current_price < pos.lowest_price:
            pos.lowest_price = current_price

        # 0a. PROFIT LOCK: move SL toward breakeven once we're up enough.
        # Never ride a winner back to a loser. We can always re-enter.
        #
        # Finding 22 trail audit (2026-04-16): old 0.3R trigger was firing
        # on market noise — at ~0.3% profit on a 1% stop, within normal
        # intraday wiggle. 58 historical trades closed within ±0.5% of
        # entry with no TP1 hit = -$47.77 of noise losses from this.
        #
        # New profile-aware thresholds (SCALP keeps tight, MEDIUM/TREND
        # get patience):
        #   SCALP:  0.3R -> BE, 0.6R -> lock 0.3R  (as before)
        #   MEDIUM: 0.6R -> BE, 1.0R -> lock 0.3R
        #   TREND:  0.8R -> BE, 1.2R -> lock 0.4R
        if pos.state == OPEN:
            sl_dist = abs(pos.entry - pos.original_sl)
            if sl_dist > 0:
                if is_long:
                    unrealized_r = (current_price - pos.entry) / sl_dist
                else:
                    unrealized_r = (pos.entry - current_price) / sl_dist

                # Determine profile-aware thresholds
                _entry_type = ""
                _prof = getattr(pos, "trade_profile", None)
                if _prof is not None:
                    _entry_type = getattr(_prof, "entry_type", "") or ""
                if _entry_type == "SCALP":
                    _be_trigger, _lock_trigger, _lock_frac = 0.3, 0.6, 0.3
                elif _entry_type == "TREND":
                    _be_trigger, _lock_trigger, _lock_frac = 0.8, 1.2, 0.4
                else:  # MEDIUM default (and unknown)
                    _be_trigger, _lock_trigger, _lock_frac = 0.6, 1.0, 0.3

                # Breakeven trigger
                if unrealized_r >= _be_trigger:
                    be_sl = pos.entry
                    if is_long and pos.sl < be_sl:
                        pos.sl = be_sl
                        logger.info(
                            f"[{symbol}] PROFIT LOCK ({_entry_type or 'MEDIUM'}): "
                            f"{unrealized_r:.2f}R >= {_be_trigger:.1f}R trigger -> "
                            f"SL moved to breakeven {be_sl}"
                        )
                    elif not is_long and pos.sl > be_sl:
                        pos.sl = be_sl
                        logger.info(
                            f"[{symbol}] PROFIT LOCK ({_entry_type or 'MEDIUM'}): "
                            f"{unrealized_r:.2f}R >= {_be_trigger:.1f}R trigger -> "
                            f"SL moved to breakeven {be_sl}"
                        )

                # Lock-in trigger (above breakeven)
                if unrealized_r >= _lock_trigger:
                    if is_long:
                        lock_sl = pos.entry + sl_dist * _lock_frac
                        if pos.sl < lock_sl:
                            pos.sl = lock_sl
                            logger.info(
                                f"[{symbol}] PROFIT LOCK {_lock_frac:.1f}R "
                                f"({_entry_type or 'MEDIUM'}): SL -> {lock_sl}"
                            )
                    else:
                        lock_sl = pos.entry - sl_dist * _lock_frac
                        if pos.sl > lock_sl:
                            pos.sl = lock_sl
                            logger.info(
                                f"[{symbol}] PROFIT LOCK {_lock_frac:.1f}R "
                                f"({_entry_type or 'MEDIUM'}): SL -> {lock_sl}"
                            )

        # 0b. Check stop loss — on flash crashes, SL must fire before early exit
        sl_hit = (current_price <= pos.sl) if is_long else (current_price >= pos.sl)
        if sl_hit:
            action = "TRAILING_STOP" if pos.state == TRAILING else "SL"
            event = self._close_position(pos, current_price, action)
            events.append(event)
            return events

        # 1a. Smart time stop: assess position health before closing.
        # Original logic: hard 8h cutoff. Problem: closes profitable trades approaching TP1.
        # New logic: check macro position health. Healthy positions get extensions (up to 12h max).
        # Sick positions (losing momentum, wrong direction) close at base time stop.
        if pos.state == OPEN:
            _now = sim_now or getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            hold_hours = (_now - pos.open_time).total_seconds() / 3600

            # Setup-specific time stop from 2,172-signal analysis
            _er = pos.entry_reasons or {}
            _strats = _er.get("strategies_agree", [])
            _driver = _er.get("primary_driver", "")
            _is_bb = "bollinger_squeeze" in _strats or _driver == "bollinger_squeeze"
            _base_sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").split("/")[0]
            _side_label = "BUY" if is_long else "SELL"
            _setup_key = f"{_base_sym}_{_side_label}_BB" if _is_bb else None

            if _setup_key and hasattr(self, '_setup_time_stops'):
                time_stop_hours = self._setup_time_stops.get(
                    _setup_key, getattr(self, '_time_stop_hours', 12)
                )
            else:
                time_stop_hours = getattr(self, '_time_stop_hours', 12)

            if hold_hours >= time_stop_hours:
                # Assess position health before closing
                _health = self._assess_position_health(pos, current_price, df_5m)
                _max_extension = 4.0  # Maximum 4h extension (8h -> 12h absolute max)
                _extension = _health.get("extension_hours", 0)
                _extended_stop = time_stop_hours + min(_extension, _max_extension)

                if hold_hours >= _extended_stop:
                    _reason = _health.get("reason", "time_expired")
                    logger.info(
                        f"[{symbol}] TIME STOP: held {hold_hours:.1f}h >= {_extended_stop:.1f}h "
                        f"(base={time_stop_hours}h + ext={min(_extension, _max_extension):.1f}h) "
                        f"reason={_reason} health={_health.get('score', 0):.0f}%"
                    )
                    event = self._close_position(pos, current_price, "TIME_STOP")
                    events.append(event)
                    return events
                else:
                    # Position is healthy — log extension and continue
                    if not hasattr(pos, '_extension_logged'):
                        logger.info(
                            f"[{symbol}] TIME STOP EXTENDED: {hold_hours:.1f}h held, "
                            f"extending to {_extended_stop:.1f}h (health={_health.get('score', 0):.0f}% "
                            f"tp1_progress={_health.get('tp1_progress', 0):.0f}%)"
                        )
                        pos._extension_logged = True

        # 1a2. Data-driven 1h assessment (from 2,172-signal analysis):
        # If position is losing at 1h mark, 67% chance it stays losing.
        # Exception: BB signals recover 56% of the time — hold BB losers to 4h.
        #
        # Finding 20 trail audit (2026-04-16): this tightening creates 59
        # premature stops over 30 days for ~$87 of leaked alpha. The 67%
        # stat is SURVIVOR BIAS — it counts "didn't recover" = "hit SL",
        # but with wider original SL, many would have recovered past 1h.
        # We now apply this ONLY to SCALP entries (short horizon — 1h is
        # meaningful) and skip MEDIUM/TREND where 1h is too early to judge.
        # Also adding confidence_scorer to the exception list (largest
        # premature-stop contributor per audit Part B).
        if pos.state == OPEN:
            _now_1h = sim_now or getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            _hold_h = (_now_1h - pos.open_time).total_seconds() / 3600
            if 0.9 <= _hold_h <= 1.5:  # ~1h mark (window to avoid checking every tick)
                _pnl_pct = (current_price - pos.entry) / pos.entry if is_long else (pos.entry - current_price) / pos.entry
                if _pnl_pct < -0.001:  # Losing at 1h (>0.1% adverse)
                    _trade_prof = getattr(pos, "trade_profile", None)
                    _entry_type = getattr(_trade_prof, "entry_type", "") if _trade_prof else ""
                    _driver = (pos.entry_reasons or {}).get("primary_driver", "") if pos.entry_reasons else ""
                    _is_bb = ("bollinger_squeeze" in (pos.entry_reasons or {}).get("strategies_agree", [])
                              or _driver == "bollinger_squeeze")
                    _is_cs = _driver == "confidence_scorer"
                    # Only tighten for SCALP profile AND not BB/CS drivers.
                    # MEDIUM and TREND profiles: skip entirely (1h too early).
                    _should_tighten = (
                        _entry_type == "SCALP"
                        and not _is_bb
                        and not _is_cs
                    )
                    if _should_tighten:
                        _tight_sl = pos.entry  # Tighten to breakeven
                        if is_long and _tight_sl < pos.sl:
                            pass  # SL already tighter than breakeven
                        elif is_long:
                            pos.sl = _tight_sl
                            logger.info(
                                f"[{symbol}] 1H ASSESSMENT (SCALP only): non-BB/CS losing ({_pnl_pct:.2%}), "
                                f"tightening SL to breakeven (67% chance stays losing)"
                            )
                        elif not is_long and _tight_sl > pos.sl:
                            pass
                        elif not is_long:
                            pos.sl = _tight_sl
                            logger.info(
                                f"[{symbol}] 1H ASSESSMENT (SCALP only): non-BB/CS losing ({_pnl_pct:.2%}), "
                                f"tightening SL to breakeven (67% chance stays losing)"
                            )
                    else:
                        # MEDIUM/TREND or BB/CS driver — let the trade breathe
                        _skip_reason = (
                            "BB driver (56% recovery)" if _is_bb else
                            "CS driver (premature-stop leak)" if _is_cs else
                            f"{_entry_type} profile (1h too early)"
                        )
                        logger.debug(
                            f"[{symbol}] 1H ASSESSMENT: losing ({_pnl_pct:.2%}), "
                            f"NOT tightening — {_skip_reason}"
                        )

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

        # Log POSITION_UPDATE periodically (every ~60 ticks) when position is still open
        if pos.state != CLOSED and not events:
            _update_counter = getattr(pos, '_tel_update_counter', 0) + 1
            pos._tel_update_counter = _update_counter
            if _update_counter % 60 == 0:
                try:
                    tel = _get_tel()
                    if tel is not None:
                        if is_long:
                            _unrealized = (current_price - pos.entry) * pos.qty * pos.leverage
                        else:
                            _unrealized = (pos.entry - current_price) * pos.qty * pos.leverage
                        tel.log(
                            "POSITION_UPDATE",
                            symbol,
                            side=pos.side,
                            current_price=current_price,
                            unrealized_pnl=round(_unrealized, 2),
                            trailing_stop=pos.sl,
                            entry_price=pos.entry,
                            state=pos.state,
                            strategy=pos.strategy,
                        )
                except Exception:
                    pass

        return events

    def _assess_position_health(self, pos, current_price: float, df_5m=None) -> dict:
        """Assess macro health of a position to decide whether to extend time stop.

        Returns dict with:
            score: 0-100 health score (higher = healthier)
            extension_hours: recommended extension (0 = close now, up to 4h)
            reason: human-readable explanation
            tp1_progress: % of distance from entry to TP1 covered

        Health factors (each 0-25 points, total 0-100):
            1. TP1 progress — how close to TP1 vs SL (approaching TP1 = healthy)
            2. Profit direction — is position profitable? (in profit = healthy)
            3. Momentum — are recent candles moving in our direction? (tailwind = healthy)
            4. MFE retention — current price vs peak price (holding gains = healthy)
        """
        is_long = pos.side == "LONG"
        entry = pos.entry
        sl = pos.original_sl
        tp1 = pos.tp1

        # Calculate distances
        entry_to_tp1 = abs(tp1 - entry)
        entry_to_sl = abs(entry - sl)
        total_range = entry_to_tp1 + entry_to_sl

        if total_range == 0:
            return {"score": 0, "extension_hours": 0, "reason": "zero_range", "tp1_progress": 0}

        # Factor 1: TP1 progress (0-25 points)
        # How much of the entry->TP1 distance have we covered?
        if is_long:
            tp1_progress = max(0, (current_price - entry) / entry_to_tp1) if entry_to_tp1 > 0 else 0
        else:
            tp1_progress = max(0, (entry - current_price) / entry_to_tp1) if entry_to_tp1 > 0 else 0
        tp1_progress_pct = min(tp1_progress * 100, 100)
        tp1_score = min(25, tp1_progress * 25)  # 100% progress = 25 points

        # Factor 2: Profit direction (0-25 points)
        if is_long:
            pnl_pct = (current_price - entry) / entry * 100
        else:
            pnl_pct = (entry - current_price) / entry * 100
        if pnl_pct > 2.0:
            profit_score = 25  # Strongly profitable
        elif pnl_pct > 1.0:
            profit_score = 20
        elif pnl_pct > 0:
            profit_score = 15  # In profit
        elif pnl_pct > -1.0:
            profit_score = 5   # Small loss
        else:
            profit_score = 0   # Losing

        # Factor 3: Momentum (0-25 points) — uses 5m data if available
        momentum_score = 12  # Default neutral if no data
        if df_5m is not None and len(df_5m) >= 10:
            try:
                c = df_5m["close"].astype(float)
                last5 = c.iloc[-5:].values
                # Are we making higher lows (LONG) or lower highs (SHORT)?
                if is_long:
                    trending_up = last5[-1] > last5[0]  # Net positive over 25min
                    ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
                    ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
                    ema_bullish = ema5 > ema13
                else:
                    trending_up = last5[-1] < last5[0]
                    ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
                    ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
                    ema_bullish = ema5 < ema13

                if trending_up and ema_bullish:
                    momentum_score = 25  # Strong tailwind
                elif trending_up or ema_bullish:
                    momentum_score = 18  # Partial tailwind
                else:
                    momentum_score = 5   # Headwind
            except Exception:
                momentum_score = 12

        # Factor 4: MFE retention (0-25 points) — holding gains vs giving them back
        if is_long:
            peak = pos.highest_price
            mfe = (peak - entry) / entry * 100 if entry > 0 else 0
            current_gain = (current_price - entry) / entry * 100
        else:
            peak = pos.lowest_price
            mfe = (entry - peak) / entry * 100 if entry > 0 else 0
            current_gain = (entry - current_price) / entry * 100

        if mfe > 0:
            retention = current_gain / mfe if mfe > 0 else 0  # What % of peak gain we still have
        else:
            retention = 0

        if retention > 0.8:
            mfe_score = 25  # Holding 80%+ of peak gains
        elif retention > 0.5:
            mfe_score = 18  # Holding 50%+ of gains
        elif retention > 0.2:
            mfe_score = 10  # Gave back a lot but still positive
        else:
            mfe_score = 0   # Lost most/all gains

        # Total health score
        total_score = tp1_score + profit_score + momentum_score + mfe_score

        # Determine extension based on score
        if total_score >= 75:
            extension = 4.0  # Very healthy — extend maximum (8h -> 12h)
            reason = "very_healthy"
        elif total_score >= 60:
            extension = 3.0  # Healthy — extend 3h (8h -> 11h)
            reason = "healthy"
        elif total_score >= 45:
            extension = 1.5  # Mixed — small extension (8h -> 9.5h)
            reason = "mixed"
        elif total_score >= 30:
            extension = 0.5  # Weak — tiny extension (8h -> 8.5h)
            reason = "weak"
        else:
            extension = 0.0  # Unhealthy — close at base time stop
            reason = "unhealthy"

        logger.debug(
            f"[{pos.symbol}] Position health: score={total_score:.0f}/100 "
            f"(tp1={tp1_score:.0f} profit={profit_score:.0f} momentum={momentum_score:.0f} "
            f"mfe={mfe_score:.0f}) ext={extension:.1f}h tp1_progress={tp1_progress_pct:.0f}%"
        )

        return {
            "score": total_score,
            "extension_hours": extension,
            "reason": reason,
            "tp1_progress": tp1_progress_pct,
            "pnl_pct": pnl_pct,
            "retention": retention,
        }

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
            _now_for_speed = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            time_to_tp1_s = (_now_for_speed - pos.open_time).total_seconds()
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

        # Log TP_HIT event
        try:
            tel = _get_tel()
            if tel is not None:
                _hold_s = ((getattr(self, '_sim_now', None) or datetime.now(timezone.utc)) - pos.open_time).total_seconds()
                tel.log(
                    "TP_HIT",
                    pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    entry_price=pos.entry,
                    pnl=pnl,
                    hold_time=_hold_s,
                    partial_close_pct=dynamic_close_pct,
                    remaining_qty=pos.qty,
                    strategy=pos.strategy,
                )
        except Exception:
            pass

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
            # Trailing SL can move above entry on strong moves without TP1_HIT
            # having fired. A closed-at-profit SL trigger is a win, not a loss.
            return "CLEAN_WIN" if win else "CLEAN_LOSS"
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
        # Use simulated time in backtest mode, real time in live
        pos.close_time = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)

        # Classify outcome before closing state
        pos.outcome = self._classify_outcome(pos, action)

        # State -> CLOSED
        pos._transition(CLOSED, f"{action} @ {price}")
        # Record close time and win/loss for cooldown enforcement
        self._last_close_time[pos.symbol] = pos.close_time
        self._last_close_won[pos.symbol] = pos.realized_pnl > 0

        # Record outcome for momentum tracker (win/loss streak sizing)
        try:
            from execution.momentum_tracker import get_momentum_tracker
            get_momentum_tracker().record_outcome(pos.symbol, pos.realized_pnl > 0)
        except Exception:
            pass

        # Neuroplasticity: strengthen/weaken setup edges, detect surprises
        try:
            from llm.neuroplasticity import run_neuroplasticity_cycle
            _er = pos.entry_reasons or {}
            run_neuroplasticity_cycle({
                "symbol": pos.symbol,
                "side": "BUY" if pos.side == "LONG" else "SELL",
                "strategy": _er.get("primary_driver", ""),
                "strategies_agree": _er.get("strategies_agree", []),
                "pnl": pos.realized_pnl,
                "entry": pos.entry,
                "regime": _er.get("regime", "unknown"),
                "outcome": pos.outcome,
            })
        except Exception:
            pass

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
                # MFE/MAE tracking — critical for exit optimization
                "mfe": round(pos.mfe, 6),
                "mae": round(pos.mae, 6),
                "mfe_pct": round(pos.mfe / pos.entry * 100, 4) if pos.entry else 0,
                "mae_pct": round(pos.mae / pos.entry * 100, 4) if pos.entry else 0,
                "highest_price": pos.highest_price,
                "lowest_price": pos.lowest_price,
            },
        )
        self.trade_log.append(event)

        # Log structured trade event (SL_HIT, TP_HIT, or TRADE_CLOSED)
        try:
            tel = _get_tel()
            if tel is not None:
                _hold_s = (pos.close_time - pos.open_time).total_seconds()
                # Map action to event type
                if action in ("SL", "TRAILING_STOP"):
                    _event_type = "SL_HIT"
                elif action in ("TP2", "TP1_FULL"):
                    _event_type = "TP_HIT"
                else:
                    _event_type = "TRADE_CLOSED"
                tel.log(
                    _event_type,
                    pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    entry_price=pos.entry,
                    pnl=pos.realized_pnl,
                    hold_time=_hold_s,
                    exit_reason=action,
                    leverage=pos.leverage,
                    strategy=pos.strategy,
                    outcome=pos.outcome,
                    confidence=pos.confidence,
                    regime=(pos.entry_reasons or {}).get("regime", ""),
                )
        except Exception:
            pass

        # Remove backup after successful close
        self._remove_backup(pos.symbol)

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

        now = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
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
