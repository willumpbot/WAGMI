"""Discord webhook — fire-and-forget delivery to a Discord channel.

No persistent bot, no intents, no OAuth. The operator creates a webhook
URL in a Discord channel (Channel Settings → Integrations → Webhooks →
New Webhook → Copy URL) and sets MEMEGINE_DISCORD_WEBHOOK_URL.

Usage: scheduler can push results here the same way it pushes to Telegram.
Bot-less delivery. Free. Requires only urllib (stdlib).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class DiscordConfig:
    webhook_url: str = ""
    username: str = "memegine"

    @classmethod
    def from_env(cls) -> "DiscordConfig":
        return cls(
            webhook_url=os.environ.get("MEMEGINE_DISCORD_WEBHOOK_URL", "").strip(),
            username=os.environ.get("MEMEGINE_DISCORD_USERNAME", "memegine").strip() or "memegine",
        )


def is_configured(cfg: DiscordConfig | None = None) -> bool:
    cfg = cfg or DiscordConfig.from_env()
    return bool(cfg.webhook_url)


def _chunks(text: str, size: int = 1900) -> list[str]:
    """Discord limit is 2000 chars per message; leave headroom."""
    if len(text) <= size:
        return [text]
    out: list[str] = []
    remaining = text
    while len(remaining) > size:
        cut = remaining.rfind("\n", 0, size)
        if cut == -1:
            cut = size
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        out.append(remaining)
    return out


def _post_one(url: str, payload: dict, timeout: float = 8.0) -> int:
    """POST a JSON payload to the webhook, return HTTP status.

    Uses urllib (stdlib) so there's no `requests` dep.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def send(text: str, *, cfg: DiscordConfig | None = None) -> int:
    """Send a plain-text message. Returns HTTP status of the last chunk.

    Safe to call when webhook isn't configured — returns 0 as a no-op.
    """
    cfg = cfg or DiscordConfig.from_env()
    if not cfg.webhook_url:
        return 0
    last_status = 204
    for chunk in _chunks(text):
        payload = {"content": chunk, "username": cfg.username}
        last_status = _post_one(cfg.webhook_url, payload)
        if 500 <= last_status < 600:
            break
    return last_status


def send_scheduler_result(cfg: DiscordConfig, job: dict, result) -> int:
    msg = (
        f"**[scheduler] {job.get('name')}** fired at {result.fired_at}\n"
        f"action: `{result.action}`\n"
        f"bundles: `{result.bundles}`\n"
        f"topics_used: `{result.topics_used}`\n"
        f"note: {result.note}"
    )
    return send(msg, cfg=cfg)
