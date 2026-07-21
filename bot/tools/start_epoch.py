"""Phase 0.5 PR-1 thin CLI wrapper around data.epoch.start_epoch().

data/equity_epoch.json is CODE-OWNED as of this PR — start_epoch() is its
ONLY writer. There is no more hand-editing the epoch marker JSON; use this
CLI (or call data.epoch.start_epoch() directly from other code) instead.

SAFETY GUARD: mirrors tools/purge_pollution.py's refuse_if_live_tree() --
this script hard-refuses to run at all if its own resolved location is not
inside the isolated `...\\WAGMI_measurework\\bot` worktree. start_epoch()
touches P&L windowing (it defines the boundary every reporting/learning
consumer fences against), so accidentally running it against the live
C:\\Users\\vince\\WAGMI bot would silently reset live reporting.

Usage (run from bot/):
    python tools/start_epoch.py --equity 5000 --reason "operator text"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Bootstrap bot/ onto sys.path so `from core import paths` / `from data
# import epoch` resolve when this script is invoked directly (python
# tools/start_epoch.py), mirroring tools/purge_pollution.py's own bootstrap.
_BOT_ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT_FOR_IMPORT))

from core import paths  # noqa: E402

# The live tree this script must NEVER operate against, even by accident.
# Same marker strings as tools/purge_pollution.py, compared case-insensitively
# against BOT_ROOT's resolved path (Windows paths are case-insensitive).
_ISOLATED_WORKTREE_MARKER = "wagmi_measurework"


class LiveTreeGuardError(RuntimeError):
    """Raised when this script's resolved location is not inside the
    isolated measurework worktree it was written for. Refusing to run is
    the only safe behavior here -- see module docstring."""


def refuse_if_live_tree() -> None:
    """Hard guard: refuse to operate unless BOT_ROOT is unambiguously the
    isolated worktree (...\\WAGMI_measurework\\bot), never the live
    ...\\WAGMI\\bot tree."""
    root_str = str(paths.BOT_ROOT.resolve()).lower()
    if _ISOLATED_WORKTREE_MARKER not in root_str:
        raise LiveTreeGuardError(
            f"REFUSING TO RUN: resolved BOT_ROOT={paths.BOT_ROOT} does not "
            f"look like the isolated '{_ISOLATED_WORKTREE_MARKER}' worktree "
            f"this script was written for. This guard exists specifically "
            f"so this script can never stamp a new epoch over the live "
            f"WAGMI bot's data."
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--equity", type=float, required=True,
        help="New epoch's starting equity baseline (e.g. 5000).",
    )
    parser.add_argument(
        "--reason", type=str, required=True,
        help="Free-text operator reason, stored verbatim in the marker.",
    )
    args = parser.parse_args(argv)

    refuse_if_live_tree()

    from data.epoch import start_epoch  # noqa: E402 (deferred: after guard)

    record = start_epoch(args.equity, args.reason)

    print(f"[start_epoch] wrote {paths.equity_epoch_path()}")
    print(json.dumps(record, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
