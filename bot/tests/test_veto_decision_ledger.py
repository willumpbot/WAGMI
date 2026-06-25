"""
Tests for the unified VETO decision-ledger that makes graduated VETO rules
self-measuring.

Background: graduated veto rules accumulated times_applied (3120 uses) but
times_correct stayed 0 forever, making them de-facto permanent hardcoded blocks.
record_outcome() skipped every veto rule (`if action=="veto": continue`) and the
ONE wired path re-matched on regime/symbol/side (lossy). The fix:
  - evaluate_signal() now returns the matched veto rule_ids as a 4th element.
  - record_veto_counterfactual() stamps metadata["veto_rule_ids"] + decision_id.
  - record_veto_outcome(rule_ids, won) credits times_correct by rule_id
    (won=False -> blocked trade would have LOST -> veto correct).
  - update_with_price resolves the stamped ids (gate on the stamp, not the
    skip_reason string — excludes 'graduated_rule_veto_overridden').

DENOMINATOR-LEAK FIX (2026-06): times_applied for VETO rules is owned EXCLUSIVELY by
record_veto_outcome() (the paired record path), NOT by evaluate_signal(). A veto fire
that is never recorded is simply UNMEASURED and can never inflate the denominator —
this makes the 5th caller (ensemble.evaluate_raw, rule_ids discarded into '_') and any
future caller leak-proof by construction. applied & correct therefore always describe
the SAME population. won=None is fully unscored (touches neither counter).

These tests prove:
  1. evaluate_signal returns veto rule_ids but does NOT bump times_applied.
  2. record_veto_outcome bumps applied (denominator) AND credits correct only on a
     losing blocked trade; won=None touches neither counter.
  3. A resolving losing counterfactual bumps applied+correct; a winning one bumps
     only applied; an unrecorded evaluate_signal veto changes nothing.
  4. The overridden substring (graduated_rule_veto_overridden, no stamp) does NOT
     credit accuracy.
  5. times_correct never exceeds times_applied (true by construction now).
  6. All FOUR veto sites return the rule_id; applied is driven ONLY by recorded
     outcomes, never by the raw evaluate_signal fire.
  7. Site-4 denominator-only fallback writes a stub without crediting accuracy.
  8. Auto-retire fires for a veto with n>=10 and accuracy<0.35.
  9. De-dup: same would-be trade vetoed at two sites resolves once, MERGING rule_ids.
"""

import os
import sys
import time
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.graduated_rules import GraduatedRulesEngine, GraduatedRule
from llm.counterfactual_learner import CounterfactualLearner


# ── Helpers ──────────────────────────────────────────────────────

def _make_engine_with_veto(rule_id="veto_test_1", symbol="SOL", regime="panic",
                           side="BUY"):
    """Engine with a single active veto rule, no file loading."""
    engine = GraduatedRulesEngine()
    engine._loaded = True
    engine._save = lambda: None  # don't touch disk
    rule = GraduatedRule(
        rule_id=rule_id,
        hypothesis_statement=f"Never {side} {symbol} in {regime} regime",
        action="veto",
        conditions={"symbol": symbol, "regime": regime, "side": side},
        active=True,
    )
    engine._rules = [rule]
    return engine, rule


def _make_cf_learner():
    """CounterfactualLearner backed by a fresh temp dir."""
    d = tempfile.mkdtemp()
    return CounterfactualLearner(data_dir=d)


# ── 1. evaluate_signal returns rule_ids but does NOT bump times_applied ──

def test_evaluate_signal_returns_veto_rule_ids_without_bumping_applied():
    engine, rule = _make_engine_with_veto()
    assert rule.times_applied == 0
    vetoed, conf, summary, veto_ids = engine.evaluate_signal(
        symbol="SOL", regime="panic", side="BUY", confidence=80.0
    )
    assert vetoed is True
    assert veto_ids == [rule.rule_id]
    # LEAK FIX: the raw veto fire is UNMEASURED until an outcome is recorded.
    assert rule.times_applied == 0


