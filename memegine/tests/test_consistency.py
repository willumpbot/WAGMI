from __future__ import annotations

import pytest

from memegine import consistency, style_codex


@pytest.fixture
def isolated_codex(tmp_path, monkeypatch):
    codex = tmp_path / "style.md"
    from memegine.config import settings
    monkeypatch.setattr(settings, "codex_path", codex, raising=False)
    return codex


def test_empty_codex_returns_zero(isolated_codex):
    report = consistency.check("any prompt")
    assert report.score == 0
    assert report.core_patterns_total == 0


def test_full_alignment_scores_100(isolated_codex):
    style_codex.append_entry("Core Patterns", "lens: 35mm f/1.4")
    style_codex.append_entry("Core Patterns", "film_stock: Cinestill 800T")
    style_codex.append_entry("Core Patterns", "lighting: hard window light")
    report = consistency.check(
        "35mm f/1.4, Cinestill 800T, hard window light, rule of thirds"
    )
    assert report.score == 100
    assert not report.missed


def test_partial_alignment(isolated_codex):
    style_codex.append_entry("Core Patterns", "lens: 35mm f/1.4")
    style_codex.append_entry("Core Patterns", "film_stock: Cinestill 800T")
    report = consistency.check("35mm f/1.4, Portra 400")  # only lens matches
    assert report.score == 50


def test_missed_tokens_reported(isolated_codex):
    style_codex.append_entry("Core Patterns", "lens: 35mm f/1.4")
    style_codex.append_entry("Core Patterns", "lighting: hard window light")
    report = consistency.check("35mm f/1.4, natural lighting")
    assert any("hard window light" in m for m in report.missed)


def test_visual_dna_counted(isolated_codex):
    style_codex.append_entry("Visual DNA", "lens: 85mm f/1.2")
    report = consistency.check("85mm f/1.2 portrait")
    assert report.core_patterns_total >= 1
    assert report.score == 100


def test_compounded_patterns_counted(isolated_codex):
    style_codex.append_entry("Compounded Patterns", "film_stock: Portra 400")
    report = consistency.check("Portra 400 look")
    assert report.score == 100


def test_non_relevant_sections_ignored(isolated_codex):
    style_codex.append_entry("Kill List", "lens: avoid 24mm")
    # Kill-list tokens shouldn't drive alignment.
    report = consistency.check("35mm f/1.4 shot")
    assert report.core_patterns_total == 0


def test_as_text_shows_score_and_tokens(isolated_codex):
    style_codex.append_entry("Core Patterns", "lens: 35mm f/1.4")
    report = consistency.check("50mm portrait")
    text = report.as_text()
    assert "style consistency" in text
    assert "0" in text or "score" in text.lower()
