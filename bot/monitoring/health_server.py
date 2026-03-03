"""
HTTP health check endpoint for container orchestration.

Provides /healthz and /readyz endpoints for Kubernetes, Docker healthchecks,
or any monitoring system.

Usage:
    from monitoring.health_server import start_health_server
    server = start_health_server(health_monitor, port=8081)
    # ... later ...
    server.shutdown()

Endpoints:
    GET /healthz  — Returns 200 if bot loop is not stalled, 503 otherwise
    GET /readyz   — Returns 200 if bot is initialized and healthy
    GET /status   — Returns full JSON status (heartbeat, exchange, positions)
"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("bot.monitoring.health_server")


class HealthRequestHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for health checks."""

    # Shared state set by the server factory
    _health_monitor = None
    _extra_status_fn: Optional[Callable] = None

    def do_GET(self):
        if self.path == "/healthz":
            self._handle_healthz()
        elif self.path == "/readyz":
            self._handle_readyz()
        elif self.path == "/status":
            self._handle_status()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_healthz(self):
        """Liveness check: is the bot loop running?"""
        if self._health_monitor and self._health_monitor.is_healthy():
            self._json_response(200, {"status": "ok"})
        else:
            self._json_response(503, {"status": "stalled"})

    def _handle_readyz(self):
        """Readiness check: is the bot initialized and able to trade?"""
        if self._health_monitor is None:
            self._json_response(503, {"status": "not_initialized"})
            return
        status = self._health_monitor.get_status()
        if status.get("scan_count", 0) > 0 and not status.get("stalled"):
            self._json_response(200, {"status": "ready", "scans": status["scan_count"]})
        else:
            self._json_response(503, {"status": "not_ready"})

    def _handle_status(self):
        """Full status endpoint with all monitoring data."""
        data: Dict[str, Any] = {}
        if self._health_monitor:
            data["health"] = self._health_monitor.get_status()
        if self._extra_status_fn:
            try:
                data["extra"] = self._extra_status_fn()
            except Exception as e:
                data["extra_error"] = str(e)
        self._json_response(200, data)

    def _json_response(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def log_message(self, format, *args):
        """Suppress default HTTP access logs."""
        pass


def start_health_server(
    health_monitor,
    port: int = 8081,
    extra_status_fn: Optional[Callable] = None,
) -> Optional[HTTPServer]:
    """Start the health check HTTP server in a background thread.

    Args:
        health_monitor: HealthMonitor instance
        port: Port to listen on
        extra_status_fn: Optional callable returning dict for /status endpoint

    Returns:
        HTTPServer instance (call .shutdown() to stop)
    """
    # Set shared state on the handler class
    HealthRequestHandler._health_monitor = health_monitor
    HealthRequestHandler._extra_status_fn = extra_status_fn

    try:
        server = HTTPServer(("0.0.0.0", port), HealthRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Health server started on port {port}")
        return server
    except OSError as e:
        logger.warning(f"Could not start health server on port {port}: {e}")
        return None
