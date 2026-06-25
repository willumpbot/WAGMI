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
