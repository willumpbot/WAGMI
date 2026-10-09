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
import re
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
    # WAGMI_LOG_DIR overrides the default log dir (set by tests/conftest.py so
    # an import-time setup_logging(log_dir="logs") in a pytest process never
    # attaches a handler to the LIVE bot's logs/). Unset in production ->
    # behaviour unchanged.
    _env_log_dir = os.environ.get("WAGMI_LOG_DIR")
    if _env_log_dir and not log_file:
        log_dir = _env_log_dir

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


# FAKE-EVENT FILTER (2026-07-20, widened 2026-07-20b): trade_events.jsonl
# accumulates rows from pytest runs (MagicMock symbols, strategy="test"/
# "test_strat", symbol="TEST"), from dormant/never-shipped-live symbols
# (POPCAT/GOAT — failed backtest, never enabled live; see project memory
# 2026-07-14 expansion note), and from in-process test/backtest harnesses
# that call PositionManager.open_position() (or similar) directly, bypassing
# the ensemble pipeline entirely.
#
# Ground-truth audit (2026-07-20, re-verified 2026-07-20c against the live
# file + trade_ledger.csv): the fabricated mass is a repeating synthetic
# fixture with SENTINEL round entry prices (50000.0 / 100.0 / 3000.0 / 150.0 /
# 95000.0), sub-second hold_time, confidence=0.0 — appended to the LIVE file
# by an in-process harness on every run from 2026-06-25 through the present.
#
# CRITICAL empirical constraint (2026-07-20c, this is why the earlier
# strategy-ALLOWLIST draft of this filter was WRONG and had to be reverted):
# the REAL live bot's own TRADE_OPENED / SL_HIT / TP_HIT / TRADE_CLOSED
# events ALSO carry strategy="" on the current LLM-first path —
# position_manager's terminal-close tel.log() doesn't pass `strategy` at
# all, and open_position() logs whatever pos.strategy is, which is blank
# for LLM-first entries (verified July 18-20 events with blank strategy
# match trade_ledger.csv closes row-for-row: HYPE SL -1.77, XRP SL +1.49,
# BTC SL -0.03, ...). The ledger also shows real multi-tags like
# "confidence_scorer,bollinger_squeeze". So a blank or unrecognized
# strategy tag must NEVER by itself mark a row fake — an allowlist here
# silently zeroes out ALL current real trading from every consumer.
#
# What actually separates the fixture (4806/4809 blank-strategy close rows
# in the live file, 99.9%) is the sentinel entry price. The 3 remaining
# round-entry rows (e.g. BTC @ 61724.0) are plausibly real and are kept.
#
# Any reporting/learning consumer of trade_events.jsonl MUST exclude these or
# non-live PnL gets mixed into real performance numbers. Centralized here so
# every consumer (dashboard, tools/*, alerts/telegram_alert_bridge, learning
# loops, etc.) applies the identical rule — see MEMORY: trade_events.jsonl
# fabricated-row ticket, all_sites list, 2026-07-20.
_FAKE_STRATEGY_MARKERS = ("test", "mock", "fake")  # substring match, lowercased
_FAKE_EXACT_SYMBOLS = frozenset({"TEST", "POPCAT", "GOAT"})
_FAKE_SYNTHETIC_SYMBOL_RE = re.compile(r"^X(LONG|SHORT)[PN]$")  # e.g. XLONGP/XSHORTN test fixtures
_FAKE_EXIT_REASONS = frozenset({"BACKTEST_END", "TEST", "TEST_FINAL"})
# Same sentinel-price family as data/trade_log.py._TEST_ENTRY_SENTINELS and
# strategies/ensemble.py._scrub_ledger_df — synthetic fixture entries only,
# never real fills (real fills carry exchange-precision decimals).
_FAKE_ENTRY_SENTINELS = frozenset({100.0, 150.0, 3000.0, 50000.0, 95000.0})


