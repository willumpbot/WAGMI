from __future__ import annotations

from pathlib import Path

import pytest

from memegine import export, x_post


@pytest.fixture
def media(tmp_path):
    f = tmp_path / "final.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    return f


def test_prepare_raises_on_missing_bundle(tmp_path):
    with pytest.raises(FileNotFoundError):
        x_post.prepare("nonexistent-id", posts_dir=tmp_path)


def test_prepare_plan_returns_clean_on_good_post(tmp_path, media):
    posts_dir = tmp_path / "posts"
    bundle = export.build(
        media_path=media, caption="kitchen, no one home",
        alt_text="portrait of a trader at a kitchen counter at 3am",
        posts_dir=posts_dir,
    )
    plan = x_post.prepare(bundle.id, posts_dir=posts_dir)
    assert plan.lint_ok
    assert plan.caption == "kitchen, no one home"
    assert plan.alt_text.startswith("portrait")
    assert plan.media_path.endswith("final.png")
    assert plan.caption_length == len("kitchen, no one home")


def test_prepare_flags_empty_alt(tmp_path, media):
    posts_dir = tmp_path / "posts"
    bundle = export.build(
        media_path=media, caption="hello",
        alt_text="",
        posts_dir=posts_dir,
    )
    plan = x_post.prepare(bundle.id, posts_dir=posts_dir)
    assert any("alt text is empty" in w for w in plan.warnings)


def test_prepare_reports_lint_errors(tmp_path, media):
    posts_dir = tmp_path / "posts"
    bundle = export.build(
        media_path=media, caption="gm wagmi 🚀",  # triggers multiple lint errors
        alt_text="alt",
        posts_dir=posts_dir,
    )
    plan = x_post.prepare(bundle.id, posts_dir=posts_dir)
    assert not plan.lint_ok
    assert len(plan.lint_errors) >= 2


def test_clipboard_block_contains_fields(tmp_path, media):
    posts_dir = tmp_path / "posts"
    bundle = export.build(
        media_path=media, caption="short",
        alt_text="alt text",
        reply_hook="the follow-up", posts_dir=posts_dir,
    )
    plan = x_post.prepare(bundle.id, posts_dir=posts_dir)
    block = plan.clipboard_block()
    assert "MEDIA" in block
    assert "CAPTION" in block
    assert "ALT TEXT" in block
    assert "REPLY HOOK" in block
    assert "short" in block
    assert "the follow-up" in block


def test_clipboard_block_omits_reply_hook_when_absent(tmp_path, media):
    posts_dir = tmp_path / "posts"
    bundle = export.build(
        media_path=media, caption="short", alt_text="alt", posts_dir=posts_dir,
    )
    plan = x_post.prepare(bundle.id, posts_dir=posts_dir)
    assert "REPLY HOOK" not in plan.clipboard_block()


def test_checklist_status_reflects_lint(tmp_path, media):
    posts_dir = tmp_path / "posts"
    good = export.build(
        media_path=media, caption="ok", alt_text="alt", posts_dir=posts_dir,
    )
    plan_good = x_post.prepare(good.id, posts_dir=posts_dir)
    assert "READY" in plan_good.checklist_text()

    bad = export.build(
        media_path=media, caption="gm 🚀", alt_text="alt", posts_dir=posts_dir,
    )
    plan_bad = x_post.prepare(bad.id, posts_dir=posts_dir)
    assert "BLOCKED" in plan_bad.checklist_text()
