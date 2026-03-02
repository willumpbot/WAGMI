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

        # Burst protection: max 5 priority alerts per symbol in 10 minutes
        if tier == "PRIORITY":
            burst = self._prio_burst[signal.symbol]
            burst.append(now)
            recent_burst = sum(1 for t in burst if now - t < 600)
            if recent_burst >= 5:
                logger.info(
                    f"[ALERT] Burst protection: {signal.symbol} hit {recent_burst} "
                    f"priority alerts in 10min — suppressing"
                )
                return

        # Format message
        msg = self._format_signal(signal, leverage, tier)
        tg_msg = self._format_signal_telegram(signal, leverage, tier)

        # Route (set timestamps AFTER successful send)
        if tier == "PRIORITY":
            self._send_discord(msg, priority=True)
            self._send_discord(msg, priority=False)
            self._send_telegram(tg_msg)
            ls["prio_ts"] = now  # Set after send, not before
        elif tier == "REGULAR":
            self._send_discord(msg, priority=False)
            if signal.confidence >= self.telegram_conf_threshold:
                self._send_telegram(tg_msg)
            ls["reg_ts"] = now  # Set after send, not before
        else:  # MANUAL
            self._send_discord(msg, priority=False)

        ls["fingerprint"] = fp

    def send_trade_event(self, event_type: str, symbol: str, details: str):
        """Send a trade event notification (open, close, TP, SL, etc.)."""
        msg = f"[TRADE] {event_type} | {symbol}\n{details}"
        self._send_discord(msg)
        if event_type in ("OPEN", "TP2", "SL", "TRAILING_STOP", "EARLY_EXIT",
                          "EMERGENCY", "LIQUIDATION_AVOID"):
            tg_msg = self._format_trade_event_telegram(event_type, symbol, details)
            self._send_telegram(tg_msg)

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

    def _format_signal_telegram(self, signal: Signal, leverage: float, tier: str) -> str:
        """Format a signal as a rich, actionable Telegram message (MarkdownV2)."""
        side_emoji = "\U0001f7e2" if signal.side == "BUY" else "\U0001f534"
        tier_emoji = "\U0001f525" if tier == "PRIORITY" else "\u26a1" if tier == "REGULAR" else "\U0001f4cb"

        strategies = signal.metadata.get("strategies_agree", [signal.strategy])
        strat_str = ", ".join(strategies) if isinstance(strategies, list) else str(strategies)
        num_agree = signal.metadata.get("num_agree", 1)
        total_strats = signal.metadata.get("total_strategies", 4)
        regime = signal.metadata.get("regime", "unknown")
        f = self._fmt

        # Confidence bar
        filled = int(signal.confidence / 10)
        bar = "\u2588" * filled + "\u2591" * (10 - filled)

        # Risk/reward
        rr1 = signal.risk_reward_tp1 if hasattr(signal, 'risk_reward_tp1') else 0
        rr2 = signal.risk_reward_tp2 if hasattr(signal, 'risk_reward_tp2') else 0

        # SL distance %
        sl_dist = abs(signal.entry - signal.sl) / signal.entry * 100 if signal.entry > 0 else 0
        tp1_dist = abs(signal.tp1 - signal.entry) / signal.entry * 100 if signal.entry > 0 else 0
        tp2_dist = abs(signal.tp2 - signal.entry) / signal.entry * 100 if signal.entry > 0 else 0

        # Signal flags
        flags = signal.metadata.get("signal_flags", "")
        flag_line = f"\nFlags: {flags}" if flags else ""

        lev_str = f"{leverage:.1f}x" if leverage > 1 else "Spot"

        msg = (
            f"{side_emoji} {signal.symbol} {signal.side} {tier_emoji} {tier}\n"
            f"{'=' * 28}\n"
            f"Confidence: {bar} {signal.confidence:.0f}%\n"
            f"Consensus: {num_agree}/{total_strats} agree\n"
            f"Strategies: {strat_str}\n"
            f"Regime: {regime} | Leverage: {lev_str}\n"
            f"{'=' * 28}\n"
            f"Entry:  {f(signal.entry)}\n"
            f"SL:     {f(signal.sl)} ({sl_dist:.1f}%)\n"
            f"TP1:    {f(signal.tp1)} ({tp1_dist:.1f}%) R:R {rr1:.1f}\n"
            f"TP2:    {f(signal.tp2)} ({tp2_dist:.1f}%) R:R {rr2:.1f}"
            f"{flag_line}"
        )
        return msg

    def _format_trade_event_telegram(self, event_type: str, symbol: str, details: str) -> str:
        """Format a trade event as a rich Telegram message."""
        event_emojis = {
            "OPEN": "\U0001f680",
            "SL": "\U0001f6d1",
            "TP1": "\U0001f4b0",
            "TP2": "\U0001f3af",
            "TRAILING_STOP": "\U0001f4c8",
            "EARLY_EXIT": "\u23f1",
            "EMERGENCY": "\U0001f6a8",
            "LIQUIDATION_AVOID": "\u26a0",
            "ROTATE_PROFIT": "\U0001f504",
            "ROTATE_LOSS_AVOIDANCE": "\U0001f504",
            "FUNDING_AVOIDANCE": "\U0001f4b8",
        }
        emoji = event_emojis.get(event_type, "\u2139")

        return f"{emoji} {event_type} | {symbol}\n{'=' * 28}\n{details}"

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
