"""Tiered dispatcher for ``TradeClosed`` events (Phase 0.4-B3).

ORDERING TIERS (spec04.md section (2), close_bus invariants). ``publish()``
delivers strictly in tier order; within a tier, subscribers run in
deterministic SUBSCRIBE order (insertion order), never re-sorted:

  T0  core-accounting     equity -> circuit-breaker -> log_trade
                           (sequential, MANDATORY -- must succeed for the
                           bus to consider the close "applied")
  T1  persistence          ledger, trades.csv, trade_logger
  T2  derived readers      ordering-sensitive pairs: auto-demotion AFTER
                           trades.csv; deep-memory BEFORE prompt-cache
                           invalidation; fact-grade BEFORE coordinator
                           lesson (subscribe() call order within T2 encodes
                           this -- the bus enforces "same order every time,"
                           the CALLER is responsible for subscribing in the
                           correct relative order for these documented pairs)
  T3  fire-and-forget      alerts, telemetry, LLM subscribers -- never
                           replayed at boot (see ``replay`` flag)

KIND FILTER: reuses ``core.close_types.CloseKind`` (FULL / PARTIAL) as the
public vocabulary for "does this subscriber care about partial legs, full
closes, or both" -- matching the literal spec text
``kind=(FULL, PARTIAL)``. ``TradeClosed.leg_kind`` uses its own
TERMINAL/PARTIAL vocabulary (see trade_closed.py's LegKind) because a
TERMINAL close and a "FULL" close type are the same concept described from
two different modules; ``_LEG_TO_KIND`` below is the one place that maps
between them so callers of ``subscribe()`` never have to think about it.

PER-SUBSCRIBER ISOLATION: one subscriber raising an exception is caught,
logged, recorded in the ``DeliveryReport``, and counted in a telemetry
counter -- it NEVER stops the remaining subscribers (including the rest of
its own tier) from running.

EXACTLY-ONCE SEAM: mandatory T0 subscribers (equity/circuit-breaker) must
never re-apply for the same ``position_id`` twice. The spec's end-state
(R1) is for this applied-set to live INSIDE the equity state file itself
(execution/risk.py's risk_equity_state.json), written in the SAME atomic
write as the equity mutation, so the two can never diverge. That file does
not yet expose this seam, so Phase B introduces ``AppliedStore`` -- a small
injectable interface with an in-memory default and an optional
file-backed implementation (``atomic_write_json`` to a JSON file keyed by
position_id) -- fully unit-testable today, and swapped for a real
equity-file-backed implementation with ZERO change to ``CloseBus`` once
that wiring lands (a later phase, not this one).

REPLAY CLASSIFICATION: ``replay=True`` (default) marks a subscriber as
"must be caught up on boot" -- required T0/T1/T2 subscribers. ``replay=False``
marks a subscriber as "never replayed" -- LLM/alert/telemetry (T3)
subscribers, since replaying a boot-time backlog through an LLM call or an
alert channel would be wasteful/spammy and is explicitly forbidden by
spec04.md T-R14 ("boot with 10-event backlog: 0 LLM calls, 0 alerts").

DURABILITY-FIRST: ``publish()`` appends to the outbox BEFORE running any
subscriber (see ``close_outbox.append`` call at the top of ``publish``),
so a crash between "fill happened" and "subscribers ran" always leaves a
durable, replayable row -- the exact guarantee ``replay_unacked`` depends
on.

NOT YET WIRED: this module is built + unit-tested in isolation (Phase B).
Nothing here is imported/called by any live code path; the god-block in
multi_strategy_main.py remains the authoritative live close path until
Phase D/E. ``bus=None`` is the documented contract for backtest call sites
(this module intentionally does NOT provide a special "null bus" class --
callers simply skip the publish call when ``bus is None``; see
``maybe_publish`` below for optional convenience sugar).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from core.atomic_state import atomic_write_json, read_json_or_none
from core.close_pipeline import close_outbox
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_bus")

PathLike = Union[str, Path]


class Tier(IntEnum):
    """Strict publish ordering -- lower value runs first. See module
    docstring for what belongs in each tier."""

    T0_CORE_ACCOUNTING = 0
    T1_PERSISTENCE = 1
    T2_DERIVED_READERS = 2
    T3_FIRE_AND_FORGET = 3


# Maps TradeClosed.leg_kind (TERMINAL/PARTIAL) onto the public subscribe()
# kind-filter vocabulary (FULL/PARTIAL, reused from core.close_types).
_LEG_TO_KIND: Dict[LegKind, CloseKind] = {
    LegKind.TERMINAL: CloseKind.FULL,
    LegKind.PARTIAL: CloseKind.PARTIAL,
}


def _leg_as_kind(event: TradeClosed) -> CloseKind:
    leg = event.leg_kind if isinstance(event.leg_kind, LegKind) else LegKind(event.leg_kind)
    return _LEG_TO_KIND[leg]


@dataclass
class DeliveryReport:
    """Result of one ``publish()`` (or one event's worth of
    ``replay_unacked``) call."""

    event_id: str
    delivered: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


@dataclass
class Subscription:
    name: str
    fn: Callable[[TradeClosed], None]
    tier: Tier
    kind: Tuple[CloseKind, ...]
    required: bool
    replay: bool
    order: int  # insertion sequence -- deterministic same-tier ordering


# ---------------------------------------------------------------------------
# Exactly-once applied-store seam (see module docstring)
# ---------------------------------------------------------------------------
class AppliedStore:
    """Interface for the exactly-once applied-``position_id`` set consulted
    by mandatory T0 subscribers. See module docstring for the seam this
    exists to provide (future: backed by the equity state file itself)."""

    def is_applied(self, position_id: str) -> bool:
        raise NotImplementedError

    def mark_applied(self, position_id: str) -> None:
        raise NotImplementedError


class InMemoryAppliedStore(AppliedStore):
    """Default applied-store: an in-memory set, thread-safe. Sufficient for
    a single process's lifetime; does NOT survive a restart (a restart
    should rely on ``replay_unacked`` + the outbox's own ack state instead,
    not on this set having remembered anything)."""

    def __init__(self) -> None:
        self._applied: Set[str] = set()
        self._lock = threading.Lock()

    def is_applied(self, position_id: str) -> bool:
        with self._lock:
            return position_id in self._applied

    def mark_applied(self, position_id: str) -> None:
        with self._lock:
            self._applied.add(position_id)


class FileBackedAppliedStore(AppliedStore):
    """Optional file-backed applied-store: ``{position_id: true}`` written
    via ``atomic_write_json`` (atomic replace) on every ``mark_applied``.
    NOT wired to the real equity state file yet -- that is the later-phase
    seam described in the module docstring (R1). Provided so tests/boot
    code can exercise crash-persistence of the applied-set today without
    waiting for that wiring."""

    def __init__(self, path: PathLike) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, bool]:
        return read_json_or_none(self._path) or {}

    def is_applied(self, position_id: str) -> bool:
        return bool(self._load().get(position_id))

    def mark_applied(self, position_id: str) -> None:
        with self._lock:
            data = self._load()
            data[position_id] = True
            atomic_write_json(self._path, data)


# ---------------------------------------------------------------------------
# Telemetry: per-subscriber failure counters (placeholder counter -- no
# existing telemetry module was specified to reuse; this is intentionally
# minimal and self-contained so it is trivially unit-testable).
# ---------------------------------------------------------------------------
_failure_counts: Dict[str, int] = {}
_failure_counts_lock = threading.Lock()


def _record_subscriber_failure(name: str) -> None:
    with _failure_counts_lock:
        _failure_counts[name] = _failure_counts.get(name, 0) + 1


def subscriber_failure_count(name: str) -> int:
    """Number of times ``name`` has raised across all CloseBus instances in
    this process (module-level counter -- see class docstring note)."""
    with _failure_counts_lock:
        return _failure_counts.get(name, 0)


# ---------------------------------------------------------------------------
# CloseBus
# ---------------------------------------------------------------------------
class CloseBus:
    """The dispatcher. See module docstring for tiering, isolation,
    exactly-once, and replay-classification invariants."""

    def __init__(
        self,
        *,
        applied_store: Optional[AppliedStore] = None,
        outbox_path: Optional[PathLike] = None,
    ) -> None:
        self._subs: List[Subscription] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._applied_store: AppliedStore = applied_store if applied_store is not None else InMemoryAppliedStore()
        self._outbox_path = outbox_path

    def subscribe(
        self,
        name: str,
        fn: Callable[[TradeClosed], None],
        *,
        tier: Tier,
        kind: Sequence[CloseKind] = (CloseKind.FULL, CloseKind.PARTIAL),
        required: bool = True,
        replay: bool = True,
    ) -> None:
        with self._lock:
            self._seq += 1
            self._subs.append(
                Subscription(
                    name=name, fn=fn, tier=Tier(tier), kind=tuple(kind),
                    required=required, replay=replay, order=self._seq,
                )
            )

    def _ordered_subs(self) -> List[Subscription]:
        return sorted(self._subs, key=lambda s: (int(s.tier), s.order))

    def publish(self, event: TradeClosed) -> DeliveryReport:
        """Deliver ``event`` to every matching subscriber in strict tier
        order. Writes to the outbox BEFORE running any subscriber
        (durability first) -- a crash between the outbox write and any
        subscriber running still leaves a durable, replayable row."""
        report = DeliveryReport(event_id=event.event_id)

        if event.sim:
            logger.warning(
                "close_bus.publish: refusing sim=True event %s (position_id=%s) "
                "-- backtest/replay must never publish to a live bus",
                event.event_id, event.position_id,
            )
            report.skipped.append("__sim_refused__")
            return report

        close_outbox.append(event, path=self._outbox_path)

        event_kind = _leg_as_kind(event)
        already_applied = self._applied_store.is_applied(event.position_id)

        for sub in self._ordered_subs():
            if event_kind not in sub.kind:
                report.skipped.append(sub.name)
                continue
            if sub.tier == Tier.T0_CORE_ACCOUNTING and sub.required and already_applied:
                # Exactly-once: a duplicate publish() for a position_id
                # already applied must not re-run mandatory T0 accounting.
                # Non-mandatory / non-T0 subscribers are NOT deduped here --
                # per spec, a no-dedup T3 (fire-and-forget) subscriber may
                # legitimately run again on a duplicate publish.
                report.skipped.append(sub.name)
                continue
            try:
                sub.fn(event)
                report.delivered.append(sub.name)
                if sub.required:
                    close_outbox.ack(event.event_id, sub.name, path=self._outbox_path)
            except Exception as e:  # noqa: BLE001 - isolation is the point
                logger.exception(
                    "close_bus: subscriber %r raised on event %s (position_id=%s)",
                    sub.name, event.event_id, event.position_id,
                )
                report.failed.append((sub.name, repr(e)))
                _record_subscriber_failure(sub.name)

        if not already_applied:
            self._applied_store.mark_applied(event.position_id)

        return report

    def replay_unacked(
        self,
        outbox: Any = None,
        *,
        required_subscribers: Optional[Iterable[str]] = None,
    ) -> int:
        """Boot-time replay: deliver every outbox event not yet acked to
        every subscriber that (a) is marked ``replay=True`` and (b) hasn't
        already acked that specific event. LLM/alert/telemetry
        (``replay=False``) subscribers are NEVER invoked here. ``outbox``
        is accepted for signature parity with the spec
        (``replay_unacked(outbox)``) but is currently unused -- this bus
        always reads through ``core.close_pipeline.close_outbox`` at
        ``self._outbox_path``; pass a distinct ``CloseBus(outbox_path=...)``
        per outbox instead of threading an outbox object through here.

        Returns the number of individual (event, subscriber) deliveries
        made.
        """
        required = (
            list(required_subscribers) if required_subscribers is not None
            else [s.name for s in self._subs if s.required]
        )
        events = close_outbox.unacked(required, path=self._outbox_path)
        ack_data = close_outbox.load_acks(path=self._outbox_path)

        delivered_count = 0
        for event in sorted(events, key=lambda e: (e.close_time or "", e.event_id)):
            event_kind = _leg_as_kind(event)
            acked = set(ack_data.get(event.event_id, []))
            already_applied = self._applied_store.is_applied(event.position_id)

            for sub in self._ordered_subs():
                if not sub.replay:
                    continue  # LLM/alert/telemetry: never replayed at boot
                if event_kind not in sub.kind:
                    continue
                if sub.name in acked:
                    continue  # this subscriber already processed this event
                if sub.tier == Tier.T0_CORE_ACCOUNTING and sub.required and already_applied:
                    continue
                try:
                    sub.fn(event)
                    delivered_count += 1
                    if sub.required:
                        close_outbox.ack(event.event_id, sub.name, path=self._outbox_path)
                        acked.add(sub.name)
                except Exception:
                    logger.exception(
                        "close_bus.replay_unacked: subscriber %r raised replaying event %s",
                        sub.name, event.event_id,
                    )
                    _record_subscriber_failure(sub.name)

            if not already_applied:
                self._applied_store.mark_applied(event.position_id)

        return delivered_count


def maybe_publish(bus: Optional[CloseBus], event: TradeClosed) -> Optional[DeliveryReport]:
    """Convenience sugar for future call sites: ``bus=None`` means
    "buffer/no-op" (the documented backtest contract) -- this just makes
    that contract a one-liner instead of every call site needing its own
    ``if bus is not None`` guard. Not required; `bus.publish(event)`
    directly is equally correct when the caller already knows ``bus`` is
    not None."""
    if bus is None:
        return None
    return bus.publish(event)
