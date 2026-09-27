#!/usr/bin/env python
"""
WAGMI Co-Pilot - unified CLI - cli.py
=============================================================================
ONE command for the whole co-pilot. This is a THIN DISPATCHER only - all real
logic stays in copilot.py / pretrade.py / whats_moving.py / copilot_alerts.py;
this file just routes argv to the right module's own main(), in-process (no
subprocess). Each module keeps its own directly-runnable CLI unchanged - this
is pure back-compat: run_alerts.ps1 / Task Scheduler "WAGMI-Copilot-Alerts"
calls copilot_alerts.py directly and is untouched by this file's existence.

READ-ONLY / STANDALONE w.r.t. the live bot, same constraints as every module
it wraps: never imports live-bot packages (llm/, execution/, core/,
strategies/), never touches live/.env/data/replay.

SUBCOMMANDS
    read    [copilot.py flags]          Per-coin ADD/HOLD/WAIT + liquidation guardrail briefs
    trade   "SYMBOL SIDE LEVx MARGIN"   Pre-trade fee/funding/liquidation card
    call    SYMBOL SIDE "reason"        OWNER CALL - log YOUR OWN discretionary entry + get a
                                         risk-amplifier brief (HL: leverage/liq/size; DEX-spot:
                                         size + organic/liquidity caveats). Logs forward-evidence
                                         of HIS edge. `call resolve` stamps 1d/7d/30d outcomes.
    eye     [SYMBOL] [--deep]           PRE-DECISION analyst brief (counterpart to `call`) - the
                                         full honest picture on a coin you're EYEING so you form
                                         your thesis faster without getting fooled. MEASURED
                                         CONTEXT, never a prediction: it NEVER says which way it
                                         goes. --deep adds a STRUCTURAL MAP (multi-TF trend, swing
                                         S/R with touch counts, liq magnets, funding/OI for HL;
                                         recent-window levels + mint-keyed accumulation for memes).
                                         Writes NOTHING (pre-decision). No SYMBOL = SCAN mode.
    book    "SYM SIDE LEVx MARGIN; ..."  Portfolio risk view - correlated exposure +
                                         BTC-shock scenario table across ALL held positions
    movers  [whats_moving.py flags]     What's-moving scanner across the HL universe (stdout)
    alerts  [copilot_alerts.py flags]   Proactive Discord alerter - DEFAULT --dry-run
                                         (no push, no state write); pass --send for a
                                         REAL Discord push. This default exists so
                                         running `cli.py alerts` out of curiosity can
                                         never accidentally ping Discord.
    brief   [briefing.py flags]         Composed MORNING BRIEFING - one scannable digest
    briefing                            over weather/watchlist/book/radar/liquidations
                                         (alias of `brief`). DEFAULT --dry-run (print
                                         only, no push); pass --send for a REAL push.

EXAMPLES
    python tools/copilot/cli.py read
    python tools/copilot/cli.py read --symbol SOL --equity 5000 --lev-range 3-15
    python tools/copilot/cli.py trade "SOL long 10x 1500"
    python tools/copilot/cli.py trade "POPCAT long 3x 800" --discord
    python tools/copilot/cli.py book "SOL long 5x 1200; POPCAT long 3x 400; BTC long 10x 2000"
    python tools/copilot/cli.py book "SOL long 5x 1200" --equity 8000
    python tools/copilot/cli.py movers
    python tools/copilot/cli.py movers --top 15
    python tools/copilot/cli.py alerts                    # dry-run preview only, no push
    python tools/copilot/cli.py alerts --equity 5000 --leverage 3 --send   # real push
    python tools/copilot/cli.py brief --equity 5000                        # dry-run digest
    python tools/copilot/cli.py brief --book "SOL long 5x 1200; POPCAT long 3x 400"
    python tools/copilot/cli.py brief --send                               # real Discord push

Every module's own flags are supported and simply forwarded (this dispatcher
does not re-declare or duplicate them) - run e.g.
`python tools/copilot/copilot.py --help` for the full flag list of the module
behind a given subcommand.
"""
from __future__ import annotations

import importlib
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

