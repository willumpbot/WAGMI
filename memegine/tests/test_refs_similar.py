from __future__ import annotations

from pathlib import Path

import pytest

from memegine import reference_lib, refs_similar


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    yield tmp_path


def _add(tmp_path, marker: str, *, color, size=(64, 64)):
    from PIL import Image
    p = tmp_path / f"{marker}.png"
    Image.new("RGB", size, color=color).save(p, "PNG")
    return reference_lib.add(p, tags=["test"]).id


def test_raises_on_missing_ref(isolated):
    with pytest.raises(KeyError):
        refs_similar.find_similar("nope")


def test_returns_empty_when_only_one_ref(isolated, tmp_path):
    rid = _add(tmp_path, "a", color=(100, 100, 100))
    hits = refs_similar.find_similar(rid)
    assert hits == []


def test_ranks_by_distance(isolated, tmp_path):
    # Subject: all-gray
    rid = _add(tmp_path, "target", color=(128, 128, 128))
    # Very similar (slightly different shade of gray)
    close = _add(tmp_path, "close", color=(130, 130, 130))
    # Very different (white vs black stripes)
    from PIL import Image
    p = tmp_path / "far.png"
    img = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            img.putpixel((x, y), (255, 255, 255) if (x + y) % 2 == 0 else (0, 0, 0))
    img.save(p, "PNG")
    far = reference_lib.add(p, tags=["test"]).id

    hits = refs_similar.find_similar(rid, limit=5)
    assert hits
    # Closest should come first.
    closest = hits[0]
    assert closest.distance <= hits[-1].distance


def test_limit_respected(isolated, tmp_path):
    rid = _add(tmp_path, "target", color=(128, 128, 128))
    for i in range(5):
        _add(tmp_path, f"r{i}", color=(128 + i, 128 + i, 128 + i))
    hits = refs_similar.find_similar(rid, limit=3)
    assert len(hits) == 3


def test_find_similar_text_error_on_missing(isolated):
    text = refs_similar.find_similar_text("nope")
    assert "ERROR" in text


def test_find_similar_text_lists_distances(isolated, tmp_path):
    rid = _add(tmp_path, "target", color=(128, 128, 128))
    _add(tmp_path, "close", color=(130, 130, 130))
    text = refs_similar.find_similar_text(rid)
    assert "similar to" in text
    assert "dist=" in text
