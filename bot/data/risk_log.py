"""
Risk rejection logger.

Logs every rejected trade to data/logs/risk_rejections.csv
and tracks rejection counts for heartbeat reporting.
"""

import csv
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("bot.data.risk_log")

_LOG_DIR = os.path.join("data", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "risk_rejections.csv")
_LOG_HEADERS = [
    "timestamp", "symbol", "reason", "rr1", "sl_distance",
    "leverage", "spread", "confidence",
]

# In-memory counters (reset on heartbeat read)
_rejection_counts = {}


def _ensure_file():
    os.makedirs(_LOG_DIR, exist_ok=True)
    if not os.path.exists(_LOG_FILE):
        with open(_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_LOG_HEADERS)


def log_rejection(
    symbol: str,
    reason: str,
    rr1: float = 0.0,
    sl_distance: float = 0.0,
    leverage: float = 0.0,
    spread: float = 0.0,
    confidence: float = 0.0,
    **kwargs,
):
    """Log a risk rejection."""
    _ensure_file()
    ts = datetime.now(timezone.utc).isoformat()

    try:
        with open(_LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([
                ts, symbol, reason,
                f"{rr1:.3f}", f"{sl_distance:.6f}",
                f"{leverage:.1f}", f"{spread:.4f}", f"{confidence:.1f}",
            ])
    except Exception as e:
        logger.warning(f"Failed to log rejection: {e}")

    _rejection_counts[reason] = _rejection_counts.get(reason, 0) + 1


def get_rejection_counts() -> dict:
    """Get rejection counts since last call (resets on read)."""
    global _rejection_counts
    counts = dict(_rejection_counts)
    _rejection_counts = {}
    return counts
