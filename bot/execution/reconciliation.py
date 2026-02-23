"""
Position reconciliation: restore state from exchange on startup.

On restart, the bot has no knowledge of open positions. This module
queries Hyperliquid for open positions and rebuilds the PositionManager
state so the bot can manage them (trailing stop, TP, etc).

What we CAN recover from the exchange:
  - Symbol, side, entry price, quantity, leverage, unrealized PnL

What we CANNOT recover (estimated from ATR):
  - Original SL / TP1 / TP2 (set conservative defaults)
  - Trade profile / entry type
  - State machine path (assume OPEN)

Design:
  - Safe to call when no positions exist (no-op)
  - Safe to call when CCXT is unavailable (logs warning, continues)
  - Never overwrites positions already in pos_mgr
  - Logs every reconciled position clearly
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from execution.position_manager import PositionManager, Position
from execution.position_state import OPEN, TRAILING
from execution.precision import round_price, round_qty

logger = logging.getLogger("bot.execution.reconciliation")


# Reverse map: CCXT pair -> our symbol name
# Hyperliquid uses "BTC/USDC:USDC" format for perpetuals
_PAIR_TO_SYMBOL = {
    "BTC/USDC:USDC": "BTC",
    "ETH/USDC:USDC": "ETH",
    "SOL/USDC:USDC": "SOL",
    "HYPE/USDC:USDC": "HYPE",
    "XRP/USDC:USDC": "XRP",
    "AVAX/USDC:USDC": "AVAX",
    "LINK/USDC:USDC": "LINK",
    "SUI/USDC:USDC": "SUI",
    "NEAR/USDC:USDC": "NEAR",
    "ARB/USDC:USDC": "ARB",
    "DOGE/USDC:USDC": "DOGE",
    "WIF/USDC:USDC": "WIF",
    "KPEPE/USDC:USDC": "PEPE",
    "TIA/USDC:USDC": "TIA",
    "SEI/USDC:USDC": "SEI",
    "JUP/USDC:USDC": "JUP",
    "ONDO/USDC:USDC": "ONDO",
    "FARTCOIN/USDC:USDC": "FARTCOIN",
}


def reconcile_positions(
    pos_mgr: PositionManager,
    exchanges: Dict[str, object],
    last_prices: Dict[str, float],
    risk_mgr=None,
) -> int:
    """Query Hyperliquid for open positions and rebuild pos_mgr state.

    Args:
        pos_mgr: The bot's PositionManager (will be populated)
        exchanges: Dict of CCXT exchange instances from DataFetcher
        last_prices: Dict of symbol -> current price (for ATR estimation)
        risk_mgr: Optional RiskManager to restore daily PnL context

    Returns:
        Number of positions reconciled.
    """
    exchange = exchanges.get("hyperliquid")
    if exchange is None:
        logger.warning("[RECONCILE] No Hyperliquid exchange instance, skipping")
        return 0

    try:
        raw_positions = exchange.fetch_positions()
    except Exception as e:
        logger.warning(f"[RECONCILE] Failed to fetch positions from Hyperliquid: {e}")
        return 0

    if not raw_positions:
        logger.info("[RECONCILE] No open positions on Hyperliquid")
        return 0

    count = 0
    total_unrealized = 0.0

    for raw in raw_positions:
        try:
            result = _reconcile_one(raw, pos_mgr, last_prices)
            if result:
                count += 1
                total_unrealized += result.get("unrealized_pnl", 0)
        except Exception as e:
            symbol_info = raw.get("symbol", "unknown")
            logger.warning(f"[RECONCILE] Failed to reconcile {symbol_info}: {e}")

    if count > 0:
        logger.info(
            f"[RECONCILE] Restored {count} positions "
            f"(unrealized PnL: ${total_unrealized:+.2f})"
        )

        # Restore daily PnL context to circuit breaker
        if risk_mgr and total_unrealized != 0:
            logger.info(
                f"[RECONCILE] Unrealized PnL ${total_unrealized:+.2f} noted "
                f"(not added to daily PnL -- only realized trades count)"
            )

    return count


def _reconcile_one(
    raw: dict,
    pos_mgr: PositionManager,
    last_prices: Dict[str, float],
) -> Optional[dict]:
    """Reconcile a single position from CCXT raw data.

    CCXT position format (Hyperliquid):
    {
        'symbol': 'BTC/USDC:USDC',
        'side': 'long' or 'short',
        'contracts': 0.001,
        'entryPrice': 50000.0,
        'leverage': 10,
        'unrealizedPnl': 5.23,
        'notional': 50.0,
        ...
    }
    """
    pair = raw.get("symbol", "")
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        # Try to extract from pair (handle unknown pairs)
        base = pair.split("/")[0] if "/" in pair else pair
        from trading_config import DEFAULT_SYMBOLS
        if base in DEFAULT_SYMBOLS:
            symbol = base
        else:
            logger.debug(f"[RECONCILE] Skipping unknown pair: {pair}")
            return None

    # Skip if no meaningful position
    contracts = abs(float(raw.get("contracts", 0) or 0))
    if contracts <= 0:
        return None

    # Skip if pos_mgr already has this position (don't overwrite)
    existing = pos_mgr.positions.get(symbol)
    if existing and existing.state != "CLOSED":
        logger.info(f"[RECONCILE] {symbol} already in pos_mgr, skipping")
        return None

    # Extract position data
    side_raw = raw.get("side", "").lower()
    if side_raw == "long":
        side = "LONG"
    elif side_raw == "short":
        side = "SHORT"
    else:
        logger.debug(f"[RECONCILE] {symbol} unknown side: {side_raw}")
        return None

    entry = float(raw.get("entryPrice", 0) or 0)
    if entry <= 0:
        logger.warning(f"[RECONCILE] {symbol} has no entry price, skipping")
        return None

    leverage = float(raw.get("leverage", 1) or 1)
    unrealized = float(raw.get("unrealizedPnl", 0) or 0)
    qty = round_qty(symbol, contracts)

    # Estimate ATR from price (rough: 2% of price for majors, 4% for memes)
    from trading_config import DEFAULT_SYMBOLS
    sym_cfg = DEFAULT_SYMBOLS.get(symbol)
    tier = sym_cfg.risk_tier if sym_cfg else "medium"
    atr_pct = {"low": 0.015, "medium": 0.025, "high": 0.04}.get(tier, 0.025)
    estimated_atr = entry * atr_pct

    # Set conservative SL/TP based on estimated ATR
    if side == "LONG":
        sl = round_price(symbol, entry - estimated_atr * 2.0)
        tp1 = round_price(symbol, entry + estimated_atr * 1.5)
        tp2 = round_price(symbol, entry + estimated_atr * 3.0)
    else:
        sl = round_price(symbol, entry + estimated_atr * 2.0)
        tp1 = round_price(symbol, entry - estimated_atr * 1.5)
        tp2 = round_price(symbol, entry - estimated_atr * 3.0)

    # Check if position is in profit (may have passed TP1 already)
    current_price = last_prices.get(symbol, entry)
    in_profit = False
    if side == "LONG" and current_price > entry:
        in_profit = True
    elif side == "SHORT" and current_price < entry:
        in_profit = True

    # Build the Position object
    pos = Position(
        symbol=symbol,
        side=side,
        entry=entry,
        qty=qty,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        leverage=leverage,
        mode="leverage" if leverage > 1 else "spot",
        strategy="reconciled",
        confidence=0.0,
        atr=estimated_atr,
        tp1_close_pct=0.7,
        state=OPEN,
        state_path=[OPEN],
        original_qty=qty,
        original_sl=sl,
        trailing_distance=estimated_atr * 1.5,
        peak_price=current_price if in_profit else entry,
        open_time=datetime.now(timezone.utc),
    )

    # If significantly in profit, assume TP1 was hit and enter TRAILING
    profit_pct = abs(current_price - entry) / entry if entry > 0 else 0
    if in_profit and profit_pct > atr_pct * 1.5:
        # Likely past TP1, move to TRAILING with breakeven SL
        fee_buffer = entry * 0.002
        if side == "LONG":
            pos.sl = round_price(symbol, entry + fee_buffer)
        else:
            pos.sl = round_price(symbol, entry - fee_buffer)
        pos.state = TRAILING
        pos.state_path = [OPEN, "TP1_HIT", TRAILING]
        pos.peak_price = current_price
        logger.info(
            f"[RECONCILE] {symbol} in significant profit ({profit_pct:.1%}), "
            f"assuming TP1 hit -> TRAILING, SL at breakeven+={pos.sl}"
        )

    pos_mgr.positions[symbol] = pos

    logger.info(
        f"[RECONCILE] Restored {symbol} {side} @ {entry} qty={qty} "
        f"lev={leverage:.0f}x SL={sl} TP1={tp1} TP2={tp2} "
        f"state={pos.state} unrealized=${unrealized:+.2f}"
    )

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "qty": qty,
        "leverage": leverage,
        "unrealized_pnl": unrealized,
        "state": pos.state,
    }
