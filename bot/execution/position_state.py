"""
Position lifecycle state machine.

States: IDLE -> OPEN -> TP1_HIT -> TRAILING -> CLOSED
                 ↓                              ↑
                 └── CLOSED (SL, EARLY_EXIT) ───┘

All transitions are validated. Invalid transitions are logged and rejected.
"""

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("bot.execution.state")

# ── States ──────────────────────────────────────────────
IDLE = "IDLE"
OPEN = "OPEN"
TP1_HIT = "TP1_HIT"
TRAILING = "TRAILING"
CLOSED = "CLOSED"

ALL_STATES = {IDLE, OPEN, TP1_HIT, TRAILING, CLOSED}

# ── Valid transitions: {from_state: {to_state, ...}} ───
VALID_TRANSITIONS = {
    IDLE:     {OPEN},
    OPEN:     {TP1_HIT, CLOSED},       # TP1 partial close, or full close (SL/EARLY_EXIT)
    TP1_HIT:  {TRAILING, CLOSED},      # activate trailing, or direct close
    TRAILING: {CLOSED},                # trailing stop or TP2 hit
    CLOSED:   set(),                   # terminal state
}

# ── Transition log ──────────────────────────────────────
_LOG_DIR = os.path.join("data", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "state_transitions.csv")
_LOG_HEADERS = ["timestamp", "symbol", "old_state", "new_state", "reason"]


def _ensure_log_file():
    """Create CSV with headers if it doesn't exist."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    if not os.path.exists(_LOG_FILE):
        with open(_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_LOG_HEADERS)


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, set())


def log_transition(
    symbol: str, old_state: str, new_state: str, reason: str = ""
):
    """Log a state transition to CSV."""
    _ensure_log_file()
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with open(_LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([ts, symbol, old_state, new_state, reason])
    except Exception as e:
        logger.warning(f"Failed to log state transition: {e}")


def transition(
    symbol: str,
    current_state: str,
    target_state: str,
    reason: str = "",
    log: bool = True,
) -> str:
    """
    Attempt a state transition. Returns the new state.
    If the transition is invalid, logs a warning and returns the current state.
    log=False skips the state_transitions.csv analytics row (OWNER_PLAN_EXEC owner positions).
    """
    if not is_valid_transition(current_state, target_state):
        logger.warning(
            f"[{symbol}] Invalid state transition: {current_state} -> {target_state} "
            f"(reason: {reason}). Staying in {current_state}."
        )
        return current_state

    if log:
        log_transition(symbol, current_state, target_state, reason)
    logger.info(f"[{symbol}] State: {current_state} -> {target_state} ({reason})")
    return target_state
