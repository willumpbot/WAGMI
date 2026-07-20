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

# This bridge is registered as a TradeEventLogger callback, so it receives
# the SAME record dict that gets written to trade_events.jsonl — including
# any pytest/backtest-in-process fabrication that ever shares the default
# (production) singleton logger before the write-guard in
# TradeEventLogger.log() closes that path. See core.structured_logging.
# is_fake_trade_event; fail open (never suppress a real alert) if the import
# ever breaks.
try:
    from core.structured_logging import is_fake_trade_event
except Exception:
    def is_fake_trade_event(evt):
        return False


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
    """Format a TRADE_OPENED event for Telegram — compact scannable format."""
    symbol = record.get("symbol", "???")
    side = record.get("side", "???")
    entry = record.get("entry", 0)
    leverage = record.get("leverage", 1.0)
    position_size = record.get("position_size", 0)
    strategy = record.get("strategy", "")
    confidence = record.get("confidence", 0)
    num_agree = record.get("num_agree", 0)
    brain_note = record.get("brain_note", "")

    direction = "LONG" if side in ("BUY", "LONG") else "SHORT"
    size_str = f" | ${position_size:,.0f}" if position_size > 0 else ""
    conf_str = f" | {confidence:.0f}%" if confidence > 0 else ""
    agree_str = f" ({num_agree}A)" if num_agree > 1 else ""

    line = f"OPENED {symbol} {direction} @ {_fmt_price(entry)} | {leverage:.0f}x{size_str}{conf_str}{agree_str}"
    if strategy:
        line += f"\n{strategy}"
    if brain_note:
        line += f"\nBrain: {brain_note}"
    return line


