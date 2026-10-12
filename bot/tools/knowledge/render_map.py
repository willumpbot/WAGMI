"""Regenerate the KNOWLEDGE_MAP section 3 ledger tables from the claim cards (HIVEMIND Phase 0).

Proves the cards hold the map's content: rendering the seeded cards reproduces the original rows (Verdict text,
Key number, Source, Changed) in the original order. --with-status adds the registry's own columns (status, wording
tier, verified_by) so the rendered table also shows what the map never said explicitly.

Usage: python tools/knowledge/render_map.py [--registry bot/knowledge] [--with-status] [--out FILE]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import KNOWLEDGE  # noqa: E402

# Section order and column layout of the map's section 3.
SECTIONS = ["Entries / direction", "Exits / stops", "Sizing / volatility", "Scanner flags",
            "Meme calls (Syndicate / DTN)"]
COLUMNS = {"Scanner flags": ["Flag", "Verdict", "Source"]}
DEFAULT_COLUMNS = ["Question", "Verdict", "Key number", "Source", "Changed"]


def cell(card, col):
    ev = card.get("evidence") or {}
    val = {"Question": card.get("question"), "Flag": card.get("question"), "Verdict": card.get("verdict_text"),
           "Key number": ev.get("key_number"), "Source": ", ".join(ev.get("sources") or []),
           "Changed": card.get("changed"), "Status": card.get("status"), "Tier": card.get("wording_tier"),
           "Verified": card.get("verified_by")}[col]
    return "" if val is None else str(val)


def render(registry_root=None, with_status=False, include_extra=False):
    """Markdown for section 3. Cards not seeded from the map (extra claims) are listed last only when asked."""
    claims = common.load_cards("claims", registry_root or KNOWLEDGE)
    lines = ["## 3. Knowledge ledger", ""]
    for sec in SECTIONS:
        rows = [c for c in claims.values() if c.get("section") == sec
                and (include_extra or "map_order" in c)]
        rows.sort(key=lambda c: (c.get("map_order", 10 ** 6), c["id"]))
        if not rows:
            continue
        cols = list(COLUMNS.get(sec, DEFAULT_COLUMNS))
        if with_status:
            cols += ["Status", "Tier", "Verified"]
        lines += [f"### {sec}", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for c in rows:
            lines.append("| " + " | ".join(cell(c, col) for col in cols) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--registry", default=str(KNOWLEDGE))
    ap.add_argument("--with-status", action="store_true")
    ap.add_argument("--include-extra", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    md = render(a.registry, a.with_status, a.include_extra)
    if a.out:
        Path(a.out).write_text(md + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)


if __name__ == "__main__":
    main()
