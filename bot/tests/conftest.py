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

import logging
import os
import sys

import pytest

# Apply before any test module imports trading_config
os.environ.setdefault("TAKER_FEE_BPS", "4")

# ---------------------------------------------------------------------------
# LIVE-WRITE GUARD (2026-10-09) -- must run before ANY bot module is imported.
# Installs an un-removable audit hook that makes every write into a live
# bot/data or bot/logs dir raise LiveWriteBlocked (OSError), and points WAGMI_LOG_DIR at
# a per-session sandbox so import-time setup_logging() can't attach a handler
# to the live log. See tests/live_write_guard.py for the incident + design.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_write_guard  # noqa: E402

_SANDBOX = live_write_guard.install()


def _strip_live_file_handlers() -> None:
    """Close + detach any logging FileHandler whose file sits in a protected
    root (belt-and-braces: the audit hook already refuses to open one)."""
    loggers = [logging.getLogger()] + [
        l for l in logging.Logger.manager.loggerDict.values()
        if isinstance(l, logging.Logger)
    ]
    for lg in loggers:
        for h in list(lg.handlers):
            fn = getattr(h, "baseFilename", None)
            if fn and live_write_guard.is_protected(fn):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass


@pytest.fixture(autouse=True, scope="session")
def _live_write_guard_session():
    _strip_live_file_handlers()
    yield _SANDBOX
    _strip_live_file_handlers()


# Writers whose default (cwd-relative or core.paths-anchored) target is under
# bot/data and which tests exercise WITHOUT redirecting it themselves. The
# guard above would refuse those writes (and fail the test); instead each
# test gets a private tmp copy of the path. A test that sets its own path
# via monkeypatch still wins (its patch is applied after this autouse one).
#   (module, attribute, relative path under the per-test redirect dir)
_REDIRECTED_WRITERS = (
    ("llm.memory_store", "_MEMORY_DIR", "llm"),
    ("llm.memory_store", "_MEMORY_PATH", "llm/llm_memory.json"),
    ("execution.risk", "_SAFETY_LOG_DIR", "logs"),
    ("execution.risk", "_SAFETY_LOG_FILE", "logs/safety_events.csv"),
    ("execution.position_state", "_LOG_DIR", "logs"),
    ("execution.position_state", "_LOG_FILE", "logs/state_transitions.csv"),
    ("execution.adaptive_risk", "_ADAPTIVE_SIZER_STATE_PATH",
     "feedback/adaptive_sizer_state.json"),
)


@pytest.fixture(autouse=True)
def _redirect_known_writers(monkeypatch, tmp_path_factory):
    import importlib
    from pathlib import Path

    redirect = tmp_path_factory.mktemp("wagmi_redirect")
    for mod_name, attr, rel in _REDIRECTED_WRITERS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, os.path.join(str(redirect), *rel.split("/")))
    try:
        from core.close_pipeline import close_outbox
        monkeypatch.setattr(close_outbox, "outbox_path",
                            lambda: Path(redirect) / "close_outbox.jsonl")
    except Exception:
        pass
    yield redirect


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


def pytest_terminal_summary(terminalreporter):
    """Surface writes the live-write guard refused. Most are swallowed by the
    writer's own try/except, so they'd otherwise be invisible; each line is a
    test that still lacks a tmp redirect for that writer."""
    from collections import Counter

    blocked = live_write_guard.state()["blocked"]
    if not blocked:
        return
    counts = Counter(p for _, p in blocked)
    terminalreporter.write_sep("-", f"live-write guard refused {len(blocked)} write(s)")
    for path, n in counts.most_common(30):
        terminalreporter.write_line(f"  {n:5d}  {path}")
