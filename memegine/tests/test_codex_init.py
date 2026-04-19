from __future__ import annotations

import pytest

from memegine import style_codex


def test_init_seeds_template(tmp_path):
    codex = tmp_path / "style.md"
    result = style_codex.init_template(codex)
    assert result == codex
    text = codex.read_text(encoding="utf-8")
    # Every required section present.
    for section in (
        "North Star", "Voice & Tone", "Visual DNA",
        "Proven Prompt Patterns", "Compounded Patterns", "Core Patterns",
        "Weekly Distill", "Kill List", "Voice Notes",
    ):
        assert section in text


def test_init_refuses_nonempty_codex(tmp_path):
    codex = tmp_path / "style.md"
    codex.write_text("already here", encoding="utf-8")
    with pytest.raises(FileExistsError):
        style_codex.init_template(codex)


def test_init_force_overwrites(tmp_path):
    codex = tmp_path / "style.md"
    codex.write_text("already here", encoding="utf-8")
    style_codex.init_template(codex, force=True)
    text = codex.read_text(encoding="utf-8")
    assert "North Star" in text
    assert "already here" not in text


def test_init_creates_parent_dir(tmp_path):
    codex = tmp_path / "nested" / "dir" / "style.md"
    style_codex.init_template(codex)
    assert codex.exists()


def test_init_over_empty_file_allowed(tmp_path):
    codex = tmp_path / "style.md"
    codex.write_text("", encoding="utf-8")
    # Empty existing file is fine — init replaces it.
    style_codex.init_template(codex)
    assert "North Star" in codex.read_text(encoding="utf-8")
