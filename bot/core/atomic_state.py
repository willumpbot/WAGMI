"""Crash-safe atomic JSON/text writes for the bot's on-disk state files.

WHY THIS EXISTS (Phase 0.3a, 2026-07-20 -- follows Phase 0.1 core/paths.py
and Phase 0.2 core/provenance.py):
  Several critical state files (``position_state.json``,
  ``risk_equity_state.json``, ``circuit_breaker_state.json``) were written
  with plain ``open(path, "w")`` + ``json.dump(...)``, sometimes followed by
  a manual "remove-then-rename" dance to work around Windows' historical
  refusal to ``os.rename()`` onto an existing file. Both patterns share the
  same failure class: if the process dies (crash, OOM kill, power loss,
  forced Task Scheduler termination) at ANY point between opening the file
  and the write completing, the file on disk is left TRUNCATED or, in the
  remove-then-rename case, the target can be flat-out MISSING (deleted, but
  the rename that was supposed to replace it never happened) -- see the
  broken sequence formerly in execution/auto_recovery.py::save_position_state:

      tmp_path = filepath + ".tmp"
      with open(tmp_path, "w") as f:
          json.dump(state, f, indent=2)
      if os.path.exists(filepath):
          os.remove(filepath)          # <-- window of total data loss here
      os.rename(tmp_path, filepath)    # <-- and this can itself still fail

  A crash in that window (between the ``os.remove`` and the ``os.rename``)
  leaves NO position_state.json at all, and the bot boots believing it has
  zero open positions -- silent state loss, not even a corrupt-file error
  to notice.

  ``bot/monitoring/health.py::write_heartbeat_atomic`` already solved this
  correctly for the heartbeat file: write to a unique temp file in the SAME
  directory (so the final replace is on the same filesystem/volume and thus
  atomic), ``flush()`` + ``os.fsync()`` the file descriptor so the bytes are
  actually durable on disk (not just sitting in an OS buffer) before the
  swap, then a single ``os.replace()`` call -- which is atomic on BOTH
  POSIX and Windows (unlike ``os.rename``, which raises on Windows if the
  destination exists). This module extracts that exact pattern into one
  reusable, dependency-light primitive so every JSON state writer in the
  codebase can share it instead of re-inventing (and sometimes getting
  wrong) its own version.

SCOPE (Phase 0.3a only):
  This module is ONLY the atomic-write primitive plus the read-side
  companion (``read_json_or_none``) needed to survive a torn file left
  behind by an OLD non-atomic write during the migration window. It does
  NOT add position_id threading, a write-ahead journal, or any change to
  the close handler -- those are separate, later phases (0.3b / 0.4).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("bot.core.atomic_state")

PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# Locking
#
# One lock per destination path (not one single global lock) so writers of
# different files don't serialize behind each other, while writers of the
# SAME file (e.g. multiple threads saving position_state.json) always
# serialize -- mirroring health.py's HEARTBEAT_LOCK, generalized to many
# paths. Guarded by a small meta-lock since the lock dict itself is shared
# mutable state.
# ---------------------------------------------------------------------------
_locks_meta_lock = threading.Lock()
_path_locks: Dict[str, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve()) if path.exists() or path.parent.exists() else str(path)
    with _locks_meta_lock:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _path_locks[key] = lock
        return lock


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Core primitive: write ``payload`` to ``path`` atomically.

    Mirrors monitoring/health.py::write_heartbeat_atomic's discipline
    exactly: unique tmp file in the same directory, flush + os.fsync before
    the swap, then a single os.replace() (atomic on POSIX and Windows,
    unlike os.rename which raises on Windows if the destination exists --
    that Windows gap is exactly what the old remove-then-rename code in
    auto_recovery.py was papering over, unsafely).
    """
    directory = path.parent
    lock = _lock_for(path)
    with lock:
        directory.mkdir(parents=True, exist_ok=True)

        # A unique temp file per (pid, thread) writer, in the SAME directory
        # as the target, so os.replace() is guaranteed to be a same-
        # filesystem/same-volume atomic rename rather than a cross-device
        # copy (which is not atomic).
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.{threading.get_ident()}.tmp",
            dir=str(directory),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            # Never leave a half-written temp file lying around after a
            # failed/interrupted write -- and re-raise so the caller knows
            # the write did NOT happen (the original file, if any, is
            # untouched: os.replace() never ran).
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise


