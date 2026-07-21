"""Tests for core/atomic_state.py -- crash-safe JSON/text state writes.

Guards against a repeat of the position_state.json data-loss class: a
process death mid-write leaving a truncated file, or (the specific bug
found in execution/auto_recovery.py's old remove-then-rename sequence) NO
file at all. See core/atomic_state.py's module docstring for full context.

Every test here uses pytest's tmp_path fixture exclusively. None of these
tests read, write, or create anything under a REAL bot/data/ directory.
"""
from __future__ import annotations

import json
import os
import threading

import pytest

from core.atomic_state import (
    atomic_write_json,
    atomic_write_text,
    read_json_or_none,
)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------
def test_round_trip_json(tmp_path):
    target = tmp_path / "state.json"
    data = {"equity": 1234.5678, "positions": {"BTC": {"side": "long", "qty": 1}}}
    atomic_write_json(target, data)
    assert json.loads(target.read_text(encoding="utf-8")) == data


def test_round_trip_via_read_json_or_none(tmp_path):
    target = tmp_path / "state.json"
    data = {"a": 1, "b": [1, 2, 3], "c": None}
    atomic_write_json(target, data)
    assert read_json_or_none(target) == data


def test_atomic_write_text_round_trip(tmp_path):
    target = tmp_path / "note.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"


def test_creates_missing_parent_directory(tmp_path):
    target = tmp_path / "nested" / "sub" / "state.json"
    atomic_write_json(target, {"x": 1})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}


def test_no_orphan_tmp_file_left_behind_on_success(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"x": 1})
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Torn-write / crash simulation
# ---------------------------------------------------------------------------
def test_crash_before_replace_leaves_original_file_intact(tmp_path, monkeypatch):
    """Simulate a process death AFTER the tmp file is fully written+fsync'd
    but BEFORE os.replace() swaps it onto the target -- the original file
    must survive untouched, and no orphan tmp file should remain."""
    target = tmp_path / "state.json"
    original = {"equity": 1000.0, "saved_at": "epoch-0"}
    atomic_write_json(target, original)

    real_replace = os.replace

    def _boom(src, dst):
        raise OSError("simulated crash mid-replace")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        atomic_write_json(target, {"equity": 9999.0, "saved_at": "epoch-1"})

    monkeypatch.setattr(os, "replace", real_replace)

    # Original file must be completely intact (not truncated, not swapped).
    assert json.loads(target.read_text(encoding="utf-8")) == original

    # No orphan .tmp file left in the directory.
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == [], f"orphan tmp file(s) left behind: {leftovers}"


def test_crash_before_replace_on_first_ever_write_leaves_no_file(tmp_path, monkeypatch):
    """If the target never existed and the replace fails, the target must
    still not exist afterward (never a half-written file at the real
    path), and the tmp file must be cleaned up."""
    target = tmp_path / "state.json"

    def _boom(src, dst):
        raise OSError("simulated crash mid-replace")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        atomic_write_json(target, {"equity": 1.0})

    assert not target.exists()
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"orphan tmp file(s) left behind: {leftovers}"


# ---------------------------------------------------------------------------
# read_json_or_none robustness
# ---------------------------------------------------------------------------
def test_read_json_or_none_missing_file(tmp_path):
    assert read_json_or_none(tmp_path / "does_not_exist.json") is None


def test_read_json_or_none_empty_file(tmp_path):
    target = tmp_path / "empty.json"
    target.write_text("", encoding="utf-8")
    assert read_json_or_none(target) is None


def test_read_json_or_none_corrupt_truncated_file(tmp_path):
    target = tmp_path / "corrupt.json"
    # Simulate exactly the failure class this module exists to prevent: a
    # write that died mid-flight, leaving a truncated JSON fragment.
    target.write_text('{"equity": 1234.5, "positions": {"BTC": {"sid', encoding="utf-8")
    assert read_json_or_none(target) is None


def test_read_json_or_none_does_not_raise(tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("not json at all {{{", encoding="utf-8")
    # Must never raise -- callers rely on None, not an exception.
    result = read_json_or_none(target)
    assert result is None


# ---------------------------------------------------------------------------
# Concurrency: many threads writing the same path must never tear the file.
# ---------------------------------------------------------------------------
def test_concurrent_writes_never_produce_a_torn_file(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"writer": -1, "payload": "x" * 500})

    n_threads = 24
    errors = []

    def _writer(i):
        try:
            # Vary payload size to increase the chance a naive
            # non-atomic writer would produce an interleaved/torn file.
            data = {"writer": i, "payload": ("y" * (100 + i)) + str(i)}
            atomic_write_json(target, data)
        except Exception as e:  # pragma: no cover - diagnostic only
            errors.append(e)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"writer thread(s) raised: {errors}"

    # The file must ALWAYS parse as one complete, self-consistent JSON
    # object written by exactly one of the threads -- never an
    # interleaved/truncated mix of two writes.
    raw = target.read_text(encoding="utf-8")
    parsed = json.loads(raw)  # raises if torn/interleaved
    assert "writer" in parsed and "payload" in parsed
    expected_payload = ("y" * (100 + parsed["writer"])) + str(parsed["writer"])
    assert parsed["payload"] == expected_payload


