"""
Structured JSON logging for production.

Provides JSON-formatted log output for easy parsing, alerting, and dashboards.
Falls back to standard text logging in development/paper mode.

Usage:
    from core.structured_logging import setup_logging
    setup_logging(json_mode=True)  # production
    setup_logging(json_mode=False) # development (human-readable)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add structured fields from extra kwargs
        if hasattr(record, "structured"):
            log_entry["data"] = record.structured

        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Add trade-specific fields if present
        for field in ("symbol", "action", "confidence", "leverage",
                      "pnl", "side", "strategy", "trigger"):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        return json.dumps(log_entry, default=str)


class HumanFormatter(logging.Formatter):
    """Human-readable format with color for development."""

    COLORS = {
        "DEBUG": "\033[90m",     # gray
        "INFO": "\033[0m",      # default
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[41m", # red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        name = record.name.replace("bot.", "")
        msg = record.getMessage()
        return f"{color}{ts} [{record.levelname[0]}] {name}: {msg}{self.RESET}"


def setup_logging(
    json_mode: bool = False,
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "logs",
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 10,
):
    """Configure logging for the entire application.

    Args:
        json_mode: True for JSON output (production), False for human-readable
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional explicit file path; if None, auto-generates in log_dir
        log_dir: Directory for log files (created if missing)
        max_bytes: Max size per log file before rotation (default 50MB)
        backup_count: Number of rotated log files to keep
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    if json_mode:
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(HumanFormatter())
    root.addHandler(console)

    # Rotating file handler (always JSON for parsing)
    if log_file or log_dir:
        os.makedirs(log_dir, exist_ok=True)
        path = log_file or os.path.join(
            log_dir,
            f"bot_{datetime.now().strftime('%Y%m%d')}.log",
        )
        file_handler = RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count,
        )
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for name in ("urllib3", "ccxt", "requests", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def log_trade_event(
    logger: logging.Logger,
    event: str,
    symbol: str,
    **kwargs,
):
    """Log a structured trade event with consistent fields.

    Usage:
        log_trade_event(logger, "trade_opened", "BTC",
                       side="BUY", confidence=85.5, leverage=5.0)
    """
    extra = {"structured": {"event": event, "symbol": symbol, **kwargs}}
    logger.info(f"[{event}] {symbol}", extra=extra)


class TradeEventLogger:
    """Logs trade lifecycle events as structured JSON to an append-only JSONL file.

    Events: SIGNAL_GENERATED, SIGNAL_FILTERED, TRADE_OPENED, TP_HIT, SL_HIT,
            TRADE_CLOSED, POSITION_UPDATE

    Each event includes: timestamp, event, symbol, and relevant trade fields.

    Usage:
        tel = TradeEventLogger()
        tel.log("SIGNAL_GENERATED", "BTC", side="BUY", strategy="regime_trend",
                confidence=85.5, entry=65000.0, regime="trend")
        tel.log("TRADE_CLOSED", "BTC", side="BUY", entry=65000.0, exit=66000.0,
                pnl=150.0, duration_s=3600)
    """

    VALID_EVENTS = frozenset({
        "SIGNAL_GENERATED",
        "SIGNAL_FILTERED",
        "TRADE_OPENED",
        "TP_HIT",
        "SL_HIT",
        "TRADE_CLOSED",
        "POSITION_UPDATE",
    })

    def __init__(self, file_path: Optional[str] = None):
        if file_path is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            os.makedirs(data_dir, exist_ok=True)
            file_path = os.path.join(data_dir, "trade_events.jsonl")
        self._file_path = file_path
        self._logger = logging.getLogger("bot.trade_events")
        self._lock = __import__("threading").Lock()
        self._callbacks = []  # List of callables: fn(record_dict) -> None

    def add_callback(self, callback) -> None:
        """Register a callback that is invoked after every event is logged.

        The callback receives the event dict. Exceptions in callbacks
        are caught so they never affect the core logging path.
        """
        self._callbacks.append(callback)

    @property
    def file_path(self) -> str:
        return self._file_path

    def log(self, event: str, symbol: str, **kwargs) -> dict:
        """Log a trade lifecycle event.

        Args:
            event: One of VALID_EVENTS (validated but not enforced for extensibility).
            symbol: Trading pair symbol (e.g. "BTC", "SOL").
            **kwargs: Optional trade fields — side, strategy, confidence, entry, exit,
                      sl, tp1, tp2, pnl, regime, duration_s, reason, leverage, atr.

        Returns:
            The event dict that was written.
        """
        if event not in self.VALID_EVENTS:
            self._logger.warning("Unknown trade event type: %s", event)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "symbol": symbol,
        }

        # Standard optional fields
        for field in ("side", "strategy", "confidence", "entry", "exit",
                      "sl", "tp1", "tp2", "pnl", "regime", "duration_s",
                      "reason", "leverage", "atr"):
            if field in kwargs:
                record[field] = kwargs[field]

        # Any extra fields
        for k, v in kwargs.items():
            if k not in record:
                record[k] = v

        # Write to JSONL (append-only, thread-safe)
        try:
            with self._lock:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            self._logger.error("Failed to write trade event: %s", exc)

        # Also emit via standard logging
        self._logger.info(
            "[%s] %s", event, symbol,
            extra={"structured": record},
        )

        # Invoke registered callbacks (e.g. Telegram alert bridge)
        for cb in self._callbacks:
            try:
                cb(record)
            except Exception as cb_exc:
                self._logger.debug("Trade event callback error: %s", cb_exc)

        return record

    def read_events(self, limit: int = 100) -> list:
        """Read the most recent events from the JSONL file.

        Args:
            limit: Maximum number of events to return (most recent first).

        Returns:
            List of event dicts, most recent first.
        """
        events = []
        try:
            if not os.path.exists(self._file_path):
                return events
            with open(self._file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines[-limit:]):
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            self._logger.error("Failed to read trade events: %s", exc)
        return events


# Module-level singleton
_trade_event_logger: Optional["TradeEventLogger"] = None


def get_trade_event_logger(file_path: Optional[str] = None) -> TradeEventLogger:
    """Get or create the singleton TradeEventLogger instance."""
    global _trade_event_logger
    if _trade_event_logger is None:
        _trade_event_logger = TradeEventLogger(file_path=file_path)
    return _trade_event_logger


def log_metric(
    logger: logging.Logger,
    metric: str,
    value: float,
    **tags,
):
    """Log a structured metric for dashboards/alerting.

    Usage:
        log_metric(logger, "equity", 10500.0, environment="paper")
    """
    extra = {"structured": {"metric": metric, "value": value, **tags}}
    logger.info(f"[metric] {metric}={value}", extra=extra)
