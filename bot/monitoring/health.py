"""
Health monitoring: heartbeat tracking and stall detection.

Writes periodic heartbeats to data/heartbeat.json so external monitors
can detect when the bot's main loop has stalled (not just when it crashes).

Usage:
    monitor = HealthMonitor()
    monitor.record_heartbeat(loop_duration_s=2.5, positions=3)
    status = monitor.get_status()
    if status["stalled"]:
        alert("Bot stalled!")
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger("bot.monitoring.health")

_HEARTBEAT_FILE = os.path.join("data", "heartbeat.json")
_STALL_THRESHOLD_S = 600  # 10 minutes without heartbeat = stalled


class HealthMonitor:
    """Tracks bot health via periodic heartbeats."""

    def __init__(self, heartbeat_file: str = _HEARTBEAT_FILE, stall_threshold_s: int = _STALL_THRESHOLD_S):
        self._file = heartbeat_file
        self._stall_threshold = stall_threshold_s
        self._last_heartbeat = time.time()
        self._loop_durations: list = []  # Last 20 loop durations
        self._scan_count = 0
        self._error_count = 0
        self._start_time = time.time()

    def record_heartbeat(
        self,
        loop_duration_s: float = 0.0,
        positions: int = 0,
        equity: float = 0.0,
        extra: Dict[str, Any] = None,
    ):
        """Record a heartbeat from the main trading loop."""
        self._last_heartbeat = time.time()
        self._scan_count += 1

        if loop_duration_s > 0:
            self._loop_durations.append(loop_duration_s)
            if len(self._loop_durations) > 20:
                self._loop_durations = self._loop_durations[-20:]

        heartbeat = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epoch": self._last_heartbeat,
            "uptime_s": round(self._last_heartbeat - self._start_time, 0),
            "scan_count": self._scan_count,
            "loop_duration_s": round(loop_duration_s, 2),
            "avg_loop_s": round(
                sum(self._loop_durations) / len(self._loop_durations), 2
            ) if self._loop_durations else 0,
            "positions": positions,
            "equity": round(equity, 2),
            "errors": self._error_count,
        }
        if extra:
            heartbeat.update(extra)

        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            with open(self._file, "w") as f:
                json.dump(heartbeat, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

    def record_error(self):
        """Record an error occurrence."""
        self._error_count += 1

    def get_status(self) -> Dict[str, Any]:
        """Get current health status."""
        now = time.time()
        since_last = now - self._last_heartbeat
        return {
            "last_heartbeat_s_ago": round(since_last, 1),
            "stalled": since_last > self._stall_threshold,
            "uptime_s": round(now - self._start_time, 0),
            "scan_count": self._scan_count,
            "error_count": self._error_count,
            "avg_loop_s": round(
                sum(self._loop_durations) / len(self._loop_durations), 2
            ) if self._loop_durations else 0,
        }

    def is_healthy(self) -> bool:
        """Quick health check."""
        return not self.get_status()["stalled"]
