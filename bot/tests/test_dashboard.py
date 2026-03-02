"""
Tests for the built-in web dashboard:
  - DashboardHandler serves HTML at GET /
  - DashboardHandler serves JSON at GET /api/data
"""

import io
import json
import os
import sys
from http.server import HTTPServer
from unittest.mock import MagicMock, patch

import pytest

# Ensure bot/ is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.server import DashboardHandler


class _FakeSocket:
    """Minimal socket-like object for constructing a handler in tests."""

    def __init__(self):
        self.data = b""

    def makefile(self, mode, buffering=-1):
        if "r" in mode:
            return io.BytesIO(b"")
        return io.BytesIO()

    def sendall(self, data):
        self.data += data


class _MockWfile(io.BytesIO):
    """Writable buffer that captures the response body."""
    pass


def _make_handler(path: str) -> DashboardHandler:
    """Construct a DashboardHandler for a given request path.

    We bypass the normal socket-based construction and directly set
    the attributes that do_GET relies on, then invoke the method.
    """
    # Build a minimal raw HTTP request line
    request_line = f"GET {path} HTTP/1.1\r\n"
    headers = "Host: localhost\r\n\r\n"
    raw_request = (request_line + headers).encode("utf-8")

    # Create a handler with a mock socket
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.rfile = io.BytesIO(raw_request)
    handler.wfile = _MockWfile()
    handler.client_address = ("127.0.0.1", 12345)
    handler.server = MagicMock()
    handler.requestline = request_line.strip()
    handler.command = "GET"
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.headers = {}
    handler.close_connection = True
    # Disable logging noise during tests
    handler.log_message = lambda fmt, *args: None

    return handler


class TestDashboard:

    def test_dashboard_serves_html(self):
        """GET / returns the dashboard HTML page with status 200."""
        handler = _make_handler("/")

        # Capture what send_response / send_header / end_headers write
        response_parts = []
        original_wfile = handler.wfile

        def mock_send_response(code, message=None):
            response_parts.append(("status", code))

        def mock_send_header(key, value):
            response_parts.append(("header", key, value))

        def mock_end_headers():
            response_parts.append(("end_headers",))

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers

        handler.do_GET()

        # Verify status 200
        status_codes = [p[1] for p in response_parts if p[0] == "status"]
        assert 200 in status_codes, f"Expected 200, got status entries: {status_codes}"

        # Verify Content-Type is HTML
        content_types = [
            p[2] for p in response_parts
            if p[0] == "header" and p[1] == "Content-Type"
        ]
        assert any("text/html" in ct for ct in content_types), (
            f"Expected text/html content type, got: {content_types}"
        )

        # Verify body was written (contains HTML)
        body = original_wfile.getvalue()
        assert b"<!DOCTYPE html>" in body or b"<html" in body, (
            "Expected HTML content in response body"
        )

    def test_dashboard_api_returns_json(self):
        """GET /api/data returns JSON with expected keys."""
        handler = _make_handler("/api/data")

        response_parts = []
        original_wfile = handler.wfile

        def mock_send_response(code, message=None):
            response_parts.append(("status", code))

        def mock_send_header(key, value):
            response_parts.append(("header", key, value))

        def mock_end_headers():
            response_parts.append(("end_headers",))

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers

        # Mock the database call to avoid needing real SQLite data
        mock_data = {
            "daily_summary": {"total_trades": 0, "net_pnl": 0, "win_rate": 0},
            "recent_trades": [],
            "signals_today": [],
            "equity_curve": [],
            "signal_performance": {"total": 0},
            "health_events": [],
            "performance_history": [],
        }

        with patch("dashboard.server.DashboardHandler._get_positions_list", return_value=[]):
            with patch("data.db.get_dashboard_data", return_value=mock_data):
                handler.do_GET()

        # Verify status 200
        status_codes = [p[1] for p in response_parts if p[0] == "status"]
        assert 200 in status_codes, f"Expected 200, got status entries: {status_codes}"

        # Verify Content-Type is JSON
        content_types = [
            p[2] for p in response_parts
            if p[0] == "header" and p[1] == "Content-Type"
        ]
        assert any("application/json" in ct for ct in content_types), (
            f"Expected application/json content type, got: {content_types}"
        )

        # Verify body is valid JSON
        body = original_wfile.getvalue()
        assert len(body) > 0, "Expected non-empty response body"
        data = json.loads(body.decode("utf-8"))
        assert isinstance(data, dict)
        assert "daily_summary" in data

    def test_dashboard_404_for_unknown_path(self):
        """GET /unknown returns 404."""
        handler = _make_handler("/unknown")

        response_parts = []

        def mock_send_response(code, message=None):
            response_parts.append(("status", code))

        def mock_send_header(key, value):
            response_parts.append(("header", key, value))

        def mock_end_headers():
            response_parts.append(("end_headers",))

        def mock_send_error(code, message=None):
            response_parts.append(("status", code))

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers
        handler.send_error = mock_send_error

        handler.do_GET()

        status_codes = [p[1] for p in response_parts if p[0] == "status"]
        assert 404 in status_codes, f"Expected 404, got: {status_codes}"
