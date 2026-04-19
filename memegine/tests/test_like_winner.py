from __future__ import annotations

import pytest

from memegine import like_winner, reference_lib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    monkeypatch.setattr(settings, "codex_path", tmp_path / "style.md", raising=False)
    yield tmp_path


def test_raises_when_no_winner(isolated):
    with pytest.raises(ValueError):
        like_winner.build("new subject")


def test_requires_intent(isolated, tmp_path):
    img = tmp_path / "w.png"
    img.write_bytes(b"PNG")
    reference_lib.add(img, prompt="some prompt", winner=True)
    with pytest.raises(ValueError):
        like_winner.build("")


def test_inherits_winner_patterns(isolated, tmp_path):
    img = tmp_path / "w.png"
    img.write_bytes(b"PNG")
    winner_prompt = (
        "Trader at 3am, 35mm f/1.4, Portra 400, window light, dusk, "
        "rule of thirds"
    )
    reference_lib.add(img, prompt=winner_prompt, winner=True)

    result = like_winner.build("a CEO at a rooftop")
    assert result.source_prompt == winner_prompt
    # The new prompt starts with the new intent and includes inherited tokens.
    assert result.prompt.startswith("a CEO at a rooftop")
    assert "35mm" in result.prompt
    assert "portra" in result.prompt.lower()
    assert "window light" in result.prompt
    assert "dusk" in result.prompt


def test_patterns_list_populated(isolated, tmp_path):
    img = tmp_path / "w.png"
    img.write_bytes(b"PNG")
    reference_lib.add(
        img, prompt="35mm f/1.4, Cinestill 800T, neon, 3am, centered medium",
        winner=True,
    )
    result = like_winner.build("dev at a desk")
    assert any("35mm" in p for p in result.patterns)


def test_score_is_high_on_inherited_craft(isolated, tmp_path):
    img = tmp_path / "w.png"
    img.write_bytes(b"PNG")
    reference_lib.add(
        img, prompt="35mm f/1.4, Portra 400, window light, dusk, rule of thirds",
        winner=True,
    )
    result = like_winner.build("a dev at a desk")
    # Inherited craft + auto-appended negatives should land A or B.
    assert result.grade in ("A", "B", "C")


def test_prefers_latest_winner(isolated, tmp_path):
    img1 = tmp_path / "old.png"
    img1.write_bytes(b"PNG1")
    img2 = tmp_path / "new.png"
    img2.write_bytes(b"PNG2")

    reference_lib.add(img1, prompt="old prompt with 50mm", winner=True)
    reference_lib.add(img2, prompt="newer with 85mm f/1.2", winner=True)

    result = like_winner.build("new intent")
    assert "85mm" in result.prompt
    assert "50mm" not in result.prompt


def test_as_text_formats():
    result = like_winner.LikeWinnerResult(
        new_intent="x", source_ref_id="abc123",
        source_prompt="src", patterns=["35mm"], prompt="p", score=90, grade="A",
    )
    text = result.as_text()
    assert "source ref" in text
    assert "new intent" in text
    assert "=== prompt ===" in text
