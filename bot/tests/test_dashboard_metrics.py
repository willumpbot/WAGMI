"""
Tests for /api/metrics and /api/signals/recent dashboard endpoints.

Covers:
  1. Metrics computation from trade_events.jsonl
  2. /api/metrics endpoint — caching, data accuracy, edge cases
  3. /api/signals/recent endpoint — signal listing with status
  4. Cache clearing
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _write_events(path: str, events: list):
    """Write a list of event dicts as JSONL to path."""
    with open(path, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, default=str) + "\n")


def _make_handler(bot_instance=None):
    """Create a DashboardHandler with mocked request/response."""
    from dashboard.server import DashboardHandler

    DashboardHandler.bot_instance = bot_instance

    handler = DashboardHandler.__new__(DashboardHandler)
    handler.path = "/api/metrics"
    handler.headers = {}
    handler.server = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.requestline = "GET /api/metrics HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"

    handler._response_code = None
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


def _call_endpoint(handler, method_name):
    """Call an endpoint method and parse the JSON response."""
    getattr(handler, method_name)()
    body = handler.wfile.getvalue().decode("utf-8")
    return handler._response_code, json.loads(body)


def _ts(hours_ago=0, minutes_ago=0):
    """Generate an ISO timestamp for a given time in the past."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=minutes_ago)
    return dt.isoformat()


