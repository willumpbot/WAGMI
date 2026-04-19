from __future__ import annotations

import pytest

from memegine import pipeline, topics


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(topics, "_queue_path", lambda: tmp_path / "queue.yaml")
    from memegine.config import settings
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs", raising=False)
    yield tmp_path


def test_build_from_topic_uses_topic_kind_and_hint(isolated_env, monkeypatch):
    t = topics.add(
        "trader cope face", tags=["night"], kind="image",
        format_hint="photoreal_portrait",
    )
    bundle = pipeline.build_from_topic(t.id)
    assert bundle.kind == "image"
    assert bundle.format_slug == "photoreal_portrait"

    # Topic marked used with bundle_id.
    used = topics.list_queued(status="used")
    assert len(used) == 1
    assert used[0]["used_bundle_id"] == bundle.id


def test_build_from_topic_auto_picks_format_when_absent(isolated_env):
    t = topics.add("drake yes no preferring X over Y", kind="image")
    bundle = pipeline.build_from_topic(t.id)
    assert bundle.kind == "image"
    # Format auto-picked by format_suggest.
    assert bundle.format_slug in ("drake_yes_no", "meme_two_panel")


def test_build_from_topic_raises_on_unknown(isolated_env):
    with pytest.raises(KeyError):
        pipeline.build_from_topic("not-a-real-id")


def test_build_from_topic_kind_override(isolated_env):
    t = topics.add("a topic", kind="image")
    # Override to video.
    bundle = pipeline.build_from_topic(t.id, kind_override="video")
    assert bundle.kind == "video"


def test_build_from_topic_handles_any_kind(isolated_env):
    # 'any' kind means infer_kind should decide.
    t = topics.add("trader portrait at dusk", kind="any")
    bundle = pipeline.build_from_topic(t.id)
    # infer_kind returns "image" here so the pipeline should be image.
    assert bundle.kind == "image"
