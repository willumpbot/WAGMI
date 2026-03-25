"""
Hyperliquid Execution Helper — Copy-paste ready order parameters.

When a sniper signal fires, the user needs to enter the trade on Hyperliquid
as fast as possible. This module converts SniperSignal into exact
Hyperliquid-compatible order parameters with correct tick sizes, min qty
steps, and leverage caps.

At 25x leverage, every second counts. The output is formatted for
glance-speed reading in Telegram.
"""

import logging
import math
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from execution.precision import (
    round_price,
    round_qty,
    format_price,
    get_min_qty,
    get_tick_size,
    get_max_leverage,
)
from manual.sniper_filter import SniperSignal

logger = logging.getLogger("bot.manual.execution_helper")

# Limit offset: place limit order slightly through the market for fast fill
# 0.05% = aggressive enough to fill, tight enough to not give up edge
LIMIT_OFFSET_PCT = 0.0005


@dataclass
class HyperliquidOrder:
    """Exact Hyperliquid-compatible order parameters."""
    # Core order fields
    symbol: str              # Hyperliquid symbol (e.g., "HYPE" not "HYPE/USDC")
    side: str                # "buy" or "sell" (Hyperliquid lowercase)
    order_type: str          # "limit" for entry
    price: float             # Limit price rounded to tick size
    size: float              # Quantity rounded to min qty step
    leverage: int            # Integer leverage, capped at symbol max
    reduce_only: bool        # False for entry, True for exit

    # Stop loss / take profit triggers
    sl_trigger: float        # Stop loss trigger price (rounded to tick)
    tp1_trigger: float       # Take profit 1 trigger price (rounded to tick)
    tp2_trigger: float       # Take profit 2 trigger price (rounded to tick)

    # Computed display fields
    market_price: float      # Original market/entry price before offset
    position_usd: float      # Total position value in USD
    margin_usd: float        # Required margin in USD
    size_half: float         # Half size for partial TP (rounded to min qty)
    size_remaining: float    # Remaining size after partial TP

    # Signal metadata for display
    direction: str           # "LONG" or "SHORT"
    tier: str                # SNIPER / PREMIUM / STANDARD
    confidence: float        # Signal confidence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HyperliquidOrderBuilder:
    """Builds exact Hyperliquid order parameters from sniper signals."""

    def from_sniper_signal(self, signal: SniperSignal) -> HyperliquidOrder:
        """
        Convert a SniperSignal into Hyperliquid-ready order parameters.

        Handles:
        - Symbol name normalization (strip /USDC suffix)
        - Price rounding to symbol tick size
        - Quantity rounding to symbol min qty step
        - Leverage capping to symbol max
        - Limit offset for fast fill (0.05% through market)
        - Partial close sizing (50/50 split for TP1/TP2)
        """
        symbol = self._normalize_symbol(signal.symbol)
        direction = "LONG" if signal.side == "BUY" else "SHORT"
        side = "buy" if signal.side == "BUY" else "sell"

        # Cap leverage to symbol max, enforce minimum of 1
        max_lev = get_max_leverage(symbol)
        try:
            leverage = min(int(signal.leverage), int(max_lev))
        except (ValueError, TypeError):
            leverage = 1
        if leverage < 1:
            leverage = 1

        # Limit price: slightly through market for fast fill
        # Buy: below market (more attractive to sellers)
        # Sell: above market (more attractive to buyers)
        market_price = signal.entry
        if side == "buy":
            limit_price = market_price * (1 - LIMIT_OFFSET_PCT)
        else:
            limit_price = market_price * (1 + LIMIT_OFFSET_PCT)
        limit_price = round_price(symbol, limit_price)

        # Round quantity to symbol min step, enforce minimum
        size = round_qty(symbol, signal.qty)
        min_qty = get_min_qty(symbol)
        if size < min_qty:
            size = min_qty

        # Partial close sizing: 50/50 split
        size_half = round_qty(symbol, size / 2.0)
        if size_half < min_qty:
            size_half = min_qty
        size_remaining = round_qty(symbol, size - size_half)
        if size_remaining < min_qty:
            # If remainder is below min, put everything on TP1
            size_half = size
            size_remaining = 0.0

        # Round SL/TP to tick size
        sl_trigger = round_price(symbol, signal.sl)
        tp1_trigger = round_price(symbol, signal.tp_scalp)
        tp2_trigger = round_price(symbol, signal.tp_swing)

        # Position value and margin
        position_usd = size * market_price
        margin_usd = position_usd / leverage if leverage > 0 else position_usd

        return HyperliquidOrder(
            symbol=symbol,
            side=side,
            order_type="limit",
            price=limit_price,
            size=size,
            leverage=leverage,
            reduce_only=False,
            sl_trigger=sl_trigger,
            tp1_trigger=tp1_trigger,
            tp2_trigger=tp2_trigger,
            market_price=market_price,
            position_usd=round(position_usd, 2),
            margin_usd=round(margin_usd, 2),
            size_half=size_half,
            size_remaining=size_remaining,
            direction=direction,
            tier=signal.tier,
            confidence=signal.confidence,
        )

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Strip exchange suffixes to get bare Hyperliquid symbol.

        'HYPE/USDC' -> 'HYPE'
        'BTC/USDC:USDC' -> 'BTC'
        'SOL' -> 'SOL'
        """
        s = symbol.split("/")[0]
        s = s.split(":")[0]
        return s.strip()


def format_quick_entry(order: HyperliquidOrder) -> str:
    """
    Format a compact Telegram message for glance-speed execution.

    The user reads this in <5 seconds and enters the trade on Hyperliquid.
    Every line is an action item — no fluff.
    """
    symbol = order.symbol
    offset_dir = "below" if order.side == "buy" else "above"
    offset_pct = LIMIT_OFFSET_PCT * 100

    lines = [
        f"\U0001f3af QUICK ENTRY",
        f"{symbol} {order.direction} {order.leverage}x",
        f"Limit: ${format_price(symbol, order.price)} ({offset_pct:.2f}% {offset_dir} market)",
        f"Size: {_fmt_qty(symbol, order.size)} {symbol} (${order.position_usd:,.2f})",
        f"Margin: ${order.margin_usd:,.2f}",
        f"",
        f"Set after fill:",
        f"SL: ${format_price(symbol, order.sl_trigger)} (stop market)",
        f"TP1: ${format_price(symbol, order.tp1_trigger)} (take profit 50%)",
        f"TP2: ${format_price(symbol, order.tp2_trigger)} (take profit remaining)",
        f"",
        f"\u23f1\ufe0f Cancel if not filled in 2 min",
    ]
    return "\n".join(lines)


def format_exit_orders(order: HyperliquidOrder) -> str:
    """
    Format SL/TP orders to set immediately after entry fill.

    The user sets these within seconds of fill confirmation.
    """
    symbol = order.symbol
    exit_side = "SELL" if order.side == "buy" else "BUY"

    lines = [
        f"Set these orders NOW:",
    ]

    # Stop loss: full size
    lines.append(
        f"1. Stop Market {exit_side} @ ${format_price(symbol, order.sl_trigger)} "
        f"(full size: {_fmt_qty(symbol, order.size)} {symbol})"
    )

    if order.size_remaining > 0:
        # TP1: half size
        lines.append(
            f"2. Limit {exit_side} @ ${format_price(symbol, order.tp1_trigger)} "
            f"(50%: {_fmt_qty(symbol, order.size_half)} {symbol})"
        )
        # TP2: remaining
        lines.append(
            f"3. Limit {exit_side} @ ${format_price(symbol, order.tp2_trigger)} "
            f"(remaining: {_fmt_qty(symbol, order.size_remaining)} {symbol})"
        )
    else:
        # Size too small to split — single TP at TP1
        lines.append(
            f"2. Limit {exit_side} @ ${format_price(symbol, order.tp1_trigger)} "
            f"(full size: {_fmt_qty(symbol, order.size)} {symbol})"
        )

    return "\n".join(lines)


def format_full_execution_block(order: HyperliquidOrder) -> str:
    """
    Combined quick entry + exit orders as a single Telegram message block.

    This is the format appended to sniper alerts.
    """
    entry = format_quick_entry(order)
    exits = format_exit_orders(order)
    sep = "\u2500" * 28
    return f"\n{sep}\n{entry}\n\n{sep}\n{exits}\n{sep}"


def _fmt_qty(symbol: str, qty: float) -> str:
    """Format quantity with appropriate decimal places for display."""
    if qty == 0:
        return "0"
    if qty >= 100:
        return f"{qty:,.0f}"
    elif qty >= 1:
        return f"{qty:.1f}"
    elif qty >= 0.01:
        return f"{qty:.2f}"
    else:
        return f"{qty:.4f}"
