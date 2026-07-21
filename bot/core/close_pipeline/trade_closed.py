"""The frozen ``TradeClosed`` event (Phase 0.4-B1).

WHAT THIS IS: the one authoritative, immutable snapshot of "a position (or
one leg of a position) just closed," built ONCE at emit time from a
``TradeEvent`` (execution/position_manager.py) plus -- optionally, where
``TradeEvent.metadata`` doesn't carry it -- the originating ``Position``
snapshot. Every close_bus subscriber reads exclusively off this frozen
object; nothing may reach back into ``pos_mgr.positions`` or ``risk_mgr``
after the event is constructed (spec04.md R5/R7/R10 -- the "leaked locals /
raced-close" bug class this exists to make structurally impossible).

DEDUP KEY: ``(position_id, event_id)``. ``position_id`` identifies the
position across its whole lifecycle (possibly several TradeClosed events:
one PARTIAL per leg, one TERMINAL). ``event_id`` identifies THIS specific
close event uniquely (fresh uuid4 per construction) so a genuine reopen/
reclose of the same position_id within the replay window is never confused
with a duplicate delivery of the same event.

IMMUTABILITY: ``frozen=True``. Mutable fields (``entry_reasons``,
``trade_profile``, ``state_path``) are deep-copied in ``__post_init__`` so
that even a caller who mutates the dict/list they originally passed in can
never retroactively change what a subscriber already read.

TOTAL_PNL: sourced ONLY from ``event.metadata["total_pnl"]`` (falling back
to ``position.realized_pnl`` if a position snapshot is supplied and the
metadata key is absent) -- never from ``event.pnl``, which is a PER-LEG
delta, not the position's authoritative cumulative net pnl. See
position_manager.py's PNL_SEMANTICS_FIX comments around the TP1/final-close
TradeEvent construction sites for the exact incident class this guards
(summing ``event.pnl`` across a TP1 leg + the terminal close event used to
double count the TP1 leg's contribution).

FIELDS TRADE_CLOSED CANNOT SOURCE FROM ``TradeEvent`` ALONE (documented,
not silently defaulted): ``close_volatility`` (computed as a bare local
`_close_vol` inside the multi_strategy_main.py god-block at close time --
never attached to the Position or TradeEvent; see spec04.md's note on the
`'_close_vol' in dir()` bug), ``compound_mult`` (an ENTRY-time value popped
from ``self._compound_mult_cache`` and written straight into the entry-time
ledger row -- never carried onto the Position or the close TradeEvent), and
``candidate_ref`` (a rotation/entry-candidate correlation id that does not
exist anywhere in the codebase yet -- reserved for a later phase, e.g. the
close_with_execution helper or rotation_manager passing it in explicitly).
All three are accepted as optional override kwargs on
``from_trade_event`` so a FUTURE caller that DOES have this context
(Phase C/D helper, once built) can populate them; today they default to
``None``.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:  # pragma: no cover - import-cycle avoidance only
    from execution.position_manager import Position, TradeEvent


class LegKind(str, Enum):
    """Whether this TradeClosed event terminates the position's lifecycle
    (TERMINAL, derived from ``TradeEvent.is_position_close is True``) or is
    one partial leg while the position stays open (PARTIAL, derived from
    ``is_position_close is False``). This is the ONLY boolean/whitelist this
    module trusts for that distinction -- see position_manager.py's
    TRADE_SUMMARY_PER_POSITION_FIX comment: ``is_position_close`` is set
    inside ``_close_position()`` regardless of which reason string
    (``action``) triggered it, so it covers every current AND future close
    reason with no hand-maintained list."""

    PARTIAL = "PARTIAL"
    TERMINAL = "TERMINAL"


def _as_dict(value: Any) -> Dict[str, Any]:
    """Best-effort coercion of a Position-like snapshot to a plain dict for
    uniform ``.get()`` access, whether the caller passed a real
    ``Position`` dataclass instance, a dict (e.g. a rehydrated snapshot),
    or ``None``."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    # dataclasses / arbitrary objects: read attributes we know about via
    # getattr in the caller instead of vars(), since Position carries
    # non-serializable fields (trade_profile object, datetimes) we want to
    # convert deliberately rather than blindly dumping __dict__.
    return {}


def _get(meta: Dict[str, Any], position: Any, key: str, pos_attr: Optional[str] = None, default: Any = None) -> Any:
    """Read ``key`` from the TradeEvent's metadata dict first (it is the
    per-event snapshot taken at the exact moment of close); if absent AND a
    position snapshot was supplied, fall back to the position's attribute
    (``pos_attr``, defaulting to ``key``) so fields metadata doesn't carry
    for a given close_type (e.g. TP1 partials omit several terminal-only
    keys) can still be filled in when the caller has the Position on hand."""
    if key in meta and meta[key] is not None:
        return meta[key]
    if position is not None:
        attr = pos_attr or key
        if isinstance(position, dict):
            val = position.get(attr, None)
        else:
            val = getattr(position, attr, None)
        if val is not None:
            return val
    return default


