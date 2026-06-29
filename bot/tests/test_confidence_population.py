"""Rank-2 instrument fix: pos.confidence must be populated even when the caller
passes confidence only inside entry_reasons (the LLM-first path bug that left
81/85 trades.csv rows at confidence=0.0)."""
import os
import pytest

from execution.position_manager import PositionManager


@pytest.fixture
def pm(tmp_path, monkeypatch):
    # Keep position backups off the live data dir.
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    return PositionManager()


def _open(pm, symbol, **kw):
    return pm.open_position(
        symbol=symbol, side="SELL", entry=100.0, qty=1.0,
        sl=102.0, tp1=98.0, tp2=96.0, atr=1.0, leverage=2.0, **kw)


def test_confidence_derived_from_entry_reasons_ensemble(pm):
    """LLM-first path: confidence in entry_reasons['confidence'] (0-100), arg omitted."""
    pos = _open(pm, "BTC", entry_reasons={"llm_first": True, "confidence": 68.8})
    assert pos is not None
    assert abs(pos.confidence - 68.8) < 1e-9


def test_confidence_derived_from_llm_confidence_scaled(pm):
    """Falls back to llm_confidence (0-1) scaled to 0-100 when no ensemble confidence."""
    pos = _open(pm, "ETH", entry_reasons={"llm_first": True, "llm_confidence": 0.52})
    assert pos is not None
    assert abs(pos.confidence - 52.0) < 1e-6


def test_explicit_confidence_arg_wins(pm):
    """An explicit, valid confidence= arg is not overridden by entry_reasons."""
    pos = _open(pm, "SOL", confidence=71.0, entry_reasons={"confidence": 10.0})
    assert pos is not None
    assert abs(pos.confidence - 71.0) < 1e-9


def test_no_confidence_anywhere_stays_zero(pm):
    pos = _open(pm, "XRP", entry_reasons={"llm_first": True})
    assert pos is not None
    assert pos.confidence == 0.0
