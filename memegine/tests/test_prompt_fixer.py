from __future__ import annotations

from memegine import prompt_fixer


def test_fix_improves_weak_prompt():
    result = prompt_fixer.fix("a trader")
    assert result.improvement > 0
    assert result.fixed != result.original
    assert len(result.inserted) >= 3  # multiple categories plugged


def test_fix_noop_on_already_strong_prompt():
    prompt = (
        "Trader, 35mm f/1.4, Cinestill 800T, hard window light, dusk, "
        "rule of thirds, subject in hoodie, no extra fingers, no warped text."
    )
    result = prompt_fixer.fix(prompt)
    # Nothing to add — fixed == original (modulo strip)
    assert not result.inserted


def test_fixed_prompt_keeps_original_text():
    result = prompt_fixer.fix("a trader")
    assert result.fixed.startswith("a trader")


def test_fix_inserts_named_fragments():
    result = prompt_fixer.fix("a trader")
    # Check one of our defaults is referenced in the tokens.
    token_cats = [tok.split(".")[0] for tok in result.inserted]
    assert "LENS" in token_cats
    assert "LIGHTING" in token_cats


def test_fix_score_sanity():
    result = prompt_fixer.fix("a trader")
    assert 0 <= result.original_score <= 100
    assert 0 <= result.fixed_score <= 100
    assert result.fixed_score >= result.original_score


def test_as_text_includes_before_after():
    result = prompt_fixer.fix("a trader")
    text = result.as_text()
    assert "original score" in text
    assert "fixed score" in text
    assert "fixed prompt" in text
