"""FALLACY_AUDIT 2026-07-02 D1 — quarantine keyword-graduated rules + seed retirement ledger.

What it does (idempotent):
1. Deactivates every rule with an auto-generated id (rule_<epoch>_<n>) in
   bot/data/llm/graduated_rules.json. These were produced by the lossy keyword
   parser (graduated_rules._parse_hypothesis) from sub-standard hypotheses
   (n as low as 7, INVALIDATED ratio<=0.3 graduating, actions inverted vs the
   statement's actual stats). No provenance, no dollar validation -> shadow.
2. Seeds bot/data/llm/retired_rule_ids.json (the durable retirement ledger)
   with every inactive rule, so file regeneration/wipes can never resurrect a
   verdicted-retired rule again (the 2026-07-01 clobber re-activated 3).
3. Removes the corresponding keyword-rule injections from
   bot/data/llm/teaching/knowledge_base.json (knowledge_type=graduated_rule,
   source=hypothesis_graduation) so quarantined opinions leave agent prompts.

Run from bot/: python tools/fallacy_d1_quarantine.py
"""
import json
import os
import re
import sys
import time

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "llm")
RULES = os.path.join(BASE, "graduated_rules.json")
LEDGER = os.path.join(BASE, "retired_rule_ids.json")
KB = os.path.join(BASE, "teaching", "knowledge_base.json")

QUARANTINE_REASON = ("D1 quarantine 2026-07-02: keyword-parsed graduation "
                     "(inverted actions, n<13, no provenance/dollar validation) "
                     "[FALLACY_AUDIT D1, THE_STANDARD 2b]")
PERSIST_REASON = "pre-existing retirement persisted to durable ledger (S4/veto-rescore/owner verdicts)"

AUTO_ID = re.compile(r"^rule_\d+_\d+$")


def main():
    with open(RULES, "r") as f:
        data = json.load(f)
    rules = data.get("rules", [])

    ledger = {"entries": []}
    if os.path.exists(LEDGER):
        with open(LEDGER, "r") as f:
            ledger = json.load(f)
    entries = ledger.setdefault("entries", [])
    known_ids = {e.get("rule_id") for e in entries}

    quarantined, persisted = [], []
    for r in rules:
        rid = r.get("rule_id", "")
        if AUTO_ID.match(rid):
            if r.get("active"):
                r["active"] = False
                r["retired_reason"] = QUARANTINE_REASON
                quarantined.append(rid)
            reason = r.get("retired_reason") or QUARANTINE_REASON
        elif not r.get("active"):
            reason = r.get("retired_reason") or PERSIST_REASON
            persisted.append(rid)
        else:
            continue  # active hand-crafted rule with a standing verdict — leave alone
        if rid not in known_ids:
            entries.append({
                "rule_id": rid,
                "statement": r.get("hypothesis_statement", ""),
                "reason": reason,
                "retired_at": time.time(),
            })
            known_ids.add(rid)

    with open(RULES, "w") as f:
        json.dump(data, f, indent=2, default=str)
    with open(LEDGER, "w") as f:
        json.dump(ledger, f, indent=2, default=str)

    # 3. Strip quarantined keyword-rule injections from the knowledge base
    kb_removed = 0
    if os.path.exists(KB):
        with open(KB, "r") as f:
            kb = json.load(f)
        before = len(kb.get("entries", []))
        ledgered = known_ids
        kb["entries"] = [
            e for e in kb.get("entries", [])
            if not (e.get("knowledge_type") == "graduated_rule"
                    and e.get("source") == "hypothesis_graduation"
                    and e.get("rule_id") in ledgered)
        ]
        kb_removed = before - len(kb["entries"])
        if kb_removed:
            with open(KB, "w") as f:
                json.dump(kb, f, indent=2, default=str)

    active_after = sum(1 for r in rules if r.get("active"))
    print(f"quarantined now: {len(quarantined)} -> {quarantined}")
    print(f"persisted pre-existing retirements: {len(persisted)}")
    print(f"ledger entries total: {len(entries)}")
    print(f"KB graduated_rule injections removed: {kb_removed}")
    print(f"rules: {len(rules)} total, {active_after} active after quarantine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
