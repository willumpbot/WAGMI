"""Tests for Phase 0.3b -- position_id identity + core/position_journal.py
write-ahead journal + startup reconcile.

Guards against a repeat of the "-$370 double-count" / "silent drop"
incident class: a crash between "position marked closed" and "ledger row +
equity credit booked" must be DETECTABLE on restart (never silently lost,
never silently double-booked). See core/position_journal.py's module
docstring for full context.

Every test here uses pytest's tmp_path / monkeypatch fixtures exclusively.
None of these tests read, write, or create anything under a REAL
bot/data/ directory.
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from core.position_journal import (
    CLOSED_BOOKED,
    CLOSING,
    OPEN,
    ReconcileReport,
    compact,
    journal_booked,
    journal_closing,
    journal_open,
    startup_reconcile,
)
from execution.auto_recovery import _dict_to_position, _position_to_dict
from execution.position_manager import Position
from feedback.trade_ledger import LEDGER_COLUMNS, TradeLedger


# ---------------------------------------------------------------------------
# position_id identity + serialize/deserialize round-trip
# ---------------------------------------------------------------------------
class TestPositionIdentity:
    def test_position_id_minted_at_construction(self):
        pos = Position(symbol="BTC", side="LONG", entry=100.0, qty=1.0, sl=95.0, tp1=105.0, tp2=110.0)
        assert pos.position_id
        assert isinstance(pos.position_id, str)
        assert len(pos.position_id) == 32  # uuid4().hex

    def test_two_positions_get_different_ids(self):
        p1 = Position(symbol="BTC", side="LONG", entry=100.0, qty=1.0, sl=95.0, tp1=105.0, tp2=110.0)
        p2 = Position(symbol="BTC", side="LONG", entry=100.0, qty=1.0, sl=95.0, tp1=105.0, tp2=110.0)
        assert p1.position_id != p2.position_id

    def test_round_trip_preserves_position_id(self):
        pos = Position(symbol="ETH", side="SHORT", entry=2000.0, qty=2.0, sl=2100.0, tp1=1900.0, tp2=1800.0)
        original_id = pos.position_id
        d = _position_to_dict(pos)
        assert d["position_id"] == original_id
        restored = _dict_to_position(d)
        assert restored.position_id == original_id

    def test_old_dict_without_position_id_loads_with_fresh_id_no_crash(self):
        pos = Position(symbol="SOL", side="LONG", entry=150.0, qty=3.0, sl=140.0, tp1=160.0, tp2=170.0)
        d = _position_to_dict(pos)
        del d["position_id"]  # simulate an OLD persisted dict, pre-0.3b

        restored = _dict_to_position(d)  # must not raise

        assert restored.position_id
        assert isinstance(restored.position_id, str)
        assert len(restored.position_id) == 32

    def test_explicit_empty_position_id_gets_minted(self):
        pos = Position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0, sl=95.0, tp1=105.0, tp2=110.0,
            position_id="",
        )
        assert pos.position_id  # __post_init__ backfills, never stays ""


# ---------------------------------------------------------------------------
# Ledger column: position_id lands in the CSV, readers tolerate it (and its
# absence).
# ---------------------------------------------------------------------------
class TestLedgerPositionIdColumn:
    def test_position_id_in_schema(self):
        assert "position_id" in LEDGER_COLUMNS
        # Appended at the END so pre-existing column positions are unchanged.
        assert LEDGER_COLUMNS[-1] == "position_id"

    def test_record_trade_writes_position_id_from_dict(self, tmp_path):
        led = TradeLedger(data_dir=str(tmp_path))
        led.record_trade({"symbol": "BTC", "side": "LONG", "net_pnl": "10.0", "position_id": "abc123"})
        with open(os.path.join(str(tmp_path), "trade_ledger.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["position_id"] == "abc123"

    def test_record_trade_writes_position_id_from_kwarg(self, tmp_path):
        led = TradeLedger(data_dir=str(tmp_path))
        led.record_trade({"symbol": "BTC", "side": "LONG", "net_pnl": "10.0"}, position_id="def456")
        with open(os.path.join(str(tmp_path), "trade_ledger.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["position_id"] == "def456"

    def test_dict_position_id_wins_over_kwarg(self, tmp_path):
        led = TradeLedger(data_dir=str(tmp_path))
        led.record_trade(
            {"symbol": "BTC", "side": "LONG", "net_pnl": "10.0", "position_id": "from_dict"},
            position_id="from_kwarg",
        )
        with open(os.path.join(str(tmp_path), "trade_ledger.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["position_id"] == "from_dict"

    def test_get_run_stats_parses_ledger_with_position_id_column(self, tmp_path, monkeypatch):
        """csv.DictReader is header-driven -- adding a trailing column must
        not break any reader that iterates by column name."""
        led = TradeLedger(data_dir=str(tmp_path))
        led.record_trade({
            "symbol": "BTC", "side": "LONG", "net_pnl": "12.5",
            "timestamp": "1700000000", "position_id": "posid1",
        })

        from data import trade_source
        ledger_path = tmp_path / "trade_ledger.csv"
        stats = trade_source.get_run_stats(epoch=False, ledger_path=ledger_path)
        assert stats["n"] == 1
        assert stats["net"] == 12.5

    def test_get_run_stats_parses_ledger_without_position_id_column(self, tmp_path):
        """An OLD ledger file (written before this column existed) must
        still parse fine -- csv.DictReader tolerates a header with fewer
        columns than the new schema; missing keys just come back as None
        via row.get(...), never a KeyError."""
        old_cols = [c for c in LEDGER_COLUMNS if c != "position_id"]
        p = tmp_path / "trade_ledger.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=old_cols)
            w.writeheader()
            row = {c: "" for c in old_cols}
            row.update({"trade_id": "abc123def456", "symbol": "BTC", "net_pnl": "5.0", "timestamp": "1700000000"})
            w.writerow(row)

        from data import trade_source
        stats = trade_source.get_run_stats(epoch=False, ledger_path=p)
        assert stats["n"] == 1
        assert stats["net"] == 5.0

    def test_migration_pads_old_rows_with_blank_position_id(self, tmp_path):
        old_cols = [c for c in LEDGER_COLUMNS if c != "position_id"]
        p = os.path.join(str(tmp_path), "trade_ledger.csv")
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=old_cols)
            w.writeheader()
            row = {c: "" for c in old_cols}
            row.update({"trade_id": "abc123def456", "symbol": "BTC"})
            w.writerow(row)

        led = TradeLedger(data_dir=str(tmp_path))
        led.record_trade({"symbol": "ETH", "net_pnl": "1.0", "position_id": "new_pos"})

        with open(p, newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["symbol"] == "BTC"
        assert rows[0]["position_id"] == ""  # old row padded, not corrupted
        assert rows[1]["position_id"] == "new_pos"


# ---------------------------------------------------------------------------
# Journal append primitives
# ---------------------------------------------------------------------------
class TestJournalAppend:
    def test_journal_open_appends_one_line(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", {"side": "LONG"}, symbol="BTC", path=p)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["position_id"] == "pid1"
        assert event["phase"] == OPEN
        assert event["symbol"] == "BTC"
        assert event["meta"] == {"side": "LONG"}

    def test_journal_closing_and_booked_append_in_order(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", {"action": "SL"}, symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        phases = [json.loads(l)["phase"] for l in lines]
        assert phases == [OPEN, CLOSING, CLOSED_BOOKED]

    def test_creates_missing_parent_directory(self, tmp_path):
        p = tmp_path / "nested" / "sub" / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        assert p.exists()


# ---------------------------------------------------------------------------
# startup_reconcile -- exactly-once detection, ledger-is-truth
# ---------------------------------------------------------------------------
class TestStartupReconcile:
    def test_fully_booked_lifecycle_reports_zero_unbooked(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", {"action": "SL"}, symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)

        report = startup_reconcile(set(), set(), path=p)

        assert isinstance(report, ReconcileReport)
        assert report.unbooked == []

    def test_closing_without_booked_and_not_in_ledger_is_unbooked(self, tmp_path):
        """The exact incident class: crash between 'decided to close' and
        'ledger row written'."""
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", {"action": "SL", "price": 100.0}, symbol="BTC", path=p)
        # CRASH -- no journal_booked() call.

        report = startup_reconcile(ledger_position_ids=set(), open_position_ids=set(), path=p)

        assert len(report.unbooked) == 1
        assert report.unbooked[0]["position_id"] == "pid1"
        assert report.duplicates_skipped == []

    def test_position_id_already_in_ledger_never_reported_unbooked(self, tmp_path):
        """LEDGER IS TRUTH: even though the journal's last known phase is
        CLOSING (mid-flight / journal_booked never landed), a position_id
        already present in the ledger must NEVER be re-booked."""
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", {"action": "SL"}, symbol="BTC", path=p)
        # No journal_booked() -- but the ledger DOES have this position_id
        # (e.g. the ledger write succeeded, only the journal_booked() call
        # itself failed non-fatally).

        report = startup_reconcile(ledger_position_ids={"pid1"}, open_position_ids=set(), path=p)

        assert report.unbooked == []
        assert "pid1" in report.duplicates_skipped

    def test_still_open_position_is_healthy_not_unbooked(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)

        report = startup_reconcile(ledger_position_ids=set(), open_position_ids={"pid1"}, path=p)

        assert report.unbooked == []
        assert report.healthy == 1

    def test_duplicate_closed_booked_events_skipped_not_double_reported(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)  # duplicate re-fire

        report = startup_reconcile(ledger_position_ids=set(), open_position_ids=set(), path=p)

        assert report.unbooked == []
        assert report.duplicates_skipped.count("pid1") == 1

    def test_missing_journal_file_reports_empty(self, tmp_path):
        p = tmp_path / "does_not_exist.jsonl"
        report = startup_reconcile(ledger_position_ids=set(), open_position_ids=set(), path=p)
        assert report.unbooked == []
        assert report.duplicates_skipped == []
        assert report.healthy == 0

    def test_torn_last_line_skipped_not_fatal(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)
        # Simulate a crash mid-append: an incomplete JSON fragment as the
        # last line.
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"position_id": "pid2", "phase": "OPEN", "symbol": "E')

        report = startup_reconcile(ledger_position_ids=set(), open_position_ids=set(), path=p)  # must not raise

        assert report.torn_lines_skipped == 1
        # pid1's clean lifecycle is still correctly reconciled despite the
        # torn trailing line.
        assert report.unbooked == []

    def test_multiple_positions_mixed_outcomes(self, tmp_path):
        p = tmp_path / "journal.jsonl"
        # pid1: fully booked
        journal_open("pid1", symbol="BTC", path=p)
        journal_closing("pid1", symbol="BTC", path=p)
        journal_booked("pid1", symbol="BTC", path=p)
        # pid2: crashed before booking, not in ledger -> unbooked
        journal_open("pid2", symbol="ETH", path=p)
        journal_closing("pid2", symbol="ETH", path=p)
        # pid3: still open
        journal_open("pid3", symbol="SOL", path=p)

        report = startup_reconcile(ledger_position_ids=set(), open_position_ids={"pid3"}, path=p)

        assert [u["position_id"] for u in report.unbooked] == ["pid2"]
        # pid1 is CLOSED_BOOKED in the journal (once) with no corroborating
        # ledger row -- not re-booked (journal alone is insufficient
        # evidence), counted healthy with a warning logged for review.
        # pid3 is still open and expected. Neither is "unbooked".
        assert report.healthy == 2  # pid1 + pid3
        assert report.duplicates_skipped == []


# ---------------------------------------------------------------------------
# compact()
# ---------------------------------------------------------------------------
class TestCompact:
    def test_compact_drops_old_fully_booked_entries(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        p = tmp_path / "journal.jsonl"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"position_id": "old1", "phase": OPEN, "ts": old_ts, "symbol": "BTC"}) + "\n")
            f.write(json.dumps({"position_id": "old1", "phase": CLOSING, "ts": old_ts, "symbol": "BTC"}) + "\n")
            f.write(json.dumps({"position_id": "old1", "phase": CLOSED_BOOKED, "ts": old_ts, "symbol": "BTC"}) + "\n")
        journal_open("new1", symbol="ETH", path=p)

        dropped = compact(older_than_days=7.0, path=p)

        assert dropped == 1
        remaining_ids = {json.loads(l)["position_id"] for l in p.read_text(encoding="utf-8").splitlines()}
        assert remaining_ids == {"new1"}

    def test_compact_keeps_recent_and_unbooked_regardless_of_age(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        p = tmp_path / "journal.jsonl"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(p, "a", encoding="utf-8") as f:
            # Old but never booked -- must be kept (still needed for reconcile).
            f.write(json.dumps({"position_id": "old_open", "phase": OPEN, "ts": old_ts, "symbol": "BTC"}) + "\n")

        dropped = compact(older_than_days=7.0, path=p)

        assert dropped == 0
        remaining_ids = {json.loads(l)["position_id"] for l in p.read_text(encoding="utf-8").splitlines()}
        assert remaining_ids == {"old_open"}

    def test_compact_missing_file_is_noop(self, tmp_path):
        p = tmp_path / "does_not_exist.jsonl"
        assert compact(older_than_days=7.0, path=p) == 0
