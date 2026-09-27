"""
Leak-proof replay-validation harness for the VETO decision-ledger refactor.

Validates the CURRENT (denominator-leak-fix) design, where:
  - graduated_rules.evaluate_signal() NO LONGER bumps times_applied for veto rules
    (it only RETURNS the matched veto rule_ids as the 4th tuple element).
  - record_veto_outcome(rule_ids, won) is the SOLE writer of veto times_applied AND
    times_correct, so the denominator (applied) and numerator (correct) describe the
    SAME population BY CONSTRUCTION, regardless of how many call sites fire the veto.

This directly probes the adversarial finding: a 5th call site
(ensemble.evaluate_raw, ~line 1011) vetoes WITHOUT recording (rule_ids -> '_').
Under the fix, driving evaluate_signal from ANY non-recording context must leave
times_applied at zero.

Scenarios (mapped to the task spec):
  (a) non-recording caller (simulate evaluate_raw) -> times_applied UNCHANGED.
  (b) recorded losing veto -> applied AND correct both +1 on the SAME rule_ids.
  (c) winning blocked counterfactual -> applied +1, correct +0.
  (d) overridden trade -> excluded entirely (neither applied nor correct).
  (e) two sites vetoing the SAME decision_id -> union rule_ids, resolve once.
  (f) times_correct <= times_applied always (global invariant).

DRY: isolated engine (_save no-op), throwaway temp learner dir, module singleton
re-pointed to the isolated engine. Never touches live rules/CF files or .env.

RUN (from bot/):  python data/analysis/veto_ledger_leakproof_harness.py
EXIT 0 = safe-to-deploy, 1 = needs-fix.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.graduated_rules import GraduatedRulesEngine, GraduatedRule
from llm.counterfactual_learner import CounterfactualLearner
import llm.graduated_rules as gr_mod


# ── isolation helpers ─────────────────────────────────────────────

def make_isolated_engine(rules):
    eng = GraduatedRulesEngine()
    eng._loaded = True
    eng._save = lambda: None
    eng._rules = list(rules)
    return eng


def make_temp_learner():
    d = tempfile.mkdtemp(prefix="veto_leakproof_")
    return CounterfactualLearner(data_dir=d), d


def wire_singleton(engine):
    gr_mod._engine = engine
    gr_mod.get_graduated_rules_engine = lambda: engine


def veto_rule(rule_id, conditions, statement="auto"):
    return GraduatedRule(
        rule_id=rule_id,
        hypothesis_statement=(statement if statement != "auto"
                              else f"Never trade under {conditions}"),
        action="veto",
        conditions=dict(conditions),
        active=True,
    )


class Check:
    def __init__(self):
        self.results = []
        self.anomalies = []

    def ok(self, name, cond, detail=""):
        cond = bool(cond)
        self.results.append((name, cond, detail))
        if not cond:
            self.anomalies.append(f"{name}: {detail}")
        return cond

    def invariant_correct_le_applied(self, engine, label):
        for r in engine._rules:
            self.ok(f"[{label}] correct<=applied ({r.rule_id})",
                    r.times_correct <= r.times_applied,
                    f"correct={r.times_correct} applied={r.times_applied}")
            self.ok(f"[{label}] accuracy in [0,1] ({r.rule_id})",
                    0.0 <= r.accuracy <= 1.0, f"acc={r.accuracy}")


def run():
    c = Check()
    # Track whether each global property holds across all scenarios.
    no_leak_any_caller = True
    applied_equals_recorded = True

    # ============================================================
    # (a) NON-RECORDING CALLER (simulate evaluate_raw): firing the
    #     veto N times WITHOUT recording must NOT move times_applied.
    #     This is the exact leak the adversarial review flagged at the
    #     5th site (rule_ids discarded into '_').
    # ============================================================
    ruleA = veto_rule("rule_a", {"symbol": "BTC", "side": "BUY"})
    engA = make_isolated_engine([ruleA])
    wire_singleton(engA)

    EVALUATE_RAW_FIRES = 25
    returned_ids_each_fire = []
    for _ in range(EVALUATE_RAW_FIRES):
        # Mirror ensemble.evaluate_raw ~1011: 4th element discarded into '_'.
        vetoed, _conf, _summary, _ = engA.evaluate_signal(
            symbol="BTC", regime="trend", side="BUY",
            strategy="ensemble", num_agree=2, confidence=70.0,
            strategies_active=["regime_trend"],
        )
        # Re-call to capture ids (proves the rule matched / would-veto).
        _v2, _, _, ids = engA.evaluate_signal(
            symbol="BTC", regime="trend", side="BUY", confidence=70.0)
        returned_ids_each_fire.append((vetoed, ids))

    fired_every_time = all(v and ids == ["rule_a"] for v, ids in returned_ids_each_fire)
    c.ok("(a) evaluate_raw-style fire returns rule_ids every time",
         fired_every_time, f"sample={returned_ids_each_fire[:2]}")
    leak_a = (ruleA.times_applied == 0 and ruleA.times_correct == 0)
    c.ok("(a) non-recording caller does NOT move times_applied (LEAK-PROOF)",
         leak_a, f"applied={ruleA.times_applied} correct={ruleA.times_correct} "
                 f"after {EVALUATE_RAW_FIRES*2} fires")
    if not leak_a:
        no_leak_any_caller = False
    c.invariant_correct_le_applied(engA, "a")

    # ============================================================
    # (b) RECORDED LOSING VETO through resolution -> applied AND
    #     correct both +1 on the SAME rule_ids.
    #     (Drive via the real CF resolution path, not a direct call.)
    # ============================================================
    ruleB = veto_rule("rule_b", {"symbol": "ETH", "side": "BUY"})
    engB = make_isolated_engine([ruleB])
    cfB, _ = make_temp_learner()
    wire_singleton(engB)

    # Site fires (no counter movement), then stamps a CF carrying the ids.
    _v, _, _, idsB = engB.evaluate_signal(symbol="ETH", regime="trend",
                                          side="BUY", confidence=70.0)
    c.ok("(b) pre-resolution applied still zero (fire didn't count)",
         ruleB.times_applied == 0, f"applied={ruleB.times_applied}")
    cfB.record_veto_counterfactual(
        symbol="ETH", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0,
        tp2=120.0, confidence=70.0, veto_rule_ids=idsB)
    # BUY price falls through SL -> blocked trade would have LOST -> veto correct.
    cfB.update_with_price("ETH", high=100.0, low=94.0, close=94.0)
    c.ok("(b) losing recorded veto: applied +1", ruleB.times_applied == 1,
         f"applied={ruleB.times_applied}")
    c.ok("(b) losing recorded veto: correct +1 (same rule_id)",
         ruleB.times_correct == 1, f"correct={ruleB.times_correct}")
    # applied == recorded population (1 resolved CF carrying rule_b).
    resolvedB = [r for r in cfB._resolved_recent
                 if "rule_b" in (r.metadata.get("veto_rule_ids") or [])]
    eqB = (len(resolvedB) == ruleB.times_applied == 1)
    c.ok("(b) applied == recorded resolved-CF population",
         eqB, f"resolved={len(resolvedB)} applied={ruleB.times_applied}")
    if not eqB:
        applied_equals_recorded = False
    c.invariant_correct_le_applied(engB, "b")

    # ============================================================
    # (c) WINNING blocked counterfactual -> applied +1, correct +0.
    # ============================================================
    ruleC = veto_rule("rule_c", {"symbol": "SOL", "side": "BUY"})
    engC = make_isolated_engine([ruleC])
    cfC, _ = make_temp_learner()
    wire_singleton(engC)
    _v, _, _, idsC = engC.evaluate_signal(symbol="SOL", regime="trend",
                                          side="BUY", confidence=70.0)
    cfC.record_veto_counterfactual(
        symbol="SOL", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0,
        tp2=120.0, confidence=70.0, veto_rule_ids=idsC)
    # BUY price runs through TP2 -> blocked trade would have WON -> veto WRONG.
    cfC.update_with_price("SOL", high=121.0, low=100.0, close=121.0)
    c.ok("(c) winning blocked veto: applied +1", ruleC.times_applied == 1,
         f"applied={ruleC.times_applied}")
    c.ok("(c) winning blocked veto: correct stays 0",
         ruleC.times_correct == 0, f"correct={ruleC.times_correct}")
    resolvedC = [r for r in cfC._resolved_recent
                 if "rule_c" in (r.metadata.get("veto_rule_ids") or [])]
    eqC = (len(resolvedC) == ruleC.times_applied == 1)
    c.ok("(c) applied == recorded resolved-CF population", eqC,
         f"resolved={len(resolvedC)} applied={ruleC.times_applied}")
    if not eqC:
        applied_equals_recorded = False
    c.invariant_correct_le_applied(engC, "c")

    # ============================================================
    # (d) OVERRIDDEN trade excluded entirely: record_skip with the
    #     overridden reason and NO stamp must touch NEITHER counter.
    # ============================================================
    ruleD = veto_rule("rule_d", {"symbol": "BTC", "side": "BUY"})
    engD = make_isolated_engine([ruleD])
    cfD, _ = make_temp_learner()
    wire_singleton(engD)
    # Override path fires evaluate_signal (no counter move) then flows through.
    engD.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)
    applied_before_d = ruleD.times_applied
    cfD.record_skip(symbol="BTC", side="BUY", entry_price=100.0, sl=95.0,
                    tp1=110.0, tp2=120.0, confidence=70.0,
                    skip_reason="graduated_rule_veto_overridden")
    cfD.update_with_price("BTC", high=100.0, low=94.0, close=94.0)  # would-be loss
    excluded_d = (ruleD.times_applied == applied_before_d == 0
                  and ruleD.times_correct == 0)
    c.ok("(d) overridden trade excluded from denominator AND numerator",
         excluded_d,
         f"applied={ruleD.times_applied} correct={ruleD.times_correct}")
    # Override is leak-class too: it must never inflate applied.
    if ruleD.times_applied != 0:
        no_leak_any_caller = False
    # The dedicated override counters DO move (separate audit-only bookkeeping).
    engD.record_veto_overridden(["rule_d"], won=True)
    c.ok("(d) override tracked in separate counters only",
         ruleD.times_overridden == 1 and ruleD.overridden_correct == 1
         and ruleD.times_applied == 0 and ruleD.times_correct == 0,
         f"ov={ruleD.times_overridden} ovc={ruleD.overridden_correct} "
         f"applied={ruleD.times_applied} correct={ruleD.times_correct}")
    c.invariant_correct_le_applied(engD, "d")

    # ============================================================
    # (e) TWO sites veto the SAME decision_id (same symbol/side/entry/
    #     minute) -> union rule_ids, ONE pending row, resolve ONCE.
    # ============================================================
    ruleE1 = veto_rule("rule_e1", {"symbol": "BTC", "side": "BUY"})
    ruleE2 = veto_rule("rule_e2", {"symbol": "BTC", "side": "BUY"})
    engE = make_isolated_engine([ruleE1, ruleE2])
    cfE, _ = make_temp_learner()
    wire_singleton(engE)
    # Site 1 stamps rule_e1 only (simulate a site that matched only e1's id set).
    rid1 = cfE.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0,
        tp2=120.0, confidence=70.0, veto_rule_ids=["rule_e1"])
    # Site 2, SAME would-be trade, stamps rule_e2 -> must MERGE into the same row.
    rid2 = cfE.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0,
        tp2=120.0, confidence=70.0, veto_rule_ids=["rule_e2"])
    c.ok("(e) two sites collapse to ONE CF row", rid1 == rid2,
         f"rid1={rid1} rid2={rid2}")
    pendE = [r for r in cfE._pending.values() if r.metadata.get("veto_rule_ids")]
    c.ok("(e) exactly one pending CF after merge", len(pendE) == 1,
         f"pending={len(pendE)}")
    merged_ids = pendE[0].metadata.get("veto_rule_ids") if pendE else []
    c.ok("(e) rule_ids are UNIONED across both sites",
         set(merged_ids) == {"rule_e1", "rule_e2"}, f"merged={merged_ids}")
    # Resolve once (loss) -> BOTH rules credited applied+correct exactly once.
    cfE.update_with_price("BTC", high=100.0, low=94.0, close=94.0)
    e_credit = (ruleE1.times_applied == 1 and ruleE1.times_correct == 1
                and ruleE2.times_applied == 1 and ruleE2.times_correct == 1)
    c.ok("(e) single resolution credits BOTH unioned rules exactly once",
         e_credit,
         f"e1=({ruleE1.times_applied},{ruleE1.times_correct}) "
         f"e2=({ruleE2.times_applied},{ruleE2.times_correct})")
    resolvedE = [r for r in cfE._resolved_recent if r.metadata.get("veto_rule_ids")]
    eqE = (len(resolvedE) == 1 and ruleE1.times_applied == 1
           and ruleE2.times_applied == 1)
    c.ok("(e) applied per rule == one resolved population (no double count)",
         eqE, f"resolved_rows={len(resolvedE)}")
    if not eqE:
        applied_equals_recorded = False
    c.invariant_correct_le_applied(engE, "e")

    # ============================================================
    # (f) GLOBAL invariant: times_correct <= times_applied across a
    #     mixed sequence of recorded outcomes on one rule.
    # ============================================================
    ruleF = veto_rule("rule_f", {"symbol": "BTC", "side": "BUY"})
    engF = make_isolated_engine([ruleF])
    wire_singleton(engF)
    # Interleave: fire (no-op), wins (applied only), losses (applied+correct).
    seq = [False, True, False, True, True, False, None, False]
    for w in seq:
        engF.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)
        engF.record_veto_outcome(["rule_f"], won=w)
    # won=None is fully unscored -> not in either counter.
    expected_applied = sum(1 for w in seq if w is not None)
    expected_correct = sum(1 for w in seq if w is False)
    c.ok("(f) applied counts only scored outcomes",
         ruleF.times_applied == expected_applied,
         f"applied={ruleF.times_applied} expected={expected_applied}")
    c.ok("(f) correct counts only losing-blocked outcomes",
         ruleF.times_correct == expected_correct,
         f"correct={ruleF.times_correct} expected={expected_correct}")
    c.ok("(f) times_correct <= times_applied (global invariant)",
         ruleF.times_correct <= ruleF.times_applied,
         f"correct={ruleF.times_correct} applied={ruleF.times_applied}")
    c.invariant_correct_le_applied(engF, "f")

    # ── report ──
    passed = sum(1 for _, ok, _ in c.results if ok)
    total = len(c.results)
    verdict = ("safe-to-deploy" if (passed == total and no_leak_any_caller
                                    and applied_equals_recorded) else "needs-fix")

    print(f"\n{'='*66}")
    print(f"VETO LEDGER LEAK-PROOF HARNESS — {passed}/{total} checks passed")
    print(f"{'='*66}")
    for name, ok, detail in c.results:
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name}"
        if not ok and detail:
            line += f"  <-- {detail}"
        print(line)

    print(f"\napplied_equals_recorded : {applied_equals_recorded}")
    print(f"no_leak_any_caller      : {no_leak_any_caller}")
    print(f"VERDICT                 : {verdict}")

    summary = {
        "checks_passed": passed,
        "checks_total": total,
        "applied_equals_recorded": applied_equals_recorded,
        "no_leak_any_caller": no_leak_any_caller,
        "anomalies": c.anomalies,
        "verdict": verdict,
    }
    out = os.path.join(os.path.dirname(__file__), "veto_ledger_leakproof_report.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Report written: {out}")
    return 0 if verdict == "safe-to-deploy" else 1


if __name__ == "__main__":
    sys.exit(run())
