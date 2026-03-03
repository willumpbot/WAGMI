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
import sys
import time
from datetime import datetime, timezone
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
):
    """Configure logging for the entire application.

    Args:
        json_mode: True for JSON output (production), False for human-readable
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path to also write logs to
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

    # File handler (always JSON for parsing)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a")
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
