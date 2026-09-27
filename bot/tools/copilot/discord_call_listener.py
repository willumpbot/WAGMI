#!/usr/bin/env python
"""
WAGMI Co-Pilot - SECURE Discord-inbound CALL listener - discord_call_listener.py
=============================================================================
Lets the OWNER fire the co-pilot `call` command from his phone by posting in
ONE Discord channel, and replies in-channel with the risk brief. That is the
whole job. It is a thin, LOCKED-DOWN bridge between one Discord message and the
already-existing, read-only `call` subcommand (tools/copilot/cli.py call ...).

    call KITTY long reclaimed range low, holders ripping
    call POPCAT long reclaimed 200MA --leverage 3 --equity 5000
    call SOL short lost the range --risk-pct 0.4

SECURITY MODEL (this shells out based on network input - every item is a hard
requirement, not a nicety):
  1. AUTHORIZE BY OWNER USER-ID. Only messages whose author.id ==
     WAGMI_DISCORD_OWNER_ID are ever acted on, and only in the channel
     WAGMI_DISCORD_CALL_CHANNEL_ID. Every other user / channel is ignored
     SILENTLY (no reply, no execution, no log of content).
  2. STRICT WHITELIST PARSE. A message is only executed if it matches EXACTLY
     `call <symbol> <long|short> <reason> [--leverage f] [--equity f]
     [--risk-pct f]`. symbol = ^[A-Za-z0-9]{1,15}$; side in {long,short};
     numeric flags are floats inside sane bounds (leverage 1-50, equity 1-1e7,
     risk-pct 0-0.5); reason is the remaining free text passed as ONE argument.
     Anything else -> a short usage reply, never an execution.
  3. NO SHELL, EVER. Execution is subprocess.run([...ARG LIST...], shell=False,
     timeout=60). User text is NEVER string-formatted into a command, never
     eval'd. The reason is a single argv element, so
     `call KITTY long x"; rm -rf /` just hands the string `x"; rm -rf /` to
     argparse as the reason - there is no shell to interpret it.
  4. FIXED ARGV PREFIX. The command is hard-coded:
     [sys.executable, "tools/copilot/cli.py", "call", symbol, side, reason,
     *flags]. The program name is never derived from the message.
  5. BOUNDED REPLY. The reply is the captured stdout, truncated to Discord's
     2000-char limit, in a ``` code block. On non-zero exit / timeout it is a
     short error line, never a raw traceback.
  6. FAIL-DORMANT ON MISSING CONFIG. If the bot token / owner-id / channel-id
     env vars are absent, it prints a clear message and EXITS 0 - it does NOT
     connect and does NOT crash-loop. The token is never logged.

READ-ONLY / STANDALONE w.r.t. the live bot, same contract as every
tools/copilot/*.py module: it only ever launches `cli.py call` (itself
read-only: logs to owner_call_ledger.jsonl + prints a brief). It never imports
live-bot packages and never touches the running processes.

OFFLINE PROOF: `python tools/copilot/discord_call_listener.py --selftest` runs
the whole parse/authorize/injection battery WITHOUT connecting to Discord and
prints PASS/FAIL per case. `import discord` is deferred into the connect path
so the selftest needs no network and no token.

ENV VARS (owner sets these; names only, never commit values):
    WAGMI_DISCORD_BOT_TOKEN         the bot's token (secret - never logged)
    WAGMI_DISCORD_OWNER_ID          the owner's Discord user id (int)
    WAGMI_DISCORD_CALL_CHANNEL_ID   the one channel to listen in (int)
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys

# --- paths (this file lives at bot/tools/copilot/) ---------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))           # .../bot
CLI_REL = os.path.join("tools", "copilot", "cli.py")           # run from BOT_DIR

# --- env var names (values live only in the environment, never here) ---------
ENV_TOKEN = "WAGMI_DISCORD_BOT_TOKEN"
ENV_OWNER = "WAGMI_DISCORD_OWNER_ID"
ENV_CHANNEL = "WAGMI_DISCORD_CALL_CHANNEL_ID"

# --- strict whitelist grammar ------------------------------------------------
SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,15}$")
SIDES = {"long", "short"}
# ONLY these three flags are recognized. Their bounds are hard. A float outside
# the bound, a non-numeric value, or a non-finite value (inf/nan) is rejected.
FLAG_BOUNDS = {
    "--leverage": (1.0, 50.0),
    "--equity": (1.0, 1e7),
    "--risk-pct": (0.0, 0.5),
}
FLAG_ORDER = ("--leverage", "--equity", "--risk-pct")   # canonical argv order

MAX_MESSAGE_LEN = 1900      # under Discord's 2000; anything longer is rejected
MAX_REASON_LEN = 500        # matches owner_call.MAX_REASON_LEN

DISCORD_MSG_LIMIT = 2000

# parse outcomes
IGNORE = "ignore"   # not a `call` at all -> stay completely silent
USAGE = "usage"     # looked like a call but malformed -> short usage reply
RUN = "run"         # valid -> execute
STATUS = "status"   # bare `status` -> read-only digest, takes NO user input

# The status digest. Fixed path, run with --no-send so the reply appears in
# channel instead of being double-posted through the webhook.
DIGEST_REL = os.path.join("tools", "daily_digest.py")

USAGE_TEXT = (
    "usage: `call <SYMBOL> <long|short> <your reason> "
    "[--leverage 1-50] [--equity 1-1e7] [--risk-pct 0-0.5]`\n"
    "e.g. `call POPCAT long reclaimed 200MA --leverage 3 --equity 5000`\n"
    "(symbol: letters/numbers, <=15 chars; reason is required and free text)"
)


# ---------------------------------------------------------------------------
# STRICT WHITELIST PARSE  (pure - no side effects, never executes anything)
# ---------------------------------------------------------------------------

def _fmt_num(val: float) -> str:
    """Numeric flag value as a clean string for argv (no sci-notation surprises
    for the common integer-ish inputs; float() round-trips it either way)."""
    if val == int(val):
        return str(int(val))
    return repr(val)


def parse_call_command(text: str):
    """Parse a raw Discord message into the argv SUFFIX after `call`.

    Returns a tuple (outcome, payload):
        (IGNORE, None)            -> not a `call` command; caller stays silent
        (USAGE, usage_string)     -> looked like a call but invalid; reply usage
        (RUN, [symbol, side, reason, *flags]) -> validated argv suffix

    WHITESPACE SPLIT ONLY - deliberately NOT shlex/shell: the reason is free
    text (it may contain unbalanced quotes, `;`, `$(...)`, `../`, backticks)
    and we neither interpret nor let those escape the reason field. This
    function has no side effects and NEVER runs a subprocess.
    """
    if not isinstance(text, str):
        return (IGNORE, None)
    raw = text.strip()
    tokens = raw.split()
    # Only messages that begin with the literal command word `call` are ours.
    # Everything else is ignored silently (this is a shared channel; we do not
    # reply to normal chatter).
    # `status` — the one command that carries NO user input at all. It is a bare
    # verb: anything after it makes the message not-a-status, so there is nothing
    # to validate and no way to smuggle an argument into the fixed argv below.
    if len(tokens) == 1 and tokens[0].lower() == "status":
        return (STATUS, None)
    if not tokens or tokens[0].lower() != "call":
        return (IGNORE, None)
    if len(raw) > MAX_MESSAGE_LEN:
        return (USAGE, "message too long - shorten your reason.")

    # Need at minimum: call <symbol> <side> <reason(1+ token)>
    if len(tokens) < 4:
        return (USAGE, USAGE_TEXT)

    symbol = tokens[1]
    side = tokens[2].lower()
    if not SYMBOL_RE.match(symbol):
        return (USAGE, USAGE_TEXT)
    if side not in SIDES:
        return (USAGE, USAGE_TEXT)

    rest = tokens[3:]

    # Split reason | flags at the FIRST recognized flag token. Any `--foo` that
    # is NOT one of the three recognized flags is treated as ordinary reason
    # text (it stays confined to the single reason arg, never a shell/flag).
    flag_start = None
    for i, tok in enumerate(rest):
        if tok in FLAG_BOUNDS:
            flag_start = i
            break
    if flag_start is None:
        reason_tokens, flag_tokens = rest, []
    else:
        reason_tokens, flag_tokens = rest[:flag_start], rest[flag_start:]

    # reason is REQUIRED by the grammar
    if not reason_tokens:
        return (USAGE, USAGE_TEXT)
    reason = " ".join(reason_tokens)
    # A reason that starts with '-' would be misread as a flag by cli.py's
    # loose call re-parser; reject it so the single reason arg is unambiguous.
    if reason.startswith("-"):
        return (USAGE, USAGE_TEXT)
    if len(reason) > MAX_REASON_LEN:
        reason = reason[:MAX_REASON_LEN]

    # Parse the flags section as strict (flag, value) pairs: recognized flag,
    # finite float in-bounds, no repeats, no dangling flag, no stray tokens.
    parsed_flags: dict[str, float] = {}
    j = 0
    while j < len(flag_tokens):
        flag = flag_tokens[j]
        if flag not in FLAG_BOUNDS:
            return (USAGE, USAGE_TEXT)
        if flag in parsed_flags:
            return (USAGE, USAGE_TEXT)
        if j + 1 >= len(flag_tokens):
            return (USAGE, USAGE_TEXT)           # flag with no value
        try:
            val = float(flag_tokens[j + 1])
        except (TypeError, ValueError):
            return (USAGE, USAGE_TEXT)
        if not math.isfinite(val):               # reject inf / nan explicitly
            return (USAGE, USAGE_TEXT)
        lo, hi = FLAG_BOUNDS[flag]
        if not (lo <= val <= hi):
            return (USAGE, USAGE_TEXT)
        parsed_flags[flag] = val
        j += 2

    argv_suffix = [symbol, side, reason]
    for flag in FLAG_ORDER:
        if flag in parsed_flags:
            argv_suffix.append(flag)
            argv_suffix.append(_fmt_num(parsed_flags[flag]))
    return (RUN, argv_suffix)


# ---------------------------------------------------------------------------
# AUTHORIZATION  (pure)
# ---------------------------------------------------------------------------

def authorize(author_id, channel_id_of_msg, owner_id: int, channel_id: int) -> bool:
    """True IFF the message is from the owner AND in the one allowed channel.
    Both must match; anything else is unauthorized (caller stays silent)."""
    return author_id == owner_id and channel_id_of_msg == channel_id


# ---------------------------------------------------------------------------
# EXECUTION  (fixed argv, shell=False, bounded output)
# ---------------------------------------------------------------------------

def build_argv(argv_suffix: list) -> list:
    """The FIXED, hard-coded command. Program name never comes from the message.
    Reason + flags are individual list elements - never a formatted string."""
    return [sys.executable, CLI_REL, "call", *argv_suffix]


def _codeblock(s: str) -> str:
    """Wrap output in a ``` block, guaranteeing the whole reply <= 2000 chars."""
    fence = "```"
    budget = DISCORD_MSG_LIMIT - (len(fence) * 2) - 2          # two newlines
    body = s if s else "(no output)"
    if len(body) > budget:
        body = body[: budget - 16].rstrip() + "\n...[truncated]"
    return f"{fence}\n{body}\n{fence}"


