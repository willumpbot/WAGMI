"""
Alert routing for Discord and Telegram.
Routes signals to appropriate channels based on tier/priority.

Priority routing:
- PRIORITY signals -> Discord priority channel + Telegram
- REGULAR signals -> Discord all channel + Telegram (if conf >= threshold)
- MANUAL signals -> Discord all channel only

Includes dedup, rate limiting, and burst protection.
"""

import logging
import time
import requests
from collections import defaultdict, deque
from typing import Optional, Dict, Any

from strategies.base import Signal

logger = logging.getLogger("bot.alerts")


class AlertRouter:
    """
    Routes trading signals to Discord and Telegram with smart filtering.
    """

    def __init__(
        self,
        discord_webhook: str = "",
        discord_priority_webhook: str = "",
        telegram_token: str = "",
        telegram_chat_id: str = "",
        telegram_conf_threshold: int = 65,
        priority_conf_threshold: int = 75,
        min_gap_priority_s: int = 90,
        min_gap_regular_s: int = 45,
    ):
        self.discord_webhook = discord_webhook
        self.discord_priority_webhook = discord_priority_webhook
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_conf_threshold = telegram_conf_threshold
        self.priority_conf_threshold = priority_conf_threshold
        self.min_gap_priority_s = min_gap_priority_s
        self.min_gap_regular_s = min_gap_regular_s

        self._last_sent: Dict[str, Dict] = defaultdict(
            lambda: {"prio_ts": 0, "reg_ts": 0, "fingerprint": ""}
        )
        self._prio_burst: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5))

    def send_signal(self, signal: Signal, leverage: float = 1.0, tier: str = ""):
        """Route a signal to appropriate channels."""
        if not tier:
            if signal.confidence >= self.priority_conf_threshold:
                tier = "PRIORITY"
            elif signal.confidence >= self.telegram_conf_threshold:
                tier = "REGULAR"
            else:
                tier = "MANUAL"

        # Dedup check
        now = int(time.time())
        ls = self._last_sent[signal.symbol]
        fp = f"{signal.symbol}:{signal.side}:{tier}:{int(signal.confidence)}"

        if fp == ls["fingerprint"] and (now - max(ls["prio_ts"], ls["reg_ts"])) < 180:
            return

        # Rate limit check
        if tier == "PRIORITY" and (now - ls["prio_ts"]) < self.min_gap_priority_s:
            return
        if tier == "REGULAR" and (now - ls["reg_ts"]) < self.min_gap_regular_s:
            return

        # Format message
        msg = self._format_signal(signal, leverage, tier)

        # Route
        if tier == "PRIORITY":
            ls["prio_ts"] = now
            self._send_discord(msg, priority=True)
            self._send_discord(msg, priority=False)
            self._send_telegram(msg)
        elif tier == "REGULAR":
            ls["reg_ts"] = now
            self._send_discord(msg, priority=False)
            if signal.confidence >= self.telegram_conf_threshold:
                self._send_telegram(msg)
        else:  # MANUAL
            self._send_discord(msg, priority=False)

        ls["fingerprint"] = fp

    def send_trade_event(self, event_type: str, symbol: str, details: str):
        """Send a trade event notification (open, close, TP, SL, etc.)."""
        msg = f"[TRADE] {event_type} | {symbol}\n{details}"
        self._send_discord(msg)
        if event_type in ("OPEN", "TP2", "SL", "TRAILING_STOP"):
            self._send_telegram(msg)

    def send_heartbeat(self, status: Dict[str, Any]):
        """Send periodic heartbeat with bot status."""
        equity = status.get("equity", 0)
        positions = status.get("open_positions", 0)
        daily_pnl = status.get("daily_pnl", 0)
        ml_samples = status.get("ml_samples", 0)

        msg = (
            f"[HEARTBEAT]\n"
            f"Equity: ${equity:,.2f} | Positions: {positions}\n"
            f"Daily PnL: ${daily_pnl:+,.2f} | ML Samples: {ml_samples}"
        )
        self._send_discord(msg)

    def send_market_update(self, msg: str):
        """Send periodic market status update (even without signals)."""
        self._send_discord(msg)
        self._send_telegram(msg)

    def send_startup(self, symbols: list, strategies: int, leverage_max: float):
        """Send a startup confirmation message to verify alerts are working."""
        msg = (
            f"[NunuIRL Bot Started]\n"
            f"Mode: Paper Trading\n"
            f"Symbols: {', '.join(symbols)}\n"
            f"Strategies: {strategies} active\n"
            f"Max Leverage: {leverage_max:.0f}x\n"
            f"Alerts: Active — you'll receive signals here!"
        )
        self._send_discord(msg)
        self._send_telegram(msg)

    def send_circuit_breaker(self, reason: str):
        """Alert when circuit breaker triggers."""
        msg = f"CIRCUIT BREAKER TRIPPED\nReason: {reason}\nTrading halted until cooldown expires."
        self._send_discord(msg, priority=True)
        self._send_telegram(msg)

    @staticmethod
    def _fmt(price: float) -> str:
        """Format price with appropriate precision (handles micro-prices like PEPE)."""
        if price == 0:
            return "0"
        abs_p = abs(price)
        if abs_p >= 1.0:
            return f"{price:,.2f}"
        elif abs_p >= 0.001:
            return f"{price:.4f}"
        elif abs_p >= 0.000001:
            return f"{price:.8f}"
        else:
            return f"{price:.12f}"

    def _format_signal(self, signal: Signal, leverage: float, tier: str) -> str:
        icon = {"PRIORITY": "PRIORITY", "REGULAR": "REGULAR", "MANUAL": "MANUAL"}.get(tier, "SIGNAL")
        lev_str = f" | {leverage:.1f}x" if leverage > 1 else " | Spot"
        strategies = signal.metadata.get("strategies_agree", [signal.strategy])
        strat_str = ", ".join(strategies) if isinstance(strategies, list) else str(strategies)
        f = self._fmt

        lines = [
            f"[{icon}] {signal.symbol} {signal.side} | Conf {signal.confidence:.0f}%{lev_str}",
            f"Strategies: {strat_str}",
            f"Entry: {f(signal.entry)} | SL: {f(signal.sl)}",
            f"TP1: {f(signal.tp1)} | TP2: {f(signal.tp2)}",
        ]

        if signal.atr > 0:
            lines.append(f"ATR: {f(signal.atr)} | R:R1={signal.risk_reward_tp1:.1f} R:R2={signal.risk_reward_tp2:.1f}")

        return "\n".join(lines)

    def _send_discord(self, msg: str, priority: bool = False):
        webhook = self.discord_priority_webhook if priority else self.discord_webhook
        if not webhook:
            return
        try:
            r = requests.post(webhook, json={"content": msg}, timeout=10)
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 1))
                time.sleep(retry_after)
                requests.post(webhook, json={"content": msg}, timeout=10)
        except Exception as e:
            logger.warning(f"Discord send failed: {e}")

    def _send_telegram(self, msg: str):
        if not self.telegram_token or not self.telegram_chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={
                "chat_id": self.telegram_chat_id,
                "text": msg,
            }, timeout=10)
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
