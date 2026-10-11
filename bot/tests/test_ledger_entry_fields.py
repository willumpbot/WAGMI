"""LEDGER_ENTRY_SIZING_FIELDS (2026-10-11): the six entry-time ledger cells.

predicted_ev, kelly_weight_applied, compound_size_multiplier,
funding_rate_entry, open_interest_entry, premium_entry must be written from
the values captured at OPEN on ``pos.entry_reasons`` (persisted through
execution/auto_recovery position_state, so a restart keeps them), on every
exit path, by both ledger writers (live god-block helper + shadow CloseBus
subscriber). Pure logging: these tests also prove sizing/exits are
unchanged by the extra entry_reasons keys.

Everything runs in tmp dirs (cwd chdir'd to tmp_path).
"""
import copy
import csv
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.close_subscribers_accounting import on_close_ledger
from core.close_pipeline.trade_closed import TradeClosed
from execution.auto_recovery import _dict_to_position, _position_to_dict
from execution.position_manager import PositionManager
from feedback.trade_ledger import (
    TradeLedger,
    ledger_entry_fields,
    stamp_entry_sizing_fields,
)

ENTRY, SL, TP1, TP2, QTY, LEV = 100.0, 95.0, 110.0, 130.0, 2.0, 2.0
SIX = ("predicted_ev", "kelly_weight_applied", "compound_size_multiplier",
       "funding_rate_entry", "open_interest_entry", "premium_entry")

# Representative LLM-first entry_reasons as built at open
# (multi_strategy_main._process_symbol_llm_first + _capture_measurement_floor_fields).
BASE_REASONS = {
    "llm_first": True,
    "confidence": 72.0,
    "num_agree": 2,
    "regime": "range",
    "ev_per_dollar": 0.2586,
    "win_prob": 0.55,
    "rr_tp1": 2.0,
    "regime_4h": "consolidation",
    "funding_rate_entry": 1.25e-05,
    "open_interest_entry": 358302817.0,
    "premium_entry": 0.0002884518,
    "funding_oi_ts": "2026-10-11T13:54:49",
}
LLM_BASE_QTY = 2.5   # coordinator's risk-sized qty; final opened qty = QTY


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for flag in ("BREAKEVEN_RATCHET", "SL_FILL_FIDELITY_FIX", "FUNDING_ACCRUAL_CADENCE_FIX"):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "true")
    import core.position_journal as _pj
    monkeypatch.setattr(_pj, "journal_path", lambda: tmp_path / "position_journal.jsonl")
    m = PositionManager(taker_fee_bps=4)
    m._backup_dir = tmp_path
    m.is_live = False
    return m


def _reasons(stamp=True):
    er = copy.deepcopy(BASE_REASONS)
    if stamp:
        stamp_entry_sizing_fields(er, QTY, LLM_BASE_QTY, 0.8)
    return er


def _open(pm, entry_reasons):
    pm.open_position(symbol="ETH", side="LONG", entry=ENTRY, qty=QTY, sl=SL,
                     tp1=TP1, tp2=TP2, atr=1.0, leverage=LEV,
                     entry_reasons=entry_reasons)
    return pm.positions["ETH"]


def _restart(pm, pos):
    """Simulate a bot restart: Position -> position_state JSON -> Position."""
    d = json.loads(json.dumps(_position_to_dict(pos), default=str))
    restored = _dict_to_position(d)
    pm.positions[pos.symbol] = restored
    return restored


def _run_sl(pm):
    events = pm.update_price("ETH", 94.0)
    final = [e for e in events if e.action == "SL"]
    assert final, [e.action for e in events]
    return final[0]


def _run_tp1_trailing(pm):
    ev1 = pm.update_price("ETH", 110.0)
    assert any(e.action == "TP1" for e in ev1), [e.action for e in ev1]
    pm.update_price("ETH", 120.0)
    for px in (119.0, 117.0, 115.0, 112.0, 108.0, 104.0, 101.0, 99.0):
        events = pm.update_price("ETH", px)
        final = [e for e in events if e.action in ("TRAILING_STOP", "SL")]
        if final:
            return final[0]
    raise AssertionError("never stopped out after TP1")