def test_unrecorded_evaluate_signal_veto_never_inflates_denominator():
    """The 5th-site class (evaluate_raw discards rule_ids): firing the veto many
    times WITHOUT recording an outcome must leave times_applied at zero."""
    engine, rule = _make_engine_with_veto()
    for _ in range(25):
        v, _, _, ids = engine.evaluate_signal(
            symbol="SOL", regime="panic", side="BUY", confidence=80.0
        )
        assert v is True and ids == [rule.rule_id]
    assert rule.times_applied == 0  # no recorded outcomes -> no denominator
    assert rule.times_correct == 0


def test_evaluate_signal_no_match_returns_empty_ids():
    engine, rule = _make_engine_with_veto()
    vetoed, conf, summary, veto_ids = engine.evaluate_signal(
        symbol="ETH", regime="trend", side="BUY", confidence=80.0
    )
    assert vetoed is False
    assert veto_ids == []
    assert rule.times_applied == 0


def test_record_veto_outcome_owns_the_denominator():
    """times_applied is driven SOLELY by record_veto_outcome, independent of how
    many times evaluate_signal fired the veto."""
    engine, rule = _make_engine_with_veto()
    # Fire 10x without recording -> still zero.
    for _ in range(10):
        engine.evaluate_signal(symbol="SOL", regime="panic", side="BUY", confidence=80.0)
    assert rule.times_applied == 0
    # Now record 3 resolved outcomes -> denominator == 3 (the measured population).
    engine.record_veto_outcome([rule.rule_id], won=False)
    engine.record_veto_outcome([rule.rule_id], won=True)
    engine.record_veto_outcome([rule.rule_id], won=False)
    assert rule.times_applied == 3
    assert rule.times_correct == 2


# ── 2/3. record_veto_outcome numerator semantics ────────────────

def test_record_veto_outcome_credits_only_on_loss():
    engine, rule = _make_engine_with_veto()
    # evaluate_signal does NOT move counters anymore.
    engine.evaluate_signal(symbol="SOL", regime="panic", side="BUY", confidence=80.0)
    assert rule.times_applied == 0 and rule.times_correct == 0

    # Blocked trade would have LOST -> veto correct -> applied+1, correct+1.
    engine.record_veto_outcome([rule.rule_id], won=False)
    assert rule.times_applied == 1 and rule.times_correct == 1

    # Blocked trade would have WON -> veto wrong -> applied+1, correct unchanged.
    engine.record_veto_outcome([rule.rule_id], won=True)
    assert rule.times_correct == 1  # unchanged
    assert rule.times_applied == 2  # denominator still counts the resolved fire


def test_record_veto_outcome_none_is_fully_unscored():
    engine, rule = _make_engine_with_veto()
    engine.evaluate_signal(symbol="SOL", regime="panic", side="BUY", confidence=80.0)
    engine.record_veto_outcome([rule.rule_id], won=None)
    # Unscored: touches NEITHER counter (no possible numerator -> no denominator).
    assert rule.times_correct == 0
    assert rule.times_applied == 0


def test_accuracy_clamped_zero_to_one():
    engine, rule = _make_engine_with_veto()
    rule.times_applied = 5
    rule.times_correct = 99  # corrupt counter
    assert 0.0 <= rule.accuracy <= 1.0
    assert rule.accuracy == 1.0


# ── 4. Counterfactual resolution wiring (losing -> credit) ──────

def test_losing_counterfactual_credits_veto_via_resolution(monkeypatch):
    engine, rule = _make_engine_with_veto(symbol="BTC", regime="trend", side="BUY")
    # Engine fires once -> denominator = 1.
    engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)

    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)

    cf = _make_cf_learner()
    # Stamp the veto record (entry above SL; price will fall to SL = a loss).
    cf.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0, tp2=120.0,
        confidence=70.0, veto_rule_ids=[rule.rule_id],
    )
    # Drive price down through SL -> blocked BUY would have lost.
    cf.update_with_price("BTC", high=100.0, low=94.0, close=94.0)

    assert rule.times_applied == 1  # denominator credited on resolution
    assert rule.times_correct == 1  # losing blocked trade -> veto correct


