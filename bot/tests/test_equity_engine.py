"""Tests for Phase 0.5 PR-2: EquityEngine (execution/equity_engine.py), the
read-only derive()/reconcile() façade over data/trade_source.py's canonical
get_run_stats(), and the no-behavior-change delegation of
execution/risk.py::RiskManager.compute_ledger_drift() onto it.

Every test is fully sandboxed via tmp_path + EPOCH_START_FILE env override +
explicit ledger_path kwargs (EquityEngine) / a monkeypatched
data.trade_source.LEDGER_CSV (for the RiskManager delegation tests, since
compute_ledger_drift() takes no ledger_path parameter). No test reads,
writes, or creates anything under the real data/ directory.
"""

import csv
import inspect
import json
import sys
from pathlib import Path

import pytest

_BOT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

import data.epoch as epoch_module  # noqa: E402
import data.trade_source as trade_source_module  # noqa: E402
from execution.equity_engine import EquityEngine  # noqa: E402
from feedback.trade_ledger import LEDGER_COLUMNS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_epoch_marker.py's conventions)
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
    """Isolated tmp data dir: epoch marker + a 3-row ledger (net = -5+10-2 = 3)."""
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
    return {"data_dir": data_dir, "ledger_path": ledger_path, "epoch_file": epoch_file}


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


# ---------------------------------------------------------------------------
# derive()
# ---------------------------------------------------------------------------

