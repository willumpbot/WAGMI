"""
PNL_LEVERAGE_FIX flag tests.

The PNL_LEVERAGE_FIX flag (default OFF) controls whether realized/unrealized
pnl re-applies leverage. The coordinator sizes qty as FULL base-currency
exposure (qty = risk$/stop_width, NOT multiplied by leverage), so the correct
base semantics is pnl = move * qty. The flag defaults OFF to preserve the
current (leverage-inflated) behavior pnl = move * qty * leverage until a
reviewed replay flips it.

Verifies:
1. Flag unset/false  -> realized pnl = move * qty * leverage (current behavior)
2. Flag true         -> realized pnl = move * qty          (leverage removed)
3. _pnl_lev(leverage) returns leverage when off, 1.0 when on
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager

_ENTRY = 100.0
_EXIT = 110.0
_QTY = 10.0
_LEVERAGE = 5.0


def _make_pm():
    # taker_fee_bps=0 so realized_pnl == gross pnl (no fee subtraction),
    # isolating the leverage term under test.
    return PositionManager(taker_fee_bps=0)


# --- (c) _pnl_lev helper directly -------------------------------------------

def test_pnl_lev_off_returns_leverage(monkeypatch):
    monkeypatch.delenv("PNL_LEVERAGE_FIX", raising=False)
    pm = _make_pm()
    assert pm._pnl_lev(5.0) == 5.0
    assert pm._pnl_lev(1.0) == 1.0


def test_pnl_lev_explicit_false_returns_leverage(monkeypatch):
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "false")
    pm = _make_pm()
    assert pm._pnl_lev(5.0) == 5.0


def test_pnl_lev_on_returns_one(monkeypatch):
    pm = _make_pm()
    for val in ("true", "1", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("PNL_LEVERAGE_FIX", val)
        assert pm._pnl_lev(5.0) == 1.0, f"expected 1.0 with PNL_LEVERAGE_FIX={val}"


# --- (a) flag OFF: current leverage-inflated behavior preserved -------------

def test_realized_pnl_off_includes_leverage(monkeypatch):
    monkeypatch.delenv("PNL_LEVERAGE_FIX", raising=False)
    pm = _make_pm()
    pm.open_position("TEST", "LONG", _ENTRY, _QTY, 95.0, _EXIT, 120.0,
                     leverage=_LEVERAGE, atr=3.0)
    event = pm.force_close("TEST", _EXIT, "TEST")
    expected = (_EXIT - _ENTRY) * _QTY * _LEVERAGE  # 10 * 10 * 5 = 500
    assert event.pnl == pytest.approx(expected, abs=1e-6)
    assert pm.positions["TEST"].realized_pnl == pytest.approx(expected, abs=1e-6)


def test_realized_pnl_off_short_includes_leverage(monkeypatch):
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "false")
    pm = _make_pm()
    pm.open_position("TEST", "SHORT", _ENTRY, _QTY, 105.0, 90.0, 80.0,
                     leverage=_LEVERAGE, atr=3.0)
    event = pm.force_close("TEST", 90.0, "TEST")
    expected = (_ENTRY - 90.0) * _QTY * _LEVERAGE  # 10 * 10 * 5 = 500
    assert event.pnl == pytest.approx(expected, abs=1e-6)


# --- (b) flag ON: leverage removed from pnl ---------------------------------

def test_realized_pnl_on_removes_leverage(monkeypatch):
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    pm = _make_pm()
    pm.open_position("TEST", "LONG", _ENTRY, _QTY, 95.0, _EXIT, 120.0,
                     leverage=_LEVERAGE, atr=3.0)
    event = pm.force_close("TEST", _EXIT, "TEST")
    expected = (_EXIT - _ENTRY) * _QTY  # 10 * 10 = 100 (no leverage)
    assert event.pnl == pytest.approx(expected, abs=1e-6)
    assert pm.positions["TEST"].realized_pnl == pytest.approx(expected, abs=1e-6)


def test_realized_pnl_on_short_removes_leverage(monkeypatch):
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "1")
    pm = _make_pm()
    pm.open_position("TEST", "SHORT", _ENTRY, _QTY, 105.0, 90.0, 80.0,
                     leverage=_LEVERAGE, atr=3.0)
    event = pm.force_close("TEST", 90.0, "TEST")
    expected = (_ENTRY - 90.0) * _QTY  # 10 * 10 = 100 (no leverage)
    assert event.pnl == pytest.approx(expected, abs=1e-6)


def test_on_vs_off_ratio_is_leverage(monkeypatch):
    """Same trade: OFF pnl should be exactly leverage x the ON pnl."""
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "false")
    pm_off = _make_pm()
    pm_off.open_position("TEST", "LONG", _ENTRY, _QTY, 95.0, _EXIT, 120.0,
                         leverage=_LEVERAGE, atr=3.0)
    pnl_off = pm_off.force_close("TEST", _EXIT, "TEST").pnl

    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    pm_on = _make_pm()
    pm_on.open_position("TEST", "LONG", _ENTRY, _QTY, 95.0, _EXIT, 120.0,
                        leverage=_LEVERAGE, atr=3.0)
    pnl_on = pm_on.force_close("TEST", _EXIT, "TEST").pnl

    assert pnl_off == pytest.approx(pnl_on * _LEVERAGE, abs=1e-6)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
