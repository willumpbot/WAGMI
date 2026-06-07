#!/usr/bin/env python3
"""
Real-time backtest monitoring
Watches progress, detects errors, ensures smooth execution
"""

import json
import time
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path("coordination/backtest_results")
PROGRESS_FILE = RESULTS_DIR / "progress.jsonl"
LOG_FILE = RESULTS_DIR / "backtest.log"
CHECKPOINT_FILE = RESULTS_DIR / "monitor_checkpoints.jsonl"

def log_monitor(msg):
    """Log monitoring events"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[MONITOR {timestamp}] {msg}")

    # Write to persistent log
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "monitor.log", "a") as f:
        f.write(f"[{timestamp}] {msg}\n")

def read_progress():
    """Read all completed checkpoints"""
    if not PROGRESS_FILE.exists():
        return []

    try:
        checkpoints = []
        with open(PROGRESS_FILE, "r") as f:
            for line in f:
                if line.strip():
                    checkpoints.append(json.loads(line))
        return checkpoints
    except Exception as e:
        log_monitor(f"Error reading progress: {e}")
        return []

def read_recent_log(lines=50):
    """Read last N lines of backtest log"""
    if not LOG_FILE.exists():
        return []

    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            all_lines = f.readlines()
        return all_lines[-lines:]
    except Exception as e:
        log_monitor(f"Error reading log: {e}")
        return []

def detect_errors():
    """Scan for error patterns"""
    log_lines = read_recent_log(100)
    errors = []

    for line in log_lines:
        if "[ERROR]" in line or "[FAILED]" in line or "[TIMEOUT]" in line:
            errors.append(line.strip())

    return errors

def get_progress_summary():
    """Summarize current progress"""
    checkpoints = read_progress()

    if not checkpoints:
        return "No progress yet"

    quarters = {}
    for cp in checkpoints:
        q = cp.get("quarter", "unknown")
        stage = cp.get("stage", "unknown")

        if q not in quarters:
            quarters[q] = []
        quarters[q].append(stage)

    summary = []
    for q in sorted(quarters.keys()):
        stages = quarters[q]
        summary.append(f"{q}: {' > '.join(stages)}")

    return " | ".join(summary)

def monitor_loop():
    """Continuous monitoring loop"""
    log_monitor("Starting real-time backtest monitor")
    log_monitor("Checking progress every 5 seconds...")

    last_checkpoint_count = 0
    last_error_count = 0
    consecutive_silent = 0

    while True:
        try:
            checkpoints = read_progress()
            current_count = len(checkpoints)

            # Detect new progress
            if current_count > last_checkpoint_count:
                log_monitor(f"Progress update: {current_count} checkpoints")
                log_monitor(get_progress_summary())
                last_checkpoint_count = current_count
                consecutive_silent = 0
            else:
                consecutive_silent += 1

            # Detect errors
            errors = detect_errors()
            if len(errors) > last_error_count:
                log_monitor(f"ERROR DETECTED: {errors[-1]}")
                last_error_count = len(errors)

            # Alert if silent for too long
            if consecutive_silent > 120:  # 10 minutes
                log_monitor(f"WARNING: No progress for 10 minutes. Last checkpoints: {current_count}")
                # Check if process still running by looking at log
                recent = read_recent_log(5)
                if recent:
                    log_monitor(f"Last log entries: {recent[-1].strip()}")

            # Check if complete
            if "COMPLETE" in str(read_recent_log(20)):
                log_monitor("BACKTEST COMPLETE - Monitor shutting down")
                break

            time.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            log_monitor("Monitor stopped by user")
            break
        except Exception as e:
            log_monitor(f"Monitor error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    monitor_loop()
