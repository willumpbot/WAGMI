from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from memegine import morning_briefer


def test_error_when_no_api_key(monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    result = morning_briefer.generate()
    assert result.error


def test_generates_with_mocked_client(monkeypatch, tmp_path):
    from memegine import executor, topics, reference_lib, style_codex
    from memegine.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-fake", raising=False)
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)

    # Seed some state.
    topics.add("trader at 3am", priority=4)
    style_codex.init_template()

    fake_client = MagicMock()
    fake_client.complete_json.return_value = {
        "intents": [
            {
                "label": "sharpened-from-queue",
                "intent": "trader at 3am, cope face, 35mm Cinestill 800T",
                "why": "quick reactive win given recent ETH dump",
                "suggested_format": "photoreal_portrait",
            },
            {
                "label": "winner-variant",
                "intent": "same character, different location",
                "why": "compound the winning character",
                "suggested_format": "photoreal_portrait",
            },
            {
                "label": "net-new",
                "intent": "a cope chart with absurd numbers",
                "why": "archive has never done this register",
                "suggested_format": "cope_chart",
            },
        ],
        "note": "focus on compounding one character",
    }
    monkeypatch.setattr(executor, "get_client", lambda: fake_client)

    result = morning_briefer.generate()
    assert not result.error
    assert len(result.intents) == 3
    assert result.note


def test_gather_state_includes_queue_and_codex(tmp_path, monkeypatch):
    from memegine import topics, style_codex
    from memegine.config import settings
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()

    topics.add("x", priority=3)
    style_codex.init_template()
    state = morning_briefer._gather_state()
    assert len(state["queued_topics"]) == 1
    assert "North Star" in state["codex"]


def test_as_text_handles_error():
    result = morning_briefer.MorningBrief(error="boom")
    assert "ERROR" in result.as_text()


def test_as_text_formats_intents():
    result = morning_briefer.MorningBrief(
        intents=[
            {"label": "a", "intent": "one", "why": "wa", "suggested_format": "f1"},
            {"label": "b", "intent": "two", "why": "wb", "suggested_format": "f2"},
        ],
        note="hi",
    )
    text = result.as_text()
    assert "morning brief" in text.lower()
    assert "one" in text and "two" in text