def execute_call(argv_suffix: list) -> str:
    """Run the fixed `cli.py call ...` argv with NO shell and a hard timeout;
    return a Discord-ready reply. Never raises."""
    argv = build_argv(argv_suffix)
    try:
        proc = subprocess.run(
            argv,
            shell=False,                # MANDATORY: no shell interpretation
            cwd=BOT_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "call timed out after 60s - try again."
    except Exception as e:  # noqa: BLE001 - launch failure must not crash the listener
        return f"call could not be launched ({type(e).__name__})."

    if proc.returncode != 0:
        # short error, NOT a raw traceback
        tail = ""
        if proc.stderr:
            last = [ln for ln in proc.stderr.splitlines() if ln.strip()]
            if last:
                tail = " - " + last[-1][:200]
        return f"call failed (exit {proc.returncode}){tail}"
    return _codeblock(proc.stdout.strip())


def execute_status() -> str:
    """Run the read-only digest. The argv is a CONSTANT — no element of it comes
    from the message — so this adds no injection surface at all. Never raises."""
    argv = [sys.executable, DIGEST_REL, "--no-send"]
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            cwd=BOT_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "status timed out after 60s - the bot may be wedged."
    except Exception as e:  # noqa: BLE001
        return f"status could not be launched ({type(e).__name__})."
    if proc.returncode != 0:
        return f"status failed (exit {proc.returncode})."
    return _codeblock(proc.stdout.strip())


# ---------------------------------------------------------------------------
# CONFIG  (fail-dormant if anything is missing/invalid)
# ---------------------------------------------------------------------------

def load_config():
    """Read + validate the three env vars. Returns (token, owner_id, channel_id)
    on success, or None (after printing a clear, token-free message) if anything
    is missing or malformed - the caller then EXITS 0 (dormant, no crash-loop)."""
    token = os.environ.get(ENV_TOKEN, "").strip()
    owner_raw = os.environ.get(ENV_OWNER, "").strip()
    channel_raw = os.environ.get(ENV_CHANNEL, "").strip()

    missing = [name for name, val in
               ((ENV_TOKEN, token), (ENV_OWNER, owner_raw), (ENV_CHANNEL, channel_raw))
               if not val]
    if missing:
        print(f"[discord_call_listener] {', '.join(missing)} not set - staying dormant "
              f"(not connecting). Set the env vars to enable. Exiting cleanly.")
        return None

    try:
        owner_id = int(owner_raw)
        channel_id = int(channel_raw)
    except ValueError:
        print(f"[discord_call_listener] {ENV_OWNER}/{ENV_CHANNEL} must be integer Discord IDs "
              f"- got non-integer values. Staying dormant. Exiting cleanly.")
        return None

    return token, owner_id, channel_id


# ---------------------------------------------------------------------------
# LISTENER  (discord import DEFERRED here so --selftest needs no dependency)
# ---------------------------------------------------------------------------

def run_listener(token: str, owner_id: int, channel_id: int) -> None:
    try:
        import discord  # deferred: selftest and config-checks never need it
    except ImportError:
        print("[discord_call_listener] discord.py not installed "
              "(`python -m pip install discord.py`). Cannot connect. Exiting cleanly.")
        return

    intents = discord.Intents.default()
    intents.message_content = True           # required to read message text
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        who = getattr(client.user, "id", "?")
        print(f"[discord_call_listener] connected (bot id={who}); listening ONLY to owner "
              f"{owner_id} in channel {channel_id}.")

    @client.event
    async def on_message(message):
        # --- SECURITY GATE 1: owner-only + single-channel, else silent -------
        # Ignore our own messages, and never act on anyone but the owner.
        if client.user is not None and message.author.id == client.user.id:
            return
        if not authorize(message.author.id, message.channel.id, owner_id, channel_id):
            return
        # --- SECURITY GATE 2: strict whitelist parse -------------------------
        outcome, payload = parse_call_command(message.content or "")
        if outcome == IGNORE:
            return
        if outcome == STATUS:
            try:
                await message.channel.send(execute_status())
            except Exception as e:  # noqa: BLE001
                print(f"[discord_call_listener] reply failed: {type(e).__name__}")
            return
        if outcome == USAGE:
            try:
                await message.channel.send(payload if payload else USAGE_TEXT)
            except Exception as e:  # noqa: BLE001
                print(f"[discord_call_listener] reply failed: {type(e).__name__}")
            return
        # --- outcome == RUN: fixed-argv, no-shell execution ------------------
        reply = execute_call(payload)
        try:
            await message.channel.send(reply)
        except Exception as e:  # noqa: BLE001
            print(f"[discord_call_listener] reply failed: {type(e).__name__}")

    # client.run blocks; discord.py handles its own reconnect/backoff.
    client.run(token)


# ---------------------------------------------------------------------------
# SELFTEST  (fully offline - no Discord, no token, no subprocess needed)
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    """Battery over parse + authorize + injection safety. Prints PASS/FAIL per
    case and returns 0 iff every case passed. Connects to NOTHING."""
    passed = 0
    failed = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        tag = "PASS" if cond else "FAIL"
        if cond:
            passed += 1
        else:
            failed += 1
        print(f"  [{tag}] {name}" + (f"  -- {detail}" if detail and not cond else ""))

    print("== PARSE: valid messages ==")

    o, p = parse_call_command("call KITTY long reclaimed range low, holders ripping")
    check("valid spot call parses to expected argv",
          o == RUN and p == ["KITTY", "long", "reclaimed range low, holders ripping"],
          f"got {o} {p}")

    o, p = parse_call_command("call POPCAT long reclaimed 200MA --leverage 3 --equity 5000")
    check("valid HL call with flags parses to expected argv",
          o == RUN and p == ["POPCAT", "long", "reclaimed 200MA", "--leverage", "3", "--equity", "5000"],
          f"got {o} {p}")

    o, p = parse_call_command("call SOL short lost the range --risk-pct 0.4")
    check("valid call with --risk-pct parses",
          o == RUN and p == ["SOL", "short", "lost the range", "--risk-pct", "0.4"],
          f"got {o} {p}")

    o, p = parse_call_command("CALL sol LONG uppercase keyword and side")
    check("keyword/side case-insensitive; symbol preserved",
          o == RUN and p == ["sol", "long", "uppercase keyword and side"],
          f"got {o} {p}")

    print("== INJECTION: must be rejected OR confined to the reason arg ==")

    o, p = parse_call_command('call KITTY long x"; rm -rf /')
    confined = (o == RUN and p[0] == "KITTY" and p[1] == "long"
                and p[2] == 'x"; rm -rf /' and len(p) == 3)
    check("shell-injection payload confined to single reason arg (no shell)",
          confined, f"got {o} {p}")
    if o == RUN:
        argv = build_argv(p)
        # the entire payload is ONE argv element, and there is no shell
        check("injected string is exactly one argv element (argv[5])",
              argv[5] == 'x"; rm -rf /' and len(argv) == 6, f"argv={argv}")

    o, p = parse_call_command("call ../../etc long attempted path symbol")
    check("path-traversal symbol REJECTED (fails ^[A-Za-z0-9]{1,15}$)",
          o == USAGE, f"got {o} {p}")

    o, p = parse_call_command("call KITTY long $(whoami)")
    check("command-substitution payload confined to reason arg (no shell)",
          o == RUN and p == ["KITTY", "long", "$(whoami)"], f"got {o} {p}")

    o, p = parse_call_command("call KITTY long `id` and backticks")
    check("backtick payload confined to reason arg",
          o == RUN and p[2] == "`id` and backticks", f"got {o} {p}")

    print("== PARSE: malformed -> USAGE (never executes) ==")

    for msg, why in [
        ("call KITTY sideways some reason", "bad side"),
        ("call TOOLONGSYMBOL123 long reason", "symbol > 15 chars"),
        ("call KIT$Y long reason", "symbol has non-alnum"),
        ("call KITTY long", "reason missing"),
        ("call KITTY long --leverage 3", "reason missing (only flags)"),
        ("call KITTY long trade --leverage 999", "leverage above bound"),
        ("call KITTY long trade --leverage 0.5", "leverage below bound"),
        ("call KITTY long trade --leverage abc", "leverage non-numeric"),
        ("call KITTY long trade --leverage nan", "leverage nan"),
        ("call KITTY long trade --leverage inf", "leverage inf"),
        ("call KITTY long trade --equity 1e9", "equity above bound"),
        ("call KITTY long trade --risk-pct 0.9", "risk-pct above bound"),
        ("call KITTY long trade --equity", "flag with no value"),
        ("call KITTY long trade --leverage 3 --leverage 4", "duplicate flag"),
    ]:
        o, _p = parse_call_command(msg)
        check(f"USAGE: {why}", o == USAGE, f"got {o} for {msg!r}")

    print("== PARSE: non-call chatter -> IGNORE (silent) ==")
    for msg in ["hello team", "gm", "", "   ", "recall the plan", "calling it a day"]:
        o, _p = parse_call_command(msg)
        check(f"IGNORE: {msg!r}", o == IGNORE, f"got {o}")

    print("== AUTHORIZATION: owner-id + channel-id gate ==")
    OWNER, CHAN, OTHER_USER, OTHER_CHAN = 111, 222, 999, 888
    check("owner in allowed channel -> authorized",
          authorize(OWNER, CHAN, OWNER, CHAN) is True)
    check("NON-OWNER in allowed channel -> rejected",
          authorize(OTHER_USER, CHAN, OWNER, CHAN) is False)
    check("owner in WRONG channel -> rejected",
          authorize(OWNER, OTHER_CHAN, OWNER, CHAN) is False)
    check("non-owner in wrong channel -> rejected",
          authorize(OTHER_USER, OTHER_CHAN, OWNER, CHAN) is False)

    print("== REPLY: code block never exceeds Discord's 2000-char limit ==")
    big = _codeblock("A" * 5000)
    check("oversized output truncated <= 2000", len(big) <= DISCORD_MSG_LIMIT, f"len={len(big)}")

    print(f"\n== SELFTEST: {passed} passed, {failed} failed ==")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if "--selftest" in sys.argv[1:]:
        sys.exit(run_selftest())
    cfg = load_config()
    if cfg is None:
        # fail-dormant: clean exit 0, no connection, no crash-loop
        sys.exit(0)
    token, owner_id, channel_id = cfg
    run_listener(token, owner_id, channel_id)


if __name__ == "__main__":
    main()