@dataclass(frozen=True)
class TradeClosed:
    """Immutable, fully-snapshotted "a position/leg just closed" event.

    See module docstring for dedup key, immutability, and total_pnl
    sourcing invariants. Construct via ``from_trade_event`` in production;
    direct construction is supported (and used by tests) but callers are
    responsible for supplying a non-empty ``position_id``.
    """

    # ---- identity / dedup key -------------------------------------------------
    position_id: str
    leg_kind: LegKind
    close_type: str

    # ---- fill facts (direct from the TradeEvent) ------------------------------
    symbol: str
    side: str
    price: float
    qty: float
    pnl: float
    fee: float
    leverage: float
    strategy: str

    # ---- authoritative pnl -----------------------------------------------------
    total_pnl: float

    # ---- event identity (defaulted; everything below also has a default) ------
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    fees_total: Optional[float] = None
    funding_costs: Optional[float] = None
    equity_after: Optional[float] = None
    pnl_pct_of_equity: Optional[float] = None
    session_dd_pct: Optional[float] = None

    # ---- position snapshot ------------------------------------------------------
    entry: Optional[float] = None
    original_sl: Optional[float] = None
    original_qty: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    confidence: Optional[float] = None
    entry_reasons: Dict[str, Any] = field(default_factory=dict)
    trade_profile: Dict[str, Any] = field(default_factory=dict)
    state_path: Optional[List[str]] = None
    outcome: str = ""
    open_time: Optional[str] = None   # ISO-8601 string (never a raw datetime -- JSON-safe)
    close_time: Optional[str] = None  # ISO-8601 string
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    regime: str = ""
    entry_type: str = ""
    primary_driver: str = ""
    llm_action: str = ""
    llm_conf: float = 0.0
    llm_agreed: bool = True
    hold_time_s: float = 0.0
    close_volatility: Optional[float] = None
    compound_mult: Optional[float] = None
    candidate_ref: Optional[str] = None

    # ---- delivery metadata -------------------------------------------------------
    exchange_submitted: bool = False
    sim: bool = False

    def __post_init__(self) -> None:
        assert self.position_id, "TradeClosed: position_id must be non-empty"
        assert self.event_id, "TradeClosed: event_id must be non-empty"

        # Normalize a plain-string leg_kind (e.g. reconstructed from a JSON
        # outbox row) back into the enum.
        if not isinstance(self.leg_kind, LegKind):
            object.__setattr__(self, "leg_kind", LegKind(self.leg_kind))

        # Deep-copy isolation (spec invariant: "no field may be lazily
        # computed later from live mutable state" -- enforced here so even
        # a caller who mutates their source dict AFTER construction cannot
        # retroactively change what a subscriber already read).
        object.__setattr__(
            self, "entry_reasons",
            copy.deepcopy(self.entry_reasons) if self.entry_reasons else {},
        )
        object.__setattr__(
            self, "trade_profile",
            copy.deepcopy(self.trade_profile) if self.trade_profile else {},
        )
        object.__setattr__(
            self, "state_path",
            copy.deepcopy(self.state_path) if self.state_path else None,
        )

    @classmethod
    def from_trade_event(
        cls,
        event: "TradeEvent",
        *,
        position: Optional[Union["Position", Dict[str, Any]]] = None,
        equity_after: Optional[float] = None,
        session_dd_pct: Optional[float] = None,
        sim: bool = False,
        exchange_submitted: bool = False,
        close_volatility: Optional[float] = None,
        compound_mult: Optional[float] = None,
        candidate_ref: Optional[str] = None,
    ) -> "TradeClosed":
        """Build a frozen ``TradeClosed`` from a ``TradeEvent`` (+ optional
        ``Position`` snapshot for fields the TradeEvent's metadata doesn't
        carry for every close_type -- see module docstring).

        ``position`` may be a real ``Position`` dataclass instance, a
        plain dict (e.g. a rehydrated snapshot), or omitted. When omitted,
        fields only available on the Position (e.g. ``original_qty``,
        ``open_time`` for a PARTIAL leg) are left as ``None`` rather than
        guessed -- callers that have the Position on hand should pass it.
        """
        meta: Dict[str, Any] = event.metadata or {}
        position_id = getattr(event, "position_id", "") or ""
        assert position_id, (
            "TradeClosed.from_trade_event: event.position_id is empty -- "
            "every TradeEvent constructor must populate position_id from "
            "pos.position_id (Phase 0.4-A1); refusing to build an event "
            "with no identity."
        )

        leg_kind = LegKind.TERMINAL if event.is_position_close else LegKind.PARTIAL

        # entry_reasons: metadata carries a per-close-time copy of
        # pos.entry_reasons for BOTH partial and terminal events; prefer the
        # position snapshot's copy only if metadata is missing it entirely.
        entry_reasons = meta.get("entry_reasons")
        if not entry_reasons:
            entry_reasons = _get(meta, position, "entry_reasons", default={}) or {}

        # total_pnl: the ONLY pnl source is metadata["total_pnl"] (the
        # position's realized_pnl at the moment this TradeEvent was built),
        # falling back to position.realized_pnl if a snapshot was supplied.
        # event.pnl is deliberately never used here -- see module docstring.
        total_pnl = meta.get("total_pnl")
        if total_pnl is None and position is not None:
            total_pnl = (
                position.get("realized_pnl") if isinstance(position, dict)
                else getattr(position, "realized_pnl", None)
            )
        assert total_pnl is not None, (
            "TradeClosed.from_trade_event: no total_pnl available from "
            "event.metadata['total_pnl'] nor position.realized_pnl -- "
            "refusing to fall back to event.pnl (a per-leg delta, not the "
            "authoritative total; see spec04.md R7/R10)."
        )

        trade_profile = meta.get("trade_profile")
        if not trade_profile:
            tp_obj = position.get("trade_profile") if isinstance(position, dict) else getattr(position, "trade_profile", None) if position is not None else None
            if tp_obj is not None:
                trade_profile = tp_obj.to_dict() if hasattr(tp_obj, "to_dict") else (tp_obj if isinstance(tp_obj, dict) else {})

        open_time = _get(meta, position, "open_time")
        close_time = meta.get("close_time")
        if close_time is None:
            close_time = _get(meta, position, "close_time")
        if close_time is None:
            close_time = getattr(event, "timestamp", None)

        def _iso(value: Any) -> Optional[str]:
            if value is None:
                return None
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        pnl_pct_of_equity: Optional[float] = None
        if equity_after:
            try:
                pnl_pct_of_equity = (float(total_pnl) / float(equity_after)) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                pnl_pct_of_equity = None

        regime = meta.get("regime") or entry_reasons.get("regime", "") or ""

        return cls(
            position_id=position_id,
            leg_kind=leg_kind,
            close_type=event.action,
            symbol=event.symbol,
            side=event.side,
            price=event.price,
            qty=event.qty,
            pnl=event.pnl,
            fee=event.fee,
            leverage=event.leverage,
            strategy=event.strategy,
            total_pnl=float(total_pnl),
            fees_total=_get(meta, position, "total_fees", pos_attr="fees_paid"),
            funding_costs=meta.get("funding_costs", meta.get("funding_share"))
            if ("funding_costs" in meta or "funding_share" in meta)
            else _get(meta, position, "funding_costs"),
            equity_after=equity_after,
            pnl_pct_of_equity=pnl_pct_of_equity,
            session_dd_pct=session_dd_pct,
            entry=_get(meta, position, "entry"),
            original_sl=_get(meta, position, "sl", pos_attr="original_sl"),
            original_qty=_get(meta, position, "original_qty"),
            tp1=_get(meta, position, "tp1"),
            tp2=_get(meta, position, "tp2"),
            confidence=_get(meta, position, "confidence"),
            entry_reasons=entry_reasons,
            trade_profile=trade_profile or {},
            state_path=meta.get("state_path") or _get(meta, position, "state_path_str"),
            outcome=meta.get("outcome") or _get(meta, position, "outcome", default=""),
            open_time=_iso(open_time),
            close_time=_iso(close_time),
            mfe_pct=meta.get("mfe_pct"),
            mae_pct=meta.get("mae_pct"),
            highest_price=_get(meta, position, "highest_price"),
            lowest_price=_get(meta, position, "lowest_price"),
            regime=regime,
            entry_type=meta.get("entry_type", ""),
            primary_driver=meta.get("primary_driver", ""),
            llm_action=entry_reasons.get("llm_action", "") or "",
            llm_conf=entry_reasons.get("llm_confidence", 0.0) or 0.0,
            llm_agreed=entry_reasons.get("llm_agreed", True),
            hold_time_s=meta.get("hold_time_s", 0.0) or 0.0,
            close_volatility=close_volatility,
            compound_mult=compound_mult,
            candidate_ref=candidate_ref,
            exchange_submitted=exchange_submitted,
            sim=sim,
        )
