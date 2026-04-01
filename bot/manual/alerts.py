"""
Manual Sniper Telegram Alert Formatter.

Produces actionable, copy-paste-ready alerts for manual execution.
Each alert includes exact entry, SL, TP, leverage, qty, margin needed,
expected P&L, and account growth projection.

Optimized for aggressive small account scaling ($100+).
"""

import logging
import requests
import time
from typing import Optional, Dict, Any

from manual.sniper_filter import SniperSignal
from manual.config import ManualSniperConfig
from manual.execution_helper import (
    HyperliquidOrderBuilder,
    format_full_execution_block,
)

logger = logging.getLogger("bot.manual.alerts")


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


def _confidence_bar(conf: float) -> str:
    """Visual confidence bar."""
    filled = int(conf / 10)
    return "\u2588" * filled + "\u2591" * (10 - filled)


def _tier_header(tier: str) -> str:
    """Tier-specific header."""
    if tier == "MICRO_SNIPER":
        return "\U0001f52b MICRO-SNIPER — LOTTERY TICKET"
    elif tier == "SNIPER":
        return "\U0001f3af SNIPER — MAX CONVICTION"
    elif tier == "PREMIUM":
        return "\u26a1 PREMIUM SETUP"
    else:
        return "\U0001f4ca STANDARD"


def format_sniper_alert(sniper: SniperSignal, equity: float = 100) -> str:
    """
    Format a manual sniper signal as an actionable Telegram message.

    Optimized for glance-speed reading at 25x leverage.
    Structure: ACTION → LEVELS → SIZING → P&L (that's it).
    The Hyperliquid execution block at the bottom has exact order params.
    """
    direction = "LONG" if sniper.side == "BUY" else "SHORT"
    acct = sniper.account_equity

    # Stop/TP widths as %
    stop_pct = abs(sniper.entry - sniper.sl) / sniper.entry * 100 if sniper.entry > 0 else 0

    # ── HEADER: What to do ──
    lines = [
        f"\u2550" * 32,
        f"  {_tier_header(sniper.tier)}",
        f"  {direction} {sniper.symbol} @ {_fmt_price(sniper.entry)}",
        f"  {sniper.leverage:.0f}x | {sniper.num_agree} agree | {sniper.confidence:.0f}%",
        f"\u2550" * 32,
    ]

    # ── LEVELS: Where to set orders ──
    lines.extend([
        f"",
        f"Entry:    {_fmt_price(sniper.entry)}",
        f"Stop:     {_fmt_price(sniper.sl)}  (-{stop_pct:.1f}%)",
        f"Scalp TP: {_fmt_price(sniper.tp_scalp)}  ({sniper.rr_scalp:.1f}R)",
        f"Swing TP: {_fmt_price(sniper.tp_swing)}  ({sniper.rr_swing:.1f}R)",
    ])

    # ── SIZING: How much ──
    lines.extend([
        f"",
        f"Margin: ${sniper.margin_required:,.2f} / ${acct:,.2f} acct",
        f"Size:   {sniper.qty:.4f} {sniper.symbol} (${sniper.position_size_usd:,.0f})",
    ])

    # ── P&L: What's at stake ──
    lines.extend([
        f"",
        f"Win:  +${sniper.pnl_scalp:,.2f} (+{sniper.growth_pct:.0f}%)",
        f"Loss: -${sniper.loss_amount:,.2f}",
    ])

    # ── Regime context (one line) ──
    lines.append(f"")
    lines.append(f"Regime: {sniper.regime} | Hold: {sniper.hold_target_hours}")

    if sniper.tier == "MICRO_SNIPER":
        lines.append(f"\U0001f52b MICRO-SNIPER: {sniper.risk_pct*100:.0f}% risk, {sniper.leverage:.0f}x lev, 3h time-stop")
        lines.append(f"   Asymmetric: risk ${sniper.loss_amount:.2f} to make ${sniper.pnl_scalp:.2f}")

    if getattr(sniper, 'is_dip_buy', False):
        lines.append(f"\U0001f4c9 DIP-BUY setup — higher conviction (88.5% WR)")

    if sniper.signal_context:
        lines.append(f"Why: {sniper.signal_context[:120]}")

    # Append Hyperliquid execution block (exact order parameters)
    try:
        builder = HyperliquidOrderBuilder()
        hl_order = builder.from_sniper_signal(sniper)
        lines.append(format_full_execution_block(hl_order))
    except Exception as e:
        logger.warning(f"[SNIPER-ALERT] Execution helper failed: {e}")

    lines.append(f"\u2550" * 32)

    return "\n".join(lines)


