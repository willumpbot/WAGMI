"""Guard: no Python SOURCE file under bot/ may match a .gitignore pattern.

Why this exists
---------------
The repo's ``.gitignore`` has a broad ``data/`` rule that (before the fix in the
same commit as this test) silently matched ``bot/data/*.py`` SOURCE modules, not
just runtime data. The consequence was insidious: ``git add bot/data/epoch.py``
did nothing and did NOT error, so a commit whose message claimed to add
``epoch.py`` / ``trade_source.py`` (the canonical get_run_stats "one true number")
never actually tracked them — they lived only on disk, invisible to git and one
``git clean`` away from deletion.

This test turns that silent footgun into a loud, permanent failure: if any
``*.py`` under ``bot/`` would be ignored by a gitignore pattern, the build fails
and names the file. It uses ``git check-ignore --no-index`` so it evaluates the
IGNORE PATTERN regardless of whether the file happens to be tracked already
(a tracked-but-would-be-ignored file is still fragile — re-add it once and it
vanishes).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(out.stdout.strip())


def _iter_source_py(bot_dir: Path):
    for p in bot_dir.rglob("*.py"):
        parts = set(p.parts)
        if "__pycache__" in parts:
            continue
        yield p


def test_no_source_py_under_bot_is_gitignored():
    """Every *.py source file under bot/ must be trackable (not ignore-matched)."""
    root = _repo_root()
    bot_dir = root / "bot"
    assert bot_dir.is_dir(), f"expected bot/ under repo root {root}"

    paths = [str(p.relative_to(root).as_posix()) for p in _iter_source_py(bot_dir)]
    assert paths, "found no .py under bot/ — test wiring is wrong"

    # `--no-index` => evaluate the ignore PATTERN, not the tracked/untracked status.
    # Pass paths as ARGS (not --stdin): text-mode stdin on Windows appends \r to each
    # line, so "foo.py\r" no longer matches the *.py re-include and falsely reports
    # ignored. Chunk to stay under the OS command-line length limit. Matched (ignored)
    # paths are echoed to stdout; a clean result echoes nothing.
    ignored: list[str] = []
    for i in range(0, len(paths), 400):
        chunk = paths[i:i + 400]
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", *chunk],
            capture_output=True, text=True, cwd=str(root),
        )
        ignored.extend(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())
    assert not ignored, (
        "These Python SOURCE files under bot/ match a .gitignore pattern and would "
        "be silently dropped by `git add` (see .gitignore data/ rule + the "
        "bot/data/**/*.py re-include):\n  " + "\n  ".join(sorted(ignored))
    )


def test_canonical_number_modules_are_tracked():
    """The one-true-number modules must be actually tracked in git (not just on disk)."""
    root = _repo_root()
    for rel in ("bot/data/trade_source.py", "bot/data/epoch.py"):
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            capture_output=True, text=True, cwd=str(root),
        )
        assert r.returncode == 0, (
            f"{rel} is NOT tracked by git despite being a canonical source module "
            f"(the exact failure this guard exists to prevent)."
        )