USAGE = """WAGMI Co-Pilot - unified CLI

Usage:
  python tools/copilot/cli.py read   [copilot.py flags]         Per-coin ADD/HOLD/WAIT + liquidation briefs
  python tools/copilot/cli.py trade  "SYMBOL SIDE LEVx MARGIN"  Pre-trade fee/funding/liquidation card
  python tools/copilot/cli.py call   SYMBOL SIDE "reason"        OWNER CALL - log your entry + risk-amplifier brief
                                                                 (HL: leverage/liq/size; DEX-spot: size + health)
  python tools/copilot/cli.py eye    [SYMBOL]                    PRE-DECISION analyst brief (before you pick a side) -
                                                                 measured context, never a prediction; no SYMBOL = scan
  python tools/copilot/cli.py book   "SYM SIDE LEVx MARGIN; ..." Portfolio risk view - correlated exposure
                                                                 + BTC-shock scenario table (all held positions)
  python tools/copilot/cli.py movers [whats_moving.py flags]    What's-moving scanner (stdout)
  python tools/copilot/cli.py alerts [copilot_alerts.py flags]  Proactive Discord alerter
                                                                 (default --dry-run; add --send for a real push)
  python tools/copilot/cli.py brief  [briefing.py flags]        Composed MORNING BRIEFING digest
                                                                 (default --dry-run; add --send for a real push)

Examples:
  python tools/copilot/cli.py read --symbol SOL --equity 5000 --lev-range 3-15
  python tools/copilot/cli.py eye SOL
  python tools/copilot/cli.py eye KITTY
  python tools/copilot/cli.py eye                       # scan mode (attention list)
  python tools/copilot/cli.py trade "SOL long 10x 1500"
  python tools/copilot/cli.py book "SOL long 5x 1200; POPCAT long 3x 400; BTC long 10x 2000"
  python tools/copilot/cli.py movers --top 15
  python tools/copilot/cli.py alerts --send
  python tools/copilot/cli.py brief --equity 5000
  python tools/copilot/cli.py brief --book "SOL long 5x 1200; POPCAT long 3x 400" --send

Run `python tools/copilot/<module>.py --help` for a subcommand's full flag list
(copilot.py, pretrade.py, book.py, whats_moving.py, copilot_alerts.py,
briefing.py) - this dispatcher forwards flags through unchanged; it does not
re-declare them.

See tools/copilot/README.md for a full walkthrough of what each command does
and what the output means.
"""


def _run(module_name: str, argv: list) -> None:
    """Import `module_name` and call its main() with sys.argv set to
    [module_name] + argv, then restore sys.argv. In-process call (no
    subprocess) so exceptions/exit codes propagate normally."""
    mod = importlib.import_module(module_name)
    old_argv = sys.argv
    sys.argv = [f"{module_name}.py"] + list(argv)
    try:
        mod.main()
    finally:
        sys.argv = old_argv


def cmd_read(argv: list) -> None:
    """Straight pass-through to copilot.py's own CLI (--symbol, --equity,
    --leverage, --lev-range, --side, --discord, ...)."""
    _run("copilot", argv)


def cmd_trade(argv: list) -> None:
    """Wraps copilot.py --trade. Accepts the spec either quoted as one
    argument ("SOL long 10x 1500") or as separate words (SOL long 10x 1500)
    - leading non-flag tokens are joined into the spec string; anything from
    the first "-"-prefixed token onward (e.g. --discord) is forwarded as-is."""
    if not argv:
        print('usage: cli.py trade "SYMBOL SIDE LEVERAGEx MARGIN_USD" [--discord]', file=sys.stderr)
        sys.exit(2)
    spec_tokens, i = [], 0
    while i < len(argv) and not argv[i].startswith("-"):
        spec_tokens.append(argv[i])
        i += 1
    spec = " ".join(spec_tokens)
    extra = argv[i:]
    _run("copilot", ["--trade", spec] + extra)


def cmd_book(argv: list) -> None:
    """Wraps book.py (portfolio risk view). Accepts the semicolon-separated
    position spec either quoted as one argument ("SOL long 5x 1200; POPCAT
    long 3x 400") or as separate words - leading non-flag tokens are joined
    into the spec string (same convention as cmd_trade above); anything from
    the first "-"-prefixed token onward (e.g. --equity 8000) is forwarded
    as-is. Read-only, no Discord push (book.py has no --discord path)."""
    if not argv:
        print('usage: cli.py book "SYM SIDE LEVx MARGIN; SYM SIDE LEVx MARGIN; ..." [--equity N]', file=sys.stderr)
        sys.exit(2)
    spec_tokens, i = [], 0
    while i < len(argv) and not argv[i].startswith("-"):
        spec_tokens.append(argv[i])
        i += 1
    spec = " ".join(spec_tokens)
    extra = argv[i:]
    _run("book", [spec] + extra)