def is_fake_trade_event(evt: dict) -> bool:
    """True if `evt` is test/mock/non-live contamination that must never be
    counted in live reporting or learning aggregates.

    A record is fake iff ANY of:
      - its `symbol` is a known test/dormant-symbol marker (TEST/POPCAT/GOAT,
        MagicMock reprs, XLONGP-style synthetic fixtures)
      - its `strategy` tag contains a test/mock marker substring
        (blank strategy is REAL — the live LLM-first path logs blank; see
        module comment)
      - its `exit_reason` is a test/backtest marker
      - its entry price is one of the known synthetic fixture sentinels
    """
    symbol = str(evt.get("symbol", ""))
    strategy = str(evt.get("strategy", "")).lower()
    exit_reason = str(evt.get("exit_reason", ""))

    if symbol in _FAKE_EXACT_SYMBOLS or "MagicMock" in symbol:
        return True
    if _FAKE_SYNTHETIC_SYMBOL_RE.match(symbol):
        return True
    if any(m in strategy for m in _FAKE_STRATEGY_MARKERS):
        return True
    if exit_reason in _FAKE_EXIT_REASONS:
        return True
    try:
        entry = float(evt.get("entry_price", evt.get("entry", 0)) or 0)
    except (TypeError, ValueError):
        entry = 0.0
    if entry in _FAKE_ENTRY_SENTINELS:
        return True
    return False


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

    # DASHBOARD-CLOSE-COVERAGE-FIX (2026-07-20): position_manager.py logs a
    # position's terminal close as exactly ONE of these three event names
    # depending on exit reason (SL_HIT for stop/trailing-stop exits, TP_HIT
    # for take-profit exits, TRADE_CLOSED for everything else — see
    # execution/position_manager.py _close_position()). Any consumer that
    # aggregates "closed trades" (win rate, PnL, strategy/symbol breakdowns)
    # MUST treat all three as closes or it silently drops ~84% of them
    # (only TRADE_CLOSED was being counted — audited 2026-07-20).
    CLOSE_EVENT_TYPES = frozenset({"TRADE_CLOSED", "SL_HIT", "TP_HIT"})

    # A TP_HIT carrying "remaining_qty" is the TP1 *partial* leg (position
    # manager's partial-close path — see _close_position()'s sibling that
    # logs TP1 fills). The position is still open afterwards, so it must
    # count toward realized PnL but NOT as a second completed "trade" —
    # otherwise trade counts/win-rate denominators double-count every
    # position that took partial profit before its final close.
    @staticmethod
    def is_partial_close_leg(evt: dict) -> bool:
        """True if `evt` is a non-terminal partial-close leg (e.g. TP1 partial)."""
        return evt.get("event") == "TP_HIT" and "remaining_qty" in evt

    def __init__(self, file_path: Optional[str] = None):
        # TEST_WRITE_GUARD (2026-07-20): remember whether the caller took the
        # default (production) path vs. an explicit override. Every current
        # caller of the module-level singleton (get_trade_event_logger(),
        # used by execution/position_manager.py, strategies/ensemble.py,
        # core/signal_pipeline.py, multi_strategy_main.py) passes no
        # file_path and lands here -- so this flag is the single choke point
        # that distinguishes "real production logger" from "test-supplied
        # tmp-file logger" for every one of those call sites at once.
        self._is_default_path = file_path is None
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

        # TEST_WRITE_GUARD (2026-07-20): pytest runs that obtain the default
        # (production-path) logger -- directly or transitively through
        # position_manager/ensemble/signal_pipeline/multi_strategy_main --
        # must never write into the real bot/data/trade_events.jsonl. This
        # mirrors the sibling guards already in execution/position_manager.py
        # (_backup_position at the default backup dir, and the exit_closes.jsonl
        # append before EXIT-REGRET stamping). Tests that pass an explicit
        # file_path (tmp_path / tempfile.mktemp(), as every existing
        # TradeEventLogger test does) are unaffected and still exercise the
        # real write + read-back path.
        _skip_write = bool(os.getenv("PYTEST_CURRENT_TEST")) and self._is_default_path

        # Write to JSONL (append-only, thread-safe)
        if not _skip_write:
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
