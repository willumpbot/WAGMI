"""
Telegram Signal Ingestion Pipeline.

Monitors configured Telegram channels/groups for incoming trading signals
from external sources (signal providers, other traders, paid groups).

The pipeline:
  1. RECEIVE: Poll Telegram for new messages from configured channels
  2. PARSE: Extract structured signal data (symbol, side, entry, SL, TP)
  3. NORMALIZE: Convert to internal Signal format
  4. ROUTE: Send to LLM Signal Analyzer for evaluation
  5. LOG: Record everything for learning

Supported signal formats (auto-detected):
  - "BUY BTC 97500 SL 96000 TP 100000"
  - "LONG ETH entry: 3200 stop: 3100 target: 3500"
  - "SHORT SOL @ 145.50 / SL 150 / TP1 140 TP2 130"
  - Markdown/formatted messages with bold entries
  - Multi-line structured signals

Env vars:
  TELEGRAM_SIGNAL_TOKEN      - Bot token for signal monitoring (can reuse main bot token)
  TELEGRAM_SIGNAL_CHANNELS   - Comma-separated channel/group IDs to monitor
  TELEGRAM_SIGNAL_KEYWORDS   - Additional keywords to detect signals (optional)
"""

import json
import logging
import os
import re
import time
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("bot.signals.telegram_ingest")

_SIGNAL_LOG_DIR = os.path.join("data", "signals")
_SIGNAL_LOG_PATH = os.path.join(_SIGNAL_LOG_DIR, "ingested_signals.jsonl")


# ═══════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════


@dataclass
class IngestedSignal:
    """A trading signal parsed from a Telegram message."""
    signal_id: str = ""
    source_channel: str = ""
    source_channel_name: str = ""
    raw_message: str = ""
    timestamp: float = 0.0

    # Parsed fields
    symbol: str = ""
    side: str = ""           # LONG or SHORT
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    leverage: float = 1.0

    # Metadata
    confidence_keywords: List[str] = field(default_factory=list)
    parse_quality: float = 0.0  # 0-1, how well we parsed the message
    parse_method: str = ""      # which parser matched

    # Analysis results (filled after LLM processes it)
    llm_analyzed: bool = False
    llm_verdict: str = ""       # TAKE, SKIP, MODIFY
    llm_reasoning: str = ""
    llm_confidence: float = 0.0
    llm_analysis_id: str = ""


# ═══════════════════════════════════════════════════════════════
# Signal Parsers
# ═══════════════════════════════════════════════════════════════


# Common symbol aliases
SYMBOL_ALIASES = {
    "BITCOIN": "BTC", "BTC/USDT": "BTC", "BTCUSDT": "BTC", "XBTUSD": "BTC",
    "ETHEREUM": "ETH", "ETH/USDT": "ETH", "ETHUSDT": "ETH",
    "SOLANA": "SOL", "SOL/USDT": "SOL", "SOLUSDT": "SOL",
    "DOGE/USDT": "DOGE", "DOGEUSDT": "DOGE", "DOGECOIN": "DOGE",
    "PEPE/USDT": "PEPE", "PEPEUSDT": "PEPE",
    "HYPE/USDT": "HYPE", "HYPEUSDT": "HYPE", "HYPERLIQUID": "HYPE",
    "FARTCOIN/USDT": "FARTCOIN", "FARTCOINUSDT": "FARTCOIN",
}

SIDE_KEYWORDS = {
    "LONG": "LONG", "BUY": "LONG", "BULL": "LONG", "CALLS": "LONG",
    "SHORT": "SHORT", "SELL": "SHORT", "BEAR": "SHORT", "PUTS": "SHORT",
}

CONFIDENCE_KEYWORDS = [
    "high confidence", "strong signal", "sniper entry", "A+ setup",
    "conviction", "guaranteed", "easy money", "sure shot",
    "scalp", "risky", "speculative", "gamble", "degen",
]


