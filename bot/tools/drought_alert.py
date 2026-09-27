#!/usr/bin/env python
"""WAGMI drought alerter — catches "healthy but silent". Mechanical, LLM-FREE.

THE FAILURE THIS EXISTS FOR (2026-07-29 -> 2026-09-12)
  The bot ran perfectly for 45 days and took ZERO trades. Heartbeat green,
  collectors green, 18 scheduled tasks green, dashboard updating, site
  publishing hourly — and a hardcoded 0.60 confidence floor in risk_gating.py
  silently rejecting every single decision against a scale that had dropped to
  0.23-0.62. health_alert.py never fired because nothing was "wrong": a bot
  that does nothing looks exactly like a bot that finds nothing.

  Nobody noticed for six weeks. That is the hole this closes.

WHAT IT DOES
  Alerts to Discord when the bot has gone quiet for too long, and — crucially —
  says WHY, by tallying the gate's own rejection reasons over the window. A
  drought caused by "the market gave us nothing" and a drought caused by "a
  constant is strangling every decision" look identical from outside; the top
  rejection reason tells them apart in one line.

  Also flags the deeper break: alive, but producing no DECISIONS at all.

CADENCE
  Designed for an absent owner. First alert at DROUGHT_DAYS, then at most one
  every REPEAT_DAYS, so a month of silence produces ~10 messages, not 30.
  Sends one "broke the drought" note when a trade finally lands.

Usage: python bot/tools/drought_alert.py           (alert only when warranted)
       python bot/tools/drought_alert.py --force   (always send, for testing)
       python bot/tools/drought_alert.py --dry-run (print, send nothing)
"""
import os
import re
import sys
import csv
import json
import glob
import time
import argparse
from collections import Counter

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BOT, "tools"))

STATE = os.path.join(BOT, "data", "drought_alert_state.json")
LEDGER = os.path.join(BOT, "data", "trade_ledger.csv")
HB = os.path.join(BOT, "data", "heartbeat.json")
POS = os.path.join(BOT, "data", "position_state.json")

DROUGHT_DAYS = float(os.getenv("DROUGHT_ALERT_DAYS", "3"))
REPEAT_DAYS = float(os.getenv("DROUGHT_REPEAT_DAYS", "3"))
WINDOW_DAYS = 7          # how far back to tally gate reasons
DAY = 86400.0

_GATE_RE = re.compile(r"\[LLM-GATE\] REJECTED: \w+ conf=[0-9.]+ regime=\w+ reason=([^\"]+)")
_ALLOW_RE = re.compile(r"\[LLM-GATE\] ALLOWED")
_DEC_RE = re.compile(r"\[LLM-GATE\] (?:REJECTED|ALLOWED)")


def _load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2)
    os.replace(tmp, STATE)


def _last_trade_ts():
    """Timestamp of the newest closed trade, or None if the ledger is empty."""
    try:
        with open(LEDGER) as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return None
        return max(float(r["timestamp"]) for r in rows if r.get("timestamp"))
    except (OSError, ValueError, KeyError):
        return None


def _open_positions():
    try:
        with open(POS) as fh:
            return int(json.load(fh).get("position_count", 0))
    except (OSError, ValueError, TypeError):
        return 0


def _heartbeat():
    try:
        with open(HB) as fh:
            d = json.load(fh)
        return d, time.time() - os.path.getmtime(HB)
    except (OSError, ValueError):
        return None, 1e9


def _gate_tally(window_s):
    """(decisions, admits, Counter(reason)) over the recent logs."""
    cutoff = time.time() - window_s
    reasons = Counter()
    decisions = admits = 0
    logs = sorted(glob.glob(os.path.join(BOT, "logs", "bot_2026*.log")))[-10:]
    for path in logs:
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 40_000_000))   # tail only; logs get huge
                text = fh.read().decode("utf-8", "ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if "[LLM-GATE]" not in line:
                continue
            if not _DEC_RE.search(line):
                continue
            decisions += 1
            if _ALLOW_RE.search(line):
                admits += 1
                continue
            m = _GATE_RE.search(line)
            if m:
                # collapse "confidence_too_low (0.31 < 0.41)" -> "confidence_too_low"
                reasons[m.group(1).split(" (")[0].strip()] += 1
    return decisions, admits, reasons


def _floor_note():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BOT, ".env"))
        sys.path.insert(0, BOT)
        from llm import living_conf_floor as lcf
        s = lcf.stats()
        if not s["enabled"]:
            return "confidence floor: legacy hardcoded 0.60 (LIVING_CONF_FLOOR off)"
        return (f"confidence floor: {s['floor']:.2f} living "
                f"(P{s['pctl']:.0f} of n={s['n']}, live range {s['min']:.2f}-{s['max']:.2f})")
    except Exception:
        return ""


