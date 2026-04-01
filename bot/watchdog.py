#!/usr/bin/env python3
"""
External Watchdog — standalone process that monitors the WAGMI trading bot.

Unlike the in-process monitoring.watchdog (which dies when the bot dies),
this runs as a separate process and can detect when the bot has crashed,
hung, or run out of memory.

Usage:
    python watchdog.py monitor          # Continuous monitoring (check every 60s)
    python watchdog.py status           # One-shot health check
    python watchdog.py restart          # Force restart the bot

The watchdog reads the heartbeat file written by the bot every tick and
triggers alerts + crash reports when the heartbeat goes stale.
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure bot/ is in sys.path so we can import bot modules
sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger("watchdog")

# ── Paths ──────────────────────────────────────────────────
BOT_DIR = Path(__file__).parent
DATA_DIR = BOT_DIR / "data"
HEARTBEAT_FILE = DATA_DIR / "heartbeat.json"
POSITION_STATE_FILE = DATA_DIR / "position_state.json"
CRASH_REPORT_DIR = DATA_DIR / "crash_reports"
LOG_DIR = BOT_DIR / "logs"

# ── Thresholds ─────────────────────────────────────────────
HEARTBEAT_STALE_S = int(os.getenv("WATCHDOG_STALE_THRESHOLD_S", "300"))  # 5 min
CHECK_INTERVAL_S = int(os.getenv("WATCHDOG_CHECK_INTERVAL_S", "60"))
AUTO_RESTART = os.getenv("WATCHDOG_AUTO_RESTART", "false").lower() == "true"
MAX_RESTART_ATTEMPTS = int(os.getenv("WATCHDOG_MAX_RESTARTS", "3"))
RESTART_COOLDOWN_S = int(os.getenv("WATCHDOG_RESTART_COOLDOWN_S", "300"))  # 5 min


def _setup_logging():
    """Configure logging for the watchdog process."""
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    # File
    fh = logging.FileHandler(LOG_DIR / "watchdog.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


# ── Heartbeat Reader ──────────────────────────────────────

def read_heartbeat(filepath: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read the heartbeat file. Returns None if missing or unreadable."""
    if filepath is None:
        filepath = HEARTBEAT_FILE
    try:
        if not Path(filepath).exists():
            return None
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read heartbeat: {e}")
        return None


def heartbeat_age_seconds(hb: Optional[Dict]) -> float:
    """Return seconds since last heartbeat. Returns inf if no heartbeat."""
    if hb is None:
        return float("inf")
    try:
        last_alive = datetime.fromisoformat(hb["last_alive"])
        if last_alive.tzinfo is None:
            last_alive = last_alive.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_alive
        return max(0.0, delta.total_seconds())
    except (KeyError, ValueError):
        return float("inf")


def is_bot_process_alive(hb: Optional[Dict]) -> bool:
    """Check if the PID in the heartbeat is still running."""
    if hb is None:
        return False
    pid = hb.get("pid")
    if pid is None:
        return False
    try:
        if sys.platform == "win32":
            # On Windows, use tasklist to check PID
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        else:
            # On Unix, signal 0 checks process existence
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.TimeoutExpired):
        return False


# ── System Info ────────────────────────────────────────────

