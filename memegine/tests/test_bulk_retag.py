from __future__ import annotations

from pathlib import Path

import pytest

from memegine import bulk_retag, reference_lib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    yield tmp_path


def _add(tmp_path, marker: str, tags: list[str]) -> str:
    p = tmp_path / f"{marker}.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + marker.encode())
    return reference_lib.add(p, tags=tags).id


def test_rename_dry_run_does_not_persist(isolated, tmp_path):
    _add(tmp_path, "a", ["portraits"])
    result = bulk_retag.rename("portraits", "portrait", dry_run=True)
    assert result.changed == 1
    # But the file is unchanged.
    assert reference_lib._load_index()[0]["tags"] == ["portraits"]


def test_rename_persists(isolated, tmp_path):
    _add(tmp_path, "a", ["portraits"])
    _add(tmp_path, "b", ["portraits", "night"])
    bulk_retag.rename("portraits", "portrait")
    tags_list = [r["tags"] for r in reference_lib._load_index()]
    # Both refs should have 'portrait' instead of 'portraits'.
    for tags in tags_list:
        assert "portrait" in tags
        assert "portraits" not in tags


def test_rename_dedupes(isolated, tmp_path):
    _add(tmp_path, "a", ["portrait", "portraits"])
    bulk_retag.rename("portraits", "portrait")
    tags = reference_lib._load_index()[0]["tags"]
    assert tags == ["portrait"]  # deduped


def test_rename_unaffected_refs_untouched(isolated, tmp_path):
    _add(tmp_path, "a", ["portraits"])
    _add(tmp_path, "b", ["night"])  # no 'portraits'
    result = bulk_retag.rename("portraits", "portrait")
    assert result.changed == 1


def test_remove_strips_tag(isolated, tmp_path):
    _add(tmp_path, "a", ["night", "batch1"])
    _add(tmp_path, "b", ["night"])
    bulk_retag.remove("batch1")
    for r in reference_lib._load_index():
        assert "batch1" not in r["tags"]


def test_add_where_selector(isolated, tmp_path):
    _add(tmp_path, "a", ["hero"])
    _add(tmp_path, "b", ["hero"])
    _add(tmp_path, "c", ["regular"])
    bulk_retag.add_where("hero", "starred")
    tags_list = [r["tags"] for r in reference_lib._load_index()]
    hero_refs = [t for t in tags_list if "hero" in t]
    for t in hero_refs:
        assert "starred" in t
    regular_refs = [t for t in tags_list if "regular" in t]
    for t in regular_refs:
        assert "starred" not in t


def test_add_where_idempotent(isolated, tmp_path):
    _add(tmp_path, "a", ["hero", "starred"])
    result = bulk_retag.add_where("hero", "starred")
    # Already has starred; no change.
    assert result.changed == 0


def test_as_text_shows_changes(isolated, tmp_path):
    _add(tmp_path, "a", ["portraits"])
    result = bulk_retag.rename("portraits", "portrait", dry_run=True)
    text = result.as_text()
    assert "1 refs" in text
    assert "portraits" in text
    assert "portrait" in text
