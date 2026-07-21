"""Write-ahead journal for position lifecycle + startup reconcile.

WHY THIS EXISTS (Phase 0.3b, 2026-07-21 -- follows Phase 0.1 core/paths.py,
Phase 0.2 core/provenance.py, Phase 0.3a core/atomic_state.py):
  Today a position has no durable record of its own lifecycle intent. Two
  failure classes motivate this module:

  1. NO EXACTLY-ONCE RECOVERY: if the process crashes AFTER a position is
     marked CLOSED in memory / persisted, but BEFORE the ledger row + equity
     credit are written, that close is permanently lost -- equity and ledger
     silently diverge. Conversely a re-fire on restart can double-book the
     same close. This is behind the historical "phantom rows / -$370
     double-count" and "silent drop" incidents.
  2. NO POSITION IDENTITY: dedup previously relied on fragile value-tuples
     (symbol, entry, exit, pnl) which false-positive on a genuine second
     identical trade and false-negative on re-fires. See execution/
     position_manager.py's ``Position.position_id`` (Phase 0.3b) for the
     identity primitive this journal keys on.

  This module is the write-ahead log: every position lifecycle transition
  (OPEN -> CLOSING -> CLOSED_BOOKED) is appended here BEFORE the
  corresponding real action commits, so a crash at any point leaves enough
  evidence on disk to detect -- on the next boot -- exactly which positions
  were left in an inconsistent state.

SCOPE (Phase 0.3b only -- deliberately narrow):
  This module DETECTS and REPORTS inconsistencies via ``startup_reconcile``.
  It does NOT re-book anything itself -- the actual re-book/replay wiring
  belongs to Phase 0.4's close-handler rebuild (the ~40-subscriber "god
  block" in multi_strategy_main.py). Keeping this module detect-only keeps
  its blast radius small: it can be wired into the three call sites
  (journal_open / journal_closing / journal_booked) without touching a
  single one of those 40 subscribers.

LEDGER IS TRUTH: ``startup_reconcile`` never trusts the journal over the
ledger. A position_id already present in ``ledger_position_ids`` is NEVER
reported as needing a re-book, even if the journal's last known phase for
that position is CLOSING (mid-flight) -- the ledger write already happened,
the journal just never heard about it (e.g. journal_booked() itself failed
non-fatally, or the process died between the ledger write and the
journal_booked() call). Re-booking a position_id already in the ledger
would double-count -- exactly the "-$370 double-count" incident class this
module exists to prevent, not reproduce.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from core import paths
from core.atomic_state import atomic_write_text

logger = logging.getLogger("bot.core.position_journal")

PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# Phase vocabulary
# ---------------------------------------------------------------------------
OPEN = "OPEN"
CLOSING = "CLOSING"
CLOSED_BOOKED = "CLOSED_BOOKED"

_PHASES = (OPEN, CLOSING, CLOSED_BOOKED)


def journal_path() -> Path:
    """Canonical journal location: DATA_DIR/position_journal.jsonl."""
    return paths.position_journal_path()


# ---------------------------------------------------------------------------
# Append primitives
# ---------------------------------------------------------------------------
def _append_event(
    position_id: str,
    phase: str,
    *,
    symbol: str = "",
    meta: Optional[Dict[str, Any]] = None,
    path: Optional[PathLike] = None,
) -> None:
    """Append one journal line. Never raises out of this module's own
    control -- callers (journal_open/journal_closing/journal_booked) are
    the ones responsible for try/except at the wiring call sites, per the
    "journaling is a safety net, not a gate" rule -- but the write itself
    still needs to surface I/O errors to the caller so a systemic failure
    (disk full, permissions) is visible in logs rather than silently
    swallowed here too."""
    target = Path(path) if path is not None else journal_path()
    entry: Dict[str, Any] = {
        "position_id": position_id,
        "phase": phase,
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
    }
    if meta:
        entry["meta"] = meta
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def journal_open(
    position_id: str,
    meta: Optional[Dict[str, Any]] = None,
    *,
    symbol: str = "",
    path: Optional[PathLike] = None,
) -> None:
    """Append an OPEN event. Call synchronously at the position-open site,
    right after the position is created + persisted -- this closes the
    "crash-after-open" window: on restart we know a position existed even
    if position_state.json itself never made it to disk."""
    _append_event(position_id, OPEN, symbol=symbol, meta=meta, path=path)


def journal_closing(
    position_id: str,
    close_meta: Optional[Dict[str, Any]] = None,
    *,
    symbol: str = "",
    path: Optional[PathLike] = None,
) -> None:
    """Append a CLOSING event -- intent to close, written BEFORE the ledger
    row / equity credit are booked."""
    _append_event(position_id, CLOSING, symbol=symbol, meta=close_meta, path=path)


def journal_booked(
    position_id: str,
    *,
    symbol: str = "",
    path: Optional[PathLike] = None,
) -> None:
    """Append a CLOSED_BOOKED event -- written AFTER the ledger row +
    equity credit succeed. Once this lands, the position's lifecycle is
    fully accounted for and startup_reconcile will never flag it again."""
    _append_event(position_id, CLOSED_BOOKED, symbol=symbol, path=path)


# ---------------------------------------------------------------------------
# Startup reconcile
# ---------------------------------------------------------------------------
@dataclass
class ReconcileReport:
    """Structured result of startup_reconcile().

    Attributes:
        unbooked: list of {"position_id", "symbol", "meta", ...} dicts for
            positions whose last known journal phase is CLOSING (intent to
            close was recorded) but which are NOT present in the ledger --
            i.e. the process crashed between "decided to close" and "ledger
            row written". These need a re-book by the Phase 0.4 outbox/
            replay wiring; this module only detects and reports them.
        duplicates_skipped: position_ids whose journal/ledger state shows
            the close was already accounted for (CLOSED_BOOKED already seen,
            or already present in the ledger) -- explicitly NOT re-booked,
            per the ledger-is-truth rule.
        healthy: count of position_ids whose journal state is fully
            consistent (still open and tracked, or cleanly closed+booked)
            and required no action.
        torn_lines_skipped: number of journal lines that failed to parse
            (e.g. a torn last line from a crash mid-append) -- skipped, not
            fatal.
        total_events: total journal lines successfully parsed.
    """

    unbooked: List[Dict[str, Any]] = field(default_factory=list)
    duplicates_skipped: List[str] = field(default_factory=list)
    healthy: int = 0
    torn_lines_skipped: int = 0
    total_events: int = 0


def _read_events(target: Path) -> List[Dict[str, Any]]:
    """Read + parse journal lines, skipping (not raising on) any line that
    fails to parse -- a torn last line from a crash mid-append must never
    make reconcile itself unusable."""
    if not target.exists():
        return []
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("position_journal: failed to read %s: %s", target, e)
        return []

    parsed: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError) as e:
            logger.warning(
                "position_journal: skipping unparseable line in %s: %s", target, e
            )
            parsed.append({"__torn__": True})
            continue
        if not isinstance(event, dict) or not event.get("position_id") or event.get("phase") not in _PHASES:
            logger.warning(
                "position_journal: skipping malformed event in %s: %r", target, event
            )
            parsed.append({"__torn__": True})
            continue
        parsed.append(event)
    return parsed


def startup_reconcile(
    ledger_position_ids: Set[str],
    open_position_ids: Set[str],
    *,
    path: Optional[PathLike] = None,
) -> ReconcileReport:
    """Detect (never re-book) exactly-once recovery candidates.

    Args:
        ledger_position_ids: the set of position_ids already present as a
            recorded row in trade_ledger.csv -- LEDGER IS TRUTH, see module
            docstring.
        open_position_ids: the set of position_ids the in-memory/persisted
            PositionManager currently considers open (not yet closed).
        path: override the journal file (tests).

    Returns:
        A ReconcileReport. The boot sequence is responsible for acting on
        ``report.unbooked`` (Phase 0.4); this function only detects.
    """
    target = Path(path) if path is not None else journal_path()
    report = ReconcileReport()

    events = _read_events(target)

    latest_phase: Dict[str, str] = {}
    latest_event: Dict[str, Dict[str, Any]] = {}
    booked_count: Dict[str, int] = {}

    for event in events:
        if event.get("__torn__"):
            report.torn_lines_skipped += 1
            continue
        report.total_events += 1
        pid = event["position_id"]
        phase = event["phase"]
        latest_phase[pid] = phase
        latest_event[pid] = event
        if phase == CLOSED_BOOKED:
            booked_count[pid] = booked_count.get(pid, 0) + 1

    for pid, phase in latest_phase.items():
        in_ledger = pid in ledger_position_ids
        ev = latest_event[pid]
        symbol = ev.get("symbol", "")

        if phase == CLOSED_BOOKED:
            # Already booked according to the journal itself, or the ledger
            # independently confirms it -- never re-book, just note it.
            if booked_count.get(pid, 0) > 1 or in_ledger:
                report.duplicates_skipped.append(pid)
            else:
                # Journal claims booked but the ledger (truth) disagrees --
                # do NOT trust the journal enough to re-book (that risks a
                # phantom row with no ledger corroboration); surface it as a
                # loud warning for manual investigation instead of silently
                # dropping it.
                logger.warning(
                    "position_journal: %s (%s) marked CLOSED_BOOKED in "
                    "journal but absent from ledger -- not re-booking "
                    "(ledger is truth); flag for manual review",
                    pid, symbol,
                )
                report.healthy += 1
        elif phase == CLOSING:
            if in_ledger:
                # Ledger already has the row -- the CLOSING intent was
                # honored, journal_booked() just never landed (or hasn't
                # been read yet). Never re-book.
                report.duplicates_skipped.append(pid)
            else:
                # Crash between "decided to close" and "ledger row
                # written" -- the exact incident class this module exists
                # to make detectable.
                report.unbooked.append(dict(ev))
        else:  # OPEN, no later phase recorded
            if pid in open_position_ids or in_ledger:
                report.healthy += 1
            else:
                # Opened, but neither still open nor present in the ledger
                # anywhere we can see -- unaccounted for. Report it rather
                # than silently losing it.
                report.unbooked.append(dict(ev))

    return report


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
def compact(
    *,
    older_than_days: float = 7.0,
    path: Optional[PathLike] = None,
    now: Optional[datetime] = None,
) -> int:
    """Drop fully-booked (CLOSED_BOOKED, and only CLOSED_BOOKED) position
    lifecycles whose last event is older than ``older_than_days``. Rewrites
    the journal atomically via core.atomic_state.atomic_write_text.

    Positions that are not cleanly terminal (still OPEN, or CLOSING with no
    matching CLOSED_BOOKED) are always kept regardless of age -- they may
    still be needed by a future startup_reconcile() call.

    Returns the number of position_ids dropped.
    """
    target = Path(path) if path is not None else journal_path()
    if not target.exists():
        return 0

    now = now or datetime.now(timezone.utc)
    cutoff_ts = now.timestamp() - older_than_days * 86400.0

    events = _read_events(target)

    order: List[str] = []
    events_by_pid: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        if event.get("__torn__"):
            continue
        pid = event["position_id"]
        if pid not in events_by_pid:
            events_by_pid[pid] = []
            order.append(pid)
        events_by_pid[pid].append(event)

    dropped = 0
    kept_lines: List[str] = []
    for pid in order:
        evs = events_by_pid[pid]
        last = evs[-1]
        is_old = False
        ts_raw = last.get("ts")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
                is_old = ts < cutoff_ts
            except (ValueError, TypeError):
                is_old = False

        if last.get("phase") == CLOSED_BOOKED and is_old:
            dropped += 1
            continue

        for e in evs:
            kept_lines.append(json.dumps(e, default=str))

    new_content = ("\n".join(kept_lines) + "\n") if kept_lines else ""
    atomic_write_text(target, new_content)
    return dropped
