"""Canonical, cwd-independent path anchoring for the bot's "brain" files.

WHY THIS EXISTS (2026-07-15/19/20 incident chain):
  The bot's data/state/ledger/heartbeat paths were historically written as
  cwd-relative literals (e.g. ``"data/trade_ledger.csv"``, ``os.path.join(
  "data", "position_state.json")``) scattered across modules such as
  execution/risk.py, execution/auto_recovery.py, monitoring/health.py,
  execution/reconciliation.py and llm/agents/prompt_enricher.py. Those paths
  only resolve correctly when the process is launched with cwd == bot/.

  When the bot was ever launched from the wrong working directory (a bad
  scheduled-task shortcut, a supervisor cwd bug, a shell that cd'd
  somewhere else), every "data/..." literal silently resolved to a *new*
  location and Python/os happily created it via os.makedirs / open(...,
  "w") — no error, no crash, just a brand-new empty "brain". The bot then
  traded off zero history: no ledger, no position state, no learned edges.
  This produced a confirmed 7-day silent-trading incident, and left
  physical evidence on disk: an orphan directory
  ``C:\\Users\\vince\\WAGMI\\paper_trades`` one level ABOVE bot/, created by
  exactly this failure class (a launch whose cwd was the repo root instead
  of repo root/bot).

  Some newer modules (watchdog.py, api_server.py, feedback/live_edge.py,
  llm/agents/dynamic_stats.py) already anchor correctly via
  ``Path(__file__).resolve().parent[.parent]``. This module generalizes
  that pattern into one canonical source of truth so every module can stop
  reinventing (and sometimes getting wrong) its own relative path.

WHAT THIS MODULE DOES NOT DO (yet):
  It does NOT change any other module's behavior and it is NOT wired into
  run.py's startup sequence. Nothing here is imported/called by production
  code paths yet — see Phase 0.1 scope notes. This is the foundation only:
  canonical paths + a boot-integrity check that callers can opt into later.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("bot.core.paths")

# ---------------------------------------------------------------------------
# Canonical anchors — NEVER derived from cwd.
#
# This file lives at bot/core/paths.py, so its parent is bot/core/ and its
# grandparent is bot/. Anchoring off __file__ means these constants resolve
# correctly no matter what directory the process was launched from or later
# chdir'd to.
# ---------------------------------------------------------------------------
BOT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BOT_ROOT / "data"


class BootIntegrityError(RuntimeError):
    """Raised when the bot's on-disk "brain" cannot be found/trusted at boot.

    The correct response to this error is to REFUSE TO START, not to fall
    back to creating a fresh empty ledger/state file. Silently auto-creating
    those files is exactly the failure mode that caused the 7-day silent
    ledger-loss incident this module exists to prevent.
    """


# ---------------------------------------------------------------------------
# Critical "brain" file accessors.
#
# Only files actually referenced elsewhere in the codebase are included here
# (verified via grep across bot/ before writing this module):
#   - trade_ledger.csv        feedback/trade_ledger.py (TradeLedger._csv_path,
#                              default data_dir="data"), cli.py, daily_report.py
#   - position_state.json     execution/auto_recovery.py, watchdog.py,
#                              api_server.py, tools/gen_state.py, tools/daily_digest.py
#   - risk_equity_state.json  execution/risk.py, api_server.py,
#                              multi_strategy_main.py, tools/check_invariants.py
#   - circuit_breaker_state.json  execution/reconciliation.py,
#                              llm/agents/prompt_enricher.py, tools/daily_digest.py,
#                              tools/accumulate_snapshot.py
#   - heartbeat.json          monitoring/health.py, watchdog.py
#   - epoch_start.json        data/epoch.py, referenced by execution/risk.py,
#                              feedback/trade_ledger.py, tools/proof_window.py
#
# These are read-only path accessors: they return where the file SHOULD be,
# they do not create it. Existence is checked by assert_boot_integrity(),
# not here.
# ---------------------------------------------------------------------------

def trade_ledger_path() -> Path:
    """Path to the trade ledger CSV — the de-biased source of truth for
    every closed trade's net PnL. This is the single most important "brain"
    file: if it's missing/empty, the bot has no memory of its own history."""
    return DATA_DIR / "trade_ledger.csv"


def position_state_path() -> Path:
    """Path to the open-position state snapshot used for crash recovery."""
    return DATA_DIR / "position_state.json"


def risk_equity_state_path() -> Path:
    """Path to the risk/equity state used by circuit breakers and the
    daily-loss-limit calculation (current-equity anchor)."""
    return DATA_DIR / "risk_equity_state.json"


