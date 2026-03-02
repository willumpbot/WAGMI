"""
Enhanced Telegram alert formatter: actionable trading signals with rich formatting.

Produces messages that traders can immediately act on:
- Clear entry/SL/TP levels
- Visual confidence bars
- Strategy consensus breakdown
- Historical win rate context
- Risk/reward ratios
- Position sizing guidance
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("bot.alerts.enhanced_telegram")


def _confidence_bar(conf: float) -> str:
    """Visual confidence bar for Telegram."""
    filled = int(conf / 10)
    empty = 10 - filled
    return "[" + "#" * filled + "-" * empty + "]"


def _fmt_price(price: float) -> str:
    """Format price with appropriate precision."""
    if price == 0:
        return "0"
    abs_p = abs(price)
    if abs_p >= 100:
        return f"{price:,.2f}"
    elif abs_p >= 1.0:
        return f"{price:.4f}"
    elif abs_p >= 0.001:
        return f"{price:.6f}"
    else:
        return f"{price:.10f}"


def format_signal_telegram(
    symbol: str,
    side: str,
    confidence: float,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    leverage: float = 1.0,
    strategies_agree: Optional[List[str]] = None,
    num_agree: int = 1,
    total_strategies: int = 4,
    regime: str = "",
    atr: float = 0,
    equity: float = 10000,
    risk_per_trade: float = 0.015,
    win_rate_symbol: float = 0,
    win_rate_strategy: float = 0,
    total_trades_symbol: int = 0,
    signal_score: float = 0,
) -> str:
    """Format a trading signal as an actionable Telegram message."""

    # Direction emoji
    dir_emoji = "LONG" if side == "BUY" else "SHORT"

    # Confidence tier
    if confidence >= 80 and num_agree >= 3:
        tier = "A+"
        tier_emoji = "!!!"
    elif confidence >= 70 and num_agree >= 2:
        tier = "A"
        tier_emoji = "!!"
    elif confidence >= 60:
        tier = "B"
        tier_emoji = "!"
    else:
        tier = "C"
        tier_emoji = ""

    # Risk/reward calculations
    risk = abs(entry - sl) if entry and sl else 0
    reward1 = abs(tp1 - entry) if entry and tp1 else 0
    reward2 = abs(tp2 - entry) if entry and tp2 else 0
    rr1 = reward1 / risk if risk > 0 else 0
    rr2 = reward2 / risk if risk > 0 else 0

    # Position sizing (based on equity and risk per trade)
    risk_amount = equity * risk_per_trade
    qty = risk_amount / risk if risk > 0 else 0
    position_value = qty * entry if entry > 0 else 0

    # Strategy consensus
    if strategies_agree:
        strat_list = ", ".join(strategies_agree)
    else:
        strat_list = "ensemble"

    # Build message
    lines = [
        f"{'=' * 30}",
        f"  {dir_emoji} {symbol} | Grade {tier}{tier_emoji}",
        f"{'=' * 30}",
        f"",
        f"Confidence: {_confidence_bar(confidence)} {confidence:.0f}%",
        f"Consensus:  {num_agree}/{total_strategies} strategies agree",
        f"Strategies: {strat_list}",
    ]

    if regime:
        lines.append(f"Regime:     {regime}")

    lines.extend([
        f"",
        f"--- Entry & Exits ---",
        f"Entry:  ${_fmt_price(entry)}",
        f"SL:     ${_fmt_price(sl)}  (Risk: ${risk:,.2f})",
        f"TP1:    ${_fmt_price(tp1)}  (R:R {rr1:.1f}x)",
        f"TP2:    ${_fmt_price(tp2)}  (R:R {rr2:.1f}x)",
    ])

    if leverage > 1:
        lines.append(f"Leverage: {leverage:.0f}x")

    # Position sizing guidance
    lines.extend([
        f"",
        f"--- Position Size ---",
        f"Risk amount: ${risk_amount:,.2f} ({risk_per_trade:.1%} of ${equity:,.0f})",
    ])
    if qty > 0:
        lines.append(f"Suggested qty: {qty:.4f} {symbol}")
        lines.append(f"Position value: ${position_value:,.2f}")

    # Historical context
    if total_trades_symbol > 0:
        lines.extend([
            f"",
            f"--- History ---",
            f"Symbol WR: {win_rate_symbol:.0%} ({total_trades_symbol} trades)",
        ])
        if win_rate_strategy > 0:
            lines.append(f"Strategy WR: {win_rate_strategy:.0%}")
        if signal_score > 0:
            lines.append(f"Signal score: {signal_score:.0f}/100")

    # Action guidance
    lines.extend([
        f"",
        f"--- Action ---",
    ])
    if tier in ("A+", "A"):
        lines.append(f"Strong setup. Execute if risk budget allows.")
    elif tier == "B":
        lines.append(f"Moderate setup. Wait for confirmation or use reduced size.")
    else:
        lines.append(f"Weak setup. Consider skipping or paper-only.")

    lines.append(f"{'=' * 30}")

    return "\n".join(lines)


def format_trade_event_telegram(
    action: str,
    symbol: str,
    side: str,
    price: float,
    pnl: float = 0,
    leverage: float = 1.0,
    total_pnl: float = 0,
    hold_time_s: float = 0,
    strategy: str = "",
    equity: float = 0,
) -> str:
    """Format a trade event (open/close/TP/SL) for Telegram."""

    # Action emoji and formatting
    action_labels = {
        "OPEN": "OPENED",
        "TP1": "TP1 HIT",
        "TP2": "TP2 HIT (CLOSED)",
        "SL": "STOP LOSS",
        "TRAILING_STOP": "TRAILING STOP",
        "EARLY_EXIT": "EARLY EXIT",
        "EMERGENCY": "EMERGENCY CLOSE",
        "LIQUIDATION_AVOID": "LIQUIDATION AVOIDED",
        "FUNDING_AVOIDANCE": "FUNDING CLOSE",
        "ROTATE_PROFIT": "ROTATED (PROFIT)",
        "ROTATE_LOSS": "ROTATED (LOSS CUT)",
    }
    label = action_labels.get(action, action)

    is_close = action not in ("OPEN", "TP1")

    lines = []

    if action == "OPEN":
        dir_str = "LONG" if side == "BUY" or side == "LONG" else "SHORT"
        lines = [
            f"--- {dir_str} {symbol} ---",
            f"Entry: ${_fmt_price(price)}",
            f"Leverage: {leverage:.0f}x",
        ]
        if strategy:
            lines.append(f"Strategy: {strategy}")

    elif is_close:
        result = "WIN" if pnl > 0 else "LOSS"
        pnl_display = total_pnl if total_pnl != 0 else pnl

        # Hold time formatting
        if hold_time_s > 3600:
            hold_str = f"{hold_time_s / 3600:.1f}h"
        elif hold_time_s > 60:
            hold_str = f"{hold_time_s / 60:.0f}m"
        else:
            hold_str = f"{hold_time_s:.0f}s"

        lines = [
            f"--- {label} {symbol} ---",
            f"Result: {result}",
            f"Exit: ${_fmt_price(price)}",
            f"PnL: ${pnl_display:+,.2f}",
            f"Hold time: {hold_str}",
        ]
        if equity > 0:
            pct = pnl_display / equity * 100
            lines.append(f"Equity impact: {pct:+.2f}%")

    else:
        # TP1 partial close
        lines = [
            f"--- {label} {symbol} ---",
            f"Price: ${_fmt_price(price)}",
            f"Partial PnL: ${pnl:+,.2f}",
        ]

    return "\n".join(lines)


def format_heartbeat_telegram(
    equity: float,
    open_positions: int,
    daily_pnl: float,
    daily_trades: int,
    daily_wins: int,
    ml_samples: int = 0,
    uptime_h: float = 0,
    llm_mode: str = "",
    health_status: str = "OK",
) -> str:
    """Format periodic heartbeat for Telegram."""
    wr = daily_wins / daily_trades * 100 if daily_trades > 0 else 0
    lines = [
        f"--- NunuIRL Heartbeat ---",
        f"Status: {health_status}",
        f"Equity: ${equity:,.2f}",
        f"Positions: {open_positions}",
        f"Daily PnL: ${daily_pnl:+,.2f}",
        f"Daily trades: {daily_trades} ({wr:.0f}% WR)",
    ]
    if llm_mode:
        lines.append(f"LLM: {llm_mode}")
    if uptime_h > 0:
        lines.append(f"Uptime: {uptime_h:.1f}h")
    lines.append(f"{'=' * 25}")
    return "\n".join(lines)


def format_daily_report_telegram(
    date: str,
    total_trades: int,
    wins: int,
    losses: int,
    net_pnl: float,
    equity: float,
    best_strategy: str = "",
    worst_strategy: str = "",
    by_strategy: Optional[Dict[str, Dict]] = None,
    by_symbol: Optional[Dict[str, Dict]] = None,
) -> str:
    """Format end-of-day performance report."""
    wr = wins / total_trades * 100 if total_trades > 0 else 0

    lines = [
        f"{'=' * 30}",
        f"  Daily Report - {date}",
        f"{'=' * 30}",
        f"",
        f"Trades:   {total_trades}",
        f"W/L:      {wins}/{losses}",
        f"Win Rate: {wr:.0f}%",
        f"Net PnL:  ${net_pnl:+,.2f}",
        f"Equity:   ${equity:,.2f}",
    ]

    if by_strategy:
        lines.extend(["", "--- By Strategy ---"])
        for strat, stats in sorted(by_strategy.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
            s_wr = stats.get("wins", 0) / stats.get("trades", 1) * 100 if stats.get("trades", 0) > 0 else 0
            lines.append(
                f"  {strat}: {stats.get('trades', 0)} trades, "
                f"{s_wr:.0f}% WR, ${stats.get('pnl', 0):+,.2f}"
            )

    if by_symbol:
        lines.extend(["", "--- By Symbol ---"])
        for sym, stats in sorted(by_symbol.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
            s_wr = stats.get("wins", 0) / stats.get("trades", 1) * 100 if stats.get("trades", 0) > 0 else 0
            lines.append(
                f"  {sym}: {stats.get('trades', 0)} trades, "
                f"{s_wr:.0f}% WR, ${stats.get('pnl', 0):+,.2f}"
            )

    lines.append(f"{'=' * 30}")
    return "\n".join(lines)
