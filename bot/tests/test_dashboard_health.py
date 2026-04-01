"""
Tests for the /health endpoint and TradeEventLogger.

Covers:
  1. /health endpoint — healthy (200), degraded (503), edge cases
  2. TradeEventLogger — event logging, file I/O, validation, read-back
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer
from io import BytesIO
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════
# TradeEventLogger Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTradeEventLogger:
    """Tests for the structured TradeEventLogger class."""

    def _make_logger(self, tmp_path=None):
        from core.structured_logging import TradeEventLogger
        if tmp_path is None:
            tmp_path = tempfile.mktemp(suffix=".jsonl")
        return TradeEventLogger(file_path=tmp_path)

    def test_log_signal_generated(self):
        tel = self._make_logger()
        record = tel.log(
            "SIGNAL_GENERATED", "BTC",
            side="BUY", strategy="regime_trend",
            confidence=85.5, entry=65000.0, regime="trend",
        )
        assert record["event"] == "SIGNAL_GENERATED"
        assert record["symbol"] == "BTC"
        assert record["side"] == "BUY"
        assert record["strategy"] == "regime_trend"
        assert record["confidence"] == 85.5
        assert record["entry"] == 65000.0
        assert record["regime"] == "trend"
        assert "timestamp" in record

    def test_log_trade_closed_with_pnl(self):
        tel = self._make_logger()
        record = tel.log(
            "TRADE_CLOSED", "SOL",
            side="SELL", entry=150.0, exit=145.0,
            pnl=50.0, duration_s=1800,
        )
        assert record["event"] == "TRADE_CLOSED"
        assert record["pnl"] == 50.0
        assert record["duration_s"] == 1800
        assert record["exit"] == 145.0

    def test_log_signal_filtered(self):
        tel = self._make_logger()
        record = tel.log(
            "SIGNAL_FILTERED", "ETH",
            side="BUY", strategy="monte_carlo",
            confidence=42.0, reason="circuit_breaker",
        )
        assert record["event"] == "SIGNAL_FILTERED"
        assert record["reason"] == "circuit_breaker"

    def test_log_tp_hit(self):
        tel = self._make_logger()
        record = tel.log("TP_HIT", "HYPE", side="BUY", entry=20.0, exit=22.0, pnl=100.0)
        assert record["event"] == "TP_HIT"

    def test_log_sl_hit(self):
        tel = self._make_logger()
        record = tel.log("SL_HIT", "BTC", side="SELL", entry=65000.0, exit=66000.0, pnl=-50.0)
        assert record["event"] == "SL_HIT"
        assert record["pnl"] == -50.0

    def test_log_trade_opened(self):
        tel = self._make_logger()
        record = tel.log(
            "TRADE_OPENED", "BTC",
            side="BUY", entry=65000.0, leverage=5.0,
            sl=64000.0, tp1=66000.0, tp2=67000.0,
        )
        assert record["event"] == "TRADE_OPENED"
        assert record["leverage"] == 5.0

    def test_log_position_update(self):
        tel = self._make_logger()
        record = tel.log("POSITION_UPDATE", "SOL", side="BUY", entry=150.0, pnl=10.0)
        assert record["event"] == "POSITION_UPDATE"

    def test_all_valid_events(self):
        from core.structured_logging import TradeEventLogger
        expected = {
            "SIGNAL_GENERATED", "SIGNAL_FILTERED", "TRADE_OPENED",
            "TP_HIT", "SL_HIT", "TRADE_CLOSED", "POSITION_UPDATE",
        }
        assert TradeEventLogger.VALID_EVENTS == expected

    def test_unknown_event_warns_but_works(self):
        tel = self._make_logger()
        record = tel.log("UNKNOWN_EVENT", "BTC")
        assert record["event"] == "UNKNOWN_EVENT"
        assert record["symbol"] == "BTC"

    def test_file_append_only(self):
        path = tempfile.mktemp(suffix=".jsonl")
        tel = self._make_logger(path)
        tel.log("SIGNAL_GENERATED", "BTC", side="BUY")
        tel.log("TRADE_OPENED", "BTC", side="BUY")
        tel.log("TRADE_CLOSED", "BTC", side="BUY", pnl=100.0)

        with open(path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 3
        events = [json.loads(line)["event"] for line in lines]
        assert events == ["SIGNAL_GENERATED", "TRADE_OPENED", "TRADE_CLOSED"]

    def test_read_events_returns_most_recent_first(self):
        path = tempfile.mktemp(suffix=".jsonl")
        tel = self._make_logger(path)
        tel.log("SIGNAL_GENERATED", "BTC")
        tel.log("TRADE_OPENED", "SOL")
        tel.log("TRADE_CLOSED", "ETH")

        events = tel.read_events(limit=10)
        assert len(events) == 3
        assert events[0]["event"] == "TRADE_CLOSED"
        assert events[0]["symbol"] == "ETH"
        assert events[2]["event"] == "SIGNAL_GENERATED"

    def test_read_events_with_limit(self):
        path = tempfile.mktemp(suffix=".jsonl")
        tel = self._make_logger(path)
        for i in range(10):
            tel.log("SIGNAL_GENERATED", f"SYM{i}")

        events = tel.read_events(limit=3)
        assert len(events) == 3
        assert events[0]["symbol"] == "SYM9"

    def test_read_events_empty_file(self):
        path = tempfile.mktemp(suffix=".jsonl")
        tel = self._make_logger(path)
        events = tel.read_events()
        assert events == []

    def test_read_events_missing_file(self):
        tel = self._make_logger("/nonexistent/path/events.jsonl")
        events = tel.read_events()
        assert events == []

    def test_extra_kwargs_included(self):
        tel = self._make_logger()
        record = tel.log("TRADE_OPENED", "BTC", custom_field="hello", score=99)
        assert record["custom_field"] == "hello"
        assert record["score"] == 99

    def test_timestamp_is_utc_iso(self):
        tel = self._make_logger()
        record = tel.log("SIGNAL_GENERATED", "BTC")
        ts = record["timestamp"]
        # Should parse as ISO format with UTC timezone
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_file_path_property(self):
        path = "/tmp/test_events.jsonl"
        tel = self._make_logger(path)
        assert tel.file_path == path

    def test_singleton_getter(self):
        import core.structured_logging as sl
        # Reset singleton
        sl._trade_event_logger = None
        logger1 = sl.get_trade_event_logger()
        logger2 = sl.get_trade_event_logger()
        assert logger1 is logger2
        # Cleanup
        sl._trade_event_logger = None

    def test_thread_safety(self):
        """Multiple threads writing concurrently should not corrupt the file."""
        path = tempfile.mktemp(suffix=".jsonl")
        tel = self._make_logger(path)
        errors = []

        def write_events(thread_id):
            try:
                for i in range(20):
                    tel.log("SIGNAL_GENERATED", f"T{thread_id}_S{i}")
            except Exception as e:
                errors.append(e)

        threads = [Thread(target=write_events, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        with open(path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 100  # 5 threads x 20 events
        for line in lines:
            parsed = json.loads(line.strip())
            assert "event" in parsed
            assert "symbol" in parsed

    def test_write_failure_does_not_raise(self):
        """If file write fails, log error but don't crash."""
        tel = self._make_logger()
        # Patch open to raise
        with patch("builtins.open", side_effect=PermissionError("denied")):
            # Should not raise
            record = tel.log("SIGNAL_GENERATED", "BTC")
            assert record["event"] == "SIGNAL_GENERATED"