def circuit_breaker_state_path() -> Path:
    """Path to the circuit breaker (consecutive-loss / drawdown) state."""
    return DATA_DIR / "circuit_breaker_state.json"


def heartbeat_path() -> Path:
    """Path to the liveness heartbeat file written by monitoring/health.py
    and read by watchdog.py to detect stalls/crashes."""
    return DATA_DIR / "heartbeat.json"


def epoch_start_path() -> Path:
    """Path to the current trading epoch's baseline stamp (equity anchor +
    start timestamp for the current "clean flat" epoch)."""
    return DATA_DIR / "epoch_start.json"


def equity_epoch_path() -> Path:
    """Path to the CODE-OWNED epoch marker written by data/epoch.py's
    start_epoch() (Phase 0.5 PR-1). This supersedes the hand-edited
    epoch_start_path() -- once this file exists, data/epoch.py's reader
    prefers it (see epoch.py::_epoch_path() fallback order: EPOCH_START_FILE
    env -> equity_epoch.json if exists -> legacy epoch_start.json). Unlike
    epoch_start_path(), this file is NEVER hand-edited: start_epoch() is the
    only writer, and it dual-fences (timestamp + raw ledger row-count/
    trade-id) so the epoch_id fence in feedback/trade_ledger.py's auto-stamp
    is no longer dead."""
    return DATA_DIR / "equity_epoch.json"


def trade_outcomes_path() -> Path:
    """Path to the per-trade outcomes CSV (data/learning.py:record_trade_outcome).

    Added for Phase 0.2 (core/provenance.py write-time pollution gate) --
    this is the file that absorbed 253 fabricated POPCAT rows (~23% of the
    file) from a backtest run that reused the live write path. Every ML
    training/graduation reader treats this file as ground truth, so
    provenance.gate_live_write() protects it explicitly."""
    return DATA_DIR / "analysis" / "trade_outcomes.csv"


def position_journal_path() -> Path:
    """Path to the write-ahead position lifecycle journal (Phase 0.3b,
    core/position_journal.py). Append-only log of OPEN / CLOSING /
    CLOSED_BOOKED events keyed by position_id, used for exactly-once
    crash recovery of the close-then-book sequence (see position_journal.py
    module docstring for the "-$370 double-count" / "silent drop" incident
    class this exists to make detectable)."""
    return DATA_DIR / "position_journal.jsonl"


def close_outbox_path() -> Path:
    """Path to the append-only durable close-delivery log (Phase 0.4-B2,
    core/close_pipeline/close_outbox.py). Each line is one TradeClosed
    event, written durably (fsync'd append) BEFORE the CloseBus runs any
    subscriber, so a crash between "fill happened" and "subscribers ran"
    leaves a durable, replayable record on disk instead of a silently lost
    close. Not read/written by any live code path yet -- Phase B builds
    this in isolation; the god-block in multi_strategy_main.py remains the
    authoritative live close path until Phase D/E."""
    return DATA_DIR / "close_outbox.jsonl"


def momentum_state_path() -> Path:
    """Path to the per-symbol win/loss streak state used for sizing
    multipliers (execution/momentum_tracker.py).

    Added for Phase 0.2 -- this file previously had a live ``"TEST"`` key
    written into it by a test/sim process sharing the live state path."""
    return DATA_DIR / "momentum_state.json"


# The trade ledger is the minimum bar for "the bot has memory": every other
# state file can in principle be reconstructed/regenerated (position_state
# from exchange reconciliation, heartbeat is transient, circuit breaker
# state can restart neutral) but a missing/empty ledger means zero learned
# history. This is intentionally a short list, not every accessor above.
_REQUIRED_NONEMPTY = (trade_ledger_path,)


