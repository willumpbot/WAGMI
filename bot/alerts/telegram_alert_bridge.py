"""
Telegram Alert Bridge: sends Telegram notifications for critical trading events.

Hooks into the TradeEventLogger to send formatted alerts for:
- TRADE_OPENED: entry details, leverage, strategy, confidence
- TRADE_CLOSED (TP_HIT, SL_HIT): PnL, hold time, exit reason
- CIRCUIT_BREAKER: which breaker tripped, stats, cooldown
- BOT_RESTART: downtime, positions reconciled
- DAILY_SUMMARY: trades, WR, PnL, best/worst

Telegram failures never affect trading — all sends are wrapped in try/except.
If no token/chat_id configured, alerts are silently skipped.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable

import requests

logger = logging.getLogger("bot.alerts.telegram_bridge")


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


def _fmt_hold_time(seconds: float) -> str:
    """Format hold time as human-readable string."""
    if seconds <= 0:
        return "0s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{int(seconds)}s"


def format_trade_opened(record: Dict[str, Any]) -> str:
    """Format a TRADE_OPENED event for Telegram."""
    symbol = record.get("symbol", "???")
    side = record.get("side", "???")
    entry = record.get("entry", 0)
    leverage = record.get("leverage", 1.0)
    position_size = record.get("position_size", 0)
    strategy = record.get("strategy", "")
    confidence = record.get("confidence", 0)

    direction = "LONG" if side in ("BUY", "LONG") else "SHORT"
    parts = [
        f"OPENED: {symbol} {direction} @ ${_fmt_price(entry)}"
        f" | {leverage:.1f}x leverage"
    ]
    if position_size > 0:
        parts[0] += f" | ${position_size:,.2f} position"
    if confidence > 0:
        parts[0] += f" | confidence: {confidence:.0f}%"
    if strategy:
        parts.append(f"Strategy: {strategy}")
    return "\n".join(parts)


def format_trade_closed(record: Dict[str, Any]) -> str:
    """Format a TRADE_CLOSED / TP_HIT / SL_HIT event for Telegram."""
    symbol = record.get("symbol", "???")
    side = record.get("side", "???")
    exit_price = record.get("exit_price", record.get("exit", 0))
    entry_price = record.get("entry_price", record.get("entry", 0))
    pnl = record.get("pnl", 0)
    hold_time = record.get("hold_time", record.get("duration_s", 0))
    exit_reason = record.get("exit_reason", record.get("reason", ""))

    direction = "LONG" if side in ("BUY", "LONG") else "SHORT"
    pnl_pct = (pnl / (entry_price * record.get("position_size", 1)) * 100) if entry_price > 0 else 0
    # If position_size not available, try to compute from leverage
    if entry_price > 0 and pnl != 0 and abs(pnl_pct) > 1000:
        # Fallback: just show dollar PnL without %
        pnl_pct = 0

    hold_str = _fmt_hold_time(hold_time)

    # Map exit reasons to readable labels
    reason_labels = {
        "TP2": "TP2 hit",
        "TP1_FULL": "TP1 hit (full)",
        "SL": "stopped out",
        "TRAILING_STOP": "trailing stop",
        "TRAILING_WIN": "trailing win",
        "EARLY_EXIT": "early exit",
        "EMERGENCY": "emergency close",
        "HOLD_LIMIT": "hold limit",
        "LIQUIDATION_AVOID": "liquidation avoid",
    }
    reason_label = reason_labels.get(exit_reason, exit_reason or "closed")

    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    line = f"CLOSED: {symbol} {direction} @ ${_fmt_price(exit_price)}"
    line += f" | {pnl_str}"
    if pnl_pct != 0:
        pct_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"-{abs(pnl_pct):.1f}%"
        line += f" ({pct_str})"
    line += f" | held {hold_str} | {reason_label}"

    return line


def format_circuit_breaker(
    reason: str,
    daily_pnl: float = 0,
    consecutive_losses: int = 0,
    cooldown_minutes: int = 60,
) -> str:
    """Format a circuit breaker trip for Telegram."""
    daily_pnl_str = f"+${daily_pnl:,.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):,.2f}"
    parts = [f"CB TRIPPED: {reason}"]
    parts.append(f"Pausing {cooldown_minutes}min | Daily PnL: {daily_pnl_str}")
    if consecutive_losses > 0:
        parts.append(f"Consecutive losses: {consecutive_losses}")
    return "\n".join(parts)


def format_bot_restart(
    downtime_seconds: float = 0,
    positions_reconciled: int = 0,
    phantoms_closed: int = 0,
) -> str:
    """Format a bot restart notification for Telegram."""
    downtime_str = _fmt_hold_time(downtime_seconds)
    parts = [f"BOT RESTARTED: Down {downtime_str}"]
    parts.append(
        f"{positions_reconciled} positions reconciled | Resuming trading"
    )
    if phantoms_closed > 0:
        parts.append(f"Phantom positions closed: {phantoms_closed}")
    return "\n".join(parts)


def format_daily_summary(
    total_trades: int = 0,
    wins: int = 0,
    net_pnl: float = 0,
    best_trade: Optional[Dict[str, Any]] = None,
    worst_trade: Optional[Dict[str, Any]] = None,
    active_positions: int = 0,
) -> str:
    """Format a daily summary for Telegram."""
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    pnl_str = f"+${net_pnl:,.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):,.2f}"
    parts = [
        f"DAILY SUMMARY: {total_trades} trades | {wr:.0f}% WR | {pnl_str}"
    ]
    details = []
    if best_trade:
        sym = best_trade.get("symbol", "?")
        pnl = best_trade.get("pnl", 0)
        details.append(f"Best: {sym} +${pnl:,.2f}")
    if worst_trade:
        sym = worst_trade.get("symbol", "?")
        pnl = worst_trade.get("pnl", 0)
        w_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        details.append(f"Worst: {sym} {w_str}")
    if details:
        parts.append(" | ".join(details))
    if active_positions > 0:
        parts.append(f"Active positions: {active_positions}")
    return "\n".join(parts)


class TelegramAlertBridge:
    """
    Bridges TradeEventLogger events to Telegram notifications.

    Silently skips if no token/chat_id configured.
    Never raises exceptions to the caller — all errors are caught and logged.
    """

    # Events that trigger Telegram alerts
    ALERT_EVENTS = frozenset({
        "TRADE_OPENED",
        "TRADE_CLOSED",
        "TP_HIT",
        "SL_HIT",
    })

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        send_timeout: int = 10,
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.send_timeout = send_timeout
        self._enabled = bool(telegram_token and telegram_chat_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def on_trade_event(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Called when a trade event is logged. Formats and sends Telegram alert.

        Returns the formatted message (for testing), or None if skipped.
        """
        event = record.get("event", "")
        if event not in self.ALERT_EVENTS:
            return None

        try:
            if event == "TRADE_OPENED":
                msg = format_trade_opened(record)
            elif event in ("TRADE_CLOSED", "TP_HIT", "SL_HIT"):
                msg = format_trade_closed(record)
            else:
                return None

            self._send(msg)
            return msg
        except Exception as e:
            logger.warning(f"Telegram alert formatting failed: {e}")
            return None

    def send_circuit_breaker(
        self,
        reason: str,
        daily_pnl: float = 0,
        consecutive_losses: int = 0,
        cooldown_minutes: int = 60,
    ) -> Optional[str]:
        """Send circuit breaker alert. Returns formatted message or None."""
        try:
            msg = format_circuit_breaker(
                reason=reason,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                cooldown_minutes=cooldown_minutes,
            )
            self._send(msg)
            return msg
        except Exception as e:
            logger.warning(f"Telegram CB alert failed: {e}")
            return None

    def send_bot_restart(
        self,
        downtime_seconds: float = 0,
        positions_reconciled: int = 0,
        phantoms_closed: int = 0,
    ) -> Optional[str]:
        """Send bot restart alert. Returns formatted message or None."""
        try:
            msg = format_bot_restart(
                downtime_seconds=downtime_seconds,
                positions_reconciled=positions_reconciled,
                phantoms_closed=phantoms_closed,
            )
            self._send(msg)
            return msg
        except Exception as e:
            logger.warning(f"Telegram restart alert failed: {e}")
            return None

    def send_daily_summary(
        self,
        total_trades: int = 0,
        wins: int = 0,
        net_pnl: float = 0,
        best_trade: Optional[Dict[str, Any]] = None,
        worst_trade: Optional[Dict[str, Any]] = None,
        active_positions: int = 0,
    ) -> Optional[str]:
        """Send daily summary alert. Returns formatted message or None."""
        try:
            msg = format_daily_summary(
                total_trades=total_trades,
                wins=wins,
                net_pnl=net_pnl,
                best_trade=best_trade,
                worst_trade=worst_trade,
                active_positions=active_positions,
            )
            self._send(msg)
            return msg
        except Exception as e:
            logger.warning(f"Telegram daily summary failed: {e}")
            return None

    def _send(self, msg: str):
        """Send message to Telegram. Silently skips if not configured."""
        if not self._enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(
                url,
                json={"chat_id": self.telegram_chat_id, "text": msg},
                timeout=self.send_timeout,
            )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")


# Module-level singleton
_bridge: Optional[TelegramAlertBridge] = None


def get_telegram_alert_bridge(
    telegram_token: str = "",
    telegram_chat_id: str = "",
) -> TelegramAlertBridge:
    """Get or create the singleton TelegramAlertBridge."""
    global _bridge
    if _bridge is None:
        _bridge = TelegramAlertBridge(
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
        )
    return _bridge


def reset_telegram_alert_bridge():
    """Reset the singleton (for testing)."""
    global _bridge
    _bridge = None
