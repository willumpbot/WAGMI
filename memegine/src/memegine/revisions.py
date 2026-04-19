"""Revisions — track iteration lineage on refs.

When the operator reshoots a piece with tweaks ("same character but
different lighting"), they'd like to say "this ref is a revision of
ref abc123". This module adds a `revises` field to the ref index
pointing at the parent ref id. The full chain is walkable both ways
— parent knows its children, child knows its parent.

Useful for:
- seeing the lineage of "Kilroy" character pieces across 5 revisions
- comparing how a look evolved between iterations
- reverting to an earlier variant's prompt when a later one went wrong
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import reference_lib


@dataclass
class LineageNode:
    ref_id: str
    filename: str
    prompt: str
    notes: str
    is_winner: bool
    children: list[str] = field(default_factory=list)


def link(child_id: str, parent_id: str) -> bool:
    """Mark `child_id` as a revision of `parent_id`."""
    refs = reference_lib._load_index()
    child = next((r for r in refs if r["id"] == child_id), None)
    parent = next((r for r in refs if r["id"] == parent_id), None)
    if child is None or parent is None:
        return False
    if child_id == parent_id:
        raise ValueError("cannot revise self")
    child["revises"] = parent_id
    reference_lib._save_index(refs)
    return True


def unlink(child_id: str) -> bool:
    refs = reference_lib._load_index()
    hit = False
    for r in refs:
        if r["id"] == child_id and "revises" in r:
            del r["revises"]
            hit = True
    if hit:
        reference_lib._save_index(refs)
    return hit


def lineage(ref_id: str) -> list[LineageNode]:
    """Return the full lineage: the ref, its ancestors, and descendants.

    Chronological order: oldest ancestor first, target in the middle,
    descendants at the end.
    """
    refs = reference_lib._load_index()
    by_id = {r["id"]: r for r in refs}
    if ref_id not in by_id:
        raise KeyError(ref_id)

    # Walk ancestors.
    ancestors: list[dict] = []
    current = by_id[ref_id]
    seen = {ref_id}
    while "revises" in current and current["revises"] in by_id:
        parent = by_id[current["revises"]]
        if parent["id"] in seen:
            break  # guard against cycles
        ancestors.append(parent)
        seen.add(parent["id"])
        current = parent
    ancestors.reverse()  # oldest first

    # Walk descendants (BFS).
    descendants: list[dict] = []
    frontier = [ref_id]
    while frontier:
        next_frontier: list[str] = []
        for r in refs:
            if r.get("revises") in frontier and r["id"] not in seen:
                descendants.append(r)
                seen.add(r["id"])
                next_frontier.append(r["id"])
        frontier = next_frontier

    chain = ancestors + [by_id[ref_id]] + descendants

    # Build nodes with children lists.
    children_map: dict[str, list[str]] = {}
    for r in refs:
        parent = r.get("revises")
        if parent:
            children_map.setdefault(parent, []).append(r["id"])

    nodes: list[LineageNode] = []
    for r in chain:
        tags = r.get("tags", []) or []
        nodes.append(LineageNode(
            ref_id=r["id"], filename=r["filename"],
            prompt=(r.get("prompt") or "")[:200],
            notes=(r.get("notes") or "")[:200],
            is_winner="winner" in tags,
            children=children_map.get(r["id"], []),
        ))
    return nodes


def lineage_text(ref_id: str) -> str:
    try:
        nodes = lineage(ref_id)
    except KeyError:
        return f"ERROR: ref not found: {ref_id}"
    if len(nodes) == 1:
        return f"=== lineage {ref_id} — standalone ==="
    lines = [f"=== lineage for {ref_id} — {len(nodes)} iterations ==="]
    for i, n in enumerate(nodes, 1):
        marker = "★" if n.is_winner else " "
        lines.append(f"  {i:>2}.{marker} {n.ref_id}  children={len(n.children)}")
        if n.notes:
            lines.append(f"        notes: {n.notes[:90]}")
        if n.prompt:
            lines.append(f"        prompt: {n.prompt[:90]}")
    return "\n".join(lines)
