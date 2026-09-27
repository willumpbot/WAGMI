#!/usr/bin/env python
"""
DEPRECATED - popcat_copilot.py (v1) has been superseded by copilot.py (v2).

v1's swing logic told the owner to TRIM into strength / ADD into weakness as
an "accumulation" technique. A hard backtest showed that's a disguised exit:
it only nets more tokens when the coin FALLS, and on up-legs it surrenders
upside. v2 (tools/copilot/copilot.py) fixes this: ADD on dips, HOLD through
strength, and generalizes to multiple symbols (default POPCAT + SOL).

This shim just forwards to copilot.py's CLI, defaulting --symbol to POPCAT
only (to preserve v1's single-symbol CLI behavior for anyone with an old
invocation saved). Prefer calling copilot.py directly.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import copilot

    if not any(a == "--symbol" or a.startswith("--symbol=") for a in sys.argv[1:]):
        sys.argv.insert(1, "--symbol")
        sys.argv.insert(2, "POPCAT")
    copilot.main()
