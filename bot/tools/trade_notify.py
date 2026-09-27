#!/usr/bin/env python
"""WAGMI trade notifier — pushes every open and close to Discord. LLM-FREE.

WHY THIS EXISTS
  The bot has never told anyone when it trades. Nothing in the trading path
  touches Discord: the only pushes are health (15m), co-pilot alerts (2h),
  briefing (4h) and the daily digest. So a fill that happens while the owner is
  at work is invisible until the next digest — and for 45 days there were no
  fills at all and no message said so.

DESIGN: OUT-OF-PROCESS, BY DESIGN
  This reads state files and pushes; it is NOT wired into the entry/exit code.
  A notifier that can throw inside the trading path is a notifier that can cost
  money. Run it on a schedule (WAGMI-TradeNotify, every 5 min). Worst case it
  is late; it can never break a trade.

WHAT IT SAYS
  OPEN  -> side, symbol, entry, size, SL/TP, leverage, and whether this was a
           conviction entry or a tiny PROBE of a gate-blocked class.
  CLOSE -> exit reason, net PnL, running equity.
  Dedupes on a state file, so a missed run catches up and a repeat run is silent.

Usage: python bot/tools/trade_notify.py            (push new events)
       python bot/tools/trade_notify.py --dry-run  (print, send nothing)
       python bot/tools/trade_notify.py --seed     (adopt current state silently)
"""
import os
import re
import sys
import csv
import json
import time
import argparse

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BOT, "tools"))

STATE = os.path.join(BOT, "data", "trade_notify_state.json")
POS = os.path.join(BOT, "data", "position_state.json")
TRADES = os.path.join(BOT, "data", "trades.csv")
HB = os.path.join(BOT, "data", "heartbeat.json")

MAX_EVENTS_PER_RUN = 8       # a burst cannot turn into a Discord flood


def _load_state():
    try:
        with open(STATE) as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    st.setdefault("open_keys", [])
    st.setdefault("last_close_ts", 0.0)
    return st


def _save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2)
    os.replace(tmp, STATE)


def _positions():
    try:
        with open(POS) as fh:
            return (json.load(fh).get("positions") or {})
    except (OSError, ValueError, TypeError):
        return {}


def _equity():
    try:
        with open(HB) as fh:
            return float(json.load(fh).get("equity") or 0.0)
    except (OSError, ValueError, TypeError):
        return 0.0


def _row_ts(raw):
    """trades.csv stores ISO-8601 ('2026-07-29T22:13:30.721138+00:00'), while
    trade_ledger.csv stores epoch floats. Accept both, return epoch seconds."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        import datetime
        return datetime.datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _closed_since(ts):
    """Closed trades newer than ts, oldest first."""
    out = []
    try:
        with open(TRADES) as fh:
            for r in csv.DictReader(fh):
                t = _row_ts(r.get("timestamp"))
                if t is not None and t > ts:
                    out.append((t, r))
    except (OSError, ValueError):
        return []
    out.sort(key=lambda x: x[0])
    return out


def _pos_key(sym, p):
    """Identity of an open position: symbol + side + open_time."""
    return f"{sym}|{p.get('side', '')}|{p.get('open_time', '')}"


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_probe(p):
    notes = str(p.get("notes") or "")
    return notes.startswith("PROBE (") or "blocked class" in notes


def _fmt_open(sym, p):
    entry = _f(p.get("entry"))
    qty = _f(p.get("qty"))
    lev = _f(p.get("leverage"), 1.0)
    notional = entry * qty * (lev or 1.0)
    kind = "PROBE (tiny, gate-blocked class)" if _is_probe(p) else (
        "EXPLORATION" if "EXPLORATION" in str(p.get("notes") or "") else "conviction entry")
    lines = [
        f"**OPENED {p.get('side', '?')} {sym}** @ {entry:g}",
        f"Kind: {kind}",
        f"Size: {qty:g} (~${notional:,.0f} notional, {lev:g}x)",
        f"SL {_f(p.get('sl')):g}  /  TP1 {_f(p.get('tp1')):g}  /  TP2 {_f(p.get('tp2')):g}",
    ]
    thesis = re.sub(r"\s+", " ", str(p.get("notes") or "")).strip()
    if thesis:
        lines.append(f"Why: {thesis[:300]}")
    return "\n".join(lines)


def _fmt_close(r, equity):
    pnl = _f(r.get("pnl"))
    sign = "+" if pnl >= 0 else ""
    lines = [
        f"**CLOSED {r.get('side', '?')} {r.get('symbol', '?')}** "
        f"{_f(r.get('entry')):g} -> {_f(r.get('exit')):g}",
        f"Net: {sign}${pnl:,.2f}   (fees ${_f(r.get('fees')):,.2f})",
        f"Exit: {r.get('exit_type') or r.get('outcome') or 'unknown'}",
    ]
    if str(r.get("entry_type") or "").upper() == "EXPLORATION":
        lines.append("This was a tiny probe, not a conviction trade.")
    if equity:
        lines.append(f"Equity now: ${equity:,.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true",
                    help="adopt current state without sending (first-run setup)")
    args = ap.parse_args()

    st = _load_state()
    positions = _positions()
    now_keys = [_pos_key(s, p) for s, p in positions.items()]
    equity = _equity()

    if args.seed:
        st["open_keys"] = now_keys
        rows = _closed_since(0)
        st["last_close_ts"] = rows[-1][0] if rows else 0.0
        _save_state(st)
        print(f"[trade_notify] seeded: {len(now_keys)} open, "
              f"last_close_ts={st['last_close_ts']}")
        return 0

    events = []
    known = set(st["open_keys"])
    for sym, p in positions.items():
        k = _pos_key(sym, p)
        if k not in known:
            events.append(("OPEN", _fmt_open(sym, p)))

    for t, r in _closed_since(_f(st["last_close_ts"])):
        events.append(("CLOSE", _fmt_close(r, equity)))
        st["last_close_ts"] = max(_f(st["last_close_ts"]), t)

    st["open_keys"] = now_keys
    st["checked_at"] = time.time()

    if not events:
        if not args.dry_run:
            _save_state(st)
        print("[trade_notify] nothing new")
        return 0

    dropped = 0
    if len(events) > MAX_EVENTS_PER_RUN:
        dropped = len(events) - MAX_EVENTS_PER_RUN
        events = events[:MAX_EVENTS_PER_RUN]

    ok_all = True
    for idx, (kind, body) in enumerate(events):
        if dropped and idx == len(events) - 1:
            body += f"\n\n(+{dropped} more events this run, see the dashboard)"
        print(f"=== {kind} ===\n{body}\n")
        if args.dry_run:
            continue
        try:
            from discord_notify import send_discord
            ok_all = send_discord(body, title=f"WAGMI {kind}") and ok_all
        except Exception as exc:
            print(f"[trade_notify] send failed: {exc}")
            ok_all = False

    if not args.dry_run and ok_all:
        _save_state(st)      # only advance state on a delivered message
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
