from __future__ import annotations

import json
from pathlib import Path

import pytest

from memegine import batch


def test_build_creates_folder_and_n_briefs(tmp_path):
    result = batch.build("trader at 3am", n=3, outputs_dir=tmp_path)
    folder = Path(result.folder)
    assert folder.exists()
    assert len(result.items) == 3
    # Each item's brief file exists and contains its format slug.
    for item in result.items:
        p = Path(item.brief_path)
        assert p.exists()
        assert item.format_slug in p.read_text(encoding="utf-8")
    # batch.json wraps the result.
    meta = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
    assert len(meta["items"]) == 3


def test_build_respects_explicit_formats(tmp_path):
    result = batch.build(
        "trader at 3am", n=2,
        formats=["photoreal_portrait", "cope_chart"],
        outputs_dir=tmp_path,
    )
    slugs = [i.format_slug for i in result.items]
    assert slugs == ["photoreal_portrait", "cope_chart"]


def test_build_skips_invalid_formats(tmp_path):
    # An unknown format is silently skipped; batch uses the default rotation.
    result = batch.build(
        "trader", n=2,
        formats=["this_format_does_not_exist"],
        outputs_dir=tmp_path,
    )
    # Falls back to rotation since no requested formats were valid.
    assert len(result.items) == 2
    assert result.items[0].format_slug in batch.DEFAULT_ROTATION


def test_build_rejects_n_zero(tmp_path):
    with pytest.raises(ValueError):
        batch.build("x", n=0, outputs_dir=tmp_path)


def test_default_rotation_covers_variety():
    # The default rotation should span different "angles" — at least one
    # meme format, one photoreal, one chart/terminal, one lore.
    assert "photoreal_portrait" in batch.DEFAULT_ROTATION
    assert "meme_two_panel" in batch.DEFAULT_ROTATION
    assert "cope_chart" in batch.DEFAULT_ROTATION
    assert "lore_drop" in batch.DEFAULT_ROTATION


def test_readme_generated(tmp_path):
    result = batch.build("test theme", n=2, outputs_dir=tmp_path)
    readme = Path(result.folder) / "README.md"
    assert readme.exists()
    text = readme.read_text(encoding="utf-8")
    assert "test theme" in text
    assert "memegine refs add" in text
