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

EXACTLY-ONCE SEAM (GENERALIZED): every ``dedupe=True`` subscriber (the
default -- see ``subscribe()``) must never re-apply its side effect for the
same ``position_id`` twice. This generalizes what used to be a T0-only
("mandatory equity/circuit-breaker") rule into the same guarantee for
EVERY tier: T1 persistence (ledger, trades.csv), T2 derived readers
(kelly, IC, weights, learning hooks), anything. This is the CloseBus
replacement for the old god-block's ``CLOSE_DEDUP_GUARD``, which only made
a duplicate close idempotent for ledger/IC/Kelly but left equity able to
double-count (the 12-phantom-rows/-$370 incident) -- here the SAME
mechanism covers every subscriber uniformly, so no side effect can be
missed from the guarantee by construction. A subscriber that must
legitimately run on every publish (e.g. a fire-and-forget alert/telemetry
sink where "ran twice" is harmless or even correct) opts out with
``dedupe=False``.

The applied-store is keyed by ``(subscriber_name, position_id, leg_kind)``
-- "did THIS subscriber already apply for THIS position's THIS leg" --
not by ``(subscriber_name, position_id)`` alone. D1 FIX: a bare
``(subscriber_name, position_id)`` key cannot distinguish a PARTIAL
(e.g. TP1) publish from the position's later TERMINAL publish -- both
share the same ``position_id`` -- so a PARTIAL publish would mark
``("equity", pid)`` applied and the subsequent TERMINAL publish for the
SAME position_id would then be silently skipped (terminal equity delta,
ledger row, and trade_logger row all dropped -- a money-accounting bug,
not a duplicate). Including ``leg_kind`` (``TradeClosed.leg_kind.value``,
"PARTIAL" or "TERMINAL") in the key means a PARTIAL and a TERMINAL of the
SAME position are distinct entries -- both run exactly once -- while an
EXACT duplicate re-publish of the same leg (same position_id AND same
leg_kind) is still correctly deduped. Different subscribers each need
their own independent exactly-once record (a duplicate publish that
arrives while one subscriber's first attempt raised must still retry
only that one subscriber, not skip the others that already succeeded,
and must not re-run the ones that already succeeded).

This is deliberately a DIFFERENT mechanism from the outbox's ack-set
(``close_outbox.ack``, keyed by ``(event_id, subscriber_name)``): the
ack-set answers "did subscriber X process THIS SPECIFIC EVENT" and drives
boot-time REPLAY recovery (an event can be re-delivered to subscribers
that never acked it, regardless of position_id history); the applied-store
answers "did subscriber X already apply ITS SIDE EFFECT for this
POSITION" and drives duplicate-publish idempotence, since a position may
be re-published (same or different event_id) without that meaning the
side effect should run again. Both are consulted together in
``publish()``/``replay_unacked()``: the ack-set decides "must I retry this
subscriber for this event," the applied-store decides "may I actually run
it, or has it already had its effect."

