from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from memegine import weekly_report


def test_no_api_key_returns_error(monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    result = weekly_report.generate()
    assert result.error


def test_generates_markdown_with_mocked_client(monkeypatch, tmp_path):
    from memegine import executor, style_codex
    from memegine.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-fake", raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs", raising=False)
    (tmp_path / "refs").mkdir()
    (tmp_path / "logs").mkdir()
    style_codex.init_template()

    from memegine import performance, session
    monkeypatch.setattr(performance, "_store_path", lambda: tmp_path / "perf.jsonl")
    monkeypatch.setattr(session, "_events_path", lambda: tmp_path / "events.jsonl")
    from memegine import export as export_mod
    monkeypatch.setattr(export_mod, "_posts_dir", lambda: tmp_path / "posts")

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = "## This week in pieces\n\nGreat week.\n"
    fake_client.complete.return_value = fake_response
    monkeypatch.setattr(executor, "get_client", lambda: fake_client)

    result = weekly_report.generate(days=7)
    assert not result.error
    assert "This week" in result.markdown


def test_strips_outer_code_fences(monkeypatch, tmp_path):
    from memegine import executor, style_codex
    from memegine.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-fake", raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs", raising=False)
    (tmp_path / "refs").mkdir()
    (tmp_path / "logs").mkdir()
    style_codex.init_template()

    from memegine import performance, session, export as export_mod
    monkeypatch.setattr(performance, "_store_path", lambda: tmp_path / "perf.jsonl")
    monkeypatch.setattr(session, "_events_path", lambda: tmp_path / "events.jsonl")
    monkeypatch.setattr(export_mod, "_posts_dir", lambda: tmp_path / "posts")

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = "```markdown\n## Report\n\nContent here.\n```"
    fake_client.complete.return_value = fake_response
    monkeypatch.setattr(executor, "get_client", lambda: fake_client)

    result = weekly_report.generate(days=7)
    assert "## Report" in result.markdown
    assert "```" not in result.markdown


def test_error_on_exception(monkeypatch, tmp_path):
    from memegine import executor
    from memegine.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-fake", raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs", raising=False)
    (tmp_path / "refs").mkdir()
    (tmp_path / "logs").mkdir()

    from memegine import performance, session, export as export_mod
    monkeypatch.setattr(performance, "_store_path", lambda: tmp_path / "perf.jsonl")
    monkeypatch.setattr(session, "_events_path", lambda: tmp_path / "events.jsonl")
    monkeypatch.setattr(export_mod, "_posts_dir", lambda: tmp_path / "posts")

    fake_client = MagicMock()
    fake_client.complete.side_effect = RuntimeError("claude boom")
    monkeypatch.setattr(executor, "get_client", lambda: fake_client)

    result = weekly_report.generate(days=7)
    assert result.error
    assert "boom" in result.error
