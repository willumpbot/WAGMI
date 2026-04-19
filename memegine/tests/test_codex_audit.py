from __future__ import annotations

from memegine import codex_audit


def test_parse_sections_handles_basic_codex():
    text = """
# Style codex

## Winners
- (2026-04-18) "prompt A" — landed because foo
- (2026-04-17) "prompt B" — landed because bar

## Kill List
- (2026-04-15) drake yes/no — feels stale
"""
    sections = codex_audit._parse_sections(text)
    assert len(sections) >= 2
    names = [s[0] for s in sections]
    assert "Winners" in names
    assert "Kill List" in names


def test_detect_duplicates_finds_repeats():
    entries = [
        '"prompt A" — landed',
        '"prompt A" — landed',
        "unique entry",
    ]
    dups = codex_audit._detect_duplicates(entries)
    assert len(dups) == 1
    assert dups[0][1] == 2


def test_detect_contradictions_finds_use_vs_avoid():
    entries = [
        "always use Portra 400 for skin tones",
        "avoid Portra 400 for night scenes",
    ]
    pairs = codex_audit._detect_contradictions(entries)
    assert pairs
    # The pair references both the 'use' and 'avoid' lines.
    pair = pairs[0]
    joined = pair[0].lower() + " " + pair[1].lower()
    assert "use portra 400" in joined
    assert "avoid portra 400" in joined


def test_detect_contradictions_ignores_unrelated():
    entries = [
        "use Cinestill 800T for night",
        "avoid digital HDR",
    ]
    pairs = codex_audit._detect_contradictions(entries)
    assert pairs == []


def test_audit_reports_empty_codex():
    result = codex_audit.audit("")
    assert result.total_entries == 0
    text = result.as_text()
    assert "codex is clean" in text


def test_audit_reports_heavy_section():
    # Generate a section with 21 entries.
    entries = "\n".join(f"- entry {i}" for i in range(21))
    text = f"## Some Section\n{entries}\n"
    result = codex_audit.audit(text)
    assert "Some Section" in result.heavy_sections


def test_audit_reports_global_duplicates():
    text = """
## Sec A
- "prompt A" — landed
## Sec B
- "prompt A" — landed
"""
    result = codex_audit.audit(text)
    assert result.global_duplicates
    # The duplicate body surfaces.
    dup_body = result.global_duplicates[0][0].lower()
    assert "prompt a" in dup_body


def test_audit_as_text_includes_key_markers():
    text = """
## Winners
- "prompt A"
- "prompt A"
"""
    result = codex_audit.audit(text)
    out = result.as_text()
    assert "codex audit" in out
    assert "Winners" in out


def test_audit_ignores_empty_placeholders():
    text = """
## Winners
- (empty)

## Kill List
- (none yet)
"""
    result = codex_audit.audit(text)
    # Both sections parsed but have zero real entries.
    assert result.total_entries == 0