def format_trade_closed(record: Dict[str, Any]) -> str:
    """Format a TRADE_CLOSED / TP_HIT / SL_HIT event — compact scannable format."""
    symbol = record.get("symbol", "???")
    side = record.get("side", "???")
    exit_price = record.get("exit_price", record.get("exit", 0))
    entry_price = record.get("entry_price", record.get("entry", 0))
    # PNL_SEMANTICS_FIX (2026-07-20): trade_events.jsonl's `pnl` field now
    # means "this leg's own net contribution" (see position_manager.py
    # TP_HIT / SL_HIT / TP2 / TRADE_CLOSED tel.log() calls), not "cumulative
    # trade total" -- so a TP1-then-final-close trade would show only the
    # final leg's pnl here, understating the real total. `total_pnl` (added
    # alongside `pnl` on every close-type event) carries the true
    # whole-position cumulative net pnl as of this event; prefer it and fall
    # back to `pnl` for older records / event types that predate this field.
    pnl = record.get("total_pnl", record.get("pnl", 0))
    hold_time = record.get("hold_time", record.get("duration_s", 0))
    exit_reason = record.get("exit_reason", record.get("reason", ""))
    brain_note = record.get("brain_note", "")

    direction = "LONG" if side in ("BUY", "LONG") else "SHORT"
    hold_str = _fmt_hold_time(hold_time)

    # Compact exit reason
    reason_labels = {
        "TP2": "TP2", "TP1_FULL": "TP1", "SL": "SL",
        "TRAILING_STOP": "trail", "TRAILING_WIN": "trail-W",
        "EARLY_EXIT": "early", "EMERGENCY": "EMRG",
        "HOLD_LIMIT": "time", "LIQUIDATION_AVOID": "liq-avoid",
    }
    reason_label = reason_labels.get(exit_reason, exit_reason or "closed")

    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    pnl_pct = 0.0
    if entry_price > 0:
        pos_size = record.get("position_size", 1)
        if pos_size > 0:
            pnl_pct = pnl / pos_size * 100
    pct_part = f" ({pnl_pct:+.1f}%)" if abs(pnl_pct) > 0.01 and abs(pnl_pct) < 1000 else ""

    line = f"CLOSED {symbol} {direction} {pnl_str}{pct_part}"
    line += f"\nHold: {hold_str} | Entry: {_fmt_price(entry_price)} > Exit: {_fmt_price(exit_price)} | {reason_label}"
    if brain_note:
        line += f"\nBrain: {brain_note}"
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
    equity: float = 0,
    llm_cost: float = 0,
    llm_budget: float = 0,
    brain_note: str = "",
) -> str:
    """Format a daily summary for Telegram — compact dashboard format.

    DAILY_SUMMARY_GROSS_SINCE_RESTART_FIX (2026-07-20): label/header honesty
    only, no logic change — the producer now computes a real rolling 24h,
    net-of-fee/funding figure, so the message itself should say so instead of
    the previously-ambiguous "DAILY REPORT" / "P&L:" labels.
    """
    losses = total_trades - wins
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    pnl_str = f"+${net_pnl:,.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):,.2f}"

    parts = [f"DAILY REPORT (24h)"]
    parts.append(f"Net P&L: {pnl_str} | Trades: {total_trades} ({wins}W {losses}L) | WR: {wr:.0f}%")

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

    if equity > 0:
        parts.append(f"Equity: ${equity:,.2f}")
    if llm_budget > 0:
        parts.append(f"Brain: ${llm_cost:.2f}/${llm_budget:.2f} used")
    if active_positions > 0:
        parts.append(f"Open: {active_positions} positions")
    if brain_note:
        parts.append(f"Brain says: '{brain_note}'")
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
        self._command_bot = None  # Set by TelegramCommandBot for quiet/digest mode

    @property
    def enabled(self) -> bool:
        return self._enabled

    def on_trade_event(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Called when a trade event is logged. Formats and sends Telegram alert.
        Respects quiet/digest mode from TelegramCommandBot.

        Returns the formatted message (for testing), or None if skipped.
        """
        event = record.get("event", "")
        if event not in self.ALERT_EVENTS:
            return None
        if is_fake_trade_event(record):
            logger.debug(f"Telegram alert suppressed (fabricated/test event): {event}")
            return None

        # Quiet mode: suppress trade alerts (only circuit breakers + daily summary pass through)
        if self._command_bot and getattr(self._command_bot, '_quiet_mode', False):
            logger.debug(f"Telegram alert suppressed (quiet mode): {event}")
            return None

        try:
            if event == "TRADE_OPENED":
                msg = format_trade_opened(record)
            elif event in ("TRADE_CLOSED", "TP_HIT", "SL_HIT"):
                msg = format_trade_closed(record)
            else:
                return None

            # Digest mode: buffer instead of sending immediately
            if self._command_bot and getattr(self._command_bot, '_digest_mode', False):
                self._command_bot._digest_buffer.append(msg)
                # Flush every 30 minutes
                import time as _t
                _now = _t.time()
                _last = getattr(self._command_bot, '_last_digest_ts', 0)
                if _now - _last >= 1800:  # 30 min
                    self._flush_digest()
                    self._command_bot._last_digest_ts = _now
                return msg

            self._send(msg)
            return msg
        except Exception as e:
            logger.warning(f"Telegram alert formatting failed: {e}")
            return None

    def _flush_digest(self):
        """Send buffered digest messages as one combined message."""
        if not self._command_bot:
            return
        buf = self._command_bot._digest_buffer
        if not buf:
            return
        n = len(buf)
        combined = f"Digest ({n} events):\n\n" + "\n---\n".join(buf[-10:])  # Last 10
        self._send(combined)
        self._command_bot._digest_buffer = []

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
        equity: float = 0,
        llm_cost: float = 0,
        llm_budget: float = 0,
        brain_note: str = "",
    ) -> Optional[str]:
        """Send daily summary alert. Returns formatted message or None.

        DAILY_SUMMARY_GROSS_SINCE_RESTART_FIX (2026-07-20): added
        equity/llm_cost/llm_budget/brain_note passthrough. This is
        load-bearing, not cosmetic — the producer
        (multi_strategy_main.py._send_daily_summary) already calls this
        method with these kwargs, so the missing parameters previously
        raised TypeError on every single invocation, silently swallowed by
        the caller's outer try/except (logged at DEBUG only). The daily
        summary never reached Telegram at all until this signature matched.
        """
        try:
            msg = format_daily_summary(
                total_trades=total_trades,
                wins=wins,
                net_pnl=net_pnl,
                best_trade=best_trade,
                worst_trade=worst_trade,
                active_positions=active_positions,
                equity=equity,
                llm_cost=llm_cost,
                llm_budget=llm_budget,
                brain_note=brain_note,
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
