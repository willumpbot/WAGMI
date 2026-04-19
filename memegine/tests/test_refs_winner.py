from __future__ import annotations

import json
from pathlib import Path

import pytest

from memegine import reference_lib


@pytest.fixture
def isolated_refs(tmp_path, monkeypatch):
    refs_dir = tmp_path / "refs"
    monkeypatch.setattr(reference_lib.settings, "references_dir", refs_dir, raising=False)
    index = refs_dir / "index.json"
    monkeypatch.setattr(reference_lib, "INDEX_PATH", index, raising=False)
    return refs_dir


@pytest.fixture
def image_file(tmp_path):
    f = tmp_path / "shot.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nsome bytes")
    return f


def test_add_without_winner_flag_does_not_add_tag(isolated_refs, image_file, tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc
    monkeypatch.setattr(sc.settings, "codex_path", codex_path, raising=False)

    entry = reference_lib.add(
        image_file, tags=["night"], prompt="a prompt", notes="cool"
    )
    assert "winner" not in entry.tags
    # No codex entry written.
    assert not codex_path.exists() or "Proven Prompt Patterns" not in codex_path.read_text(encoding="utf-8")


def test_add_with_winner_flag_tags_and_logs(isolated_refs, image_file, tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc
    monkeypatch.setattr(sc.settings, "codex_path", codex_path, raising=False)

    entry = reference_lib.add(
        image_file,
        tags=["night"],
        prompt="Trader, 35mm f/1.4, Portra 400, window light, dusk, rule of thirds",
        notes="landed because of grain",
        winner=True,
    )
    assert "winner" in entry.tags
    # Codex was written:
    text = codex_path.read_text(encoding="utf-8")
    assert "Proven Prompt Patterns" in text
    assert "Compounded Patterns" in text


def test_add_winner_without_prompt_does_not_log_codex(isolated_refs, image_file, tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc
    monkeypatch.setattr(sc.settings, "codex_path", codex_path, raising=False)

    entry = reference_lib.add(
        image_file, tags=["night"], prompt="", notes="", winner=True,
    )
    # winner tag still added, but no codex side-effect since no prompt.
    assert "winner" in entry.tags
    assert not codex_path.exists() or "Proven Prompt Patterns" not in codex_path.read_text(encoding="utf-8")


def test_winner_dedupes_tag(isolated_refs, image_file, tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc
    monkeypatch.setattr(sc.settings, "codex_path", codex_path, raising=False)

    entry = reference_lib.add(
        image_file, tags=["winner"], prompt="Trader, 35mm, Portra", winner=True,
    )
    assert entry.tags.count("winner") == 1
