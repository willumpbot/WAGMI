"""
Price Action Enhanced Trade Simulator.

Goes beyond simple TP/SL by analyzing real candlestick data to make smarter
entry/exit decisions — simulating what a skilled manual trader would do with
sniper signals at 10-25x leverage.

Key improvements over basic SniperSimulator:
1. PA confirmation before entry (wait for bullish/bearish candle close)
2. Rejection pattern detection (wick rejection, volume spike, chase filter)
3. Smart exit management (breakeven SL, partial close, time tightening, RSI divergence)
4. MFE/MAE tracking per trade
5. Comparison output vs basic simulator
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("bot.manual.pa_simulator")

# ── Paths ──────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join("data", "manual")
_PA_TRADES_PATH = os.path.join(_DATA_DIR, "pa_sim_trades.jsonl")
_PA_STATUS_PATH = os.path.join(_DATA_DIR, "pa_sim_status.json")
_COMPARISON_PATH = os.path.join(_DATA_DIR, "pa_vs_basic_comparison.json")

# ── Constants ──────────────────────────────────────────────────────────
STARTING_EQUITY = 100.0
PA_CONFIRMATION_WINDOW_S = 15 * 60       # 15 minutes to get PA confirmation
CHASE_THRESHOLD_PCT = 0.01               # 1% — don't chase if price moved past entry
WICK_REJECTION_RATIO = 2.0               # Upper/lower wick > 2x body = rejection
VOLUME_SPIKE_RATIO = 3.0                 # Volume > 3x avg on opposite candle = skip
BREAKEVEN_TRIGGER_RATIO = 0.5            # Move SL to BE after 0.5x TP distance
PARTIAL_CLOSE_RATIO = 0.5               # Close 50% at scalp TP
TIME_FLAT_HOURS = 4.0                    # Tighten SL if flat after 4h
TIME_FLAT_SL_FACTOR = 0.5               # Tighten SL to 0.5x original width
TIME_STOP_HOURS = 12.0
TIME_STOP_S = TIME_STOP_HOURS * 3600
RSI_PERIOD = 14
RSI_DIVERGENCE_LOOKBACK = 6             # Candles to check for divergence


# ── Data classes ───────────────────────────────────────────────────────

@dataclass
class PACandle:
    """A single OHLCV candle used for PA analysis."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class PendingEntry:
    """A signal waiting for PA confirmation."""
    signal: Any               # SniperSignal
    received_at: float        # unix timestamp when signal arrived
    confirmed: bool = False
    rejected: bool = False
    reject_reason: str = ""
    pa_entry_price: float = 0.0  # Actual entry after PA confirmation


@dataclass
class PAPosition:
    """A simulated PA-enhanced open position."""
    trade_id: str
    symbol: str
    side: str
    tier: str
    signal_entry: float         # Original signal entry price
    pa_entry: float             # Actual PA-confirmed entry price
    sl: float
    original_sl: float          # Original SL (before any moves)
    tp_scalp: float
    tp_swing: float
    leverage: float
    risk_pct: float
    position_size_usd: float
    qty: float
    risk_amount: float
    equity_at_open: float
    opened_at: float
    opened_at_iso: str
    confidence: float
    num_agree: int
    regime: str
    # State tracking
    sl_at_breakeven: bool = False
    partial_closed: bool = False
    remaining_size_pct: float = 1.0    # 1.0 = full, 0.5 = half closed
    time_tightened: bool = False
    # MFE/MAE tracking
    mfe: float = 0.0          # Max favorable excursion (%)
    mae: float = 0.0          # Max adverse excursion (%)
    mfe_price: float = 0.0
    mae_price: float = 0.0
    # Partial close tracking
    partial_pnl_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PATrade:
    """A completed PA-enhanced trade."""
    trade_id: str
    symbol: str
    side: str
    tier: str
    signal_entry: float
    pa_entry: float
    exit_price: float
    sl: float
    original_sl: float
    tp_scalp: float
    tp_swing: float
    leverage: float
    position_size_usd: float
    qty: float
    risk_amount: float
    equity_at_open: float
    equity_at_close: float
    pnl_usd: float
    pnl_pct: float
    result: str               # WIN / LOSS / TIME_STOP
    exit_reason: str          # pa_scalp_tp / pa_swing_tp / sl / breakeven_sl / time_stop / time_tighten / rsi_divergence
    hold_time_s: float
    hold_time_hours: float
    opened_at: str
    closed_at: str
    confidence: float
    num_agree: int
    regime: str
    # PA-specific metrics
    entry_improvement_pct: float   # Positive = PA got better entry
    sl_moved_to_be: bool
    partial_closed: bool
    partial_pnl_usd: float
    time_tightened: bool
    mfe_pct: float
    mae_pct: float
    exit_quality: str              # OPTIMAL / GOOD / FAIR / POOR

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── PA Analysis Helpers ────────────────────────────────────────────────

def candles_from_dataframe(df: pd.DataFrame) -> List[PACandle]:
    """Convert a pandas DataFrame (OHLCV) to list of PACandle objects."""
    candles = []
    if df is None or df.empty:
        return candles
    for _, row in df.iterrows():
        try:
            candles.append(PACandle(
                timestamp=row.get('timestamp', 0) if isinstance(row.get('timestamp'), (int, float))
                          else time.time(),
                open=float(row.get('open', row.get('Open', 0))),
                high=float(row.get('high', row.get('High', 0))),
                low=float(row.get('low', row.get('Low', 0))),
                close=float(row.get('close', row.get('Close', 0))),
                volume=float(row.get('volume', row.get('Volume', 0))),
            ))
        except (ValueError, TypeError):
            continue
    return candles


