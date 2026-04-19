"""Discord webhook tests — stub urllib so we don't hit the network."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from memegine import discord_webhook


def test_from_env_empty(monkeypatch):
    monkeypatch.delenv("MEMEGINE_DISCORD_WEBHOOK_URL", raising=False)
    cfg = discord_webhook.DiscordConfig.from_env()
    assert cfg.webhook_url == ""
    assert cfg.username == "memegine"


def test_from_env_reads_url(monkeypatch):
    monkeypatch.setenv("MEMEGINE_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/xxx")
    monkeypatch.setenv("MEMEGINE_DISCORD_USERNAME", "custom")
    cfg = discord_webhook.DiscordConfig.from_env()
    assert cfg.webhook_url == "https://discord.com/api/webhooks/xxx"
    assert cfg.username == "custom"


def test_is_configured():
    assert discord_webhook.is_configured(discord_webhook.DiscordConfig(webhook_url="url"))
    assert not discord_webhook.is_configured(discord_webhook.DiscordConfig(webhook_url=""))


def test_send_noop_when_unconfigured():
    cfg = discord_webhook.DiscordConfig(webhook_url="")
    assert discord_webhook.send("hello", cfg=cfg) == 0


def test_send_posts_to_webhook():
    cfg = discord_webhook.DiscordConfig(webhook_url="https://discord.com/api/webhooks/fake")
    with patch.object(discord_webhook, "_post_one", return_value=204) as mock:
        status = discord_webhook.send("hello", cfg=cfg)
    assert status == 204
    mock.assert_called_once()
    # Verify payload shape.
    call_args = mock.call_args
    url, payload = call_args[0][0], call_args[0][1]
    assert url == cfg.webhook_url
    assert payload["content"] == "hello"
    assert payload["username"] == "memegine"


def test_send_chunks_long_messages():
    cfg = discord_webhook.DiscordConfig(webhook_url="https://discord.com/api/webhooks/fake")
    long_text = "\n".join(["line"] * 500)
    with patch.object(discord_webhook, "_post_one", return_value=204) as mock:
        discord_webhook.send(long_text, cfg=cfg)
    # Should have been called multiple times (chunked).
    assert mock.call_count >= 2


def test_send_stops_on_server_error():
    cfg = discord_webhook.DiscordConfig(webhook_url="https://discord.com/api/webhooks/fake")
    long_text = "\n".join(["line"] * 500)
    with patch.object(discord_webhook, "_post_one", return_value=500) as mock:
        status = discord_webhook.send(long_text, cfg=cfg)
    assert status == 500
    # Stopped after the first 5xx.
    assert mock.call_count == 1


def test_send_scheduler_result():
    @dataclass
    class FakeResult:
        fired_at: str = "2026-04-18T10:00:00Z"
        action: str = "daily_batch"
        bundles: list = None
        topics_used: list = None
        note: str = ""

    result = FakeResult(bundles=["b1"], topics_used=["t1"])
    cfg = discord_webhook.DiscordConfig(webhook_url="https://discord.com/api/webhooks/fake")
    with patch.object(discord_webhook, "_post_one", return_value=204) as mock:
        status = discord_webhook.send_scheduler_result(cfg, {"name": "morning"}, result)
    assert status == 204
    payload = mock.call_args[0][1]
    assert "morning" in payload["content"]
    assert "b1" in payload["content"]
