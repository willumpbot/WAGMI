"""
Health monitoring: heartbeat tracking, stall detection, and alert escalation.

Writes periodic heartbeats to data/heartbeat.json so external monitors
can detect when the bot's main loop has stalled (not just when it crashes).

Watchdog features:
- Detects main loop stalls (no heartbeat for 10+ minutes)
- Tracks error rate spikes (>5 errors in 10 minutes)
- Monitors memory/loop performance degradation
- Sends Telegram alerts on health anomalies
- Logs health events to SQLite for post-mortem analysis

Usage:
    monitor = HealthMonitor(alert_router=alerts)
    monitor.record_heartbeat(loop_duration_s=2.5, positions=3)
    status = monitor.get_status()
    if status["stalled"]:
        alert("Bot stalled!")
"""

import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.monitoring.health")

_HEARTBEAT_FILE = os.path.join("data", "heartbeat.json")
_STALL_THRESHOLD_S = 600  # 10 minutes without heartbeat = stalled
_ERROR_SPIKE_WINDOW_S = 600  # 10 minutes
_ERROR_SPIKE_THRESHOLD = 5  # 5 errors in the window = spike
_SLOW_LOOP_THRESHOLD_S = 120  # 2 minutes per loop = degraded


class HealthMonitor:
    """Tracks bot health via periodic heartbeats with watchdog alerts."""

    def __init__(
        self,
        heartbeat_file: str = _HEARTBEAT_FILE,
        stall_threshold_s: int = _STALL_THRESHOLD_S,
        alert_router=None,
    ):
        self._file = heartbeat_file
        self._stall_threshold = stall_threshold_s
        self._alert_router = alert_router
        self._last_heartbeat = time.time()
        self._loop_durations: list = []  # Last 20 loop durations
        self._scan_count = 0
        self._error_count = 0
        self._start_time = time.time()
        self._error_timestamps: deque = deque(maxlen=50)

        # Alert cooldowns (don't spam)
        self._last_stall_alert = 0.0
        self._last_error_spike_alert = 0.0
        self._last_slow_loop_alert = 0.0
        self._stall_alert_cooldown_s = 1800  # 30 min between stall alerts
        self._error_spike_cooldown_s = 900  # 15 min between error spike alerts
        self._slow_loop_cooldown_s = 900  # 15 min between slow loop alerts

        # Track consecutive stalls for escalation
        self._consecutive_stall_checks = 0

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
        self._consecutive_stall_checks = 0  # Reset stall counter on heartbeat

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
            "error_rate_10m": self._get_error_rate(),
        }
        if extra:
            heartbeat.update(extra)

        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            with open(self._file, "w") as f:
                json.dump(heartbeat, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

        # Check for slow loop degradation
        if loop_duration_s > _SLOW_LOOP_THRESHOLD_S:
            self._alert_slow_loop(loop_duration_s)

    def record_error(self, error_msg: str = ""):
        """Record an error occurrence and check for spike."""
        self._error_count += 1
        self._error_timestamps.append(time.time())

        # Check error rate spike
        rate = self._get_error_rate()
        if rate >= _ERROR_SPIKE_THRESHOLD:
            self._alert_error_spike(rate, error_msg)

        # Log to SQLite
        try:
            from data.db import log_health_event
            log_health_event(
                event_type="error",
                severity="warning",
                message=error_msg[:500] if error_msg else "Unspecified error",
            )
        except Exception:
            pass

    def check_watchdog(self):
        """Run periodic watchdog checks. Call this from the main loop or a timer.

        Detects stalls and other health anomalies. Should be called every
        30-60 seconds from the main loop's tick.
        """
        now = time.time()
        since_last = now - self._last_heartbeat

        # Stall detection
        if since_last > self._stall_threshold:
            self._consecutive_stall_checks += 1
            self._alert_stall(since_last)

    def get_status(self) -> Dict[str, Any]:
        """Get current health status."""
        now = time.time()
        since_last = now - self._last_heartbeat
        uptime = now - self._start_time
        return {
            "last_heartbeat_s_ago": round(since_last, 1),
            "stalled": since_last > self._stall_threshold,
            "uptime_s": round(uptime, 0),
            "uptime_human": self._format_duration(uptime),
            "scan_count": self._scan_count,
            "error_count": self._error_count,
            "error_rate_10m": self._get_error_rate(),
            "avg_loop_s": round(
                sum(self._loop_durations) / len(self._loop_durations), 2
            ) if self._loop_durations else 0,
            "consecutive_stalls": self._consecutive_stall_checks,
        }

    def is_healthy(self) -> bool:
        """Quick health check."""
        return not self.get_status()["stalled"]

    def format_health_summary(self) -> str:
        """Format a human-readable health summary for Telegram /status."""
        s = self.get_status()
        health_icon = "\u2705" if not s["stalled"] else "\U0001f6a8"

        lines = [
            f"{health_icon} Bot Health",
            f"{'=' * 24}",
            f"Uptime: {s['uptime_human']}",
            f"Scans: {s['scan_count']}",
            f"Avg Loop: {s['avg_loop_s']:.1f}s",
            f"Errors: {s['error_count']} ({s['error_rate_10m']} in 10m)",
            f"Last Beat: {s['last_heartbeat_s_ago']:.0f}s ago",
        ]
        if s["stalled"]:
            lines.append(f"\U0001f6a8 STALLED for {s['last_heartbeat_s_ago']:.0f}s!")
        return "\n".join(lines)

    # ── Internal helpers ──

    def _get_error_rate(self) -> int:
        """Count errors in the last 10 minutes."""
        cutoff = time.time() - _ERROR_SPIKE_WINDOW_S
        return sum(1 for t in self._error_timestamps if t > cutoff)

    def _alert_stall(self, seconds_since: float):
        """Send stall alert via Telegram."""
        now = time.time()
        if now - self._last_stall_alert < self._stall_alert_cooldown_s:
            return

        self._last_stall_alert = now
        severity = "critical" if self._consecutive_stall_checks >= 3 else "warning"

        msg = (
            f"\U0001f6a8 BOT STALL DETECTED\n"
            f"{'=' * 24}\n"
            f"No heartbeat for {seconds_since:.0f}s\n"
            f"Consecutive stalls: {self._consecutive_stall_checks}\n"
            f"Last scan: {self._scan_count}\n"
            f"Errors: {self._error_count}\n"
            f"Action: Check bot process immediately"
        )

        logger.error(f"[HEALTH] Stall detected: {seconds_since:.0f}s since last heartbeat")

        if self._alert_router:
            try:
                self._alert_router.send_market_update(msg)
            except Exception as e:
                logger.warning(f"Failed to send stall alert: {e}")

        try:
            from data.db import log_health_event
            log_health_event(
                event_type="stall",
                severity=severity,
                message=f"No heartbeat for {seconds_since:.0f}s",
                details={"seconds_since": seconds_since,
                         "consecutive": self._consecutive_stall_checks},
            )
        except Exception:
            pass

    def _alert_error_spike(self, rate: int, last_error: str = ""):
        """Send error spike alert."""
        now = time.time()
        if now - self._last_error_spike_alert < self._error_spike_cooldown_s:
            return

        self._last_error_spike_alert = now

        msg = (
            f"\u26a0 ERROR SPIKE\n"
            f"{'=' * 24}\n"
            f"{rate} errors in last 10 minutes\n"
            f"Total errors: {self._error_count}\n"
            f"Last: {last_error[:200] if last_error else 'unknown'}"
        )

        logger.warning(f"[HEALTH] Error spike: {rate} errors in 10m window")

        if self._alert_router:
            try:
                self._alert_router.send_market_update(msg)
            except Exception as e:
                logger.warning(f"Failed to send error spike alert: {e}")

        try:
            from data.db import log_health_event
            log_health_event(
                event_type="error_spike",
                severity="warning",
                message=f"{rate} errors in 10 minutes",
                details={"rate": rate, "last_error": last_error[:500]},
            )
        except Exception:
            pass

    def _alert_slow_loop(self, duration_s: float):
        """Send slow loop alert."""
        now = time.time()
        if now - self._last_slow_loop_alert < self._slow_loop_cooldown_s:
            return

        self._last_slow_loop_alert = now

        msg = (
            f"\U0001f422 SLOW LOOP\n"
            f"{'=' * 24}\n"
            f"Loop took {duration_s:.1f}s (threshold: {_SLOW_LOOP_THRESHOLD_S}s)\n"
            f"Avg: {sum(self._loop_durations) / len(self._loop_durations):.1f}s"
        )

        logger.warning(f"[HEALTH] Slow loop: {duration_s:.1f}s")

        if self._alert_router:
            try:
                self._alert_router.send_market_update(msg)
            except Exception as e:
                logger.warning(f"Failed to send slow loop alert: {e}")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        elif seconds < 86400:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
        else:
            d = int(seconds // 86400)
            h = int((seconds % 86400) // 3600)
            return f"{d}d {h}h"
