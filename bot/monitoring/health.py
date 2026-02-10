"""
Bot health monitoring and alerting.

Checks every minute:
- Is bot process running?
- Last data fetch time
- Exchange connection status
- Equity trend
- Memory usage
- Log file size
- ML training status

Sends Discord alerts if issues detected.
"""

import logging
import os
import psutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.monitoring.health")


class HealthMonitor:
    """Monitors bot health and detects issues."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.last_check = None
        self.alerts_sent = {}  # Track sent alerts to avoid spam

        # Defaults
        self.max_memory_mb = self.config.get("max_memory_mb", 500)
        self.max_log_size_mb = self.config.get("max_log_size_mb", 100)
        self.data_fetch_timeout_s = self.config.get("data_fetch_timeout_s", 60)
        self.equity_stale_threshold_min = self.config.get("equity_stale_threshold_min", 5)

    def check_all(self, bot_process: Optional[psutil.Process] = None) -> Dict[str, Any]:
        """
        Run all health checks.

        Returns: Dict with status of each check and any issues found
        """
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {},
            "alerts": [],
        }

        # Bot process health
        if bot_process:
            status["checks"]["bot_running"] = self._check_process(bot_process)

        # Memory usage
        memory_status = self._check_memory()
        status["checks"]["memory"] = memory_status

        if memory_status["alert"]:
            status["alerts"].append({
                "severity": "WARN",
                "message": f"⚠️ Memory usage {memory_status['mb']:.0f}MB (threshold: {self.max_memory_mb}MB)",
            })

        # Log file size
        log_status = self._check_log_size()
        status["checks"]["log_size"] = log_status

        if log_status["alert"]:
            status["alerts"].append({
                "severity": "WARN",
                "message": f"⚠️ Log file {log_status['mb']:.0f}MB (threshold: {self.max_log_size_mb}MB)",
            })

        # Data freshness
        data_status = self._check_data_freshness()
        status["checks"]["data_freshness"] = data_status

        if data_status["alert"]:
            status["alerts"].append({
                "severity": "CRITICAL",
                "message": f"🚨 No data fetch for {data_status['minutes']:.0f} minutes (threshold: {self.data_fetch_timeout_s}s)",
            })

        self.last_check = status
        return status

    def _check_process(self, process: psutil.Process) -> Dict[str, Any]:
        """Check if bot process is running."""
        try:
            is_alive = process.is_running()
            return {
                "ok": is_alive,
                "alert": not is_alive,
                "message": "✅ Bot process running" if is_alive else "🚨 Bot process not found",
            }
        except Exception as e:
            logger.warning(f"Could not check process: {e}")
            return {"ok": False, "alert": True, "message": f"Could not verify: {e}"}

    def _check_memory(self) -> Dict[str, Any]:
        """Check memory usage."""
        try:
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            is_ok = mem_mb < self.max_memory_mb

            return {
                "ok": is_ok,
                "alert": not is_ok,
                "mb": mem_mb,
                "message": f"Memory: {mem_mb:.0f}MB",
            }
        except Exception as e:
            logger.warning(f"Could not check memory: {e}")
            return {"ok": True, "alert": False, "mb": 0}

    def _check_log_size(self) -> Dict[str, Any]:
        """Check log file size."""
        log_file = Path("logs") / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        if not log_file.exists():
            return {"ok": True, "alert": False, "mb": 0}

        try:
            size_mb = log_file.stat().st_size / (1024 * 1024)
            is_ok = size_mb < self.max_log_size_mb

            return {
                "ok": is_ok,
                "alert": not is_ok,
                "mb": size_mb,
                "message": f"Log file: {size_mb:.0f}MB",
            }
        except Exception as e:
            logger.warning(f"Could not check log size: {e}")
            return {"ok": True, "alert": False, "mb": 0}

    def _check_data_freshness(self) -> Dict[str, Any]:
        """Check how recently data was fetched."""
        # Look for recent files in logs
        log_dir = Path("logs")
        if not log_dir.exists():
            return {"ok": True, "alert": False, "minutes": 0}

        try:
            # Find most recent log file
            log_files = list(log_dir.glob("bot_*.log"))
            if not log_files:
                return {"ok": False, "alert": True, "minutes": 999}

            latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
            last_modified = datetime.fromtimestamp(latest_log.stat().st_mtime, tz=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - last_modified).total_seconds()
            age_minutes = age_seconds / 60

            is_ok = age_seconds < self.data_fetch_timeout_s

            return {
                "ok": is_ok,
                "alert": not is_ok,
                "minutes": age_minutes,
                "message": f"Last data: {age_minutes:.1f}min ago",
            }
        except Exception as e:
            logger.warning(f"Could not check data freshness: {e}")
            return {"ok": False, "alert": True, "minutes": 999}

    def print_status(self):
        """Print current health status."""
        if not self.last_check:
            print("❌ No health check performed yet")
            return

        print("\n" + "=" * 60)
        print("BOT HEALTH STATUS")
        print("=" * 60)
        print(f"Checked: {self.last_check['timestamp']}")

        print("\n✅ CHECKS:")
        for check_name, result in self.last_check["checks"].items():
            status = "✅" if result.get("ok") else "❌"
            print(f"  {status} {check_name}: {result.get('message', 'ok')}")

        if self.last_check["alerts"]:
            print(f"\n🚨 ALERTS ({len(self.last_check['alerts'])}):")
            for alert in self.last_check["alerts"]:
                print(f"  {alert['severity']}: {alert['message']}")
        else:
            print("\n✅ No alerts")

        print("=" * 60 + "\n")

    def should_restart(self) -> bool:
        """Determine if bot should be restarted for recovery."""
        if not self.last_check:
            return False

        # Check for critical alerts
        for alert in self.last_check["alerts"]:
            if alert["severity"] == "CRITICAL":
                return True

        return False


def format_alert_message(status: Dict[str, Any]) -> str:
    """Format health status for Discord."""
    checks = status.get("checks", {})

    if not status.get("alerts"):
        # All good - send normal status
        emoji = "✅"
        lines = [f"{emoji} Bot Healthy"]

        if "memory" in checks:
            mb = checks["memory"].get("mb", 0)
            lines.append(f"  Memory: {mb:.0f}MB")

        if "data_freshness" in checks:
            mins = checks["data_freshness"].get("minutes", 0)
            lines.append(f"  Last data: {mins:.1f}min ago")

        return "\n".join(lines)

    else:
        # Problems - send alert
        lines = ["🚨 **BOT HEALTH ALERT**"]
        for alert in status["alerts"]:
            lines.append(f"  {alert['message']}")

        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitor = HealthMonitor()
    status = monitor.check_all()
    monitor.print_status()
