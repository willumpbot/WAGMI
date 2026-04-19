from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from memegine import stats


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    # Redirect every store used by stats to the tmp dir.
    from memegine import reference_lib, style_codex, topics, export as export_mod
    from memegine.config import settings

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir()

    monkeypatch.setattr(settings, "logs_dir", logs_dir, raising=False)
    monkeypatch.setattr(settings, "references_dir", refs_dir, raising=False)
    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(reference_lib, "INDEX_PATH", refs_dir / "index.json", raising=False)
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    monkeypatch.setattr(export_mod, "_posts_dir", lambda: posts_dir)

    yield tmp_path


def _write_brief(
    logs_dir: Path, *, kind: str, day: str,
    time: str = "00:00:01", extra: dict | None = None,
) -> None:
    """Write a JSONL brief into logs_dir. Default time is just after midnight
    so briefs always fall inside the 'daily' window (00:00 → now)."""
    path = logs_dir / f"briefs-{day}.jsonl"
    rec = {
        "id": "x",
        "created_at": f"{day}T{time}Z",
        "kind": kind,
        "intent": "test",
        "system": "s",
        "user": "u",
    }
    if extra:
        rec.update(extra)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def test_empty_environment(isolated_env):
    report = stats.compute(window="daily")
    assert report.briefs_total == 0
    assert report.refs_total == 0


def test_daily_window_counts_todays_briefs_only(isolated_env):
    logs_dir = isolated_env / "logs"
    today = dt.datetime.utcnow().date().isoformat()
    yesterday = (dt.datetime.utcnow().date() - dt.timedelta(days=1)).isoformat()
    _write_brief(logs_dir, kind="prompt", day=today)
    _write_brief(logs_dir, kind="prompt", day=today)
    _write_brief(logs_dir, kind="copy", day=yesterday)

    r = stats.compute(window="daily", logs_dir=logs_dir)
    assert r.briefs_total == 2
    assert r.briefs_by_kind["prompt"] == 2
    assert "copy" not in r.briefs_by_kind


def test_weekly_window_counts_last_7_days(isolated_env):
    logs_dir = isolated_env / "logs"
    today = dt.datetime.utcnow().date().isoformat()
    long_ago = (dt.datetime.utcnow().date() - dt.timedelta(days=30)).isoformat()
    _write_brief(logs_dir, kind="prompt", day=today)
    _write_brief(logs_dir, kind="prompt", day=long_ago)

    r = stats.compute(window="weekly", logs_dir=logs_dir)
    assert r.briefs_total == 1


def test_all_window_counts_everything(isolated_env):
    logs_dir = isolated_env / "logs"
    long_ago = (dt.datetime.utcnow().date() - dt.timedelta(days=365)).isoformat()
    _write_brief(logs_dir, kind="prompt", day=long_ago)

    r = stats.compute(window="all", logs_dir=logs_dir)
    assert r.briefs_total == 1


def test_refs_and_winner_count(isolated_env, tmp_path):
    from memegine import reference_lib
    img = tmp_path / "x.png"
    img.write_bytes(b"PNG")

    reference_lib.add(img, tags=["night"])
    reference_lib.add(img, tags=["night", "winner"])
    # Same content → dedupe; use different bytes to force two entries:
    img2 = tmp_path / "y.png"
    img2.write_bytes(b"PNG2")
    reference_lib.add(img2, winner=True)

    logs_dir = isolated_env / "logs"
    r = stats.compute(window="all", logs_dir=logs_dir)
    assert r.refs_total == 2
    # Winner count: at least 1 (the two_add on same file dedupes to 1 entry).
    assert r.refs_winners >= 1


def test_as_text_includes_key_fields(isolated_env):
    report = stats.compute(window="daily")
    text = report.as_text()
    assert "memegine activity" in text
    assert "daily" in text


def test_rejects_unknown_window(isolated_env):
    with pytest.raises(ValueError):
        stats.compute(window="unknown")
