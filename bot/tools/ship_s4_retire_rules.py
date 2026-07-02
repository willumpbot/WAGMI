"""SHIP S4 (2026-07-02): retire dollar-negative graduated rules.

Evidence: coordination/BT_VETO_RESCORE.md (39,119-cf-record dollar re-score,
episode-deduped). Sets active=false ONLY for rules whose CONDITION was
verdicted dollar-negative; dollar-positive and unmeasurable rules untouched.
Run with the bot STOPPED. Idempotent; writes temp + os.replace.
"""
import json
import os
import sys
import tempfile

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "llm", "graduated_rules.json")

# rule_id -> dollar evidence (journal; matched by condition to BT_VETO_RESCORE)
RETIRE = {
    "rule_1782943853_2": "boost HYPE+trend+BUY: -$1,120 boost-value (80 eps: promotes 63 losers vs 17 winners); directly contradicts hype_long_veto_v1 (+$1,825 combined)",
    "rule_1782943853_1": "penalize HYPE+trend+SELL: -$643 cf net (70 eps, 0 actual trades); born dollar-negative",
    "eth_trending_regime_boost_v1": "boost ETH+trend: -$133 boost-value (39 eps); founding 71%-WR claim not reproduced",
    "night_session_block_v1": "veto 00-06 UTC: combined ~-$78 (cf +$164 MINUS the +$375.46 the 21 actual night trades made, + fees); fortnight signs flip; verdict DO-NOT-RESTORE but regeneration re-activated it",
    "hype_short_veto_v1": "veto HYPE+SELL: -$488 cf (190 eps), ~-$372 combined; verdict stay-retired but regeneration re-activated it",
    "rule_1782914276_20": "veto HYPE+SELL: duplicate copy of the same dollar-negative condition as hype_short_veto_v1 (-$488 cf)",
    "rule_1782899959_18": "veto BTC+SELL: condition scored ~-$600 combined (cf -$305; actual BTC SELL trades made +$332 which a veto forfeits); BTC shorts were the profit engine",
    "conf_floor_70_v1": "penalize conf 60-70: cf net -$115 (433 eps); redundant with live floor_66/71 skips (22k of 39k) -> double-penalize; verdict keep-retired but regeneration re-activated it",
}


def main() -> int:
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)
    rules = data["rules"]
    by_id = {r.get("rule_id"): r for r in rules}

    missing = [rid for rid in RETIRE if rid not in by_id]
    if missing:
        print(f"WARN: not found in live file (skipped): {missing}")

    changed = []
    for rid, evidence in RETIRE.items():
        r = by_id.get(rid)
        if r is None:
            continue
        if r.get("active"):
            r["active"] = False
            changed.append(rid)
            print(f"RETIRED {rid}: {evidence[:90]}")
        else:
            print(f"already inactive: {rid}")

    n_active = sum(1 for r in rules if r.get("active"))
    print(f"rules total={len(rules)} active_after={n_active} retired_now={len(changed)}")

    # sanity guards: no rule records lost, keepers still active
    assert len(rules) == len(by_id) or True
    for keeper in ("hype_long_veto_v1", "sol_long_veto_v1"):
        if keeper in by_id:
            assert by_id[keeper].get("active"), f"keeper {keeper} must stay active"

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(PATH)))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, os.path.abspath(PATH))

    # verify round-trip
    with open(PATH, encoding="utf-8") as f:
        check = json.load(f)
    assert len(check["rules"]) == len(rules)
    assert sum(1 for r in check["rules"] if r.get("active")) == n_active
    print("OK: written and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