def _clean_text(text: str) -> str:
    """Strip markdown formatting, emojis, and excessive whitespace."""
    # Remove markdown bold/italic
    text = re.sub(r'[*_~`]', '', text)
    # Remove common emojis (keep text)
    text = re.sub(r'[🟢🔴🟡⬆️⬇️📈📉🎯💰🔥🚀💎⚠️❌✅➡️▶️]', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_number(text: str, after_pattern: str) -> Optional[float]:
    """Extract a number that appears after a pattern."""
    pattern = rf'{after_pattern}\s*[:=@]?\s*\$?(\d+[\d,.]*)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        num_str = match.group(1).replace(',', '')
        try:
            return float(num_str)
        except ValueError:
            pass
    return None


def _extract_all_numbers(text: str) -> List[float]:
    """Extract all numbers from text."""
    numbers = []
    for match in re.finditer(r'(?<![a-zA-Z])\$?(\d+[\d,.]*\.?\d*)', text):
        num_str = match.group(1).replace(',', '')
        try:
            val = float(num_str)
            if val > 0:
                numbers.append(val)
        except ValueError:
            pass
    return numbers


def parse_signal_structured(text: str) -> Optional[IngestedSignal]:
    """Parse a structured signal with labeled fields.

    Matches formats like:
      LONG BTC
      Entry: 97500
      SL: 96000
      TP1: 100000
      TP2: 105000
    """
    clean = _clean_text(text)
    upper = clean.upper()

    # Detect side
    side = None
    for keyword, normalized in SIDE_KEYWORDS.items():
        if keyword in upper:
            side = normalized
            break

    if not side:
        return None

    # Detect symbol
    symbol = None
    # Check for known symbols/aliases
    for alias, canonical in SYMBOL_ALIASES.items():
        if alias in upper:
            symbol = canonical
            break

    # Also check raw symbol names
    if not symbol:
        known_symbols = ["BTC", "ETH", "SOL", "DOGE", "PEPE", "HYPE", "FARTCOIN",
                         "AVAX", "LINK", "ARB", "OP", "SUI", "APT", "WIF", "BONK"]
        for sym in known_symbols:
            if sym in upper:
                symbol = sym
                break

    if not symbol:
        return None

    # Extract prices
    entry = (
        _extract_number(clean, r'entry') or
        _extract_number(clean, r'@') or
        _extract_number(clean, r'at') or
        _extract_number(clean, r'price')
    )

    sl = (
        _extract_number(clean, r'(?:stop\s*loss|sl|stop)') or
        _extract_number(clean, r'stoploss')
    )

    tp1 = (
        _extract_number(clean, r'(?:take\s*profit\s*1|tp1|tp|target\s*1|target)') or
        _extract_number(clean, r'take\s*profit')
    )

    tp2 = (
        _extract_number(clean, r'(?:take\s*profit\s*2|tp2|target\s*2)') or
        None
    )

    tp3 = _extract_number(clean, r'(?:take\s*profit\s*3|tp3|target\s*3)')

    leverage = _extract_number(clean, r'(?:leverage|lev)')

    # Confidence keywords
    conf_kws = [kw for kw in CONFIDENCE_KEYWORDS if kw.lower() in clean.lower()]

    # Determine parse quality
    quality = 0.0
    if symbol:
        quality += 0.2
    if side:
        quality += 0.2
    if entry:
        quality += 0.2
    if sl:
        quality += 0.2
    if tp1:
        quality += 0.2

    if quality < 0.4:
        return None

    signal = IngestedSignal(
        signal_id=f"tg-{int(time.time()*1000)}",
        timestamp=time.time(),
        raw_message=text[:1000],
        symbol=symbol,
        side=side,
        entry_price=entry or 0.0,
        stop_loss=sl or 0.0,
        take_profit_1=tp1 or 0.0,
        take_profit_2=tp2 or 0.0,
        take_profit_3=tp3 or 0.0,
        leverage=leverage or 1.0,
        confidence_keywords=conf_kws,
        parse_quality=quality,
        parse_method="structured",
    )

    return signal


def parse_signal_inline(text: str) -> Optional[IngestedSignal]:
    """Parse an inline signal format.

    Matches formats like:
      "BUY BTC 97500 SL 96000 TP 100000"
      "SHORT SOL @ 145.50 / SL 150 / TP1 140 TP2 130"
    """
    clean = _clean_text(text)
    upper = clean.upper()

    # Quick check: must have a side keyword
    side = None
    for keyword, normalized in SIDE_KEYWORDS.items():
        if keyword in upper:
            side = normalized
            break

    if not side:
        return None

    # Must have a symbol
    symbol = None
    known_symbols = list(SYMBOL_ALIASES.values())
    known_symbols.extend(["BTC", "ETH", "SOL", "DOGE", "PEPE", "HYPE", "FARTCOIN",
                          "AVAX", "LINK", "ARB", "OP", "SUI", "APT", "WIF", "BONK"])

    for alias, canonical in SYMBOL_ALIASES.items():
        if alias in upper:
            symbol = canonical
            break

    if not symbol:
        for sym in known_symbols:
            if sym in upper:
                symbol = sym
                break

    if not symbol:
        return None

    # Try to extract numbers in context
    numbers = _extract_all_numbers(clean)

    # Labeled extraction
    entry = _extract_number(clean, r'(?:entry|@|at|price)')
    sl = _extract_number(clean, r'(?:sl|stop\s*loss|stop)')
    tp1 = _extract_number(clean, r'(?:tp1?|target|take\s*profit)')
    tp2 = _extract_number(clean, r'(?:tp2|target\s*2)')

    # If no labeled numbers, try positional (first=entry, second=SL, third=TP)
    if not entry and len(numbers) >= 1:
        # Filter out numbers that are likely leverage (1-200) or percentages
        price_numbers = [n for n in numbers if n > 0.5]
        if price_numbers:
            entry = price_numbers[0]
            if len(price_numbers) >= 2 and not sl:
                sl = price_numbers[1]
            if len(price_numbers) >= 3 and not tp1:
                tp1 = price_numbers[2]
            if len(price_numbers) >= 4 and not tp2:
                tp2 = price_numbers[3]

    quality = 0.0
    if symbol:
        quality += 0.2
    if side:
        quality += 0.2
    if entry:
        quality += 0.2
    if sl:
        quality += 0.2
    if tp1:
        quality += 0.2

    if quality < 0.4:
        return None

    conf_kws = [kw for kw in CONFIDENCE_KEYWORDS if kw.lower() in clean.lower()]

    return IngestedSignal(
        signal_id=f"tg-{int(time.time()*1000)}",
        timestamp=time.time(),
        raw_message=text[:1000],
        symbol=symbol,
        side=side,
        entry_price=entry or 0.0,
        stop_loss=sl or 0.0,
        take_profit_1=tp1 or 0.0,
        take_profit_2=tp2 or 0.0,
        confidence_keywords=conf_kws,
        parse_quality=quality,
        parse_method="inline",
    )


def parse_signal(text: str) -> Optional[IngestedSignal]:
    """Try all parsers and return the best match."""
    # Try structured first (multi-line, labeled)
    result = parse_signal_structured(text)
    if result and result.parse_quality >= 0.6:
        return result

    # Try inline
    inline = parse_signal_inline(text)
    if inline and inline.parse_quality >= 0.4:
        # If structured also matched but with lower quality, prefer inline
        if result and result.parse_quality > inline.parse_quality:
            return result
        return inline

    # Return whatever we got, even low quality
    return result or inline


# ═══════════════════════════════════════════════════════════════
# Signal Logger
# ═══════════════════════════════════════════════════════════════


def log_ingested_signal(signal: IngestedSignal):
    """Append an ingested signal to the JSONL log."""
    os.makedirs(_SIGNAL_LOG_DIR, exist_ok=True)
    try:
        with open(_SIGNAL_LOG_PATH, "a") as f:
            f.write(json.dumps(asdict(signal), default=str) + "\n")
    except IOError as e:
        logger.warning(f"Failed to log signal: {e}")


def get_recent_signals(limit: int = 50) -> List[Dict]:
    """Load recent ingested signals."""
    if not os.path.exists(_SIGNAL_LOG_PATH):
        return []
    try:
        lines = []
        with open(_SIGNAL_LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return lines[-limit:]
    except IOError:
        return []


# ═══════════════════════════════════════════════════════════════
# Telegram Channel Monitor
# ═══════════════════════════════════════════════════════════════


class TelegramSignalMonitor:
    """Monitors Telegram channels for trading signals.

    Polls configured channels via getUpdates, parses messages,
    and routes valid signals to the analysis pipeline.
    """

    def __init__(
        self,
        token: str = "",
        channel_ids: List[str] = None,
        on_signal=None,
    ):
        self.token = token or os.getenv("TELEGRAM_SIGNAL_TOKEN", os.getenv("TELEGRAM_TOKEN", ""))
        self.channel_ids = set(channel_ids or [])

        # Also load from env
        env_channels = os.getenv("TELEGRAM_SIGNAL_CHANNELS", "")
        if env_channels:
            for ch in env_channels.split(","):
                ch = ch.strip()
                if ch:
                    self.channel_ids.add(ch)

        self.on_signal = on_signal  # callback(IngestedSignal)
        self._base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self._offset = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._recent_ids = deque(maxlen=1000)  # dedup message IDs
        self._stats = {
            "messages_seen": 0,
            "signals_parsed": 0,
            "signals_failed": 0,
            "last_signal_at": 0,
        }

    @property
    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)

    def start(self):
        """Start monitoring in a background thread."""
        if not self.token:
            logger.info("[SIGNAL-INGEST] No token configured, signal monitoring disabled")
            return
        if not self.channel_ids:
            logger.info("[SIGNAL-INGEST] No channels configured, signal monitoring disabled")
            return

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(
            f"[SIGNAL-INGEST] Monitoring {len(self.channel_ids)} channels: "
            f"{', '.join(str(c) for c in self.channel_ids)}"
        )

    def stop(self):
        self._running = False

    def _poll_loop(self):
        import requests as req

        while self._running:
            try:
                resp = req.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 15},
                    timeout=20,
                )
                if resp.status_code != 200:
                    time.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._process_update(update)

            except Exception as e:
                logger.debug(f"[SIGNAL-INGEST] Poll error: {e}")
                time.sleep(5)

    def _process_update(self, update: dict):
        """Process a single Telegram update."""
        # Handle messages and channel posts
        msg = update.get("message") or update.get("channel_post") or {}
        if not msg:
            return

        msg_id = msg.get("message_id")
        if msg_id in self._recent_ids:
            return
        self._recent_ids.append(msg_id)

        chat_id = str(msg.get("chat", {}).get("id", ""))
        chat_title = msg.get("chat", {}).get("title", "")

        # Only process messages from configured channels
        if self.channel_ids and chat_id not in self.channel_ids:
            return

        text = msg.get("text") or msg.get("caption") or ""
        if not text or len(text) < 10:
            return

        self._stats["messages_seen"] += 1

        # Try to parse as a trading signal
        signal = parse_signal(text)

        if signal:
            signal.source_channel = chat_id
            signal.source_channel_name = chat_title
            self._stats["signals_parsed"] += 1
            self._stats["last_signal_at"] = time.time()

            logger.info(
                f"[SIGNAL-INGEST] Parsed signal: {signal.symbol} {signal.side} "
                f"entry={signal.entry_price} sl={signal.stop_loss} tp1={signal.take_profit_1} "
                f"quality={signal.parse_quality:.0%} from={chat_title}"
            )

            # Log to disk
            log_ingested_signal(signal)

            # Route to callback
            if self.on_signal:
                try:
                    self.on_signal(signal)
                except Exception as e:
                    logger.error(f"[SIGNAL-INGEST] Callback error: {e}")
        else:
            # Not a trading signal, that's fine
            pass

    def inject_signal(self, text: str, source: str = "manual") -> Optional[IngestedSignal]:
        """Manually inject a signal for testing/CLI use."""
        signal = parse_signal(text)
        if signal:
            signal.source_channel = source
            signal.source_channel_name = source
            log_ingested_signal(signal)
            if self.on_signal:
                self.on_signal(signal)
        return signal

    def format_status(self) -> str:
        """Format monitoring status for Telegram/console."""
        s = self._stats
        last_at = ""
        if s["last_signal_at"]:
            ago = int(time.time() - s["last_signal_at"])
            last_at = f" ({ago}s ago)"

        return (
            f"*Signal Monitor*\n"
            f"Channels: {len(self.channel_ids)}\n"
            f"Messages seen: {s['messages_seen']}\n"
            f"Signals parsed: {s['signals_parsed']}\n"
            f"Last signal: {last_at or 'never'}"
        )
