"""Tests for the BLOCKED_GO_PROBE forward-evidence valve.

Context: from 2026-07-29 to 2026-09-12 the ENTRY_SELECTIVITY gate blocked 100%
of the entries the LLM-FIRST path proposed. The gate was right on the evidence
it had (solo entries: n=32, WR 18.8% vs a 57% fee-adjusted breakeven, net -$549)
but the result was 45 days of zero trades and therefore zero new evidence — the
gates are derived from a ledger the gates themselves stopped growing.

BLOCKED_GO_PROBE lets a small, hard-capped fraction of blocked entries through
at ~0.1x size, tagged EXPLORATION so no learning input mistakes them for edge.
These tests pin the safety properties: off by default, capped, and incapable of
loosening the gate itself.
"""
from __future__ import annotations

import pytest

from core import entry_selectivity as es


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("BLOCKED_GO_PROBE", "BLOCKED_GO_PROBE_RATE",
              "BLOCKED_GO_PROBE_SIZE_MULT", "EXPLORATION_RISK_MULT"):
        monkeypatch.delenv(k, raising=False)
    yield


# ------------------------------------------------------------------ default off


def test_probe_is_off_by_default():
    assert es.blocked_go_probe_enabled() is False


@pytest.mark.parametrize("val", ["false", "0", "no", "", "off", "maybe"])
def test_only_explicit_truthy_values_enable_it(monkeypatch, val):
    monkeypatch.setenv("BLOCKED_GO_PROBE", val)
    assert es.blocked_go_probe_enabled() is False


@pytest.mark.parametrize("val", ["true", "1", "yes", "TRUE", " True "])
def test_truthy_values_enable_it(monkeypatch, val):
    monkeypatch.setenv("BLOCKED_GO_PROBE", val)
    assert es.blocked_go_probe_enabled() is True


# --------------------------------------------------------------------- rate cap


def test_default_rate():
    assert es.blocked_go_probe_rate() == pytest.approx(0.15)


def test_rate_is_hard_capped_at_half(monkeypatch):
    """The valve must never become a way to re-open a drain wholesale."""
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "1.0")
    assert es.blocked_go_probe_rate() == 0.5
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "99")
    assert es.blocked_go_probe_rate() == 0.5


def test_rate_cannot_go_negative(monkeypatch):
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "-1")
    assert es.blocked_go_probe_rate() == 0.0


def test_rate_junk_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "banana")
    assert es.blocked_go_probe_rate() == pytest.approx(0.15)


# --------------------------------------------------------------------- size cap


def test_size_defaults_to_exploration_risk_mult(monkeypatch):
    monkeypatch.setenv("EXPLORATION_RISK_MULT", "0.2")
    assert es.blocked_go_probe_size_mult() == pytest.approx(0.2)


def test_size_default_when_nothing_set():
    assert es.blocked_go_probe_size_mult() == pytest.approx(0.1)


def test_explicit_size_overrides_exploration_mult(monkeypatch):
    monkeypatch.setenv("EXPLORATION_RISK_MULT", "0.2")
    monkeypatch.setenv("BLOCKED_GO_PROBE_SIZE_MULT", "0.05")
    assert es.blocked_go_probe_size_mult() == pytest.approx(0.05)


def test_size_never_exceeds_full_size(monkeypatch):
    """A probe is a probe. It can never be sized up into a conviction entry."""
    monkeypatch.setenv("BLOCKED_GO_PROBE_SIZE_MULT", "5")
    assert es.blocked_go_probe_size_mult() == 1.0


def test_size_has_a_floor(monkeypatch):
    monkeypatch.setenv("BLOCKED_GO_PROBE_SIZE_MULT", "0")
    assert es.blocked_go_probe_size_mult() == pytest.approx(0.01)


def test_size_junk_falls_back(monkeypatch):
    monkeypatch.setenv("BLOCKED_GO_PROBE_SIZE_MULT", "banana")
    assert es.blocked_go_probe_size_mult() == pytest.approx(0.1)


# ------------------------------------------------- the gate itself is untouched


def test_probe_flag_does_not_loosen_the_gate(monkeypatch):
    """The valve lives in the CALLER. evaluate_entry must still report a block
    for a blocked class regardless of the probe flags — otherwise a full-size
    entry could slip through with the probe enabled."""
    monkeypatch.setenv("ENTRY_SELECTIVITY", "true")
    monkeypatch.setenv("BLOCKED_GO_PROBE", "true")
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "0.5")
    block_with, reasons_with, _ = es.evaluate_entry(
        num_agree=1, ev_per_dollar=0.1, loss_streak=0, is_exploration=False,
        symbol="BTC", side="SELL", regime="high_volatility",
    )
    monkeypatch.setenv("BLOCKED_GO_PROBE", "false")
    block_without, reasons_without, _ = es.evaluate_entry(
        num_agree=1, ev_per_dollar=0.1, loss_streak=0, is_exploration=False,
        symbol="BTC", side="SELL", regime="high_volatility",
    )
    assert block_with == block_without
    assert reasons_with == reasons_without


def test_exploration_entries_stay_exempt(monkeypatch):
    """The probe path works by tagging the entry as exploration; that exemption
    is the mechanism, so it must hold."""
    monkeypatch.setenv("ENTRY_SELECTIVITY", "true")
    block, reasons, _ = es.evaluate_entry(
        num_agree=1, ev_per_dollar=-1.0, loss_streak=99, is_exploration=True,
        symbol="BTC", side="SELL", regime="high_volatility",
    )
    assert block is False
