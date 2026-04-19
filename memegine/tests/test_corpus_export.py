from __future__ import annotations

import csv
from pathlib import Path

import pytest

from memegine import corpus_export, reference_lib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    yield tmp_path


def _add_ref(tmp_path: Path, marker: str, tags: list[str], patterns: dict | None = None) -> str:
    img = tmp_path / f"{marker}.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + marker.encode())
    entry = reference_lib.add(img, tags=tags)
    if patterns:
        refs = reference_lib._load_index()
        for r in refs:
            if r["id"] == entry.id:
                r["extracted_patterns"] = patterns
        reference_lib._save_index(refs)
    return entry.id


def test_export_empty_writes_header_only(isolated, tmp_path):
    dst = tmp_path / "out.csv"
    n = corpus_export.export(dst)
    assert n == 0
    rows = dst.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1  # header


def test_export_includes_extracted_fields(isolated, tmp_path):
    _add_ref(tmp_path, "a", ["night"], {
        "lens": "35mm f/1.4", "film_stock": "Portra 400",
    })
    dst = tmp_path / "out.csv"
    corpus_export.export(dst)
    rows = list(csv.DictReader(dst.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["lens"] == "35mm f/1.4"
    assert rows[0]["film_stock"] == "Portra 400"


def test_compare_by_tag_returns_per_field_counts(isolated, tmp_path):
    _add_ref(tmp_path, "a1", ["editor:alice"], {"lens": "35mm f/1.4"})
    _add_ref(tmp_path, "a2", ["editor:alice"], {"lens": "35mm f/1.4"})
    _add_ref(tmp_path, "b1", ["editor:bob"], {"lens": "85mm f/1.2"})

    diff = corpus_export.compare_by_tag("editor:alice", "editor:bob")
    alice_lens = diff["lens"]["a"]
    bob_lens = diff["lens"]["b"]
    assert alice_lens and alice_lens[0][0] == "35mm f/1.4"
    assert bob_lens and bob_lens[0][0] == "85mm f/1.2"


def test_compare_text_shows_both_sides(isolated, tmp_path):
    _add_ref(tmp_path, "a", ["editor:alice"], {"lens": "35mm f/1.4"})
    _add_ref(tmp_path, "b", ["editor:bob"], {"lens": "85mm f/1.2"})
    text = corpus_export.compare_text("editor:alice", "editor:bob")
    assert "editor:alice" in text
    assert "editor:bob" in text
    assert "35mm" in text
    assert "85mm" in text


def test_compare_ignores_refs_without_patterns(isolated, tmp_path):
    _add_ref(tmp_path, "a", ["editor:alice"])  # no patterns
    _add_ref(tmp_path, "b", ["editor:alice"], {"lens": "50mm"})
    diff = corpus_export.compare_by_tag("editor:alice", "editor:other")
    assert diff["lens"]["a"] == [("50mm", 1)]
