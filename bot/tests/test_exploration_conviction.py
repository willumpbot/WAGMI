"""Tests for the conviction-aware exploration gate (2026-06-25).

Exploration (epsilon-greedy skip->go) used to override the LLM's skips BLINDLY,
including high-conviction -EV longs (overnight BTC/ETH/HYPE LONG: LLM skipped
with "0% WR / lacks credible edge / likely chops", exploration forced them, 3/3
stopped out -$64). The gate now only converts GENUINELY-UNCERTAIN skips and never
clearly -EV ones, behind EXPLORATION_RESPECT_CONVICTION (default true).

These tests exercise the REAL gate (multi_strategy_main.exploration_conviction_ok),
which is the same function the inline skip->go converter calls.
"""
import os

import pytest

from multi_strategy_main import exploration_conviction_ok


def test_high_conviction_neg_ev_skip_is_not_converted():
    """(a) The overnight bleed case: high-conviction skip on a -EV long.

    LLM is SURE (confidence=0.80) and quant win_prob is clearly negative-edge
    (0.30 < 0.40 floor). Exploration must DECLINE -> conviction_ok is False so
    the skip->go conversion never fires. Reproduces/blocks the BTC/ETH/HYPE LONG
    forced-entry bleed.
    """
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.80,
        win_prob=0.30,
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
        conv_thresh=0.65,
        wp_floor=0.40,
    )
    assert conviction_ok is False, "high-conviction -EV skip must NOT be explored"
    # Fails on BOTH arms: not uncertain (conf>=thresh) AND -EV (wp<floor)
    assert uncertain is False
    assert neg_ev is True


def test_uncertain_coinflip_skip_is_still_converted():
    """(b) Aggression preserved: a genuinely-uncertain coin-flip skip still explores.

    confidence=0.50 (< 0.65 thresh) and win_prob=0.52 (>= 0.40 floor, not -EV).
    This is exactly where exploration adds edge-data value, so the gate must
    ALLOW conversion (conviction_ok True). Confirms epsilon aggression is intact
    on uncertain/+EV setups.
    """
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.50,
        win_prob=0.52,
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
        conv_thresh=0.65,
        wp_floor=0.40,
    )
    assert conviction_ok is True, "uncertain +EV skip must still be explored (aggression)"
    assert uncertain is True
    assert neg_ev is False


def test_flag_off_reproduces_current_behavior():
    """(c) Regression guard: EXPLORATION_RESPECT_CONVICTION=false => prior behavior.

    With respect disabled, even a high-conviction -EV skip is eligible
    (conviction_ok True) exactly as before the gate existed.
    """
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.80,
        win_prob=0.30,
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=False,
    )
    assert conviction_ok is True, "flag OFF must reproduce blind (current) behavior"
    assert uncertain is True
    assert neg_ev is False


def test_toxic_cell_blocks_even_low_conviction():
    """-EV guard arm: a toxic regime cell blocks conversion regardless of conviction."""
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.45,  # low conviction (uncertain)
        win_prob=0.55,   # win_prob alone would pass
        is_toxic=True,
        reg_wr=None,
        reg_n=0,
        respect=True,
    )
    assert conviction_ok is False
    assert neg_ev is True


def test_zero_wr_cell_blocks_even_low_conviction():
    """-EV guard arm: a 0%-WR cell with n>=5 blocks conversion."""
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.45,
        win_prob=0.55,
        is_toxic=False,
        reg_wr=0.0,
        reg_n=5,
        respect=True,
    )
    assert conviction_ok is False
    assert neg_ev is True


def test_none_winprob_low_conviction_degrades_safe_to_convert():
    """(d) Missing win_prob must NOT force exploration nor block it on its own.

    With win_prob=None and a low-conviction skip in a clean cell, the -EV arm
    adds no block and the conviction arm allows it -> converts (matches prior
    behavior on the conviction arm).
    """
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.40,
        win_prob=None,
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
    )
    assert conviction_ok is True
    assert uncertain is True
    assert neg_ev is False


# ──────────────────────────────────────────────────────────────────────────
# UNIFIED TOXIC + EV-PRIMARY gate (2026-06-25 swarm #4 GATED FIX)
# ──────────────────────────────────────────────────────────────────────────


def test_unified_symbol_side_toxic_skip_not_admitted_on_either_source(monkeypatch):
    """(a) The force-admit hole: a toxic {sym}_{side} skip is NOT explored.

    Reproduces the BTC_SHORT bleed: 8% WR, n=13, PF 0.28, verdict
    NEGATIVE_EV_BLOCKED. The REGIME cell only gates at n>=20 (so is_toxic=False
    here), but the symbol-side verdict the LLM/counterfactual veto reads is
    toxic at n>=13. The unified gate must DECLINE via the symbol-side source
    even though the regime-cell source does not fire.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "true")
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.10,            # LOW go-confidence (inert under unified)
        win_prob=0.45,            # above wp floor — would pass on wp alone
        is_toxic=False,           # regime cell NOT toxic (only n>=20 gated)
        reg_wr=None,
        reg_n=13,
        respect=True,
        setup_verdict="NEGATIVE_EV_BLOCKED",
        setup_pf=0.28,
        setup_wr=8.0,
        setup_n=13,
        rr_tp1=2.0,
    )
    assert conviction_ok is False, "toxic symbol-side skip must NOT be explored"
    assert neg_ev is True

    # And it must ALSO decline on the PF<1.0 @ n>=13 source with no verdict str.
    ok2, _, neg2 = exploration_conviction_ok(
        skip_conf=0.10, win_prob=0.45, is_toxic=False, reg_wr=None, reg_n=13,
        respect=True, setup_verdict="", setup_pf=0.28, setup_wr=8.0, setup_n=13,
        rr_tp1=2.0,
    )
    assert ok2 is False
    assert neg2 is True


def test_unified_pos_ev_bear_short_still_explores(monkeypatch):
    """(b) Aggression preserved: a +EV bear short still explores.

    BTC_SHORT in trending_bear has a high regime win_prob (+EV, n=7 exp +$194).
    No toxic verdict, EV>0 -> the gate ADMITS even though go-confidence is low.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "true")
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.20,            # low go-confidence (non-binding)
        win_prob=0.58,            # strong regime win_prob -> +EV
        is_toxic=False,
        reg_wr=None,
        reg_n=7,
        respect=True,
        setup_verdict="MARGINAL",
        setup_pf=1.4,             # PF>=1.0 -> not toxic
        setup_wr=55.0,
        setup_n=7,
        rr_tp1=2.0,               # EV = .58*2 - .42 = 0.74 > 0
    )
    assert conviction_ok is True, "+EV bear short must still explore (aggression)"
    assert neg_ev is False


