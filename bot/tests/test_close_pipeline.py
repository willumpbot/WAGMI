"""Tests for Phase 0.4-B core/close_pipeline/ (trade_closed, close_outbox,
close_bus) -- the frozen TradeClosed event, the durable append-only
close_outbox, and the tiered CloseBus dispatcher.

Built + unit-tested IN ISOLATION: nothing here is wired into the god-block.
Every test uses tmp_path / explicit path= kwargs exclusively -- none of
these tests read, write, or create anything under a REAL bot/data/
directory.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from core.close_pipeline.close_bus import (
    CloseBus,
    DeliveryReport,
    FileBackedAppliedStore,
    InMemoryAppliedStore,
    Tier,
)
from core.close_pipeline import close_outbox
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_types import CloseKind
from execution.position_manager import Position, TradeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_position(**overrides) -> Position:
    defaults = dict(
        symbol="BTC-USD",
        side="LONG",
        entry=100.0,
        qty=1.0,
        sl=95.0,
        tp1=105.0,
        tp2=110.0,
        strategy="regime_trend",
        confidence=72.0,
    )
    defaults.update(overrides)
    pos = Position(**defaults)
    return pos


def _terminal_event(pos: Position, *, pnl_leg=8.0, total_pnl=12.0, position_id=None) -> TradeEvent:
    """Mirror the metadata shape position_manager.py's _close_position()
    builds for a terminal (full) close TradeEvent."""
    return TradeEvent(
        symbol=pos.symbol,
        action="SL",
        side=pos.side,
        price=94.5,
        qty=pos.qty,
        pnl=pnl_leg,
        fee=0.42,
        leverage=pos.leverage,
        strategy=pos.strategy,
        position_id=position_id if position_id is not None else pos.position_id,
        is_position_close=True,
        metadata={
            "total_pnl": total_pnl,
            "total_fees": 1.23,
            "funding_costs": 0.05,
            "hold_time_s": 3600.0,
            "peak_price": 108.0,
            "outcome": "CLEAN_LOSS",
            "state_path": "IDLE->OPEN->CLOSED",
            "entry_reasons": {
                "regime": "trend", "num_agree": 3, "strategies_agree": ["a", "b"],
                "llm_action": "proceed", "llm_confidence": 0.81, "llm_agreed": True,
            },
            "num_agree": 3,
            "strategies_agree": ["a", "b"],
            "entry_type": "TREND",
            "primary_driver": "regime_trend",
            "regime": "trend",
            "volatility_band": "normal",
            "trade_profile": {"entry_type": "TREND", "primary_driver": "regime_trend"},
            "entry": pos.entry,
            "sl": pos.original_sl,
            "tp1": pos.tp1,
            "tp2": pos.tp2,
            "confidence": pos.confidence,
            "mfe": 8.0, "mae": 5.0,
            "mfe_pct": 8.0, "mae_pct": 5.0,
            "highest_price": 108.0,
            "lowest_price": 94.0,
        },
    )


def _partial_event(pos: Position, *, position_id=None) -> TradeEvent:
    """Mirror the metadata shape _partial_close_tp1() builds -- notably
    missing several terminal-only keys (state_path, outcome, trade_profile,
    mfe_pct/mae_pct, highest/lowest_price)."""
    return TradeEvent(
        symbol=pos.symbol,
        action="TP1",
        side=pos.side,
        price=105.0,
        qty=0.5,
        pnl=2.5,
        fee=0.1,
        leverage=pos.leverage,
        strategy=pos.strategy,
        position_id=position_id if position_id is not None else pos.position_id,
        is_position_close=False,
        metadata={
            "remaining_qty": 0.5,
            "new_sl": 100.2,
            "tp1_close_pct": 0.5,
            "funding_share": 0.01,
            "entry_reasons": {
                "regime": "trend",
                "llm_action": "proceed", "llm_confidence": 0.81, "llm_agreed": True,
            },
            "num_agree": 3,
            "strategies_agree": ["a", "b"],
            "entry": pos.entry,
            "sl": pos.original_sl,
            "tp1": pos.tp1,
            "tp2": pos.tp2,
            "confidence": pos.confidence,
            "hold_time_s": 600.0,
        },
    )


def _minimal_closed(position_id="pid-1", event_id=None, **overrides) -> TradeClosed:
    kwargs = dict(
        position_id=position_id,
        leg_kind=LegKind.TERMINAL,
        close_type="SL",
        symbol="BTC-USD",
        side="LONG",
        price=94.5,
        qty=1.0,
        pnl=8.0,
        fee=0.4,
        leverage=1.0,
        strategy="regime_trend",
        total_pnl=12.0,
    )
    if event_id is not None:
        kwargs["event_id"] = event_id
    kwargs.update(overrides)
    return TradeClosed(**kwargs)


# ---------------------------------------------------------------------------
# trade_closed.py
# ---------------------------------------------------------------------------
class TestTradeClosed:
    def test_from_trade_event_terminal_mapping(self):
        pos = _make_position()
        event = _terminal_event(pos, pnl_leg=8.0, total_pnl=12.0)

        tc = TradeClosed.from_trade_event(event, position=pos)

        assert tc.position_id == pos.position_id
        assert tc.leg_kind == LegKind.TERMINAL
        assert tc.close_type == "SL"
        assert tc.symbol == "BTC-USD"
        assert tc.side == "LONG"
        assert tc.price == 94.5
        assert tc.qty == pos.qty
        assert tc.pnl == 8.0
        assert tc.total_pnl == 12.0  # from metadata["total_pnl"], NOT event.pnl (8.0)
        assert tc.fees_total == 1.23
        assert tc.funding_costs == 0.05
        assert tc.outcome == "CLEAN_LOSS"
        assert tc.state_path == "IDLE->OPEN->CLOSED"
        assert tc.entry_type == "TREND"
        assert tc.primary_driver == "regime_trend"
        assert tc.regime == "trend"
        assert tc.llm_action == "proceed"
        assert tc.llm_conf == 0.81
        assert tc.llm_agreed is True
        assert tc.hold_time_s == 3600.0
        assert tc.mfe_pct == 8.0 and tc.mae_pct == 5.0
        assert tc.highest_price == 108.0 and tc.lowest_price == 94.0
        assert tc.entry == pos.entry
        assert tc.tp1 == pos.tp1 and tc.tp2 == pos.tp2
        assert tc.confidence == pos.confidence
        # position-sourced fields not present in metadata at all:
        assert tc.original_qty == pos.original_qty
        assert tc.open_time is not None  # ISO string, sourced from pos.open_time
        # exchange_submitted/sim/close_volatility/compound_mult/candidate_ref
        # all default when not explicitly overridden:
        assert tc.exchange_submitted is False
        assert tc.sim is False
        assert tc.close_volatility is None
        assert tc.compound_mult is None
        assert tc.candidate_ref is None

    def test_from_trade_event_partial_mapping(self):
        pos = _make_position()
        event = _partial_event(pos)

        tc = TradeClosed.from_trade_event(event, position=pos)

        assert tc.leg_kind == LegKind.PARTIAL
        assert tc.close_type == "TP1"
        assert tc.qty == 0.5
        assert tc.pnl == 2.5
        # total_pnl for a partial leg still comes from metadata["total_pnl"]
        # if present, else falls back to position.realized_pnl -- this
        # fixture's partial metadata has no "total_pnl" key, so it must
        # fall back to the position snapshot.
        assert tc.total_pnl == pos.realized_pnl
        assert tc.llm_action == "proceed"
        assert tc.llm_conf == 0.81
        # Terminal-only keys absent from TP1 metadata and not derivable
        # from the (non-closed) position either -- must not crash, must
        # default sanely.
        assert tc.outcome == ""
        assert tc.mfe_pct is None and tc.mae_pct is None

    def test_from_trade_event_without_position_snapshot(self):
        """When no `position=` is supplied, fields metadata already carries
        must still populate; fields only on Position (original_qty,
        open_time) fall back to None rather than raising."""
        pos = _make_position()
        event = _terminal_event(pos)

        tc = TradeClosed.from_trade_event(event)

        assert tc.total_pnl == 12.0
        assert tc.entry == pos.entry  # present in metadata directly
        assert tc.original_qty is None  # never in metadata, no position given
        assert tc.open_time is None

    def test_empty_position_id_raises(self):
        """from_trade_event's own invariant check is an explicit `raise
        ValueError`, not `assert` (assertions are compiled out under
        `python -O`) -- see trade_closed.py FIX 2."""
        pos = _make_position()
        event = _terminal_event(pos, position_id="")
        with pytest.raises(ValueError):
            TradeClosed.from_trade_event(event)

    def test_direct_construction_empty_position_id_raises(self):
        """__post_init__'s invariants are explicit `raise ValueError`, not
        `assert` (assertions are compiled out under `python -O`, which
        would let an empty position_id pass through silently in an
        optimized run) -- finishes FIX 2 for the direct-construction path
        (from_trade_event's path was already converted)."""
        with pytest.raises(ValueError, match="position_id must be non-empty"):
            _minimal_closed(position_id="")

    def test_direct_construction_empty_event_id_raises(self):
        with pytest.raises(ValueError, match="event_id must be non-empty"):
            _minimal_closed(event_id="")

    def test_frozen_mutation_raises(self):
        tc = _minimal_closed()
        with pytest.raises(dataclasses.FrozenInstanceError):
            tc.pnl = 999.0  # type: ignore[misc]

    def test_total_pnl_never_falls_back_to_event_pnl_silently(self):
        """If NEITHER metadata["total_pnl"] NOR position.realized_pnl is
        available, from_trade_event must refuse, never silently substitute
        event.pnl. This is an explicit `raise ValueError`, not `assert`
        (assertions are compiled out under `python -O`) -- see
        trade_closed.py FIX 2."""
        pos = _make_position()
        event = _partial_event(pos)
        event.metadata.pop("total_pnl", None)  # already absent, explicit for clarity
        # Use a bare dict "position" with no realized_pnl key at all.
        with pytest.raises(ValueError):
            TradeClosed.from_trade_event(event, position={})

    def test_invariants_raise_not_assert(self):
        """Both from_trade_event invariants (non-empty position_id,
        total_pnl availability) must be explicit `raise ValueError`, not
        `assert` -- `assert` is compiled out under `python -O`, which would
        silently let a bad event through in an optimized run. This directly
        exercises the raise/message rather than relying on AssertionError's
        accidental-pass-under -O behavior."""
        pos = _make_position()

        empty_id_event = _terminal_event(pos, position_id="")
        with pytest.raises(ValueError, match="position_id is empty"):
            TradeClosed.from_trade_event(empty_id_event)

        no_pnl_event = _partial_event(pos)
        no_pnl_event.metadata.pop("total_pnl", None)
        with pytest.raises(ValueError, match="no total_pnl available"):
            TradeClosed.from_trade_event(no_pnl_event, position={})

    def test_deep_copy_isolation_entry_reasons(self):
        pos = _make_position()
        event = _terminal_event(pos)
        source_er = event.metadata["entry_reasons"]

        tc = TradeClosed.from_trade_event(event, position=pos)
        assert tc.entry_reasons["regime"] == "trend"

        # Mutate the SOURCE dict after construction -- must not leak in.
        source_er["regime"] = "MUTATED"
        source_er["new_key"] = "should not appear"
        assert tc.entry_reasons["regime"] == "trend"
        assert "new_key" not in tc.entry_reasons

    def test_deep_copy_isolation_direct_construction(self):
        er = {"regime": "trend"}
        tc = _minimal_closed(entry_reasons=er)
        er["regime"] = "MUTATED"
        assert tc.entry_reasons["regime"] == "trend"

    def test_leg_kind_derived_from_is_position_close(self):
        pos = _make_position()
        terminal = TradeClosed.from_trade_event(_terminal_event(pos), position=pos)
        partial = TradeClosed.from_trade_event(_partial_event(pos), position=pos)
        assert terminal.leg_kind == LegKind.TERMINAL
        assert partial.leg_kind == LegKind.PARTIAL


# ---------------------------------------------------------------------------
# close_outbox.py
# ---------------------------------------------------------------------------
class TestCloseOutbox:
    def test_append_and_reload_round_trip(self, tmp_path):
        target = tmp_path / "close_outbox.jsonl"
        tc = _minimal_closed(position_id="pid-A", event_id="ev-A")

        close_outbox.append(tc, path=target)
        loaded = close_outbox.load_all(path=target)

        assert len(loaded) == 1
        assert loaded[0].position_id == "pid-A"
        assert loaded[0].event_id == "ev-A"
        assert loaded[0].total_pnl == tc.total_pnl
        assert loaded[0].leg_kind == LegKind.TERMINAL

    def test_sim_event_never_written(self, tmp_path):
        target = tmp_path / "close_outbox.jsonl"
        tc = _minimal_closed(position_id="pid-sim", event_id="ev-sim", sim=True)

        close_outbox.append(tc, path=target)

        assert not target.exists()
        assert close_outbox.load_all(path=target) == []

    def test_torn_last_line_skipped(self, tmp_path):
        target = tmp_path / "close_outbox.jsonl"
        good = _minimal_closed(position_id="pid-good", event_id="ev-good")
        close_outbox.append(good, path=target)
        # Corrupt-append a torn line (simulating a crash mid-write).
        with open(target, "a", encoding="utf-8") as f:
            f.write('{"position_id": "pid-torn", "event_id": "ev-torn", "incomplete')

        loaded = close_outbox.load_all(path=target)
        assert len(loaded) == 1
        assert loaded[0].position_id == "pid-good"

    def test_ack_and_unacked(self, tmp_path):
        target = tmp_path / "close_outbox.jsonl"
        e1 = _minimal_closed(position_id="pid-1", event_id="ev-1")
        e2 = _minimal_closed(position_id="pid-2", event_id="ev-2")
        close_outbox.append(e1, path=target)
        close_outbox.append(e2, path=target)

        required = ["equity", "cb"]
        pending = close_outbox.unacked(required, path=target)
        assert {e.event_id for e in pending} == {"ev-1", "ev-2"}

        close_outbox.ack("ev-1", "equity", path=target)
        close_outbox.ack("ev-1", "cb", path=target)
        pending = close_outbox.unacked(required, path=target)
        assert {e.event_id for e in pending} == {"ev-2"}

        # Idempotent: acking again is a no-op, still fully acked.
        close_outbox.ack("ev-1", "equity", path=target)
        pending = close_outbox.unacked(required, path=target)
        assert {e.event_id for e in pending} == {"ev-2"}

    def test_compact_drops_fully_acked_old_rows(self, tmp_path):
        target = tmp_path / "close_outbox.jsonl"
        now = datetime.now(timezone.utc)
        old_iso = (now - timedelta(days=30)).isoformat()
        fresh_iso = (now - timedelta(hours=1)).isoformat()

        old_event = _minimal_closed(position_id="pid-old", event_id="ev-old", close_time=old_iso)
        fresh_event = _minimal_closed(position_id="pid-fresh", event_id="ev-fresh", close_time=fresh_iso)
        unacked_old_event = _minimal_closed(position_id="pid-old2", event_id="ev-old2", close_time=old_iso)

        close_outbox.append(old_event, path=target)
        close_outbox.append(fresh_event, path=target)
        close_outbox.append(unacked_old_event, path=target)

        close_outbox.ack("ev-old", "equity", path=target)
        close_outbox.ack("ev-fresh", "equity", path=target)
        # ev-old2 deliberately left unacked.

        dropped = close_outbox.compact(
            older_than_days=7, required_subscribers=["equity"], path=target, now=now,
        )

        assert dropped == 1
        remaining_ids = {e.event_id for e in close_outbox.load_all(path=target)}
        assert remaining_ids == {"ev-fresh", "ev-old2"}

        acks = close_outbox.load_acks(path=target)
        assert "ev-old" not in acks  # pruned alongside the dropped row

    def test_ack_concurrent_writes_no_lost_updates(self, tmp_path):
        """FIX 3: ack() used to do an unlocked read-modify-write of the acks
        map. Single-threaded that's fine, but close_with_execution is
        designed to be called from the Telegram poll thread concurrently
        with the main thread -- many threads acking DIFFERENT (event_id,
        subscriber) pairs against the SAME acks file must never lose an
        update. Uses a barrier to force maximum contention."""
        target = tmp_path / "close_outbox.jsonl"
        n_events = 12
        n_subs = 5
        events = [
            _minimal_closed(position_id=f"pid-{i}", event_id=f"ev-{i}")
            for i in range(n_events)
        ]
        for e in events:
            close_outbox.append(e, path=target)

        sub_names = [f"sub{i}" for i in range(n_subs)]
        pairs = [(e.event_id, sub) for e in events for sub in sub_names]

        barrier = threading.Barrier(len(pairs))

        def _do_ack(event_id: str, sub_name: str) -> None:
            barrier.wait()  # release every thread at (roughly) the same instant
            close_outbox.ack(event_id, sub_name, path=target)

        threads = [
            threading.Thread(target=_do_ack, args=(event_id, sub_name))
            for event_id, sub_name in pairs
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        acks = close_outbox.load_acks(path=target)
        for e in events:
            assert set(acks.get(e.event_id, [])) == set(sub_names), (
                f"lost ack(s) for {e.event_id}: got {acks.get(e.event_id, [])}"
            )


# ---------------------------------------------------------------------------
# close_bus.py
# ---------------------------------------------------------------------------
class TestCloseBus:
    def _wire_full_tier_bus(self, tmp_path, call_order, *, extra_subs=()):
        bus = CloseBus(outbox_path=tmp_path / "close_outbox.jsonl")

        def make(name):
            def _fn(event):
                call_order.append(name)
            return _fn

        bus.subscribe("equity", make("equity"), tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("cb", make("cb"), tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("log_trade", make("log_trade"), tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("ledger", make("ledger"), tier=Tier.T1_PERSISTENCE, required=True, replay=True)
        bus.subscribe("trades_csv", make("trades_csv"), tier=Tier.T1_PERSISTENCE, required=True, replay=True)
        bus.subscribe("auto_demotion", make("auto_demotion"), tier=Tier.T2_DERIVED_READERS, required=True, replay=True)
        bus.subscribe("alert", make("alert"), tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False)
        bus.subscribe("llm", make("llm"), tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False)
        for name, fn, tier, required, replay in extra_subs:
            bus.subscribe(name, fn, tier=tier, required=required, replay=replay)
        return bus

    def test_tier_ordering(self, tmp_path):
        call_order = []
        bus = self._wire_full_tier_bus(tmp_path, call_order)
        event = _minimal_closed(position_id="pid-order", event_id="ev-order")

        report = bus.publish(event)

        expected_prefix_groups = [
            {"equity", "cb", "log_trade"},
            {"ledger", "trades_csv"},
            {"auto_demotion"},
            {"alert", "llm"},
        ]
        # T0 must run strictly before T1 before T2 before T3.
        idx = {name: i for i, name in enumerate(call_order)}
        assert max(idx[n] for n in expected_prefix_groups[0]) < min(idx[n] for n in expected_prefix_groups[1])
        assert max(idx[n] for n in expected_prefix_groups[1]) < idx["auto_demotion"]
        assert idx["auto_demotion"] < min(idx[n] for n in expected_prefix_groups[3])
        # Deterministic within-tier subscribe order.
        assert call_order.index("equity") < call_order.index("cb") < call_order.index("log_trade")
        assert call_order.index("ledger") < call_order.index("trades_csv")
        assert set(report.delivered) == {
            "equity", "cb", "log_trade", "ledger", "trades_csv", "auto_demotion", "alert", "llm",
        }

    def test_per_subscriber_isolation(self, tmp_path):
        call_order = []

        def raising_ledger(event):
            raise RuntimeError("ledger boom")

        bus = self._wire_full_tier_bus(
            tmp_path, call_order,
        )
        # Replace ledger's fn with a raising one by re-subscribing under a
        # fresh bus (subscribe doesn't support overwrite; build directly).
        bus2 = CloseBus(outbox_path=tmp_path / "close_outbox2.jsonl")
        order2 = []
        bus2.subscribe("equity", lambda e: order2.append("equity"), tier=Tier.T0_CORE_ACCOUNTING)
        bus2.subscribe("ledger", raising_ledger, tier=Tier.T1_PERSISTENCE)
        bus2.subscribe("alert", lambda e: order2.append("alert"), tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False)

        event = _minimal_closed(position_id="pid-iso", event_id="ev-iso")
        report = bus2.publish(event)

        assert "equity" in report.delivered
        assert "alert" in report.delivered  # ledger's crash never skipped alert
        assert any(name == "ledger" for name, _err in report.failed)
        assert order2 == ["equity", "alert"]

    def test_exactly_once_mandatory_vs_fire_and_forget(self, tmp_path):
        """T0 (equity) keeps the default dedupe=True -- applied exactly
        once. "alert" is fire-and-forget AND explicitly opts out of the
        exactly-once seam (dedupe=False) -- the documented case for a
        subscriber that legitimately re-runs on a duplicate publish. A
        fire-and-forget subscriber that does NOT opt out is, by the new
        generalized default, deduped exactly like any other subscriber --
        see test_duplicate_publish_idempotent_for_all_dedupe_subscribers."""
        equity_calls = []
        alert_calls = []
        bus = CloseBus(outbox_path=tmp_path / "close_outbox.jsonl")
        bus.subscribe("equity", lambda e: equity_calls.append(1), tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe(
            "alert", lambda e: alert_calls.append(1),
            tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False, dedupe=False,
        )

        event = _minimal_closed(position_id="pid-dup", event_id="ev-dup")
        report1 = bus.publish(event)
        report2 = bus.publish(event)  # duplicate publish, same position_id + event_id

        assert len(equity_calls) == 1  # mandatory T0: applied exactly once (default dedupe=True)
        assert len(alert_calls) == 2  # explicit dedupe=False opt-out: no dedup guarantee
        assert "equity" in report1.delivered
        assert "equity" in report2.skipped  # second delivery explicitly skipped

    def test_duplicate_publish_idempotent_for_all_dedupe_subscribers(self, tmp_path):
        """GENERALIZED exactly-once: the old CLOSE_DEDUP_GUARD only made a
        duplicate close idempotent for T0 (equity/CB) -- ledger (T1) and
        kelly/IC (T2) could still double-fire on a re-published close (the
        12-phantom-rows/-$370 incident's real cause: equity double-counted
        because the guard was incomplete). Every dedupe=True subscriber,
        across every tier, must now fire EXACTLY ONCE per position_id even
        when the duplicate publish uses a DIFFERENT event_id."""
        calls = {"equity": 0, "ledger": 0, "kelly": 0}
        bus = CloseBus(outbox_path=tmp_path / "close_outbox.jsonl")
        bus.subscribe(
            "equity", lambda e: calls.__setitem__("equity", calls["equity"] + 1),
            tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True,
        )
        bus.subscribe(
            "ledger", lambda e: calls.__setitem__("ledger", calls["ledger"] + 1),
            tier=Tier.T1_PERSISTENCE, required=True, replay=True,
        )
        bus.subscribe(
            "kelly", lambda e: calls.__setitem__("kelly", calls["kelly"] + 1),
            tier=Tier.T2_DERIVED_READERS, required=True, replay=True,
        )

        event1 = _minimal_closed(position_id="pid-dup-all", event_id="ev-dup-all-1")
        event2 = _minimal_closed(position_id="pid-dup-all", event_id="ev-dup-all-2")
        report1 = bus.publish(event1)
        report2 = bus.publish(event2)  # duplicate publish: SAME position_id, different event_id

        assert calls == {"equity": 1, "ledger": 1, "kelly": 1}
        assert set(report1.delivered) == {"equity", "ledger", "kelly"}
        assert report1.skipped == []
        assert report2.delivered == []
        assert set(report2.skipped) == {"equity", "ledger", "kelly"}

    def test_dedupe_false_opt_out_runs_on_every_publish(self, tmp_path):
        """A subscriber registered with dedupe=False is NOT covered by the
        exactly-once seam -- it must run on every publish() regardless of
        position_id repetition (the documented opt-out for legitimately
        re-run fire-and-forget sinks)."""
        calls = []
        bus = CloseBus(outbox_path=tmp_path / "close_outbox.jsonl")
        bus.subscribe(
            "telemetry", lambda e: calls.append(1),
            tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False, dedupe=False,
        )

        event1 = _minimal_closed(position_id="pid-nodedup", event_id="ev-nodedup-1")
        event2 = _minimal_closed(position_id="pid-nodedup", event_id="ev-nodedup-2")
        bus.publish(event1)
        bus.publish(event2)

        assert calls == [1, 1]

    def test_generalized_dedupe_raise_then_replay_recovers_then_publish_skips(self, tmp_path):
        """Combines aed7f79's raise/replay guarantee with the GENERALIZED
        dedupe: a dedupe=True required T2 subscriber ("kelly") raises on
        the first publish -> stays un-applied (and unacked) while its
        sibling ("equity") already succeeded and IS applied -> replay
        redelivers ONLY kelly (not equity again) -> kelly succeeds -> now
        applied -> a further publish() of the same position_id skips BOTH
        subscribers, proving exactly-once still holds after a recovered
        failure."""
        outbox_path = tmp_path / "close_outbox.jsonl"
        calls = {"equity": 0, "kelly": 0}
        fail_kelly = {"raise": True}

        def equity_fn(e):
            calls["equity"] += 1

        def kelly_fn(e):
            calls["kelly"] += 1
            if fail_kelly["raise"]:
                raise RuntimeError("kelly boom")

        bus = CloseBus(outbox_path=outbox_path)
        bus.subscribe("equity", equity_fn, tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("kelly", kelly_fn, tier=Tier.T2_DERIVED_READERS, required=True, replay=True)

        event = _minimal_closed(position_id="pid-gen-raise", event_id="ev-gen-raise")
        report1 = bus.publish(event)  # 1st publish: kelly raises

        assert calls == {"equity": 1, "kelly": 1}
        assert "equity" in report1.delivered
        assert report1.failed and report1.failed[0][0] == "kelly"
        assert bus._applied_store.is_applied("equity", "pid-gen-raise") is True
        assert bus._applied_store.is_applied("kelly", "pid-gen-raise") is False
        assert close_outbox.unacked(["kelly"], path=outbox_path) != []

        fail_kelly["raise"] = False
        delivered = bus.replay_unacked()  # must redeliver ONLY kelly

        assert calls == {"equity": 1, "kelly": 2}  # equity NOT re-run by replay
        assert delivered == 1
        assert bus._applied_store.is_applied("kelly", "pid-gen-raise") is True
        assert close_outbox.unacked(["kelly"], path=outbox_path) == []

        # A further publish() of the same position_id (after the recovered
        # failure) must now skip BOTH subscribers -- kelly's side effect
        # landed via replay, so exactly-once still holds.
        event2 = _minimal_closed(position_id="pid-gen-raise", event_id="ev-gen-raise-2")
        report3 = bus.publish(event2)

        assert calls == {"equity": 1, "kelly": 2}  # unchanged: both skipped
        assert set(report3.skipped) == {"equity", "kelly"}
        assert report3.delivered == []

    def test_replay_unacked_drives_only_must_replay_subscribers(self, tmp_path):
        outbox_path = tmp_path / "close_outbox.jsonl"
        # Simulate a crash-before-subscribers-ran: append directly without
        # going through publish(), so nothing is acked yet.
        stale_event = _minimal_closed(position_id="pid-stale", event_id="ev-stale")
        close_outbox.append(stale_event, path=outbox_path)

        equity_calls = []
        llm_calls = []
        alert_calls = []
        bus = CloseBus(outbox_path=outbox_path)
        bus.subscribe("equity", lambda e: equity_calls.append(e.event_id), tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("ledger", lambda e: None, tier=Tier.T1_PERSISTENCE, required=True, replay=True)
        bus.subscribe("llm", lambda e: llm_calls.append(1), tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False)
        bus.subscribe("alert", lambda e: alert_calls.append(1), tier=Tier.T3_FIRE_AND_FORGET, required=False, replay=False)

        delivered = bus.replay_unacked()

        assert equity_calls == ["ev-stale"]
        assert llm_calls == []
        assert alert_calls == []
        assert delivered == 2  # equity + ledger, the two replay=True subs

        # A second replay call must not re-deliver to already-acked
        # required subscribers (idempotent boot replay).
        delivered_again = bus.replay_unacked()
        assert delivered_again == 0

    def test_publish_writes_outbox_before_subscribers_run(self, tmp_path):
        outbox_path = tmp_path / "close_outbox.jsonl"
        bus = CloseBus(outbox_path=outbox_path)

        def crashing_subscriber(event):
            raise RuntimeError("simulated crash mid-subscriber")

        bus.subscribe("equity", crashing_subscriber, tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)

        event = _minimal_closed(position_id="pid-crash", event_id="ev-crash")
        report = bus.publish(event)

        # Even though the (only) subscriber raised, the outbox row is
        # durable -- proving append-before-dispatch.
        assert outbox_path.exists()
        rows = [json.loads(l) for l in outbox_path.read_text().splitlines() if l.strip()]
        assert any(r["event_id"] == "ev-crash" for r in rows)
        assert report.failed and report.failed[0][0] == "equity"

    def test_sim_event_refused_by_bus(self, tmp_path):
        outbox_path = tmp_path / "close_outbox.jsonl"
        bus = CloseBus(outbox_path=outbox_path)
        calls = []
        bus.subscribe("equity", lambda e: calls.append(1), tier=Tier.T0_CORE_ACCOUNTING)

        event = _minimal_closed(position_id="pid-sim", event_id="ev-sim", sim=True)
        report = bus.publish(event)

        assert calls == []
        assert not outbox_path.exists()
        assert report.delivered == []

    def test_kind_filter_full_vs_partial(self, tmp_path):
        outbox_path = tmp_path / "close_outbox.jsonl"
        bus = CloseBus(outbox_path=outbox_path)
        full_only_calls = []
        partial_only_calls = []
        bus.subscribe(
            "full_only", lambda e: full_only_calls.append(1),
            tier=Tier.T1_PERSISTENCE, kind=(CloseKind.FULL,),
        )
        bus.subscribe(
            "partial_only", lambda e: partial_only_calls.append(1),
            tier=Tier.T1_PERSISTENCE, kind=(CloseKind.PARTIAL,),
        )

        terminal_event = _minimal_closed(position_id="pid-t", event_id="ev-t", leg_kind=LegKind.TERMINAL)
        partial_event = _minimal_closed(position_id="pid-p", event_id="ev-p", leg_kind=LegKind.PARTIAL)

        bus.publish(terminal_event)
        bus.publish(partial_event)

        assert full_only_calls == [1]
        assert partial_only_calls == [1]

    def test_file_backed_applied_store_survives_new_bus_instance(self, tmp_path):
        store_path = tmp_path / "applied.json"
        outbox_path = tmp_path / "close_outbox.jsonl"

        calls_1 = []
        bus1 = CloseBus(applied_store=FileBackedAppliedStore(store_path), outbox_path=outbox_path)
        bus1.subscribe("equity", lambda e: calls_1.append(1), tier=Tier.T0_CORE_ACCOUNTING, required=True)

        event = _minimal_closed(position_id="pid-persist", event_id="ev-persist")
        bus1.publish(event)
        assert calls_1 == [1]

        # A brand-new CloseBus instance, but backed by the SAME file-backed
        # applied-store, must still recognize this position_id as applied.
        calls_2 = []
        bus2 = CloseBus(applied_store=FileBackedAppliedStore(store_path), outbox_path=outbox_path)
        bus2.subscribe("equity", lambda e: calls_2.append(1), tier=Tier.T0_CORE_ACCOUNTING, required=True)
        bus2.publish(event)
        assert calls_2 == []  # deduped via the persisted applied-store

    def test_required_subscriber_raise_stays_unacked_and_is_recovered_by_replay(self, tmp_path):
        """FIX 1: a raised REQUIRED subscriber must never be acked, and the
        position_id must never be recorded as "applied" -- otherwise the
        failed booking (e.g. equity) becomes permanently unrecoverable:
        replay_unacked's own already-applied skip (tier==T0, required,
        already_applied) would then skip retrying the very subscriber that
        never actually ran successfully."""
        outbox_path = tmp_path / "close_outbox.jsonl"
        calls = {"equity": 0, "cb": 0, "log_trade": 0}
        fail_cb = {"raise": True}

        def equity_fn(e):
            calls["equity"] += 1

        def cb_fn(e):
            calls["cb"] += 1
            if fail_cb["raise"]:
                raise RuntimeError("cb boom")

        def log_trade_fn(e):
            calls["log_trade"] += 1

        bus = CloseBus(outbox_path=outbox_path)
        bus.subscribe("equity", equity_fn, tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("cb", cb_fn, tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)
        bus.subscribe("log_trade", log_trade_fn, tier=Tier.T0_CORE_ACCOUNTING, required=True, replay=True)

        event = _minimal_closed(position_id="pid-req-fail", event_id="ev-req-fail")
        report = bus.publish(event)

        assert dict(report.failed) and report.failed[0][0] == "cb"
        assert "equity" in report.delivered and "log_trade" in report.delivered
        assert calls == {"equity": 1, "cb": 1, "log_trade": 1}

        # (a) The failed subscriber ("cb") must remain UNACKED -- unacked()
        # for just that subscriber still returns the event. The subscribers
        # that DID succeed ("equity") must already be acked.
        pending_for_cb = close_outbox.unacked(["cb"], path=outbox_path)
        assert {e.event_id for e in pending_for_cb} == {"ev-req-fail"}
        pending_for_equity = close_outbox.unacked(["equity"], path=outbox_path)
        assert pending_for_equity == []

        # The failed subscriber ("cb") must NOT be recorded as "applied" --
        # a raised subscriber blocks its OWN mark_applied entirely, while
        # its siblings that already succeeded ARE independently recorded
        # applied (generalized per-(subscriber, position_id) applied-store
        # -- see close_bus.py's EXACTLY-ONCE SEAM).
        assert bus._applied_store.is_applied("equity", "pid-req-fail") is True
        assert bus._applied_store.is_applied("log_trade", "pid-req-fail") is True
        assert bus._applied_store.is_applied("cb", "pid-req-fail") is False

        # (b) replay_unacked() must redeliver ONLY to the failed subscriber
        # ("cb") -- "equity"/"log_trade" already succeeded and must NOT run
        # again (idempotent recovery, no double-booking).
        fail_cb["raise"] = False  # subscriber recovers on retry
        delivered = bus.replay_unacked()

        assert calls == {"equity": 1, "cb": 2, "log_trade": 1}
        assert delivered == 1

        # (c) Having succeeded on replay, "cb" is now acked and applied; a
        # second replay is a no-op.
        assert close_outbox.unacked(["cb"], path=outbox_path) == []
        assert bus._applied_store.is_applied("cb", "pid-req-fail") is True

        delivered_again = bus.replay_unacked()
        assert delivered_again == 0
