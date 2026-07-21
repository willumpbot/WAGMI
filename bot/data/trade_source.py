"""
Canonical closed-trade reader (FALLACY_AUDIT / measurework fix).

ROOT CAUSE: multi_strategy_main.py writes trade_ledger.csv and trades.csv from
two independently-resolved close-handler branches. trades.csv silently misses
a meaningful fraction of closes (skewed towards losers), inflating win rate
for every consumer that reads it directly. trade_ledger.csv is the complete,
canonical record of every closed trade.

This module promotes the ledger-reading logic already proven in
llm/agents/dynamic_stats.py (_load_recent_trades_from_ledger) into a shared
util so every consumer (dashboards, telegram, API, learning inputs) reads the
same correct data instead of hand-rolling its own trades.csv parse.

Usage:
    from data.trade_source import load_closed_trades
    trades = load_closed_trades(max_trades=30)          # last N
    trades = load_closed_trades(window_days=7)           # last N days
    trades = load_closed_trades()                        # everything

Each returned dict has normalized keys:
    symbol, side (BUY/SELL), pnl (net), won (bool), strategy, regime,
    confidence, leverage, fees, funding, gross, outcome, timestamp

CANONICAL RUN-LEVEL AGGREGATION (measurement-integrity, Phase 0):
    from data.trade_source import get_run_stats, get_run_pnl, derive_equity
    stats = get_run_stats()      # epoch-fenced net/gross/fees/WR/count — THE
                                  # single number that answers "what's the
                                  # bot's P&L right now", replacing the old
                                  # -$42.39 / -$34.75 / -$10.01 sibling set.
    net = get_run_pnl()          # shorthand for stats["net"]
    eq = derive_equity()         # epoch_equity + in-epoch net_pnl, or None
                                  # if no epoch baseline is stamped yet.

These fence to data/epoch.py's active epoch by default (epoch=True). Pass
epoch=False for the pre-fix all-time behavior (still TEST-row filtered).
Learning/calibration consumers (kelly_engine, ensemble, confidence_scorer,
etc.) intentionally read the FULL ledger history directly and are NOT routed
through this epoch fence — that window is a deliberate design choice (the
learning ledger is preserved across the reset), not a reporting bug.
"""

import csv
import logging
import os
import time
import datetime as _dt
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEDGER_CSV = _DATA_DIR / "trade_ledger.csv"

_SIDE_MAP = {"SHORT": "SELL", "LONG": "BUY", "SELL": "SELL", "BUY": "BUY"}


def _is_fake_row(row: dict) -> bool:
    """TEST/sim-fixture filter (same rule as dynamic_stats.py's proven filter)."""
    if "TEST" in str(row.get("symbol", "")).upper():
        return True
    try:
        entry = float(row.get("entry_price") or 0)
    except (ValueError, TypeError):
        entry = 0
    if entry in (100.0, 150.0, 50000.0):
        return True
    return False


def _row_ts(row: dict) -> Optional[float]:
    t = str(row.get("timestamp", "")).strip()
    if not t:
        return None
    try:
        if "T" in t:
            return _dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        return float(t)
    except (ValueError, TypeError):
        return None