def _shadow_row(tmp_path, pos, event):
    d = tmp_path / "shadow"
    os.makedirs(d, exist_ok=True)
    led = TradeLedger(data_dir=str(d))
    ev = TradeClosed.from_trade_event(event, position=pos)
    on_close_ledger(ev, CloseCtx(risk_mgr=None, trade_ledger=led,
                                 journal_booked_fn=lambda *a, **k: None))
    with open(d / "trade_ledger.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    return rows[0]


def _assert_six(cells):
    assert cells["predicted_ev"] == "0.2586"
    assert cells["compound_size_multiplier"] == str(round(QTY / LLM_BASE_QTY, 4))
    assert float(cells["funding_rate_entry"]) == pytest.approx(1.25e-05)
    assert float(cells["open_interest_entry"]) == pytest.approx(358302817.0)
    assert float(cells["premium_entry"]) == pytest.approx(0.0002884518)
    # No live path applies a Kelly weight to size -> honestly blank.
    assert cells["kelly_weight_applied"] == ""


# ── exit paths x restart ─────────────────────────────────────────────────

@pytest.mark.parametrize("restart", [False, True], ids=["no_restart", "restart"])
@pytest.mark.parametrize("path", ["sl", "tp1_trailing"])
def test_six_columns_populated_from_entry(pm, tmp_path, path, restart):
    pos = _open(pm, _reasons())
    if restart:
        pos = _restart(pm, pos)
    event = _run_sl(pm) if path == "sl" else _run_tp1_trailing(pm)
    assert pos.state == "CLOSED"
    # live god-block writer (multi_strategy_main) uses this helper verbatim
    live_cells = ledger_entry_fields(pos.entry_reasons, compound_fallback=None)
    _assert_six(live_cells)
    _assert_six(_shadow_row(tmp_path, pos, event))


def test_full_ledger_row_written(tmp_path, pm):
    pos = _open(pm, _reasons())
    pos = _restart(pm, pos)
    _run_sl(pm)
    led = TradeLedger(data_dir=str(tmp_path))
    led.record_trade({"symbol": "ETH", "side": "LONG",
                      **ledger_entry_fields(pos.entry_reasons)})
    with open(tmp_path / "trade_ledger.csv", newline="") as f:
        row = list(csv.DictReader(f))[-1]
    _assert_six(row)


# ── blank, never fabricated ──────────────────────────────────────────────

def test_missing_values_stay_blank():
    cells = ledger_entry_fields({"ev_per_dollar": None, "funding_rate_entry": None})
    assert all(cells[k] == "" for k in SIX)
    assert all(v == "" for v in ledger_entry_fields(None).values())


def test_legacy_cache_fallback_and_json_string_reasons():
    cells = ledger_entry_fields(json.dumps({"ev_per_dollar": 0.1}), compound_fallback=1.25)
    assert cells["predicted_ev"] == "0.1"
    assert cells["compound_size_multiplier"] == "1.25"
    # entry-time stamp wins over the in-memory cache
    cells = ledger_entry_fields({"compound_size_multiplier": 0.5}, compound_fallback=1.25)
    assert cells["compound_size_multiplier"] == "0.5"


def test_funding_flag_off_blanks_funding_only(monkeypatch):
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "false")
    cells = ledger_entry_fields(_reasons())
    assert cells["funding_rate_entry"] == cells["open_interest_entry"] == cells["premium_entry"] == ""
    assert cells["predicted_ev"] == "0.2586"


def test_stamp_without_base_qty_is_blank():
    er = {}
    stamp_entry_sizing_fields(er, 1.0, 0.0, None)
    assert "compound_size_multiplier" not in er
    stamp_entry_sizing_fields("not a dict", 1.0, 1.0)  # never raises


# ── no trading-behaviour change ──────────────────────────────────────────

def _trajectory(pm, path, reasons):
    pos = _open(pm, reasons)
    opened = (pos.qty, pos.sl, pos.tp1, pos.tp2, pos.leverage, pos.entry)
    event = _run_sl(pm) if path == "sl" else _run_tp1_trailing(pm)
    closed = (event.action, round(event.price, 8), round(pos.realized_pnl, 8),
              round(pos.fees_paid, 8), pos.sl, pos.original_qty, pos.original_sl,
              list(pos.state_path))
    pm.positions.pop("ETH", None)
    return opened, closed


def _fresh_pm(tmp_path):
    m = PositionManager(taker_fee_bps=4)
    m._backup_dir = tmp_path
    m.is_live = False
    return m


@pytest.mark.parametrize("path", ["sl", "tp1_trailing"])
def test_sizing_and_exits_unchanged(pm, tmp_path, path):
    # fresh managers so the loss cooldown from run 1 can't gate run 2
    old = _trajectory(_fresh_pm(tmp_path), path, copy.deepcopy(BASE_REASONS))  # pre-change keys
    new = _trajectory(_fresh_pm(tmp_path), path, _reasons(stamp=True))         # + stamped keys
    assert old == new


def test_stamp_does_not_touch_qty_inputs():
    er, qty, base = {}, 2.0, 2.5
    stamp_entry_sizing_fields(er, qty, base, 0.8)
    assert (qty, base) == (2.0, 2.5)
    assert set(er) == {"compound_size_multiplier", "llm_base_qty", "llm_size_multiplier"}


def test_live_writer_wired_to_helper():
    src = open(os.path.join(os.path.dirname(__file__), "..", "multi_strategy_main.py"),
               encoding="utf-8").read()
    for col in SIX:
        assert re.search(rf'"{col}": _entry_cells\["{col}"\]', src), col
    # stamp happens after the fill (qty final), immediately before the open
    i_fill = src.index("qty = order_result.fill_qty if order_result.fill_qty > 0 else qty")
    i_stamp = src.index("_sesf(entry_reasons, qty, entry_decision.position_qty")
    i_open = src.index("self.pos_mgr.open_position(", i_stamp)
    assert i_fill < i_stamp < i_open
    between = src[i_stamp:i_open]
    assert not re.search(r"^\s*qty\s*=", between, re.M), "stamp block must not reassign qty"
