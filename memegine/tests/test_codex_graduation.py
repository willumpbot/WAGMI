from __future__ import annotations

import pytest

from memegine import auto_codex


@pytest.fixture
def isolated_codex(tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc
    monkeypatch.setattr(sc.settings, "codex_path", codex_path, raising=False)
    return codex_path


def test_graduate_promotes_when_threshold_met(isolated_codex):
    prompts = [
        "35mm f/1.4, Portra 400, window light, dusk, rule of thirds",
        "35mm f/1.4, Cinestill 800T, window light, 3am, rule of thirds",
        "35mm f/1.4, Portra 400, window light, dusk, centered",
        "35mm f/1.4, Portra 400, softbox, dusk, centered",
        "35mm f/1.4, Portra 400, window light, dusk, rule of thirds",
    ]
    promoted = auto_codex.graduate_patterns(prompts, promotion_threshold=5)
    assert promoted  # 35mm appears 5 times
    assert "lens" in promoted
    text = isolated_codex.read_text(encoding="utf-8")
    assert "Core Patterns" in text
    assert "35mm" in text


def test_graduate_noop_below_threshold(isolated_codex):
    prompts = ["35mm f/1.4", "50mm f/1.8"]
    promoted = auto_codex.graduate_patterns(prompts, promotion_threshold=5)
    assert promoted == {}
    # No Core Patterns section written.
    assert not isolated_codex.exists() or "Core Patterns" not in isolated_codex.read_text(encoding="utf-8")


def test_graduate_returns_only_hit_categories(isolated_codex):
    # All 5 prompts have 35mm but no film, so lens promotes and film does not.
    prompts = ["35mm f/1.4, dusk"] * 5
    promoted = auto_codex.graduate_patterns(prompts, promotion_threshold=5)
    assert "lens" in promoted
    # film list must be empty or absent:
    assert not promoted.get("film", [])
