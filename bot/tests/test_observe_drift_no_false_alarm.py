"""Tests for Phase 0.5 PR-4 (observe-mode equity-drift false-alarm fix).

Root cause under test: `execution/risk.py::RiskManager._reconcile_equity_
with_ledger()` compared the mutable accumulator (`self.equity`) against the
ledger-derived truth (`EquityEngine`/`get_run_stats`) with zero correction
for open positions. TP1 partial-close legs land in `self.equity`
immediately (`multi_strategy_main.py`'s `update_equity()` call) but
`trade_ledger.csv` only gets a row once a position fully terminates
(`_is_terminal_close` gate) -- so an open, partially-TP1'd position looked
like phantom drift (and the "derived" side looked frozen/stale) until its
final close, and the false alarm fired at ERROR level, polluting logs.

This suite proves, fully sandboxed (tmp_path ledger + EPOCH_START_FILE
override, no real data/ touched):
  1. The `open_realized_pnl` correction term is load-bearing: without it, an
     open position's unledgered TP1 leg reads as drift and fires a WARNING;
     with it (computed the way multi_strategy_main.py now computes it --
     sum of non-CLOSED positions' realized_pnl), the drift is ~0 and
     nothing fires.
  2. Zero open positions + a consistent ledger/accumulator -> drift ~0, no
     alarm (baseline, unaffected by the fix).
  3. A GENUINE drift ($5 off, no open positions) still fires -- the fix
     does not over-suppress real drift.
  4. The drift log, when it fires, is WARNING (or below) -- never ERROR.

No test reads, writes, or creates anything under the real data/ directory.
Mirrors tests/test_equity_engine.py's sandboxing conventions.
"""

import csv
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BOT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

import data.epoch as epoch_module  # noqa: E402
import data.trade_source as trade_source_module  # noqa: E402
from execution.risk import RiskManager  # noqa: E402
from feedback.trade_ledger import LEDGER_COLUMNS  # noqa: E402

_DRIFT_LOGGER_NAME = "bot.execution.risk"


# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_equity_engine.py)
# ---------------------------------------------------------------------------

