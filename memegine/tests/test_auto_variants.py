from __future__ import annotations

import pytest

from memegine import reference_lib, topics


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    yield tmp_path


@pytest.fixture
def image_file(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"PNG123")
    return f


def test_auto_variants_enqueues_topics(isolated, image_file):
    entry = reference_lib.add(
        image_file, prompt="trader at 3am, 35mm, Portra 400",
        winner=True, auto_variants=True, n_variants=3,
    )
    queued = topics.list_queued()
    assert len(queued) == 3
    # Each queued topic references the ref id.
    for t in queued:
        assert entry.id[:8] in t["text"]
        assert f"variant_of:{entry.id}" in t["tags"]


def test_auto_variants_noop_without_winner(isolated, image_file):
    reference_lib.add(
        image_file, prompt="trader", winner=False, auto_variants=True,
    )
    assert topics.list_queued() == []


def test_auto_variants_noop_without_prompt(isolated, image_file):
    reference_lib.add(
        image_file, prompt="", winner=True, auto_variants=True,
    )
    assert topics.list_queued() == []


def test_n_variants_capped_at_axis_count(isolated, image_file):
    # Our axes list has 5; asking for 100 returns 5.
    reference_lib.add(
        image_file, prompt="trader", winner=True,
        auto_variants=True, n_variants=100,
    )
    assert len(topics.list_queued()) == 5


def test_topics_source_tag(isolated, image_file):
    reference_lib.add(
        image_file, prompt="trader", winner=True, auto_variants=True, n_variants=2,
    )
    for t in topics.list_queued():
        assert t["source"] == "winner_auto_variants"
