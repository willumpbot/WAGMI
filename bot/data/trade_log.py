"""
Enhanced trade logging to CSV with state path and ML context.

File: data/trades.csv
Written on every full trade close.
"""

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


# TRADES_CSV_COMPLETENESS_FILTER (2026-07-20): shared reader for every
# consumer of trades.csv. multi_strategy_main.py's terminal-close gate that
# feeds log_closed_trade() above was, until this same date, a hand-maintained
# action-name allowlist (`_FULL_CLOSE`) that repeatedly missed new
# terminal-close action strings (TIME_STOP/TP1_FULL/HOLD_LIMIT/LLM_EXIT_AGENT/
# LLM_EXIT_ENGINE were each added only after a real trade's row went missing).
# Rows written before the state-based gate shipped can silently be missing
# legitimate closes, so mixing them with post-fix rows re-introduces the same
# undercount the fix closes. This helper lets every consumer apply the same
# cutover + the same TEST/synthetic scrub already used elsewhere
# (strategies/ensemble.py._scrub_ledger_df, llm/agents/dynamic_stats.py)
# instead of each re-inventing (or omitting) its own.
_COMPLETENESS_FIX_CUTOVER = "2026-07-20T00:00:00+00:00"
_TEST_ENTRY_SENTINELS = (100.0, 150.0, 50000.0)


def read_trades_csv(
    min_ts: str = _COMPLETENESS_FIX_CUTOVER,
    exclude_test: bool = True,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read a trades.csv-format file as a list of dict rows, post-completeness-fix only.

    - `path` defaults to the live data/trades.csv (_TRADES_FILE); callers that
      need to point at an alternate/test file (e.g. a monkeypatched fixture
      path) may pass one explicitly. When `path` is given, the file is read
      as-is without the auto-create/migration side effects of _ensure_file().
    - Skips rows with a timestamp older than `min_ts` (pass min_ts="" to
      disable the cutover). Pre-fix rows are exactly the ones that can have
      undercount gaps, so they are excluded by default rather than silently
      blended with trustworthy post-fix rows.
    - Skips rows with an unparsable/missing timestamp (same reasoning — the
      gap rows are the ones most likely to have gone stale/corrupt too).
    - When exclude_test=True (default), skips rows whose symbol contains
      'TEST' or whose entry price is a known synthetic/test sentinel value
      (100.0, 150.0, 50000.0) — same scrub already used by
      strategies/ensemble.py._scrub_ledger_df and
      llm/agents/dynamic_stats.py's TEST filter.
    """
    target = path if path is not None else _TRADES_FILE
    if path is None:
        _ensure_file()
    min_dt: Optional[datetime] = None
    if min_ts:
        try:
            min_dt = datetime.fromisoformat(min_ts)
            if min_dt.tzinfo is None:
                min_dt = min_dt.replace(tzinfo=timezone.utc)
        except Exception:
            min_dt = None

    rows: List[Dict[str, Any]] = []
    if not os.path.exists(target):
        return rows
    try:
        with open(target, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_raw = row.get("timestamp", "") or ""
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except Exception:
                    continue  # unparsable/missing timestamp: pre-fix gap row
                if min_dt is not None:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < min_dt:
                        continue
                if exclude_test:
                    symbol = (row.get("symbol", "") or "").upper()
                    if "TEST" in symbol:
                        continue
                    try:
                        entry_val = float(row.get("entry", "") or 0)
                    except Exception:
                        entry_val = None
                    if entry_val in _TEST_ENTRY_SENTINELS:
                        continue
                rows.append(row)
    except Exception as e:
        logger.warning(f"read_trades_csv failed: {e}")
    return rows