def get_system_memory() -> Dict[str, Any]:
    """Get system memory usage. Returns empty dict on failure."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_pct": mem.percent,
        }
    except ImportError:
        # psutil not available — try platform-specific fallback
        return {"note": "psutil not installed, memory info unavailable"}


def get_last_log_lines(n: int = 30) -> str:
    """Get the last N lines from the most recent bot log file."""
    try:
        log_files = sorted(LOG_DIR.glob("bot_*.log"), key=os.path.getmtime, reverse=True)
        if not log_files:
            return "(no bot log files found)"
        with open(log_files[0], "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:
        return f"(error reading logs: {e})"


def get_open_positions(filepath: Optional[Path] = None) -> list:
    """Read open positions from position_state.json."""
    if filepath is None:
        filepath = POSITION_STATE_FILE
    try:
        if not Path(filepath).exists():
            return []
        with open(POSITION_STATE_FILE, "r") as f:
            state = json.load(f)
        positions = []
        for symbol, pos in state.get("positions", {}).items():
            if pos.get("state", "CLOSED") != "CLOSED":
                positions.append({
                    "symbol": symbol,
                    "side": pos.get("side"),
                    "entry": pos.get("entry"),
                    "qty": pos.get("qty"),
                    "leverage": pos.get("leverage"),
                    "state": pos.get("state"),
                })
        return positions
    except Exception:
        return []


# ── Crash Reports ──────────────────────────────────────────

def save_crash_report(
    age_seconds: float,
    heartbeat: Optional[Dict],
    reason: str = "heartbeat_stale",
) -> str:
    """Save a crash report and return the file path."""
    os.makedirs(CRASH_REPORT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filepath = CRASH_REPORT_DIR / f"crash_{ts}.json"

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "last_heartbeat": heartbeat.get("last_alive") if heartbeat else None,
        "bot_pid": heartbeat.get("pid") if heartbeat else None,
        "bot_pid_alive": is_bot_process_alive(heartbeat),
        "downtime_seconds": round(age_seconds, 1),
        "downtime_minutes": round(age_seconds / 60, 1),
        "open_positions": get_open_positions(),
        "system_memory": get_system_memory(),
        "last_log_lines": get_last_log_lines(30),
        "platform": platform.platform(),
        "python_version": sys.version,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    logger.critical(f"Crash report saved: {filepath}")
    return str(filepath)


# ── Telegram Alert ─────────────────────────────────────────

def send_telegram_alert(message: str) -> bool:
    """Attempt to send a Telegram alert. Returns True on success."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BOT_DIR / ".env")
    except ImportError:
        pass

    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram not configured (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing)")
        return False

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")
        return False


# ── Bot Restart ────────────────────────────────────────────

