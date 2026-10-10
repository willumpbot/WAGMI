"""LEDGER_RR_FIX (2026-10-10): realized_rr / stop_initial / stop_final.

Every exit path that writes a ledger row must populate realized_rr as the
WHOLE-TRADE R multiple:

    realized_rr = pos.realized_pnl (net, all legs)
                  / (|entry - stop_initial| * original_qty * pnl_leverage)

where pnl_leverage is the factor the pnl was actually booked with
(PositionManager._pnl_lev: 1.0 under PNL_LEVERAGE_FIX=true, else leverage).
stop_initial = the stop at OPEN, stop_final = the stop at CLOSE.

Pure logging: these tests also prove that computing/writing the cells
does not touch any trading-relevant Position/PositionManager state.

Everything runs in tmp dirs (cwd is chdir'd to tmp_path so the
PositionManager's relative data/position_backups never hits the live dir).
"""
import copy
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.close_subscribers_accounting import on_close_ledger
from core.close_pipeline.trade_closed import TradeClosed
from execution.auto_recovery import _dict_to_position, _position_to_dict
from execution.position_manager import PositionManager
from feedback.trade_ledger import (
    LEDGER_COLUMNS,
    TradeLedger,
    compute_realized_rr,
    ledger_rr_fields,
    rr_pnl_leverage,
)

ENTRY = 100.0
SL = 95.0
QTY = 2.0
LEV = 2.0


# ── fixtures / helpers ───────────────────────────────────────────────────

@pytest.fixture(params=["true", "false"], ids=["pnl_lev_fix_on", "pnl_lev_fix_off"])
def pnl_lev_flag(request, monkeypatch):
    monkeypatch.setenv("PNL_LEVERAGE_FIX", request.param)
    return request.param


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # relative data/ paths -> tmp, never live
    # Keep the position lifecycle purely mechanical/deterministic.
    for flag in ("BREAKEVEN_RATCHET", "SL_FILL_FIDELITY_FIX", "FUNDING_ACCRUAL_CADENCE_FIX"):
        monkeypatch.delenv(flag, raising=False)
    import core.position_journal as _pj
    monkeypatch.setattr(_pj, "journal_path", lambda: tmp_path / "position_journal.jsonl")
    m = PositionManager(taker_fee_bps=4)
    m._backup_dir = tmp_path
    m.is_live = False
    return m


def _open(pm, side="LONG", symbol="ETH"):
    long_ = side == "LONG"
    pm.open_position(
        symbol=symbol, side=side, entry=ENTRY, qty=QTY,
        sl=SL if long_ else 2 * ENTRY - SL,
        tp1=110.0 if long_ else 90.0,
        tp2=130.0 if long_ else 70.0,
        atr=1.0, leverage=LEV,
    )
    return pm.positions[symbol]


def _expected_rr(pos):
    lev = 1.0 if os.getenv("PNL_LEVERAGE_FIX", "").lower() == "true" else pos.leverage
    risk = abs(pos.entry - pos.original_sl) * pos.original_qty * lev
    return round(pos.realized_pnl / risk, 3)


def _trading_state(pos):
    """Everything about a Position that trading/learning reads."""
    keys = ("entry", "qty", "sl", "tp1", "tp2", "leverage", "state", "original_qty",
            "original_sl", "realized_pnl", "fees_paid", "funding_costs", "outcome",
            "peak_price", "trailing_distance", "highest_price", "lowest_price")
    return {k: copy.deepcopy(getattr(pos, k)) for k in keys} | {
        "state_path": list(pos.state_path),
        "entry_reasons": copy.deepcopy(pos.entry_reasons),
    }


