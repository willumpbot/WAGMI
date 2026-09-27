"""
Dry replay harness — proves graduated VETO rules are self-measuring across ALL
FOUR veto call sites, and that the denominator-loss bug from the prior reverted
attempt does NOT recur.

WHY THIS EXISTS
---------------
A prior fix moved the times_applied increment off evaluate_signal but wired only
ONE of four veto call sites to record outcomes, leaving 3 paths with no
denominator. That made veto accuracy unmeasurable (times_correct=0 over 3120 uses
== de-facto permanent hardcoded block) and was REVERTED.

The current design keeps times_applied incremented INSIDE evaluate_signal (every
fire), and each of the four sites stamps the matched rule_ids into a counterfactual
that resolves the numerator (times_correct) by rule_id. This harness drives all
four sites' recording calls with KNOWN outcomes and asserts the invariants.

THE FOUR VETO SITES (faithfully simulated here with each site's exact recording call)
  1. strategies/ensemble.py veto block (~595-617)
       -> evaluate_signal(full) then cf.record_veto_counterfactual(entry/sl/tp1/tp2, ids)
  2. core/signal_pipeline.py Gate 1g (~456-478)
       -> evaluate_signal(hour_utc + strategies_active) then record_veto_counterfactual
  3. llm/agents/coordinator.py pre-LLM veto_only filter (~1633-1664) [highest volume]
       -> evaluate_signal(veto_only=True) then record_veto_counterfactual,
          denominator_only when entry/sl/tp1 missing
  4. llm/agents/coordinator.py merge veto (~4853-4877, action='flat')
       -> evaluate_signal(full) then record_veto_counterfactual,
          denominator_only when snapshot omitted sl/tp

RUN: python data/analysis/veto_replay_harness.py        (from bot/)
EXIT 0 = safe-to-deploy, EXIT 1 = needs-fix.

This is a DRY harness. It does NOT touch the live bot, the live rules file, the
live counterfactual files, or .env. The engine is isolated (_save monkeypatched
to a no-op) and the learner is backed by a throwaway temp dir.
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


# ── isolation helpers ────────────────────────────────────────────

def make_isolated_engine(rules):
    """Engine pre-loaded with the given rules, disk writes disabled."""
    eng = GraduatedRulesEngine()
    eng._loaded = True            # skip _ensure_loaded disk read
    eng._save = lambda: None      # monkeypatch disk write to no-op
    eng._rules = list(rules)
    return eng


def make_temp_learner():
    """CounterfactualLearner over a throwaway temp dir (real writes land there)."""
    d = tempfile.mkdtemp(prefix="veto_replay_")
    return CounterfactualLearner(data_dir=d), d


def wire_engine_singleton(engine):
    """Point the module-level get_graduated_rules_engine() at our isolated engine
    so counterfactual_learner.update_with_price resolves outcomes against IT,
    not the live singleton."""
    gr_mod._engine = engine
    gr_mod.get_graduated_rules_engine = lambda: engine


def new_veto_rule(rule_id, conditions, statement="auto"):
    return GraduatedRule(
        rule_id=rule_id,
        hypothesis_statement=statement if statement != "auto"
            else f"Never trade under {conditions}",
        action="veto",
        conditions=dict(conditions),
        active=True,
    )


# ── per-site drivers (mirror the EXACT recording call each site makes) ──

def drive_site1_ensemble(engine, cf, *, symbol, side, regime, strategy,
                         num_agree, confidence, entry, sl, tp1, tp2,
                         strategies_active):
    """ensemble.py ~595-617: full evaluate_signal, then record_veto_counterfactual
    with real entry/sl/tp1/tp2 (always has them — post-merge signal)."""
    vetoed, _conf, _summary, ids = engine.evaluate_signal(
        symbol=symbol, regime=regime, side=side, strategy=strategy,
        num_agree=num_agree, confidence=confidence,
        strategies_active=strategies_active,
    )
    if not vetoed:
        return None
    return cf.record_veto_counterfactual(
        symbol=symbol, side=side, entry_price=entry, sl=sl, tp1=tp1, tp2=tp2,
        confidence=confidence, veto_rule_ids=ids, strategy=strategy, regime=regime,
    )


def drive_site2_pipeline_gate1g(engine, cf, *, symbol, side, regime, num_agree,
                                confidence, hour_utc, strategies_active,
                                entry, sl, tp1, tp2, strategy=""):
    """signal_pipeline.py Gate 1g ~456-478: evaluate_signal with hour_utc +
    strategies_active, then record_veto_counterfactual (no denominator_only —
    Signal always carries entry/sl/tp1/tp2)."""
    vetoed, _conf, _applied, ids = engine.evaluate_signal(
        symbol=symbol, regime=regime, side=side, num_agree=num_agree,
        confidence=confidence, hour_utc=hour_utc,
        strategies_active=strategies_active,
    )
    if not vetoed:
        return None
    return cf.record_veto_counterfactual(
        symbol=symbol, side=side, entry_price=entry, sl=sl, tp1=tp1, tp2=tp2,
        confidence=confidence, veto_rule_ids=ids, strategy=strategy, regime=regime,
    )


def drive_site3_pre_llm_filter(engine, cf, *, symbol, side, confidence, hour_utc,
                               strategy, num_agree, strategies_active, regime,
                               entry, sl, tp1, tp2):
    """coordinator.py pre-LLM veto_only filter ~1633-1664: evaluate_signal(
    veto_only=True), then record_veto_counterfactual. denominator_only when
    entry/sl/tp1 missing (the exact guard the site uses)."""
    vetoed, _conf, _notes, ids = engine.evaluate_signal(
        symbol=symbol, side=side, confidence=confidence, strategy=strategy,
        num_agree=num_agree, hour_utc=hour_utc,
        strategies_active=strategies_active, veto_only=True,
    )
    if not vetoed:
        return None
    denom_only = not (entry > 0 and sl > 0 and tp1 > 0)
    return cf.record_veto_counterfactual(
        symbol=symbol, side=side, entry_price=entry, sl=sl, tp1=tp1, tp2=tp2,
        confidence=confidence, veto_rule_ids=ids, strategy=strategy, regime=regime,
        denominator_only=denom_only,
    )


def drive_site4_merge_veto(engine, cf, *, symbol, side, regime, strategy,
                           num_agree, confidence, entry, sl, tp1, tp2):
    """coordinator.py merge veto ~4853-4877: full evaluate_signal, then
    record_veto_counterfactual with the site's tp2-synthesis + denominator_only
    guard (compacted snapshots often omit sl/tp)."""
    vetoed, _conf, _notes, ids = engine.evaluate_signal(
        symbol=symbol, regime=regime, side=side, strategy=strategy,
        num_agree=num_agree, confidence=confidence,
    )
    if not vetoed:
        return None
    if tp2 <= 0 and entry > 0 and tp1 > 0:
        tp2 = entry + 2.0 * (tp1 - entry)  # mirror site-4 synthesis
    denom_only = not (entry > 0 and sl > 0 and tp1 > 0)
    return cf.record_veto_counterfactual(
        symbol=symbol, side=side, entry_price=entry, sl=sl, tp1=tp1, tp2=tp2,
        confidence=confidence, veto_rule_ids=ids, strategy=strategy, regime=regime,
        denominator_only=denom_only,
    )


# ── assertion harness ────────────────────────────────────────────

class Check:
    def __init__(self):
        self.results = []
        self.anomalies = []

    def ok(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        if not cond:
            self.anomalies.append(f"{name}: {detail}")
        return bool(cond)

    def invariant_correct_le_applied(self, engine, label):
        for r in engine._rules:
            self.ok(f"[{label}] times_correct<=times_applied ({r.rule_id})",
                    r.times_correct <= r.times_applied,
                    f"correct={r.times_correct} applied={r.times_applied}")
            self.ok(f"[{label}] accuracy in [0,1] ({r.rule_id})",
                    0.0 <= r.accuracy <= 1.0, f"acc={r.accuracy}")


def run():
    c = Check()
    per_site = {}

    # ============================================================
    # PART A — each site increments times_applied on its own rule,
    # losing counterfactual bumps times_correct via resolution.
    # ============================================================
    # One rule per site, conditioned on symbol+side only so every site
    # (incl. site 3 which passes no regime) matches.
    rules = [
        new_veto_rule("rule_site1", {"symbol": "ETH", "side": "BUY"}),
        new_veto_rule("rule_site2", {"symbol": "SOL", "side": "BUY"}),
        new_veto_rule("rule_site3", {"symbol": "BTC", "side": "BUY"}),
        new_veto_rule("rule_site4", {"symbol": "DOGE", "side": "BUY"}),
    ]
    engine = make_isolated_engine(rules)
    cf, _tmp = make_temp_learner()
    wire_engine_singleton(engine)
    by_id = {r.rule_id: r for r in engine._rules}

    # Site 1 — losing blocked trade (price falls through SL on a BUY).
    drive_site1_ensemble(engine, cf, symbol="ETH", side="BUY", regime="trend",
                         strategy="ensemble", num_agree=2, confidence=70.0,
                         entry=100.0, sl=95.0, tp1=110.0, tp2=120.0,
                         strategies_active=["regime_trend"])
    cf.update_with_price("ETH", high=100.0, low=94.0, close=94.0)
    r1 = by_id["rule_site1"]
    per_site[1] = (r1.times_applied, r1.times_correct)
    c.ok("site1 times_applied incremented", r1.times_applied == 1, f"applied={r1.times_applied}")
    c.ok("site1 losing CF bumped times_correct", r1.times_correct == 1, f"correct={r1.times_correct}")

    # Site 2 — losing blocked trade.
    drive_site2_pipeline_gate1g(engine, cf, symbol="SOL", side="BUY", regime="trend",
                                num_agree=2, confidence=70.0, hour_utc=12,
                                strategies_active=["regime_trend"],
                                entry=200.0, sl=190.0, tp1=220.0, tp2=240.0)
    cf.update_with_price("SOL", high=200.0, low=188.0, close=188.0)
    r2 = by_id["rule_site2"]
    per_site[2] = (r2.times_applied, r2.times_correct)
    c.ok("site2 times_applied incremented", r2.times_applied == 1, f"applied={r2.times_applied}")
    c.ok("site2 losing CF bumped times_correct", r2.times_correct == 1, f"correct={r2.times_correct}")

    # Site 3 — pre-LLM filter WITH entry/sl/tp1 present (resolvable, losing).
    drive_site3_pre_llm_filter(engine, cf, symbol="BTC", side="BUY", confidence=70.0,
                               hour_utc=12, strategy="ensemble", num_agree=2,
                               strategies_active=["regime_trend"], regime="trend",
                               entry=50000.0, sl=49000.0, tp1=52000.0, tp2=54000.0)
    cf.update_with_price("BTC", high=50000.0, low=48500.0, close=48500.0)
    r3 = by_id["rule_site3"]
    per_site[3] = (r3.times_applied, r3.times_correct)
    c.ok("site3 times_applied incremented", r3.times_applied == 1, f"applied={r3.times_applied}")
    c.ok("site3 losing CF bumped times_correct", r3.times_correct == 1, f"correct={r3.times_correct}")

    # Site 4 — merge veto, losing blocked trade.
    drive_site4_merge_veto(engine, cf, symbol="DOGE", side="BUY", regime="trend",
                           strategy="ensemble", num_agree=2, confidence=70.0,
                           entry=0.10, sl=0.095, tp1=0.11, tp2=0.12)
    cf.update_with_price("DOGE", high=0.10, low=0.094, close=0.094)
    r4 = by_id["rule_site4"]
    per_site[4] = (r4.times_applied, r4.times_correct)
    c.ok("site4 times_applied incremented", r4.times_applied == 1, f"applied={r4.times_applied}")
    c.ok("site4 losing CF bumped times_correct", r4.times_correct == 1, f"correct={r4.times_correct}")

    c.invariant_correct_le_applied(engine, "PART A")

    # ============================================================
    # PART B — denominator-loss regression: ALL FOUR sites fire on
    # the SAME rule. Every fire must count (no 3 uncounted paths).
    # ============================================================
    shared = new_veto_rule("rule_shared", {"symbol": "BTC", "side": "BUY"})
    engineB = make_isolated_engine([shared])
    cfB, _tmpB = make_temp_learner()
    wire_engine_singleton(engineB)

    # Distinct entries so decision_id de-dup does NOT collapse them.
    drive_site1_ensemble(engineB, cfB, symbol="BTC", side="BUY", regime="trend",
                         strategy="ensemble", num_agree=2, confidence=70.0,
                         entry=50000.0, sl=49000.0, tp1=52000.0, tp2=54000.0,
                         strategies_active=["regime_trend"])
    drive_site2_pipeline_gate1g(engineB, cfB, symbol="BTC", side="BUY", regime="trend",
                                num_agree=2, confidence=70.0, hour_utc=12,
                                strategies_active=["regime_trend"],
                                entry=50001.0, sl=49000.0, tp1=52000.0, tp2=54000.0)
    drive_site3_pre_llm_filter(engineB, cfB, symbol="BTC", side="BUY", confidence=70.0,
                               hour_utc=12, strategy="ensemble", num_agree=2,
                               strategies_active=["regime_trend"], regime="trend",
                               entry=50002.0, sl=49000.0, tp1=52000.0, tp2=54000.0)
    drive_site4_merge_veto(engineB, cfB, symbol="BTC", side="BUY", regime="trend",
                           strategy="ensemble", num_agree=2, confidence=70.0,
                           entry=50003.0, sl=49000.0, tp1=52000.0, tp2=54000.0)

    c.ok("B: all 4 sites counted on shared rule (no denominator loss)",
         shared.times_applied == 4,
         f"expected 4, got {shared.times_applied} -- THIS IS THE REVERTED BUG IF <4")
    pending_with_rule = [r for r in cfB._pending.values()
                         if "rule_shared" in (r.metadata.get("veto_rule_ids") or [])]
    c.ok("B: trackable CF population == denominator",
         len(pending_with_rule) == 4,
         f"pending={len(pending_with_rule)} vs applied={shared.times_applied}")
    c.invariant_correct_le_applied(engineB, "PART B")

    # ============================================================
    # PART C — overridden (LLM_FIRST) must NOT enter denominator OR
    # credit accuracy. record_skip with the overridden reason, NO stamp.
    # ============================================================
    ruleC = new_veto_rule("rule_override", {"symbol": "BTC", "side": "BUY"})
    engineC = make_isolated_engine([ruleC])
    cfC, _tmpC = make_temp_learner()
    wire_engine_singleton(engineC)
    # An override fires evaluate_signal (denominator counts the fire under the live
    # ensemble override branch too), but the recorded CF has NO veto_rule_ids.
    engineC.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)
    applied_before = ruleC.times_applied
    cfC.record_skip(symbol="BTC", side="BUY", entry_price=100.0, sl=95.0,
                    tp1=110.0, tp2=120.0, confidence=70.0,
                    skip_reason="graduated_rule_veto_overridden")
    cfC.update_with_price("BTC", high=100.0, low=94.0, close=94.0)  # would-be loss
    c.ok("C: overridden substring does NOT credit times_correct",
         ruleC.times_correct == 0, f"correct={ruleC.times_correct}")
    c.ok("C: overridden resolution did not touch denominator",
         ruleC.times_applied == applied_before,
         f"applied moved {applied_before}->{ruleC.times_applied}")

    # Also exercise the dedicated override counter path (separate bookkeeping).
    engineC.record_veto_overridden(["rule_override"], won=True)
    c.ok("C: override counters tracked separately (times_overridden)",
         ruleC.times_overridden == 1 and ruleC.overridden_correct == 1
         and ruleC.times_correct == 0,
         f"ov={ruleC.times_overridden} ovc={ruleC.overridden_correct} correct={ruleC.times_correct}")

    # ============================================================
    # PART D — winning blocked trade does NOT credit (veto was wrong).
    # ============================================================
    ruleD = new_veto_rule("rule_win", {"symbol": "BTC", "side": "BUY"})
    engineD = make_isolated_engine([ruleD])
    cfD, _tmpD = make_temp_learner()
    wire_engine_singleton(engineD)
    drive_site1_ensemble(engineD, cfD, symbol="BTC", side="BUY", regime="trend",
                         strategy="ensemble", num_agree=2, confidence=70.0,
                         entry=100.0, sl=95.0, tp1=110.0, tp2=120.0,
                         strategies_active=["regime_trend"])
    cfD.update_with_price("BTC", high=121.0, low=100.0, close=121.0)  # through TP2 = win
    c.ok("D: winning blocked trade does NOT credit times_correct",
         ruleD.times_correct == 0, f"correct={ruleD.times_correct}")
    c.ok("D: winning blocked trade still counted denominator",
         ruleD.times_applied == 1, f"applied={ruleD.times_applied}")
    c.invariant_correct_le_applied(engineD, "PART D")

    # ============================================================
    # PART E — denominator-only stub (site 3/4 missing SL/TP): row
    # exists, resolved unscored, NO accuracy change, denominator-only
    # records are NOT silently inflating sample (won=None).
    # ============================================================
    ruleE = new_veto_rule("rule_stub", {"symbol": "BTC", "side": "BUY"})
    engineE = make_isolated_engine([ruleE])
    cfE, _tmpE = make_temp_learner()
    wire_engine_singleton(engineE)
    rid = drive_site3_pre_llm_filter(engineE, cfE, symbol="BTC", side="BUY",
                                     confidence=70.0, hour_utc=12, strategy="ensemble",
                                     num_agree=2, strategies_active=["regime_trend"],
                                     regime="trend", entry=0.0, sl=0.0, tp1=0.0, tp2=0.0)
    resolved_stub = [r for r in cfE._resolved_recent
                     if "rule_stub" in (r.metadata.get("veto_rule_ids") or [])]
    c.ok("E: denominator-only stub written & resolved", bool(rid) and len(resolved_stub) == 1,
         f"rid={rid} resolved={len(resolved_stub)}")
    if resolved_stub:
        c.ok("E: stub resolved unscored (pnl None)",
             resolved_stub[0].hypothetical_pnl_pct is None,
             f"pnl={resolved_stub[0].hypothetical_pnl_pct}")
        c.ok("E: stub flagged cf_denominator_only",
             resolved_stub[0].metadata.get("cf_denominator_only") is True)
    c.ok("E: stub did NOT credit accuracy", ruleE.times_correct == 0,
         f"correct={ruleE.times_correct}")
    # Denominator still counted the fire (denominator-only != uncounted).
    c.ok("E: stub still counted denominator", ruleE.times_applied == 1,
         f"applied={ruleE.times_applied}")

    # ============================================================
    # PART F — de-dup: same would-be trade vetoed at TWO sites in one
    # cycle resolves once (no double-counting of the trackable CF).
    # ============================================================
    ruleF = new_veto_rule("rule_dedup", {"symbol": "BTC", "side": "BUY"})
    engineF = make_isolated_engine([ruleF])
    cfF, _tmpF = make_temp_learner()
    wire_engine_singleton(engineF)
    rid1 = drive_site1_ensemble(engineF, cfF, symbol="BTC", side="BUY", regime="trend",
                                strategy="ensemble", num_agree=2, confidence=70.0,
                                entry=100.0, sl=95.0, tp1=110.0, tp2=120.0,
                                strategies_active=["regime_trend"])
    rid2 = drive_site4_merge_veto(engineF, cfF, symbol="BTC", side="BUY", regime="trend",
                                  strategy="ensemble", num_agree=2, confidence=70.0,
                                  entry=100.0, sl=95.0, tp1=110.0, tp2=120.0)
    c.ok("F: same-trade two-site veto collapses to one CF row", rid1 == rid2,
         f"rid1={rid1} rid2={rid2}")
    pendF = [r for r in cfF._pending.values() if r.metadata.get("veto_rule_ids")]
    c.ok("F: one pending CF after dup", len(pendF) == 1, f"pending={len(pendF)}")
    # NOTE: times_applied legitimately == 2 here (the rule DID fire twice); de-dup is
    # on the CF tracking row, not the denominator. This is by design.
    c.ok("F: both fires counted in denominator (de-dup is CF-row only)",
         ruleF.times_applied == 2, f"applied={ruleF.times_applied}")

    # ============================================================
    # PART G — auto-retire on low veto accuracy (n>=10, acc<0.35).
    # ============================================================
    ruleG = new_veto_rule("rule_retire", {"symbol": "BTC", "side": "BUY"})
    engineG = make_isolated_engine([ruleG])
    wire_engine_singleton(engineG)
    for _ in range(10):
        engineG.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)
    for _ in range(2):
        engineG.record_veto_outcome(["rule_retire"], won=False)  # only 2 correct
    engineG.record_veto_outcome(["rule_retire"], won=True)        # re-check retire
    c.ok("G: low-accuracy veto auto-retires",
         (ruleG.times_applied == 10 and ruleG.accuracy < 0.35 and ruleG.active is False),
         f"applied={ruleG.times_applied} acc={ruleG.accuracy:.2f} active={ruleG.active}")

    # ── report ──
    passed = sum(1 for _, ok, _ in c.results if ok)
    total = len(c.results)
    print(f"\n{'='*64}")
    print(f"VETO REPLAY HARNESS — {passed}/{total} checks passed")
    print(f"{'='*64}")
    for name, ok, detail in c.results:
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name}"
        if not ok and detail:
            line += f"  <-- {detail}"
        print(line)
    print(f"\nPer-site times_applied/times_correct (PART A): {per_site}")
    print(f"PART B shared-rule denominator (expect 4): {engineB._rules[0].times_applied}")

    summary = {
        "checks_passed": passed,
        "checks_total": total,
        "per_site_part_a": {str(k): {"applied": v[0], "correct": v[1]}
                            for k, v in per_site.items()},
        "shared_rule_denominator_part_b": engineB._rules[0].times_applied,
        "anomalies": c.anomalies,
        "verdict": "safe-to-deploy" if passed == total else "needs-fix",
    }
    out_path = os.path.join(os.path.dirname(__file__), "veto_replay_report.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nReport written: {out_path}")
    print(f"VERDICT: {summary['verdict']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
