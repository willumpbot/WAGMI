"""Append-only durable delivery log for ``TradeClosed`` events (Phase 0.4-B2).

WHY THIS EXISTS: today, if the process dies between "a close filled" and
"every god-block subscriber finished running," the close is either
silently lost (equity/ledger never see it) or -- on a naive restart replay
-- silently double-booked. This module is the write-ahead durability layer
that makes that window recoverable: every ``TradeClosed`` event is
appended, fsync'd, to ``data/close_outbox.jsonl`` BEFORE any subscriber
runs (see close_bus.py's ``publish()``), and each row tracks which
subscribers have successfully processed it (``applied_by``) so a boot-time
replay can deliver to exactly the subscribers that missed it -- no more,
no less.

DESIGN:
  - ``data/close_outbox.jsonl``: one JSON object per line, one line per
    ``append()`` call. Uses ``core.atomic_state.append_jsonl_line`` for the
    fsync'd-append durability guarantee (see that function's docstring).
    This file is APPEND-ONLY in normal operation; the only code that
    rewrites it wholesale is ``compact()``, via
    ``core.atomic_state.atomic_write_text`` (atomic replace).
  - ``data/close_outbox.acks.json``: a companion file, ``{event_id: [subscriber
    names]}``, written via ``core.atomic_state.atomic_write_json`` (atomic
    replace) on every ``ack()`` call. Chosen over appending ack records to
    the same JSONL (which would require replaying the whole file to fold
    acks before every ``unacked()`` query) because: (a) the ack set per
    event is small and bounded (number of subscribers, not number of
    closes), (b) atomic_write_json's whole-file replace is already
    crash-safe (readers never see a torn ack file), and (c) acks are
    idempotent (registering the same subscriber twice is a no-op), so a
    read-modify-write race between two ack() calls for DIFFERENT event_ids
    is naturally serialized by atomic_state's per-path lock and never loses
    data -- the worst case is two sequential atomic writes instead of one,
    never a lost or corrupted ack.
  - ``sim=True`` events are NEVER written (guard inside ``append()``) --
    backtest/replay closes must never pollute the live outbox.
  - The JSONL loader tolerates a torn last line (crash mid-append): it is
    logged and skipped, never raised.

NOT YET WIRED: nothing calls ``append()``/``ack()``/``unacked()`` from any
live code path. This module is built + unit-tested in isolation (Phase B);
the god-block remains the authoritative live close path until Phase D/E.
"""

from __future__ import annotations

import json
import logging
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from core import paths
from core.atomic_state import (
    append_jsonl_line,
    atomic_write_json,
    atomic_write_text,
    read_json_or_none,
)
from core.close_pipeline.trade_closed import LegKind, TradeClosed

logger = logging.getLogger("bot.core.close_pipeline.close_outbox")

PathLike = Union[str, Path]

# Every field name TradeClosed accepts, used to filter stray/foreign keys
# (e.g. "applied_by") out of a JSONL row before reconstructing the event.
_FIELD_NAMES = {f.name for f in dataclass_fields(TradeClosed)}


def outbox_path() -> Path:
    """Canonical outbox location: DATA_DIR/close_outbox.jsonl."""
    return paths.close_outbox_path()


def acks_path(*, path: Optional[PathLike] = None) -> Path:
    """Companion ack-set file, sibling of the outbox: replaces the
    ``.jsonl`` suffix with ``.acks.json`` (e.g. ``close_outbox.jsonl`` ->
    ``close_outbox.acks.json``)."""
    base = Path(path) if path is not None else outbox_path()
    return base.with_name(base.stem + ".acks.json")


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------
def _row_from_event(event: TradeClosed) -> Dict[str, Any]:
    row: Dict[str, Any] = {f.name: getattr(event, f.name) for f in dataclass_fields(event)}
    leg = row.get("leg_kind")
    row["leg_kind"] = leg.value if isinstance(leg, LegKind) else leg
    # Ack-set lives in the companion acks.json (see module docstring), but
    # stamping an empty list here documents the row's shape / makes a raw
    # `cat close_outbox.jsonl` line self-explanatory even before any ack.
    row["applied_by"] = []
    return row


def append(event: TradeClosed, *, path: Optional[PathLike] = None) -> None:
    """Durably append one row for ``event``. A row is conceptually written
    only after a real fill (or `no_exchange`/paper booking) -- this
    function itself does not gate on that; the CALLER decides WHEN to
    append (close_bus.publish() calls this immediately before running
    subscribers). ``sim=True`` events are never written -- backtest/replay
    must never write to the live outbox (bus=None is the documented
    contract for backtest call sites; this guard is defense in depth for
    any code that constructs a bus directly in a sim context anyway)."""
    if event.sim:
        logger.debug(
            "close_outbox.append: refusing sim=True event %s (position_id=%s)",
            event.event_id, event.position_id,
        )
        return
    target = Path(path) if path is not None else outbox_path()
    append_jsonl_line(target, _row_from_event(event))


