from __future__ import annotations

from memegine import caption_linter


def test_clean_caption_passes():
    r = caption_linter.lint("kitchen, no one home")
    assert r.ok
    assert r.score == 100
    assert r.errors == []


def test_emoji_flagged():
    r = caption_linter.lint("3am 🚀")
    assert not r.ok
    assert any("emoji" in e for e in r.errors)


def test_hashtag_flagged():
    r = caption_linter.lint("trader #crypto")
    assert not r.ok
    assert any("hashtag" in e for e in r.errors)


def test_banned_phrase_flagged():
    r = caption_linter.lint("gm, wagmi, lfg")
    assert not r.ok
    # gm and wagmi and lfg all flagged
    assert len(r.errors) >= 3


def test_engagement_bait_flagged():
    r = caption_linter.lint("who else is up at 3am")
    assert not r.ok
    assert any("who else" in e for e in r.errors)


def test_length_over_280_flagged():
    caption = "a" * 300
    r = caption_linter.lint(caption)
    assert not r.ok
    assert any("280" in e for e in r.errors)


def test_empty_caption_warns():
    r = caption_linter.lint("")
    assert r.ok  # empty is technically valid (post with no caption)
    assert any("empty" in w for w in r.warnings)


def test_score_drops_with_warnings():
    # Caption that's OK but has multiple exclamation points → warn.
    r = caption_linter.lint("kitchen! quiet! 3am!")
    assert r.ok
    assert r.score < 100
    assert r.warnings


def test_score_drops_with_each_error():
    r1 = caption_linter.lint("clean caption")
    r2 = caption_linter.lint("🚀 clean")
    r3 = caption_linter.lint("🚀 #crypto")
    assert r1.score >= r2.score
    assert r2.score >= r3.score


def test_word_count_and_length_reported():
    r = caption_linter.lint("hello there friend")
    assert r.words == 3
    assert r.length == len("hello there friend")
