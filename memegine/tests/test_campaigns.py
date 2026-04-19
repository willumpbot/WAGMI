from __future__ import annotations

import pytest

from memegine import campaigns


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from memegine.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    yield tmp_path


def test_create_returns_campaign(isolated):
    c = campaigns.create("post-launch-week", description="week 1 after token launch")
    assert c.id
    assert c.name == "post-launch-week"
    assert c.status == "active"


def test_list_all_returns_created_campaigns(isolated):
    campaigns.create("a")
    campaigns.create("b")
    assert len(campaigns.list_all()) == 2


def test_list_by_status(isolated):
    c = campaigns.create("x")
    campaigns.set_status(c.id, "closed")
    campaigns.create("y")
    assert len(campaigns.list_all(status="active")) == 1
    assert len(campaigns.list_all(status="closed")) == 1


def test_get_by_id_or_name(isolated):
    c = campaigns.create("my-campaign")
    assert campaigns.get(c.id) is not None
    assert campaigns.get("my-campaign") is not None
    assert campaigns.get("nope") is None


def test_add_ref_dedupes(isolated):
    c = campaigns.create("x")
    assert campaigns.add_ref(c.id, "r1")
    assert not campaigns.add_ref(c.id, "r1")  # already present
    assert campaigns.add_ref(c.id, "r2")
    entry = campaigns.get(c.id)
    assert entry["ref_ids"] == ["r1", "r2"]


def test_add_topic(isolated):
    c = campaigns.create("x")
    assert campaigns.add_topic(c.id, "t1")
    entry = campaigns.get(c.id)
    assert entry["topic_ids"] == ["t1"]


def test_set_status_rejects_invalid(isolated):
    c = campaigns.create("x")
    with pytest.raises(ValueError):
        campaigns.set_status(c.id, "deleted")


def test_set_status_applies(isolated):
    c = campaigns.create("x")
    assert campaigns.set_status(c.id, "paused")
    assert campaigns.get(c.id)["status"] == "paused"


def test_summary_text_empty(isolated):
    assert "no campaigns" in campaigns.summary_text()


def test_summary_text_shows_counts(isolated):
    c = campaigns.create("x", description="notes here")
    campaigns.add_ref(c.id, "r1")
    campaigns.add_topic(c.id, "t1")
    text = campaigns.summary_text()
    assert "x" in text
    assert "refs=1" in text
    assert "topics=1" in text
