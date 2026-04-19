from __future__ import annotations

from pathlib import Path

import pytest

from memegine import reference_lib, thumbnails


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    yield tmp_path


def _make_png(path: Path, size: tuple[int, int] = (512, 384), color=(128, 64, 32)) -> None:
    from PIL import Image
    img = Image.new("RGB", size, color)
    img.save(path, "PNG")


def test_generate_creates_thumbnails(isolated, tmp_path):
    src = tmp_path / "a.png"
    _make_png(src)
    reference_lib.add(src, tags=["test"])
    result = thumbnails.generate_all()
    assert result.generated == 1
    # Thumb exists and is smaller than the source in pixel width.
    refs = reference_lib._load_index()
    thumb = thumbnails.thumb_path_for(refs[0]["id"])
    assert thumb is not None and thumb.exists()
    from PIL import Image
    with Image.open(thumb) as img:
        assert img.width == 256


def test_generate_skips_up_to_date(isolated, tmp_path):
    src = tmp_path / "a.png"
    _make_png(src)
    reference_lib.add(src, tags=["test"])
    r1 = thumbnails.generate_all()
    assert r1.generated == 1
    r2 = thumbnails.generate_all()
    assert r2.generated == 0
    assert r2.skipped == 1


def test_generate_force_regenerates(isolated, tmp_path):
    src = tmp_path / "a.png"
    _make_png(src)
    reference_lib.add(src, tags=["test"])
    thumbnails.generate_all()
    r2 = thumbnails.generate_all(force=True)
    assert r2.generated == 1
    assert r2.skipped == 0


def test_handles_missing_source_file(isolated, tmp_path):
    src = tmp_path / "a.png"
    _make_png(src)
    reference_lib.add(src, tags=["test"])
    # Remove the source file after adding.
    from memegine.config import settings
    (settings.references_dir / next(iter(reference_lib._load_index()))["filename"]).unlink()
    result = thumbnails.generate_all()
    assert result.errors


def test_small_image_not_upscaled(isolated, tmp_path):
    """A 128px image shouldn't be upscaled to 256."""
    src = tmp_path / "tiny.png"
    _make_png(src, size=(128, 96))
    reference_lib.add(src, tags=["test"])
    result = thumbnails.generate_all()
    assert result.generated == 1
    refs = reference_lib._load_index()
    thumb = thumbnails.thumb_path_for(refs[0]["id"])
    from PIL import Image
    with Image.open(thumb) as img:
        assert img.width == 128  # preserved


def test_summary_text_includes_counts(isolated):
    r = thumbnails.ThumbResult(generated=3, skipped=1)
    text = thumbnails.summary_text(r)
    assert "3 generated" in text
    assert "1 skipped" in text
