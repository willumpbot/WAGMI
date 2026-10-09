"""Hard guard: a pytest process may NEVER write into a live bot/data or bot/logs.

WHY (2026-10-09): the suite is routinely run from the LIVE checkout
(C:\\Users\\vince\\WAGMI\\bot) while the bot runs from the same directory.
Dozens of modules resolve their state/ledger paths as cwd-relative
``"data/..."`` literals or ``Path(__file__).parent/"data"`` anchors, so every
test that exercised a writer without remembering to redirect it appended
fixture rows to the live brain (~7% of a live jsonl), rewrote tracked data
files, and ``multi_strategy_main``'s import-time ``setup_logging(log_dir=
"logs")`` attached a RotatingFileHandler to the live ``logs/bot_YYYYMMDD.log``
(mock "API down" tracebacks from bot.backtest.llm showed up in it).

HOW: ``install()`` is called from tests/conftest.py at import time -- before
any test module (and therefore any bot module) is imported -- and:

1. Creates a per-session sandbox dir and points ``WAGMI_LOG_DIR`` at it
   (core/structured_logging.setup_logging honours it; unset at runtime, so
   the live bot is byte-identical).
2. Registers a ``sys.addaudithook`` that raises ``LiveWriteBlocked`` (OSError) for any
   write-ish operation (open for write/append/create, os.open with write
   flags, rename/replace, remove/unlink, mkdir of a NEW dir, rmdir, truncate,
   shutil copy/move/rmtree, sqlite3.connect) whose target is under a
   protected root. Audit hooks cannot be removed, so nothing a test or a
   bot module does later (monkeypatching open, chdir, reloading modules)
   can bypass it within this process.

Protected roots = ``<this checkout>/bot/{data,logs,bot}`` plus, when running
from a git worktree, the MAIN checkout's same three dirs (the live bot).
``__pycache__`` is exempt (bot/data is also a Python package). Reads are
never blocked -- tests may read fixtures/caches from data/.

A test that genuinely needs to exercise persistence must point the writer
at ``tmp_path`` (monkeypatch the module path constant / pass a path arg).
If it doesn't, it now fails loudly with "LIVE-WRITE BLOCKED" instead of
silently polluting live state.

Out of scope (cannot be enforced in-process): child processes spawned by a
test (they inherit WAGMI_LOG_DIR / WAGMI_SOURCE=test but not the hook).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

BOT_ROOT = Path(__file__).resolve().parent.parent

# data/ + logs/: the live brain and logs. bot/bot/: holds the generated
# trading_config_swarm_overrides.py the live bot imports; feedback/
# swarm_feedback_loop.py rewrites it via a cwd-relative path during tests.
_PROTECTED_SUBDIRS = ("data", "logs", "bot")

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

_state = {
    "installed": False,
    "roots": [],          # normcased absolute str paths
    "sandbox": None,      # Path
    "blocked": [],        # list of (event, path) actually blocked
}


def _main_checkout_bot_root(bot_root: Path) -> Optional[Path]:
    """If ``bot_root`` lives in a git worktree, return the main checkout's
    bot/ dir (where the live bot runs). Pure file reads, no subprocess."""
    dot_git = bot_root.parent / ".git"
    try:
        if not dot_git.is_file():
            return None
        line = dot_git.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            return None
        gitdir = Path(line.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (bot_root.parent / gitdir)
        common = gitdir
        commondir_file = gitdir / "commondir"
        if commondir_file.is_file():
            rel = commondir_file.read_text(encoding="utf-8").strip()
            common = Path(rel) if Path(rel).is_absolute() else gitdir / rel
        main_bot = common.resolve().parent / "bot"
        return main_bot if main_bot.is_dir() else None
    except OSError:
        return None


def protected_roots(bot_root: Path = BOT_ROOT) -> List[Path]:
    roots = [bot_root / d for d in _PROTECTED_SUBDIRS]
    main_bot = _main_checkout_bot_root(bot_root)
    if main_bot is not None and main_bot.resolve() != bot_root.resolve():
        roots += [main_bot / d for d in _PROTECTED_SUBDIRS]
    extra = os.environ.get("WAGMI_TEST_PROTECTED_DIRS", "")
    roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return roots


def _norm(p) -> Optional[str]:
    if p is None or isinstance(p, int):
        return None
    try:
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        return os.path.normcase(os.path.abspath(os.fspath(p)))
    except Exception:
        return None


def is_protected(path) -> bool:
    n = _norm(path)
    if not n:
        return False
    parts = n.split(os.sep)
    if "__pycache__" in parts:
        return False
    for r in _state["roots"]:
        if n == r or n.startswith(r + os.sep):
            return True
    return False


class LiveWriteBlocked(OSError):
    """Raised by the audit hook. Deliberately NOT a PermissionError: on
    Windows tempfile.mkstemp treats PermissionError as "name collision" and
    retries 10,000 times, which turns a blocked atomic write into a hang."""


def _deny(event: str, path) -> None:
    _state["blocked"].append((event, str(path)))
    raise LiveWriteBlocked(
        f"LIVE-WRITE BLOCKED by tests/live_write_guard.py: {event} -> {path}. "
        f"pytest may not write into a live bot data/ or logs/ dir; redirect "
        f"this writer to tmp_path in the test."
    )


def _hook(event: str, args) -> None:  # noqa: C901 - flat dispatch
    if event == "open":
        path, mode, flags = args
        if isinstance(mode, str):
            writing = any(c in mode for c in "wax+")
        else:
            writing = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        if writing and is_protected(path):
            _deny(event, path)
    elif event in ("os.rename", "shutil.copyfile", "shutil.copymode",
                   "shutil.copystat", "shutil.move", "os.link", "os.symlink"):
        for p in args[:2]:
            if is_protected(p):
                _deny(event, p)
    elif event == "os.mkdir":
        p = args[0]
        # mkdir of an EXISTING dir is a no-op (os.makedirs(exist_ok=True)
        # always attempts the leaf); only block creating something new.
        if is_protected(p) and not os.path.isdir(os.fspath(p) if not isinstance(p, bytes) else os.fsdecode(p)):
            _deny(event, p)
    elif event in ("os.remove", "os.rmdir", "os.truncate", "shutil.rmtree",
                   "os.chmod", "os.utime"):
        if is_protected(args[0]):
            _deny(event, args[0])
    elif event == "sqlite3.connect":
        db = args[0]
        if isinstance(db, (str, bytes, os.PathLike)) and str(db) != ":memory:" and is_protected(db):
            _deny(event, db)


def install() -> Path:
    """Idempotently install the guard. Returns the session sandbox dir."""
    if _state["installed"]:
        return _state["sandbox"]
    sandbox = Path(tempfile.mkdtemp(prefix="wagmi_pytest_sandbox_"))
    (sandbox / "logs").mkdir()
    os.environ["WAGMI_LOG_DIR"] = str(sandbox / "logs")
    _state["roots"] = [_norm(r) for r in protected_roots()]
    _state["sandbox"] = sandbox
    sys.addaudithook(_hook)
    _state["installed"] = True
    return sandbox


def state() -> dict:
    return _state
