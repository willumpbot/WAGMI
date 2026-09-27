"""Latest funding-rate / open-interest snapshot reader (measurement-floor).

MEASUREMENT-FLOOR (2026-07-27): the funding/OI collector
(``tools/funding_oi_collector.py``) appends a tick every 15 min per symbol to
``bot/data/funding_oi_history.jsonl`` with numeric ``funding_rate``,
``open_interest`` and ``premium`` fields, but nothing captured those NUMBERS
onto a Position at entry -- so the ledger/entry record had no numeric
funding/OI field and derivatives-confirmation instruments were blind.

This module provides ONE tiny, fail-neutral read used at position OPEN to
snapshot the most-recent funding/OI values for a symbol. It is pure
measurement plumbing: it never raises into the open path (missing/corrupt
feed -> all-None), and it never mutates anything.

Record shape (from funding_oi_collector.collect_tick):
    {"timestamp": "...", "symbol": "BTC", "funding_rate": <float>,
     "open_interest": <float notional USD>, "premium": <float>, ...}

Symbol matching: the bot's live ``symbol`` is the SHORT name ("BTC", "ETH",
...) exactly as the collector writes it, but we normalize a full CCXT symbol
("BTC/USDC:USDC") down to the same short form defensively so either caller
convention resolves.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.core.funding_oi_snapshot")

# Default location: bot/data/funding_oi_history.jsonl, resolved relative to
# this module (bot/core/) so it is correct regardless of the process cwd --
# mirrors tools/funding_oi_collector.py's own __file__-anchored DATA_FILE.
_DEFAULT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "funding_oi_history.jsonl")
)

# Only scan the tail of the file -- the latest tick for any of the ~5 tracked
# symbols is always within the last handful of lines, so reading the final
# chunk keeps this O(1)-ish even as the history grows for months.
_TAIL_BYTES = 65536


def _norm_symbol(symbol: str) -> str:
    """Normalize 'BTC/USDC:USDC' or 'BTC' -> 'BTC' (upper)."""
    if not symbol:
        return ""
    return str(symbol).split("/")[0].split(":")[0].strip().upper()


def _read_tail_lines(path: str) -> list:
    """Return the last ~_TAIL_BYTES worth of complete lines, newest last.

    Fail-neutral: any error returns []. Drops a possibly-truncated first
    partial line when we did not read from the start of the file.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    try:
        with open(path, "rb") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
                partial = True
            else:
                partial = False
            chunk = f.read()
    except OSError:
        return []
    try:
        text = chunk.decode("utf-8", errors="ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if partial and lines:
        lines = lines[1:]  # first line may be truncated mid-record
    return lines


def latest_funding_oi(
    symbol: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Return the most-recent funding/OI snapshot for ``symbol``.

    Always returns a dict with keys ``funding_rate``, ``open_interest``,
    ``premium`` and ``funding_oi_ts`` -- values are floats when available, or
    ``None`` when the feed is missing/unreadable or carries no row for this
    symbol. NEVER raises: this is called on the position-open path and must
    fail-neutral (null), never break the open.
    """
    out: Dict[str, Any] = {
        "funding_rate": None,
        "open_interest": None,
        "premium": None,
        "funding_oi_ts": None,
    }
    try:
        target = _norm_symbol(symbol)
        if not target:
            return out
        p = path or _DEFAULT_PATH
        lines = _read_tail_lines(p)
        # Walk newest -> oldest; take the first row matching this symbol.
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(rec, dict):
                continue
            if _norm_symbol(rec.get("symbol", "")) != target:
                continue
            fr = rec.get("funding_rate")
            oi = rec.get("open_interest")
            prem = rec.get("premium")
            out["funding_rate"] = float(fr) if fr is not None else None
            out["open_interest"] = float(oi) if oi is not None else None
            out["premium"] = float(prem) if prem is not None else None
            out["funding_oi_ts"] = rec.get("timestamp")
            return out
    except Exception as e:  # absolute belt-and-suspenders: never break the open
        logger.debug(f"[FUNDING-OI-SNAPSHOT] read skipped for {symbol}: {e}")
    return out