def _ledger_rows_both_writers(tmp_path, pos, event):
    """Return (god-block cells, shadow-pipeline ledger row) for a terminal
    close, asserting neither writer mutates trading state."""
    before = _trading_state(pos)
    cells = ledger_rr_fields(pos, pos.realized_pnl, event.qty)
    led = TradeLedger(data_dir=str(tmp_path / "shadow"))
    os.makedirs(tmp_path / "shadow", exist_ok=True)
    ev = TradeClosed.from_trade_event(event, position=pos)
    on_close_ledger(ev, CloseCtx(risk_mgr=None, trade_ledger=led,
                                 journal_booked_fn=lambda *a, **k: None))
    with open(tmp_path / "shadow" / "trade_ledger.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert _trading_state(pos) == before, "ledger write mutated trading state"
    assert len(rows) == 1
    return cells, rows[0]


def _assert_rr(tmp_path, pos, event, *, stop_moved):
    cells, row = _ledger_rows_both_writers(tmp_path, pos, event)
    exp = _expected_rr(pos)
    for src in (cells, row):
        assert src["realized_rr"] != "", f"{event.action}: realized_rr blank"
        assert float(src["realized_rr"]) == pytest.approx(exp, abs=1e-3)
        assert float(src["stop_initial"]) == pytest.approx(pos.original_sl)
        assert float(src["stop_final"]) == pytest.approx(pos.sl)
    sl0 = SL if pos.side == "LONG" else 2 * ENTRY - SL   # stop at open
    assert float(cells["stop_initial"]) == pytest.approx(sl0)
    if stop_moved:
        assert float(cells["stop_final"]) != pytest.approx(sl0)
    else:
        assert float(cells["stop_final"]) == pytest.approx(sl0)
    return float(cells["realized_rr"])


# ── leverage factor must mirror the one pnl is booked with ───────────────

@pytest.mark.parametrize("flag", ["true", "false", "1", "no"])
def test_rr_leverage_mirrors_position_manager(flag, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PNL_LEVERAGE_FIX", flag)
    m = PositionManager(taker_fee_bps=4)
    for lev in (1.0, 2.0, 5.0):
        assert rr_pnl_leverage(lev) == m._pnl_lev(lev)


def test_compute_realized_rr_unknown_is_blank_not_zero():
    assert compute_realized_rr(10.0, 100.0, 0.0, 1.0) is None      # no stop
    assert compute_realized_rr(10.0, 100.0, 100.0, 1.0) is None    # zero width
    assert compute_realized_rr(10.0, 100.0, 95.0, 0.0) is None     # no qty
    assert compute_realized_rr(0.0, 100.0, 95.0, 1.0) == 0.0       # genuine scratch


# ── every exit path ──────────────────────────────────────────────────────

def test_sl_loss_is_about_minus_one_r(pm, pnl_lev_flag, tmp_path):
    pos = _open(pm)
    events = pm.update_price("ETH", 94.0)
    final = [e for e in events if e.action == "SL"]
    assert final, [e.action for e in events]
    rr = _assert_rr(tmp_path, pos, final[0], stop_moved=False)
    # 1R past the stop + fees: about -1.2R regardless of leverage flag. The
    # old `* leverage` denominator gave ~-0.6R under PNL_LEVERAGE_FIX=true.
    assert -1.4 < rr < -1.0


def test_tp1_partial_then_trailing_stop_is_whole_trade(pm, pnl_lev_flag, tmp_path):
    pos = _open(pm)
    ev1 = pm.update_price("ETH", 110.0)
    assert any(e.action == "TP1" for e in ev1), [e.action for e in ev1]
    assert pos.qty < QTY  # partial leg booked
    tp1_leg_pnl = pos.realized_pnl
    assert tp1_leg_pnl > 0
    pm.update_price("ETH", 120.0)            # run up -> trail
    events = []
    for px in (119.0, 117.0, 115.0, 112.0, 108.0, 104.0, 101.0, 99.0):
        events = pm.update_price("ETH", px)
        if any(e.action in ("TRAILING_STOP", "SL") for e in events):
            break
    final = [e for e in events if e.action in ("TRAILING_STOP", "SL")]
    assert final, "position never stopped out after TP1"
    assert pos.state == "CLOSED"
    rr = _assert_rr(tmp_path, pos, final[0], stop_moved=True)
    # whole-trade R includes the TP1 leg (not just the final leg)
    assert pos.realized_pnl != pytest.approx(final[0].pnl - final[0].fee)
    assert rr > 0


def test_tp2_close(pm, pnl_lev_flag, tmp_path):
    pos = _open(pm)
    pm.update_price("ETH", 110.0)            # TP1 first (normal path)
    events = pm.update_price("ETH", 131.0)
    final = [e for e in events if e.action in ("TP2", "TRAILING_STOP")]
    assert final, [e.action for e in events]
    rr = _assert_rr(tmp_path, pos, final[0], stop_moved=True)
    assert rr > 1.0


@pytest.mark.parametrize("reason", ["TIME_STOP", "LLM_EXIT_AGENT", "LLM_EXIT_HIGH"])
def test_force_close_paths(pm, pnl_lev_flag, tmp_path, reason):
    pos = _open(pm, side="SHORT")
    ev = pm.force_close("ETH", 103.0, reason=reason)
    assert ev is not None and ev.action == reason
    rr = _assert_rr(tmp_path, pos, ev, stop_moved=False)
    assert rr < 0  # short, price went up


# ── immutable initial stop survives restart ──────────────────────────────

def test_original_sl_survives_state_roundtrip_after_breakeven(pm, tmp_path):
    pos = _open(pm)
    pm.update_price("ETH", 110.0)            # TP1 -> stop moved to ~breakeven
    assert pos.sl != pytest.approx(SL)
    restored = _dict_to_position(_position_to_dict(pos))
    assert restored.original_sl == pytest.approx(SL)
    assert restored.sl == pytest.approx(pos.sl)
    assert restored.original_qty == pytest.approx(QTY)


def test_old_persisted_dict_without_original_sl_falls_back(pm):
    pos = _open(pm)
    d = _position_to_dict(pos)
    d.pop("original_sl")
    assert _dict_to_position(d).original_sl == pytest.approx(SL)


# ── schema backward compatibility ────────────────────────────────────────

def test_new_columns_appended_at_end():
    assert LEDGER_COLUMNS[-2:] == ["stop_initial", "stop_final"]
    for col in ("realized_rr", "position_id", "pipeline_id", "thesis_id"):
        assert col in LEDGER_COLUMNS


def test_old_rows_still_parse_and_migrate(tmp_path):
    old_cols = LEDGER_COLUMNS[:-2]
    p = tmp_path / "trade_ledger.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        row = {c: "" for c in old_cols}
        row.update({"trade_id": "abc123def456", "symbol": "BTC", "net_pnl": "-1.5",
                    "timestamp": str(datetime.now(timezone.utc).timestamp())})
        w.writerow(row)
    led = TradeLedger(data_dir=str(tmp_path))
    # reader on the un-migrated file
    assert led.get_trades(lookback_days=1)[0]["symbol"] == "BTC"
    led.record_trade({"symbol": "ETH", "realized_rr": "1.2",
                      "stop_initial": "95.0", "stop_final": "100.1"})
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == LEDGER_COLUMNS
    assert rows[0]["symbol"] == "BTC" and rows[0]["stop_initial"] == ""
    assert rows[1]["stop_initial"] == "95.0" and rows[1]["stop_final"] == "100.1"
    # fresh reader over the migrated file
    assert len(TradeLedger(data_dir=str(tmp_path)).get_trades(lookback_days=1)) == 2


def test_god_block_uses_shared_helper():
    """The live writer in multi_strategy_main.py must source all three cells
    from ledger_rr_fields (the function the tests above exercise)."""
    src_path = os.path.join(os.path.dirname(__file__), "..", "multi_strategy_main.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "ledger_rr_fields as _lrf" in src
    for col in ("realized_rr", "stop_initial", "stop_final"):
        assert f'"{col}": _rr_cells["{col}"]' in src