# ═══════════════════════════════════════════════════════════════════════
# Health Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """Tests for the /health production health check endpoint."""

    def _make_handler(self, bot_instance=None, env_overrides=None):
        """Create a DashboardHandler with mocked request/response."""
        from dashboard.server import DashboardHandler

        DashboardHandler.bot_instance = bot_instance

        handler = DashboardHandler.__new__(DashboardHandler)
        handler.path = "/health"
        handler.headers = {}
        handler.server = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.requestline = "GET /health HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.command = "GET"

        # Capture response
        handler._response_code = None
        handler._response_body = None
        handler._headers = {}

        def mock_send_response(code):
            handler._response_code = code

        def mock_send_header(key, value):
            handler._headers[key] = value

        def mock_end_headers():
            pass

        handler.wfile = BytesIO()
        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers

        return handler

    def _call_health(self, handler):
        """Call _serve_health_check and parse the JSON response."""
        handler._serve_health_check()
        body = handler.wfile.getvalue().decode("utf-8")
        return handler._response_code, json.loads(body)

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_basic_structure(self):
        """Health response has required fields."""
        handler = self._make_handler()
        code, data = self._call_health(handler)

        assert "status" in data
        assert "version" in data
        assert "environment" in data
        assert "uptime_seconds" in data
        assert "started_at" in data
        assert "active_positions" in data
        assert "open_pnl" in data
        assert "daily_pnl" in data
        assert "error_count_1h" in data
        assert "exchange_connected" in data
        assert "llm_api_ok" in data

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_no_bot_returns_200(self):
        """Without a bot instance, should still return 200 (no heartbeats to check)."""
        handler = self._make_handler(bot_instance=None)
        code, data = self._call_health(handler)
        assert code == 200
        assert data["status"] == "healthy"
        assert data["active_positions"] == 0
        assert data["open_pnl"] == 0

    @patch.dict(os.environ, {"ENVIRONMENT": "production", "LLM_MODE": "3", "ANTHROPIC_API_KEY": "sk-ant-test123456789"})
    def test_health_shows_environment(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["environment"] == "production"

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "3", "ANTHROPIC_API_KEY": "sk-ant-test123456789"})
    def test_health_llm_ok_when_key_present(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["llm_api_ok"] is True

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_llm_none_when_disabled(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["llm_api_ok"] is None

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "3", "ANTHROPIC_API_KEY": ""})
    def test_health_llm_false_when_no_key(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["llm_api_ok"] is False

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_exchange_connected_with_bot(self):
        bot = MagicMock()
        bot.exchange = MagicMock()
        handler = self._make_handler(bot_instance=bot)
        code, data = self._call_health(handler)
        assert data["exchange_connected"] is True

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_exchange_unknown_without_bot(self):
        handler = self._make_handler(bot_instance=None)
        code, data = self._call_health(handler)
        assert data["exchange_connected"] is None

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_positions_counted(self):
        bot = MagicMock()
        bot.open_positions = [
            {"symbol": "BTC", "side": "LONG", "unrealized_pnl": 100.0,
             "entry_price": 65000, "current_price": 65100, "leverage": 5},
            {"symbol": "SOL", "side": "SHORT", "unrealized_pnl": -20.0,
             "entry_price": 150, "current_price": 152, "leverage": 3},
        ]
        handler = self._make_handler(bot_instance=bot)
        code, data = self._call_health(handler)
        assert data["active_positions"] == 2
        assert data["open_pnl"] == 80.0

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_uptime_positive(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["uptime_seconds"] > 0
        assert data["started_at"] is not None

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_degraded_high_error_rate(self):
        """More than 10 errors in 1 hour should return 503."""
        mock_events = [{"severity": "ERROR", "event_type": "ERROR"} for _ in range(15)]

        handler = self._make_handler()
        with patch("data.db.get_health_events", return_value=mock_events):
            code, data = self._call_health(handler)

        assert code == 503
        assert data["status"] == "degraded"
        assert data["error_count_1h"] == 15
        assert any("high_error_rate" in r for r in data["degraded_reasons"])

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_degraded_stale_data(self):
        """Tick older than 5 minutes should cause degradation."""
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        mock_events = [{"event_type": "HEARTBEAT", "timestamp": old_time, "severity": "INFO"}]

        handler = self._make_handler(bot_instance=MagicMock())
        with patch("data.db.get_health_events", return_value=mock_events):
            code, data = self._call_health(handler)

        assert code == 503
        assert data["status"] == "degraded"
        assert any("stale_data" in r for r in data["degraded_reasons"])

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_healthy_recent_heartbeat(self):
        """Recent heartbeat within thresholds should be healthy."""
        recent_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        mock_events = [{"event_type": "HEARTBEAT", "timestamp": recent_time, "severity": "INFO"}]

        handler = self._make_handler()
        with patch("data.db.get_health_events", return_value=mock_events):
            code, data = self._call_health(handler)

        assert code == 200
        assert data["status"] == "healthy"
        assert data["tick_age_seconds"] is not None
        assert data["tick_age_seconds"] < 60

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_no_degraded_reasons_when_healthy(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert data["status"] == "healthy"
        assert data["degraded_reasons"] is None

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_version_present(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        assert "version" in data
        assert isinstance(data["version"], str)

    @patch.dict(os.environ, {"ENVIRONMENT": "paper", "LLM_MODE": "0"})
    def test_health_memory_field_present(self):
        handler = self._make_handler()
        code, data = self._call_health(handler)
        # memory_mb can be None if psutil not installed, but key must exist
        assert "memory_mb" in data


# ═══════════════════════════════════════════════════════════════════════
# Route Registration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHealthRouteRegistration:
    """Verify /health route is registered in the handler."""

    def test_health_route_in_routes(self):
        from dashboard.server import DashboardHandler

        handler = DashboardHandler.__new__(DashboardHandler)
        handler.path = "/health"
        handler.headers = {}

        # Just check the handler method exists
        assert hasattr(handler, "_serve_health_check")

    def test_api_health_route_still_exists(self):
        """Ensure the original /api/health endpoint wasn't broken."""
        from dashboard.server import DashboardHandler
        handler = DashboardHandler.__new__(DashboardHandler)
        assert hasattr(handler, "_serve_health")


# ═══════════════════════════════════════════════════════════════════════
# Integration: Existing log_trade_event function still works
# ═══════════════════════════════════════════════════════════════════════


class TestExistingLogFunctions:
    """Ensure existing structured logging functions still work."""

    def test_log_trade_event_works(self):
        from core.structured_logging import log_trade_event
        logger = MagicMock()
        log_trade_event(logger, "trade_opened", "BTC", side="BUY", confidence=85.5)
        logger.info.assert_called_once()

    def test_log_metric_works(self):
        from core.structured_logging import log_metric
        logger = MagicMock()
        log_metric(logger, "equity", 10500.0, environment="paper")
        logger.info.assert_called_once()

    def test_json_formatter_unchanged(self):
        from core.structured_logging import JSONFormatter
        formatter = JSONFormatter()
        import logging
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["msg"] == "test message"
        assert parsed["level"] == "INFO"

    def test_setup_logging_import(self):
        from core.structured_logging import setup_logging
        assert callable(setup_logging)