def test_winning_counterfactual_does_not_credit_veto(monkeypatch):
    engine, rule = _make_engine_with_veto(symbol="BTC", regime="trend", side="BUY")
    engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)

    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)

    cf = _make_cf_learner()
    cf.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0, tp2=120.0,
        confidence=70.0, veto_rule_ids=[rule.rule_id],
    )
    # Drive price up through TP2 -> blocked BUY would have WON.
    cf.update_with_price("BTC", high=121.0, low=100.0, close=121.0)

    assert rule.times_applied == 1  # denominator still counts the resolved fire
    assert rule.times_correct == 0  # winning blocked trade -> veto wrong, no credit


# ── 5. Overridden substring bug regression ──────────────────────

def test_overridden_record_does_not_credit_accuracy(monkeypatch):
    """A record with skip_reason='graduated_rule_veto_overridden' and NO
    veto_rule_ids must NOT call record_veto_outcome (the trade was not blocked)."""
    engine, rule = _make_engine_with_veto(symbol="BTC", regime="trend", side="BUY")
    engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)

    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)

    cf = _make_cf_learner()
    # Plain skip via record_skip with the OVERRIDDEN reason and no stamp.
    cf.record_skip(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0, tp2=120.0,
        confidence=70.0, skip_reason="graduated_rule_veto_overridden",
    )
    # Resolve as a loss — the old substring guard would have credited this.
    cf.update_with_price("BTC", high=100.0, low=94.0, close=94.0)

    assert rule.times_correct == 0  # stamp-gated: override never touches accuracy


# ── times_correct never exceeds times_applied ───────────────────

def test_times_correct_never_exceeds_times_applied():
    engine, rule = _make_engine_with_veto()
    # applied & correct are now the same population BY CONSTRUCTION — every correct
    # credit is paired with an applied credit inside record_veto_outcome, so correct
    # can never exceed applied no matter how evaluate_signal is called.
    for _ in range(3):
        engine.evaluate_signal(symbol="SOL", regime="panic", side="BUY", confidence=80.0)
        engine.record_veto_outcome([rule.rule_id], won=False)
    assert rule.times_correct <= rule.times_applied
    assert rule.times_correct == 3 and rule.times_applied == 3


# ── 6. All five sites return the rule_id; denominator is leak-proof ─

def test_all_sites_return_rule_id_but_only_recorded_outcomes_count(monkeypatch):
    """Fire the SAME veto rule via each call site (incl. the 5th leaky site that
    discards rule_ids). Every site RETURNS the rule_id, but the raw fires NEVER move
    times_applied — only paired record_veto_outcome calls do."""
    # Rule conditions on symbol+side only — satisfiable by ALL sites, including the
    # pre-LLM filter (site 3) which does not pass regime.
    engine = GraduatedRulesEngine()
    engine._loaded = True
    engine._save = lambda: None
    rule = GraduatedRule(
        rule_id="veto_allsites_1",
        hypothesis_statement="Never BUY BTC",
        action="veto",
        conditions={"symbol": "BTC", "side": "BUY"},
        active=True,
    )
    engine._rules = [rule]
    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)
    monkeypatch.setattr(gr, "_engine", engine, raising=False)

    # Site 1: ensemble path (full evaluate_signal)
    v1, _, _, ids1 = engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY",
                                            confidence=70.0)
    # Site 2: signal_pipeline Gate 1g (with hour_utc + strategies_active)
    v2, _, _, ids2 = engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY",
                                            num_agree=2, confidence=70.0, hour_utc=12,
                                            strategies_active=["regime_trend"])
    # Site 3: coordinator pre-LLM veto_only filter
    v3, _, _, ids3 = engine.evaluate_signal(symbol="BTC", side="BUY", confidence=70.0,
                                            hour_utc=12, veto_only=True)
    # Site 4: coordinator merge veto
    v4, _, _, ids4 = engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY",
                                            confidence=70.0)
    # Site 5: ensemble.evaluate_raw — the leaky site (discards rule_ids into '_').
    v5, _, _, ids5 = engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY",
                                            confidence=70.0)

    assert v1 and v2 and v3 and v4 and v5
    assert ids1 == ids2 == ids3 == ids4 == ids5 == [rule.rule_id]
    # FIVE fires, ZERO recorded outcomes -> denominator stays 0. Leak eliminated:
    # the 5th site can no longer inflate the denominator even though it records nothing.
    assert rule.times_applied == 0

    # Only the sites that actually record an outcome move the denominator.
    engine.record_veto_outcome([rule.rule_id], won=False)  # site 1 resolved
    engine.record_veto_outcome([rule.rule_id], won=False)  # site 2 resolved
    assert rule.times_applied == 2
    assert rule.times_correct == 2


