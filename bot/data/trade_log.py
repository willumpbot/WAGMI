"""
Enhanced trade logging to CSV with state path and ML context.

File: data/trades.csv
Written on every full trade close.
"""

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.data.trade_log")

_TRADES_DIR = "data"
_TRADES_FILE = os.path.join(_TRADES_DIR, "trades.csv")
_HEADERS = [
    "timestamp", "symbol", "side", "entry", "exit",
    "tp1_hit", "tp2_hit", "sl_hit", "trailing_hit", "early_exit",
    "pnl", "fees",
    "ml_samples_at_entry", "ml_samples_at_exit",
    "ml_conf_at_entry", "ml_conf_at_exit",
    "state_path", "outcome", "leverage", "confidence",
    "strategy", "entry_reasons",
    "entry_type", "primary_driver", "regime", "volatility_band",
    # exit_type (2026-07-02): raw close action (SL/TP2/TRAILING_STOP/EARLY_EXIT/
    # LLM_EXIT_AGENT/HOLD_LIMIT/ROTATE_*/...). The five boolean flags above only
    # cover 4 actions, so e.g. LLM_EXIT_AGENT closes were unattributable
    # (all-False flags). Appended LAST so positional readers stay valid.
    "exit_type",
]


def _ensure_file():
    os.makedirs(_TRADES_DIR, exist_ok=True)
    if not os.path.exists(_TRADES_FILE):
        with open(_TRADES_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_HEADERS)
        return
    _migrate_exit_type_column()


def _migrate_exit_type_column():
    """One-time in-place migration: append exit_type to header, pad old rows.

    Cheap header check on every call; full rewrite only if the column is missing.
    """
    try:
        with open(_TRADES_FILE, "r", encoding="utf-8") as f:
            header_line = f.readline()
        if "exit_type" in header_line:
            return
        with open(_TRADES_FILE, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if not rows:
            return
        rows[0] = list(rows[0]) + ["exit_type"]
        width = len(rows[0])
        migrated = [rows[0]] + [r + [""] * (width - len(r)) for r in rows[1:]]
        tmp = _TRADES_FILE + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(migrated)
        os.replace(tmp, _TRADES_FILE)
        logger.info(f"trades.csv migrated: exit_type column added ({len(migrated)-1} rows padded)")
    except Exception as e:
        logger.warning(f"trades.csv exit_type migration failed (non-fatal): {e}")


def log_closed_trade(
    symbol: str,
    side: str,
    entry: float,
    exit_price: float,
    action: str,
    pnl: float,
    fees: float,
    state_path: str,
    outcome: str,
    leverage: float = 1.0,
    confidence: float = 0.0,
    strategy: str = "",
    ml_samples_at_entry: int = 0,
    ml_samples_at_exit: int = 0,
    ml_conf_at_entry: float = 0.0,
    ml_conf_at_exit: float = 0.0,
    entry_reasons: Optional[Dict[str, Any]] = None,
    entry_type: str = "",
    primary_driver: str = "",
    regime: str = "",
    volatility_band: str = "",
):
    """Log a fully closed trade to CSV."""
    import json
    _ensure_file()
    ts = datetime.now(timezone.utc).isoformat()

    tp1_hit = "TP1_HIT" in state_path
    tp2_hit = action == "TP2"
    sl_hit = action == "SL"
    trailing_hit = action == "TRAILING_STOP"
    early_exit = action == "EARLY_EXIT"

    row = [
        ts, symbol, side, f"{entry}", f"{exit_price}",
        str(tp1_hit), str(tp2_hit), str(sl_hit), str(trailing_hit), str(early_exit),
        f"{pnl:.2f}", f"{fees:.2f}",
        str(ml_samples_at_entry), str(ml_samples_at_exit),
        f"{ml_conf_at_entry:.4f}", f"{ml_conf_at_exit:.4f}",
        state_path, outcome, f"{leverage:.1f}", f"{confidence:.1f}",
        strategy, json.dumps(entry_reasons or {}),
        entry_type, primary_driver, regime, volatility_band,
        action,  # exit_type: full attribution even when all flags are False
    ]

    try:
        with open(_TRADES_FILE, "a", newline="") as f:
            csv.writer(f).writerow(row)
    except Exception as e:
        logger.warning(f"Failed to log trade: {e}")
