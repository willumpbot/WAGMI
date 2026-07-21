"""Canonical epoch fence — single source of truth for "which trades count".

THE PROBLEM (measurement-integrity, Phase 0): the same bot reported three
different P&Ls (-$42.39 / -$34.75 / -$10.01) because every consumer invented
its own window (since-restart, today-UTC, 24h/7d/30d, lifetime, a hardcoded
"honest-numbers" cutoff...). None of them ever read data/epoch_start.json —
the one file that actually recorded the operational $5k reset baseline
(2026-07-15T12:40:51Z, epoch_equity=$5000).

This module makes that file the single canonical epoch. Anything that
reports RUN-level P&L (as opposed to LEARNING-window P&L — see
data/trade_source.py's get_run_stats() docstring for that distinction)
should fence through get_active_epoch().

Fail-soft by design: if data/epoch_start.json is missing or unparsable,
get_active_epoch() returns epoch_start_ts=0.0 (no fence -> effectively
all-time) and epoch_equity=None (nothing to derive equity from). It never
raises. Callers MUST treat epoch_equity=None as "can't derive equity here",
never as "$0".

Env override: EPOCH_START_FILE points at an alternate epoch marker (tests /
alternate worktrees where the live data/epoch_start.json is absent).

CODE-OWNED MARKER (Phase 0.5 PR-1): data/equity_epoch.json is the successor
to the hand-edited data/epoch_start.json -- it is written ONLY by
start_epoch() below (never hand-edited), and carries a DUAL fence: the
original epoch_start timestamp PLUS a raw ledger row-count/trade-id fence
(start_ledger_row_count / start_after_trade_id) that data/trade_source.py's
_epoch_filter uses to fence by file position, not just clock time. See
_epoch_path() for the fallback order and start_epoch() for the writer
contract. A legacy epoch_start.json (no row-count field) degrades to
start_row_count=0 / start_after_trade_id="" -- a pure timestamp fence,
BIT-IDENTICAL to pre-PR-1 behavior until the first start_epoch() call.
"""
import csv
import os
import json
import logging
import threading
import datetime as _dt
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_BOT_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_EPOCH_FILE = _BOT_DIR / "data" / "epoch_start.json"
_EQUITY_EPOCH_FILE = _BOT_DIR / "data" / "equity_epoch.json"

# Synthetic/test entry prices seeded by test fixtures — exclude from real-trade
# aggregation. Mirrors data/trade_source.py::_is_fake_row and
# feedback/live_edge.py::_TEST_ENTRY_PRICES — kept here too so any module can
# import ONE shared filter instead of copy-pasting the rule (measurement-
# integrity fix 9: "stop re-implementing the exclusion list per-caller").
TEST_ENTRY_PRICES = (100.0, 150.0, 50000.0)

_lock = threading.Lock()
_cache: Dict[str, Any] = {"epoch": None, "mtime": None, "path": None, "warned_missing": False}


def _epoch_path() -> Path:
    """Fallback order (Phase 0.5 PR-1c): EPOCH_START_FILE env override ->
    the code-owned equity_epoch.json if it exists -> the legacy hand-edited
    epoch_start.json. This makes the code-owned marker take over
    transparently the first time start_epoch() runs, with zero change to
    any caller (they all go through get_active_epoch())."""
    override = os.environ.get("EPOCH_START_FILE", "").strip()
    if override:
        return Path(override)
    if _EQUITY_EPOCH_FILE.exists():
        return _EQUITY_EPOCH_FILE
    return _DEFAULT_EPOCH_FILE


def _parse_iso_ts(iso_str: str) -> float:
    try:
        return _dt.datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _fallback_epoch() -> Dict[str, Any]:
    return {
        "epoch_id": "",
        "epoch_start": "",
        "epoch_start_ts": 0.0,
        "epoch_equity": None,
        "start_row_count": 0,
        "start_after_trade_id": "",
        "source": "fallback_no_fence",
    }


