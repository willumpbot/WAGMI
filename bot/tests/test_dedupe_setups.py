"""Tests for core.dedupe.dedupe_setups — the canonical scanner-re-log collapse.

Mirrors tools/resolve_missed_trades.py:_dedupe_setups semantics: same
symbol+side, entry within 0.4%, timestamp within 3h -> one cluster, earliest
row kept. See core/dedupe.py docstring for the verified root cause (10x-33x
duplicate scanner re-logs per real setup).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dedupe import dedupe_setups, is_same_setup


def _row(symbol="SOL", side="SELL", entry=100.0, ts=1_000_000.0, **extra):
    d = {"symbol": symbol, "side": side, "entry_price": entry, "timestamp": ts}
    d.update(extra)
    return d


def test_30_duplicates_collapse_to_1():
    rows = [_row(ts=1_000_000.0 + i * 30) for i in range(30)]  # 30s apart scanner ticks
    out = dedupe_setups(rows)
    assert len(out) == 1
    # earliest row kept
    assert out[0]["timestamp"] == 1_000_000.0


def test_distinct_setups_preserved():
    rows = [
        _row(symbol="SOL", side="SELL", entry=100.0, ts=1_000_000.0),
        _row(symbol="SOL", side="SELL", entry=100.0, ts=1_000_030.0),  # dup of above
        _row(symbol="SOL", side="BUY", entry=100.0, ts=1_000_000.0),   # different side
        _row(symbol="ETH", side="SELL", entry=100.0, ts=1_000_000.0),  # different symbol
        _row(symbol="SOL", side="SELL", entry=150.0, ts=1_000_000.0),  # entry too far (>0.4%)
        _row(symbol="SOL", side="SELL", entry=100.0, ts=1_020_000.0),  # ts too far (>3h)
    ]
    out = dedupe_setups(rows)
    # 5 distinct setups: SOL/SELL@100 (dedup pair), SOL/BUY@100, ETH/SELL@100,
    # SOL/SELL@150, SOL/SELL@100(+ >3h)
    assert len(out) == 5


def test_missing_entry_rows_preserved():
    rows = [
        _row(ts=1_000_000.0),
        {"symbol": "SOL", "side": "SELL", "timestamp": 1_000_030.0},  # no entry_price
        {"symbol": "SOL", "side": "SELL", "entry_price": None, "timestamp": 1_000_060.0},
        {"symbol": "SOL", "side": "SELL", "entry_price": "not-a-number", "timestamp": 1_000_090.0},
    ]
    out = dedupe_setups(rows)
    # The one clean row clusters with itself (1); the 3 unparseable-entry rows
    # are each kept standalone rather than dropped or crashing.
    assert len(out) == 4


def test_missing_timestamp_rows_preserved():
    rows = [
        _row(ts=1_000_000.0),
        {"symbol": "SOL", "side": "SELL", "entry_price": 100.0},  # no timestamp
        {"symbol": "SOL", "side": "SELL", "entry_price": 100.0, "timestamp": None},
    ]
    out = dedupe_setups(rows)
    assert len(out) == 3


def test_empty_input():
    assert dedupe_setups([]) == []


def test_configurable_field_names():
    rows = [
        {"symbol": "BTC", "side": "BUY", "entry": 50000.0, "created_at": 1000.0},
        {"symbol": "BTC", "side": "BUY", "entry": 50010.0, "created_at": 1030.0},
        {"symbol": "BTC", "side": "BUY", "entry": 60000.0, "created_at": 1000.0},
    ]
    out = dedupe_setups(rows, entry_key="entry", ts_key="created_at")
    assert len(out) == 2


def test_is_same_setup_direct():
    a = _row(entry=100.0, ts=1_000_000.0)
    b = _row(entry=100.3, ts=1_000_100.0)  # within tol
    c = _row(entry=105.0, ts=1_000_000.0)  # outside 0.4%
    assert is_same_setup(a, b) is True
    assert is_same_setup(a, c) is False


def test_fail_neutral_on_garbage_input():
    # Should never raise — falls back to returning input unchanged.
    out = dedupe_setups(None)
    assert out is None