def build_report():
    now = time.time()
    last = _last_trade_ts()
    quiet_days = (now - last) / DAY if last else None
    hb, hb_age = _heartbeat()
    decisions, admits, reasons = _gate_tally(WINDOW_DAYS * DAY)
    open_pos = _open_positions()

    lines = []
    if last:
        lines.append(f"No closed trade for **{quiet_days:.1f} days** "
                     f"(last: {time.strftime('%Y-%m-%d %H:%M', time.localtime(last))})")
    else:
        lines.append("No closed trade on record at all.")

    alive = hb_age < 600
    lines.append(f"Bot: {'alive' if alive else 'NOT ALIVE'} "
                 f"(heartbeat {hb_age/60:.0f} min old)"
                 + (f", equity ${hb.get('equity', 0):,.2f}" if hb and hb.get("equity") else ""))
    lines.append(f"Open positions: {open_pos}")
    lines.append(f"Last {WINDOW_DAYS}d: {decisions} gate decisions, {admits} admitted")

    if decisions == 0 and alive:
        lines.append("")
        lines.append("**The bot is making no decisions at all** — that is deeper than "
                     "selectivity. Check the signal path, not the gate.")
    elif reasons:
        lines.append("")
        lines.append("Why it is not trading (top gate rejections):")
        for reason, n in reasons.most_common(4):
            pct = 100.0 * n / max(decisions, 1)
            lines.append(f"  - {reason}: {n} ({pct:.0f}%)")
        top, topn = reasons.most_common(1)[0]
        if topn / max(decisions, 1) > 0.8:
            lines.append("")
            lines.append(f"**{top} alone accounts for {100.0*topn/decisions:.0f}% of rejections.** "
                         "A single rule swallowing nearly everything is the signature of the "
                         "2026-07-29 drought - check that its threshold still matches the scale "
                         "it is measuring.")

    note = _floor_note()
    if note:
        lines.append("")
        lines.append(note)

    return "\n".join(lines), quiet_days, bool(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="send regardless of thresholds")
    ap.add_argument("--dry-run", action="store_true", help="print, send nothing")
    args = ap.parse_args()

    now = time.time()
    st = _load_state()
    body, quiet_days, has_trades = build_report()

    last_alert = float(st.get("last_alert_ts") or 0)
    was_drought = bool(st.get("in_drought"))
    in_drought = has_trades and quiet_days is not None and quiet_days >= DROUGHT_DAYS

    title = None
    if args.force:
        title = "WAGMI drought check (manual)"
    elif in_drought and (now - last_alert) >= REPEAT_DAYS * DAY:
        title = f"WAGMI quiet for {quiet_days:.0f} days"
    elif was_drought and not in_drought:
        title = "WAGMI broke the drought"
        body = "A trade closed — the bot is transacting again.\n\n" + body

    st["in_drought"] = in_drought
    st["checked_at"] = now
    st["quiet_days"] = quiet_days

    if not title:
        if not args.dry_run:
            _save_state(st)
        print(f"[drought] no alert (quiet {quiet_days:.1f}d, threshold {DROUGHT_DAYS}d, "
              f"last alert {(now-last_alert)/DAY:.1f}d ago)" if quiet_days is not None
              else "[drought] no alert (no ledger)")
        return 0

    print(f"=== {title} ===\n{body}")
    if args.dry_run:
        return 0

    try:
        from discord_notify import send_discord
        ok = send_discord(body, title=title)
    except Exception as exc:                      # never let alerting crash the box
        print(f"[drought] send failed: {exc}")
        ok = False
    if ok:
        st["last_alert_ts"] = now
    _save_state(st)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