The spec's end-state (R1) is for the applied-store to live INSIDE the
equity state file itself (execution/risk.py's risk_equity_state.json),
written in the SAME atomic write as the equity mutation, so the two can
never diverge. That file does not yet expose this seam, so Phase B
introduces ``AppliedStore`` -- a small injectable interface with an
in-memory default and an optional file-backed implementation
(``atomic_write_json`` to a JSON file keyed by ``subscriber_name`` ->
``position_id`` -> ``True``) -- fully unit-testable today, and swapped for
a real equity-file-backed implementation with ZERO change to ``CloseBus``
once that wiring lands (a later phase, not this one).

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
    dedupe: bool
    order: int  # insertion sequence -- deterministic same-tier ordering


# ---------------------------------------------------------------------------
# Exactly-once applied-store seam (see module docstring)
# ---------------------------------------------------------------------------
class AppliedStore:
    """Interface for the exactly-once applied-``(subscriber_name,
    position_id, leg_kind)`` set consulted by every ``dedupe=True``
    subscriber (the default -- see ``subscribe()``). ``leg_kind`` is
    ``TradeClosed.leg_kind.value`` ("PARTIAL" or "TERMINAL") -- see module
    docstring's D1 FIX note for why the key must include it (a PARTIAL and
    a TERMINAL of the same position_id are distinct events that must BOTH
    run). See module docstring for the seam this exists to provide
    (future: backed by the equity state file itself) and for how this
    differs from the outbox's per-event ack-set."""

    def is_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> bool:
        raise NotImplementedError

    def mark_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> None:
        raise NotImplementedError


class InMemoryAppliedStore(AppliedStore):
    """Default applied-store: an in-memory set of ``(subscriber_name,
    position_id, leg_kind)`` triples, thread-safe. Sufficient for a single
    process's lifetime; does NOT survive a restart (a restart should rely
    on ``replay_unacked`` + the outbox's own ack state instead, not on
    this set having remembered anything)."""

    def __init__(self) -> None:
        self._applied: Set[Tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    def is_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> bool:
        with self._lock:
            return (subscriber_name, position_id, leg_kind) in self._applied

    def mark_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> None:
        with self._lock:
            self._applied.add((subscriber_name, position_id, leg_kind))


class FileBackedAppliedStore(AppliedStore):
    """Optional file-backed applied-store: ``{subscriber_name:
    {position_id: {leg_kind: true}}}`` written via ``atomic_write_json``
    (atomic replace) on every ``mark_applied``. NOT wired to the real
    equity state file yet -- that is the later-phase seam described in the
    module docstring (R1). Provided so tests/boot code can exercise
    crash-persistence of the applied-set today without waiting for that
    wiring."""

    def __init__(self, path: PathLike) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, Dict[str, Dict[str, bool]]]:
        return read_json_or_none(self._path) or {}

    def is_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> bool:
        return bool(self._load().get(subscriber_name, {}).get(position_id, {}).get(leg_kind))

    def mark_applied(self, subscriber_name: str, position_id: str, leg_kind: str) -> None:
        with self._lock:
            data = self._load()
            subs = data.setdefault(subscriber_name, {})
            legs = subs.setdefault(position_id, {})
            legs[leg_kind] = True
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
        dedupe: bool = True,
    ) -> None:
        """Register ``fn`` for delivery. ``dedupe`` (default ``True``) --
        a position closes once, so by default every subscriber's side
        effect fires AT MOST ONCE per ``position_id`` even if the same
        close is ``publish()``-ed more than once (see module docstring's
        EXACTLY-ONCE SEAM). Pass ``dedupe=False`` only for a subscriber
        that must legitimately re-run on every publish regardless of
        position_id history (e.g. a fire-and-forget alert/telemetry sink
        where re-running is harmless) -- the default keeps everything else
        safe without each call site having to reason about it."""
        with self._lock:
            self._seq += 1
            self._subs.append(
                Subscription(
                    name=name, fn=fn, tier=Tier(tier), kind=tuple(kind),
                    required=required, replay=replay, dedupe=dedupe, order=self._seq,
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

        for sub in self._ordered_subs():
            if event_kind not in sub.kind:
                report.skipped.append(sub.name)
                continue
            if sub.dedupe and self._applied_store.is_applied(sub.name, event.position_id, event.leg_kind.value):
                # Exactly-once (generalized, D1 FIX): THIS subscriber
                # already applied its side effect for THIS position_id's
                # THIS leg (PARTIAL vs TERMINAL) -- a duplicate publish()
                # (same position_id AND same leg_kind, same or different
                # event_id) must not re-run it. A PARTIAL publish and the
                # later TERMINAL publish for the SAME position_id are
                # DIFFERENT leg_kind values, so they are never confused for
                # each other here -- both run. Checked/marked
                # per-(subscriber, position_id, leg_kind), not once for the
                # whole event, so a subscriber that failed on a previous
                # publish is still retried here while its siblings that
                # already succeeded are correctly skipped.
                report.skipped.append(sub.name)
                continue
            try:
                sub.fn(event)
                report.delivered.append(sub.name)
                # Ack + mark-applied ONLY on successful delivery -- this is
                # what makes the event recoverable via replay_unacked() if
                # this subscriber (or a sibling) fails: a raised subscriber
                # must never be recorded as "processed" or "applied", so a
                # later replay/publish keeps retrying exactly it.
                if sub.required:
                    close_outbox.ack(event.event_id, sub.name, path=self._outbox_path)
                if sub.dedupe:
                    self._applied_store.mark_applied(sub.name, event.position_id, event.leg_kind.value)
            except Exception as e:  # noqa: BLE001 - isolation is the point
                logger.exception(
                    "close_bus: subscriber %r raised on event %s (position_id=%s)",
                    sub.name, event.event_id, event.position_id,
                )
                report.failed.append((sub.name, repr(e)))
                _record_subscriber_failure(sub.name)

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

            for sub in self._ordered_subs():
                if not sub.replay:
                    continue  # LLM/alert/telemetry: never replayed at boot
                if event_kind not in sub.kind:
                    continue
                if sub.name in acked:
                    continue  # this subscriber already processed this event
                if sub.dedupe and self._applied_store.is_applied(sub.name, event.position_id, event.leg_kind.value):
                    # Belt & suspenders (D1 FIX: leg-aware): the
                    # applied-store is the source of truth for "already had
                    # the side effect for this leg," even if the ack is
                    # (for whatever reason) missing -- e.g. applied via a
                    # different event_id for the same position AND leg_kind.
                    # Never re-run the subscriber; if it's required,
                    # converge the ack-set too so this doesn't keep showing
                    # up as unacked on every future replay.
                    if sub.required:
                        close_outbox.ack(event.event_id, sub.name, path=self._outbox_path)
                        acked.add(sub.name)
                    continue
                try:
                    sub.fn(event)
                    delivered_count += 1
                    if sub.required:
                        close_outbox.ack(event.event_id, sub.name, path=self._outbox_path)
                        acked.add(sub.name)
                    if sub.dedupe:
                        self._applied_store.mark_applied(sub.name, event.position_id, event.leg_kind.value)
                except Exception:
                    logger.exception(
                        "close_bus.replay_unacked: subscriber %r raised replaying event %s",
                        sub.name, event.event_id,
                    )
                    _record_subscriber_failure(sub.name)
                    # Do NOT ack, do NOT mark_applied -- a future
                    # replay_unacked() call must keep retrying exactly this
                    # subscriber (same rule as publish()).

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
