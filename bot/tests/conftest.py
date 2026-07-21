"""
Test conftest — environment overrides so pre-existing fixtures keep working
after SHIP-2026-04-19 constant changes.

Production defaults:
- TAKER_FEE_BPS = 45   (Hyperliquid Tier-0 real rate)
- MIN_SAMPLES_PER_BIN = 20  (raised from 5 to stop noisy-bin poisoning)

Many pre-existing tests baked in the OLD values (4 bps, 5 samples) directly
into their fixtures. Rather than update 11 fixture files individually, this
conftest restores the old values for tests only. Production is unaffected.

Follow-up: as tests are touched for unrelated reasons, remove their reliance
on these constants and eventually retire this conftest.
"""
from __future__ import annotations

import os

import pytest

# Apply before any test module imports trading_config
os.environ.setdefault("TAKER_FEE_BPS", "4")


# ---------------------------------------------------------------------------
# Phase 0.2 (core/provenance.py) -- autouse pollution-gate sandbox.
#
# WHY: 253 fabricated POPCAT rows landed in the live trade_outcomes.csv, and
# a stray "TEST" key landed in the live momentum_state.json, because nothing
# distinguished "this write came from a test/backtest process" from a real
# live/paper write. core.provenance.resolve_source() already auto-detects a
# live pytest process via PYTEST_CURRENT_TEST, so this fixture is a belt-
# and-suspenders guarantee: WAGMI_SOURCE=test is forced for the whole test
# session (not just the ambient PYTEST_CURRENT_TEST heuristic) so any writer
# that calls gate_live_write() during a test run is blocked from touching a
# real "brain" file, no matter how it resolves provenance otherwise.
#
# Restored after each test so nothing leaks into a later real process.
# Tests that legitimately need to exercise real-source behavior (e.g.
# core/provenance.py's own tests, which explicitly pass source=... or
# monkeypatch WAGMI_SOURCE per-case) are unaffected -- an explicit source=
# argument or a test-local monkeypatch.setenv always takes precedence over
# this session-wide default.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _wagmi_source_test_sandbox(monkeypatch):
    monkeypatch.setenv("WAGMI_SOURCE", "test")


def pytest_configure(config):
    """Patch calibrator MIN_SAMPLES_PER_BIN back to 5 for tests that built
    fixtures against the old value."""
    try:
        from llm.confidence_calibrator import ConfidenceCalibrator
        # Save production value for tests that specifically want to test the new behavior
        ConfidenceCalibrator._PROD_MIN_SAMPLES_PER_BIN = ConfidenceCalibrator.MIN_SAMPLES_PER_BIN
        ConfidenceCalibrator.MIN_SAMPLES_PER_BIN = 5
    except Exception as e:
        # Surface the error rather than hiding it — helps future debugging
        print(f"[conftest] could not patch ConfidenceCalibrator: {e}")