def cmd_call(argv: list) -> None:
    """OWNER CALL: log YOUR OWN discretionary entry + get a risk-amplifier
    brief. `call SYMBOL SIDE "your reason" [--leverage N] [--equity N]
    [--risk-pct N] [--dry-run]`. HL-listed coins get leverage/liquidation/size;
    DEX-spot memes ($KITTY etc.) get size + organic/liquidity caveats (no
    leverage). Reason may be quoted or given as loose words - leading non-flag
    tokens after SYMBOL/SIDE are joined into the reason. Logs to
    owner_call_ledger.jsonl for forward-evidence resolution of HIS edge.
    `call resolve` stamps forward 1d/7d/30d outcomes onto mature rows."""
    if not argv:
        print('usage: cli.py call SYMBOL SIDE "your reason" [--leverage N] [--equity N] [--risk-pct N] [--dry-run]\n'
              '       cli.py call resolve', file=sys.stderr)
        sys.exit(2)
    if argv[0] == "resolve":
        _run("owner_call", argv)
        return
    # SYMBOL SIDE then loose reason words up to the first flag, then flags
    if len(argv) < 2:
        print('usage: cli.py call SYMBOL SIDE "your reason" [flags]', file=sys.stderr)
        sys.exit(2)
    symbol, side = argv[0], argv[1]
    rest = argv[2:]
    reason_tokens, i = [], 0
    while i < len(rest) and not rest[i].startswith("-"):
        reason_tokens.append(rest[i])
        i += 1
    reason = " ".join(reason_tokens)
    flags = rest[i:]
    _run("owner_call", [symbol, side, reason] + flags)


def cmd_eye(argv: list) -> None:
    """PRE-DECISION analyst brief - `eye [SYMBOL] [--equity N] [--top N]`.
    Straight pass-through to eye.py's own CLI (its arg parser handles the
    optional SYMBOL positional and the no-symbol SCAN mode). READ-ONLY and
    writes NOTHING - unlike `call`, this is pre-decision and logs no ledger."""
    _run("eye", argv)


def cmd_movers(argv: list) -> None:
    """Straight pass-through to whats_moving.py's own CLI."""
    _run("whats_moving", argv)


def cmd_alerts(argv: list) -> None:
    """Wraps copilot_alerts.py. SAFETY DEFAULT: never pushes a real Discord
    alert unless the owner explicitly passes --send. Without --send,
    --dry-run is injected (compute + print only, no push, no state write) -
    running `cli.py alerts` with zero args is always safe to try."""
    argv = list(argv)
    send = "--send" in argv
    if send:
        argv = [a for a in argv if a != "--send"]
    if not send and "--dry-run" not in argv:
        argv = ["--dry-run"] + argv
    _run("copilot_alerts", argv)


def cmd_brief(argv: list) -> None:
    """Wraps briefing.py (the composed MORNING BRIEFING digest). SAFETY:
    briefing.py's own default is already never-push-without---send (unlike
    copilot_alerts.py, it understands --send natively), but this mirrors
    cmd_alerts' belt-and-braces convention anyway - if the owner didn't pass
    --send, --dry-run is injected so running `cli.py brief` out of curiosity
    can never accidentally ping Discord."""
    argv = list(argv)
    if "--send" not in argv and "--dry-run" not in argv:
        argv = ["--dry-run"] + argv
    _run("briefing", argv)


DISPATCH = {
    "read": cmd_read,
    "trade": cmd_trade,
    "call": cmd_call,
    "eye": cmd_eye,
    "book": cmd_book,
    "movers": cmd_movers,
    "alerts": cmd_alerts,
    "brief": cmd_brief,
    "briefing": cmd_brief,
}


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0 if argv else 1)
    command, rest = argv[0], argv[1:]
    handler = DISPATCH.get(command)
    if handler is None:
        print(f"Unknown command: {command!r}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    handler(rest)


if __name__ == "__main__":
    main()