def test_denominator_equals_recorded_population(monkeypatch):
    """times_applied == count of resolved CF records carrying that rule_id
    (denominator == measured population, never the raw-fire count)."""
    engine, rule = _make_engine_with_veto(symbol="BTC", regime="trend", side="BUY")
    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)

    cf = _make_cf_learner()
    # Each site fires + records a CF with a distinct decision_id (distinct entry).
    for entry in [100.0, 101.0, 102.0, 103.0]:
        engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)
        cf.record_veto_counterfactual(
            symbol="BTC", side="BUY", entry_price=entry, sl=entry - 5, tp1=entry + 10,
            tp2=entry + 20, confidence=70.0, veto_rule_ids=[rule.rule_id],
        )

    # Before resolution: 4 pending, denominator still 0 (nothing measured yet).
    pending_with_rule = [r for r in cf._pending.values()
                         if rule.rule_id in r.metadata.get("veto_rule_ids", [])]
    assert len(pending_with_rule) == 4
    assert rule.times_applied == 0

    # Resolve all 4 (each drops to SL -> a loss -> veto correct).
    for entry in [100.0, 101.0, 102.0, 103.0]:
        cf.update_with_price("BTC", high=entry, low=entry - 6, close=entry - 6)
    assert rule.times_applied == 4   # denominator == resolved population
    assert rule.times_correct == 4


# ── 7. Site-4 denominator-only fallback ─────────────────────────

def test_denominator_only_stub_no_accuracy_change(monkeypatch):
    engine, rule = _make_engine_with_veto(symbol="BTC", regime="trend", side="BUY")
    engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)

    import llm.graduated_rules as gr
    monkeypatch.setattr(gr, "get_graduated_rules_engine", lambda: engine)

    cf = _make_cf_learner()
    # SL/TP missing -> denominator-only stub. Row must exist, resolved, won=None.
    rid = cf.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=0.0, sl=0.0, tp1=0.0, tp2=0.0,
        confidence=70.0, veto_rule_ids=[rule.rule_id], denominator_only=True,
    )
    assert rid
    resolved = [r for r in cf._resolved_recent
                if rule.rule_id in r.metadata.get("veto_rule_ids", [])]
    assert len(resolved) == 1
    assert resolved[0].resolved is True
    assert resolved[0].hypothetical_pnl_pct is None
    assert resolved[0].metadata.get("cf_denominator_only") is True
    assert rule.times_correct == 0  # unscored


# ── 8. Veto auto-retire ─────────────────────────────────────────

def test_veto_auto_retires_on_low_accuracy():
    engine, rule = _make_engine_with_veto()
    # 10 recorded outcomes, only 2 correct -> accuracy 0.2 < 0.35 -> retire.
    # applied is now driven entirely by record_veto_outcome (paired with correct).
    engine.record_veto_outcome([rule.rule_id], won=False)  # +applied +correct
    engine.record_veto_outcome([rule.rule_id], won=False)  # +applied +correct
    for _ in range(8):
        engine.record_veto_outcome([rule.rule_id], won=True)  # +applied only
    assert rule.times_applied == 10
    assert rule.times_correct == 2
    assert rule.accuracy < 0.35
    assert rule.active is False


# ── 9. De-dup ───────────────────────────────────────────────────

def test_dedup_same_decision_id_resolves_once():
    cf = _make_cf_learner()
    # Same symbol/side/entry vetoed twice in one cycle -> one pending row.
    rid1 = cf.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0, tp2=120.0,
        confidence=70.0, veto_rule_ids=["veto_a"],
    )
    rid2 = cf.record_veto_counterfactual(
        symbol="BTC", side="BUY", entry_price=100.0, sl=95.0, tp1=110.0, tp2=120.0,
        confidence=70.0, veto_rule_ids=["veto_b"],
    )
    assert rid1 == rid2  # dup collapsed onto the first record
    pending = [r for r in cf._pending.values() if r.metadata.get("veto_rule_ids")]
    assert len(pending) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