def _row(trade_id: str, ts: str, net_pnl: float, funding: float = 0.0, epoch_id: str = "") -> dict:
    return {
        "trade_id": trade_id,
        "timestamp": ts,
        "symbol": "BTC",
        "side": "BUY",
        "net_pnl": str(net_pnl),
        "gross_pnl": str(net_pnl),
        "fees": "0",
        "funding": str(funding),
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


def _write_epoch_marker(path: Path, epoch_equity, epoch_start: str = "2020-01-01T00:00:00+00:00") -> None:
    payload = {"epoch_start": epoch_start, "reason": "test"}
    if epoch_equity is not None:
        payload["epoch_equity"] = epoch_equity
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup(tmp_path: Path, monkeypatch, epoch_equity=5000.0):
    """Isolated tmp data dir: epoch marker + a 3-row ledger (net = -5+10-2 = 3),
    matching test_equity_engine.py's fixture so derived_equity == 5003.0."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ledger_path = data_dir / "trade_ledger.csv"
    epoch_file = data_dir / "equity_epoch.json"

    monkeypatch.setenv("EPOCH_START_FILE", str(epoch_file))
    _write_epoch_marker(epoch_file, epoch_equity)
    _write_ledger(ledger_path, [
        _row("t1", "2024-01-01T00:00:00+00:00", -5.0),
        _row("t2", "2024-01-02T00:00:00+00:00", 10.0, funding=0.5),
        _row("t3", "2024-01-03T00:00:00+00:00", -2.0),
    ])
    monkeypatch.setattr(trade_source_module, "LEDGER_CSV", ledger_path)
    return {"data_dir": data_dir, "ledger_path": ledger_path, "epoch_file": epoch_file}


def _make_rm(equity: float) -> RiskManager:
    rm = RiskManager(starting_equity=equity, load_persisted_equity=False)
    rm.equity = equity
    return rm


def _fake_pos_mgr(realized_pnls_by_state):
    """A minimal stand-in for execution.position_manager.PositionManager --
    only the `.positions` dict of objects exposing `.realized_pnl`/`.state`
    that multi_strategy_main.py's open_realized_pnl sum reads.

    Args:
        realized_pnls_by_state: list of (state, realized_pnl) tuples.
    """
    positions = {}
    for i, (state, pnl) in enumerate(realized_pnls_by_state):
        positions[f"SYM{i}"] = SimpleNamespace(state=state, realized_pnl=pnl)
    return SimpleNamespace(positions=positions)


def _open_realized_pnl_sum(pos_mgr) -> float:
    """Exactly mirrors the sum multi_strategy_main.py now computes at the
    update_equity() call site (execution/risk.py-adjacent, msm.py ~3805)."""
    return sum(
        p.realized_pnl for p in pos_mgr.positions.values()
        if getattr(p, "state", None) != "CLOSED"
    )


@pytest.fixture(autouse=True)
def _reset_epoch_cache():
    epoch_module._cache["epoch"] = None
    epoch_module._cache["mtime"] = None
    epoch_module._cache["path"] = None
    epoch_module._cache["warned_missing"] = False
    yield
    epoch_module._cache["epoch"] = None
    epoch_module._cache["mtime"] = None
    epoch_module._cache["path"] = None
    epoch_module._cache["warned_missing"] = False


def _unset_pytest_guard(monkeypatch):
    """_reconcile_equity_with_ledger() short-circuits under
    PYTEST_CURRENT_TEST (same guard as save_equity_state) so unit tests are
    deterministic/I-O-free by default. These tests are specifically
    exercising that method's log/alarm behavior, so they must remove the
    guard -- established pattern, see tests/test_pollution_gate.py.

    NOT an autouse fixture: pytest re-sets PYTEST_CURRENT_TEST itself right
    as the "call" phase begins (after fixture setup finishes), so an
    autouse fixture's delenv during setup gets silently overwritten by the
    time the test body runs. Must be called explicitly from inside each
    test body instead (same phase pytest's own re-set happens in, so ours
    wins)."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


# ---------------------------------------------------------------------------
# 1. open_realized_pnl correction suppresses the false alarm (load-bearing)
# ---------------------------------------------------------------------------

def test_open_position_tp1_leg_without_correction_false_alarms(tmp_path, monkeypatch, caplog):
    """Reproduces the reported false alarm: an open position banked a $15
    TP1 leg to the accumulator, no ledger row yet (ledger-derived == 5003).
    Without the open_realized_pnl correction, this reads as $15 drift and
    fires the WARNING (pre-fix: fired at ERROR)."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0 + 15.0)  # accumulator ran "hot" by the unledgered TP1 leg

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger()  # open_realized_pnl defaults to 0.0

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert len(drift_records) == 1, "expected the false alarm to fire without the correction term"
    assert rm._last_ledger_drift["drift"] == pytest.approx(15.0)


def test_open_position_correction_suppresses_the_false_alarm(tmp_path, monkeypatch, caplog):
    """Same scenario as above, but the caller now sums open (non-CLOSED)
    positions' realized_pnl the way multi_strategy_main.py does and passes
    it through -- the phantom drift must vanish and NO log fires."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0 + 15.0)

    # One open position (TRAILING, after its TP1 leg) carrying the exact
    # $15 that's already in the accumulator but not yet in the ledger.
    pos_mgr = _fake_pos_mgr([("TRAILING", 15.0)])
    open_realized_pnl = _open_realized_pnl_sum(pos_mgr)
    assert open_realized_pnl == pytest.approx(15.0)

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=open_realized_pnl)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert drift_records == [], "open-position correction must suppress the phantom drift alarm"
    assert rm._last_ledger_drift["drift"] == pytest.approx(0.0, abs=1e-6)


def test_closed_positions_excluded_from_open_realized_pnl_sum():
    """A CLOSED position's realized_pnl is already in the ledger (or about
    to be, via the same close event) -- it must NOT be double-counted into
    the correction term. Only non-CLOSED positions contribute."""
    pos_mgr = _fake_pos_mgr([
        ("TRAILING", 15.0),   # open, TP1'd -- counts
        ("CLOSED", 42.0),     # just terminated -- excluded
        ("OPEN", 0.0),        # open, no TP1 yet -- counts (contributes 0)
    ])
    assert _open_realized_pnl_sum(pos_mgr) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 2. Zero open positions + consistent ledger -> no alarm (baseline)
# ---------------------------------------------------------------------------

