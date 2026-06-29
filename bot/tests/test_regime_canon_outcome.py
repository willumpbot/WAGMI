"""Rank-6 instrument fix: regime labels are canonicalized at outcome-record time so
named variants (trending_bull/trending_bear/trend) consolidate into one bucket
instead of fragmenting the per-regime WR table below the n>=13 graduation bar."""
import os
import pytest

from feedback.continuous_backtest import ContinuousBacktester


@pytest.fixture
def cb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("data/feedback", exist_ok=True)
    return ContinuousBacktester(data_dir="data/feedback")


def test_regime_canonicalized_at_write(cb):
    for rg in ("trending_bull", "trending_bear", "trend"):
        cb.record_outcome(symbol="BTC", win=False, pnl=-1.0,
                          confidence_at_entry=60.0, strategy="ensemble", regime=rg)
    regimes = {o["regime"] for o in cb._outcome_history}
    # All three variants must collapse to the single canonical "trend".
    assert regimes == {"trend"}, f"expected consolidation to 'trend', got {regimes}"


def test_blank_regime_preserved(cb):
    cb.record_outcome(symbol="ETH", win=True, pnl=1.0,
                      confidence_at_entry=50.0, strategy="ensemble", regime="")
    assert cb._outcome_history[-1]["regime"] == ""  # blank stays blank (capture is upstream)
