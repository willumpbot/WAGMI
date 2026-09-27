#!/usr/bin/env python
"""
WAGMI Co-Pilot ALERTS - copilot_alerts.py
=============================================================================
The PROACTIVE layer on top of tools/copilot/copilot.py. Runs on a schedule
(cron / Task Scheduler), computes the current co-pilot read for each watched
symbol, and pushes a Discord alert ONLY when something ACTIONABLE changes.

OWNER'S #1 REQUIREMENT: NO SPAM. This tool must never re-alert a standing
condition. It alerts on a STATE TRANSITION into something actionable, once,
and then goes quiet until the state changes again (or clears, if opted in).
Read the anti-spam design in _decide() before touching this file.

READ-ONLY / STANDALONE, same constraints as copilot.py:
  - Only imports tools/copilot/copilot.py's public functions/dataclasses and
    tools/discord_notify.py's send_discord(). No llm/execution/core/
    strategies imports. Never touches live/.env/data/replay.
  - Its own persistent state lives at data/copilot/alert_state.json - a new,
    isolated file this tool owns; it never reads/writes any live-bot state.

STATE MODEL (per symbol)
-------------------------
Each run computes a coarse composite state "ACTION|LEVERAGE", e.g.:
    ADD|SAFE            - in the add zone, leverage fine
    HOLD|SAFE           - nothing to do
    WAIT_KNIFE|SAFE     - falling-knife gate is blocking adds
    WAIT_CHOP|SAFE      - dead-flat range, not actionable, informational only
    HOLD|RISKY          - no dip call, but current leverage exceeds safe max
    ADD|SUICIDAL        - dip says add, but leverage would wipe the account

ACTION bucket collapses DipRead.action + WHY it's WAITing (falling knife is
an actionable "don't touch it" warning; a tight-range chop wait is just
"nothing to do", so it's deliberately NOT alert-worthy on its own).
LEVERAGE bucket is LiquidationRead.risk_label (SAFE / RISKY / SUICIDAL)
verbatim - already a clean 3-value classification, no re-bucketing needed.

ANTI-SPAM LOGIC (the whole point of this file - see _decide())
-------------------------
1. last_state (what the symbol read as, every run) is ALWAYS refreshed
   (outside --dry-run) so a later run correctly detects a NEW transition
   even if an earlier transition into/out of an actionable state was never
   alerted (e.g. suppressed by cooldown, or a clear-note that's off by
   default). Standing conditions never look "new" twice.
2. Alert-worthy transitions only:
     - ACTION enters {ADD, WAIT_KNIFE} and wasn't already in it.
     - LEVERAGE enters/escalates into {RISKY, SUICIDAL} (SAFE->RISKY,
       SAFE->SUICIDAL, RISKY->SUICIDAL). De-escalation is never alert-worthy
       here (that's a "clear", see below).
   Anything else (unchanged state, HOLD<->WAIT_CHOP shuffling, tiny
   numeric wiggles that don't cross a bucket boundary) is coarse-grained
   away by construction - format_brief()'s underlying numbers can jiggle
   all they want without flipping the bucket.
3. Optional "cleared back to calm" note (--alert-on-clear, DEFAULT OFF):
   previous state was actionable/dangerous and current is not -> a single
   low-key note, still subject to the same cooldown.
4. COOLDOWN (default 6h) per symbol: even a genuine alert-worthy transition
   is suppressed if the last alert for that symbol fired within the window.
   A suppressed alert is NOT queued/retried - last_state still advances, so
   the owner won't get a delayed burst later; they just won't get this one
   (they already got a fresh alert for this symbol recently). This is the
   deliberate second guard against flapping near a bucket boundary.
5. State/timestamp is only persisted to disk when something actually FIRES
   (alert sent or, in --dry-run, "would fire") - EXCEPT last_state, which
   always advances on real (non-dry) runs regardless of firing, per (1).

CLI:
    python tools/copilot/copilot_alerts.py                    # real run: compute, alert on transitions, persist
    python tools/copilot/copilot_alerts.py --dry-run           # compute + print only; NO Discord push, NO state write
    python tools/copilot/copilot_alerts.py --symbols POPCAT,SOL
    python tools/copilot/copilot_alerts.py --equity 2500 --leverage 3 --side long
    python tools/copilot/copilot_alerts.py --cooldown-hours 6
    python tools/copilot/copilot_alerts.py --alert-on-clear     # opt into the low-key "back to calm" note
    python tools/copilot/copilot_alerts.py --seed               # write current state as baseline WITHOUT alerting
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Import copilot.py's public API only - no reimplementation, no live-bot deps
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    DEFAULT_SYMBOLS,
    DEFAULT_EQUITY_USD,
    DEFAULT_LEVERAGE,
    DEFAULT_SIDE,
    DipRead,
    LiquidationRead,
    _get_hl_client,
    build_dip_read,
    compute_liquidation,
    fetch_hl_max_leverage,
    format_brief,
)

BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
STATE_DIR = os.path.join(BOT_DIR, "data", "copilot")
STATE_PATH = os.path.join(STATE_DIR, "alert_state.json")

DEFAULT_COOLDOWN_HOURS = 6.0

# Action buckets that are worth interrupting the owner for on their own.
ACTIONABLE_ACTIONS = {"ADD", "WAIT_KNIFE"}
# Leverage buckets that are dangerous.
DANGER_LEVELS = {"RISKY", "SUICIDAL"}
LEV_RANK = {"SAFE": 0, "UNKNOWN": 0, "RISKY": 1, "SUICIDAL": 2}


# ---------------------------------------------------------------------------
# Composite state derivation
# ---------------------------------------------------------------------------

def action_bucket(dip: DipRead) -> str:
    """Collapse DipRead.action (+ WHY, for WAIT) into a coarse alert bucket."""
    if not dip.ok:
        return "NODATA"
    if dip.action == "ADD":
        return "ADD"
    if dip.action == "WAIT":
        reason = (dip.action_reason or "").upper()
        if "FALLING KNIFE" in reason:
            return "WAIT_KNIFE"
        return "WAIT_CHOP"  # tight-range wait - informational, not alert-worthy
    return "HOLD"


def lev_bucket(liq: Optional[LiquidationRead]) -> str:
    if liq is None:
        return "UNKNOWN"
    return liq.risk_label


def composite_state(dip: DipRead, liq: Optional[LiquidationRead]) -> str:
    return f"{action_bucket(dip)}|{lev_bucket(liq)}"


def _split(state: str) -> Tuple[str, str]:
    if not state or "|" not in state:
        return "HOLD", "SAFE"
    a, l = state.split("|", 1)
    return a, l


def _is_actionable(state: str) -> bool:
    a, l = _split(state)
    return a in ACTIONABLE_ACTIONS or l in DANGER_LEVELS


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

def load_state() -> Dict[str, dict]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state: Dict[str, dict]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_ts: Optional[str]) -> float:
    if not iso_ts:
        return float("inf")
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# The anti-spam decision - the whole point of this file
# ---------------------------------------------------------------------------

def _decide(
    symbol: str,
    prior: Optional[dict],
    cur_state: str,
    cooldown_hours: float,
    alert_on_clear: bool,
) -> Tuple[str, str]:
    """Returns (verdict, reason).

    verdict in:
      FIRE            - alert-worthy transition, cooldown clear -> send it
      FIRE_CLEAR      - "back to calm" note, cooldown clear -> send it (opt-in)
      SUPPRESS_COOLDOWN - alert-worthy transition, but within cooldown -> skip
      NONE            - no alert-worthy transition (unchanged / non-actionable)
    """
    prev_state = (prior or {}).get("last_state")
    prev_actionable = _is_actionable(prev_state) if prev_state else False
    cur_actionable = _is_actionable(cur_state)
    prev_a, prev_l = _split(prev_state) if prev_state else ("HOLD", "SAFE")
    cur_a, cur_l = _split(cur_state)

    transitioned = prev_state is None or prev_state != cur_state
    if not transitioned:
        return "NONE", f"unchanged ({cur_state}) - no alert"

    entered_actionable_action = cur_a in ACTIONABLE_ACTIONS and cur_a != prev_a
    escalated_leverage = LEV_RANK.get(cur_l, 0) > LEV_RANK.get(prev_l, 0) and cur_l in DANGER_LEVELS
    worth_firing = entered_actionable_action or escalated_leverage

    if worth_firing:
        last_alert_ts = (prior or {}).get("last_alert_ts")
        cooldown_ok = _hours_since(last_alert_ts) >= cooldown_hours
        if cooldown_ok:
            why = []
            if entered_actionable_action:
                why.append(f"action {prev_a}->{cur_a}")
            if escalated_leverage:
                why.append(f"leverage {prev_l}->{cur_l}")
            return "FIRE", "entered actionable state: " + ", ".join(why)
        remaining = cooldown_hours - _hours_since(last_alert_ts)
        return "SUPPRESS_COOLDOWN", (
            f"transitioned to {cur_state} but last alert for {symbol} was "
            f"{_hours_since(last_alert_ts):.1f}h ago (cooldown {cooldown_hours}h, "
            f"{remaining:.1f}h remaining) - suppressed"
        )

    cleared = prev_actionable and not cur_actionable
    if cleared:
        if not alert_on_clear:
            return "NONE", f"cleared {prev_state}->{cur_state} but --alert-on-clear is off"
        last_alert_ts = (prior or {}).get("last_alert_ts")
        cooldown_ok = _hours_since(last_alert_ts) >= cooldown_hours
        if cooldown_ok:
            return "FIRE_CLEAR", f"cleared back to calm: {prev_state}->{cur_state}"
        return "SUPPRESS_COOLDOWN", f"cleared {prev_state}->{cur_state} but within cooldown"

    return "NONE", f"transitioned {prev_state}->{cur_state} but not alert-worthy (coarse bucket unchanged in the ways that matter)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_symbols(raw: str):
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return syms or list(DEFAULT_SYMBOLS)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Co-Pilot proactive alerts - Discord push ONLY on a meaningful state transition (anti-spam by design)."
    )
    ap.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbol list (default: POPCAT,SOL)")
    ap.add_argument("--equity", type=float, default=DEFAULT_EQUITY_USD, help="Account equity in USD")
    ap.add_argument("--leverage", type=float, default=DEFAULT_LEVERAGE, help="Intended leverage")
    ap.add_argument("--side", type=str, default=DEFAULT_SIDE, choices=["long", "short", "LONG", "SHORT"], help="Intended position side")
    ap.add_argument("--cooldown-hours", type=float, default=DEFAULT_COOLDOWN_HOURS, help="Min hours between alerts for the same symbol (default 6)")
    ap.add_argument("--alert-on-clear", action="store_true", help="Also send a low-key note when a symbol clears back to calm (default: off, stays quiet)")
    ap.add_argument("--dry-run", action="store_true", help="Compute + print what WOULD happen; no Discord push, no state file write")
    ap.add_argument("--seed", action="store_true", help="Write current state as the baseline WITHOUT sending any alert (use for first-run setup)")
    args = ap.parse_args()

    symbols = _parse_symbols(args.symbols)
    prior_state = load_state()
    new_state = dict(prior_state)  # mutated copy; only saved outside --dry-run

    client = _get_hl_client()

    print(f"=== WAGMI Co-Pilot Alerts {'[DRY RUN]' if args.dry_run else '[SEED]' if args.seed else ''} - {_now_iso()} ===")
    any_fired = False

    for symbol in symbols:
        dip = build_dip_read(client, symbol)
        hl_max_lev = fetch_hl_max_leverage(client, symbol) if dip.ok else None
        liq = compute_liquidation(dip.price, args.side, args.leverage, dip.vol, hl_max_lev, symbol) if dip.ok else None
        cur_state = composite_state(dip, liq)
        prior = prior_state.get(symbol)
        prior_desc = prior["last_state"] if prior else "(none - first run)"

        print(f"\n--- {symbol} ---")
        print(f"  prior state:   {prior_desc}")
        print(f"  current state: {cur_state}  (action={dip.action if dip.ok else 'NODATA'}, leverage={lev_bucket(liq)})")

        if args.seed:
            new_state[symbol] = {"last_state": cur_state, "last_alert_ts": prior.get("last_alert_ts") if prior else None}
            print(f"  SEEDING baseline to {cur_state} (no alert sent)")
            continue

        if dip.ok is False:
            print(f"  NODATA: {dip.data_note} - skipping alert logic for {symbol}")
            continue

        verdict, reason = _decide(symbol, prior, cur_state, args.cooldown_hours, args.alert_on_clear)
        print(f"  verdict: {verdict} - {reason}")

        if verdict in ("FIRE", "FIRE_CLEAR"):
            any_fired = True
            # source="alert": logs a CALL LEDGER row (data/copilot/call_ledger.jsonl)
            # for forward-evidence testing (see call_logger.py). This module doesn't
            # compute MARKET WEATHER (that's a copilot.py `read`-path-only extra pass
            # over BTC + the longtail universe) so the logged row's weather_regime/
            # breadth20/btc_vs_ema50 come through as null for source="alert" rows -
            # documented in call_logger.py's module docstring, not a bug.
            brief = format_brief(symbol, dip, liq, args.equity, args.leverage, args.side, source="alert")
            title = f"WAGMI Co-Pilot ALERT - {symbol} {cur_state}" if verdict == "FIRE" else f"WAGMI Co-Pilot - {symbol} back to calm"
            if args.dry_run:
                print(f"  [DRY RUN] would push to Discord (title={title!r}):")
                print("  " + brief.replace("\n", "\n  "))
            else:
                # tools/ MUST be on sys.path BEFORE importing discord_notify -
                # the previous order (import first, then path-insert) raised
                # ModuleNotFoundError on every real fire, so the owner silently
                # got NO alerts on genuine transitions (matches whats_moving.py's
                # correct order).
                tools_dir = os.path.dirname(_THIS_DIR)
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from discord_notify import send_discord  # local import: only needed on a real fire
                ok = send_discord(brief, title=title)
                print(f"  Discord push {'sent' if ok else 'FAILED'}")
                new_state[symbol] = {"last_state": cur_state, "last_alert_ts": _now_iso()}
        elif not args.dry_run:
            # No alert fired, but always advance last_state on a real run so a
            # later transition is measured against what actually happened,
            # not against a stale pre-cooldown/pre-opt-out snapshot.
            existing_alert_ts = prior.get("last_alert_ts") if prior else None
            new_state[symbol] = {"last_state": cur_state, "last_alert_ts": existing_alert_ts}

    if args.dry_run:
        print("\n[DRY RUN] no Discord push sent, no state file written.")
    else:
        save_state(new_state)
        print(f"\nState written to {STATE_PATH}")
    if not any_fired and not args.dry_run and not args.seed:
        print("(no alerts fired this run)")


if __name__ == "__main__":
    main()
