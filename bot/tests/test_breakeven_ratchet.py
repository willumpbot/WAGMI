"""Tests for the BREAKEVEN-RATCHET (peak-lock) stop feature in
execution/position_manager.py.

Feature contract (see PositionManager._apply_breakeven_ratchet):
  * Flag BREAKEVEN_RATCHET: off (default, byte-equiv no-op) | shadow | true.
  * Once favorable excursion from entry >= K x round-trip fee hurdle
    (round-trip = 2 * taker_fee_bps), lock the stop to entry +/- the
    round-trip fee equivalent (long: entry+fee, short: entry-fee).
  * The lock NEVER retreats and NEVER loosens a stop that is already tighter
    (composes with the profit-lock / progressive trailing).
  * Runs only in the OPEN state; does not modify state transitions.
  * Fail-open: any internal error leaves pos.sl untouched.

All tests pin taker_fee_bps=10 (round-trip hurdle = 20bps = 0.20%) and
EXIT_RATCHET_K=2, so the arm point is 0.40% and the long lock is entry*1.002.
A deliberately WIDE stop keeps the R-based profit-lock dormant so we observe
the ratchet in isolation, except in the explicit composition test.
"""
import os

import pytest

from execution.position_manager import PositionManager, _breakeven_ratchet_mode
from execution.position_state import OPEN, TRAILING, CLOSED


FEE_BPS = 10.0          # round-trip hurdle = 2*10 = 20 bps = 0.20%
# arm at K=2 -> 0.40% favorable; long lock = 100 * (1 + 0.002) = 100.20


def _pm():
    return PositionManager(taker_fee_bps=FEE_BPS)


def _open_long(pm, entry=100.0, sl=90.0, qty=10.0, tp1=105.0, tp2=110.0):
    # wide sl (10%) keeps the 0.3R profit-lock dormant during small moves
    return pm.open_position("TEST", "LONG", entry, qty, sl, tp1, tp2,
                            leverage=1.0, atr=1.0)


def _open_short(pm, entry=100.0, sl=110.0, qty=10.0, tp1=95.0, tp2=90.0):
    return pm.open_position("TEST", "SHORT", entry, qty, sl, tp1, tp2,
                            leverage=1.0, atr=1.0)


# ── flag parsing ────────────────────────────────────────────────────────
def test_mode_parsing(monkeypatch):
    monkeypatch.delenv("BREAKEVEN_RATCHET", raising=False)
    assert _breakeven_ratchet_mode() == "off"
    monkeypatch.setenv("BREAKEVEN_RATCHET", "false")
    assert _breakeven_ratchet_mode() == "off"
    monkeypatch.setenv("BREAKEVEN_RATCHET", "shadow")
    assert _breakeven_ratchet_mode() == "shadow"
    for v in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("BREAKEVEN_RATCHET", v)
        assert _breakeven_ratchet_mode() == "true"


# ── OFF = byte-equivalent no-op ──────────────────────────────────────────
def test_off_is_noop(monkeypatch):
    monkeypatch.delenv("BREAKEVEN_RATCHET", raising=False)  # default off
    pm = _pm()
    pos = _open_long(pm)
    orig_sl = pos.sl
    # a favorable move well past the would-be arm point (0.4%)
    pm.update_price("TEST", 101.0)
    assert pos.state == OPEN
    assert pos.sl == orig_sl                    # SL never moved
    assert getattr(pos, "_ratchet_armed", False) is False


def test_off_matches_baseline_sl_path(monkeypatch):
    # With the wide stop the ONLY thing that could move SL pre-TP1 is the
    # ratchet; off must leave the SL identical to the open value across a
    # full favorable-then-adverse path that would otherwise arm+lock.
    monkeypatch.setenv("BREAKEVEN_RATCHET", "off")
    pm = _pm()
    pos = _open_long(pm)
    orig_sl = pos.sl
    for p in (100.5, 101.2, 100.6, 100.3):
        pm.update_price("TEST", p)
    assert pos.sl == orig_sl


# ── arms only after MFE >= threshold ─────────────────────────────────────
def test_arms_only_after_threshold_long(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)
    # below arm (0.30% < 0.40%): not armed, SL untouched
    pm.update_price("TEST", 100.30)
    assert getattr(pos, "_ratchet_armed", False) is False
    assert pos.sl == 90.0
    # at/above arm (0.50% >= 0.40%): armed, SL ratcheted to entry+fee = 100.20
    pm.update_price("TEST", 100.50)
    assert pos._ratchet_armed is True
    assert pos.sl == pytest.approx(100.20)
    assert pos._ratchet_lock_sl == pytest.approx(100.20)
    assert pos.state == OPEN  # state machine untouched


