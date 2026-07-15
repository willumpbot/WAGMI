"""Capacity eviction must not fabricate resolved-0 counterfactual outcomes."""
import pytest

from llm.counterfactual_learner import CounterfactualLearner


@pytest.fixture
def learner(tmp_path):
    return CounterfactualLearner(data_dir=str(tmp_path))


def _skip(l, i):
    return l.record_skip(
        symbol="SOL", side="BUY", entry_price=100.0 + i,
        sl=95.0, tp1=105.0, tp2=110.0, confidence=70.0,
        skip_reason="test",
    )


def test_eviction_is_unscored_not_zero(learner):
    learner.MAX_PENDING = 3
    for i in range(5):
        _skip(learner, i)
    evicted = [r for r in learner._resolved_recent
               if r.metadata.get("cf_evicted_unresolved")]
    assert len(evicted) == 2
    for r in evicted:
        assert r.hypothetical_pnl_pct is None


def test_evicted_records_excluded_from_stats(learner):
    learner.MAX_PENDING = 2
    for i in range(6):
        _skip(learner, i)
    # All resolved records are evictions -> no scored outcomes -> no fake losers
    stats = learner.get_missed_opportunity_stats()
    assert stats["total_skips"] == 0


def test_legacy_fake_zero_filtered_by_is_scored(learner):
    rid = _skip(learner, 0)
    rec = learner._pending[rid]
    rec.resolved = True
    rec.hypothetical_pnl_pct = 0.0  # legacy eviction signature
    rec.bars_to_resolve = 5
    assert learner._is_scored(rec) is False
