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
    ev_per_dollar: float = 0,
    fee_drag_pct: float = 0,
    regime_confidence: float = 0,
    chop_score: float = 0,
    setup_type: str = "",
    setup_wr: float = 0,
    setup_trades: int = 0,
    combo_edge: str = "",
    magnitude_bypass: bool = False,
    solo_trade: bool = False,
) -> str:
    """Format a trading signal as a clean, scannable Telegram message."""

    direction = "LONG" if side == "BUY" else "SHORT"

    # Grade
    if confidence >= 80 and num_agree >= 3:
        grade = "A+"
    elif confidence >= 70 and num_agree >= 2:
        grade = "A"
    elif confidence >= 60:
        grade = "B"
    else:
        grade = "C"

    # R:R
    risk = abs(entry - sl) if entry and sl else 0
    rr1 = abs(tp1 - entry) / risk if risk > 0 and tp1 else 0
    rr2 = abs(tp2 - entry) / risk if risk > 0 and tp2 else 0

    # Why we're taking this trade
    why_parts = []
    why_parts.append(f"{num_agree}/{total_strategies} strategies agree")
    if regime:
        why_parts.append(f"regime: {regime}")
    if ev_per_dollar > 0:
        why_parts.append(f"EV: +{ev_per_dollar:.2f}/dollar")
    if setup_type and setup_trades > 0:
        why_parts.append(f"{setup_type} setup ({setup_wr:.0%} WR)")

    # Build clean message
    lev_str = f" | {leverage:.0f}x" if leverage > 1 else ""
    lines = [
        f"{direction} {symbol} [{grade}] {confidence:.0f}%{lev_str}",
        f"",
        f"Entry: ${_fmt_price(entry)}",
        f"SL: ${_fmt_price(sl)} | TP1: ${_fmt_price(tp1)} ({rr1:.1f}R) | TP2: ${_fmt_price(tp2)} ({rr2:.1f}R)",
        f"",
        f"Why: {' | '.join(why_parts)}",
    ]

    # Flags (only if noteworthy)
    if solo_trade:
        lines.append("Note: solo signal, half size")
    if magnitude_bypass:
        lines.append("Note: magnitude bypass, reduced size")
    if chop_score > 0.55:
        lines.append(f"Warning: choppy market ({chop_score:.2f})")

    # History if available
    if total_trades_symbol >= 5:
        lines.append(f"Track record: {win_rate_symbol:.0%} WR on {symbol} ({total_trades_symbol} trades)")

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
    daily_pnl: float = 0,
    daily_trades: int = 0,
    daily_wins: int = 0,
    # Trade quality fields (for "traded this poorly" diagnosis)
    entry_price: float = 0,
    original_sl: float = 0,
    confidence: float = 0,
    num_agree: int = 0,
    ev_per_dollar: float = 0,
    regime: str = "",
    tp1_hit: bool = False,
    tp1_price: float = 0,
    max_favorable_pct: float = 0,
) -> str:
    """Format a trade event for Telegram. Clean, scannable, actionable.
    Includes trade quality diagnosis on losses."""

    is_close = action not in ("OPEN", "TP1")

    if action == "OPEN":
        dir_str = "LONG" if side in ("BUY", "LONG") else "SHORT"
        lines = [
            f"OPENED {dir_str} {symbol} @ ${_fmt_price(price)} | {leverage:.0f}x",
        ]
        if strategy:
            lines.append(f"Strategy: {strategy}")

    elif is_close:
        pnl_display = total_pnl if total_pnl != 0 else pnl
        result = "WIN" if pnl_display > 0 else "LOSS"

        # Hold time
        if hold_time_s > 3600:
            hold_str = f"{hold_time_s / 3600:.1f}h"
        elif hold_time_s > 60:
            hold_str = f"{hold_time_s / 60:.0f}m"
        else:
            hold_str = f"{hold_time_s:.0f}s"

        # Clean action label
        labels = {
            "TP2": "TP2 HIT", "SL": "STOPPED OUT", "TRAILING_STOP": "TRAILING WIN",
            "TRAILING_WIN": "TRAILING WIN", "EARLY_EXIT": "EARLY EXIT",
            "EMERGENCY": "EMERGENCY CLOSE", "HOLD_LIMIT": "HOLD LIMIT",
        }
        label = labels.get(action, action)

        lines = [
            f"CLOSED {symbol} - {result} ({label})",
            f"PnL: ${pnl_display:+,.2f} | Held: {hold_str}",
        ]

        if equity > 0:
            pct = pnl_display / equity * 100
            lines.append(f"Equity: ${equity:,.2f} ({pct:+.2f}%)")

        # Running daily summary after every close
        if daily_trades > 0:
            wr = daily_wins / daily_trades * 100 if daily_trades > 0 else 0
            lines.append(f"Today: {daily_trades} trades | {wr:.0f}% WR | ${daily_pnl:+,.2f}")

        # ── Trade quality diagnosis on losses ──
        if pnl_display < 0:
            issues = _diagnose_trade(
                action=action, hold_time_s=hold_time_s, pnl=pnl_display,
                leverage=leverage, confidence=confidence, num_agree=num_agree,
                ev_per_dollar=ev_per_dollar, entry_price=entry_price,
                exit_price=price, original_sl=original_sl, regime=regime,
                daily_pnl=daily_pnl, tp1_hit=tp1_hit, tp1_price=tp1_price,
                max_favorable_pct=max_favorable_pct,
            )
            if issues:
                lines.append("")
                lines.append("Traded this poorly:")
                for issue in issues[:3]:
                    lines.append(f"  - {issue}")

    else:
        # TP1 partial close
        lines = [
            f"TP1 HIT {symbol} | +${pnl:,.2f}",
            f"Trailing remainder to TP2",
        ]

    return "\n".join(lines)


