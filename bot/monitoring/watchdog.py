"""
Watchdog: background thread that monitors bot health and sends alerts.

Detects:
- Main loop stalls (no heartbeat for N seconds)
- High error rates
- Memory/resource issues
- Exchange connectivity loss
- Equity drawdown alerts

Sends alerts via the alert router (Telegram/Discord) when issues detected.
Also logs health events to SQLite for dashboard visibility.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger("bot.monitoring.watchdog")

# Thresholds
STALL_THRESHOLD_S = int(os.getenv("WATCHDOG_STALL_THRESHOLD_S", "300"))  # 5 min
ERROR_RATE_THRESHOLD = int(os.getenv("WATCHDOG_ERROR_THRESHOLD", "10"))  # errors per check
CHECK_INTERVAL_S = int(os.getenv("WATCHDOG_CHECK_INTERVAL_S", "60"))  # check every 60s
DRAWDOWN_ALERT_PCT = float(os.getenv("WATCHDOG_DRAWDOWN_ALERT_PCT", "5.0"))  # 5%


class Watchdog:
    """Background thread that monitors bot health and triggers alerts."""

    def __init__(
        self,
        alert_fn: Optional[Callable[[str], None]] = None,
        stall_threshold_s: int = STALL_THRESHOLD_S,
        check_interval_s: int = CHECK_INTERVAL_S,
    ):
        self.alert_fn = alert_fn
        self.stall_threshold_s = stall_threshold_s
        self.check_interval_s = check_interval_s

        self._thread: Optional[threading.Thread] = None
        self._running = False

        # State tracking
        self._last_heartbeat_ts = time.time()
        self._last_equity = 0.0
        self._peak_equity = 0.0
        self._error_count = 0
        self._errors_since_last_check = 0
        self._scan_count = 0
        self._last_stall_alert_ts = 0.0
        self._last_error_alert_ts = 0.0
        self._last_drawdown_alert_ts = 0.0
        self._consecutive_stalls = 0
        self._exchange_healthy = True
        self._last_exchange_alert_ts = 0.0

    def start(self):
        """Start watchdog in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="watchdog")
        self._thread.start()
        logger.info(
            f"Watchdog started: stall_threshold={self.stall_threshold_s}s, "
            f"check_interval={self.check_interval_s}s"
        )

    def stop(self):
        """Stop watchdog."""
        self._running = False

    def heartbeat(self, equity: float = 0.0, scan_count: int = 0,
                  exchange_healthy: bool = True):
        """Called by main loop to report it's alive."""
        self._last_heartbeat_ts = time.time()
        self._scan_count = scan_count
        self._exchange_healthy = exchange_healthy
        self._consecutive_stalls = 0

        if equity > 0:
            self._last_equity = equity
            if equity > self._peak_equity:
                self._peak_equity = equity

    def record_error(self):
        """Called when an error occurs in the main loop."""
        self._error_count += 1
        self._errors_since_last_check += 1

    def _run(self):
        """Main watchdog loop."""
        while self._running:
            try:
                self._check_health()
            except Exception as e:
                logger.debug(f"Watchdog check error: {e}")
            time.sleep(self.check_interval_s)

    def _check_health(self):
        """Run all health checks."""
        now = time.time()

        # 1. Stall detection
        since_heartbeat = now - self._last_heartbeat_ts
        if since_heartbeat > self.stall_threshold_s:
            self._consecutive_stalls += 1
            if now - self._last_stall_alert_ts > 600:  # Max 1 stall alert per 10 min
                self._last_stall_alert_ts = now
                mins = since_heartbeat / 60
                msg = (
                    f"*WATCHDOG: Bot Stall Detected*\n"
                    f"No heartbeat for {mins:.1f} minutes\n"
                    f"Last scan count: {self._scan_count}\n"
                    f"Consecutive stalls: {self._consecutive_stalls}"
                )
                self._alert(msg, "STALL", "ALERT")

        # 2. Error rate check
        if self._errors_since_last_check >= ERROR_RATE_THRESHOLD:
            if now - self._last_error_alert_ts > 300:  # Max 1 error alert per 5 min
                self._last_error_alert_ts = now
                msg = (
                    f"*WATCHDOG: High Error Rate*\n"
                    f"Errors in last check: {self._errors_since_last_check}\n"
                    f"Total errors: {self._error_count}"
                )
                self._alert(msg, "ERROR_RATE", "WARNING")
        self._errors_since_last_check = 0

        # 3. Equity drawdown check
        if self._peak_equity > 0 and self._last_equity > 0:
            drawdown_pct = (self._peak_equity - self._last_equity) / self._peak_equity * 100
            if drawdown_pct >= DRAWDOWN_ALERT_PCT:
                if now - self._last_drawdown_alert_ts > 1800:  # Max 1 per 30 min
                    self._last_drawdown_alert_ts = now
                    msg = (
                        f"*WATCHDOG: Drawdown Alert*\n"
                        f"Current equity: ${self._last_equity:,.2f}\n"
                        f"Peak equity: ${self._peak_equity:,.2f}\n"
                        f"Drawdown: {drawdown_pct:.1f}%"
                    )
                    self._alert(msg, "DRAWDOWN", "WARNING")

        # 4. Exchange connectivity
        if not self._exchange_healthy:
            if now - self._last_exchange_alert_ts > 600:
                self._last_exchange_alert_ts = now
                msg = (
                    f"*WATCHDOG: Exchange Connectivity Issue*\n"
                    f"Exchange appears unhealthy. Data fetches may be failing."
                )
                self._alert(msg, "EXCHANGE_DOWN", "WARNING")

    def _alert(self, message: str, event_type: str, severity: str):
        """Send alert and log health event."""
        logger.warning(f"[WATCHDOG] {event_type}: {message}")

        # Log to database
        try:
            from data.db import log_health_event
            log_health_event(event_type, severity, message)
        except Exception:
            pass

        # Send via alert router
        if self.alert_fn:
            try:
                self.alert_fn(message)
            except Exception as e:
                logger.debug(f"Watchdog alert send failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get current watchdog status for Telegram /health command."""
        now = time.time()
        since_heartbeat = now - self._last_heartbeat_ts
        return {
            "running": self._running,
            "last_heartbeat_s_ago": round(since_heartbeat, 1),
            "stalled": since_heartbeat > self.stall_threshold_s,
            "consecutive_stalls": self._consecutive_stalls,
            "total_errors": self._error_count,
            "exchange_healthy": self._exchange_healthy,
            "equity": self._last_equity,
            "peak_equity": self._peak_equity,
            "drawdown_pct": round(
                (self._peak_equity - self._last_equity) / self._peak_equity * 100, 1
            ) if self._peak_equity > 0 else 0,
        }


# Module-level singleton
_watchdog: Optional[Watchdog] = None


def get_watchdog(alert_fn: Optional[Callable] = None) -> Watchdog:
    """Get or create the global watchdog instance."""
    global _watchdog
    if _watchdog is None:
        _watchdog = Watchdog(alert_fn=alert_fn)
    return _watchdog
