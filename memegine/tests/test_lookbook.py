from __future__ import annotations

from pathlib import Path

import pytest

from memegine import lookbook, reference_lib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    yield tmp_path


def _add(tmp_path: Path, marker: str, *, tags: list[str], prompt="", notes="",
         patterns: dict | None = None):
    img = tmp_path / f"{marker}.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + marker.encode())
    entry = reference_lib.add(img, tags=tags, prompt=prompt, notes=notes)
    if patterns:
        refs = reference_lib._load_index()
        for r in refs:
            if r["id"] == entry.id:
                r["extracted_patterns"] = patterns
        reference_lib._save_index(refs)
    return entry.id


def test_empty_corpus(isolated):
    out = lookbook.generate_markdown()
    assert "No refs yet" in out


def test_generate_lists_winners(isolated, tmp_path):
    _add(tmp_path, "a", tags=["winner", "portrait"], prompt="prompt a", notes="landed")
    _add(tmp_path, "b", tags=["winner", "chart"], prompt="prompt b", notes="landed 2")
    out = lookbook.generate_markdown()
    assert "# Lookbook" in out
    assert "## portrait" in out
    assert "## chart" in out
    assert "prompt a" in out
    assert "prompt b" in out


def test_winners_only_filter(isolated, tmp_path):
    _add(tmp_path, "a", tags=["winner", "portrait"], prompt="w")
    _add(tmp_path, "b", tags=["portrait"], prompt="not winner")
    out = lookbook.generate_markdown(winners_only=True)
    assert "prompt" not in out or "not winner" not in out  # excluded
    out_all = lookbook.generate_markdown(winners_only=False)
    assert "not winner" in out_all


def test_renders_extracted_patterns(isolated, tmp_path):
    _add(tmp_path, "a", tags=["winner"], prompt="p", patterns={
        "lens": "35mm f/1.4", "film_stock": "Portra 400",
    })
    out = lookbook.generate_markdown()
    assert "Craft tokens" in out
    assert "35mm" in out


def test_summary_footer_includes_top_tokens(isolated, tmp_path):
    for i in range(3):
        _add(tmp_path, f"r{i}", tags=["winner"], patterns={"lens": "35mm f/1.4"})
    out = lookbook.generate_markdown()
    assert "Summary" in out
    assert "35mm" in out


def test_write_creates_file(isolated, tmp_path):
    _add(tmp_path, "a", tags=["winner"], prompt="p")
    path = lookbook.write(tmp_path / "out.md")
    assert path.exists()
    assert "# Lookbook" in path.read_text(encoding="utf-8")


def test_write_default_destination_uses_dated_name(isolated, tmp_path):
    _add(tmp_path, "a", tags=["winner"], prompt="p")
    path = lookbook.write()
    assert path.exists()
    assert "lookbook-" in path.name


def test_max_entries_respected(isolated, tmp_path):
    for i in range(10):
        _add(tmp_path, f"r{i}", tags=["winner"], prompt=f"p{i}")
    out = lookbook.generate_markdown(max_entries=3)
    # Three refs rendered, header says "3 winners".
    assert "3 winners" in out
