"""
Tests for the 2026-07-01 wiring-audit accounting fixes.

Covers:
  1. PositionManager.partial_close() — the shared partial-close accounting
     extracted from the TP1 path (audit #2: LLM/heuristic partials previously
     did only `pos.qty -=`, vaporizing the banked leg PnL from equity,
     trades log, and learning).
  2. Graduated-rule PnL-weighted veto retirement (master plan P2 / audit #16):
     record_veto_outcome accumulates pnl_saved/pnl_missed and the retire
     criterion is accuracy<0.35 AND net_pnl_saved<=0.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.position_manager import PositionManager
from llm.graduated_rules import GraduatedRulesEngine, GraduatedRule


# ── Helpers ──────────────────────────────────────────────────────

def _make_pm(tmp_path):
    pm = PositionManager(taker_fee_bps=4)
    pm._backup_dir = tmp_path  # never touch live crash-recovery backups
    return pm


def _open_long(pm, symbol="ETH", entry=100.0, qty=1.0, leverage=2.0):
    pm.open_position(
        symbol=symbol, side="LONG", entry=entry, qty=qty,
        sl=entry * 0.95, tp1=entry * 1.05, tp2=entry * 1.10,
        atr=1.0, leverage=leverage,
    )
    return pm.positions[symbol]


# ── 1. partial_close accounting ──────────────────────────────────

def test_partial_close_books_pnl_fee_and_qty(tmp_path):
    pm = _make_pm(tmp_path)
    pos = _open_long(pm, entry=100.0, qty=1.0, leverage=2.0)
    fees_open = pos.fees_paid

    event = pm.partial_close("ETH", pct=0.5, price=110.0, action="LLM_EXIT_PARTIAL")

    assert event is not None
    assert event.action == "LLM_EXIT_PARTIAL"
    assert event.side == "LONG"
    assert event.qty == pytest.approx(0.5)
    # Leg PnL = (110-100) * 0.5 qty * 2x leverage = 10.0
    assert event.pnl == pytest.approx(10.0)
    # Fee = price * qty * 4bps
    assert event.fee == pytest.approx(110.0 * 0.5 * 0.0004)
    # Position accounting updated
    assert pos.qty == pytest.approx(0.5)
    assert pos.fees_paid == pytest.approx(fees_open + event.fee)
    assert pos.realized_pnl == pytest.approx(10.0 - event.fee)
    # Metadata for the main event loop
    assert event.metadata["remaining_qty"] == pytest.approx(0.5)
    assert event.metadata["partial_pct"] == 0.5


def test_partial_close_short_side_pnl_sign(tmp_path):
    pm = _make_pm(tmp_path)
    pm.open_position(
        symbol="ETH", side="SHORT", entry=100.0, qty=1.0,
        sl=105.0, tp1=95.0, tp2=90.0, atr=1.0, leverage=1.0,
    )
    event = pm.partial_close("ETH", pct=0.5, price=90.0)
    assert event is not None
    # SHORT leg PnL = (100-90) * 0.5 * 1x = +5.0
    assert event.pnl == pytest.approx(5.0)


def test_partial_close_allocates_funding_share(tmp_path):
    pm = _make_pm(tmp_path)
    pos = _open_long(pm, entry=100.0, qty=1.0, leverage=1.0)
    pos.funding_costs = 2.0  # accrued funding before the partial

    event = pm.partial_close("ETH", pct=0.5, price=100.0)
    assert event is not None
    # Half the funding allocated to the leg, half remains for the final close
    assert pos.funding_costs == pytest.approx(1.0)
    assert pos.realized_pnl == pytest.approx(0.0 - event.fee - 1.0)


def test_partial_close_never_zeroes_position(tmp_path):
    pm = _make_pm(tmp_path)
    pos = _open_long(pm, entry=100.0, qty=1.0)
    # pct=1.0 must NOT fully close (a "partial" keeps a remainder)
    event = pm.partial_close("ETH", pct=1.0, price=105.0)
    if event is not None:
        assert pos.qty > 0
    else:
        assert pos.qty == pytest.approx(1.0)  # untouched on refusal


def test_partial_close_missing_or_closed_position_returns_none(tmp_path):
    pm = _make_pm(tmp_path)
    assert pm.partial_close("ETH", pct=0.5, price=100.0) is None
    pos = _open_long(pm, entry=100.0, qty=1.0)
    pm.force_close("ETH", 100.0, "TEST")
    assert pm.partial_close("ETH", pct=0.5, price=100.0) is None


def test_partial_close_qty_override_matches_exchange_fill(tmp_path):
    pm = _make_pm(tmp_path)
    pos = _open_long(pm, entry=100.0, qty=2.0)
    event = pm.partial_close("ETH", pct=0.5, price=100.0, qty=0.75)
    assert event is not None
    assert event.qty == pytest.approx(0.75)
    assert pos.qty == pytest.approx(1.25)


def test_final_close_after_partial_totals_full_trade(tmp_path):
    """Partial leg + final close must sum to the whole trade's PnL
    (the black hole was the partial leg never being booked anywhere)."""
    pm = _make_pm(tmp_path)
    pos = _open_long(pm, entry=100.0, qty=1.0, leverage=1.0)
    leg1 = pm.partial_close("ETH", pct=0.5, price=110.0)
    final = pm.force_close("ETH", 110.0, "TEST_FINAL")
    assert leg1 is not None and final is not None
    # Both legs: 0.5 qty each at +10 -> +5.0 each (gross)
    assert leg1.pnl == pytest.approx(5.0)
    assert final.pnl == pytest.approx(5.0)
    # realized_pnl carries the full trade net of CLOSE-leg fees (the open fee
    # lives only in fees_paid — same convention as the TP1/full-close path)
    assert pos.realized_pnl == pytest.approx(
        10.0 - leg1.fee - final.fee, abs=1e-6
    )


# ── 2. PnL-weighted veto retirement ──────────────────────────────

def _veto_engine(rule_id="veto_pnl_1"):
    engine = GraduatedRulesEngine()
    engine._loaded = True
    engine._save = lambda: None
    rule = GraduatedRule(
        rule_id=rule_id,
        hypothesis_statement="test veto",
        action="veto",
        conditions={"symbol": "SOL", "side": "BUY"},
        active=True,
    )
    engine._rules = [rule]
    return engine, rule


def test_veto_outcome_accumulates_pnl_saved_and_missed():
    engine, rule = _veto_engine()
    engine.record_veto_outcome([rule.rule_id], won=False, hypothetical_pnl_pct=-3.0)
    engine.record_veto_outcome([rule.rule_id], won=True, hypothetical_pnl_pct=1.5)
    assert rule.pnl_saved == pytest.approx(3.0)
    assert rule.pnl_missed == pytest.approx(1.5)
    assert rule.net_pnl_saved == pytest.approx(1.5)


def test_money_saving_veto_survives_low_hit_rate():
    """acc < 0.35 but net_pnl_saved > 0 -> must stay active (the
    hype_long_veto failure mode: rate-only scoring retired a net saver)."""
    engine, rule = _veto_engine()
    # 3 correct blocks of big losers (saves 5% each)
    for _ in range(3):
        engine.record_veto_outcome([rule.rule_id], won=False, hypothetical_pnl_pct=-5.0)
    # 7 wrong blocks of small winners (misses 0.5% each)
    for _ in range(7):
        engine.record_veto_outcome([rule.rule_id], won=True, hypothetical_pnl_pct=0.5)
    assert rule.times_applied == 10
    assert rule.accuracy < 0.35
    assert rule.net_pnl_saved > 0
    assert rule.active is True  # would have been retired under rate-only scoring


def test_net_losing_veto_still_retires():
    engine, rule = _veto_engine()
    for _ in range(3):
        engine.record_veto_outcome([rule.rule_id], won=False, hypothetical_pnl_pct=-0.5)
    for _ in range(7):
        engine.record_veto_outcome([rule.rule_id], won=True, hypothetical_pnl_pct=4.0)
    assert rule.accuracy < 0.35
    assert rule.net_pnl_saved <= 0
    assert rule.active is False


def test_veto_outcome_backward_compatible_without_pnl():
    """Legacy call sites (no pnl kwarg) must keep working; zero-pnl history
    retires exactly as before (net_pnl_saved == 0 -> <= 0)."""
    engine, rule = _veto_engine()
    for _ in range(10):
        engine.record_veto_outcome([rule.rule_id], won=True)
    assert rule.times_applied == 10
    assert rule.accuracy < 0.35
    assert rule.active is False
