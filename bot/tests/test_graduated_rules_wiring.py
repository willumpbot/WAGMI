"""Tests for the graduated-rules accuracy-wiring fix (rank-1 instrument repair).

Bugs fixed:
1. SIDE-VOCAB CLASH: evaluate_signal is called with BUY/SELL but record_outcome is
   called at close with SHORT/LONG, so side-conditioned rules could never match at
   close -> times_correct stuck at 0 by construction (e.g. rule_4 ETH/SELL 4/0).
2. DENOMINATOR POPULATION MISMATCH: times_applied was bumped in evaluate_signal on
   EVERY scan match while times_correct only on close -> accuracy = closes/scans,
   meaningless (e.g. rule_10 BTC 3328/0). Now both counters are owned by record_outcome
   (paired increment, same population) mirroring the proven veto fix.
"""
import importlib
import pytest

import llm.graduated_rules as gr
from llm.graduated_rules import GraduatedRule, GraduatedRulesEngine, _canon_side


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # Redirect persistence to a temp file so we never touch the live rules json.
    monkeypatch.setattr(gr, "_RULES_FILE", str(tmp_path / "rules.json"))
    e = GraduatedRulesEngine()
    e._loaded = True  # skip disk load; we inject rules directly
    return e


def _penalize_rule(rid="r_pen", **cond):
    return GraduatedRule(rule_id=rid, action="penalize", conditions=cond, adjustment=-10.0,
                         hypothesis_statement="penalize test")


def _boost_rule(rid="r_boost", **cond):
    return GraduatedRule(rule_id=rid, action="boost", conditions=cond, adjustment=10.0,
                         hypothesis_statement="boost test")


def test_canon_side_maps_both_vocabularies():
    assert _canon_side("BUY") == _canon_side("LONG")
    assert _canon_side("SELL") == _canon_side("SHORT")
    assert _canon_side("LONG") != _canon_side("SHORT")


def test_side_conditioned_rule_credits_at_close(engine):
    """The core fix: a side='SELL' rule must credit when the close passes side='SHORT'."""
    rule = _penalize_rule(symbol="SOL", regime="consolidation", side="SELL")
    engine._rules = [rule]
    # Close vocabulary is SHORT/LONG (event.side); penalize is "correct" on a loss.
    engine.record_outcome(symbol="SOL", regime="consolidation", side="SHORT", won=False)
    assert rule.times_applied == 1, "side-conditioned rule must match at close (SHORT==SELL)"
    assert rule.times_correct == 1, "penalize rule is correct on a loss"


def test_evaluate_signal_does_not_bump_applied(engine):
    """Paired-increment: scanning must NOT inflate the denominator (no scan-spam)."""
    rule = _penalize_rule(symbol="SOL", side="SELL")
    engine._rules = [rule]
    # Simulate many scan-time evaluations (ensemble vocab BUY/SELL).
    for _ in range(50):
        engine.evaluate_signal(symbol="SOL", regime="consolidation", side="SELL",
                               num_agree=2, confidence=60.0)
    assert rule.times_applied == 0, "evaluate_signal must not bump times_applied anymore"
    # Only a real close moves the denominator.
    engine.record_outcome(symbol="SOL", regime="consolidation", side="SHORT", won=False)
    assert rule.times_applied == 1


def test_single_close_credits_exactly_once(engine):
    """One record_outcome call = exactly one applied increment (no double-count)."""
    rule = _penalize_rule(symbol="BTC")
    engine._rules = [rule]
    engine.record_outcome(symbol="BTC", regime="trend", side="SHORT", won=False)
    assert rule.times_applied == 1 and rule.times_correct == 1


def test_boost_correct_only_on_win(engine):
    rule = _boost_rule(symbol="ETH", side="BUY")
    engine._rules = [rule]
    engine.record_outcome(symbol="ETH", regime="trend", side="LONG", won=True)
    assert rule.times_applied == 1 and rule.times_correct == 1  # boost correct on win
    engine.record_outcome(symbol="ETH", regime="trend", side="LONG", won=False)
    assert rule.times_applied == 2 and rule.times_correct == 1  # loss: applied++ only


def test_accuracy_is_finite_and_bounded(engine):
    rule = _penalize_rule(symbol="SOL")
    engine._rules = [rule]
    for won in (False, False, True, False):  # 3 losses (penalize correct), 1 win
        engine.record_outcome(symbol="SOL", regime="range", side="SHORT", won=won)
    assert rule.times_applied == 4
    assert rule.times_correct == 3
    assert 0.0 <= rule.accuracy <= 1.0
    assert abs(rule.accuracy - 0.75) < 1e-9