def _diagnose_trade(
    action: str, hold_time_s: float, pnl: float,
    leverage: float, confidence: float, num_agree: int,
    ev_per_dollar: float, entry_price: float, exit_price: float,
    original_sl: float, regime: str, daily_pnl: float,
    tp1_hit: bool = False, tp1_price: float = 0,
    max_favorable_pct: float = 0,
) -> list:
    """Diagnose WHY a trade was poor. Returns list of issues."""
    issues = []

    # Didn't take profit - was winning but gave it back
    if tp1_hit and pnl < 0:
        issues.append("Hit TP1 but ended in a loss. Should have secured more profit at TP1.")
    elif not tp1_hit and max_favorable_pct > 1.5 and pnl < 0:
        issues.append(f"Was up {max_favorable_pct:.1f}% but didn't take profit. Tighten trailing or scale out.")
    elif tp1_hit and action in ("SL", "TRAILING_STOP", "TRAILING_WIN") and pnl > 0 and tp1_price > 0:
        # Won but gave back a lot after TP1
        if entry_price > 0:
            tp1_profit_pct = abs(tp1_price - entry_price) / entry_price * 100
            actual_profit_pct = abs(exit_price - entry_price) / entry_price * 100
            if actual_profit_pct < tp1_profit_pct * 0.5:
                issues.append(f"Hit TP1 but gave most back. Exited at {actual_profit_pct:.1f}% vs TP1 at {tp1_profit_pct:.1f}%.")

    # Fast stop = entered at a bad level or stop too tight
    if hold_time_s < 120 and action == "SL":
        issues.append("Stopped in under 2 min. Entry level was off or SL too tight.")

    # Low confidence trade that lost = shouldn't have taken it
    if confidence > 0 and confidence < 65:
        issues.append(f"Low confidence ({confidence:.0f}%). Shouldn't trade below 65%.")

    # Solo strategy (1 agree) loss = not enough consensus
    if num_agree == 1:
        issues.append("Only 1 strategy agreed. Solo signals are risky.")

    # Negative EV trade that lost = math was against us
    if ev_per_dollar < 0:
        issues.append(f"Negative EV ({ev_per_dollar:.3f}). Edge wasn't there.")

    # High leverage loss = sizing was too aggressive
    if leverage >= 5 and abs(pnl) > 20:
        issues.append(f"High leverage ({leverage:.0f}x) amplified the loss. Consider lower sizing.")

    # Stopped out far from original SL = slippage or SL moved
    if original_sl > 0 and entry_price > 0 and exit_price > 0:
        expected_loss_pct = abs(entry_price - original_sl) / entry_price * 100
        actual_loss_pct = abs(entry_price - exit_price) / entry_price * 100
        if actual_loss_pct > expected_loss_pct * 1.5 and actual_loss_pct > 1:
            issues.append(f"Lost {actual_loss_pct:.1f}% vs expected {expected_loss_pct:.1f}% SL. Slippage or gap.")

    # Choppy regime loss
    if regime and regime.lower() in ("range", "consolidation", "choppy"):
        issues.append(f"Traded in {regime} regime. Avoid trend entries in chop.")

    # Accumulating daily losses
    if daily_pnl < -50:
        issues.append("Daily losses piling up. Consider pausing for the day.")

    # If nothing specific found but it's still a loss
    if not issues and action == "SL":
        issues.append("Clean stop. Risk was managed correctly.")

    return issues


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
    """Format end-of-day report. Clean summary + what to fix."""
    wr = wins / total_trades * 100 if total_trades > 0 else 0
    verdict = "Good day." if net_pnl > 0 else "Rough day." if net_pnl < -20 else "Flat day."

    lines = [
        f"DAILY REPORT - {date}",
        f"",
        f"{verdict}",
        f"{wins}W/{losses}L ({wr:.0f}% WR) | ${net_pnl:+,.2f}",
        f"Equity: ${equity:,.2f}",
    ]

    # Best/worst by strategy (keep it short)
    if by_strategy:
        sorted_strats = sorted(by_strategy.items(), key=lambda x: x[1].get("pnl", 0), reverse=True)
        if sorted_strats:
            best = sorted_strats[0]
            b_wr = best[1].get("wins", 0) / max(best[1].get("trades", 1), 1) * 100
            lines.append(f"Best: {best[0]} (${best[1].get('pnl', 0):+,.2f}, {b_wr:.0f}% WR)")
        if len(sorted_strats) > 1:
            worst = sorted_strats[-1]
            if worst[1].get("pnl", 0) < 0:
                w_wr = worst[1].get("wins", 0) / max(worst[1].get("trades", 1), 1) * 100
                lines.append(f"Worst: {worst[0]} (${worst[1].get('pnl', 0):+,.2f}, {w_wr:.0f}% WR)")

    # By symbol (only if multiple)
    if by_symbol and len(by_symbol) > 1:
        lines.append("")
        for sym, stats in sorted(by_symbol.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
            s_wr = stats.get("wins", 0) / max(stats.get("trades", 1), 1) * 100
            lines.append(f"  {sym}: ${stats.get('pnl', 0):+,.2f} ({stats.get('trades', 0)}t, {s_wr:.0f}%)")

    # Actionable flags
    flags = []
    if wr < 40 and total_trades >= 3:
        flags.append("Low win rate - check if signals are too aggressive")
    if losses >= 3 and wins == 0:
        flags.append("No wins today - consider tightening entry criteria")
    if total_trades == 0:
        flags.append("No trades executed - check if gates are too strict")
    if net_pnl < -50:
        flags.append("Significant loss - review risk sizing")
    if total_trades >= 10:
        flags.append("High trade count - check for overtrading")

    if by_strategy:
        for strat, stats in by_strategy.items():
            if stats.get("trades", 0) >= 3 and stats.get("pnl", 0) < -30:
                s_wr = stats.get("wins", 0) / max(stats.get("trades", 1), 1) * 100
                flags.append(f"{strat} bleeding (${stats.get('pnl', 0):+,.2f}) - consider reducing weight")

    if flags:
        lines.append("")
        lines.append("Action items:")
        for f in flags[:3]:  # Max 3 flags
            lines.append(f"  - {f}")

    return "\n".join(lines)
