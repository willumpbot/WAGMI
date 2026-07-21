"""Write-time pollution filter for the bot's live ledger/learning/state files.

WHY THIS EXISTS (Phase 0.2, 2026-07-20 -- follows Phase 0.1 core/paths.py):
  Backtest/test/sim processes have written directly into LIVE learning files
  because the writers themselves never distinguished *where the call was
  coming from*. Confirmed on-disk damage that motivated this module:

    - 253 fabricated POPCAT rows (~23% of the file) in
      ``bot/data/analysis/trade_outcomes.csv`` -- a backtest run reused the
      exact same ``record_trade_outcome()`` write path the live/paper bot
      uses, so simulated closes were appended straight into the file every
      dashboard, the Learning Agent, and Kelly/IC sizing all read as ground
      truth.
    - A stray ``"TEST"`` key written into
      ``bot/data/momentum_state.json`` by a test/sim process sharing the
      live state path, corrupting the momentum-streak sizing multiplier.

  Both incidents share one root cause: no single choke point existed where
  a write could be positively identified as "this came from a simulation"
  and stopped before it touched a live file. This module is that choke
  point. Every writer of ledger/learning/state files should call
  ``gate_live_write()`` immediately before it writes, and (where records are
  parsed from external/replay input) ``is_real_event()`` / ``quarantine()``
  to make sure malformed input is never silently dropped OR silently
  written.

DESIGN PRINCIPLE -- conservative about blocking real writes, aggressive
about blocking simulated ones:
  A false NEGATIVE here (a simulated write slips through) reproduces the
  POPCAT incident. A false POSITIVE (a genuine live/paper write gets
  blocked) stops the bot from trading. Both are bad, but they are not
  symmetric in this codebase's history -- the bot has previously gone dark
  for days when a defensive check misfired (see paths.py's own incident
  notes). So: source resolution below only escalates to a *blocking*
  (simulated) classification when it has positive evidence (an explicit
  source=, WAGMI_SOURCE env var, or a live pytest process). Ambiguous/unset
  provenance resolves to PAPER (a real, non-blocking source) -- never to a
  simulated one.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

from core import paths

logger = logging.getLogger("bot.core.provenance")


# ---------------------------------------------------------------------------
# Source taxonomy
# ---------------------------------------------------------------------------
class Source(str, Enum):
    """Where a write is coming from.

    LIVE / PAPER are REAL: the bot is actually trading (paper or live money)
    and its writes to ledger/learning/state files are ground truth.

    BACKTEST / TEST / SIM are SIMULATED: the process is replaying history,
    running the test suite, or otherwise generating synthetic events. Writes
    from these sources must never land in a live file.
    """

    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"
    TEST = "test"
    SIM = "sim"


REAL_SOURCES = frozenset({Source.LIVE, Source.PAPER})
SIMULATED_SOURCES = frozenset({Source.BACKTEST, Source.TEST, Source.SIM})

# Marker tokens that, if found in an otherwise-unrecognized source label or
# in a record's symbol/keys, indicate simulated/synthetic data.
_SIM_MARKER_TOKENS = ("TEST", "SIM", "BACKTEST", "MOCK", "FAKE", "DUMMY")

# Subdirectories of DATA_DIR that are explicitly SAFE for simulated writes --
# run-scoped backtest sinks and the quarantine sink itself both live under
# DATA_DIR but must never be treated as "live files" by the gate below.
_SIM_SAFE_SUBDIRS = frozenset({"backtest_runs", "quarantine"})


class PollutionError(RuntimeError):
    """Raised when a simulated/test-sourced write attempts to touch a live
    ledger/learning/state file.

    This is the exception that should have fired before the 253 fabricated
    POPCAT rows were ever appended to trade_outcomes.csv. If you are seeing
    this raised, the fix is almost always to redirect the caller's write to
    a run-scoped sink (see backtest/engine.py's use of this module), not to
    catch and suppress this error.
    """


class QuarantineError(RuntimeError):
    """Raised when quarantine() itself cannot persist a rejected record.

    Malformed live records must NEVER be silently dropped. If the
    quarantine sink can't be written to, that is a fatal condition for
    processing that record -- callers should not swallow this.
    """


def _coerce_source(value: Union[str, "Source"]) -> Source:
    if isinstance(value, Source):
        return value
    v = str(value).strip().lower()
    try:
        return Source(v)
    except ValueError:
        # Unrecognized label. If it looks like it's naming a sim/test
        # concept, treat it as TEST (blocking); otherwise fall back to the
        # conservative default (PAPER, non-blocking) rather than guessing.
        upper = v.upper()
        if any(tok in upper for tok in _SIM_MARKER_TOKENS):
            return Source.TEST
        return Source.PAPER


def resolve_source(source: Optional[Union[str, "Source"]] = None) -> Source:
    """Resolve the provenance of the current write.

    Resolution order (most to least specific):
      1. Explicit ``source`` argument, if given.
      2. ``WAGMI_SOURCE`` env var.
      3. ``ENVIRONMENT`` env var (paper -> PAPER, production/live -> LIVE).
      4. Live pytest process (``PYTEST_CURRENT_TEST`` set) -> TEST.
      5. Default: PAPER.

    Step 5 is intentionally a REAL source, not a simulated one -- this gate
    must never default-block genuine bot writes just because provenance was
    merely unspecified. It only blocks sources it can positively identify
    as simulated.
    """
    if source is not None:
        return _coerce_source(source)

    env_source = os.environ.get("WAGMI_SOURCE")
    if env_source:
        return _coerce_source(env_source)

    environment = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    if environment == "paper":
        return Source.PAPER
    if environment in ("production", "live"):
        return Source.LIVE

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return Source.TEST

    return Source.PAPER


def is_simulated(source: Optional[Union[str, "Source"]] = None) -> bool:
    """True if the resolved source must not write to live files."""
    return resolve_source(source) in SIMULATED_SOURCES


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _is_live_target(target: Path) -> bool:
    """True if ``target`` is inside DATA_DIR and NOT inside a known
    sim-safe subdirectory (backtest run sinks, the quarantine sink).

    Deliberately broad (anything under DATA_DIR is "live" by default) rather
    than an explicit filename whitelist -- new ledger/learning/state files
    get protected automatically instead of silently falling outside the
    gate the way trade_outcomes.csv did before this module existed.
    """
    data_dir = paths.DATA_DIR.resolve()
    try:
        rel = target.resolve().relative_to(data_dir)
    except ValueError:
        return False  # not under DATA_DIR at all -- not this gate's concern
    if rel.parts and rel.parts[0] in _SIM_SAFE_SUBDIRS:
        return False
    return True


def gate_live_write(target_path: Union[str, Path], *, source: Optional[Union[str, "Source"]] = None) -> None:
    """Raise PollutionError if a simulated-source write is about to hit a
    live data file. No-op for real sources or non-live targets.

    Call this immediately before opening ``target_path`` for writing/
    appending. See module docstring for the incident (253 fabricated
    POPCAT rows in trade_outcomes.csv) this exists to make structurally
    impossible.
    """
    resolved = resolve_source(source)
    if resolved in REAL_SOURCES:
        return

    target = Path(target_path)
    if not _is_live_target(target):
        return

    raise PollutionError(
        f"BLOCKED write to live file '{target}' from source={resolved.value!r}. "
        f"Simulated/test-sourced processes must not write to files under "
        f"{paths.DATA_DIR} (see core/provenance.py). If this is a "
        f"backtest/replay run, redirect its output to a run-scoped sink "
        f"(e.g. DATA_DIR/backtest_runs/<run_id>/...) instead of the live "
        f"path."
    )


# ---------------------------------------------------------------------------
# Record validation + quarantine
# ---------------------------------------------------------------------------
_REQUIRED_EVENT_KEYS = ("symbol", "side", "pnl")


def is_real_event(record: Dict[str, Any]) -> bool:
    """Validate that ``record`` is well-formed enough to be a real trade/
    learning event -- has the required keys, no sim/test markers, sane
    values.

    This does NOT resolve provenance (see gate_live_write for that) -- it
    catches the complementary failure mode: a record that *is* live but is
    malformed, or a record that carries an explicit test marker (e.g. a
    literal ``"TEST"`` key/value, mirroring the polluted momentum_state.json
    incident). Callers should route anything this rejects through
    quarantine() rather than writing OR silently dropping it.
    """
    if not isinstance(record, dict):
        return False

    for key in _REQUIRED_EVENT_KEYS:
        if key not in record or record.get(key) in (None, ""):
            return False

    # Explicit sim/test marker keys anywhere in the record (mirrors the
    # literal "TEST" key found live in momentum_state.json).
    for marker in _SIM_MARKER_TOKENS:
        if marker in record:
            return False

    symbol = str(record.get("symbol", "")).strip().upper()
    if not symbol or any(tok in symbol for tok in _SIM_MARKER_TOKENS):
        return False

    side = str(record.get("side", "")).strip().upper()
    if side not in ("BUY", "SELL", "LONG", "SHORT"):
        return False

    try:
        float(record.get("pnl"))
    except (TypeError, ValueError):
        return False

    # Explicit source/flag fields, if present, must not claim simulated.
    for flag_key in ("source", "is_test", "is_sim", "is_backtest", "test", "sim", "backtest"):
        if flag_key not in record:
            continue
        val = record[flag_key]
        if isinstance(val, bool) and val:
            return False
        if isinstance(val, str) and any(tok in val.strip().upper() for tok in _SIM_MARKER_TOKENS):
            return False

    return True


def quarantine(
    record: Dict[str, Any],
    reason: str,
    target_path: Union[str, Path],
    *,
    timestamp: Optional[str] = None,
) -> Path:
    """Persist a rejected record to the quarantine sink. NEVER silently
    drops a record -- either it lands in the quarantine file, or this
    raises QuarantineError so the caller knows the record is unaccounted
    for.

    Sink location: ``DATA_DIR/quarantine/<basename-of-target>.jsonl`` (one
    line of JSON per rejected record, newest last).

    Args:
        record: the rejected record (any JSON-serializable dict).
        reason: short human-readable reason it was rejected.
        target_path: the live file this record WOULD have been written to
            -- used only to name the quarantine sink file, never opened.
        timestamp: optional pre-computed ISO-8601 timestamp; if omitted,
            uses the current UTC time (a plain ``datetime.now()`` call,
            same as every other write-timestamp in this codebase).
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    target = Path(target_path)
    sink_dir = paths.DATA_DIR / "quarantine"
    entry = {
        "timestamp": ts,
        "reason": reason,
        "target": str(target),
        "record": record,
    }
    try:
        sink_dir.mkdir(parents=True, exist_ok=True)
        sink_path = sink_dir / f"{target.stem}.jsonl"
        with open(sink_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:
        raise QuarantineError(
            f"Failed to quarantine record (reason={reason!r}) intended for "
            f"{target}: {e}. This record is now UNACCOUNTED FOR -- it was "
            f"neither written to the live target nor persisted to "
            f"quarantine."
        ) from e

    logger.warning(
        "Quarantined record for %s (reason=%s) -> %s", target, reason, sink_path
    )
    return sink_path