def test_zero_open_positions_consistent_ledger_no_alarm(tmp_path, monkeypatch, caplog):
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    # Accumulator matches derived (5003.0) to within a couple cents -- the
    # kind of residual float noise observed live with 0 open positions.
    rm = _make_rm(5003.02)

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=0.0)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert drift_records == []
    assert abs(rm._last_ledger_drift["drift"]) < 0.50


# ---------------------------------------------------------------------------
# 3. Genuine drift (no open positions) is still detected -- no over-suppression
# ---------------------------------------------------------------------------

def test_genuine_drift_with_no_open_positions_still_fires(tmp_path, monkeypatch, caplog):
    """A real $5 accumulator/ledger mismatch, zero open positions (so
    open_realized_pnl is legitimately 0.0) -- the correction term must not
    swallow this. It's real drift and must still WARNING."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0 + 5.0)  # genuine $5 drift, nothing to explain it away

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=0.0)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert len(drift_records) == 1, "genuine drift with no open positions must still alarm"
    assert rm._last_ledger_drift["drift"] == pytest.approx(5.0)


def test_open_position_correction_does_not_mask_additional_real_drift(tmp_path, monkeypatch, caplog):
    """An open position's TP1 leg ($15, correctly absorbed) coexists with a
    genuine extra $5 of unexplained drift on top -- the correction must
    cancel exactly the $15 it's given, leaving the real $5 still visible
    and still alarming."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0 + 15.0 + 5.0)

    pos_mgr = _fake_pos_mgr([("TRAILING", 15.0)])
    open_realized_pnl = _open_realized_pnl_sum(pos_mgr)

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=open_realized_pnl)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert len(drift_records) == 1
    assert rm._last_ledger_drift["drift"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 4. Log level is WARNING (or below), never ERROR
# ---------------------------------------------------------------------------

def test_drift_alarm_logs_at_warning_not_error(tmp_path, monkeypatch, caplog):
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0 + 5.0)

    with caplog.at_level(logging.DEBUG, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=0.0)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert len(drift_records) == 1
    assert drift_records[0].levelno == logging.WARNING
    assert drift_records[0].levelname == "WARNING"
    # Hard guard: no drift record at ERROR level, under any scenario above.
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_update_equity_threads_open_realized_pnl_through(tmp_path, monkeypatch, caplog):
    """End-to-end through the public update_equity() entry point (what
    multi_strategy_main.py actually calls): passing open_realized_pnl
    suppresses the alarm exactly as the private method does directly."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    rm = _make_rm(5003.0)  # starts matched to derived
    # update_equity() also calls save_equity_state(), which persists to the
    # REAL (relative) "data/risk_equity_state.json" path and is normally
    # blocked by the same PYTEST_CURRENT_TEST guard we just removed above
    # to exercise the drift log. No-op it here so this test can't write
    # outside tmp_path/the sandbox -- this test is about the
    # open_realized_pnl threading, not persistence.
    monkeypatch.setattr(rm, "save_equity_state", lambda: None)

    pos_mgr = _fake_pos_mgr([("TRAILING", 15.0)])
    open_realized_pnl = _open_realized_pnl_sum(pos_mgr)

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        # Booking the same $15 TP1 leg pnl to the accumulator via the public
        # API, alongside the matching open_realized_pnl correction.
        rm.update_equity(15.0, open_realized_pnl=open_realized_pnl)

    drift_records = [r for r in caplog.records if "EQUITY-LEDGER-DRIFT" in r.message]
    assert drift_records == []
    assert rm.equity == pytest.approx(5018.0)  # accumulator mutation still happens (observe-only)


def test_reconcile_never_mutates_equity_when_derive_flag_off(tmp_path, monkeypatch, caplog):
    """Observe-only guarantee: even with a genuine drift that fires the
    alarm, self.equity is untouched unless EQUITY_DERIVE_FROM_LEDGER=true
    (default false in tests -- not set here)."""
    _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    _unset_pytest_guard(monkeypatch)
    monkeypatch.delenv("EQUITY_DERIVE_FROM_LEDGER", raising=False)
    starting = 5003.0 + 5.0
    rm = _make_rm(starting)

    with caplog.at_level(logging.WARNING, logger=_DRIFT_LOGGER_NAME):
        rm._reconcile_equity_with_ledger(open_realized_pnl=0.0)

    assert rm.equity == pytest.approx(starting), "observe-mode must never mutate equity"
