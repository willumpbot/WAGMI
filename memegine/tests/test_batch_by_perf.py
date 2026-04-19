from __future__ import annotations

import pytest

from memegine import batch, performance


@pytest.fixture
def isolated_all(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "_store_path", lambda: tmp_path / "perf.jsonl")
    yield tmp_path


def test_by_performance_empty_store_falls_back_to_rotation(isolated_all):
    # No perf data → pick_by_performance returns the default rotation items.
    from memegine.prompt_engine import load_formats
    image_formats = {f.slug for f in load_formats() if f.kind == "image"}
    picks = batch._pick_by_performance(4, image_formats)
    assert len(picks) == 4
    # First few should match default rotation order.
    assert picks[0] == batch.DEFAULT_ROTATION[0]


def test_by_performance_ranks_by_engagement(isolated_all):
    # Log enough posts for two formats to meet min_posts=2.
    performance.log(format_slug="meme_two_panel", likes=500)
    performance.log(format_slug="meme_two_panel", likes=400)
    performance.log(format_slug="lore_drop", likes=50)
    performance.log(format_slug="lore_drop", likes=40)

    from memegine.prompt_engine import load_formats
    image_formats = {f.slug for f in load_formats() if f.kind == "image"}
    picks = batch._pick_by_performance(4, image_formats)
    # meme_two_panel has higher avg score → should appear before lore_drop.
    meme_idx = picks.index("meme_two_panel")
    lore_idx = picks.index("lore_drop")
    assert meme_idx < lore_idx


def test_build_by_performance_passes_through(tmp_path, isolated_all):
    performance.log(format_slug="meme_two_panel", likes=500)
    performance.log(format_slug="meme_two_panel", likes=400)

    result = batch.build(
        "some theme", n=2, by_performance=True, outputs_dir=tmp_path,
    )
    assert len(result.items) == 2
    slugs = [i.format_slug for i in result.items]
    assert "meme_two_panel" in slugs
