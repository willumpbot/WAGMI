"""Local corpus reverse — apply craft tokens without an API call.

The operator doesn't have an ANTHROPIC_API_KEY, but they ARE in a
Claude Code session. Claude has vision in-session. So instead of
calling the API, we let the operator (or Claude directly) feed in
extracted_patterns JSON that was produced by any route — in-session
analysis, manual annotation, OCR, whatever — and persist it to the
ref index.

Two entry points:
- apply_one(ref_id, patterns): write a single ref's patterns
- apply_many(payload): bulk update from {"ref_id": {...patterns...}, ...}

Also propagates patterns across sibling frames: if you analyze frame:3
of a video, the same patterns apply to frames 1/2/4/5 of that video
(they share lens/lighting/mood by construction).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import reference_lib


@dataclass
class ApplyResult:
    updated: int = 0
    propagated: int = 0
    missing: list[str] = None

    def __post_init__(self):
        if self.missing is None:
            self.missing = []

    def as_text(self) -> str:
        lines = [f"=== local reverse applied — {self.updated} direct, "
                 f"{self.propagated} propagated to video siblings ==="]
        if self.missing:
            lines.append(f"  missing ref_ids ({len(self.missing)}):")
            for m in self.missing[:10]:
                lines.append(f"    - {m}")
        return "\n".join(lines)


def _video_siblings(ref: dict, all_refs: list[dict]) -> list[dict]:
    """For a ref extracted from a video, return all 5 frames of that video."""
    video_tag = next(
        (t for t in ref.get("tags", []) or [] if t.startswith("video:")),
        None,
    )
    if not video_tag:
        return []
    return [r for r in all_refs if video_tag in (r.get("tags") or [])]


def _inherit_prompt(ref: dict) -> None:
    """When we have extracted_patterns but no prompt, synthesize one."""
    if ref.get("prompt", "").strip():
        return
    from . import corpus_reverse
    patterns = ref.get("extracted_patterns") or {}
    synth = corpus_reverse.synthesize_prompt(patterns)
    if synth:
        ref["prompt"] = synth


def apply_one(
    ref_id: str,
    patterns: dict,
    *,
    propagate_to_video: bool = True,
) -> ApplyResult:
    """Write extracted_patterns onto a single ref and optionally mirror it
    to all sibling frames from the same source video."""
    result = ApplyResult()
    refs = reference_lib._load_index()
    target = next((r for r in refs if r["id"] == ref_id), None)
    if target is None:
        result.missing = [ref_id]
        return result

    target["extracted_patterns"] = patterns
    _inherit_prompt(target)
    result.updated = 1

    if propagate_to_video:
        for sibling in _video_siblings(target, refs):
            if sibling["id"] == ref_id:
                continue
            sibling["extracted_patterns"] = dict(patterns)
            _inherit_prompt(sibling)
            result.propagated += 1

    reference_lib._save_index(refs)
    return result


def apply_many(
    payload: dict[str, dict],
    *,
    propagate_to_video: bool = True,
) -> ApplyResult:
    """Bulk variant: {ref_id: {...patterns...}}. Single file-write at end."""
    result = ApplyResult()
    refs = reference_lib._load_index()
    by_id = {r["id"]: r for r in refs}

    for ref_id, patterns in payload.items():
        target = by_id.get(ref_id)
        if target is None:
            result.missing.append(ref_id)
            continue
        target["extracted_patterns"] = patterns
        _inherit_prompt(target)
        result.updated += 1
        if propagate_to_video:
            for sibling in _video_siblings(target, refs):
                if sibling["id"] == ref_id:
                    continue
                sibling["extracted_patterns"] = dict(patterns)
                _inherit_prompt(sibling)
                result.propagated += 1

    reference_lib._save_index(refs)
    return result


def load_from_file(path: Path | str) -> ApplyResult:
    """Load a JSON file mapping ref_id → patterns dict and apply."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return apply_many(payload)