def check_pa_confirmation(
    candles: List[PACandle],
    side: str,
    entry_price: float,
    signal_time: float,
    window_s: float = PA_CONFIRMATION_WINDOW_S,
) -> Tuple[bool, float, str]:
    """
    Check if price action confirms the signal entry.

    For BUY: wait for a bullish candle that closes above entry on 5m chart.
    For SELL: wait for a bearish candle that closes below entry on 5m chart.

    Returns:
        (confirmed, pa_entry_price, reason)
    """
    if not candles:
        return False, 0.0, "no_candles"

    for candle in candles:
        # Only look at candles within the confirmation window
        if candle.timestamp < signal_time:
            continue
        if candle.timestamp > signal_time + window_s:
            return False, 0.0, "timeout_15m"

        if side == "BUY":
            if candle.is_bullish and candle.close >= entry_price:
                return True, candle.close, "bullish_close_above_entry"
        else:  # SELL
            if candle.is_bearish and candle.close <= entry_price:
                return True, candle.close, "bearish_close_below_entry"

    return False, 0.0, "no_confirmation"


def check_rejection_patterns(
    candles: List[PACandle],
    side: str,
    entry_price: float,
    signal_time: float,
) -> Tuple[bool, str]:
    """
    Check for rejection patterns that would CANCEL the trade.

    Rejection patterns:
    1. Long upper wick > 2x body on entry candle = rejection
    2. Volume spike > 3x average on opposite-direction candle
    3. Price already moved > 1% past entry in our direction = chase

    Returns:
        (rejected, reason)
    """
    if not candles:
        return False, ""

    # Get recent candles for volume average
    recent_candles = [c for c in candles if c.timestamp <= signal_time]
    avg_volume = 0.0
    if recent_candles:
        volumes = [c.volume for c in recent_candles[-20:] if c.volume > 0]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0

    # Check candles around signal time
    for candle in candles:
        if candle.timestamp < signal_time:
            continue
        if candle.timestamp > signal_time + PA_CONFIRMATION_WINDOW_S:
            break

        body = candle.body
        if body < 1e-10:
            body = 1e-10  # Avoid division by zero for doji candles

        # 1. Wick rejection
        if side == "BUY":
            # Long upper wick on the candle = buyers being rejected at highs
            if candle.upper_wick > WICK_REJECTION_RATIO * body and candle.high >= entry_price:
                return True, "upper_wick_rejection"
        else:  # SELL
            # Long lower wick = sellers being rejected at lows
            if candle.lower_wick > WICK_REJECTION_RATIO * body and candle.low <= entry_price:
                return True, "lower_wick_rejection"

        # 2. Volume spike on opposite-direction candle
        if avg_volume > 0 and candle.volume > VOLUME_SPIKE_RATIO * avg_volume:
            if side == "BUY" and candle.is_bearish:
                return True, "volume_spike_bearish"
            elif side == "SELL" and candle.is_bullish:
                return True, "volume_spike_bullish"

        # 3. Chase filter — price already moved too far in our direction
        if side == "BUY":
            if candle.close > entry_price * (1 + CHASE_THRESHOLD_PCT):
                return True, "chase_too_far"
        else:
            if candle.close < entry_price * (1 - CHASE_THRESHOLD_PCT):
                return True, "chase_too_far"

    return False, ""


