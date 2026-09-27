#!/usr/bin/env python
"""
DEPRECATED - copilot_read.py (v1) has been superseded by copilot.py (v2) and
the unified `tools/copilot/cli.py read` entry point.

v1 covered a broader watchlist (BTC, FARTCOIN, PENGU, kPEPE, kBONK, kSHIB,
WLD, PUMP) framed around pullback/breakout "actionable setups" for a
trend-continuation meme trader. v2 (tools/copilot/copilot.py) is the actively
maintained engine and a strict superset of v1's regime/momentum/S-R math: it
adds the liquidation/leverage guardrails (the #1 job), range-aware leverage,
a funding-as-carry line, real per-asset HL maintenance margin, and the
ADD/HOLD/WAIT accumulation call (backtest-corrected from v1's now-refuted
swing-trim logic - see copilot.py's module docstring, "WHY v2 EXISTS").
Verified 2026-07-31: nothing else in this repo imports copilot_read.py.

This shim just forwards to copilot.py's CLI so any saved old invocation
keeps working - `--symbols` maps to copilot.py's `--symbol` (defaulting to
v1's original 8-symbol watchlist if you don't pass one), `--discord` passes
through unchanged. Prefer calling `cli.py read` or `copilot.py` directly for
anything new.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# v1's original default watchlist - preserved here only so an old saved
# invocation with no --symbols still scans the same coins it always did.
_V1_DEFAULT_SYMBOLS = "BTC,FARTCOIN,PENGU,kPEPE,kBONK,kSHIB,WLD,PUMP"


def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--discord", action="store_true")
    ap.add_argument("--symbols", type=str, default=None)
    args, _unknown = ap.parse_known_args()

    import copilot  # local import: deprecated shim, keep import cost off the v2 hot path

    forwarded = ["--symbol", args.symbols or _V1_DEFAULT_SYMBOLS]
    if args.discord:
        forwarded.append("--discord")
    sys.argv = ["copilot.py"] + forwarded
    copilot.main()


if __name__ == "__main__":
    main()