def restart_bot() -> bool:
    """Attempt to restart the bot process. Returns True on success."""
    logger.info("Attempting to restart bot...")
    try:
        python = sys.executable
        run_script = str(BOT_DIR / "run.py")
        # Start in background, detached from watchdog
        if sys.platform == "win32":
            subprocess.Popen(
                [python, run_script, "paper"],
                cwd=str(BOT_DIR),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            subprocess.Popen(
                [python, run_script, "paper"],
                cwd=str(BOT_DIR),
                start_new_session=True,
            )
        logger.info("Bot restart initiated")
        return True
    except Exception as e:
        logger.error(f"Bot restart failed: {e}")
        return False


# ── Commands ───────────────────────────────────────────────

def cmd_status():
    """One-shot health check."""
    hb = read_heartbeat()
    age = heartbeat_age_seconds(hb)
    pid_alive = is_bot_process_alive(hb)
    positions = get_open_positions()

    print("=" * 50)
    print("WAGMI Bot Health Check")
    print("=" * 50)

    if hb is None:
        print("  Heartbeat: NOT FOUND (bot never started or crashed on startup)")
        print("  Status: UNKNOWN")
    else:
        print(f"  Last heartbeat: {hb.get('last_alive', '?')}")
        print(f"  Heartbeat age: {age:.0f}s ({age/60:.1f} min)")
        print(f"  Bot PID: {hb.get('pid', '?')} ({'ALIVE' if pid_alive else 'DEAD'})")

        if age <= HEARTBEAT_STALE_S:
            print(f"  Status: HEALTHY (threshold: {HEARTBEAT_STALE_S}s)")
        else:
            print(f"  Status: STALE/CRASHED (>{HEARTBEAT_STALE_S}s)")

    print(f"  Open positions: {len(positions)}")
    for p in positions:
        print(f"    {p['symbol']} {p['side']} entry=${p['entry']} lev={p['leverage']}x")

    mem = get_system_memory()
    if "used_pct" in mem:
        print(f"  System memory: {mem['used_pct']}% used ({mem['available_gb']:.1f}GB free)")

    print("=" * 50)

    # Return status for programmatic use
    return age <= HEARTBEAT_STALE_S if hb else False


def cmd_restart():
    """Force restart the bot."""
    hb = read_heartbeat()
    pid_alive = is_bot_process_alive(hb)

    if pid_alive and hb:
        print(f"Bot process (PID {hb['pid']}) is still alive.")
        print("Kill it first or wait for it to stop.")
        return False

    print("Bot process is not running. Starting...")
    return restart_bot()


def cmd_monitor():
    """Continuous monitoring loop."""
    logger.info(
        f"Watchdog monitor started: "
        f"check_interval={CHECK_INTERVAL_S}s, "
        f"stale_threshold={HEARTBEAT_STALE_S}s, "
        f"auto_restart={AUTO_RESTART}"
    )

    restart_attempts = 0
    last_restart_ts = 0.0
    last_alert_ts = 0.0
    was_healthy = True

    while True:
        try:
            hb = read_heartbeat()
            age = heartbeat_age_seconds(hb)
            pid_alive = is_bot_process_alive(hb)

            if age <= HEARTBEAT_STALE_S:
                # Bot is healthy
                if not was_healthy:
                    logger.info("Bot recovered — heartbeat is fresh again")
                    send_telegram_alert("Bot *recovered* and is running normally again.")
                was_healthy = True
                restart_attempts = 0
            else:
                # Bot is stuck or crashed
                was_healthy = False
                now = time.time()

                # Only alert every 10 minutes
                if now - last_alert_ts > 600:
                    last_alert_ts = now

                    if hb is None:
                        reason = "no_heartbeat_file"
                        msg = "No heartbeat file found — bot may have never started"
                    elif not pid_alive:
                        reason = "process_dead"
                        msg = f"Bot process (PID {hb.get('pid')}) is dead"
                    else:
                        reason = "heartbeat_stale"
                        msg = f"Heartbeat stale for {age/60:.1f} min (process alive but hung?)"

                    logger.critical(f"BOT DOWN: {msg}")

                    # Save crash report
                    report_path = save_crash_report(age, hb, reason)

                    # Telegram alert
                    alert_msg = (
                        f"*WATCHDOG ALERT: Bot Down*\n"
                        f"{msg}\n"
                        f"Downtime: {age/60:.1f} min\n"
                        f"Open positions: {len(get_open_positions())}\n"
                        f"Crash report: `{Path(report_path).name}`"
                    )
                    send_telegram_alert(alert_msg)

                    # Auto-restart if enabled
                    if AUTO_RESTART and not pid_alive:
                        if restart_attempts < MAX_RESTART_ATTEMPTS:
                            if now - last_restart_ts > RESTART_COOLDOWN_S:
                                restart_attempts += 1
                                last_restart_ts = now
                                logger.info(
                                    f"Auto-restart attempt {restart_attempts}/{MAX_RESTART_ATTEMPTS}"
                                )
                                success = restart_bot()
                                send_telegram_alert(
                                    f"Auto-restart attempt {restart_attempts}: "
                                    f"{'initiated' if success else 'FAILED'}"
                                )
                        else:
                            logger.error(
                                f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached. "
                                f"Manual intervention required."
                            )

        except KeyboardInterrupt:
            logger.info("Watchdog stopped by user")
            break
        except Exception as e:
            logger.error(f"Watchdog error: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL_S)


# ── Main ───────────────────────────────────────────────────

def main():
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="WAGMI Bot External Watchdog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  monitor    Continuous monitoring (check every 60s, alert on stale heartbeat)
  status     One-shot health check
  restart    Force restart the bot process

Environment variables:
  WATCHDOG_STALE_THRESHOLD_S   Seconds before heartbeat is considered stale (default: 300)
  WATCHDOG_CHECK_INTERVAL_S    Seconds between checks in monitor mode (default: 60)
  WATCHDOG_AUTO_RESTART        Enable auto-restart on crash (default: false)
  WATCHDOG_MAX_RESTARTS        Max restart attempts before giving up (default: 3)
  WATCHDOG_RESTART_COOLDOWN_S  Min seconds between restart attempts (default: 300)
        """,
    )
    parser.add_argument(
        "command",
        choices=["monitor", "status", "restart"],
        help="Watchdog command",
    )
    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "restart":
        cmd_restart()
    elif args.command == "monitor":
        cmd_monitor()


if __name__ == "__main__":
    main()