def _normalize_row(row: dict) -> Optional[Dict]:
    try:
        pnl = float(row.get("net_pnl", row.get("pnl", "")))
    except (ValueError, TypeError):
        return None
    cf = (row.get("contributing_factors", "") or "").split(",")
    try:
        entry_price = float(row.get("entry_price", 0) or 0)
    except (ValueError, TypeError):
        entry_price = 0.0
    try:
        exit_price = float(row.get("exit_price", 0) or 0)
    except (ValueError, TypeError):
        exit_price = 0.0
    try:
        fees = float(row.get("fees", 0) or 0)
    except (ValueError, TypeError):
        fees = 0.0
    try:
        funding = float(row.get("funding", 0) or 0)
    except (ValueError, TypeError):
        funding = 0.0
    try:
        gross = float(row.get("gross_pnl", "") or "")
    except (ValueError, TypeError):
        # Fall back to the declared ledger identity (gross - fees + funding
        # == net, see tools/backfill_ledger_fees.py) when gross_pnl is blank.
        gross = pnl + fees - funding
    return {
        "symbol": row.get("symbol", ""),
        "side": _SIDE_MAP.get((row.get("side", "") or "").upper(), row.get("side", "")),
        "pnl": pnl,
        "gross": gross,
        "won": pnl > 0,
        "strategy": cf[0].strip() if cf and cf[0].strip() else "",
        "regime": row.get("regime_1h", ""),
        "confidence": float(row.get("confidence_score", 0) or 0),
        "leverage": float(row.get("leverage", 0) or 0),
        "fees": fees,
        "funding": funding,
        "outcome": row.get("exit_type", ""),
        "timestamp": row.get("timestamp", ""),
        "entry": entry_price,
        "exit": exit_price,
        "entry_type": "",   # not present in trade_ledger.csv schema
        "state_path": "",   # not present in trade_ledger.csv schema
    }


