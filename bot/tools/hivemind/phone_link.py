"""Send the owner the current phone link to the WAGMI Terminal whenever the tunnel address changes.

The free Cloudflare tunnel gets a new address on every restart, so a bookmarked link would break. Each
cycle this reads the latest address from logs/tunnel_manager.log and, if it changed, sends
<tunnel>/t?k=<owner token> to the owner's own Telegram chat via the existing bot (TELEGRAM_TOKEN /
TELEGRAM_CHAT_ID in .env). The key is the same secret the local terminal embeds.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
STATE = HM / "phone_link.json"


def _env(name):
    v = os.getenv(name)
    if v:
        return v
    try:
        for line in (BOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].split("#")[0].strip().strip('"')
    except OSError:
        pass
    return None


def current_url():
    try:
        txt = (BOT / "logs" / "tunnel_manager.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", txt)
    return m[-1] if m else None


def main(force=False):
    url = current_url()
    if not url:
        return None
    try:
        last = json.loads(STATE.read_text(encoding="utf-8")).get("url")
    except Exception:
        last = None
    if url == last and not force:
        return None
    token = (HM / "owner_token.txt").read_text(encoding="utf-8").strip()
    link = f"{url}/t?k={token}"
    tg, chat = _env("TELEGRAM_TOKEN"), _env("TELEGRAM_CHAT_ID")
    sent = False
    if tg and chat:
        text = ("📈 WAGMI Terminal: your phone link (it changes when the PC's tunnel restarts; "
                f"I'll send the new one automatically):\n{link}\n\nKeep this private: the key in it lets the page log calls in your name.")
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{tg}/sendMessage", data=data, timeout=20) as r:
                sent = json.loads(r.read()).get("ok", False)
        except Exception:
            sent = False
    STATE.write_text(json.dumps({"url": url, "sent": sent}), encoding="utf-8")
    return {"url": url, "sent": sent}


if __name__ == "__main__":
    import sys
    print(main(force="--force" in sys.argv))