def atomic_write_json(path: PathLike, data: Any, *, indent: int = 2) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Guarantees:
      1. Readers never observe a partial/truncated/torn file -- the target
         path either still holds its previous complete contents, or holds
         the complete new contents. There is no intermediate state visible
         from outside this function.
      2. The write is DURABLE before the swap: the temp file's bytes are
         fsync'd to disk (not just buffered) before ``os.replace()`` runs,
         so a crash immediately after this function returns cannot lose the
         write even if the OS page cache hasn't been flushed by the kernel
         yet.
      3. Concurrent writers of the SAME path serialize (see ``_lock_for``)
         so two threads writing the same state file cannot interleave.
      4. The parent directory is created if missing.

    Raises whatever exception occurred (I/O error, non-serializable data,
    etc.) after cleaning up any temp file -- callers that want the old
    "log and swallow" behavior should catch around this call themselves
    (this mirrors the call sites being converted, which already wrap their
    save_* functions in try/except).
    """
    target = Path(path)
    payload = json.dumps(data, indent=indent).encode("utf-8")
    _atomic_write_bytes(target, payload)


def atomic_write_text(path: PathLike, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path``. Same guarantees as
    ``atomic_write_json``, for non-JSON payloads."""
    target = Path(path)
    _atomic_write_bytes(target, text.encode(encoding))


def append_jsonl_line(path: PathLike, obj: Any) -> None:
    """Durably append one JSON-serialized line to an append-only log file
    (Phase 0.3a companion primitive, added Phase 0.4-B for
    core/close_pipeline/close_outbox.py's ``data/close_outbox.jsonl``).

    This is deliberately NOT ``atomic_write_json`` -- an append-only JSONL
    log (close_outbox, position_journal) needs "this one line, once
    appended, is durable on disk" semantics, not "the whole file is
    atomically replaced." Rewriting the entire file on every append would
    be both wasteful and would reintroduce a torn-file window for every
    OTHER line already in the log, which is exactly what atomic replace is
    supposed to prevent.

    Guarantees, mirroring ``_atomic_write_bytes``'s discipline:
      1. Durable: ``flush()`` + ``os.fsync()`` before returning, so a crash
         immediately after this call cannot lose the appended line even if
         the OS page cache hasn't been flushed by the kernel yet.
      2. Concurrent appenders to the SAME path serialize via the same
         per-path lock ``_atomic_write_bytes`` uses, so two threads
         appending to the same log cannot interleave and tear each other's
         lines.
      3. The parent directory is created if missing.

    Does NOT protect against a torn LAST line from a crash mid-write of
    THIS call (a crash between the partial ``f.write`` and the fsync can
    still leave a half-written final line) -- readers of append-only logs
    in this codebase (position_journal.py, close_outbox.py) are required to
    tolerate and skip an unparseable last line rather than crash; see
    ``read_json_or_none`` and each module's own line-reader for that
    contract.
    """
    target = Path(path)
    line = json.dumps(obj, default=str)
    lock = _lock_for(target)
    with lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(line if line.endswith("\n") else line + "\n")
            f.flush()
            os.fsync(f.fileno())


def read_json_or_none(path: PathLike) -> Optional[dict]:
    """Robustly load JSON from ``path``, returning None instead of raising
    on any failure: missing file, empty file, or corrupt/truncated JSON.

    This is the read-side companion needed during migration off the old
    non-atomic writers: a file torn by a PAST crash (before this module
    existed) must be survivable -- callers should treat None as "no usable
    state, fall back to defaults / reconciliation", not crash the boot
    sequence. Every failure is logged as a warning so a torn file is at
    least visible in the logs, never silently invisible.
    """
    target = Path(path)
    try:
        if not target.exists():
            return None
        raw = target.read_text(encoding="utf-8")
        if not raw.strip():
            logger.warning("read_json_or_none: %s exists but is empty", target)
            return None
        return json.loads(raw)
    except (OSError, ValueError) as e:
        logger.warning("read_json_or_none: failed to read/parse %s: %s", target, e)
        return None
