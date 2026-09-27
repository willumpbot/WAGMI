"""MEASUREMENT-FLOOR logging-gap fixes (LEDGER_FIELD_COMPLETION, 2026-07-27).

Proves the three living-value fields now land on the ledger row when the
entry metadata carries them, that a missing/null entry still writes a full
row (blanks, no exception), and that existing row semantics are unchanged.

The ledger row is exercised through the extracted, unit-testable close
subscriber (``core.close_pipeline.close_subscribers_accounting.on_close_ledger``),
writing to a REAL ``TradeLedger`` under ``tmp_path`` (tmp paths are not live
canonical files, so the provenance gate permits the write). The god-block
live path in ``multi_strategy_main.py`` writes the identical column set from
the same ``entry_reasons`` keys.

These are LOGGING-ONLY changes: no test here asserts any change to a trade
decision, sizing, or exit -- there is none.
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from feedback.trade_ledger import LEDGER_COLUMNS, TradeLedger
from core.funding_oi_snapshot import latest_funding_oi
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import LegKind, TradeClosed
from core.close_pipeline.close_subscribers_accounting import on_close_ledger

MF_COLS = ("funding_rate_entry", "open_interest_entry", "premium_entry")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_event(entry_reasons=None, **overrides) -> TradeClosed:
    defaults = dict(
        position_id="pos-mf-001",
        leg_kind=LegKind.TERMINAL,
        close_type="TP2",
        symbol="BTC",
        side="SHORT",
        price=49000.0,
        qty=0.1,
        pnl=98.0,
        fee=2.0,
        leverage=5.0,
        strategy="ensemble",
        total_pnl=96.0,
        fees_total=2.0,
        funding_costs=0.0,
        equity_after=5096.0,
        session_dd_pct=0.0,
        entry=50000.0,
        original_sl=50500.0,
        original_qty=0.1,
        tp1=49500.0,
        tp2=49000.0,
        confidence=74.0,
        entry_reasons=entry_reasons if entry_reasons is not None else {},
        trade_profile={"volatility_band": "normal"},
        state_path="IDLE->OPEN->CLOSED",
        outcome="WIN",
        hold_time_s=3600.0,
        regime="high_volatility",
    )
    defaults.update(overrides)
    return TradeClosed(**defaults)


def _ledger_ctx(tmp_path) -> tuple:
    led = TradeLedger(data_dir=str(tmp_path))
    ctx = CloseCtx(
        risk_mgr=None,
        trade_ledger=led,
        kelly_engine=None,
        source="paper",
        journal_booked_fn=lambda *a, **k: None,  # no-op: never touch the real journal
    )
    return led, ctx


def _read_rows(tmp_path) -> list:
    with open(os.path.join(str(tmp_path), "trade_ledger.csv"), newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def test_schema_has_measurement_floor_columns():
    for col in MF_COLS:
        assert col in LEDGER_COLUMNS, f"{col} missing from LEDGER_COLUMNS"
    # Appended at the END so existing readers/positions are unchanged.
    assert LEDGER_COLUMNS[-3:] == list(MF_COLS)
    # The distinct realized-funding-P&L column must still exist and be separate.
    assert "funding" in LEDGER_COLUMNS
    assert "funding" not in MF_COLS


# ---------------------------------------------------------------------------
# funding/OI snapshot helper
# ---------------------------------------------------------------------------
def test_funding_oi_snapshot_reads_latest(tmp_path):
    p = tmp_path / "funding_oi_history.jsonl"
    rows = [
        {"timestamp": "2026-07-27T10:00:00", "symbol": "BTC", "funding_rate": 0.00001, "open_interest": 1000.0, "premium": 0.0001},
        {"timestamp": "2026-07-27T10:00:00", "symbol": "ETH", "funding_rate": -0.00002, "open_interest": 2000.0, "premium": -0.0002},
        {"timestamp": "2026-07-27T10:15:00", "symbol": "BTC", "funding_rate": 0.00005, "open_interest": 1500.0, "premium": 0.0003},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    snap = latest_funding_oi("BTC", path=str(p))
    assert snap["funding_rate"] == pytest.approx(0.00005)   # newest BTC row, not the 10:00 one
    assert snap["open_interest"] == pytest.approx(1500.0)
    assert snap["premium"] == pytest.approx(0.0003)
    assert snap["funding_oi_ts"] == "2026-07-27T10:15:00"

    # Full CCXT symbol normalizes to the short name the collector writes.
    assert latest_funding_oi("BTC/USDC:USDC", path=str(p))["open_interest"] == pytest.approx(1500.0)
    # Distinct symbol resolves independently.
    assert latest_funding_oi("ETH", path=str(p))["funding_rate"] == pytest.approx(-0.00002)


def test_funding_oi_snapshot_fail_neutral(tmp_path):
    # Missing file -> all-None, no exception.
    missing = latest_funding_oi("BTC", path=str(tmp_path / "nope.jsonl"))
    assert missing == {"funding_rate": None, "open_interest": None, "premium": None, "funding_oi_ts": None}

    # Corrupt / partial lines are skipped; a valid trailing row still resolves.
    p = tmp_path / "funding_oi_history.jsonl"
    p.write_text('{bad json\nnot even close\n{"symbol":"BTC","funding_rate":0.0009,"open_interest":42.0,"premium":0.0}\n')
    snap = latest_funding_oi("BTC", path=str(p))
    assert snap["funding_rate"] == pytest.approx(0.0009)
    assert snap["open_interest"] == pytest.approx(42.0)

    # Symbol not present -> nulls, no exception.
    assert latest_funding_oi("DOGE", path=str(p))["funding_rate"] is None


# ---------------------------------------------------------------------------
# End-to-end: a simulated close writes all three onto the ledger row
# ---------------------------------------------------------------------------
def test_close_populates_regime4h_factors_and_funding(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "true")
    led, ctx = _ledger_ctx(tmp_path)
    entry_reasons = {
        "num_agree": 2,
        "strategies_agree": ["bollinger_squeeze", "confidence_scorer"],
        "regime_4h": "range",
        "funding_rate_entry": 0.000123,
        "open_interest_entry": 987654321.0,
        "premium_entry": -0.00045,
        "ev_per_dollar": "0.09",
        "snapshot_entry": "50000.0",
    }
    ev = _make_event(entry_reasons=entry_reasons)
    on_close_ledger(ev, ctx)

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    # 1) regime_4h threaded from the entry snapshot (was always blank before).
    assert row["regime_4h"] == "range"
    assert row["regime_1h"] == "high_volatility"  # unchanged existing semantics
    # 2) contributing_factors carries the agreeing strategies, comma-joined.
    assert row["contributing_factors"] == "bollinger_squeeze,confidence_scorer"
    # 3) numeric funding/OI/premium at entry.
    assert row["funding_rate_entry"] == "0.000123"
    assert row["open_interest_entry"] == "987654321.0"
    assert row["premium_entry"] == "-0.00045"


def test_close_missing_metadata_still_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "true")
    led, ctx = _ledger_ctx(tmp_path)
    # Empty entry_reasons: no regime_4h, no strategies_agree, no funding fields.
    ev = _make_event(entry_reasons={})
    on_close_ledger(ev, ctx)  # must not raise

    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    # New fields blank, row still complete (all schema columns present).
    assert row["regime_4h"] == ""
    assert row["funding_rate_entry"] == ""
    assert row["open_interest_entry"] == ""
    assert row["premium_entry"] == ""
    # contributing_factors falls back to the strategy name (existing semantics,
    # never blank, never overwritten with a sentinel) -- here "ensemble".
    assert row["contributing_factors"] == "ensemble"
    # Core accounting fields intact.
    assert row["net_pnl"] == "96.0"
    assert row["position_id"] == "pos-mf-001"
    assert row["win"] == "1"


def test_existing_row_semantics_unchanged(tmp_path, monkeypatch):
    """Fields that already worked must be untouched by the new plumbing."""
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "true")
    led, ctx = _ledger_ctx(tmp_path)
    entry_reasons = {
        "num_agree": 3,
        "strategies_agree": ["regime_trend", "multi_tier_quality", "confidence_scorer"],
        "ev_per_dollar": "0.15",
        "snapshot_entry": "50000.0",
        # no funding/regime_4h keys on purpose
    }
    ev = _make_event(entry_reasons=entry_reasons, close_type="SL", total_pnl=-40.0, pnl=-38.0, outcome="LOSS")
    on_close_ledger(ev, ctx)

    row = _read_rows(tmp_path)[0]
    assert row["agreement_level"] == "3"
    assert row["contributing_factors"] == "regime_trend,multi_tier_quality,confidence_scorer"
    assert row["predicted_ev"] == "0.15"
    assert row["snapshot_entry"] == "50000.0"
    assert row["win"] == "0"                 # loss
    assert row["net_pnl"] == "-40.0"
    assert row["exit_type"] == "SL"
    # New fields simply blank (absent from entry_reasons), never breaking the row.
    assert row["regime_4h"] == ""
    assert row["funding_rate_entry"] == ""


def test_flag_off_leaves_new_fields_blank(tmp_path, monkeypatch):
    """LEDGER_FIELD_COMPLETION=false -> the new fields are not populated even
    when the entry metadata carries them (clean one-switch revert)."""
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "false")
    led, ctx = _ledger_ctx(tmp_path)
    entry_reasons = {
        "num_agree": 2,
        "strategies_agree": ["bollinger_squeeze", "confidence_scorer"],
        "regime_4h": "range",
        "funding_rate_entry": 0.000123,
        "open_interest_entry": 987654321.0,
        "premium_entry": -0.00045,
    }
    ev = _make_event(entry_reasons=entry_reasons)
    on_close_ledger(ev, ctx)

    row = _read_rows(tmp_path)[0]
    assert row["regime_4h"] == ""
    assert row["funding_rate_entry"] == ""
    assert row["open_interest_entry"] == ""
    assert row["premium_entry"] == ""
    # contributing_factors is independent of the flag (existing behavior).
    assert row["contributing_factors"] == "bollinger_squeeze,confidence_scorer"


# ---------------------------------------------------------------------------
# Entry-capture unit: _capture_measurement_floor_fields threads the fields
# onto entry_reasons at OPEN (tested standalone, no full bot construction).
# ---------------------------------------------------------------------------
def test_entry_capture_threads_fields(monkeypatch, tmp_path):
    import multi_strategy_main as msm

    # Point the snapshot helper at a controlled history file.
    p = tmp_path / "funding_oi_history.jsonl"
    p.write_text(json.dumps({
        "timestamp": "2026-07-27T10:15:00", "symbol": "ETH",
        "funding_rate": 0.00007, "open_interest": 555.0, "premium": 0.0002,
    }) + "\n")
    monkeypatch.setenv("LEDGER_FIELD_COMPLETION", "true")
    monkeypatch.setattr(
        "core.funding_oi_snapshot._DEFAULT_PATH", str(p), raising=False
    )

    # Call the unbound method with a bare namespace as self (it only uses env
    # + the helper, no other instance state).
    er = {"strategies_agree": ["confidence_scorer"], "num_agree": 1}
    msm.MultiStrategyBot._capture_measurement_floor_fields(
        object.__new__(msm.MultiStrategyBot), er, "ETH", {"regime_4h": "trend"}
    )
    assert er["regime_4h"] == "trend"
    assert er["funding_rate_entry"] == pytest.approx(0.00007)
    assert er["open_interest_entry"] == pytest.approx(555.0)
    assert er["premium_entry"] == pytest.approx(0.0002)
