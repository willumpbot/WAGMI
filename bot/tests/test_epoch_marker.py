"""Tests for Phase 0.5 PR-1: the code-owned equity_epoch.json marker,
data/epoch.py::start_epoch(), and the dual row/id epoch fence in
data/trade_source.py.

Every test here is fully sandboxed via tmp_path + EPOCH_START_FILE env
override + a monkeypatched core.paths.risk_equity_state_path(). No test
reads, writes, or creates anything under the real data/ directory, and
start_epoch() is NEVER called against real/live data (only tmp_path
fixtures, always with an explicit epoch_file= override, which is also the
only way start_epoch() is even willing to run under pytest).

Covers ACID tests D (epoch reset chain) and E (fence integrity) from
BUILD SPEC 0.5, plus the PR-1 backward-compat acceptance bar: a legacy
epoch_start.json-style marker (no epoch_id, no row-count) must fence
IDENTICALLY to the pre-PR-1 pure timestamp fence.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

_BOT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

import core.paths as paths_module  # noqa: E402
import data.epoch as epoch_module  # noqa: E402
import data.trade_source as trade_source_module  # noqa: E402
from feedback.trade_ledger import LEDGER_COLUMNS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(trade_id: str, ts: str, net_pnl: float, epoch_id: str = "") -> dict:
    return {
        "trade_id": trade_id,
        "timestamp": ts,
        "symbol": "BTC",
        "side": "BUY",
        "net_pnl": str(net_pnl),
        "gross_pnl": str(net_pnl),
        "fees": "0",
        "funding": "0",
        "epoch_id": epoch_id,
    }


def _write_ledger(path: Path, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()
        for r in rows:
            full = {c: "" for c in LEDGER_COLUMNS}
            full.update(r)
            writer.writerow(full)


def _append_row(path: Path, row: dict) -> None:
    full = {c: "" for c in LEDGER_COLUMNS}
    full.update(row)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        writer.writerow(full)


def _setup_worktree(tmp_path: Path, monkeypatch) -> dict:
    """Isolated tmp 'data/' directory: a legacy-style marker (pre-PR-1
    schema, no epoch_id/row-count), a risk_equity_state.json, and a 3-row
    ledger fully inside that legacy epoch (epoch_start well before all 3
    rows' timestamps)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    ledger_path = data_dir / "trade_ledger.csv"
    epoch_file = data_dir / "equity_epoch.json"
    risk_path = data_dir / "risk_equity_state.json"

    monkeypatch.setenv("EPOCH_START_FILE", str(epoch_file))
    monkeypatch.setattr(paths_module, "risk_equity_state_path", lambda: risk_path)

    risk_path.write_text(json.dumps({"equity": 4975.26, "peak_equity": 5000.0}), encoding="utf-8")

    epoch_file.write_text(json.dumps({
        "epoch_start": "2020-01-01T00:00:00+00:00",
        "epoch_equity": 5000.0,
        "reason": "legacy baseline",
    }), encoding="utf-8")

    _write_ledger(ledger_path, [
        _row("t1", "2024-01-01T00:00:00+00:00", -5.0),
        _row("t2", "2024-01-02T00:00:00+00:00", 10.0),
        _row("t3", "2024-01-03T00:00:00+00:00", -2.0),
    ])

    return {
        "data_dir": data_dir,
        "ledger_path": ledger_path,
        "epoch_file": epoch_file,
        "risk_path": risk_path,
    }


@pytest.fixture(autouse=True)
def _reset_epoch_cache():
    """data/epoch.py caches the active epoch keyed by (path, mtime). Every
    test here uses a fresh tmp_path so real collisions are impossible, but
    reset defensively so no stale in-memory state can leak between tests."""
    epoch_module._cache["epoch"] = None
    epoch_module._cache["mtime"] = None
    epoch_module._cache["path"] = None
    epoch_module._cache["warned_missing"] = False
    yield
    epoch_module._cache["epoch"] = None
    epoch_module._cache["mtime"] = None
    epoch_module._cache["path"] = None
    epoch_module._cache["warned_missing"] = False


# ---------------------------------------------------------------------------
# PYTEST_CURRENT_TEST guard
# ---------------------------------------------------------------------------

def test_start_epoch_refuses_under_pytest_without_override():
    """The core safety property: under pytest (PYTEST_CURRENT_TEST is set by
    the pytest runner itself for the duration of every test), start_epoch()
    must refuse to run against the real data/ dir unless an explicit
    epoch_file= override is supplied -- mirrors execution/risk.py's
    PYTEST_CURRENT_TEST guard on save_equity_state."""
    with pytest.raises(RuntimeError, match="pytest"):
        epoch_module.start_epoch(5000.0, "no override given")


# ---------------------------------------------------------------------------
# ACID test D — epoch reset chain
# ---------------------------------------------------------------------------

def test_start_epoch_reset_chain(tmp_path, monkeypatch):
    ctx = _setup_worktree(tmp_path, monkeypatch)
    epoch_file = ctx["epoch_file"]
    ledger_path = ctx["ledger_path"]

    # Sanity: before the reset, the legacy epoch reports the 3 seeded rows.
    before = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert before["n"] == 3
    assert before["net"] == 3.0
    assert before["derived_equity"] == 5003.0

    record = epoch_module.start_epoch(
        5000.0, "test reset", ledger_path=ledger_path, epoch_file=epoch_file,
    )

    # New record schema (spec 1a).
    assert record["schema_version"] == 1
    assert record["epoch_id"].startswith("epoch-")
    assert record["epoch_start"]
    assert record["epoch_equity"] == 5000.0
    assert record["start_ledger_row_count"] == 3
    assert record["start_after_trade_id"] == "t3"
    assert record["reason"] == "test reset"
    assert record["prior_epoch_id"] == ""  # legacy marker had none
    assert record["prior_derived_equity"] == 5003.0
    assert record["prior_equity_accumulator"] == 4975.26
    assert record["written_by"] == "data.epoch.start_epoch"
    assert "stamped_at" in record

    # Old marker archived to epoch_history.jsonl BEFORE being overwritten.
    history_path = epoch_file.parent / "epoch_history.jsonl"
    assert history_path.exists()
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    archived = json.loads(lines[0])
    assert archived["epoch_equity"] == 5000.0
    assert archived["reason"] == "legacy baseline"
    assert archived["_archived_from_path"] == str(epoch_file)

    # get_active_epoch(force_reload=True) picks up the new marker immediately.
    active = epoch_module.get_active_epoch(force_reload=True)
    assert active["epoch_id"] == record["epoch_id"]
    assert active["epoch_equity"] == 5000.0
    assert active["start_row_count"] == 3
    assert active["start_after_trade_id"] == "t3"

    # Prior rows fall out of get_run_stats -- clean $5000 epoch, zero trades.
    after = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert after["n"] == 0
    assert after["net"] == 0.0
    assert after["derived_equity"] == 5000.0  # exact

    # A genuinely NEW trade (appended after the fence) counts.
    _append_row(ledger_path, _row("t4", "2024-06-01T00:00:00+00:00", 10.0))
    after2 = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert after2["n"] == 1
    assert after2["net"] == 10.0
    assert after2["derived_equity"] == 5010.0


def test_start_epoch_archives_a_prior_code_owned_marker_too(tmp_path, monkeypatch):
    """A SECOND start_epoch() call must archive the FIRST code-owned marker
    (not just the legacy one), proving the archive chain works across
    multiple resets, not only the legacy->code-owned migration."""
    ctx = _setup_worktree(tmp_path, monkeypatch)
    epoch_file = ctx["epoch_file"]
    ledger_path = ctx["ledger_path"]

    first = epoch_module.start_epoch(
        5000.0, "first reset", ledger_path=ledger_path, epoch_file=epoch_file,
    )
    _append_row(ledger_path, _row("t4", "2024-06-01T00:00:00+00:00", 20.0))

    second = epoch_module.start_epoch(
        5100.0, "second reset", ledger_path=ledger_path, epoch_file=epoch_file,
    )

    assert second["prior_epoch_id"] == first["epoch_id"]
    assert second["prior_derived_equity"] == 5020.0  # 5000 + 20 from t4
    assert second["start_ledger_row_count"] == 4  # t1..t4 raw rows
    assert second["start_after_trade_id"] == "t4"

    history_path = epoch_file.parent / "epoch_history.jsonl"
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    archived_second = json.loads(lines[1])
    assert archived_second["epoch_id"] == first["epoch_id"]


# ---------------------------------------------------------------------------
# ACID test E — fence integrity
# ---------------------------------------------------------------------------

def test_fence_integrity_truncated_ledger_falls_back_to_timestamp_only(tmp_path, monkeypatch, caplog):
    ctx = _setup_worktree(tmp_path, monkeypatch)
    epoch_file = ctx["epoch_file"]
    ledger_path = ctx["ledger_path"]

    epoch_module.start_epoch(5000.0, "test", ledger_path=ledger_path, epoch_file=epoch_file)
    _append_row(ledger_path, _row("t4", "2024-06-01T00:00:00+00:00", 5.0))
    _append_row(ledger_path, _row("t5", "2024-06-02T00:00:00+00:00", 7.0))

    sane = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert sane["n"] == 2
    assert sane["net"] == 12.0

    # Simulate a rewrite that truncates the ledger below the fence's
    # recorded start_ledger_row_count=3 -- e.g. a crash-recovery rewrite.
    # The single remaining row is dated BEFORE the (legacy) epoch_start
    # that was in effect when the fence's own timestamp component was
    # captured, so a correct timestamp-only fallback excludes it.
    _write_ledger(ledger_path, [_row("only", "2019-01-01T00:00:00+00:00", 999.0)])

    with caplog.at_level("ERROR"):
        broken = trade_source_module.get_run_stats(ledger_path=ledger_path)

    assert any("[EPOCH-FENCE]" in rec.message for rec in caplog.records), (
        "expected an [EPOCH-FENCE] ERROR log when the ledger is truncated "
        "below start_ledger_row_count"
    )
    # No crash, and no fabricated number: the fabricated-looking 999.0 row
    # is correctly excluded by the timestamp-only fallback.
    assert broken["n"] == 0
    assert broken["net"] == 0.0


def test_fence_row_index_catches_unparseable_timestamp_row(tmp_path, monkeypatch):
    """A genuinely post-reset row (raw ordinal >= start_ledger_row_count)
    whose timestamp field is garbage must still count as in-epoch. Pre-PR-1
    (timestamp-only) fencing dropped it silently: _row_ts() -> None -> 0,
    and 0 >= epoch_start_ts is False. The row-position fence fixes this."""
    ctx = _setup_worktree(tmp_path, monkeypatch)
    epoch_file = ctx["epoch_file"]
    ledger_path = ctx["ledger_path"]

    epoch_module.start_epoch(5000.0, "test", ledger_path=ledger_path, epoch_file=epoch_file)
    _append_row(ledger_path, _row("t4", "not-a-timestamp", 42.0))

    stats = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert stats["n"] == 1
    assert stats["net"] == 42.0
    assert stats["derived_equity"] == 5042.0


# ---------------------------------------------------------------------------
# Backward-compat acceptance bar
# ---------------------------------------------------------------------------

def test_legacy_marker_backward_compat_identical_to_ts_only(tmp_path, monkeypatch):
    """A legacy epoch_start.json-style marker (no epoch_id, no row-count)
    must fence IDENTICALLY to the pre-PR-1 pure timestamp fence -- this is
    the PR-1 acceptance bar: zero numeric change to the CURRENT live epoch
    until the first start_epoch() call."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ledger_path = data_dir / "trade_ledger.csv"
    legacy_marker = data_dir / "epoch_start.json"

    epoch_start_iso = "2020-01-01T00:00:00+00:00"
    legacy_marker.write_text(json.dumps({
        "epoch_start": epoch_start_iso,
        "epoch_equity": 1000.0,
        "reason": "legacy",
    }), encoding="utf-8")
    monkeypatch.setenv("EPOCH_START_FILE", str(legacy_marker))

    _write_ledger(ledger_path, [
        _row("a", "2019-12-31T00:00:00+00:00", -100.0),  # before epoch -> excluded
        _row("b", "2020-06-01T00:00:00+00:00", 50.0),    # after epoch -> included
        _row("c", "2020-07-01T00:00:00+00:00", 25.0),    # after epoch -> included
    ])

    stats = trade_source_module.get_run_stats(ledger_path=ledger_path)
    assert stats["epoch_id"] == ""
    assert stats["n"] == 2
    assert stats["net"] == 75.0
    assert stats["derived_equity"] == 1075.0

    # Directly prove the dual-fence formula reduces to ts-only when
    # start_row_count == 0 (the legacy/default value).
    trades = trade_source_module.load_closed_trades(ledger_path=ledger_path)
    cutoff = trade_source_module._row_ts({"timestamp": epoch_start_iso})
    dual = trade_source_module._epoch_filter(trades, cutoff, start_row_count=0, active_epoch_id="")
    naive_ts_only = [t for t in trades if (trade_source_module._row_ts(t) or 0) >= cutoff]
    assert [t["pnl"] for t in dual] == [t["pnl"] for t in naive_ts_only]
    assert len(dual) == 2


def test_active_epoch_defaults_row_fields_when_missing(tmp_path, monkeypatch):
    """get_active_epoch() must surface start_row_count=0 / start_after_trade_id=""
    defaults for a legacy marker missing those keys entirely, and for the
    no-file-at-all fallback."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy_marker = data_dir / "epoch_start.json"
    legacy_marker.write_text(json.dumps({
        "epoch_start": "2020-01-01T00:00:00+00:00",
        "epoch_equity": 1000.0,
    }), encoding="utf-8")
    monkeypatch.setenv("EPOCH_START_FILE", str(legacy_marker))

    active = epoch_module.get_active_epoch(force_reload=True)
    assert active["start_row_count"] == 0
    assert active["start_after_trade_id"] == ""

    # Missing file entirely -> fallback epoch, same defaults.
    monkeypatch.setenv("EPOCH_START_FILE", str(data_dir / "does_not_exist.json"))
    fallback = epoch_module.get_active_epoch(force_reload=True)
    assert fallback["start_row_count"] == 0
    assert fallback["start_after_trade_id"] == ""
    assert fallback["epoch_equity"] is None
