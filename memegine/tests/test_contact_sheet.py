from __future__ import annotations

from pathlib import Path

import pytest

from memegine import contact_sheet, reference_lib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    yield tmp_path


_COLOR_COUNTER = [0]


def _add(tmp_path, marker: str, *, tags=None):
    """Create a uniquely-colored image (avoids content-hash dedup)."""
    from PIL import Image
    _COLOR_COUNTER[0] += 1
    n = _COLOR_COUNTER[0]
    src = tmp_path / f"{marker}.png"
    img = Image.new(
        "RGB", (400, 300),
        color=(n % 256, (n * 37) % 256, (n * 71) % 256),
    )
    img.save(src, "PNG")
    return reference_lib.add(src, tags=tags or []).id


def test_raises_on_empty_corpus(isolated):
    with pytest.raises(ValueError):
        contact_sheet.generate(destination=isolated / "out.jpg")


def test_generates_sheet_winners_only(isolated, tmp_path):
    for i in range(3):
        _add(tmp_path, f"w{i}", tags=["winner"])
    _add(tmp_path, "non", tags=["regular"])

    dst = isolated / "sheet.jpg"
    result = contact_sheet.generate(destination=dst, winners_only=True)
    assert result.n_refs == 3
    assert dst.exists()


def test_generates_sheet_with_non_winners_when_all_flag(isolated, tmp_path):
    _add(tmp_path, "a", tags=["any"])
    _add(tmp_path, "b", tags=["any"])
    dst = isolated / "sheet.jpg"
    result = contact_sheet.generate(destination=dst, winners_only=False)
    assert result.n_refs == 2


def test_respects_max_refs(isolated, tmp_path):
    for i in range(10):
        _add(tmp_path, f"w{i}", tags=["winner"])
    dst = isolated / "sheet.jpg"
    result = contact_sheet.generate(destination=dst, max_refs=5)
    assert result.n_refs == 5


def test_grid_dimensions_match_ref_count(isolated, tmp_path):
    for i in range(7):
        _add(tmp_path, f"w{i}", tags=["winner"])
    result = contact_sheet.generate(
        destination=isolated / "sheet.jpg", cols=3, max_refs=7,
    )
    # 7 refs in a 3-wide grid → 3 rows (ceil).
    assert result.cols == 3
    assert result.rows == 3


def test_output_image_is_valid(isolated, tmp_path):
    _add(tmp_path, "w", tags=["winner"])
    dst = isolated / "sheet.jpg"
    contact_sheet.generate(destination=dst, cols=1)
    # Can open and get dimensions.
    from PIL import Image
    with Image.open(dst) as img:
        assert img.width > 0
        assert img.height > 0
