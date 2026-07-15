#!/usr/bin/env python
"""WAGMI hands-off health alerter — mechanical, LLM-FREE. Owner QoL: no babysitting.

Checks the bot's health from heartbeat.json + newest log and pushes a Discord alert
ONLY when something is actually wrong (bot down / heartbeat stale / degraded / real
errors / rate-limit / auth). Deduplicates so it doesn't spam — alerts on state CHANGE
(healthy->bad) and sends one "recovered" note when it clears. Run on a schedule
(e.g. every 15 min via Task Scheduler). Nothing here trades.

Usage: python bot/tools/health_alert.py            (alert only on problems / recovery)
       python bot/tools/health_alert.py --heartbeat (always send a status line)
"""
import os
import re
import sys
import json
import time
import glob

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BOT, "data", "health_alert_state.json")
HB = os.path.join(BOT, "data", "heartbeat.json")

# Tight patterns only — '429'/'oauth' loose-match timestamps.
_ERR_PATTERNS = re.compile(r"Too Many Requests|429 Client Error|invalid_api_key|authentication_error|Traceback")


def _hb():
    try:
        d = json.load(open(HB))
        if d.get("equity") is None:  # mid-write; re-read once
            time.sleep(1)
            d = json.load(open(HB))
        return d, time.time() - os.path.getmtime(HB)
    except Exception:
        return None, 1e9


def _recent_errors():
    try:
        f = sorted(glob.glob(os.path.join(BOT, "logs", "bot_2026*.log")))[-1]
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 200_000))
            tail = fh.read().decode("utf-8", "ignore")
        return len(_ERR_PATTERNS.findall(tail))
    except Exception:
        return 0


def _assess():
    d, age = _hb()
    problems = []
    if d is None:
        problems.append("heartbeat unreadable")
    else:
        if age > 420:  # >7 min stale (startup can take ~5)
            problems.append(f"heartbeat stale {age/60:.0f}m")
        if d.get("llm_first_degraded"):
            problems.append("LLM degraded")
        if (d.get("errors") or 0) > 0:
            problems.append(f"{d['errors']} errors")
    ne = _recent_errors()
    if ne > 0:
        problems.append(f"{ne} tight error-lines in log")
    eq = (d or {}).get("equity")
    return problems, eq, age


def main():
    always = "--heartbeat" in sys.argv
    problems, eq, age = _assess()
    try:
        prev = json.load(open(STATE)).get("bad", False)
    except Exception:
        prev = False
    bad = bool(problems)

    try:
        sys.path.insert(0, os.path.join(BOT, "tools"))
        from discord_notify import send_discord
    except Exception:
        def send_discord(*a, **k):
            print("[health_alert] discord unavailable")
            return False

    if bad and not prev:
        send_discord(f"⚠️ WAGMI health: {'; '.join(problems)} | eq=${eq} | hb {age:.0f}s", title="WAGMI ALERT")
    elif prev and not bad:
        send_discord(f"✅ WAGMI recovered — healthy again | eq=${eq}", title="WAGMI recovered")
    elif always:
        send_discord(f"WAGMI {'⚠️ '+'; '.join(problems) if bad else '✅ healthy'} | eq=${eq} | hb {age:.0f}s")
    print(f"[health_alert] bad={bad} problems={problems} eq={eq}")

    try:
        json.dump({"bad": bad, "ts": time.time()}, open(STATE, "w"))
    except Exception:
        pass


if __name__ == "__main__":
    main()