def assert_boot_integrity() -> None:
    """Refuse to start if the anchored data directory or "brain" files look
    wrong, and normalize the process cwd to BOT_ROOT.

    Two responsibilities, both load-bearing for the same incident class:

    1. Normalize cwd -> BOT_ROOT. The rest of the codebase (run.py,
       health.py, risk.py, auto_recovery.py, reconciliation.py, ...) still
       uses cwd-relative "data/..." literals and is launched via
       ``cd bot && python run.py paper`` (see run.py's own cwd-relative
       ``os.makedirs("logs", ...)`` at startup). Forcing cwd to BOT_ROOT is
       the least-behavior-change fix: every existing relative path resolves
       correctly afterward, with no need to touch those modules yet.
    2. Verify the anchored DATA_DIR and the trade ledger actually exist and
       are non-empty. If not, raise BootIntegrityError instead of letting
       downstream code auto-create a fresh empty ledger/state directory --
       that silent auto-create is precisely what produced the 7-day
       silent-trading incident.

    WARNING -- NOT WIRED, DO NOT WIRE CASUALLY: as of this writing, this
    function has ZERO production callers (nothing in run.py or any other
    live entry point calls it). Wiring it in is a real boot-behavior
    change, not a no-op refactor: it performs an ``os.chdir()`` (rule 1
    above) AND can outright refuse to start the process by raising
    BootIntegrityError (rule 2 above). Do not add a call site to this
    function as an incidental/drive-by edit -- that is a deliberate
    decision requiring its own validation first: confirm the chdir is safe
    for every actual launch path (Task Scheduler's cwd, a manual
    ``cd bot && python run.py``, any other entry point), and confirm
    ``_REQUIRED_NONEMPTY`` correctly reflects every file that can
    legitimately be absent/empty on a fresh epoch (an epoch reset must not
    itself trip this and refuse to boot).

    Raises:
        BootIntegrityError: if DATA_DIR is missing, or if any file in
            _REQUIRED_NONEMPTY is missing or empty (0 bytes).
    """
    if not DATA_DIR.is_dir():
        raise BootIntegrityError(
            f"BOOT INTEGRITY FAILURE: anchored DATA_DIR does not exist: "
            f"{DATA_DIR}. Refusing to start rather than auto-create a fresh "
            f"'brain-wipe' data directory. BOT_ROOT resolved to {BOT_ROOT} "
            f"(anchored via __file__, not cwd) -- if this looks wrong, the "
            f"repo layout may have changed; if it looks right, the data/ "
            f"directory is genuinely missing/misplaced."
        )

    missing_or_empty = []
    for accessor in _REQUIRED_NONEMPTY:
        p = accessor()
        if not p.exists():
            missing_or_empty.append(f"{p} (missing)")
        elif p.stat().st_size == 0:
            missing_or_empty.append(f"{p} (empty)")

    if missing_or_empty:
        raise BootIntegrityError(
            "BOOT INTEGRITY FAILURE: required brain file(s) missing or "
            "empty, refusing to start: " + "; ".join(missing_or_empty) +
            ". Auto-creating these would silently start the bot on a fresh "
            "empty ledger -- exactly the failure mode that caused the "
            "7-day silent-trading incident. If this is an intentional new "
            "epoch/environment, seed the file explicitly first."
        )

    cwd = Path.cwd().resolve()
    if cwd != BOT_ROOT:
        logger.warning(
            "Boot cwd (%s) != anchored BOT_ROOT (%s); normalizing cwd to "
            "BOT_ROOT so existing cwd-relative 'data/...' literals elsewhere "
            "in the codebase resolve correctly.", cwd, BOT_ROOT,
        )
        os.chdir(BOT_ROOT)


def detect_orphan_dirs() -> list[Path]:
    """Read-only detection of suspicious data-like directories OUTSIDE bot/.

    This is the diagnostic counterpart to the incident that motivated this
    module: a wrong-cwd launch created ``WAGMI/paper_trades`` as a sibling
    of ``WAGMI/bot`` instead of writing into ``WAGMI/bot/data/...``. This
    function never deletes or modifies anything -- it only reports
    candidates so they can be logged/alerted on and investigated by hand.

    Returns:
        A list of existing directories, siblings of BOT_ROOT (i.e. under
        BOT_ROOT.parent), whose names match known data/state directory
        names that belong inside bot/data/ -- these are the class of
        orphan produced by a wrong-cwd launch.
    """
    parent = BOT_ROOT.parent
    # Names mirrored from DATA_DIR's own known subdirectories/files plus the
    # specific orphan already observed in production ("paper_trades"). If a
    # directory with one of these names exists as a SIBLING of bot/ (i.e.
    # one level above bot/, where a wrong-cwd launch would have written it)
    # it is almost certainly a brain-wipe orphan, not intentional.
    _SUSPECT_NAMES = (
        "paper_trades",
        "data",
        "logs",
        "manual",
        "llm",
        "learning",
        "feedback",
    )
    orphans: list[Path] = []
    if not parent.exists():
        return orphans
    try:
        for name in _SUSPECT_NAMES:
            candidate = parent / name
            if candidate.is_dir():
                orphans.append(candidate)
    except OSError:
        # Best-effort diagnostic only; never raise from a read-only detector.
        pass
    return orphans
