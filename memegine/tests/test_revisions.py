from __future__ import annotations

from pathlib import Path

import pytest

from memegine import reference_lib, revisions


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "references_dir", tmp_path / "refs", raising=False)
    (tmp_path / "refs").mkdir()
    yield tmp_path


def _add(tmp_path, marker: str, **kwargs):
    p = tmp_path / f"{marker}.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + marker.encode())
    return reference_lib.add(p, **kwargs).id


def test_link_unknown_refs_returns_false(isolated):
    assert not revisions.link("a", "b")


def test_link_self_raises(isolated, tmp_path):
    rid = _add(tmp_path, "a")
    with pytest.raises(ValueError):
        revisions.link(rid, rid)


def test_link_persists_revises_field(isolated, tmp_path):
    parent = _add(tmp_path, "parent")
    child = _add(tmp_path, "child")
    assert revisions.link(child, parent)
    refs = reference_lib._load_index()
    child_entry = next(r for r in refs if r["id"] == child)
    assert child_entry.get("revises") == parent


def test_unlink_removes_revises(isolated, tmp_path):
    parent = _add(tmp_path, "parent")
    child = _add(tmp_path, "child")
    revisions.link(child, parent)
    assert revisions.unlink(child)
    refs = reference_lib._load_index()
    child_entry = next(r for r in refs if r["id"] == child)
    assert "revises" not in child_entry


def test_lineage_standalone(isolated, tmp_path):
    rid = _add(tmp_path, "a")
    chain = revisions.lineage(rid)
    assert len(chain) == 1
    assert chain[0].ref_id == rid


def test_lineage_chain_ordered(isolated, tmp_path):
    a = _add(tmp_path, "a")
    b = _add(tmp_path, "b")
    c = _add(tmp_path, "c")
    revisions.link(b, a)
    revisions.link(c, b)

    chain = revisions.lineage(b)
    ids = [n.ref_id for n in chain]
    # a → b → c, centered on b.
    assert ids == [a, b, c]


def test_lineage_missing_ref_raises(isolated):
    with pytest.raises(KeyError):
        revisions.lineage("nope")


def test_lineage_text_renders(isolated, tmp_path):
    a = _add(tmp_path, "a", notes="first")
    b = _add(tmp_path, "b", notes="revised")
    revisions.link(b, a)
    text = revisions.lineage_text(a)
    assert "2 iterations" in text
    assert a in text
    assert b in text


def test_winner_starred(isolated, tmp_path):
    a = _add(tmp_path, "a", tags=["winner"], prompt="x")
    b = _add(tmp_path, "b", prompt="y")
    revisions.link(b, a)
    text = revisions.lineage_text(a)
    assert "★" in text