def test_arms_only_after_threshold_short(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_short(pm)
    pm.update_price("TEST", 99.70)   # 0.30% favorable < 0.40%
    assert getattr(pos, "_ratchet_armed", False) is False
    assert pos.sl == 110.0
    pm.update_price("TEST", 99.50)   # 0.50% favorable >= 0.40%
    assert pos._ratchet_armed is True
    assert pos.sl == pytest.approx(99.80)   # entry - fee
    assert pos.state == OPEN


# ── stop never retreats below the lock ───────────────────────────────────
def test_stop_never_retreats_long(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)
    pm.update_price("TEST", 100.60)          # arm -> lock 100.20
    assert pos.sl == pytest.approx(100.20)
    # push higher, then retrace back toward entry (but above lock): SL holds
    for p in (101.50, 100.90, 100.25, 100.21):
        pm.update_price("TEST", p)
        assert pos.state == OPEN
        assert pos.sl >= 100.20 - 1e-9       # never retreats below the lock
    assert pos.sl == pytest.approx(100.20)


def test_lock_protects_on_retrace_to_breakeven(monkeypatch):
    # Once armed, a retrace THROUGH the lock closes the trade at ~breakeven
    # instead of riding back to the original -10% stop.
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)
    pm.update_price("TEST", 100.60)          # arm -> lock 100.20
    events = pm.update_price("TEST", 100.15)  # dips below lock 100.20
    assert pos.state == CLOSED
    assert events and events[-1].action == "SL"
    # exited at/above breakeven, NOT at the -10% original stop
    assert events[-1].price >= 100.0


def test_stop_never_retreats_short(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_short(pm)
    pm.update_price("TEST", 99.40)           # arm -> lock 99.80
    assert pos.sl == pytest.approx(99.80)
    for p in (98.50, 99.10, 99.75, 99.79):
        pm.update_price("TEST", p)
        assert pos.state == OPEN
        assert pos.sl <= 99.80 + 1e-9        # never retreats above the lock
    assert pos.sl == pytest.approx(99.80)


# ── shadow: computes + logs but never mutates ────────────────────────────
def test_shadow_does_not_mutate(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "shadow")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)
    pm.update_price("TEST", 100.80)          # would arm
    assert pos._ratchet_armed is True        # shadow still tracks arm state
    assert pos.sl == 90.0                    # ...but SL is NOT moved
    # and a dip that WOULD have hit the shadow lock does not close early
    events = pm.update_price("TEST", 100.10)
    assert pos.state == OPEN
    assert events == [] or all(e.action != "SL" for e in events)


# ── composition: never loosen a tighter stop ─────────────────────────────
def test_does_not_loosen_tighter_open_stop(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)
    pm.update_price("TEST", 100.60)          # arm -> lock 100.20
    assert pos.sl == pytest.approx(100.20)
    # Simulate a tighter stop set by another mechanism (profit-lock/trailing).
    pos.sl = 100.60
    pm.update_price("TEST", 100.95)          # ratchet must NOT pull SL back to 100.20
    assert pos.sl == pytest.approx(100.60)


def test_open_gated_cannot_loosen_trailing_stop(monkeypatch):
    # The ratchet runs ONLY in OPEN. A tighter stop in the TRAILING state must
    # never be loosened back toward the (looser) breakeven lock.
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = PositionManager(taker_fee_bps=FEE_BPS, enable_trailing=False)
    pos = _open_long(pm)
    pm.update_price("TEST", 100.60)          # arm in OPEN -> lock 100.20
    # Force TRAILING state with a stop far tighter than the ratchet lock.
    pos.state = TRAILING
    pos.sl = 103.00
    pm.update_price("TEST", 104.00)          # ratchet is OPEN-gated -> no-op here
    assert pos.state == TRAILING
    assert pos.sl == pytest.approx(103.00)   # tighter trailing stop preserved


# ── fail-open ────────────────────────────────────────────────────────────
def test_fail_open_on_internal_error(monkeypatch):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    pm = _pm()
    pos = _open_long(pm)

    def _boom():
        raise RuntimeError("synthetic ratchet failure")

    monkeypatch.setattr(pm, "_get_ratchet_k", _boom)
    # must not raise, must not close, must leave SL untouched
    events = pm.update_price("TEST", 101.00)
    assert pos.state == OPEN
    assert pos.sl == 90.0
    assert getattr(pos, "_ratchet_armed", False) is False
    assert all(e.action != "SL" for e in events)


# ── K resolution ─────────────────────────────────────────────────────────
def test_k_env_override_and_clamp(monkeypatch):
    pm = _pm()
    monkeypatch.setenv("EXIT_RATCHET_K", "2")
    assert pm._get_ratchet_k() == pytest.approx(2.0)
    monkeypatch.setenv("EXIT_RATCHET_K", "99")   # clamped to 10
    assert pm._get_ratchet_k() == pytest.approx(10.0)
    monkeypatch.setenv("EXIT_RATCHET_K", "0.1")  # clamped to 1
    assert pm._get_ratchet_k() == pytest.approx(1.0)
    monkeypatch.setenv("EXIT_RATCHET_K", "notanumber")  # falls back to live/default
    k = pm._get_ratchet_k()
    assert pm._RATCHET_K_MIN <= k <= pm._RATCHET_K_MAX


def test_live_k_within_band_or_default(monkeypatch):
    monkeypatch.delenv("EXIT_RATCHET_K", raising=False)
    pm = _pm()
    k = pm._compute_live_ratchet_k()
    # either the n<13 default, or a clamped live value — never outside [MIN,MAX]
    assert pm._RATCHET_K_MIN <= k <= pm._RATCHET_K_MAX
    assert k == pytest.approx(pm._get_ratchet_k())