def test_unified_neg_ev_low_winprob_skip_declined(monkeypatch):
    """(c) An -EV low-win_prob skip is declined via the EV arm.

    win_prob below the EV breakeven for the given RR -> EV<=0 -> declined,
    even with no toxic verdict and a clean regime cell.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "true")
    monkeypatch.setenv("EXPLORATION_MIN_WINPROB", "0.40")
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.30,
        win_prob=0.30,            # below wp floor AND EV-negative
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
        setup_verdict="MARGINAL",
        setup_pf=None,
        setup_wr=None,
        setup_n=0,
        rr_tp1=1.5,               # EV = .30*1.5 - .70 = -0.25 <= 0
    )
    assert conviction_ok is False, "-EV low-win_prob skip must be declined"
    assert neg_ev is True


def test_unified_genuinely_uncertain_skip_still_converts(monkeypatch):
    """(d) Aggression: a genuinely-uncertain +EV skip still converts.

    Clean cell, win_prob just above floor, RR makes EV>0 -> ADMIT. This is the
    coin-flip-with-edge case where exploration adds data value.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "true")
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.50,
        win_prob=0.50,            # above floor
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
        setup_verdict=None,
        setup_pf=None,
        setup_wr=None,
        setup_n=None,
        rr_tp1=2.0,               # EV = .50*2 - .50 = 0.50 > 0
    )
    assert conviction_ok is True, "uncertain +EV skip must still explore"
    assert neg_ev is False


def test_unified_none_winprob_no_verdict_degrades_safe_to_convert(monkeypatch):
    """Missing win_prob / verdict must not force NOR block under unified mode.

    With no quant signals and a clean cell, neither the EV arm nor the toxic
    arm fires -> the gate admits (no -EV evidence). Degrades safe.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "true")
    conviction_ok, _, neg_ev = exploration_conviction_ok(
        skip_conf=0.80,            # high go-conf but NON-BINDING under unified
        win_prob=None,
        is_toxic=False,
        reg_wr=None,
        reg_n=0,
        respect=True,
        setup_verdict=None,
        setup_pf=None,
        setup_n=None,
        rr_tp1=None,
    )
    assert conviction_ok is True
    assert neg_ev is False


def test_unified_flag_off_reproduces_split_source_behavior(monkeypatch):
    """(e) Flag OFF = exact current (split-source, inverted-skip_conf) behavior.

    With EXPLORATION_UNIFIED_TOXIC=false the gate ignores the symbol-side
    verdict and the EV arm, and uses the inverted skip_conf primary. The toxic
    BTC_SHORT (symbol-side toxic, regime cell NOT toxic) is ADMITTED again —
    proving the flag is a faithful rollback of today's behavior.
    """
    monkeypatch.setenv("EXPLORATION_UNIFIED_TOXIC", "false")
    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=0.10,            # low -> uncertain=True under legacy primary
        win_prob=0.45,            # above floor -> legacy neg_ev arm clean
        is_toxic=False,           # regime cell not toxic
        reg_wr=None,
        reg_n=13,
        respect=True,
        setup_verdict="NEGATIVE_EV_BLOCKED",  # IGNORED when flag off
        setup_pf=0.28,                         # IGNORED when flag off
        setup_wr=8.0,
        setup_n=13,
        rr_tp1=2.0,                            # IGNORED when flag off
    )
    assert conviction_ok is True, "flag OFF must reproduce split-source admit"
    assert uncertain is True
    assert neg_ev is False


def test_default_env_thresholds_used_when_not_overridden(monkeypatch):
    """The gate reads EXPLORATION_* env vars when explicit args are omitted."""
    monkeypatch.setenv("EXPLORATION_RESPECT_CONVICTION", "true")
    monkeypatch.setenv("EXPLORATION_CONVICTION_MAX", "0.65")
    monkeypatch.setenv("EXPLORATION_MIN_WINPROB", "0.40")
    # high-conviction -EV: blocked via env defaults
    ok, _, _ = exploration_conviction_ok(
        skip_conf=0.80, win_prob=0.30, is_toxic=False, reg_wr=None, reg_n=0,
    )
    assert ok is False
    # uncertain +EV: allowed via env defaults
    ok2, _, _ = exploration_conviction_ok(
        skip_conf=0.50, win_prob=0.52, is_toxic=False, reg_wr=None, reg_n=0,
    )
    assert ok2 is True
