"""Guard: a pytest process must not be able to write into live bot/data or bot/logs.

Design note -- why this does NOT diff mtimes of the live dirs:
the live bot runs concurrently from C:\\Users\\vince\\WAGMI\\bot and rewrites
dozens of files under data/ and logs/ every minute, so "nothing under the
live dirs changed during the run" is unassertable without flaky allowlists.
Instead we assert the MECHANISM (tests/live_write_guard.py) is in force:
  * the protected roots resolve to the same bot/data + bot/logs the runtime
    uses (core.paths.DATA_DIR, cwd-relative "data"/"logs" from bot/), and
    include the main checkout when running from a worktree;
  * every write primitive against a protected path is refused and leaves
    no file behind (open w/a/x, os.open, Path.write_text, os.replace,
    os.makedirs of a new dir, tempfile.mkstemp, sqlite3, RotatingFileHandler);
  * import-time setup_logging() lands in the sandbox, and no logging
    FileHandler anywhere in the process points into a protected root;
  * reads are still allowed.
Plus one narrow end-to-end check in a SUBPROCESS: a writer that historically
leaked (execution.adaptive_risk's cwd-relative adaptive_sizer_state.json)
cannot create a sentinel-named file in data/.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import live_write_guard as g

BOT = Path(__file__).resolve().parent.parent


def _probe(root: Path) -> Path:
    return root / f"__pytest_guard_probe_{uuid.uuid4().hex}"


def test_guard_installed_and_roots_match_runtime_paths():
    from core import paths

    st = g.state()
    assert st["installed"]
    roots = set(st["roots"])
    norm = lambda p: os.path.normcase(os.path.abspath(str(p)))  # noqa: E731
    # Anchored (core.paths) and cwd-relative ("data/..." from bot/) resolution
    # both land on a protected root.
    assert norm(paths.DATA_DIR) in roots
    assert norm(BOT / "data") in roots and norm(BOT / "logs") in roots
    main_bot = g._main_checkout_bot_root(BOT)
    if main_bot is not None:  # running from a worktree -> live checkout protected too
        assert norm(main_bot / "data") in roots and norm(main_bot / "logs") in roots


@pytest.mark.parametrize("sub", ["data", "logs", "bot"])
def test_write_primitives_are_refused(sub, tmp_path):
    root = BOT / sub
    p = _probe(root)
    attempts = [
        lambda: open(p, "w").close(),
        lambda: open(p, "a").close(),
        lambda: open(p, "xb").close(),
        lambda: os.close(os.open(str(p), os.O_WRONLY | os.O_CREAT)),
        lambda: p.write_text("x"),
        lambda: os.makedirs(p / "nested", exist_ok=True),
        lambda: tempfile.mkstemp(dir=str(root)),
        lambda: sqlite3.connect(str(p)),
        lambda: RotatingFileHandler(str(p)),
    ]
    src = tmp_path / "src.txt"
    src.write_text("x")
    attempts.append(lambda: os.replace(str(src), str(p)))
    for fn in attempts:
        with pytest.raises(g.LiveWriteBlocked):
            fn()
    assert not p.exists()
    assert src.exists()  # replace was refused, source untouched


def test_reads_and_pycache_still_allowed(tmp_path):
    # Reading a protected file is fine.
    any_file = next((f for f in (BOT / "data").rglob("*.py")), None)
    if any_file is not None:
        with open(any_file, "rb") as fh:
            fh.read(1)
    assert not g.is_protected(BOT / "data" / "__pycache__" / "x.pyc")
    assert not g.is_protected(tmp_path / "data" / "x.json")


def test_setup_logging_goes_to_sandbox_and_no_live_file_handlers():
    from core.structured_logging import setup_logging

    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        setup_logging(log_dir="logs")  # the exact multi_strategy_main call shape
        fhs = [h for h in root.handlers if getattr(h, "baseFilename", None)]
        assert fhs, "expected a file handler"
        sandbox_logs = os.path.normcase(os.environ["WAGMI_LOG_DIR"])
        for h in fhs:
            assert os.path.normcase(h.baseFilename).startswith(sandbox_logs)
    finally:
        for h in list(root.handlers):
            if h not in saved[0]:
                root.removeHandler(h)
                h.close()
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])

    for lg in [logging.getLogger()] + [
        l for l in logging.Logger.manager.loggerDict.values() if isinstance(l, logging.Logger)
    ]:
        for h in lg.handlers:
            fn = getattr(h, "baseFilename", None)
            assert not (fn and g.is_protected(fn)), f"{lg.name} logs into live dir: {fn}"


def test_historic_leaker_cannot_write_in_subprocess():
    """End-to-end: import the guard the same way conftest does, then drive a
    writer that used to leak into data/feedback/ with a cwd-relative path."""
    sentinel = f"__guard_e2e_{uuid.uuid4().hex}.json"
    code = (
        "import sys, os; sys.path.insert(0, 'tests');"
        "import live_write_guard as g; g.install();"
        "import execution.adaptive_risk as ar;"
        f"ar._ADAPTIVE_SIZER_STATE_PATH = os.path.join('data', 'feedback', {sentinel!r});"
        "s = ar.AdaptiveSizer();"
        "[s.record_outcome('BTC', won=True) for _ in range(3)];"
        "print('BLOCKED', len(g.state()['blocked']))"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(BOT),
                       capture_output=True, text=True, timeout=120)
    assert not (BOT / "data" / "feedback" / sentinel).exists()
    assert "BLOCKED" in r.stdout, r.stdout + r.stderr
    assert int(r.stdout.split("BLOCKED")[1].split()[0]) >= 1, r.stdout + r.stderr