# ---------------------------------------------------------------------------
# Load / reconstruct
# ---------------------------------------------------------------------------
def _read_rows(target: Path) -> List[Dict[str, Any]]:
    """Read + parse JSONL rows, tolerating a torn last line (crash
    mid-append) -- logged and skipped, never raised."""
    if not target.exists():
        return []
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("close_outbox: failed to read %s: %s", target, e)
        return []

    lines = raw.splitlines()
    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError) as e:
            is_last = (i == len(lines) - 1)
            logger.warning(
                "close_outbox: skipping %s line in %s: %s",
                "torn last" if is_last else "malformed", target, e,
            )
            continue
        if not isinstance(row, dict) or not row.get("position_id") or not row.get("event_id"):
            logger.warning("close_outbox: skipping malformed row (missing keys) in %s", target)
            continue
        rows.append(row)
    return rows


def load_all(*, path: Optional[PathLike] = None) -> List[TradeClosed]:
    """Reload every row as a reconstructed (frozen) ``TradeClosed``. Rows
    that fail to reconstruct (unexpected shape) are logged and skipped
    rather than raising -- a boot-time reader must survive a partially
    corrupt outbox."""
    target = Path(path) if path is not None else outbox_path()
    events: List[TradeClosed] = []
    for row in _read_rows(target):
        payload = {k: v for k, v in row.items() if k in _FIELD_NAMES}
        try:
            events.append(TradeClosed(**payload))
        except Exception as e:
            logger.warning("close_outbox: skipping row that failed to reconstruct TradeClosed: %s", e)
    return events


# ---------------------------------------------------------------------------
# Acks
# ---------------------------------------------------------------------------
def load_acks(*, path: Optional[PathLike] = None) -> Dict[str, List[str]]:
    """Return the full ``{event_id: [subscriber names]}`` ack map."""
    return read_json_or_none(acks_path(path=path)) or {}


def ack(event_id: str, subscriber_name: str, *, path: Optional[PathLike] = None) -> None:
    """Record that ``subscriber_name`` successfully processed ``event_id``.
    Idempotent -- acking the same (event_id, subscriber_name) pair twice is
    a no-op on the second call. Crash-safe: the whole ack map is rewritten
    via ``atomic_write_json`` (atomic replace), so a crash mid-write leaves
    either the old or the new complete map, never a torn one."""
    target = acks_path(path=path)
    data = read_json_or_none(target) or {}
    subs = list(data.get(event_id, []))
    if subscriber_name not in subs:
        subs.append(subscriber_name)
    data[event_id] = subs
    atomic_write_json(target, data)


def unacked(
    required_subscribers: Iterable[str],
    *,
    max_age_s: Optional[float] = None,
    path: Optional[PathLike] = None,
) -> List[TradeClosed]:
    """Return every event NOT yet acked by ALL of ``required_subscribers``
    (used for boot-time replay). ``max_age_s``, if given, additionally
    drops events older than that (by ``close_time`` falling back to
    ``open_time``) -- useful for a bounded replay window; omit for "replay
    everything unacked regardless of age"."""
    target = Path(path) if path is not None else outbox_path()
    ack_data = load_acks(path=target)
    required = set(required_subscribers)
    now = datetime.now(timezone.utc)

    result: List[TradeClosed] = []
    for event in load_all(path=target):
        acked = set(ack_data.get(event.event_id, []))
        if required and required <= acked:
            continue
        if max_age_s is not None:
            ts_raw = event.close_time or event.open_time
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = (now - ts).total_seconds()
                    if age > max_age_s:
                        continue
                except (ValueError, TypeError):
                    pass
        result.append(event)
    return result


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
def compact(
    *,
    older_than_days: float = 7.0,
    required_subscribers: Optional[Iterable[str]] = None,
    path: Optional[PathLike] = None,
    now: Optional[datetime] = None,
) -> int:
    """Drop fully-acked, old rows via an atomic rewrite of the outbox (and
    the ack map, pruning entries for dropped events so it doesn't grow
    unbounded).

    ``required_subscribers``: the set of subscriber names that must ALL
    have acked for a row to count as "fully acked." The spec's own
    signature (``compact(older_than_days=7)``) does not thread a required
    set through, so this is a documented design decision: when omitted
    (``None``), a row counts as fully-acked if it has been acked by AT
    LEAST ONE subscriber. This permissive default is only appropriate for
    a caller (or test) that doesn't care about partial-ack correctness;
    real production wiring (once close_bus's mandatory-tier subscriber
    list exists at a boot script) should always pass the actual required
    set explicitly.

    Returns the number of rows dropped.
    """
    target = Path(path) if path is not None else outbox_path()
    if not target.exists():
        return 0

    acks_target = acks_path(path=target)
    ack_data = load_acks(path=target)
    rows = _read_rows(target)

    now = now or datetime.now(timezone.utc)
    cutoff_ts = now.timestamp() - older_than_days * 86400.0
    required = set(required_subscribers) if required_subscribers is not None else None

    kept_rows: List[Dict[str, Any]] = []
    dropped = 0
    for row in rows:
        event_id = row.get("event_id")
        acked = set(ack_data.get(event_id, []))
        is_fully_acked = (required <= acked) if required is not None else bool(acked)

        ts_raw = row.get("close_time") or row.get("open_time")
        is_old = False
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
                is_old = ts < cutoff_ts
            except (ValueError, TypeError):
                is_old = False

        if is_fully_acked and is_old:
            dropped += 1
            ack_data.pop(event_id, None)
            continue
        kept_rows.append(row)

    new_content = "\n".join(json.dumps(r, default=str) for r in kept_rows)
    if kept_rows:
        new_content += "\n"
    atomic_write_text(target, new_content)
    atomic_write_json(acks_target, ack_data)
    return dropped