def compute_rsi(closes: List[float], period: int = RSI_PERIOD) -> List[float]:
    """Compute RSI from a list of close prices. Returns list of same length (NaN-padded)."""
    if len(closes) < period + 1:
        return [float('nan')] * len(closes)

    rsi_values = [float('nan')] * period
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Initial averages
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [max(-d, 0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(period, len(deltas)):
        delta = deltas[i]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    return rsi_values


def detect_rsi_divergence(
    candles: List[PACandle],
    side: str,
    lookback: int = RSI_DIVERGENCE_LOOKBACK,
) -> bool:
    """
    Detect RSI divergence against the position direction.

    For BUY position: bearish divergence = price making higher highs but RSI
    making lower highs → momentum fading, exit signal.

    For SELL position: bullish divergence = price making lower lows but RSI
    making higher lows → momentum fading, exit signal.
    """
    if len(candles) < RSI_PERIOD + lookback + 1:
        return False

    closes = [c.close for c in candles]
    rsi_values = compute_rsi(closes)

    # Get the last `lookback` valid RSI values and corresponding prices
    recent_rsi = []
    recent_highs = []
    recent_lows = []
    for i in range(len(candles) - lookback, len(candles)):
        if i < 0 or math.isnan(rsi_values[i]):
            continue
        recent_rsi.append(rsi_values[i])
        recent_highs.append(candles[i].high)
        recent_lows.append(candles[i].low)

    if len(recent_rsi) < 3:
        return False

    if side == "BUY":
        # Bearish divergence: price highs rising, RSI highs falling
        price_rising = recent_highs[-1] > recent_highs[0]
        rsi_falling = recent_rsi[-1] < recent_rsi[0]
        # RSI should be in overbought territory for meaningful divergence
        if price_rising and rsi_falling and recent_rsi[-1] > 60:
            return True
    else:  # SELL
        # Bullish divergence: price lows falling, RSI lows rising
        price_falling = recent_lows[-1] < recent_lows[0]
        rsi_rising = recent_rsi[-1] > recent_rsi[0]
        # RSI should be in oversold territory
        if price_falling and rsi_rising and recent_rsi[-1] < 40:
            return True

    return False


# ── Main Simulator ─────────────────────────────────────────────────────

class PAEnhancedSimulator:
    """
    Price Action Enhanced Trade Simulator.

    Unlike the basic SniperSimulator which enters at signal price and exits
    at fixed TP/SL, this simulator:
    1. Waits for PA confirmation before entering
    2. Detects rejection patterns to skip bad entries
    3. Manages exits dynamically (breakeven SL, partial close, time tighten, RSI exit)
    4. Tracks MFE/MAE for trade quality analysis
    5. Compares results against what a basic simulator would have done
    """

    def __init__(self, starting_equity: float = STARTING_EQUITY):
        os.makedirs(_DATA_DIR, exist_ok=True)

        self._starting_equity = starting_equity
        self._equity = starting_equity
        self._open_positions: List[PAPosition] = []
        self._pending_entries: List[PendingEntry] = []
        self._closed_trades: List[PATrade] = []
        self._trade_counter = 0

        # Stats
        self._wins = 0
        self._losses = 0
        self._gross_profit = 0.0
        self._gross_loss = 0.0
        self._max_equity = starting_equity
        self._min_equity = starting_equity
        self._max_drawdown = 0.0
        self._current_streak = 0
        self._best_trade_pnl = 0.0
        self._worst_trade_pnl = 0.0

        # PA-specific stats
        self._signals_received = 0
        self._signals_confirmed = 0
        self._signals_rejected = 0
        self._signals_timeout = 0
        self._rejection_reasons: Dict[str, int] = {}
        self._total_entry_improvement = 0.0
        self._breakeven_saves = 0
        self._partial_close_count = 0
        self._time_tighten_count = 0
        self._rsi_exit_count = 0
        self._total_mfe = 0.0
        self._total_mae = 0.0

        # Equity curve
        self._equity_curve: List[Dict[str, Any]] = [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "equity": starting_equity}
        ]
        self._daily_pnl: Dict[str, float] = {}

        # Basic simulator shadow tracking (for comparison)
        self._basic_equity = starting_equity
        self._basic_trades: List[Dict[str, Any]] = []

        self._started_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"[PA-SIM] Initialized — equity=${self._equity:.2f}"
        )

    # ── Public API ─────────────────────────────────────────────────────

    def on_signal(
        self,
        sniper_signal,
        candles_5m: Optional[List[PACandle]] = None,
    ) -> Optional[PAPosition]:
        """
        Called when a SniperSignal passes all filters.

        Unlike basic simulator, does NOT enter immediately. Instead:
        1. Checks PA confirmation (bullish/bearish candle close)
        2. Checks rejection patterns
        3. Only enters if PA confirms within 15 minutes

        Args:
            sniper_signal: SniperSignal from sniper_filter
            candles_5m: Recent 5m candles for PA analysis.
                        If None, enters immediately (fallback to basic behavior).

        Returns:
            PAPosition if entered, None if rejected/pending
        """
        self._signals_received += 1

        # Avoid duplicate positions
        for pos in self._open_positions:
            if pos.symbol == sniper_signal.symbol and pos.side == sniper_signal.side:
                logger.debug(f"[PA-SIM] Already have {pos.side} on {pos.symbol}, skipping")
                return None

        now = time.time()

        # Shadow track what basic simulator would do
        self._track_basic_entry(sniper_signal)

        # If no candles provided, fall back to immediate entry (basic mode)
        if candles_5m is None or len(candles_5m) == 0:
            logger.debug("[PA-SIM] No candle data, entering at signal price (basic mode)")
            return self._open_position(sniper_signal, sniper_signal.entry, now)

        # Step 1: Check rejection patterns FIRST (instant disqualifiers)
        rejected, reject_reason = check_rejection_patterns(
            candles_5m, sniper_signal.side, sniper_signal.entry, now
        )
        if rejected:
            self._signals_rejected += 1
            self._rejection_reasons[reject_reason] = \
                self._rejection_reasons.get(reject_reason, 0) + 1
            logger.info(
                f"[PA-SIM] REJECTED {sniper_signal.symbol} {sniper_signal.side} — {reject_reason}"
            )
            return None

        # Step 2: Check PA confirmation
        confirmed, pa_price, confirm_reason = check_pa_confirmation(
            candles_5m, sniper_signal.side, sniper_signal.entry, now
        )

        if confirmed:
            self._signals_confirmed += 1
            return self._open_position(sniper_signal, pa_price, now)
        else:
            # No confirmation yet — add to pending queue
            pending = PendingEntry(
                signal=sniper_signal,
                received_at=now,
            )
            self._pending_entries.append(pending)
            logger.info(
                f"[PA-SIM] PENDING {sniper_signal.symbol} {sniper_signal.side} — "
                f"waiting for PA confirmation ({confirm_reason})"
            )
            return None

    def check_pending_entries(
        self,
        candles_by_symbol: Dict[str, List[PACandle]],
    ) -> List[PAPosition]:
        """
        Check pending entries for PA confirmation.

        Called each scan cycle with updated candle data.
        Returns list of newly opened positions.
        """
        now = time.time()
        opened: List[PAPosition] = []
        still_pending: List[PendingEntry] = []

        for pending in self._pending_entries:
            sig = pending.signal
            elapsed = now - pending.received_at

            # Timeout — signal is stale
            if elapsed > PA_CONFIRMATION_WINDOW_S:
                self._signals_timeout += 1
                logger.info(
                    f"[PA-SIM] TIMEOUT {sig.symbol} {sig.side} — "
                    f"no PA confirmation in {elapsed / 60:.1f}m"
                )
                continue

            candles = candles_by_symbol.get(sig.symbol, [])
            if not candles:
                still_pending.append(pending)
                continue

            # Check rejection again with newer data
            rejected, reject_reason = check_rejection_patterns(
                candles, sig.side, sig.entry, pending.received_at
            )
            if rejected:
                self._signals_rejected += 1
                self._rejection_reasons[reject_reason] = \
                    self._rejection_reasons.get(reject_reason, 0) + 1
                logger.info(f"[PA-SIM] REJECTED (pending) {sig.symbol} — {reject_reason}")
                continue

            # Check confirmation
            confirmed, pa_price, _ = check_pa_confirmation(
                candles, sig.side, sig.entry, pending.received_at
            )
            if confirmed:
                self._signals_confirmed += 1
                pos = self._open_position(sig, pa_price, now)
                if pos:
                    opened.append(pos)
            else:
                still_pending.append(pending)

        self._pending_entries = still_pending
        return opened

    def check_positions(
        self,
        current_prices: Dict[str, float],
        candles_by_symbol: Optional[Dict[str, List[PACandle]]] = None,
    ) -> List[PATrade]:
        """
        Called every scan cycle. Checks all open positions with smart exit logic.

        Args:
            current_prices: {symbol: current_price}
            candles_by_symbol: {symbol: [PACandle, ...]} for RSI divergence checks

        Returns:
            List of trades closed this cycle.
        """
        if not self._open_positions:
            return []

        closed_this_cycle: List[PATrade] = []
        now = time.time()
        remaining: List[PAPosition] = []

        for pos in self._open_positions:
            price = current_prices.get(pos.symbol)
            if price is None:
                remaining.append(pos)
                continue

            # Update MFE/MAE
            self._update_mfe_mae(pos, price)

            # Also update basic simulator shadow
            self._track_basic_check(pos, price, now)

            exit_reason = None
            exit_price = price

            elapsed_s = now - pos.opened_at
            tp_distance = abs(pos.tp_scalp - pos.pa_entry)
            current_move = self._get_price_move(pos, price)

            # ── Smart Exit Logic (ordered by priority) ──

            # 1. Hard SL hit
            if self._is_sl_hit(pos, price):
                exit_reason = "sl" if not pos.sl_at_breakeven else "breakeven_sl"
                exit_price = pos.sl

            # 2. Swing TP hit (remaining position after partial)
            elif pos.partial_closed and self._is_tp_hit(pos, price, pos.tp_swing):
                exit_reason = "pa_swing_tp"
                exit_price = pos.tp_swing

            # 3. Scalp TP — partial close (50% at scalp TP, keep rest running)
            elif not pos.partial_closed and self._is_tp_hit(pos, price, pos.tp_scalp):
                self._do_partial_close(pos, pos.tp_scalp, now)
                # Don't close fully — keep position open with trailing
                remaining.append(pos)
                continue

            # 4. RSI divergence exit
            elif candles_by_symbol and not exit_reason:
                candles = candles_by_symbol.get(pos.symbol, [])
                if candles and detect_rsi_divergence(candles, pos.side):
                    exit_reason = "rsi_divergence"
                    exit_price = price
                    self._rsi_exit_count += 1

            # 5. Time stop (12h)
            elif elapsed_s >= TIME_STOP_S:
                exit_reason = "time_stop"
                exit_price = price

            # ── Dynamic SL Management (non-exit actions) ──

            if exit_reason is None:
                # Move SL to breakeven after 0.5x TP distance reached
                if not pos.sl_at_breakeven and tp_distance > 0:
                    if current_move >= BREAKEVEN_TRIGGER_RATIO * tp_distance:
                        self._move_sl_to_breakeven(pos)

                # Time-based tightening: flat after 4 hours
                if not pos.time_tightened and elapsed_s >= TIME_FLAT_HOURS * 3600:
                    current_pnl_pct = current_move / pos.pa_entry if pos.pa_entry > 0 else 0
                    # "Flat" = less than 0.2% move
                    if abs(current_pnl_pct) < 0.002:
                        self._tighten_sl(pos)

                remaining.append(pos)
            else:
                trade = self._close_position(pos, exit_price, exit_reason, now)
                closed_this_cycle.append(trade)

        self._open_positions = remaining

        if closed_this_cycle:
            self._save_status()

        return closed_this_cycle

    def get_status(self) -> Dict[str, Any]:
        """Return full PA simulator status."""
        total = self._wins + self._losses
        win_rate = (self._wins / total * 100) if total > 0 else 0.0
        profit_factor = (
            (self._gross_profit / abs(self._gross_loss))
            if self._gross_loss != 0 else float('inf') if self._gross_profit > 0 else 0.0
        )
        missed_rate = (
            (self._signals_rejected + self._signals_timeout) / self._signals_received * 100
            if self._signals_received > 0 else 0.0
        )
        avg_entry_improvement = (
            self._total_entry_improvement / self._signals_confirmed
            if self._signals_confirmed > 0 else 0.0
        )
        avg_mfe = self._total_mfe / total if total > 0 else 0.0
        avg_mae = self._total_mae / total if total > 0 else 0.0

        return {
            "current_equity": round(self._equity, 2),
            "starting_equity": self._starting_equity,
            "total_trades": total,
            "wins": self._wins,
            "losses": self._losses,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999.0,
            "best_trade": round(self._best_trade_pnl, 2),
            "worst_trade": round(self._worst_trade_pnl, 2),
            "max_drawdown": round(self._max_drawdown, 2),
            "current_streak": self._current_streak,
            "equity_curve": self._equity_curve[-200:],
            # PA-specific metrics
            "pa_metrics": {
                "signals_received": self._signals_received,
                "signals_confirmed": self._signals_confirmed,
                "signals_rejected": self._signals_rejected,
                "signals_timeout": self._signals_timeout,
                "missed_trade_rate_pct": round(missed_rate, 1),
                "avg_entry_improvement_pct": round(avg_entry_improvement * 100, 3),
                "rejection_reasons": self._rejection_reasons,
                "breakeven_saves": self._breakeven_saves,
                "partial_close_count": self._partial_close_count,
                "time_tighten_count": self._time_tighten_count,
                "rsi_exit_count": self._rsi_exit_count,
                "avg_mfe_pct": round(avg_mfe * 100, 2),
                "avg_mae_pct": round(avg_mae * 100, 2),
            },
            "open_positions": [p.to_dict() for p in self._open_positions],
            "pending_entries": len(self._pending_entries),
            "started_at": self._started_at,
            "growth_pct": round((self._equity / self._starting_equity - 1) * 100, 1),
        }

    def get_comparison(self) -> Dict[str, Any]:
        """
        Compare PA simulator results vs what basic simulator would have done.
        Saves to data/manual/pa_vs_basic_comparison.json.
        """
        pa_total = self._wins + self._losses
        pa_wr = (self._wins / pa_total * 100) if pa_total > 0 else 0.0
        pa_pf = (
            (self._gross_profit / abs(self._gross_loss))
            if self._gross_loss != 0 else float('inf') if self._gross_profit > 0 else 0.0
        )

        basic_wins = sum(1 for t in self._basic_trades if t.get("result") == "WIN")
        basic_losses = sum(1 for t in self._basic_trades if t.get("result") == "LOSS")
        basic_total = basic_wins + basic_losses
        basic_wr = (basic_wins / basic_total * 100) if basic_total > 0 else 0.0
        basic_total_pnl = sum(t.get("pnl_usd", 0) for t in self._basic_trades)
        basic_gross_profit = sum(t["pnl_usd"] for t in self._basic_trades if t.get("pnl_usd", 0) > 0)
        basic_gross_loss = sum(t["pnl_usd"] for t in self._basic_trades if t.get("pnl_usd", 0) < 0)
        basic_pf = (
            (basic_gross_profit / abs(basic_gross_loss))
            if basic_gross_loss != 0 else float('inf') if basic_gross_profit > 0 else 0.0
        )

        pa_total_pnl = self._gross_profit + self._gross_loss  # gross_loss is negative
        pnl_difference = pa_total_pnl - basic_total_pnl
        missed_rate = (
            (self._signals_rejected + self._signals_timeout) / self._signals_received * 100
            if self._signals_received > 0 else 0.0
        )

        comparison = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signals_evaluated": self._signals_received,
            "pa_simulator": {
                "equity": round(self._equity, 2),
                "total_trades": pa_total,
                "win_rate": round(pa_wr, 1),
                "profit_factor": round(pa_pf, 2) if pa_pf != float('inf') else 999.0,
                "total_pnl": round(pa_total_pnl, 2),
                "missed_trade_rate_pct": round(missed_rate, 1),
                "breakeven_saves": self._breakeven_saves,
                "partial_closes": self._partial_close_count,
                "rsi_exits": self._rsi_exit_count,
            },
            "basic_simulator": {
                "equity": round(self._basic_equity, 2),
                "total_trades": basic_total,
                "win_rate": round(basic_wr, 1),
                "profit_factor": round(basic_pf, 2) if basic_pf != float('inf') else 999.0,
                "total_pnl": round(basic_total_pnl, 2),
            },
            "comparison": {
                "pnl_difference": round(pnl_difference, 2),
                "pa_better": pnl_difference > 0,
                "equity_difference": round(self._equity - self._basic_equity, 2),
                "win_rate_difference": round(pa_wr - basic_wr, 1),
                "trades_filtered_out": self._signals_rejected + self._signals_timeout,
                "verdict": self._get_comparison_verdict(pnl_difference, pa_wr, basic_wr),
            },
        }

        # Save comparison
        try:
            with open(_COMPARISON_PATH, "w") as f:
                json.dump(comparison, f, indent=2)
            logger.info(f"[PA-SIM] Comparison saved to {_COMPARISON_PATH}")
        except Exception as e:
            logger.warning(f"[PA-SIM] Failed to save comparison: {e}")

        return comparison

    # ── Internal Methods ───────────────────────────────────────────────

    def _open_position(
        self, sniper_signal, pa_entry_price: float, now: float
    ) -> PAPosition:
        """Open a PA-enhanced position."""
        self._trade_counter += 1
        trade_id = f"PA-{self._trade_counter:04d}"

        # Recalculate sizing based on current equity
        risk_pct = sniper_signal.risk_pct
        risk_amount = self._equity * risk_pct
        stop_width_pct = abs(pa_entry_price - sniper_signal.sl) / pa_entry_price
        if stop_width_pct <= 0:
            stop_width_pct = 0.01

        position_size_usd = risk_amount / stop_width_pct
        margin_required = position_size_usd / sniper_signal.leverage if sniper_signal.leverage > 0 else position_size_usd

        # Cap margin at 95% of equity
        if margin_required > self._equity * 0.95:
            scale = (self._equity * 0.95) / margin_required
            position_size_usd *= scale
            risk_amount *= scale

        qty = position_size_usd / pa_entry_price if pa_entry_price > 0 else 0

        # Track entry improvement
        if sniper_signal.side == "BUY":
            entry_improvement = (sniper_signal.entry - pa_entry_price) / sniper_signal.entry
        else:
            entry_improvement = (pa_entry_price - sniper_signal.entry) / sniper_signal.entry
        self._total_entry_improvement += entry_improvement

        pos = PAPosition(
            trade_id=trade_id,
            symbol=sniper_signal.symbol,
            side=sniper_signal.side,
            tier=sniper_signal.tier,
            signal_entry=sniper_signal.entry,
            pa_entry=pa_entry_price,
            sl=sniper_signal.sl,
            original_sl=sniper_signal.sl,
            tp_scalp=sniper_signal.tp_scalp,
            tp_swing=sniper_signal.tp_swing,
            leverage=sniper_signal.leverage,
            risk_pct=risk_pct,
            position_size_usd=round(position_size_usd, 2),
            qty=round(qty, 6),
            risk_amount=round(risk_amount, 2),
            equity_at_open=round(self._equity, 2),
            opened_at=now,
            opened_at_iso=datetime.now(timezone.utc).isoformat(),
            confidence=sniper_signal.confidence,
            num_agree=sniper_signal.num_agree,
            regime=sniper_signal.regime,
            mfe_price=pa_entry_price,
            mae_price=pa_entry_price,
        )

        self._open_positions.append(pos)
        logger.info(
            f"[PA-SIM] OPENED {trade_id} | {pos.symbol} {pos.side} @ ${pos.pa_entry:.4f} "
            f"(signal was ${pos.signal_entry:.4f}, improvement={entry_improvement*100:+.3f}%) | "
            f"size=${pos.position_size_usd:.2f} risk=${pos.risk_amount:.2f}"
        )
        self._save_status()
        return pos

    def _close_position(
        self, pos: PAPosition, exit_price: float, exit_reason: str, now: float
    ) -> PATrade:
        """Close a PA position and update all stats."""
        # Calculate P&L (account for partial close)
        if pos.side == "BUY":
            price_change_pct = (exit_price - pos.pa_entry) / pos.pa_entry
        else:
            price_change_pct = (pos.pa_entry - exit_price) / pos.pa_entry

        remaining_pnl = pos.position_size_usd * pos.remaining_size_pct * price_change_pct
        total_pnl = remaining_pnl + pos.partial_pnl_usd
        pnl_pct = (total_pnl / pos.equity_at_open * 100) if pos.equity_at_open > 0 else 0

        hold_time_s = now - pos.opened_at
        hold_time_hours = hold_time_s / 3600

        # Determine result
        result = "WIN" if total_pnl > 0 else "LOSS"

        # Entry improvement
        if pos.side == "BUY":
            entry_improvement_pct = (pos.signal_entry - pos.pa_entry) / pos.signal_entry * 100
        else:
            entry_improvement_pct = (pos.pa_entry - pos.signal_entry) / pos.signal_entry * 100

        # MFE/MAE as percentage
        mfe_pct = pos.mfe
        mae_pct = pos.mae

        # Exit quality assessment
        exit_quality = self._assess_exit_quality(pos, exit_price, exit_reason)

        # Update equity
        self._equity += total_pnl
        equity_at_close = self._equity

        trade = PATrade(
            trade_id=pos.trade_id,
            symbol=pos.symbol,
            side=pos.side,
            tier=pos.tier,
            signal_entry=pos.signal_entry,
            pa_entry=pos.pa_entry,
            exit_price=round(exit_price, 6),
            sl=pos.sl,
            original_sl=pos.original_sl,
            tp_scalp=pos.tp_scalp,
            tp_swing=pos.tp_swing,
            leverage=pos.leverage,
            position_size_usd=pos.position_size_usd,
            qty=pos.qty,
            risk_amount=pos.risk_amount,
            equity_at_open=pos.equity_at_open,
            equity_at_close=round(equity_at_close, 2),
            pnl_usd=round(total_pnl, 2),
            pnl_pct=round(pnl_pct, 1),
            result=result,
            exit_reason=exit_reason,
            hold_time_s=round(hold_time_s, 1),
            hold_time_hours=round(hold_time_hours, 2),
            opened_at=pos.opened_at_iso,
            closed_at=datetime.now(timezone.utc).isoformat(),
            confidence=pos.confidence,
            num_agree=pos.num_agree,
            regime=pos.regime,
            entry_improvement_pct=round(entry_improvement_pct, 3),
            sl_moved_to_be=pos.sl_at_breakeven,
            partial_closed=pos.partial_closed,
            partial_pnl_usd=round(pos.partial_pnl_usd, 2),
            time_tightened=pos.time_tightened,
            mfe_pct=round(mfe_pct * 100, 2),
            mae_pct=round(mae_pct * 100, 2),
            exit_quality=exit_quality,
        )

        self._closed_trades.append(trade)

        # Update stats
        if result == "WIN":
            self._wins += 1
            self._gross_profit += total_pnl
            self._current_streak = max(0, self._current_streak) + 1
        else:
            self._losses += 1
            self._gross_loss += total_pnl
            self._current_streak = min(0, self._current_streak) - 1

        if total_pnl > self._best_trade_pnl:
            self._best_trade_pnl = total_pnl
        if total_pnl < self._worst_trade_pnl:
            self._worst_trade_pnl = total_pnl

        # Drawdown
        if self._equity > self._max_equity:
            self._max_equity = self._equity
        drawdown = (self._max_equity - self._equity) / self._max_equity * 100
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

        # MFE/MAE aggregates
        self._total_mfe += mfe_pct
        self._total_mae += mae_pct

        # Equity curve
        self._equity_curve.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": round(self._equity, 2),
        })

        # Daily P&L
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_pnl[today_key] = self._daily_pnl.get(today_key, 0.0) + total_pnl

        # Log trade
        self._log_trade(trade)

        logger.info(
            f"[PA-SIM] CLOSED {trade.trade_id} | {trade.symbol} {trade.side} | "
            f"{trade.exit_reason} @ ${trade.exit_price:.4f} | "
            f"P&L=${trade.pnl_usd:+.2f} ({trade.pnl_pct:+.1f}%) | "
            f"entry_imp={trade.entry_improvement_pct:+.3f}% | "
            f"MFE={trade.mfe_pct:.1f}% MAE={trade.mae_pct:.1f}% | "
            f"quality={trade.exit_quality} | equity=${self._equity:.2f}"
        )

        return trade

    def _do_partial_close(self, pos: PAPosition, tp_price: float, now: float) -> None:
        """Close 50% of position at scalp TP, let rest ride."""
        if pos.partial_closed:
            return

        # Calculate P&L on the partial
        if pos.side == "BUY":
            price_change_pct = (tp_price - pos.pa_entry) / pos.pa_entry
        else:
            price_change_pct = (pos.pa_entry - tp_price) / pos.pa_entry

        partial_pnl = pos.position_size_usd * PARTIAL_CLOSE_RATIO * price_change_pct
        pos.partial_pnl_usd = partial_pnl
        pos.partial_closed = True
        pos.remaining_size_pct = 1.0 - PARTIAL_CLOSE_RATIO

        # Also move SL to breakeven for remaining position
        self._move_sl_to_breakeven(pos)

        self._partial_close_count += 1
        self._equity += partial_pnl

        logger.info(
            f"[PA-SIM] PARTIAL CLOSE {pos.trade_id} | 50% @ ${tp_price:.4f} | "
            f"partial P&L=${partial_pnl:+.2f} | remaining rides to swing TP"
        )

    def _move_sl_to_breakeven(self, pos: PAPosition) -> None:
        """Move stop loss to entry price (breakeven)."""
        if pos.sl_at_breakeven:
            return
        pos.sl = pos.pa_entry
        pos.sl_at_breakeven = True
        self._breakeven_saves += 1
        logger.debug(
            f"[PA-SIM] SL→BE {pos.trade_id} | SL moved to ${pos.sl:.4f} (breakeven)"
        )

    def _tighten_sl(self, pos: PAPosition) -> None:
        """Tighten SL after position is flat for TIME_FLAT_HOURS."""
        if pos.time_tightened:
            return
        original_width = abs(pos.pa_entry - pos.original_sl)
        tightened_width = original_width * TIME_FLAT_SL_FACTOR
        if pos.side == "BUY":
            new_sl = pos.pa_entry - tightened_width
            pos.sl = max(pos.sl, new_sl)  # Never widen SL
        else:
            new_sl = pos.pa_entry + tightened_width
            pos.sl = min(pos.sl, new_sl)  # Never widen SL
        pos.time_tightened = True
        self._time_tighten_count += 1
        logger.debug(
            f"[PA-SIM] SL TIGHTENED {pos.trade_id} | "
            f"SL ${pos.original_sl:.4f} → ${pos.sl:.4f} (flat 4h)"
        )

    def _update_mfe_mae(self, pos: PAPosition, price: float) -> None:
        """Update max favorable/adverse excursion."""
        if pos.side == "BUY":
            favorable = (price - pos.pa_entry) / pos.pa_entry
            adverse = (pos.pa_entry - price) / pos.pa_entry
        else:
            favorable = (pos.pa_entry - price) / pos.pa_entry
            adverse = (price - pos.pa_entry) / pos.pa_entry

        if favorable > pos.mfe:
            pos.mfe = favorable
            pos.mfe_price = price
        if adverse > pos.mae:
            pos.mae = adverse
            pos.mae_price = price

    def _is_sl_hit(self, pos: PAPosition, price: float) -> bool:
        """Check if stop loss was hit."""
        if pos.side == "BUY":
            return price <= pos.sl
        else:
            return price >= pos.sl

    def _is_tp_hit(self, pos: PAPosition, price: float, tp: float) -> bool:
        """Check if take profit level was hit."""
        if pos.side == "BUY":
            return price >= tp
        else:
            return price <= tp

    def _get_price_move(self, pos: PAPosition, price: float) -> float:
        """Get absolute price move in favorable direction."""
        if pos.side == "BUY":
            return price - pos.pa_entry
        else:
            return pos.pa_entry - price

    def _assess_exit_quality(
        self, pos: PAPosition, exit_price: float, exit_reason: str
    ) -> str:
        """
        Assess exit quality based on MFE capture.
        OPTIMAL: captured > 80% of MFE
        GOOD: captured 50-80% of MFE
        FAIR: captured 20-50% of MFE
        POOR: captured < 20% of MFE or negative
        """
        if pos.mfe <= 0:
            return "FAIR"

        if pos.side == "BUY":
            captured = (exit_price - pos.pa_entry) / pos.pa_entry
        else:
            captured = (pos.pa_entry - exit_price) / pos.pa_entry

        capture_ratio = captured / pos.mfe if pos.mfe > 0 else 0

        if capture_ratio >= 0.8:
            return "OPTIMAL"
        elif capture_ratio >= 0.5:
            return "GOOD"
        elif capture_ratio >= 0.2:
            return "FAIR"
        else:
            return "POOR"

    # ── Basic Simulator Shadow Tracking ────────────────────────────────

    def _track_basic_entry(self, sniper_signal) -> None:
        """Shadow-track what basic simulator would do (immediate entry at signal price)."""
        # Basic sim always enters
        self._basic_trades.append({
            "symbol": sniper_signal.symbol,
            "side": sniper_signal.side,
            "entry": sniper_signal.entry,
            "sl": sniper_signal.sl,
            "tp_scalp": sniper_signal.tp_scalp,
            "position_size_usd": sniper_signal.position_size_usd,
            "risk_amount": sniper_signal.risk_amount,
            "status": "open",
            "result": None,
            "pnl_usd": 0.0,
        })

    def _track_basic_check(self, pos: PAPosition, price: float, now: float) -> None:
        """Update basic simulator shadow positions."""
        for bt in self._basic_trades:
            if bt.get("status") != "open":
                continue
            if bt["symbol"] != pos.symbol or bt["side"] != pos.side:
                continue

            # Basic sim: simple TP/SL
            if bt["side"] == "BUY":
                if price <= bt["sl"]:
                    bt["status"] = "closed"
                    bt["result"] = "LOSS"
                    pct = (bt["sl"] - bt["entry"]) / bt["entry"]
                    bt["pnl_usd"] = bt["position_size_usd"] * pct
                    self._basic_equity += bt["pnl_usd"]
                elif price >= bt["tp_scalp"]:
                    bt["status"] = "closed"
                    bt["result"] = "WIN"
                    pct = (bt["tp_scalp"] - bt["entry"]) / bt["entry"]
                    bt["pnl_usd"] = bt["position_size_usd"] * pct
                    self._basic_equity += bt["pnl_usd"]
            else:
                if price >= bt["sl"]:
                    bt["status"] = "closed"
                    bt["result"] = "LOSS"
                    pct = (bt["entry"] - bt["sl"]) / bt["entry"]
                    bt["pnl_usd"] = bt["position_size_usd"] * pct
                    self._basic_equity += bt["pnl_usd"]
                elif price <= bt["tp_scalp"]:
                    bt["status"] = "closed"
                    bt["result"] = "WIN"
                    pct = (bt["entry"] - bt["tp_scalp"]) / bt["entry"]
                    bt["pnl_usd"] = bt["position_size_usd"] * pct
                    self._basic_equity += bt["pnl_usd"]
            break

    def _get_comparison_verdict(
        self, pnl_diff: float, pa_wr: float, basic_wr: float
    ) -> str:
        """Generate human-readable comparison verdict."""
        if pnl_diff > 0 and pa_wr > basic_wr:
            return "PA WINS: Higher PnL AND higher win rate. PA filtering adds clear value."
        elif pnl_diff > 0:
            return "PA WINS: Higher PnL despite lower trade count. Quality > quantity."
        elif pnl_diff < 0 and pa_wr > basic_wr:
            return "MIXED: PA has better win rate but lower total PnL (fewer trades). Consider loosening PA filters."
        elif pnl_diff < 0:
            return "BASIC WINS: Simple execution outperformed PA filtering. PA may be too restrictive."
        else:
            return "TIE: Both approaches produced similar results."

    # ── Persistence ────────────────────────────────────────────────────

    def _log_trade(self, trade: PATrade) -> None:
        """Append closed trade to JSONL log."""
        try:
            with open(_PA_TRADES_PATH, "a") as f:
                f.write(json.dumps(trade.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"[PA-SIM] Failed to log trade: {e}")

    def _save_status(self) -> None:
        """Write current status to JSON."""
        try:
            status = self.get_status()
            tmp_path = _PA_STATUS_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(status, f, indent=2)
            os.replace(tmp_path, _PA_STATUS_PATH)
        except Exception as e:
            logger.warning(f"[PA-SIM] Failed to save status: {e}")