# ---------------------------------------------------------------------------
# Phase 0.3c: the two remaining state writers now route through
# atomic_write_json instead of plain open('w')+json.dump -- see
# execution/adaptive_risk.py (AdaptiveRiskManager + AdaptiveSizer) and
# execution/momentum_tracker.py (MomentumTracker). These tests assert the
# call happens (via monkeypatch) rather than re-testing atomic_write_json's
# own guarantees, which are already covered above.
# ---------------------------------------------------------------------------
def test_adaptive_risk_manager_save_state_uses_atomic_write_json(tmp_path, monkeypatch):
    import execution.adaptive_risk as adaptive_risk

    calls = []

    def _fake_atomic_write_json(path, data, *, indent=2):
        calls.append((path, data))

    monkeypatch.setattr(adaptive_risk, "atomic_write_json", _fake_atomic_write_json)
    monkeypatch.setattr(adaptive_risk, "_STATE_PATH", str(tmp_path / "adaptive_risk_state.json"))
    monkeypatch.setattr(
        adaptive_risk.AdaptiveRiskManager, "_backfill_from_trade_dna", lambda self: None
    )

    mgr = adaptive_risk.AdaptiveRiskManager(base_risk=0.01)
    mgr.record_outcome(win=True, regime="trend")

    assert calls, "atomic_write_json was not called by AdaptiveRiskManager._save_state"
    path, data = calls[-1]
    assert path == str(tmp_path / "adaptive_risk_state.json")
    assert data["recent_outcomes"] == [True]
    assert data["regime_wr"]["trend"] == {"wins": 1, "total": 1}


def test_adaptive_sizer_save_state_uses_atomic_write_json(tmp_path, monkeypatch):
    import execution.adaptive_risk as adaptive_risk

    calls = []

    def _fake_atomic_write_json(path, data, *, indent=2):
        calls.append((path, data))

    monkeypatch.setattr(adaptive_risk, "atomic_write_json", _fake_atomic_write_json)
    monkeypatch.setattr(
        adaptive_risk, "_ADAPTIVE_SIZER_STATE_PATH", str(tmp_path / "adaptive_sizer_state.json")
    )
    monkeypatch.setattr(
        adaptive_risk.AdaptiveSizer, "_backfill_from_trade_dna", lambda self: None
    )

    sizer = adaptive_risk.AdaptiveSizer(window=20, max_boost=1.5, min_floor=0.5)
    sizer.record_outcome("BTC", won=True)

    assert calls, "atomic_write_json was not called by AdaptiveSizer._save_state"
    path, data = calls[-1]
    assert path == str(tmp_path / "adaptive_sizer_state.json")
    assert data["outcomes"]["BTC"] == [True]


def test_momentum_tracker_save_state_uses_atomic_write_json(tmp_path, monkeypatch):
    import sys

    import execution.momentum_tracker as momentum_tracker

    calls = []

    def _fake_atomic_write_json(path, data, *, indent=2):
        calls.append((path, data))

    monkeypatch.setattr(momentum_tracker, "atomic_write_json", _fake_atomic_write_json)
    # _read_ledger_closes() is a no-op for a nonexistent ledger path -- keeps
    # this test hermetic (no read of the real bot/data/trade_ledger.csv).
    monkeypatch.setattr(momentum_tracker, "_LEDGER_PATH", str(tmp_path / "no_such_ledger.csv"))
    # MomentumTracker's _load_state/_save_state guard against persisting
    # under a live pytest process (see the module's own pollution-hardening
    # comment) -- lift that guard for this one test so we can observe the
    # atomic_write_json call, exactly like _load_state is deliberately
    # bypassed in the sizer/manager fixtures above via _backfill patches.
    monkeypatch.delitem(sys.modules, "pytest", raising=False)

    state_path = str(tmp_path / "momentum_state.json")
    tracker = momentum_tracker.MomentumTracker(state_path=state_path)
    tracker.record_outcome("BTC", True)

    assert calls, "atomic_write_json was not called by MomentumTracker._save_state"
    path, data = calls[-1]
    assert path == state_path
    assert data["streaks"]["BTC"] == 1


def test_concurrent_writes_to_different_paths_do_not_block_forever(tmp_path):
    """Sanity check that per-path locking doesn't serialize writers of
    UNRELATED files behind a single global lock forever (i.e. this
    completes promptly rather than hanging)."""
    n = 12
    threads = []
    errors = []

    def _writer(i):
        try:
            atomic_write_json(tmp_path / f"state_{i}.json", {"i": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    for i in range(n):
        t = threading.Thread(target=_writer, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    for i in range(n):
        assert json.loads((tmp_path / f"state_{i}.json").read_text()) == {"i": i}