def get_active_epoch(force_reload: bool = False) -> Dict[str, Any]:
    """Return the canonical active epoch, cached with mtime invalidation.

    Returns:
        {epoch_id: str, epoch_start: iso-str, epoch_start_ts: float (epoch
        seconds, 0.0 if unfenced), epoch_equity: float|None,
        start_row_count: int (0 if unset/legacy -- Phase 0.5 PR-1 row-
        position fence), start_after_trade_id: str ("" if unset/legacy),
        source: str}
    """
    path = _epoch_path()
    with _lock:
        try:
            mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            mtime = None

        if (not force_reload and _cache["epoch"] is not None
                and _cache["path"] == str(path) and _cache["mtime"] == mtime):
            return dict(_cache["epoch"])

        if mtime is None:
            if not _cache["warned_missing"]:
                logger.warning(
                    "[EPOCH] %s not found — reporting falls back to ALL-TIME "
                    "(no epoch fence). Expected pre-reset or in a worktree "
                    "without runtime data; stamp the file to enable "
                    "epoch-fenced reporting.", path,
                )
                _cache["warned_missing"] = True
            epoch = _fallback_epoch()
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                epoch_start_iso = str(raw.get("epoch_start", "") or "")
                raw_equity = raw.get("epoch_equity")
                try:
                    start_row_count = int(raw.get("start_ledger_row_count", 0) or 0)
                except (ValueError, TypeError):
                    start_row_count = 0
                epoch = {
                    "epoch_id": str(raw.get("epoch_id", "") or ""),
                    "epoch_start": epoch_start_iso,
                    "epoch_start_ts": _parse_iso_ts(epoch_start_iso) if epoch_start_iso else 0.0,
                    "epoch_equity": float(raw_equity) if raw_equity is not None else None,
                    "start_row_count": start_row_count,
                    "start_after_trade_id": str(raw.get("start_after_trade_id", "") or ""),
                    "source": str(path),
                }
            except Exception as e:
                logger.warning("[EPOCH] failed to parse %s: %s — falling back to ALL-TIME", path, e)
                epoch = _fallback_epoch()

        _cache["epoch"] = epoch
        _cache["mtime"] = mtime
        _cache["path"] = str(path)
        return dict(epoch)


def epoch_start_ts() -> float:
    """Epoch seconds of the active epoch's start; 0.0 if unfenced."""
    return get_active_epoch()["epoch_start_ts"]


def epoch_equity() -> Optional[float]:
    """Equity baseline at epoch start; None if unfenced/unset."""
    return get_active_epoch()["epoch_equity"]


def epoch_id() -> str:
    """Active epoch's identifier; "" if unfenced."""
    return get_active_epoch()["epoch_id"]