def test_derive_returns_epoch_base_plus_ledger_net(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    # 5000 + (-5 + 10 - 2) == 5003.0
    assert engine.derive(ledger_path=ctx["ledger_path"]) == 5003.0


def test_derive_adds_open_realized_pnl(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    assert engine.derive(open_realized_pnl=25.0, ledger_path=ctx["ledger_path"]) == 5028.0


def test_derive_returns_none_when_epoch_equity_unset(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=None)
    engine = EquityEngine()
    assert engine.derive(ledger_path=ctx["ledger_path"]) is None
    # None discipline holds even with a nonzero open_realized_pnl passed in --
    # never fabricate a number just because the caller supplied a correction.
    assert engine.derive(open_realized_pnl=100.0, ledger_path=ctx["ledger_path"]) is None


# ---------------------------------------------------------------------------
# reconcile() — base case + the 3 correction terms (each proven load-bearing)
# ---------------------------------------------------------------------------

def test_reconcile_matching_accumulator_is_zero_drift(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    result = engine.reconcile(accumulator=5003.0, ledger_path=ctx["ledger_path"])
    assert result is not None
    assert result["derived"] == 5003.0
    assert result["accumulator"] == 5003.0
    assert result["adjusted_drift"] == 0.0
    assert result["epoch_id"] == ""  # legacy marker, no epoch_id
    assert result["components"] == {
        "open_realized_pnl": 0.0, "pending_pnl": 0.0, "funding_addback": 0.0,
    }


def test_reconcile_returns_none_when_no_epoch_baseline(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=None)
    engine = EquityEngine()
    assert engine.reconcile(accumulator=1234.0, ledger_path=ctx["ledger_path"]) is None


def test_reconcile_open_realized_pnl_is_load_bearing(tmp_path, monkeypatch):
    """A TP1 leg already booked to the accumulator (+15) but with no ledger
    row yet must be absorbed by open_realized_pnl, or it reads as drift."""
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    accumulator = 5003.0 + 15.0  # ledger-derived (5003) + unledgered TP1 leg

    without = engine.reconcile(accumulator=accumulator, ledger_path=ctx["ledger_path"])
    assert without["adjusted_drift"] == pytest.approx(15.0)

    with_term = engine.reconcile(
        accumulator=accumulator, open_realized_pnl=15.0, ledger_path=ctx["ledger_path"],
    )
    assert with_term["adjusted_drift"] == pytest.approx(0.0)


def test_reconcile_pending_pnl_is_load_bearing(tmp_path, monkeypatch):
    """The just-closed trade's net PnL, booked to equity but not yet
    ledgered (the update_equity -> ledger-row-write window), must be
    absorbed by pending_pnl."""
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    accumulator = 5003.0 - 8.25  # a closing trade's -$8.25 booked, ledger row not written yet

    without = engine.reconcile(accumulator=accumulator, ledger_path=ctx["ledger_path"])
    assert without["adjusted_drift"] == pytest.approx(-8.25)

    with_term = engine.reconcile(
        accumulator=accumulator, pending_pnl=-8.25, ledger_path=ctx["ledger_path"],
    )
    assert with_term["adjusted_drift"] == pytest.approx(0.0)


def test_reconcile_funding_addback_is_load_bearing(tmp_path, monkeypatch):
    """Funding already counted inside ledger net_pnl (per the gross-fees+
    funding==net identity) must be addable back when the accumulator side
    doesn't separately deduct funding (EQUITY_DEDUCT_FUNDING=false)."""
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    accumulator = 5003.0 + 0.5  # accumulator ran 0.5 "hot" vs ledger-derived

    without = engine.reconcile(accumulator=accumulator, ledger_path=ctx["ledger_path"])
    assert without["adjusted_drift"] == pytest.approx(0.5)

    with_term = engine.reconcile(
        accumulator=accumulator, funding_addback=0.5, ledger_path=ctx["ledger_path"],
    )
    assert with_term["adjusted_drift"] == pytest.approx(0.0)


def test_reconcile_all_three_terms_compose_additively(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    engine = EquityEngine()
    accumulator = 5003.0 + 15.0 - 8.25 + 0.5
    result = engine.reconcile(
        accumulator=accumulator,
        open_realized_pnl=15.0,
        pending_pnl=-8.25,
        funding_addback=0.5,
        ledger_path=ctx["ledger_path"],
    )
    assert result["adjusted_drift"] == pytest.approx(0.0)
    assert result["components"] == {
        "open_realized_pnl": 15.0, "pending_pnl": -8.25, "funding_addback": 0.5,
    }


# ---------------------------------------------------------------------------
# NO unrealized MTM — the locked open-position policy
# ---------------------------------------------------------------------------

def test_engine_never_references_unrealized_mtm():
    """Static guard on the locked policy: EquityEngine's actual CODE (not
    its docstrings, which discuss the policy in prose) must never call
    check_unrealized_risk or otherwise read open-position unrealized PnL --
    only the injected open_realized_pnl scalar. Also asserts the engine
    holds no position-manager reference (RiskManager has none either)."""
    # Strip each method's own docstring so this checks executable code only
    # -- the module/class docstrings legitimately discuss (and rule out)
    # check_unrealized_risk in prose.
    for method in (EquityEngine.derive, EquityEngine.reconcile):
        src = inspect.getsource(method)
        doc = inspect.getdoc(method)
        body = src.replace(doc, "") if doc else src
        assert "check_unrealized_risk" not in body
        assert "unrealized" not in body.lower()
        assert "pos_mgr" not in body
        assert "position_manager" not in body.lower()

    # No instance state at all -- purely a stateless façade over scalars.
    engine = EquityEngine()
    assert engine.__dict__ == {}


def test_derive_and_reconcile_signatures_take_only_scalars():
    derive_params = inspect.signature(EquityEngine.derive).parameters
    reconcile_params = inspect.signature(EquityEngine.reconcile).parameters
    assert set(derive_params) == {"self", "open_realized_pnl", "ledger_path"}
    assert set(reconcile_params) == {
        "self", "accumulator", "open_realized_pnl", "pending_pnl",
        "funding_addback", "ledger_path",
    }


# ---------------------------------------------------------------------------
# Characterization test: RiskManager.compute_ledger_drift() delegation is a
# byte-identical no-op refactor (accumulator - derived, no corrections).
# ---------------------------------------------------------------------------

def test_compute_ledger_drift_delegates_with_identical_output(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=5000.0)
    # compute_ledger_drift() takes no ledger_path kwarg -- it goes through
    # EquityEngine.reconcile() -> get_run_stats() with the module-level
    # default LEDGER_CSV, so point that at the tmp ledger for isolation.
    monkeypatch.setattr(trade_source_module, "LEDGER_CSV", ctx["ledger_path"])

    from execution.risk import RiskManager

    rm = RiskManager(starting_equity=5003.5, load_persisted_equity=False)
    rm.equity = 5003.5  # accumulator is $0.50 "hot" vs derived (5003.0)

    result = rm.compute_ledger_drift()
    assert result is not None
    # Hand-computed expected value: pre-PR-2 formula was
    # accumulator - derived, with derived = get_run_stats()["derived_equity"].
    expected_derived = 5003.0
    expected_drift = 5003.5 - expected_derived
    assert result["accumulator_equity"] == pytest.approx(5003.5)
    assert result["derived_equity"] == pytest.approx(expected_derived)
    assert result["drift"] == pytest.approx(expected_drift)
    assert set(result.keys()) == {"accumulator_equity", "derived_equity", "drift", "epoch_id"}

    # Same result obtained by calling EquityEngine directly with 0.0
    # corrections -- proves the delegation didn't change the math.
    direct = EquityEngine().reconcile(rm.equity, ledger_path=ctx["ledger_path"])
    assert direct["adjusted_drift"] == pytest.approx(result["drift"])
    assert direct["derived"] == pytest.approx(result["derived_equity"])


def test_compute_ledger_drift_none_when_no_epoch_baseline(tmp_path, monkeypatch):
    ctx = _setup(tmp_path, monkeypatch, epoch_equity=None)
    monkeypatch.setattr(trade_source_module, "LEDGER_CSV", ctx["ledger_path"])

    from execution.risk import RiskManager

    rm = RiskManager(starting_equity=5000.0, load_persisted_equity=False)
    assert rm.compute_ledger_drift() is None