def load_closed_trades(
    max_trades: Optional[int] = None,
    window_days: Optional[float] = None,
    ledger_path: Optional[Path] = None,
) -> List[Dict]:
    """Load closed trades from the canonical trade_ledger.csv.

    Args:
        max_trades: if set, return only the most recent N (after window filter).
        window_days: if set, only include rows with timestamp within the last
            N days.
        ledger_path: override the ledger file path (mainly for tests).

    Returns:
        List of normalized trade dicts, oldest-first, TEST/sim rows excluded.
        Empty list if the ledger is missing or unreadable (fail-open, no crash).
    """
    ledger = ledger_path or LEDGER_CSV
    trades: List[Dict] = []
    try:
        if not ledger.exists():
            return trades
        with open(ledger, "r", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        logger.debug("trade_source: failed to read %s: %s", ledger, e)
        return trades

    # Raw-row ordinal (0-based, header excluded), attached BEFORE any
    # filtering — this is the file-position fence data/epoch.py's
    # start_epoch() records as start_ledger_row_count. It must reflect each
    # row's position in the RAW file, not its position after TEST-row/window
    # filtering, or the fence would drift every time the filter rules change.
    for _idx, _row in enumerate(rows):
        _row["_row_idx"] = _idx

    if window_days is not None:
        try:
            cutoff = time.time() - float(window_days) * 86400.0
            rows = [r for r in rows if (_row_ts(r) or 0) >= cutoff]
        except (ValueError, TypeError):
            pass

    for row in rows:
        if _is_fake_row(row):
            continue
        norm = _normalize_row(row)
        if norm is not None:
            # PR-1d dual fence: carry the RAW (pre-filter) row ordinal and
            # the row's own epoch_id column through to the normalized dict,
            # so _epoch_filter can fence by file position / epoch identity,
            # not just by parsed timestamp (see module docstring for why
            # timestamp-only fencing has two known holes).
            norm["_row_idx"] = row.get("_row_idx")
            norm["epoch_id"] = row.get("epoch_id", "") or ""
            trades.append(norm)

    if max_trades is not None and max_trades > 0:
        trades = trades[-max_trades:]

    return trades


def _raw_ledger_data_rows(ledger_path: Path) -> Optional[List[list]]:
    """Raw (unfiltered, header-stripped) CSV rows via csv.reader — used only
    by the epoch-fence integrity check, which needs the exact column-0
    trade_id at a given file position, not the normalized/filtered view
    load_closed_trades returns. Returns None (not []) if the file can't be
    read, so callers can distinguish "no rows" from "couldn't check"."""
    try:
        with open(ledger_path, "r", newline="") as f:
            all_rows = list(csv.reader(f))
        return all_rows[1:] if all_rows else []
    except Exception:
        return None


def _fence_integrity_ok(ledger_path: Path, start_row_count: int, start_after_trade_id: str) -> bool:
    """True if the ledger's raw shape is still consistent with the active
    epoch marker's recorded fence (data/epoch.py::start_epoch's
    start_ledger_row_count / start_after_trade_id).

    False means the ledger was truncated or rewritten since the epoch was
    stamped — trusting row indices in that state would silently produce a
    wrong window (rows that used to be at index N may no longer be there).
    Callers must fall back to timestamp-only fencing (fail-soft, matching
    data/epoch.py's fallback ethos) rather than crash or report a number
    that looks precise but is actually wrong.
    """
    if start_row_count <= 0:
        return True
    data_rows = _raw_ledger_data_rows(ledger_path)
    if data_rows is None:
        return True  # unreadable -> don't block reporting on this check
    if len(data_rows) < start_row_count:
        logger.error(
            "[EPOCH-FENCE] %s has %d raw row(s), fewer than the active "
            "epoch's start_ledger_row_count=%d — ledger appears "
            "truncated/rewritten since the epoch was stamped. Falling back "
            "to timestamp-only fencing for this call.",
            ledger_path, len(data_rows), start_row_count,
        )
        return False
    if start_after_trade_id:
        boundary_row = data_rows[start_row_count - 1]
        boundary_id = boundary_row[0] if boundary_row else ""
        if boundary_id != start_after_trade_id:
            logger.error(
                "[EPOCH-FENCE] %s row %d has trade_id=%r, expected %r from "
                "the epoch marker — ledger rewritten since the epoch was "
                "stamped. Falling back to timestamp-only fencing for this "
                "call.", ledger_path, start_row_count - 1, boundary_id,
                start_after_trade_id,
            )
            return False
    return True


def _epoch_filter(
    trades: List[Dict],
    cutoff_ts: float,
    start_row_count: int = 0,
    active_epoch_id: str = "",
) -> List[Dict]:
    """PR-1d dual fence: a trade is in-epoch iff EITHER its own epoch_id
    column matches the active epoch's id (authoritative, when both are
    non-empty) OR it clears the row-position/timestamp fence.

    The row-position fence (``_row_idx >= start_row_count``) is authoritative
    on its own once the active epoch actually has a row-count fence
    (``start_row_count > 0``) — this is what fixes the two known holes of a
    timestamp-only fence:
      1. A genuinely post-reset row with an unparseable/blank timestamp
         (``_row_ts`` -> None -> 0) used to fall out of the epoch even
         though it belongs there — now the row-position fence alone admits
         it.
      2. A pre-reset row with a stale/wrong-looking timestamp that happens
         to read as >= epoch_start_ts used to be wrongly INCLUDED by a
         timestamp-only fence — now the row-position fence alone (idx <
         start_row_count) correctly excludes it.

    When ``start_row_count == 0`` (legacy marker, or a fresh epoch stamped
    at row 0 — indistinguishable by design), the row-position term is
    trivially true for every real row (idx >= 0), so the whole fence
    reduces to the original ``ts >= cutoff_ts`` check — BIT-IDENTICAL to
    pre-PR-1 behavior. This is the backward-compat guarantee.
    """
    if cutoff_ts <= 0 and start_row_count <= 0:
        return trades
    out: List[Dict] = []
    for t in trades:
        row_epoch_id = t.get("epoch_id", "") or ""
        if active_epoch_id and row_epoch_id and row_epoch_id == active_epoch_id:
            out.append(t)
            continue
        row_idx = t.get("_row_idx")
        if row_idx is None:
            row_idx = -1  # unknown position -> never satisfies the row fence
        ts = _row_ts(t) or 0
        if row_idx >= start_row_count and (ts >= cutoff_ts or start_row_count > 0):
            out.append(t)
    return out


def get_run_stats(
    epoch: bool = True,
    ledger_path: Optional[Path] = None,
    since_ts: Optional[float] = None,
    until_ts: Optional[float] = None,
) -> Dict:
    """Canonical run-level aggregation — net, gross, fees, funding, WR, count.

    This is THE function every P&L/WR reporting consumer should call. It
    replaces the ~25 independent hand-rolled aggregations that produced the
    -$42.39 / -$34.75 / -$10.01 sibling-P&L bug.

    Args:
        epoch: fence to the active epoch (data/epoch.py), default True. When
            the epoch file is missing/unfenced, this silently degrades to
            all-time (fail-soft — see data/epoch.py::get_active_epoch).
            Pass False for explicit all-time (still TEST-row filtered).
        ledger_path: override the ledger file (tests).
        since_ts: optional additional lower-bound timestamp filter (epoch
            seconds), applied AFTER the epoch fence. Window math for
            derived callers should live here, not be re-implemented per
            caller (Phase 0.5 PR-1d).
        until_ts: optional additional upper-bound timestamp filter (epoch
            seconds), applied AFTER the epoch fence.

    Returns:
        {
          epoch_id, epoch_start, epoch_equity: baseline used (or None),
          n: trade count, wins: win count, wr: win-rate on net_pnl>0 (0-100),
          net: sum(net_pnl), gross: sum(gross_pnl), fees: sum(fees),
          funding: sum(funding), derived_equity: epoch_equity + net, or
          None if no epoch_equity baseline exists.
        }
    """
    from data.epoch import get_active_epoch

    ep = get_active_epoch()
    ledger = ledger_path or LEDGER_CSV
    trades = load_closed_trades(ledger_path=ledger_path)

    cutoff_ts = ep["epoch_start_ts"] if epoch else 0.0
    start_row_count = int(ep.get("start_row_count", 0) or 0) if epoch else 0
    start_after_trade_id = ep.get("start_after_trade_id", "") if epoch else ""
    active_epoch_id = ep["epoch_id"] if epoch else ""

    if epoch and start_row_count > 0 and not _fence_integrity_ok(ledger, start_row_count, start_after_trade_id):
        start_row_count = 0  # fail-soft: fall back to timestamp-only fencing

    if epoch and (cutoff_ts > 0 or start_row_count > 0):
        trades = _epoch_filter(trades, cutoff_ts, start_row_count=start_row_count, active_epoch_id=active_epoch_id)

    if since_ts is not None:
        trades = [t for t in trades if (_row_ts(t) or 0) >= since_ts]
    if until_ts is not None:
        trades = [t for t in trades if (_row_ts(t) or 0) <= until_ts]

    n = len(trades)
    net = sum(t["pnl"] for t in trades)
    gross = sum(t.get("gross", t["pnl"]) for t in trades)
    fees = sum(t.get("fees", 0.0) for t in trades)
    funding = sum(t.get("funding", 0.0) for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    wr = (wins / n * 100.0) if n else 0.0

    equity_base = ep["epoch_equity"] if epoch else None
    derived_equity = round(equity_base + net, 2) if equity_base is not None else None

    return {
        "epoch_id": ep["epoch_id"] if epoch else "",
        "epoch_start": ep["epoch_start"] if epoch else "",
        "epoch_equity": equity_base,
        "n": n,
        "wins": wins,
        "wr": round(wr, 1),
        "net": round(net, 2),
        "gross": round(gross, 2),
        "fees": round(fees, 2),
        "funding": round(funding, 2),
        "derived_equity": derived_equity,
    }


def get_run_pnl(epoch: bool = True) -> float:
    """Shorthand: the headline run-level net P&L number."""
    return get_run_stats(epoch=epoch)["net"]


def derive_equity(epoch: bool = True) -> Optional[float]:
    """epoch_equity + sum(in-epoch net_pnl). None if no epoch_equity baseline
    exists (e.g. data/epoch_start.json missing) — callers must fall back to
    the accumulator (risk_mgr.equity) in that case, never treat None as $0."""
    return get_run_stats(epoch=epoch)["derived_equity"]