def start_epoch(
    new_equity: float,
    reason: str,
    *,
    ledger_path: Optional[Path] = None,
    epoch_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Start a new code-owned epoch: write data/equity_epoch.json (Phase 0.5
    PR-1). This is the ONLY writer of that file -- no more hand-editing.

    Dual-fences the new epoch so both later PR-1d's row-position fence and
    the pre-existing timestamp fence protect it:
      - start_ledger_row_count: RAW (unfiltered) row count of
        trade_ledger.csv at stamp time. A ledger row is in-epoch iff its
        0-based raw ordinal is >= this value.
      - start_after_trade_id: the trade_id (column 0) of the last raw row at
        stamp time, "" if the ledger was empty. Used by
        data/trade_source.py's fence-integrity check to detect a
        truncated/rewritten ledger and fail soft to timestamp-only fencing.

    Safety guards:
      - Refuses to run under pytest (PYTEST_CURRENT_TEST set) UNLESS an
        explicit epoch_file override is given -- mirrors execution/risk.py's
        PYTEST_CURRENT_TEST guard on save_equity_state, so an unmocked test
        run can never stamp a synthetic epoch over real data.
      - Archives the outgoing marker (whatever get_active_epoch() currently
        resolves to -- code-owned or legacy) to data/epoch_history.jsonl
        BEFORE overwriting, via atomic append (never lost).
      - The new record is written with atomic_write_json (torn-file safe).

    Args:
        new_equity: the new epoch's starting equity baseline.
        reason: free-text operator/automation reason, stored verbatim.
        ledger_path: override the trade ledger path (tests only; production
            always uses core.paths.trade_ledger_path()).
        epoch_file: override where the new marker is written AND read from
            for "current marker" snapshot purposes when set (tests only;
            production always uses core.paths.equity_epoch_path()). REQUIRED
            under pytest.

    Returns:
        The new epoch record dict (schema_version, epoch_id, epoch_start,
        epoch_equity, start_ledger_row_count, start_after_trade_id, reason,
        prior_epoch_id, prior_derived_equity, prior_equity_accumulator,
        written_by, stamped_at).

    Raises:
        RuntimeError: if called under pytest without an epoch_file override.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and epoch_file is None:
        raise RuntimeError(
            "start_epoch() refuses to run under pytest without an explicit "
            "epoch_file= override -- this guards against a test run "
            "stamping a synthetic epoch over the live "
            "data/equity_epoch.json (mirrors execution/risk.py's "
            "PYTEST_CURRENT_TEST guard on save_equity_state)."
        )

    from core import paths as _paths
    from core.atomic_state import atomic_write_json, append_jsonl_line, read_json_or_none
    from data.trade_source import get_run_stats as _get_run_stats

    target_epoch_path = Path(epoch_file) if epoch_file is not None else _paths.equity_epoch_path()
    target_ledger_path = Path(ledger_path) if ledger_path is not None else _paths.trade_ledger_path()

    # 2. Snapshot the OUTGOING epoch before touching anything.
    prior_epoch = get_active_epoch(force_reload=True)
    prior_epoch_id = prior_epoch.get("epoch_id", "")
    prior_stats = _get_run_stats(ledger_path=(target_ledger_path if ledger_path is not None else None))
    prior_derived_equity = prior_stats.get("derived_equity")

    prior_equity_accumulator: Optional[float] = None
    try:
        risk_state = read_json_or_none(_paths.risk_equity_state_path())
        if risk_state is not None:
            raw_acc = risk_state.get("equity")
            prior_equity_accumulator = float(raw_acc) if raw_acc is not None else None
    except Exception as e:
        logger.debug("[EPOCH] could not read risk_equity_state for prior_equity_accumulator: %s", e)

    # 3. Raw (unfiltered) row count + last row's trade_id -> the new fence.
    start_ledger_row_count = 0
    start_after_trade_id = ""
    try:
        if target_ledger_path.exists():
            with open(target_ledger_path, "r", newline="", encoding="utf-8") as f:
                all_rows = list(csv.reader(f))
            data_rows = all_rows[1:] if all_rows else []
            start_ledger_row_count = len(data_rows)
            if data_rows and data_rows[-1]:
                start_after_trade_id = data_rows[-1][0]
    except Exception as e:
        logger.warning(
            "[EPOCH] failed to read %s for the row-count fence -- new epoch "
            "will start with start_ledger_row_count=0 (%s)", target_ledger_path, e,
        )

    # 4. New epoch id.
    now = _dt.datetime.now(_dt.timezone.utc)
    new_epoch_id = f"epoch-{now.strftime('%Y%m%dT%H%M%SZ')}"

    record: Dict[str, Any] = {
        "schema_version": 1,
        "epoch_id": new_epoch_id,
        "epoch_start": now.isoformat(),
        "epoch_equity": float(new_equity),
        "start_ledger_row_count": start_ledger_row_count,
        "start_after_trade_id": start_after_trade_id,
        "reason": str(reason),
        "prior_epoch_id": prior_epoch_id,
        "prior_derived_equity": prior_derived_equity,
        "prior_equity_accumulator": prior_equity_accumulator,
        "written_by": "data.epoch.start_epoch",
        "stamped_at": now.isoformat(),
    }

    # 5. Archive the OLD marker (whatever was actually active) BEFORE
    # overwriting it -- never lose the outgoing epoch's record.
    old_source = prior_epoch.get("source", "")
    if old_source and old_source != "fallback_no_fence":
        old_raw = read_json_or_none(Path(old_source))
        if old_raw is not None:
            archive_entry = dict(old_raw)
            archive_entry["_archived_at"] = now.isoformat()
            archive_entry["_archived_from_path"] = old_source
            history_path = target_epoch_path.parent / "epoch_history.jsonl"
            append_jsonl_line(history_path, archive_entry)

    # 6. Write the new marker atomically -- the ONLY writer of this file.
    atomic_write_json(target_epoch_path, record)

    # 7. Bust the mtime cache so the next get_active_epoch() call picks up
    # the new marker immediately (same process, same run).
    get_active_epoch(force_reload=True)

    return record


def is_real_trade(row: dict) -> bool:
    """Shared fixture/TEST-row filter — the exclusion rule every ledger
    aggregator (reporting AND learning) should share instead of
    copy-pasting. True when the row is a genuine trade."""
    if "TEST" in str(row.get("symbol", "")).upper():
        return False
    try:
        entry = float(row.get("entry_price") or 0)
    except (ValueError, TypeError):
        entry = 0.0
    if entry in TEST_ENTRY_PRICES:
        return False
    return True