class TestMetricsComputation:
    """Tests for the _compute_metrics function."""

    def setup_method(self):
        from dashboard.server import clear_metrics_cache
        clear_metrics_cache()

    def test_empty_events_returns_zeroes(self):
        """No events file should return all-zero metrics."""
        from dashboard.server import _compute_metrics, DashboardHandler
        DashboardHandler.bot_instance = None

        with patch("dashboard.server._read_trade_events", return_value=[]):
            result = _compute_metrics(None)

        assert result["signals_1h"] == 0
        assert result["signals_24h"] == 0
        assert result["trades_opened_1h"] == 0
        assert result["trades_opened_24h"] == 0
        assert result["conversion_rate_1h"] == 0.0
        assert result["conversion_rate_24h"] == 0.0
        assert result["win_rate_24h"] == 0.0
        assert result["total_pnl_24h"] == 0.0
        assert result["avg_position_size"] == 0.0
        assert result["active_positions"] == 0
        assert result["current_drawdown_pct"] == 0.0
        assert result["rejection_breakdown"] == {}
        assert result["strategy_performance"] == {}
        assert result["top_symbols"] == {}

    def test_signals_counted_correctly(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=30)},
            {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(minutes_ago=45)},
            {"event": "SIGNAL_GENERATED", "symbol": "ETH", "timestamp": _ts(hours_ago=2)},
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(hours_ago=5)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["signals_1h"] == 2
        assert result["signals_24h"] == 4

    def test_trades_opened_counted(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_OPENED", "symbol": "BTC", "timestamp": _ts(minutes_ago=20),
             "entry": 65000.0, "leverage": 5},
            {"event": "TRADE_OPENED", "symbol": "SOL", "timestamp": _ts(hours_ago=3),
             "entry": 150.0, "leverage": 10},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["trades_opened_1h"] == 1
        assert result["trades_opened_24h"] == 2

    def test_avg_position_size(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_OPENED", "symbol": "BTC", "timestamp": _ts(minutes_ago=20),
             "entry": 100.0, "leverage": 5},  # 500
            {"event": "TRADE_OPENED", "symbol": "SOL", "timestamp": _ts(hours_ago=3),
             "entry": 200.0, "leverage": 10},  # 2000
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["avg_position_size"] == 1250.0  # (500 + 2000) / 2

    def test_win_rate_and_pnl(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": 50.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "SOL", "timestamp": _ts(hours_ago=2),
             "pnl": -20.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "ETH", "timestamp": _ts(hours_ago=3),
             "pnl": 30.0, "strategy": "sniper"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["win_rate_24h"] == 0.67  # 2/3
        assert result["total_pnl_24h"] == 60.0  # 50 - 20 + 30

    def test_conversion_rate(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
            {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(minutes_ago=20)},
            {"event": "SIGNAL_GENERATED", "symbol": "ETH", "timestamp": _ts(minutes_ago=30)},
            {"event": "SIGNAL_GENERATED", "symbol": "XRP", "timestamp": _ts(minutes_ago=40)},
            {"event": "TRADE_OPENED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10),
             "entry": 65000, "leverage": 5},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["signals_1h"] == 4
        assert result["trades_opened_1h"] == 1
        assert result["conversion_rate_1h"] == 0.25

    def test_strategy_performance_breakdown(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": 50.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "SOL", "timestamp": _ts(hours_ago=2),
             "pnl": -20.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "ETH", "timestamp": _ts(hours_ago=3),
             "pnl": 30.0, "strategy": "sniper"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        sp = result["strategy_performance"]
        assert "ensemble" in sp
        assert sp["ensemble"]["trades"] == 2
        assert sp["ensemble"]["win_rate"] == 0.5
        assert sp["ensemble"]["pnl"] == 30.0
        assert "sniper" in sp
        assert sp["sniper"]["trades"] == 1
        assert sp["sniper"]["win_rate"] == 1.0
        assert sp["sniper"]["pnl"] == 30.0

    def test_top_symbols_breakdown(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": 50.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=2),
             "pnl": -10.0, "strategy": "ensemble"},
            {"event": "TRADE_CLOSED", "symbol": "SOL", "timestamp": _ts(hours_ago=3),
             "pnl": -5.0, "strategy": "sniper"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        ts = result["top_symbols"]
        assert "BTC" in ts
        assert ts["BTC"]["trades"] == 2
        assert ts["BTC"]["win_rate"] == 0.5
        assert ts["BTC"]["pnl"] == 40.0
        assert "SOL" in ts
        assert ts["SOL"]["trades"] == 1
        assert ts["SOL"]["pnl"] == -5.0

    def test_rejection_breakdown_from_filtered_events(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "SIGNAL_FILTERED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "reason": "ev_floor"},
            {"event": "SIGNAL_FILTERED", "symbol": "SOL", "timestamp": _ts(hours_ago=2),
             "reason": "ev_floor"},
            {"event": "SIGNAL_FILTERED", "symbol": "ETH", "timestamp": _ts(hours_ago=3),
             "reason": "circuit_breaker"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        rb = result["rejection_breakdown"]
        assert rb.get("ev_floor") == 2
        assert rb.get("circuit_breaker") == 1

    def test_cache_returns_same_result(self):
        """Metrics should be cached for 30 seconds."""
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events1 = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
        ]
        events2 = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
            {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(minutes_ago=20)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events1):
            result1 = _compute_metrics(None)

        # Second call with different data should return cached result
        with patch("dashboard.server._read_trade_events", return_value=events2):
            result2 = _compute_metrics(None)

        assert result1["signals_1h"] == result2["signals_1h"] == 1

    def test_cache_cleared(self):
        """clear_metrics_cache should allow fresh computation."""
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events1 = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
        ]
        events2 = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
            {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(minutes_ago=20)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events1):
            result1 = _compute_metrics(None)
        assert result1["signals_1h"] == 1

        clear_metrics_cache()

        with patch("dashboard.server._read_trade_events", return_value=events2):
            result2 = _compute_metrics(None)
        assert result2["signals_1h"] == 2

    def test_invalid_pnl_treated_as_zero(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": "invalid", "strategy": "ensemble"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["total_pnl_24h"] == 0.0
        assert result["win_rate_24h"] == 0.0

    def test_invalid_timestamp_skipped(self):
        from dashboard.server import _compute_metrics, DashboardHandler, clear_metrics_cache
        DashboardHandler.bot_instance = None
        clear_metrics_cache()

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": "not-a-date"},
            {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(minutes_ago=10)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        assert result["signals_1h"] == 1  # only the valid one


class TestReadTradeEvents:
    """Tests for _read_trade_events file reading."""

    def test_reads_events_within_window(self):
        from dashboard.server import _read_trade_events

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
            events = [
                {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=30)},
                {"event": "SIGNAL_GENERATED", "symbol": "SOL", "timestamp": _ts(hours_ago=25)},
            ]
            for evt in events:
                f.write(json.dumps(evt) + "\n")

        try:
            with patch("dashboard.server._BOT_DIR", os.path.dirname(path)):
                with patch("dashboard.server.os.path.join", return_value=path):
                    result = _read_trade_events(hours=24.0)
            assert len(result) == 1
            assert result[0]["symbol"] == "BTC"
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self):
        from dashboard.server import _read_trade_events

        with patch("dashboard.server.os.path.exists", return_value=False):
            result = _read_trade_events(hours=24.0)
        assert result == []

    def test_malformed_json_skipped(self):
        from dashboard.server import _read_trade_events

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
            f.write("not json\n")
            f.write(json.dumps({"event": "SIGNAL_GENERATED", "symbol": "BTC",
                                "timestamp": _ts(minutes_ago=10)}) + "\n")
            f.write("{malformed\n")

        try:
            with patch("dashboard.server._BOT_DIR", os.path.dirname(path)):
                with patch("dashboard.server.os.path.join", return_value=path):
                    result = _read_trade_events(hours=24.0)
            assert len(result) == 1
        finally:
            os.unlink(path)


class TestRecentSignals:
    """Tests for the _get_recent_signals function."""

    def test_empty_returns_empty(self):
        from dashboard.server import _get_recent_signals

        with patch("dashboard.server._read_trade_events", return_value=[]):
            result = _get_recent_signals()
        assert result == []

    def test_approved_and_rejected_signals(self):
        from dashboard.server import _get_recent_signals

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "side": "BUY",
             "strategy": "ensemble", "confidence": 85, "entry": 65000,
             "timestamp": _ts(minutes_ago=30)},
            {"event": "SIGNAL_FILTERED", "symbol": "SOL", "side": "SELL",
             "strategy": "sniper", "confidence": 40, "entry": 150,
             "reason": "ev_floor", "timestamp": _ts(minutes_ago=20)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _get_recent_signals()

        assert len(result) == 2
        assert result[0]["status"] == "approved"
        assert result[0]["symbol"] == "BTC"
        assert result[0]["reason"] is None
        assert result[1]["status"] == "rejected"
        assert result[1]["reason"] == "ev_floor"

    def test_limit_respected(self):
        from dashboard.server import _get_recent_signals

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": f"SYM{i}",
             "timestamp": _ts(minutes_ago=i)} for i in range(100)
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _get_recent_signals(limit=10)

        assert len(result) == 10

    def test_signal_fields_present(self):
        from dashboard.server import _get_recent_signals

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "side": "BUY",
             "strategy": "ensemble", "confidence": 90, "entry": 65000,
             "sl": 64000, "tp1": 66000, "regime": "trend",
             "timestamp": _ts(minutes_ago=5)},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _get_recent_signals()

        sig = result[0]
        assert sig["symbol"] == "BTC"
        assert sig["side"] == "BUY"
        assert sig["strategy"] == "ensemble"
        assert sig["confidence"] == 90
        assert sig["entry"] == 65000
        assert sig["sl"] == 64000
        assert sig["tp1"] == 66000
        assert sig["regime"] == "trend"
        assert sig["status"] == "approved"


class TestMetricsEndpoint:
    """Tests for /api/metrics HTTP endpoint."""

    def setup_method(self):
        from dashboard.server import clear_metrics_cache
        clear_metrics_cache()

    def test_metrics_endpoint_returns_200(self):
        handler = _make_handler()

        with patch("dashboard.server._read_trade_events", return_value=[]):
            code, data = _call_endpoint(handler, "_serve_metrics")

        assert code == 200
        assert "signals_1h" in data
        assert "signals_24h" in data
        assert "win_rate_24h" in data
        assert "total_pnl_24h" in data
        assert "rejection_breakdown" in data
        assert "strategy_performance" in data
        assert "top_symbols" in data

    def test_metrics_endpoint_with_data(self):
        from dashboard.server import clear_metrics_cache
        clear_metrics_cache()

        handler = _make_handler()
        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
            {"event": "TRADE_OPENED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10),
             "entry": 65000, "leverage": 5},
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": 100.0, "strategy": "ensemble"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            code, data = _call_endpoint(handler, "_serve_metrics")

        assert code == 200
        assert data["signals_1h"] == 1
        assert data["trades_opened_1h"] == 1
        assert data["total_pnl_24h"] == 100.0
        assert data["win_rate_24h"] == 1.0

    def test_metrics_endpoint_error_returns_500(self):
        handler = _make_handler()

        with patch("dashboard.server._compute_metrics", side_effect=RuntimeError("boom")):
            code, data = _call_endpoint(handler, "_serve_metrics")

        assert code == 500
        assert "error" in data


class TestSignalsRecentEndpoint:
    """Tests for /api/signals/recent HTTP endpoint."""

    def test_signals_recent_returns_200(self):
        handler = _make_handler()
        handler.path = "/api/signals/recent"

        with patch("dashboard.server._get_recent_signals", return_value=[]):
            code, data = _call_endpoint(handler, "_serve_signals_recent")

        assert code == 200
        assert isinstance(data, list)

    def test_signals_recent_with_data(self):
        handler = _make_handler()
        handler.path = "/api/signals/recent"

        mock_signals = [
            {"symbol": "BTC", "side": "BUY", "status": "approved", "confidence": 85},
            {"symbol": "SOL", "side": "SELL", "status": "rejected", "reason": "ev_floor"},
        ]

        with patch("dashboard.server._get_recent_signals", return_value=mock_signals):
            code, data = _call_endpoint(handler, "_serve_signals_recent")

        assert code == 200
        assert len(data) == 2
        assert data[0]["symbol"] == "BTC"
        assert data[1]["status"] == "rejected"

    def test_signals_recent_error_returns_500(self):
        handler = _make_handler()
        handler.path = "/api/signals/recent"

        with patch("dashboard.server._get_recent_signals", side_effect=RuntimeError("boom")):
            code, data = _call_endpoint(handler, "_serve_signals_recent")

        assert code == 500
        assert "error" in data


class TestRouteRegistration:
    """Verify new routes are registered in the handler."""

    def test_metrics_route_exists(self):
        from dashboard.server import DashboardHandler
        handler = DashboardHandler.__new__(DashboardHandler)
        assert hasattr(handler, "_serve_metrics")

    def test_signals_recent_route_exists(self):
        from dashboard.server import DashboardHandler
        handler = DashboardHandler.__new__(DashboardHandler)
        assert hasattr(handler, "_serve_signals_recent")

    def test_clear_metrics_cache_importable(self):
        from dashboard.server import clear_metrics_cache
        assert callable(clear_metrics_cache)


class TestMetricsAllFieldTypes:
    """Ensure all required JSON fields are present and correctly typed."""

    def setup_method(self):
        from dashboard.server import clear_metrics_cache
        clear_metrics_cache()

    def test_all_fields_present_and_typed(self):
        from dashboard.server import _compute_metrics, DashboardHandler
        DashboardHandler.bot_instance = None

        events = [
            {"event": "SIGNAL_GENERATED", "symbol": "BTC", "timestamp": _ts(minutes_ago=10)},
            {"event": "TRADE_OPENED", "symbol": "BTC", "timestamp": _ts(minutes_ago=9),
             "entry": 65000, "leverage": 5},
            {"event": "TRADE_CLOSED", "symbol": "BTC", "timestamp": _ts(hours_ago=1),
             "pnl": 50.0, "strategy": "ensemble"},
            {"event": "SIGNAL_FILTERED", "symbol": "SOL", "timestamp": _ts(hours_ago=2),
             "reason": "ev_floor"},
        ]

        with patch("dashboard.server._read_trade_events", return_value=events):
            result = _compute_metrics(None)

        # Check all top-level fields exist
        expected_fields = {
            "signals_1h", "signals_24h", "trades_opened_1h", "trades_opened_24h",
            "conversion_rate_1h", "conversion_rate_24h", "win_rate_24h",
            "total_pnl_24h", "avg_position_size", "active_positions",
            "current_drawdown_pct", "rejection_breakdown",
            "strategy_performance", "top_symbols",
        }
        assert set(result.keys()) == expected_fields

        # Check types
        assert isinstance(result["signals_1h"], int)
        assert isinstance(result["signals_24h"], int)
        assert isinstance(result["trades_opened_1h"], int)
        assert isinstance(result["trades_opened_24h"], int)
        assert isinstance(result["conversion_rate_1h"], float)
        assert isinstance(result["conversion_rate_24h"], float)
        assert isinstance(result["win_rate_24h"], float)
        assert isinstance(result["total_pnl_24h"], float)
        assert isinstance(result["avg_position_size"], float)
        assert isinstance(result["active_positions"], int)
        assert isinstance(result["current_drawdown_pct"], float)
        assert isinstance(result["rejection_breakdown"], dict)
        assert isinstance(result["strategy_performance"], dict)
        assert isinstance(result["top_symbols"], dict)
