"""Campaigns — group related pieces into named collections.

A campaign is a named set of refs + topics + briefs sharing a theme
(e.g., "post-ETF-launch week", "market-anon series 1", "Q2 earnings
season"). Operators can track a whole multi-piece arc as one unit.

Storage: YAML at data/campaigns/campaigns.yaml. Each campaign entry
lists `ref_ids` and `topic_ids` that belong to it.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from ._time import now_iso as _now_iso
from .config import settings


@dataclass
class Campaign:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    status: str = "active"          # active | paused | closed
    ref_ids: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _path() -> Path:
    return settings.data_dir / "campaigns" / "campaigns.yaml"


def _load() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list((raw.get("campaigns", []) if isinstance(raw, dict) else raw) or [])


def _save(entries: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"campaigns": entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def create(
    name: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
) -> Campaign:
    cid = uuid.uuid4().hex[:8]
    campaign = Campaign(
        id=cid, name=name.strip(), description=description.strip(),
        created_at=_now_iso(), status="active", tags=list(tags or []),
    )
    entries = _load()
    entries.append(asdict(campaign))
    _save(entries)
    return campaign


def list_all(status: str | None = None) -> list[dict]:
    entries = _load()
    if status:
        entries = [e for e in entries if e.get("status") == status]
    return entries


def get(campaign_id: str) -> dict | None:
    for e in _load():
        if e.get("id") == campaign_id or e.get("name") == campaign_id:
            return e
    return None


def add_ref(campaign_id: str, ref_id: str) -> bool:
    entries = _load()
    hit = False
    for e in entries:
        if e.get("id") == campaign_id or e.get("name") == campaign_id:
            refs = e.setdefault("ref_ids", [])
            if ref_id not in refs:
                refs.append(ref_id)
                hit = True
    if hit:
        _save(entries)
    return hit


def add_topic(campaign_id: str, topic_id: str) -> bool:
    entries = _load()
    hit = False
    for e in entries:
        if e.get("id") == campaign_id or e.get("name") == campaign_id:
            topic_ids = e.setdefault("topic_ids", [])
            if topic_id not in topic_ids:
                topic_ids.append(topic_id)
                hit = True
    if hit:
        _save(entries)
    return hit


def set_status(campaign_id: str, status: str) -> bool:
    if status not in ("active", "paused", "closed"):
        raise ValueError(f"status must be active | paused | closed, got {status!r}")
    entries = _load()
    hit = False
    for e in entries:
        if e.get("id") == campaign_id or e.get("name") == campaign_id:
            e["status"] = status
            hit = True
    if hit:
        _save(entries)
    return hit


def summary_text() -> str:
    entries = _load()
    if not entries:
        return "=== no campaigns ==="
    lines = [f"=== campaigns — {len(entries)} ==="]
    for e in entries:
        refs_n = len(e.get("ref_ids", []))
        topics_n = len(e.get("topic_ids", []))
        lines.append(
            f"  [{e.get('status', '?'):<8}] {e.get('id', '?')}  "
            f"{e.get('name', '?')}  refs={refs_n}  topics={topics_n}"
        )
        if e.get("description"):
            lines.append(f"    {e['description'][:80]}")
    return "\n".join(lines)
