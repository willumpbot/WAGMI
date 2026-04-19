from __future__ import annotations

import pytest

from memegine import scheduler


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine import topics, performance, reference_lib, session
    from memegine.config import settings
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    monkeypatch.setattr(performance, "_store_path", lambda: tmp_path / "perf.jsonl")
    monkeypatch.setattr(session, "_events_path", lambda: tmp_path / "events.jsonl")
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs", raising=False)
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    yield tmp_path


def test_morning_brief_runs(isolated):
    job = {"id": "m1", "action": "morning_brief", "name": "morning"}
    result = scheduler.run_morning_brief(job)
    assert result.action == "morning_brief"
    # The composed note includes dashboard markers.
    assert "next moves" in result.note
    assert "last 48h journal" in result.note


def test_morning_brief_with_queue_and_perf(isolated):
    from memegine import performance, topics
    topics.add("trader at 3am", priority=5)
    performance.log(format_slug="meme_two_panel", likes=500, reposts=100)
    job = {"id": "m2", "action": "morning_brief"}
    result = scheduler.run_morning_brief(job)
    assert "trader at 3am" in result.note
    assert "meme_two_panel" in result.note


def test_morning_brief_delivered_via_callback(isolated):
    calls = []
    def deliver(job, res):
        calls.append((job, res))
    job = {"id": "m3", "action": "morning_brief", "name": "m"}
    scheduler.run_morning_brief(job, deliver=deliver)
    assert len(calls) == 1
    assert calls[0][1].action == "morning_brief"


def test_morning_brief_registered_in_actions():
    assert "morning_brief" in scheduler.ACTIONS