def format_daily_summary(summary: Dict[str, Any]) -> str:
    """Format daily manual signal summary for Telegram."""
    acct = summary.get('account_equity', 100)
    mode = summary.get('mode', 'aggressive')
    mode_label = "AGGRESSIVE" if mode == "aggressive" else "STANDARD"

    lines = [
        f"\u2550" * 32,
        f"  \U0001f3af SNIPER DAILY SUMMARY ({mode_label})",
        f"\u2550" * 32,
        f"",
        f"Account: ${acct:,.2f}",
        f"Signals: {summary['signals_sent']}/{summary['max_signals']}",
        f"",
        f"If all scalp TPs hit:",
        f"  Win:  +${summary['total_potential_scalp']:,.2f}",
        f"  Risk: -${summary['total_risk']:,.2f}",
        f"  Target coverage: {summary['target_coverage_scalp_pct']:.0f}%",
    ]

    tiers = summary.get("by_tier", {})
    if any(v > 0 for v in tiers.values()):
        lines.append(f"")
        for tier, count in tiers.items():
            if count > 0:
                emoji = {"MICRO_SNIPER": "\U0001f52b", "SNIPER": "\U0001f3af", "PREMIUM": "\u26a1", "STANDARD": "\U0001f4ca"}.get(tier, "")
                lines.append(f"  {emoji} {tier}: {count}")

    lines.append(f"\u2550" * 32)
    return "\n".join(lines)


class ManualSniperAlerter:
    """Sends manual sniper signals via Telegram with dedup."""

    # Alert cooldown per setup (symbol+side+price_bucket).
    # Same setup won't fire again within this window.
    ALERT_COOLDOWN_S = 1800  # 30 minutes between alerts for the same setup

    def __init__(self, config: Optional[ManualSniperConfig] = None):
        self.config = config or ManualSniperConfig()
        self._last_alert: Dict[str, float] = {}  # setup_key -> unix timestamp

    def _alert_key(self, sniper: SniperSignal) -> str:
        """Create dedup key from signal. Groups by symbol+side+price bucket."""
        # Round entry to 1% bucket so slight price changes don't spam
        bucket = round(sniper.entry * 100) if sniper.entry < 1 else round(sniper.entry, 1)
        return f"{sniper.symbol}_{sniper.side}_{bucket}"

    def send_sniper_alert(self, sniper: SniperSignal, equity: float = 100) -> bool:
        """Send a sniper signal alert to Telegram (with dedup)."""
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            logger.warning("[SNIPER-ALERT] No Telegram credentials configured")
            return False

        # Dedup: skip if same setup alerted recently
        key = self._alert_key(sniper)
        now = time.time()
        last = self._last_alert.get(key, 0)
        if now - last < self.ALERT_COOLDOWN_S:
            mins_ago = (now - last) / 60
            logger.debug(
                f"[SNIPER-ALERT] Skipping {key} — last alert {mins_ago:.0f}m ago "
                f"(cooldown {self.ALERT_COOLDOWN_S // 60}m)"
            )
            return False

        self._last_alert[key] = now
        msg = format_sniper_alert(sniper, equity)
        return self._send_telegram(msg)

    def send_daily_summary(self, summary: Dict[str, Any]) -> bool:
        """Send daily summary to Telegram."""
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            return False
        msg = format_daily_summary(summary)
        return self._send_telegram(msg)

    def _send_telegram(self, msg: str, retries: int = 2) -> bool:
        """Send message via Telegram API with retry on failure."""
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
        for attempt in range(retries + 1):
            try:
                resp = requests.post(url, json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": msg,
                }, timeout=10)

                if resp.status_code == 200:
                    logger.info("[SNIPER-ALERT] Telegram alert sent")
                    return True
                elif resp.status_code == 429:
                    # Rate limited — back off
                    wait = min(2 ** attempt, 10)
                    logger.warning(f"[SNIPER-ALERT] Telegram rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                else:
                    logger.warning(f"[SNIPER-ALERT] Telegram error: {resp.status_code} {resp.text[:200]}")
                    return False
            except requests.exceptions.Timeout:
                if attempt < retries:
                    logger.warning(f"[SNIPER-ALERT] Telegram timeout, retrying ({attempt + 1}/{retries})")
                    time.sleep(1)
                    continue
                logger.warning("[SNIPER-ALERT] Telegram timeout after retries")
                return False
            except Exception as e:
                logger.warning(f"[SNIPER-ALERT] Telegram send failed: {e}")
                return False
        return False
