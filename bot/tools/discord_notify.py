#!/usr/bin/env python
"""WAGMI Discord notifier — mechanical, LLM-FREE. Owner-provided webhook 2026-07-14.

Sends deterministic messages to the owner's Discord via WAGMI_DISCORD_WEBHOOK (in .env).
No LLM, no secrets in code — the webhook lives in .env only. Used for: market thesis /
digest push, and critical health alerts (bot down / degraded). Import send_discord()
or run as CLI:  python tools/discord_notify.py "message"  [--file path]  [--title X]
"""
import os
import sys
import json
import urllib.request

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webhook():
    # Read from env first, then parse .env directly (bot loads it, but standalone runs may not)
    wh = os.getenv("WAGMI_DISCORD_WEBHOOK", "").strip()
    if wh:
        return wh
    try:
        for line in open(os.path.join(BOT, ".env"), encoding="utf-8"):
            line = line.strip()
            if line.startswith("WAGMI_DISCORD_WEBHOOK="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def send_discord(content, title=None):
    """POST content to the webhook. Returns True on success. Never raises."""
    wh = _webhook()
    if not wh:
        print("[discord] no WAGMI_DISCORD_WEBHOOK set — skipped")
        return False
    body = content
    if title:
        body = f"**{title}**\n{content}"
    # Discord hard-caps content at 2000 chars
    body = body[:1990]
    try:
        req = urllib.request.Request(
            wh,
            data=json.dumps({"content": body}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "WAGMI-bot"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = 200 <= resp.status < 300
            print(f"[discord] sent ({resp.status})" if ok else f"[discord] HTTP {resp.status}")
            return ok
    except Exception as e:
        print(f"[discord] send failed: {e}")
        return False


def main():
    args = sys.argv[1:]
    title = None
    if "--title" in args:
        i = args.index("--title")
        title = args[i + 1]
        del args[i:i + 2]
    if "--file" in args:
        i = args.index("--file")
        path = args[i + 1]
        content = open(path, encoding="utf-8").read()
    elif args:
        content = " ".join(args)
    else:
        content = "WAGMI notifier test."
    send_discord(content, title=title)


if __name__ == "__main__":
    main()
