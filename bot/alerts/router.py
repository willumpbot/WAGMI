"""
Alert routing for Discord and Telegram.
Routes signals to appropriate channels based on tier/priority.

Priority routing:
- PRIORITY signals -> Discord priority channel + Telegram
- REGULAR signals -> Discord all channel + Telegram (if conf >= threshold)
- MANUAL signals -> Discord all channel only

Includes dedup, rate limiting, and burst protection.
"""

import json
import logging
import os
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

        self._state_path = os.path.join("data", "alert_state.json")
        self._load_state()

    def _load_state(self) -> None:
        """Restore rate-limit state from disk, pruning entries older than 600s."""
        try:
            if not os.path.exists(self._state_path):
                return
            with open(self._state_path, "r") as f:
                data = json.load(f)
            now = int(time.time())
            max_age = 600  # seconds

            for symbol, entry in data.get("last_sent", {}).items():
                prio_ts = entry.get("prio_ts", 0)
                reg_ts = entry.get("reg_ts", 0)
                # Only restore entries less than 600 seconds old
                if (now - max(prio_ts, reg_ts)) < max_age:
                    self._last_sent[symbol] = {
                        "prio_ts": prio_ts,
                        "reg_ts": reg_ts,
                        "fingerprint": entry.get("fingerprint", ""),
                    }

            for symbol, timestamps in data.get("prio_burst", {}).items():
                recent = deque(
                    (ts for ts in timestamps if (now - ts) < max_age),
                    maxlen=5,
                )
                if recent:
                    self._prio_burst[symbol] = recent

            logger.info(
                "[ALERT] Restored rate-limit state: %d symbols",
                len(self._last_sent),
            )
        except Exception as exc:
            logger.warning("[ALERT] Failed to load alert state: %s", exc)

    def _save_state(self) -> None:
        """Persist current rate-limit state to disk."""
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            data = {
                "last_sent": {
                    sym: dict(entry)
                    for sym, entry in self._last_sent.items()
                },
                "prio_burst": {
                    sym: list(dq)
                    for sym, dq in self._prio_burst.items()
                },
            }
            with open(self._state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("[ALERT] Failed to save alert state: %s", exc)

    def send_signal(self, signal: Signal, leverage: float = 1.0, tier: str = "", wallet_tag: str = ""):
        """Route a signal to appropriate channels.

        Args:
            wallet_tag: Optional prefix like "[A]" or "[B]" for dual wallet mode.
        """
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
        if wallet_tag:
            msg = f"[{wallet_tag}] {msg}"

        # Route (set timestamps AFTER successful send)
        # Telegram gets the ENHANCED signal only (sent separately in multi_strategy_main)
        # This raw format goes to Discord only to keep Telegram clean
        if tier == "PRIORITY":
            self._send_discord(msg, priority=True)
            self._send_discord(msg, priority=False)
            ls["prio_ts"] = now
        elif tier == "REGULAR":
            self._send_discord(msg, priority=False)
            ls["reg_ts"] = now
        else:  # MANUAL
            self._send_discord(msg, priority=False)

        ls["fingerprint"] = fp
        self._save_state()

    def send_trade_event(self, event_type: str, symbol: str, details: str, wallet_tag: str = ""):
        """Send a trade event notification (open, close, TP, SL, etc.).

        Telegram gets: opens, all closes (TP, SL, trailing, early exit, emergency).
        Discord gets everything.
        """
        prefix = f"[{wallet_tag}] " if wallet_tag else ""
        msg = f"{prefix}[TRADE] {event_type} | {symbol}\n{details}"
        self._send_discord(msg)
        # Send to Telegram for all trade opens and closes (the stuff that matters)
        tg_events = ("OPEN", "TP1", "TP2", "SL", "TRAILING_STOP", "TRAILING_WIN",
                      "EARLY_EXIT", "EMERGENCY", "LIQUIDATION_AVOID", "HOLD_LIMIT",
                      "ROTATE_PROFIT", "ROTATE_LOSS", "FUNDING_AVOIDANCE")
        if event_type in tg_events:
            self._send_telegram(msg)

    def send_heartbeat(self, status: Dict[str, Any]):
        """Send periodic heartbeat with bot status. Goes to both Discord and Telegram."""
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
        self._send_telegram(msg)

    def send_market_update(self, msg: str):
        """Send periodic market status update. Goes to both Discord and Telegram."""
        self._send_discord(msg)
        self._send_telegram(msg)

    def send_market_intel(self, intel: str):
        """Send market intelligence to help manual traders during quiet periods."""
        self._send_telegram(intel)

    def send_telegram_important(self, msg: str):
        """Send to Telegram only for truly important updates (daily report, circuit breaker)."""
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

    def send_missed_opportunity(self, symbol: str, side: str, confidence: float,
                                gate: str, potential_pct: float):
        """Alert when a blocked signal would have been profitable.

        Helps calibrate gate strictness. Only sends if potential > 3%.
        """
        if potential_pct < 3.0:
            return  # Don't spam for small misses

        msg = (
            f"[MISSED OPPORTUNITY]\n"
            f"{symbol} {side} | Conf {confidence:.0f}%\n"
            f"Blocked by: {gate}\n"
            f"Would have gained: +{potential_pct:.1f}%\n"
            f"Review gate settings if this happens often."
        )
        # Rate limit: max 1 missed opportunity alert per symbol per hour
        _key = f"missed_{symbol}"
        _now = time.time()
        _last = self._last_alert_time.get(_key, 0)
        if _now - _last < 3600:
            return
        self._last_alert_time[_key] = _now
        self._send_discord(msg)
        # Only send to Telegram for big misses (>5%)
        if potential_pct >= 5.0:
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
